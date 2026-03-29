# fraud.spec.md — Fraud Detection Module Specification
## Cycle-Safe Referral Engine v1.0

---

## Feature: Real-Time Fraud Detection & Prevention

### Goal
Detect and prevent fraudulent referral activity in real time. The fraud engine operates as a synchronous pre-flight gate on every referral claim AND as an asynchronous pattern analysis service that continuously monitors for suspicious behavior that only becomes apparent across multiple events over time.

---

## Requirements

### Functional
- FR-F-01: Block self-referrals immediately with fraud record creation
- FR-F-02: Block cycle-forming referrals with fraud record creation
- FR-F-03: Enforce per-user referral velocity limits (sliding window rate limiting)
- FR-F-04: Detect duplicate IP address registrations within a time window
- FR-F-05: Detect duplicate device fingerprints registering in bulk
- FR-F-06: Detect and flag suspicious referral velocity from a single referrer (too many in short time)
- FR-F-07: Flag accounts with >X% rejection rate as suspicious
- FR-F-08: Support manual review workflow for fraud events
- FR-F-09: Provide fraud reason on every rejected referral
- FR-F-10: Support configurable fraud thresholds via admin API

### Non-Functional
- NFR-F-01: All synchronous fraud checks must complete in <20ms
- NFR-F-02: Async pattern analysis must not block referral processing
- NFR-F-03: Fraud records must be immutable once written
- NFR-F-04: False positive rate target: <0.1% of legitimate referrals blocked

---

## API Contract

### GET /api/v1/fraud/events

**Query:** `?page=1&limit=20&reason=CYCLE_DETECTED&reviewed=false&severity=3`

**Response 200:**
```json
{
  "success": true,
  "data": {
    "events": [
      {
        "id": "uuid",
        "user": { "id": "uuid", "username": "charlie" },
        "referral_id": "uuid",
        "reason": "CYCLE_DETECTED",
        "severity": 3,
        "metadata": {
          "attempted_referrer_id": "uuid",
          "cycle_path_length": 3,
          "ip_address": "203.0.113.10"
        },
        "reviewed": false,
        "created_at": "2026-03-29T10:00:00Z"
      }
    ],
    "pagination": { "page": 1, "limit": 20, "total": 38 }
  }
}
```

---

### PATCH /api/v1/fraud/events/{event_id}/review (Admin only)

**Request:**
```json
{
  "reviewed": true,
  "review_notes": "Confirmed fraud attempt — account suspended",
  "action": "SUSPEND_USER"
}
```

**Response 200:**
```json
{
  "success": true,
  "data": {
    "event_id": "uuid",
    "reviewed": true,
    "action_taken": "SUSPEND_USER"
  }
}
```

---

### GET /api/v1/fraud/stats

**Response 200:**
```json
{
  "success": true,
  "data": {
    "total_fraud_events": 1247,
    "by_reason": {
      "SELF_REFERRAL":        310,
      "CYCLE_DETECTED":        89,
      "VELOCITY_EXCEEDED":    512,
      "DUPLICATE_IP":         198,
      "DUPLICATE_DEVICE":      92,
      "SUSPICIOUS_PATTERN":    46
    },
    "unreviewed_high_severity": 12,
    "fraud_rate_7d": 0.034
  }
}
```

---

### GET /api/v1/fraud/config (Admin only)

**Response 200:**
```json
{
  "success": true,
  "data": {
    "velocity_limits": {
      "attempts_per_minute_per_user": 3,
      "attempts_per_hour_per_user": 10,
      "referrals_per_hour_per_referrer": 50
    },
    "duplicate_detection": {
      "same_ip_window_minutes": 60,
      "same_ip_max_registrations": 3,
      "same_device_window_minutes": 60,
      "same_device_max_registrations": 2
    },
    "rejection_rate_threshold": 0.5,
    "auto_suspend_on_cycle": false
  }
}
```

---

## Data Model

### PostgreSQL

```sql
CREATE TABLE fraud_events (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id         UUID NOT NULL REFERENCES users(id),
  referral_id     UUID REFERENCES referrals(id),
  -- NULL for pre-referral checks (velocity before referral created)
  reason          fraud_reason NOT NULL,
  metadata        JSONB NOT NULL DEFAULT '{}',
  severity        SMALLINT NOT NULL DEFAULT 1 CHECK (severity BETWEEN 1 AND 3),
  -- 1=low (velocity), 2=medium (dup IP/device), 3=high (cycle, self-referral)
  reviewed        BOOLEAN NOT NULL DEFAULT FALSE,
  review_notes    TEXT,
  reviewed_by     UUID REFERENCES users(id),
  reviewed_at     TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
  -- Immutable: no UPDATE allowed except review fields
);

CREATE TABLE fraud_config (
  id                              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  -- Velocity
  attempts_per_minute_per_user    SMALLINT NOT NULL DEFAULT 3,
  attempts_per_hour_per_user      SMALLINT NOT NULL DEFAULT 10,
  referrals_per_hour_per_referrer SMALLINT NOT NULL DEFAULT 50,
  -- Duplicate detection
  same_ip_window_minutes          INTEGER NOT NULL DEFAULT 60,
  same_ip_max_registrations       SMALLINT NOT NULL DEFAULT 3,
  same_device_window_minutes      INTEGER NOT NULL DEFAULT 60,
  same_device_max_registrations   SMALLINT NOT NULL DEFAULT 2,
  -- Behavioral
  rejection_rate_threshold        NUMERIC(4,3) NOT NULL DEFAULT 0.5,
  auto_suspend_on_cycle           BOOLEAN NOT NULL DEFAULT FALSE,
  -- Only one active config
  is_active                       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_one_active_fraud_config
  ON fraud_config (is_active) WHERE is_active = TRUE;

CREATE INDEX idx_fraud_user      ON fraud_events(user_id);
CREATE INDEX idx_fraud_reason    ON fraud_events(reason);
CREATE INDEX idx_fraud_severity  ON fraud_events(severity);
CREATE INDEX idx_fraud_reviewed  ON fraud_events(reviewed) WHERE reviewed = FALSE;
CREATE INDEX idx_fraud_created   ON fraud_events(created_at DESC);
```

### Redis Keys

```
# Per-user attempt velocity (sliding window)
Key: fraud:velocity:{user_id}:minute:{epoch_minute}
Type: String (INCR)
TTL: 120s
Value: count of referral attempts in this minute window

Key: fraud:velocity:{user_id}:hour:{epoch_hour}
Type: String (INCR)
TTL: 7200s
Value: count of referral attempts in this hour window

# Per-referrer output velocity (how many people they referred recently)
Key: fraud:referrer_velocity:{referrer_id}:hour:{epoch_hour}
Type: String (INCR)
TTL: 7200s

# IP registration tracking
Key: fraud:ip_reg:{ip_hash}:{window_hour}
Type: String (INCR)
TTL: 7200s

# Device registration tracking
Key: fraud:device_reg:{device_hash}:{window_hour}
Type: String (INCR)
TTL: 7200s

# Flagged users (fast lookup: is this user suspended?)
Key: fraud:flagged:{user_id}
Type: String (1 = flagged)
TTL: No expiry (cleared on manual review)
```

---

## Business Logic

### Fraud Check Pipeline

The fraud engine runs checks in priority order. Each check is a distinct concern. Early exit on first failure minimizes latency.

```python
class FraudEngine:
    
    async def pre_flight_check(
        self,
        user_id: str,
        referral_code: str,
        ip_address: str,
        device_hash: str
    ) -> FraudCheckResult:
        """
        Synchronous pre-flight checks. Must complete <20ms total.
        Called BEFORE any database writes.
        """
        
        config = await self.load_config()  # Redis-cached, TTL=300s
        
        # ─── Check 1: Is user flagged/suspended? ─────────────────
        if await self.is_user_flagged(user_id):
            return FraudCheckResult(
                blocked=True,
                reason=FraudReason.SUSPICIOUS_PATTERN,
                severity=3
            )

        # ─── Check 2: Attempt velocity (per user, sliding window) ─
        minute_count = await self.increment_and_check(
            f"fraud:velocity:{user_id}:minute:{epoch_minute()}",
            ttl=120,
            threshold=config.attempts_per_minute_per_user
        )
        if minute_count > config.attempts_per_minute_per_user:
            await self.record_fraud_event(
                user_id=user_id,
                reason=FraudReason.VELOCITY_EXCEEDED,
                severity=1,
                metadata={"window": "minute", "count": minute_count}
            )
            return FraudCheckResult(
                blocked=True,
                reason=FraudReason.VELOCITY_EXCEEDED,
                severity=1,
                retry_after=60
            )

        hour_count = await self.increment_and_check(
            f"fraud:velocity:{user_id}:hour:{epoch_hour()}",
            ttl=7200,
            threshold=config.attempts_per_hour_per_user
        )
        if hour_count > config.attempts_per_hour_per_user:
            await self.record_fraud_event(
                user_id=user_id,
                reason=FraudReason.VELOCITY_EXCEEDED,
                severity=2,
                metadata={"window": "hour", "count": hour_count}
            )
            return FraudCheckResult(
                blocked=True,
                reason=FraudReason.VELOCITY_EXCEEDED,
                severity=2,
                retry_after=3600
            )

        # ─── Check 3: IP duplicate registration ───────────────────
        if ip_address:
            ip_hash = hash_ip(ip_address)
            ip_count = await redis.get(f"fraud:ip_reg:{ip_hash}:{epoch_hour()}")
            if int(ip_count or 0) >= config.same_ip_max_registrations:
                await self.record_fraud_event(
                    user_id=user_id,
                    reason=FraudReason.DUPLICATE_IP,
                    severity=2,
                    metadata={"ip_hash": ip_hash, "count": ip_count}
                )
                # Non-blocking: log but don't reject (configurable)
                # Default: record + allow, but flag for review

        # ─── Check 4: Device duplicate registration ───────────────
        if device_hash:
            device_count = await redis.get(
                f"fraud:device_reg:{device_hash}:{epoch_hour()}"
            )
            if int(device_count or 0) >= config.same_device_max_registrations:
                await self.record_fraud_event(
                    user_id=user_id,
                    reason=FraudReason.DUPLICATE_DEVICE,
                    severity=2,
                    metadata={"device_hash": device_hash}
                )
                # Non-blocking by default; severity determines auto-action

        return FraudCheckResult(blocked=False)
    
    
    async def record_cycle_fraud(
        self,
        user_id: str,
        referrer_id: str,
        metadata: dict
    ) -> str:
        """Called by referral service when cycle is detected."""
        config = await self.load_config()
        
        event_id = await self.record_fraud_event(
            user_id=user_id,
            reason=FraudReason.CYCLE_DETECTED,
            severity=3,
            metadata={
                "attempted_referrer_id": referrer_id,
                **metadata
            }
        )
        
        if config.auto_suspend_on_cycle:
            await self.suspend_user(user_id, reason="AUTO_SUSPEND_CYCLE")
        
        return event_id
    
    
    async def record_self_referral_fraud(
        self,
        user_id: str
    ) -> str:
        return await self.record_fraud_event(
            user_id=user_id,
            reason=FraudReason.SELF_REFERRAL,
            severity=3,
            metadata={"type": "self_referral"}
        )
```

### Async Pattern Analysis (Background Service)

Runs every 5 minutes via Celery beat. Detects patterns not visible in single-event checks.

```python
async def analyze_rejection_rates():
    """
    Find users whose referral rejection rate exceeds threshold.
    High rejection rate = account may be probing for cycle vulnerabilities
    or mass-attempting fraudulent referrals.
    """
    config = await load_fraud_config()
    
    # Find users with ≥10 referral attempts and high rejection rate
    suspicious_users = await db.fetch("""
        SELECT
            r.referrer_id AS user_id,
            COUNT(*) AS total_attempts,
            SUM(CASE WHEN r.status IN ('REJECTED','FRAUD') THEN 1 ELSE 0 END) AS bad_count,
            CAST(
                SUM(CASE WHEN r.status IN ('REJECTED','FRAUD') THEN 1 ELSE 0 END) AS FLOAT
            ) / COUNT(*) AS rejection_rate
        FROM referrals r
        WHERE r.created_at > NOW() - INTERVAL '24 hours'
        GROUP BY r.referrer_id
        HAVING COUNT(*) >= 10
           AND CAST(
                SUM(CASE WHEN r.status IN ('REJECTED','FRAUD') THEN 1 ELSE 0 END) AS FLOAT
               ) / COUNT(*) > $1
    """, config.rejection_rate_threshold)
    
    for user in suspicious_users:
        existing = await db.fetchval("""
            SELECT id FROM fraud_events
            WHERE user_id = $1 AND reason = 'SUSPICIOUS_PATTERN'
              AND created_at > NOW() - INTERVAL '1 hour'
        """, user['user_id'])
        
        if not existing:
            await record_fraud_event(
                user_id=user['user_id'],
                reason=FraudReason.SUSPICIOUS_PATTERN,
                severity=2,
                metadata={
                    "rejection_rate": user['rejection_rate'],
                    "total_attempts": user['total_attempts'],
                    "window": "24h"
                }
            )
```

### Severity Classification

```
Severity 1 (LOW) → Log only, no action
  - Single velocity limit breach (1 attempt over per minute)

Severity 2 (MEDIUM) → Flag for review, may alert ops
  - Sustained velocity breaches
  - Duplicate IP/device
  - High rejection rate

Severity 3 (HIGH) → Immediate action possible (if configured)
  - CYCLE_DETECTED
  - SELF_REFERRAL
  - Known fraud pattern match
```

---

## Edge Cases

| Case | Handling |
|---|---|
| Redis down during velocity check | Fail-open: allow request, log Redis failure, alert ops |
| Fraud config not loaded (PG down) | Use in-memory hardcoded defaults as fallback |
| Legitimate user hitting velocity limit (burst) | Config tuning; exponential backoff UX guidance |
| VPN/proxy detected | IP check is a signal, not a hard block by default |
| Two users on same household IP | `same_ip_max_registrations` is configurable; default=3 |
| Fraud event insert fails | Log and continue; referral rejection still processed |
| Manual review marks false positive | `reviewed=true`, `review_notes` recorded; no auto-unsuspend |
| Suspended user tries to claim referral | Blocked at `is_user_flagged()` check (Redis lookup) |

---

## Constraints

- C-F-01: Fraud event records are append-only; no delete or update except review fields
- C-F-02: CYCLE_DETECTED and SELF_REFERRAL are always severity 3
- C-F-03: Fraud checks must not add >20ms to referral claim latency
- C-F-04: All fraud thresholds must be configurable without code deployment
- C-F-05: A single fraud event must never block legitimate users (log-and-allow for ambiguous signals)

---

## Acceptance Criteria

- AC-F-01: Self-referral attempt creates fraud event with reason=SELF_REFERRAL, severity=3
- AC-F-02: Cycle attempt creates fraud event with reason=CYCLE_DETECTED, severity=3
- AC-F-03: 4th referral attempt in 1 minute returns VELOCITY_EXCEEDED (429) with retry_after
- AC-F-04: 3 registrations from same IP in 1 hour creates DUPLICATE_IP fraud event
- AC-F-05: Fraud events list endpoint returns paginated results filterable by reason and reviewed
- AC-F-06: Admin can mark fraud event as reviewed with notes
- AC-F-07: User suspended via auto_suspend_on_cycle cannot claim future referrals
- AC-F-08: Background pattern analysis runs every 5 minutes and creates SUSPICIOUS_PATTERN events for high-rejection-rate users
- AC-F-09: All synchronous fraud checks complete in <20ms P99
