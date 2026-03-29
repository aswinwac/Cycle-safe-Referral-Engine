# referral.spec.md — Referral Module Specification
## Cycle-Safe Referral Engine v1.0

---

## Feature: DAG-Safe Referral Edge Management

### Goal
Manage directed referral edges between users while **guaranteeing** the referral graph remains a DAG at all times. This is the most performance-critical and correctness-critical module in the system. Every referral claim must complete in <100ms while atomically preventing cycles across concurrent requests.

---

## Requirements

### Functional
- FR-R-01: Accept referral claims and create directed edges (child → parent) in the graph
- FR-R-02: Reject any referral that would create a cycle (real-time, <100ms)
- FR-R-03: Reject self-referrals immediately (O(1) check)
- FR-R-04: Enforce one referrer per user globally
- FR-R-05: Provide referral status retrieval (PENDING, VALID, REJECTED, FRAUD)
- FR-R-06: Support listing referrals made by a user (downline) with pagination
- FR-R-07: Emit structured events for every referral outcome
- FR-R-08: Support admin override for referral investigation

### Non-Functional
- NFR-R-01: Cycle detection must complete in <100ms P99
- NFR-R-02: System must handle 1000 concurrent referral claims without deadlock
- NFR-R-03: No cycle must ever be created under any concurrency scenario
- NFR-R-04: Graph state in Neo4j must always match PG referrals table (eventual consistency <5s)

---

## API Contract

### POST /api/v1/referrals/claim

**Purpose:** A registered user claims a referral using a referral code. This is the core transactional endpoint.

**Auth:** JWT required (claimant = JWT subject)

**Request:**
```json
{
  "referral_code": "ALICE-7F3K",
  "ip_address": "203.0.113.10",
  "device_hash": "abc123def456"
}
```

**Response 201 (success):**
```json
{
  "success": true,
  "data": {
    "referral": {
      "id": "uuid",
      "referrer_id": "uuid",
      "referrer_username": "alice_wonder",
      "referred_id": "uuid",
      "status": "VALID",
      "created_at": "2026-03-29T10:00:00Z"
    },
    "rewards_triggered": true,
    "reward_job_id": "uuid"
  }
}
```

**Response 409 (cycle detected):**
```json
{
  "success": false,
  "error": {
    "code": "CYCLE_DETECTED",
    "message": "This referral would create a cycle in the referral graph",
    "details": {
      "fraud_event_id": "uuid",
      "marked_as": "FRAUD"
    }
  }
}
```

**Response 400 (self-referral):**
```json
{
  "success": false,
  "error": {
    "code": "SELF_REFERRAL",
    "message": "You cannot use your own referral code",
    "details": { "fraud_event_id": "uuid" }
  }
}
```

**Response 409 (already has referrer):**
```json
{
  "success": false,
  "error": {
    "code": "DUPLICATE_REFERRAL",
    "message": "User already has a referrer"
  }
}
```

**Response 429 (rate limited):**
```json
{
  "success": false,
  "error": {
    "code": "VELOCITY_EXCEEDED",
    "message": "Too many referral attempts. Try again later.",
    "details": { "retry_after_seconds": 60 }
  }
}
```

---

### GET /api/v1/referrals/{referral_id}

**Response 200:**
```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "referrer": { "id": "uuid", "username": "alice" },
    "referred": { "id": "uuid", "username": "carol" },
    "status": "VALID",
    "depth": 1,
    "fraud_reason": null,
    "created_at": "2026-03-29T10:00:00Z",
    "resolved_at": "2026-03-29T10:00:00.045Z"
  }
}
```

---

### GET /api/v1/referrals/by-user/{user_id}

**Query params:** `?role=referrer|referred&status=VALID&page=1&limit=20`

**Response 200:**
```json
{
  "success": true,
  "data": {
    "referrals": [...],
    "pagination": {
      "page": 1,
      "limit": 20,
      "total": 142,
      "has_next": true
    }
  }
}
```

---

## Data Model

### PostgreSQL
```sql
CREATE TABLE referrals (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  referrer_id     UUID NOT NULL REFERENCES users(id),
  referred_id     UUID NOT NULL REFERENCES users(id),
  status          referral_status NOT NULL DEFAULT 'PENDING',
  depth           SMALLINT NOT NULL DEFAULT 1,
  ip_address      INET,
  device_hash     VARCHAR(64),
  fraud_reason    fraud_reason,
  fraud_metadata  JSONB DEFAULT '{}',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at     TIMESTAMPTZ,

  -- Business constraints
  CONSTRAINT no_self_referral CHECK (referrer_id != referred_id),
  CONSTRAINT unique_referred   UNIQUE (referred_id)
  -- Each user can only BE referred once
);

CREATE INDEX idx_referrals_referrer  ON referrals(referrer_id);
CREATE INDEX idx_referrals_referred  ON referrals(referred_id);
CREATE INDEX idx_referrals_status    ON referrals(status);
CREATE INDEX idx_referrals_created   ON referrals(created_at DESC);
CREATE INDEX idx_referrals_ip        ON referrals(ip_address);
```

### Neo4j Graph Model

```
Edge direction: (referred:User)-[:REFERRED]->(referrer:User)

Properties on [:REFERRED] edge:
  - referral_id: UUID (FK to PG referrals.id)
  - created_at: datetime
  - depth: integer
```

**Visual example:**
```
Alice refers Bob, Bob refers Carol, Carol refers Dave:

(Bob)   -[:REFERRED]-> (Alice)
(Carol) -[:REFERRED]-> (Bob)
(Dave)  -[:REFERRED]-> (Carol)

Graph: Bob → Alice, Carol → Bob, Dave → Carol

If Dave tries to refer Alice:
  Need to check: is Dave reachable from Alice via REFERRED* ?
  Alice -> Bob -> Carol -> Dave ✓ path exists → CYCLE → REJECT
```

### Redis Keys

```
# Ancestor set cache
Key: ancestors:{user_id}
Type: Set (Redis SADD / SISMEMBER)
Value: set of all ancestor user IDs
TTL: 60s
Populated on: cache miss during cycle check

# Referral velocity counter (sliding window)
Key: referral_velocity:{user_id}:{window_minute}
Type: String (INCR)
TTL: 120s (2 windows retained)
Purpose: max N referral attempts per minute per user

# Distributed lock
Key: referral_lock:{user_id}
Type: String (SETNX with expiry)
TTL: 500ms
Purpose: Prevent concurrent referral claims for same user
```

---

## Business Logic

### 🔥 Cycle Detection Algorithm (Full Specification)

```
PROBLEM:
Given a DAG G = (V, E) where edges represent referral relationships,
when adding a new edge (new_user → referrer), determine if this edge
would create a cycle.

A cycle exists iff there is already a path referrer →* new_user.
(i.e., referrer is a descendant of new_user)

ALGORITHM: 3-Layer Detection with Redis + Neo4j DFS
```

#### Layer 1: Self-referral (O(1))
```python
if new_user_id == referrer_id:
    raise SelfReferralError()
```

#### Layer 2: Existing referrer check (O(1), PG)
```python
existing = await db.fetchval(
    "SELECT referrer_id FROM users WHERE id = $1", new_user_id
)
if existing is not None:
    raise DuplicateReferralError()
```

#### Layer 3: Redis Ancestor Cache (O(1) amortized)
```python
cache_key = f"ancestors:{referrer_id}"
is_descendant = await redis.sismember(cache_key, new_user_id)

if is_descendant:
    # referrer is a descendant of new_user → CYCLE
    raise CycleDetectedError()
```

#### Layer 4: Neo4j DFS (O(V+E), <5ms typical)
```cypher
-- Check if a path exists from referrer to new_user
-- following REFERRED edges (upward in our model means following child→parent)
-- We need to check if new_user can reach referrer going DOWN (parent→child)
-- Equivalently: can referrer reach new_user going UP (child→parent)?

MATCH path = (referrer:User {id: $referrer_id})-[:REFERRED*1..50]->(target:User {id: $new_user_id})
RETURN COUNT(path) > 0 AS cycle_exists
LIMIT 1
```

**Why LIMIT 1?** We only need to know if ANY path exists. Return immediately on first match.

**Depth limit `*1..50`:** Prevents unbounded traversal on malicious/deep graphs. A legitimate referral tree rarely exceeds 20 levels; 50 is a safe upper bound.

**If cycle found in Neo4j:**
```python
# Populate Redis cache for future O(1) lookups
ancestors = await neo4j.get_all_ancestors(referrer_id)
await redis.sadd(f"ancestors:{referrer_id}", *ancestors)
await redis.expire(f"ancestors:{referrer_id}", 60)

raise CycleDetectedError()
```

#### Full Referral Claim Flow

```python
async def claim_referral(new_user_id: str, referral_code: str, ...):
    
    # ── Step 1: Fraud pre-checks (synchronous, fast) ──────────────
    await fraud_service.check_velocity(new_user_id)     # raises if limit hit
    await fraud_service.check_device(device_hash)       # raises if device flagged

    # ── Step 2: Resolve referral code ─────────────────────────────
    referrer_id = await user_service.resolve_code(referral_code)
    if not referrer_id:
        raise InvalidCodeError()

    # ── Step 3: Layer 1 + 2 cycle checks ──────────────────────────
    if new_user_id == referrer_id:
        await fraud_service.record(new_user_id, SELF_REFERRAL)
        raise SelfReferralError()

    existing_referrer = await db.get_user_referrer(new_user_id)
    if existing_referrer:
        raise DuplicateReferralError()

    # ── Step 4: Acquire distributed lock ──────────────────────────
    lock_key = f"referral_lock:{new_user_id}"
    async with redis_lock(lock_key, ttl=500, timeout=200) as lock:
        if not lock.acquired:
            raise LockTimeoutError()

        # ── Step 5: Layer 3 - Redis ancestor cache check ──────────
        cache_key = f"ancestors:{referrer_id}"
        if await redis.sismember(cache_key, new_user_id):
            await fraud_service.record(new_user_id, CYCLE_DETECTED, referrer_id)
            raise CycleDetectedError()

        # ── Step 6: Layer 4 - Neo4j DFS (authoritative) ───────────
        cycle_exists = await neo4j.check_path_exists(
            from_id=referrer_id,    # can referrer reach new_user?
            to_id=new_user_id,      # going up the tree
            max_depth=50
        )
        
        if cycle_exists:
            # Warm Redis cache to prevent repeat DFS for same pair
            ancestors = await neo4j.get_all_ancestor_ids(referrer_id)
            await redis.sadd(cache_key, *ancestors, new_user_id)
            await redis.expire(cache_key, 60)
            
            await fraud_service.record(new_user_id, CYCLE_DETECTED, referrer_id)
            raise CycleDetectedError()

        # ── Step 7: Dual-write (PG + Neo4j) ───────────────────────
        referral_id = uuid4()
        
        async with db.transaction():
            # 7a. Insert referral record (PENDING)
            await db.execute("""
                INSERT INTO referrals (id, referrer_id, referred_id, status, ...)
                VALUES ($1, $2, $3, 'PENDING', ...)
            """, referral_id, referrer_id, new_user_id, ...)

            # 7b. Update user's referrer_id
            await db.execute("""
                UPDATE users SET referrer_id = $1, updated_at = NOW()
                WHERE id = $2
            """, referrer_id, new_user_id)

        # 7c. Create Neo4j edge (outside PG transaction)
        try:
            await neo4j.create_referral_edge(
                child_id=new_user_id,
                parent_id=referrer_id,
                referral_id=referral_id
            )
        except Neo4jError as e:
            # Compensate: undo PG writes
            await db.execute("UPDATE referrals SET status='REJECTED' ... WHERE id=$1", referral_id)
            await db.execute("UPDATE users SET referrer_id=NULL WHERE id=$1", new_user_id)
            log.error("Neo4j edge creation failed", referral_id=referral_id, error=str(e))
            raise GraphWriteError()

        # 7d. Mark referral as VALID
        await db.execute("""
            UPDATE referrals SET status='VALID', resolved_at=NOW() WHERE id=$1
        """, referral_id)

        # ── Step 8: Cache invalidation ─────────────────────────────
        # Invalidate ancestor caches for new_user and all its descendants
        # (they now have referrer_id and all its ancestors as ancestors too)
        await invalidate_descendant_caches(new_user_id)

        # ── Step 9: Async reward distribution ─────────────────────
        await reward_queue.enqueue(ReferralRewardJob(
            referral_id=referral_id,
            referred_id=new_user_id,
            referrer_id=referrer_id
        ))

        # ── Step 10: Emit event ────────────────────────────────────
        await events.emit(REFERRAL_CREATED, {
            "referral_id": str(referral_id),
            "referrer_id": referrer_id,
            "referred_id": new_user_id
        })

    return ReferralResult(referral_id=referral_id, status=VALID)
```

### Cache Invalidation Strategy

When a new edge is created `(new_user → referrer)`:

```python
async def invalidate_descendant_caches(new_user_id: str):
    """
    Any node that has new_user as an ancestor now also has
    referrer (and all of referrer's ancestors) as ancestors.
    We must invalidate their ancestor caches.
    
    Strategy: Delete all descendant ancestor caches.
    They'll be lazily repopulated on next access.
    """
    # Get all descendants of new_user in Neo4j
    descendant_ids = await neo4j.execute("""
        MATCH (u:User)-[:REFERRED*]->(root:User {id: $user_id})
        RETURN u.id AS descendant_id
    """, user_id=new_user_id)
    
    keys = [f"ancestors:{did}" for did in descendant_ids]
    keys.append(f"ancestors:{new_user_id}")
    
    if keys:
        await redis.delete(*keys)
```

### Neo4j Cypher Queries (Production)

```cypher
-- Create edge
MERGE (child:User {id: $child_id})
MERGE (parent:User {id: $parent_id})
CREATE (child)-[:REFERRED {
  referral_id: $referral_id,
  created_at: datetime()
}]->(parent)

-- Cycle check (authoritative)
MATCH (r:User {id: $referrer_id}), (n:User {id: $new_user_id})
RETURN EXISTS((r)-[:REFERRED*1..50]->(n)) AS cycle_exists

-- Get all ancestor IDs (for cache population)
MATCH (start:User {id: $user_id})-[:REFERRED*1..]->(ancestor:User)
RETURN COLLECT(ancestor.id) AS ancestor_ids

-- Get referral tree downward (for dashboard)
MATCH path = (root:User {id: $user_id})<-[:REFERRED*1..$depth]-(descendant:User)
RETURN path

-- Shortest path between two users (admin debugging)
MATCH (a:User {id: $user_a}), (b:User {id: $user_b})
RETURN shortestPath((a)-[:REFERRED*]-(b))
```

---

## Concurrency Handling

### Race Condition Scenario

```
Time    Thread A (Carol → Alice)    Thread B (Alice → Carol)
────────────────────────────────────────────────────────────
T+0ms   Check: Alice→Carol? NO      Check: Carol→Alice? NO
T+5ms   (both pass cycle check)     (both pass cycle check)
T+6ms   Acquire lock on Carol...    Acquire lock on Alice...
T+7ms   Lock acquired               Lock acquired
T+8ms   Create (Carol→Alice)        Create (Alice→Carol)  ← CYCLE!
```

**Prevention: User-scoped lock on `referred_id`**

Since each user can only have ONE referrer (UNIQUE constraint on `referred_id`), we lock on `new_user_id`:

```
Lock key: referral_lock:{new_user_id}
```

This means: only ONE referral claim for a given user can be in-flight at a time. Thread B's lock acquisition for a _different_ user (different `new_user_id`) is fine — there's no race between Carol→Alice and Alice→Carol if both new_users are different.

Wait — in the scenario above: Thread A claims Carol as referred; Thread B claims Alice as referred. These have different lock keys, so both proceed. This is the real race.

**Correct prevention: Re-check inside lock + PG unique constraint**

```python
# After lock acquired:
# 1. Re-run cycle check (Neo4j DFS) — definitive
# 2. PG UNIQUE constraint on referred_id provides final safety net
#    If both somehow pass, PG INSERT will fail for second one → 409 returned
```

The combination of:
1. Distributed lock (prevents concurrent claims for the **same** user)
2. Re-check inside lock (prevents race between A→B and B→A)
3. PG UNIQUE constraint (bulletproof final guard)

...makes cycles impossible under any concurrency pattern.

---

## Edge Cases

| Case | Handling |
|---|---|
| Referrer account suspended | Allow claim; fraud service will evaluate |
| Referral code used in same second by 100 users | Lock ensures serial processing per `referred_id` |
| Neo4j returns timeout on DFS | Treat as cycle_exists=TRUE (fail-safe); log; alert |
| Redis lock service down | Fall back to PG advisory lock: `pg_try_advisory_lock($user_id_hash)` |
| Referral created but reward job fails | Reward job retries independently; referral is already VALID |
| Admin manually removes edge from Neo4j | Reconciliation job detects PG/Neo4j divergence, alerts |
| User with 10,000 descendants claims referral | DFS limited to depth 50; cache population batched |
| Duplicate claim request (same user, same code) | UNIQUE constraint on referred_id catches; return 409 |
| Referrer deleted after claim in-flight | FK ON DELETE SET NULL in PG; Neo4j edge retained |

---

## Constraints

- C-R-01: A user MUST have at most one referrer (enforced at PG and application level)
- C-R-02: Self-referral is ALWAYS rejected (CHECK constraint + application logic)
- C-R-03: Cycle detection MUST be authoritative; false negatives are unacceptable
- C-R-04: Cycle detection MUST complete in <100ms P99
- C-R-05: Every rejection MUST create a fraud event record
- C-R-06: Neo4j and PostgreSQL referral state MUST converge within 5 seconds
- C-R-07: Graph depth traversal limit: 50 hops (configurable via env var)

---

## Acceptance Criteria

- AC-R-01: Valid referral (A refers B, no cycle) creates PG record + Neo4j edge + reward job
- AC-R-02: B→A attempt after A→B is already stored returns CYCLE_DETECTED (409)
- AC-R-03: Self-referral returns SELF_REFERRAL (400) in <5ms
- AC-R-04: 100 concurrent referral claims for different users all complete without deadlock
- AC-R-05: Two concurrent claims for the same user_id result in exactly one success
- AC-R-06: Cycle detection via Redis cache returns result in <10ms on cache hit
- AC-R-07: Cycle detection via Neo4j DFS completes in <50ms on a 100k-node graph
- AC-R-08: After any referral claim, `GET /referrals/{id}` reflects correct status within 100ms
- AC-R-09: Load test: 500 RPS sustained for 60 seconds, zero cycles created, P99 <100ms
