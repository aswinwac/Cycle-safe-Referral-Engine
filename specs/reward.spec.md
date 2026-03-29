# reward.spec.md — Reward Module Specification
## Cycle-Safe Referral Engine v1.0

---

## Feature: Multi-Level Reward Propagation

### Goal
When a valid referral is created, propagate configurable rewards upward through the DAG — from the newly referred user to their referrer, then the referrer's referrer, and so on — up to a configurable depth. Rewards are calculated per-level using either a fixed amount or a percentage-based model. All reward operations are idempotent, auditable, and safe against duplicate processing.

---

## Requirements

### Functional
- FR-RW-01: Trigger reward distribution on every VALID referral creation
- FR-RW-02: Walk up the DAG from the referred user, awarding each ancestor up to configured depth
- FR-RW-03: Support PERCENTAGE and FIXED reward types
- FR-RW-04: Support per-level reward configuration (level 1 = 10%, level 2 = 5%, level 3 = 2%)
- FR-RW-05: Reward distribution must be idempotent (duplicate job = no duplicate rewards)
- FR-RW-06: Only distribute rewards if referral graph remains acyclic (validated before reward)
- FR-RW-07: Support multiple active reward configs (A/B testing, campaigns)
- FR-RW-08: Provide reward ledger per user (what was earned, when, why)
- FR-RW-09: Support reward status lifecycle: PENDING → ISSUED → PAID / CANCELLED

### Non-Functional
- NFR-RW-01: Reward distribution is async (non-blocking on referral claim)
- NFR-RW-02: Distribution job must complete within 2 seconds for depth-3 propagation
- NFR-RW-03: Jobs must be retried on failure (max 3 retries with exponential backoff)
- NFR-RW-04: Total rewards issued must be queryable with <100ms response time

---

## API Contract

### GET /api/v1/rewards/ledger/{user_id}

**Query:** `?page=1&limit=20&status=ISSUED`

**Response 200:**
```json
{
  "success": true,
  "data": {
    "user_id": "uuid",
    "total_earned": 245.75,
    "pending": 10.00,
    "rewards": [
      {
        "id": "uuid",
        "referral_id": "uuid",
        "trigger_user": { "id": "uuid", "username": "dave" },
        "level": 1,
        "reward_type": "PERCENTAGE",
        "amount": 15.00,
        "status": "ISSUED",
        "issued_at": "2026-03-29T10:05:00Z"
      }
    ],
    "pagination": { "page": 1, "limit": 20, "total": 42 }
  }
}
```

---

### GET /api/v1/rewards/config

**Response 200:**
```json
{
  "success": true,
  "data": {
    "active_config": {
      "id": "uuid",
      "name": "Standard Q1 2026",
      "max_depth": 3,
      "reward_type": "PERCENTAGE",
      "level_configs": [
        { "level": 1, "value": 10.0 },
        { "level": 2, "value": 5.0 },
        { "level": 3, "value": 2.0 }
      ],
      "is_active": true
    }
  }
}
```

---

### POST /api/v1/rewards/config (Admin only)

**Request:**
```json
{
  "name": "Summer Campaign 2026",
  "max_depth": 2,
  "reward_type": "FIXED",
  "level_configs": [
    { "level": 1, "value": 20.00 },
    { "level": 2, "value": 5.00 }
  ]
}
```

---

### GET /api/v1/rewards/summary

**Response 200 (dashboard consumption):**
```json
{
  "success": true,
  "data": {
    "total_rewards_issued": 14523,
    "total_amount_distributed": 284750.50,
    "pending_amount": 1240.00,
    "by_level": [
      { "level": 1, "count": 8200, "amount": 164000.00 },
      { "level": 2, "count": 4100, "amount": 82000.00 },
      { "level": 3, "count": 2223, "amount": 38750.50 }
    ]
  }
}
```

---

## Data Model

### PostgreSQL

```sql
CREATE TABLE reward_config (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name            VARCHAR(100) NOT NULL,
  max_depth       SMALLINT NOT NULL DEFAULT 3 CHECK (max_depth BETWEEN 1 AND 10),
  reward_type     reward_type NOT NULL DEFAULT 'PERCENTAGE',
  level_configs   JSONB NOT NULL,
  -- Validated: array of {level: int, value: numeric}, levels must be 1..max_depth
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by      UUID REFERENCES users(id)
);

-- Enforces only one active config at a time
CREATE UNIQUE INDEX idx_one_active_config
  ON reward_config (is_active)
  WHERE is_active = TRUE;

CREATE TABLE rewards (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  referral_id     UUID NOT NULL REFERENCES referrals(id),
  recipient_id    UUID NOT NULL REFERENCES users(id),
  trigger_user_id UUID NOT NULL REFERENCES users(id),
  -- trigger_user = the newly referred user who caused this reward
  level           SMALLINT NOT NULL CHECK (level >= 1),
  reward_type     reward_type NOT NULL,
  amount          NUMERIC(12,4) NOT NULL CHECK (amount > 0),
  config_id       UUID NOT NULL REFERENCES reward_config(id),
  status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
  -- PENDING | ISSUED | PAID | CANCELLED | FAILED
  issued_at       TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- Idempotency: one reward per referral per recipient per level
  CONSTRAINT unique_reward_per_level
    UNIQUE (referral_id, recipient_id, level)
);

CREATE INDEX idx_rewards_recipient  ON rewards(recipient_id);
CREATE INDEX idx_rewards_referral   ON rewards(referral_id);
CREATE INDEX idx_rewards_status     ON rewards(status);
CREATE INDEX idx_rewards_created    ON rewards(created_at DESC);
CREATE INDEX idx_rewards_trigger    ON rewards(trigger_user_id);
```

---

## Business Logic

### Reward Propagation Algorithm

```
TRIGGER: Valid referral created → async job enqueued

INPUT:
  - referral_id: the new referral
  - referred_id: the new user (leaf node)
  - referrer_id: their direct referrer (level 1)

ALGORITHM: Upward DAG Walk

1. Load active reward config (cached in Redis, TTL=300s)
2. Initialize: current_node = referrer_id, level = 1
3. Loop while level <= config.max_depth AND current_node exists:
   a. Calculate reward amount for this level
   b. INSERT reward record (idempotent via UNIQUE constraint)
   c. Move up: current_node = current_node.referrer_id
   d. level++
4. Mark all PENDING rewards as ISSUED
5. Emit REWARD_ISSUED events for each reward
```

**Python implementation:**

```python
async def distribute_rewards(
    referral_id: str,
    referred_id: str,
    referrer_id: str
) -> List[RewardRecord]:
    
    # Idempotency guard: check if rewards already exist for this referral
    existing = await db.fetchval(
        "SELECT COUNT(*) FROM rewards WHERE referral_id = $1", referral_id
    )
    if existing > 0:
        log.warning("Reward distribution already done", referral_id=referral_id)
        return []  # idempotent exit

    # Load config (Redis cache → PG fallback)
    config = await load_active_config()
    
    rewards_created = []
    current_node_id = referrer_id
    level = 1

    async with db.transaction():
        while level <= config.max_depth and current_node_id:
            
            # Calculate reward for this level
            amount = calculate_reward(config, level, base_amount=100.0)
            # base_amount is configurable; for FIXED type, it's ignored
            
            # Create reward (UNIQUE constraint makes this idempotent)
            try:
                reward = await db.fetchrow("""
                    INSERT INTO rewards (
                        id, referral_id, recipient_id, trigger_user_id,
                        level, reward_type, amount, config_id, status
                    ) VALUES (
                        uuid_generate_v4(), $1, $2, $3, $4, $5, $6, $7, 'PENDING'
                    )
                    ON CONFLICT (referral_id, recipient_id, level) DO NOTHING
                    RETURNING *
                """, referral_id, current_node_id, referred_id,
                     level, config.reward_type, amount, config.id)
                
                if reward:
                    rewards_created.append(reward)

            except Exception as e:
                log.error("Reward insert failed", level=level, error=str(e))
                raise

            # Move up the tree
            current_node_id = await db.fetchval(
                "SELECT referrer_id FROM users WHERE id = $1", current_node_id
            )
            level += 1

        # Bulk mark as ISSUED
        referral_ids = [r['id'] for r in rewards_created]
        if referral_ids:
            await db.execute("""
                UPDATE rewards
                SET status = 'ISSUED', issued_at = NOW()
                WHERE id = ANY($1::uuid[])
            """, referral_ids)

    # Emit events outside transaction
    for reward in rewards_created:
        await events.emit(REWARD_ISSUED, {
            "reward_id": str(reward['id']),
            "recipient_id": str(reward['recipient_id']),
            "amount": float(reward['amount']),
            "level": reward['level']
        })

    return rewards_created
```

### Reward Calculation

```python
def calculate_reward(
    config: RewardConfig,
    level: int,
    base_amount: float = 100.0
) -> Decimal:
    """
    PERCENTAGE: amount = base_amount * (level_value / 100)
      Level 1 = 10% of 100 = 10.00
      Level 2 = 5%  of 100 = 5.00
      Level 3 = 2%  of 100 = 2.00

    FIXED: amount = level_value directly
      Level 1 = 20.00
      Level 2 = 5.00
    """
    level_cfg = next(
        (lc for lc in config.level_configs if lc['level'] == level),
        None
    )
    if not level_cfg:
        return Decimal('0')

    if config.reward_type == RewardType.PERCENTAGE:
        return Decimal(str(base_amount)) * Decimal(str(level_cfg['value'])) / 100
    else:  # FIXED
        return Decimal(str(level_cfg['value']))
```

### Example Propagation

```
Graph:  Dave → Carol → Bob → Alice

Dave registers via Carol's referral code.
Active config: depth=3, PERCENTAGE, L1=10%, L2=5%, L3=2%, base=100

Rewards created:
  Level 1: Carol  receives 10.00  (direct referrer)
  Level 2: Bob    receives  5.00  (Carol's referrer)
  Level 3: Alice  receives  2.00  (Bob's referrer)

Total distributed: 17.00 for this single referral event.
```

### Async Job Architecture

```
Celery task: distribute_referral_rewards
Queue: rewards (dedicated, lower priority than referral queue)
Retry: 3 attempts, backoff: [5s, 30s, 300s]
Dead letter: rewards_dlq (manual review)
Deduplication: task ID = f"reward_{referral_id}" (idempotent task key)
```

---

## Edge Cases

| Case | Handling |
|---|---|
| Referrer has no referrer (root node) | Walk stops naturally when `referrer_id IS NULL` |
| No active reward config | Log warning, skip distribution, alert ops team |
| Reward job runs twice (duplicate delivery) | `ON CONFLICT DO NOTHING` + idempotency guard |
| Recipient suspended | Reward still created (ISSUED); payout logic checks status |
| Config changes between claim and reward job | Job uses config_id captured at referral time (immutable) |
| Very deep tree (50 ancestors) | max_depth config limits loop; no runaway processing |
| Overflow: base_amount * percentage | Decimal arithmetic (not float); enforced precision NUMERIC(12,4) |
| Referral marked FRAUD after reward issued | Batch job cancels associated PENDING rewards; ISSUED untouched |

---

## Constraints

- C-RW-01: Rewards are only issued for VALID referrals, never REJECTED or FRAUD
- C-RW-02: Maximum reward propagation depth: 10 levels (configurable, hard limit)
- C-RW-03: Reward amounts must use Decimal arithmetic (no floating point)
- C-RW-04: Duplicate rewards for same (referral, recipient, level) are silently ignored
- C-RW-05: Only one reward config may be active at any time
- C-RW-06: Reward distribution is always async; referral claim must not wait for it

---

## Acceptance Criteria

- AC-RW-01: Valid referral creates rewards for all ancestors up to configured depth
- AC-RW-02: Reward amounts match configured level values exactly (decimal precision)
- AC-RW-03: Running the reward job twice for the same referral produces exactly the same reward set (idempotent)
- AC-RW-04: Reward job completes within 2 seconds for depth-3 propagation
- AC-RW-05: Ledger endpoint returns accurate totals with correct pagination
- AC-RW-06: Root user (no referrer) receives level-1 reward; nobody above receives anything (no referrer)
- AC-RW-07: Changing reward config does not affect already-queued jobs
- AC-RW-08: FRAUD-marked referrals do not trigger reward distribution
