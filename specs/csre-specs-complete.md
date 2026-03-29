--- global.spec.md ---

# global.spec.md — Cycle-Safe Referral Engine
## System-Wide Architecture Specification

---

## 1. Project Overview

**System Name:** Cycle-Safe Referral Engine (CSRE)  
**Version:** 1.0.0  
**Classification:** Production-Grade, Backend-Heavy, Graph-Based SaaS  
**Scale Target:** 10M+ users, 50M+ referral edges, 10k+ TPS peak

The CSRE is a referral management platform that models users and their referral relationships as a **Directed Acyclic Graph (DAG)**. The system enforces strict acyclicity at the graph level, propagates multi-level rewards, and detects fraudulent referral patterns in real time.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          CLIENT LAYER                           │
│   React Dashboard (SPA)  ←→  WebSocket (live events)           │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS / WSS
┌────────────────────────────▼────────────────────────────────────┐
│                         API GATEWAY                             │
│   FastAPI Application Server  (Uvicorn + Gunicorn workers)      │
│   Rate Limiting | Auth Middleware | Request Tracing             │
└──────┬──────────────┬──────────────┬────────────────┬───────────┘
       │              │              │                │
┌──────▼──────┐ ┌─────▼──────┐ ┌────▼─────┐ ┌───────▼──────────┐
│  User       │ │  Referral  │ │  Reward  │ │  Fraud           │
│  Service    │ │  Service   │ │  Service │ │  Detection Svc   │
└──────┬──────┘ └─────┬──────┘ └────┬─────┘ └───────┬──────────┘
       │              │              │                │
┌──────▼──────────────▼──────────────▼────────────────▼──────────┐
│                       DATA LAYER                                │
│                                                                 │
│  ┌─────────────────┐   ┌──────────────────┐  ┌──────────────┐  │
│  │   PostgreSQL     │   │   Neo4j (Graph)  │  │    Redis     │  │
│  │  (Source of      │   │  (Cycle Det.     │  │  (Cache /    │  │
│  │   Truth OLTP)    │   │   + Traversal)   │  │   Rate Lmt)  │  │
│  └─────────────────┘   └──────────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────────┘
       │
┌──────▼────────────────────────────────────────────────────────┐
│                     OBSERVABILITY LAYER                        │
│   Prometheus metrics | Structured JSON logs | OpenTelemetry    │
└───────────────────────────────────────────────────────────────┘
```

---

## 3. Core Architectural Decisions

### 3.1 Hybrid Database Strategy

| Concern | Store | Rationale |
|---|---|---|
| User profiles, rewards, fraud records | PostgreSQL | ACID, relational integrity, audit trails |
| Referral graph edges, cycle detection | Neo4j | Native graph traversal, O(E) DFS < 10ms |
| Cycle detection ancestor cache | Redis | Sub-millisecond ancestor set lookups |
| Rate limiting counters | Redis | Atomic increment, TTL-based windows |
| Session / JWT blacklist | Redis | Fast invalidation |

**Why Neo4j for graph?**  
PostgreSQL recursive CTEs for ancestor traversal on a 50M-edge graph are O(N) with high I/O. Neo4j stores edges as pointer-chained records on disk — DFS traversal is O(V+E) with index-backed neighbor lookups, achieving <5ms for graphs 10 levels deep.

**Why Redis for ancestor cache?**  
When a referral attempt is made, we need to answer: "Is `new_user` an ancestor of `referrer`?" instantly. Redis `SMEMBERS` on a pre-computed ancestor set answers this in O(1). The cache is invalidated on every successful edge creation affecting that subtree.

### 3.2 DAG Enforcement Architecture

The system uses a **3-layer cycle prevention** strategy:

```
Layer 1: Self-referral check (O(1), in-memory)
         └─ if referrer_id == user_id → REJECT

Layer 2: Redis ancestor cache check (O(1))
         └─ SISMEMBER ancestors:{referrer_id} user_id
         └─ Cache HIT → REJECT (cycle detected)
         └─ Cache MISS → proceed to Layer 3

Layer 3: Neo4j DFS traversal (O(V+E), <5ms)
         └─ MATCH path = (referrer)-[:REFERRED*]->(user)
         └─ EXISTS → REJECT + populate Redis cache
         └─ NOT EXISTS → PROCEED
```

### 3.3 Concurrency & Race Condition Handling

**Problem:** Two concurrent requests could both pass cycle detection and both attempt to create edges that together form a cycle.

**Solution: Distributed Lock per user pair**

```
Lock key: referral_lock:{min(user_id, referrer_id)}:{max(user_id, referrer_id)}
Lock TTL: 500ms
Acquire timeout: 200ms
Backend: Redis SETNX with Lua atomic compare-and-delete
```

**Full atomic flow:**
```
1. Acquire Redis lock on (user_id, referrer_id) pair
2. Re-check cycle in Neo4j (inside lock)
3. BEGIN PostgreSQL transaction
4. INSERT referral record (status=PENDING)
5. CREATE Neo4j edge (user)-[:REFERRED]->(referrer)
6. UPDATE PostgreSQL referral status=VALID
7. Invalidate Redis ancestor caches for affected nodes
8. COMMIT PostgreSQL
9. Release Redis lock
10. Enqueue reward distribution job (async)
```

If step 5 (Neo4j) fails after step 4 (PG insert), a compensating delete is issued. Both operations are wrapped in a saga pattern with rollback handlers.

---

## 4. Module Breakdown

| Module | Responsibility | Key Files |
|---|---|---|
| `user` | Registration, profile, user graph node | `user.spec.md` |
| `referral` | Edge creation, cycle detection, DAG ops | `referral.spec.md` |
| `reward` | Multi-level reward propagation, ledger | `reward.spec.md` |
| `fraud` | Pattern detection, velocity limits, flags | `fraud.spec.md` |
| `dashboard` | Metrics aggregation, graph view, events | `dashboard.spec.md` |

---

## 5. Global Data Models

### 5.1 PostgreSQL Schema (Source of Truth)

```sql
-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Enum types
CREATE TYPE referral_status AS ENUM ('PENDING', 'VALID', 'REJECTED', 'FRAUD');
CREATE TYPE reward_type AS ENUM ('PERCENTAGE', 'FIXED');
CREATE TYPE fraud_reason AS ENUM (
  'SELF_REFERRAL',
  'CYCLE_DETECTED',
  'VELOCITY_EXCEEDED',
  'DUPLICATE_IP',
  'DUPLICATE_DEVICE',
  'SUSPICIOUS_PATTERN'
);
CREATE TYPE event_type AS ENUM (
  'USER_REGISTERED',
  'REFERRAL_CREATED',
  'REFERRAL_REJECTED',
  'REWARD_ISSUED',
  'FRAUD_FLAGGED'
);

-- Core tables
CREATE TABLE users (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email           VARCHAR(255) UNIQUE NOT NULL,
  username        VARCHAR(100) UNIQUE NOT NULL,
  referral_code   VARCHAR(20) UNIQUE NOT NULL,
  referrer_id     UUID REFERENCES users(id) ON DELETE SET NULL,
  status          VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
  ip_address      INET,
  device_hash     VARCHAR(64),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE referrals (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  referrer_id     UUID NOT NULL REFERENCES users(id),
  referred_id     UUID NOT NULL REFERENCES users(id),
  status          referral_status NOT NULL DEFAULT 'PENDING',
  depth           SMALLINT NOT NULL DEFAULT 1,
  ip_address      INET,
  device_hash     VARCHAR(64),
  fraud_reason    fraud_reason,
  fraud_metadata  JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at     TIMESTAMPTZ,
  CONSTRAINT no_self_referral CHECK (referrer_id != referred_id),
  CONSTRAINT unique_referred UNIQUE (referred_id)  -- one referrer per user
);

CREATE TABLE reward_config (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name            VARCHAR(100) NOT NULL,
  max_depth       SMALLINT NOT NULL DEFAULT 3,
  reward_type     reward_type NOT NULL DEFAULT 'PERCENTAGE',
  level_configs   JSONB NOT NULL,
  -- e.g. [{"level":1,"value":10},{"level":2,"value":5},{"level":3,"value":2}]
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE rewards (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  referral_id     UUID NOT NULL REFERENCES referrals(id),
  recipient_id    UUID NOT NULL REFERENCES users(id),
  trigger_user_id UUID NOT NULL REFERENCES users(id),
  level           SMALLINT NOT NULL,
  reward_type     reward_type NOT NULL,
  amount          NUMERIC(12,4) NOT NULL,
  config_id       UUID NOT NULL REFERENCES reward_config(id),
  status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
  issued_at       TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE fraud_events (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id         UUID NOT NULL REFERENCES users(id),
  referral_id     UUID REFERENCES referrals(id),
  reason          fraud_reason NOT NULL,
  metadata        JSONB NOT NULL DEFAULT '{}',
  severity        SMALLINT NOT NULL DEFAULT 1,  -- 1=low, 2=med, 3=high
  reviewed        BOOLEAN NOT NULL DEFAULT FALSE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE activity_events (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  event_type      event_type NOT NULL,
  actor_id        UUID REFERENCES users(id),
  target_id       UUID REFERENCES users(id),
  payload         JSONB NOT NULL DEFAULT '{}',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_referrals_referrer ON referrals(referrer_id);
CREATE INDEX idx_referrals_status ON referrals(status);
CREATE INDEX idx_referrals_created ON referrals(created_at DESC);
CREATE INDEX idx_rewards_recipient ON rewards(recipient_id);
CREATE INDEX idx_rewards_referral ON rewards(referral_id);
CREATE INDEX idx_fraud_user ON fraud_events(user_id);
CREATE INDEX idx_fraud_created ON fraud_events(created_at DESC);
CREATE INDEX idx_activity_created ON activity_events(created_at DESC);
CREATE INDEX idx_users_referrer ON users(referrer_id);
CREATE INDEX idx_users_code ON users(referral_code);
```

### 5.2 Neo4j Graph Schema

```cypher
// Node: User
// Properties: id (UUID), username, created_at
CREATE CONSTRAINT user_id_unique IF NOT EXISTS
  FOR (u:User) REQUIRE u.id IS UNIQUE;

CREATE INDEX user_id_index IF NOT EXISTS
  FOR (u:User) ON (u.id);

// Relationship: REFERRED
// (child:User)-[:REFERRED {referral_id, created_at, depth}]->(parent:User)
// Direction: child → parent (the person who was referred → the person who referred them)

// Example:
// Alice refers Bob, Bob refers Carol:
// (Bob)-[:REFERRED]->(Alice)
// (Carol)-[:REFERRED]->(Bob)
```

**Why this edge direction?**  
Cycle detection requires checking if `referrer` is a descendant of `new_user`. With `child → parent` edges, we traverse `REFERRED*` from `referrer` to see if we reach `new_user`. This is a simple reachability query.

---

## 6. API Standards

### 6.1 Base URL Structure
```
/api/v1/{module}/{resource}
```

### 6.2 Authentication
- JWT Bearer tokens, 15-minute access + 7-day refresh
- All endpoints require auth except `/api/v1/auth/*`

### 6.3 Standard Response Envelope
```json
{
  "success": true,
  "data": { ... },
  "meta": {
    "request_id": "uuid",
    "timestamp": "ISO8601",
    "duration_ms": 42
  },
  "error": null
}
```

### 6.4 Error Response
```json
{
  "success": false,
  "data": null,
  "meta": { "request_id": "...", "timestamp": "..." },
  "error": {
    "code": "CYCLE_DETECTED",
    "message": "Referral would create a cycle in the graph",
    "details": {}
  }
}
```

### 6.5 Standard Error Codes
| Code | HTTP | Description |
|---|---|---|
| `CYCLE_DETECTED` | 409 | Referral creates a DAG cycle |
| `SELF_REFERRAL` | 400 | User attempting to refer themselves |
| `DUPLICATE_REFERRAL` | 409 | User already has a referrer |
| `VELOCITY_EXCEEDED` | 429 | Rate limit hit |
| `FRAUD_BLOCKED` | 403 | User/request flagged as fraud |
| `USER_NOT_FOUND` | 404 | Referenced user does not exist |
| `INVALID_CODE` | 400 | Referral code invalid or expired |
| `GRAPH_WRITE_FAILED` | 500 | Neo4j write failure |
| `LOCK_TIMEOUT` | 503 | Distributed lock timeout |

---

## 7. Performance Targets

| Operation | P50 | P95 | P99 | Notes |
|---|---|---|---|---|
| Referral claim (cache hit) | <10ms | <25ms | <50ms | Redis ancestor check |
| Referral claim (cache miss) | <30ms | <70ms | <99ms | Neo4j DFS required |
| Reward distribution | <200ms | <500ms | <1s | Async, non-blocking |
| Dashboard metrics | <100ms | <200ms | <400ms | Cached aggregates |
| Graph view (3 levels) | <50ms | <100ms | <200ms | Neo4j pattern match |

---

## 8. Observability

### 8.1 Structured Logging
All logs emit JSON with fields:
```json
{
  "timestamp": "ISO8601",
  "level": "INFO|WARN|ERROR",
  "service": "referral-engine",
  "module": "referral",
  "request_id": "uuid",
  "user_id": "uuid",
  "duration_ms": 42,
  "event": "REFERRAL_CREATED",
  "metadata": {}
}
```

### 8.2 Prometheus Metrics
```
csre_referrals_total{status="valid|rejected|fraud"}
csre_cycle_detections_total
csre_fraud_events_total{reason="..."}
csre_api_latency_seconds{endpoint, method}
csre_graph_traversal_ms{outcome="hit|miss"}
csre_rewards_issued_total
csre_redis_cache_hit_ratio
```

### 8.3 Health Endpoints
```
GET /health          → {pg: ok, neo4j: ok, redis: ok, status: ok}
GET /health/live     → 200 OK (liveness)
GET /health/ready    → 200 OK (readiness, checks all deps)
GET /metrics         → Prometheus text format
```

---

## 9. Security Model

- **Auth:** JWT HS256, short-lived access tokens
- **Input validation:** Pydantic v2 with strict mode
- **SQL injection:** SQLAlchemy ORM parameterized queries only
- **Cypher injection:** Neo4j parameterized Cypher, never string interpolation
- **Rate limiting:** Per-user, per-IP, per-endpoint via Redis sliding window
- **PII:** Email hashed in logs; raw in DB with field-level encryption option
- **CORS:** Whitelist-only origins
- **Secrets:** Env vars via Vault/Doppler, never in code

---

## 10. Deployment Architecture

```
Docker Compose (Dev) / Kubernetes (Prod)

Services:
- api (FastAPI, 4 workers) — HPA on CPU/RPS
- worker (Celery, reward jobs) — HPA on queue depth
- postgres (PG 15, primary + 1 read replica)
- neo4j (Community or Enterprise, single node or causal cluster)
- redis (Redis 7, Sentinel or Cluster)
- prometheus + grafana (observability)
- nginx (reverse proxy, TLS termination)
```

---

## 11. Module Dependency Graph

```
dashboard ──────────────────────────────────────────────────────┐
    │                                                            │
    ├── user ──────────────────────────────────────────────┐    │
    │                                                       │    │
    ├── referral ──────────────────────────────────────┐   │    │
    │       │                                          │   │    │
    │       ├── fraud ───────────────────────────┐    │   │    │
    │       │                                    │    │   │    │
    │       └── reward ──────────────────────┐   │    │   │    │
    │                                        │   │    │   │    │
    └────────────────────────────────────────┴───┴────┴───┘    │
                                                                 │
                            ALL MODULES ─────────────────────────┘
```

---

## 12. Critical Failure Scenarios & Mitigations

| Scenario | Detection | Mitigation |
|---|---|---|
| Neo4j down during referral | Health check + exception | Fail-closed: reject referral, queue retry |
| Redis down (lock unavailable) | Timeout exception | Fall back to DB-level advisory lock (PG `pg_try_advisory_lock`) |
| PG + Neo4j write divergence | Background reconciliation job | Saga compensating transaction, alert on divergence |
| Referral storm (viral campaign) | Rate limiter triggers | Tiered rate limits; async queue drain |
| Cache poisoning (stale ancestor set) | TTL expiry + versioning | Short TTL (60s) + version key invalidation |
| Distributed lock deadlock | Lock TTL expiry | TTL=500ms auto-expiry; never hold locks across I/O |


--- user.spec.md ---

# user.spec.md — User Module Specification
## Cycle-Safe Referral Engine v1.0

---

## Feature: User Management & Graph Node Lifecycle

### Goal
Manage the full lifecycle of a user — registration, profile management, and graph node creation. Every user is simultaneously a record in PostgreSQL (authoritative) and a `(:User)` node in Neo4j (graph operations). These two representations must stay in sync at all times.

---

## Requirements

### Functional
- FR-U-01: Register a new user with email, username, and optional referral code
- FR-U-02: Auto-generate a unique, URL-safe referral code on registration
- FR-U-03: Atomically create PostgreSQL user record AND Neo4j graph node
- FR-U-04: Validate referral code existence before registration completes
- FR-U-05: Retrieve user profile with referral stats
- FR-U-06: Look up users by referral code (for referral claim flow)
- FR-U-07: Track device fingerprint and IP for fraud context
- FR-U-08: Soft-delete / deactivate users without removing graph structure

### Non-Functional
- NFR-U-01: Registration endpoint <200ms P95
- NFR-U-02: Referral code lookup <20ms P95 (Redis-cached)
- NFR-U-03: User record creation must be idempotent (no duplicate emails)
- NFR-U-04: PII (email) never logged in plaintext

---

## API Contract

### POST /api/v1/users/register

**Request:**
```json
{
  "email": "user@example.com",
  "username": "alice_wonder",
  "password": "hashed_client_side",
  "referral_code": "REF-XKCD42",
  "ip_address": "203.0.113.10",
  "device_hash": "sha256_of_user_agent_and_fingerprint"
}
```

**Response 201:**
```json
{
  "success": true,
  "data": {
    "user": {
      "id": "uuid",
      "email": "user@example.com",
      "username": "alice_wonder",
      "referral_code": "ALICE-7F3K",
      "referrer_id": "uuid_or_null",
      "status": "ACTIVE",
      "created_at": "2026-03-29T10:00:00Z"
    },
    "tokens": {
      "access_token": "jwt...",
      "refresh_token": "jwt...",
      "expires_in": 900
    }
  }
}
```

**Response 409 (duplicate email):**
```json
{
  "success": false,
  "error": { "code": "EMAIL_EXISTS", "message": "Email already registered" }
}
```

**Response 400 (invalid referral code):**
```json
{
  "success": false,
  "error": { "code": "INVALID_CODE", "message": "Referral code not found or expired" }
}
```

---

### GET /api/v1/users/{user_id}

**Response 200:**
```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "username": "alice_wonder",
    "referral_code": "ALICE-7F3K",
    "referrer": {
      "id": "uuid",
      "username": "bob_the_builder"
    },
    "stats": {
      "total_referrals": 14,
      "valid_referrals": 12,
      "fraud_referrals": 2,
      "total_rewards_earned": 145.50
    },
    "status": "ACTIVE",
    "created_at": "2026-03-29T10:00:00Z"
  }
}
```

---

### GET /api/v1/users/by-code/{referral_code}

**Purpose:** Used internally by the referral claim flow to resolve a code to a user ID.

**Response 200:**
```json
{
  "success": true,
  "data": {
    "user_id": "uuid",
    "username": "alice_wonder",
    "referral_code": "ALICE-7F3K"
  }
}
```

---

### GET /api/v1/users/{user_id}/referral-tree

**Query params:** `?depth=3` (default 3, max 5)

**Response 200:**
```json
{
  "success": true,
  "data": {
    "root": "uuid",
    "tree": {
      "id": "uuid",
      "username": "alice_wonder",
      "children": [
        {
          "id": "uuid",
          "username": "bob",
          "children": []
        }
      ]
    },
    "total_nodes": 7,
    "depth_queried": 3
  }
}
```

---

## Data Model

### PostgreSQL

```sql
CREATE TABLE users (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email           VARCHAR(255) UNIQUE NOT NULL,
  email_hash      VARCHAR(64) NOT NULL,          -- SHA-256, used in logs
  username        VARCHAR(100) UNIQUE NOT NULL,
  password_hash   VARCHAR(255) NOT NULL,
  referral_code   VARCHAR(20) UNIQUE NOT NULL,
  referrer_id     UUID REFERENCES users(id) ON DELETE SET NULL,
  status          VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
  -- ACTIVE | SUSPENDED | DEACTIVATED
  ip_address      INET,
  device_hash     VARCHAR(64),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast referral code lookup
CREATE UNIQUE INDEX idx_users_referral_code ON users(referral_code);
-- Fraud lookups by IP
CREATE INDEX idx_users_ip ON users(ip_address);
-- Fraud lookups by device
CREATE INDEX idx_users_device ON users(device_hash);
-- Referrer relationship traversal fallback
CREATE INDEX idx_users_referrer_id ON users(referrer_id);
```

### Neo4j

```cypher
// Created atomically with PostgreSQL record
CREATE (u:User {
  id: $user_id,
  username: $username,
  created_at: $created_at,
  status: $status
})
```

### Redis

```
Key: user:code:{referral_code}  → user_id
TTL: 3600s (1 hour, rolling)
Purpose: O(1) referral code → user_id lookup without PG hit

Key: user:profile:{user_id}    → JSON profile blob
TTL: 300s
Purpose: Profile caching for dashboard reads
```

---

## Business Logic

### Referral Code Generation
```python
def generate_referral_code(username: str) -> str:
    """
    Format: {PREFIX}-{RANDOM}
    PREFIX: First 5 chars of username, uppercased, alphanumeric only
    RANDOM: 4 random alphanumeric chars (base36)
    Example: ALICE-7F3K
    
    Collision handling: retry up to 5 times with new random suffix.
    After 5 failures, use full UUID-based code (fallback).
    """
    prefix = re.sub(r'[^A-Z0-9]', '', username.upper())[:5]
    suffix = base36_random(4)
    code = f"{prefix}-{suffix}"
    # DB uniqueness check → retry on collision
    return code
```

### Registration Flow (Atomic)

```
1. Validate email format (Pydantic)
2. Validate username uniqueness (PG query)
3. If referral_code provided:
   a. Resolve code → referrer_user_id (Redis cache → PG fallback)
   b. If not found → return INVALID_CODE error
   c. If referrer == registering user → return SELF_REFERRAL error
4. Hash password (bcrypt, cost=12)
5. Generate referral code (see above)
6. BEGIN PG transaction
7. INSERT users record (with referrer_id if code provided)
8. CREATE Neo4j (:User) node
9. If referral_code provided:
   a. Trigger referral claim flow (see referral.spec.md)
10. Cache referral_code → user_id in Redis
11. COMMIT
12. Emit USER_REGISTERED activity event (async)
13. Return user + JWT tokens
```

**Rollback on Neo4j failure:**  
If Neo4j node creation fails after PG insert, execute `DELETE FROM users WHERE id = $id` as compensating action. Log error, return 500.

### Status Management
- `ACTIVE` → default on registration
- `SUSPENDED` → set by fraud engine; blocks new referral creation
- `DEACTIVATED` → soft delete; user record retained, graph node marked `status: DEACTIVATED`

---

## Edge Cases

| Case | Handling |
|---|---|
| Email with unicode/special chars | Normalize to lowercase ASCII before storage |
| Username collision race condition | Unique constraint in PG catches it; return 409 |
| Referral code collision on generation | Retry loop up to 5x; UUID fallback |
| Neo4j unavailable at registration | PG user created; Neo4j creation queued in Redis list for async retry |
| Referrer is SUSPENDED | Referral code is still valid; referral will be evaluated by fraud engine |
| Referrer is DEACTIVATED | Referral code is invalidated; return INVALID_CODE |
| Same IP/device already registered | Fraud signal recorded; registration not blocked (configurable) |
| Concurrent registration with same email | PG unique constraint raises IntegrityError → 409 |

---

## Constraints

- C-U-01: One referrer per user (enforced by `UNIQUE(referred_id)` in referrals table)
- C-U-02: Email must be unique globally
- C-U-03: Username must be unique globally, 3–50 chars, `[a-zA-Z0-9_-]` only
- C-U-04: Referral code format: `[A-Z0-9]{1,5}-[A-Z0-9]{4}`, globally unique
- C-U-05: Password minimum 8 chars; stored as bcrypt hash only
- C-U-06: User deletion does NOT remove graph edges (orphaned edges retained for audit)

---

## Acceptance Criteria

- AC-U-01: User can register with a valid referral code; referrer_id is set correctly
- AC-U-02: Duplicate email registration returns 409 with `EMAIL_EXISTS` code
- AC-U-03: Invalid referral code returns 400 with `INVALID_CODE` code
- AC-U-04: Neo4j node is created atomically with PG record; if Neo4j fails, PG record is rolled back
- AC-U-05: Referral code is resolvable via Redis within 10ms after registration
- AC-U-06: User profile endpoint returns accurate referral stats
- AC-U-07: Referral tree endpoint returns correct hierarchical structure up to requested depth
- AC-U-08: Registration endpoint completes in <200ms P95 under 100 concurrent requests


--- referral.spec.md ---

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


--- reward.spec.md ---

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


--- fraud.spec.md ---

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


--- dashboard.spec.md ---

# dashboard.spec.md — Dashboard Module Specification
## Cycle-Safe Referral Engine v1.0

---

## Feature: Real-Time System Monitoring Dashboard

### Goal
Provide a unified React dashboard for monitoring system health, referral activity, fraud events, graph structure, and reward distribution. The dashboard aggregates data from PostgreSQL (metrics), Neo4j (graph visualization), and a WebSocket event stream (live activity feed) into a cohesive operator interface.

---

## Requirements

### Functional
- FR-D-01: Display key system metrics (users, referrals, rewards, fraud) with live updates
- FR-D-02: Render interactive referral graph for any user (up to 3 levels, configurable)
- FR-D-03: List rejected/fraud referrals with reasons, filterable and paginated
- FR-D-04: Real-time activity feed via WebSocket showing last 50 events
- FR-D-05: Allow graph exploration — click a node to recenter and re-render
- FR-D-06: Support time-range filtering on metrics (last 1h, 24h, 7d, 30d)
- FR-D-07: Show system health status (database connectivity, cache status)
- FR-D-08: Display per-fraud-reason breakdown

### Non-Functional
- NFR-D-01: Metrics panel loads in <100ms (cached aggregates)
- NFR-D-02: Graph view renders in <500ms for 3-level tree
- NFR-D-03: WebSocket reconnects automatically on disconnect
- NFR-D-04: Dashboard is read-only (no mutations except admin review actions)

---

## API Contract

### GET /api/v1/dashboard/metrics

**Query:** `?window=24h` (1h | 24h | 7d | 30d)

**Response 200:**
```json
{
  "success": true,
  "data": {
    "window": "24h",
    "generated_at": "2026-03-29T10:00:00Z",
    "users": {
      "total": 142850,
      "new_in_window": 1247,
      "active": 98230
    },
    "referrals": {
      "total": 89421,
      "valid": 81234,
      "rejected": 6432,
      "fraud": 1755,
      "in_window": 847,
      "valid_rate": 0.908
    },
    "rewards": {
      "total_issued": 284750,
      "amount_distributed": 284750.50,
      "pending_amount": 1240.00
    },
    "fraud": {
      "total_events": 1755,
      "by_reason": {
        "SELF_REFERRAL": 310,
        "CYCLE_DETECTED": 89,
        "VELOCITY_EXCEEDED": 512,
        "DUPLICATE_IP": 198,
        "DUPLICATE_DEVICE": 92,
        "SUSPICIOUS_PATTERN": 46
      },
      "unreviewed_high_severity": 12
    },
    "system": {
      "graph_node_count": 142850,
      "graph_edge_count": 89421,
      "avg_referral_latency_ms": 42,
      "cache_hit_rate": 0.94
    }
  }
}
```

---

### GET /api/v1/dashboard/graph/{user_id}

**Query:** `?depth=3`

**Response 200:**
```json
{
  "success": true,
  "data": {
    "root_user_id": "uuid",
    "depth": 3,
    "nodes": [
      {
        "id": "uuid",
        "username": "alice_wonder",
        "referral_count": 14,
        "is_root": true,
        "depth_from_root": 0
      },
      {
        "id": "uuid",
        "username": "bob_builder",
        "referral_count": 3,
        "is_root": false,
        "depth_from_root": 1
      }
    ],
    "edges": [
      {
        "source": "uuid_bob",
        "target": "uuid_alice",
        "referral_id": "uuid",
        "created_at": "2026-03-29T09:00:00Z"
      }
    ],
    "stats": {
      "total_nodes": 22,
      "total_edges": 21,
      "max_depth_found": 3
    }
  }
}
```

---

### GET /api/v1/dashboard/fraud-panel

**Query:** `?page=1&limit=20&reason=CYCLE_DETECTED&severity=3`

**Response 200:**
```json
{
  "success": true,
  "data": {
    "events": [
      {
        "id": "uuid",
        "user": { "id": "uuid", "username": "charlie" },
        "reason": "CYCLE_DETECTED",
        "severity": 3,
        "severity_label": "HIGH",
        "referral_attempt": {
          "attempted_referrer": { "id": "uuid", "username": "alice" },
          "timestamp": "2026-03-29T09:55:00Z"
        },
        "metadata": { "cycle_path_length": 3 },
        "reviewed": false,
        "created_at": "2026-03-29T09:55:00Z"
      }
    ],
    "pagination": { "page": 1, "limit": 20, "total": 38 },
    "summary": {
      "total_unreviewed": 38,
      "high_severity_unreviewed": 12
    }
  }
}
```

---

### GET /api/v1/dashboard/activity-feed

**Query:** `?limit=50` (initial load)

**Response 200:**
```json
{
  "success": true,
  "data": {
    "events": [
      {
        "id": "uuid",
        "event_type": "REFERRAL_CREATED",
        "label": "Bob referred by Alice",
        "actor": { "id": "uuid", "username": "alice" },
        "target": { "id": "uuid", "username": "bob" },
        "payload": { "referral_id": "uuid", "status": "VALID" },
        "created_at": "2026-03-29T10:00:00Z"
      },
      {
        "id": "uuid",
        "event_type": "FRAUD_FLAGGED",
        "label": "Cycle attempt blocked",
        "actor": { "id": "uuid", "username": "charlie" },
        "target": null,
        "payload": { "reason": "CYCLE_DETECTED", "severity": 3 },
        "created_at": "2026-03-29T09:59:50Z"
      }
    ]
  }
}
```

---

### WebSocket: ws://host/ws/dashboard

**Protocol:** JSON messages over WebSocket

**Client → Server (subscribe):**
```json
{ "action": "subscribe", "channel": "activity_feed" }
```

**Server → Client (event push):**
```json
{
  "type": "event",
  "channel": "activity_feed",
  "data": {
    "id": "uuid",
    "event_type": "REFERRAL_CREATED",
    "label": "Dave referred by Carol",
    "actor": { "id": "uuid", "username": "carol" },
    "target": { "id": "uuid", "username": "dave" },
    "payload": { "referral_id": "uuid", "status": "VALID" },
    "created_at": "2026-03-29T10:01:00Z"
  }
}
```

**Server → Client (metrics update, every 30s):**
```json
{
  "type": "metrics_update",
  "data": {
    "users_total": 142851,
    "referrals_valid": 81235,
    "fraud_events_total": 1756
  }
}
```

**Server → Client (heartbeat, every 15s):**
```json
{ "type": "ping", "timestamp": "2026-03-29T10:01:15Z" }
```

---

## Data Model

### Dashboard Metrics Cache (Redis)

```
Key: dashboard:metrics:{window}
Type: String (JSON blob)
TTL: 30s
Content: Full metrics payload for the given window (1h|24h|7d|30d)
Refresh: Background Celery task every 30s
```

```python
# Background metrics refresh task
@celery.task
async def refresh_dashboard_metrics():
    for window in ['1h', '24h', '7d', '30d']:
        metrics = await compute_metrics(window)
        await redis.setex(
            f"dashboard:metrics:{window}",
            30,
            json.dumps(metrics)
        )
```

### Activity Events (PostgreSQL + Redis pub/sub)

```sql
-- activity_events defined in global.spec.md
-- Dashboard reads from this table for initial load
-- New events are also published to Redis channel for WebSocket

-- Efficient recent events query
SELECT ae.*, 
       u1.username AS actor_username,
       u2.username AS target_username
FROM activity_events ae
LEFT JOIN users u1 ON u1.id = ae.actor_id
LEFT JOIN users u2 ON u2.id = ae.target_id
ORDER BY ae.created_at DESC
LIMIT 50;
```

### Neo4j Graph Query for Dashboard View

```cypher
-- Fetch all nodes and edges for a user's subtree (downward, up to depth D)
MATCH (root:User {id: $user_id})
OPTIONAL MATCH path = (child:User)-[:REFERRED*1..$depth]->(root)
WITH root, COLLECT(DISTINCT nodes(path)) AS node_sets,
     COLLECT(DISTINCT relationships(path)) AS rel_sets
UNWIND node_sets AS node_list
UNWIND node_list AS n
WITH root, COLLECT(DISTINCT n) AS all_nodes, rel_sets
UNWIND rel_sets AS rel_list
UNWIND rel_list AS r
RETURN all_nodes, COLLECT(DISTINCT r) AS all_rels
```

---

## Backend Architecture

### Metrics Computation SQL

```sql
-- Users metrics
SELECT
  COUNT(*) FILTER (WHERE TRUE) AS total_users,
  COUNT(*) FILTER (WHERE created_at > NOW() - $window) AS new_in_window,
  COUNT(*) FILTER (WHERE status = 'ACTIVE') AS active_users
FROM users;

-- Referrals metrics
SELECT
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE status = 'VALID') AS valid,
  COUNT(*) FILTER (WHERE status = 'REJECTED') AS rejected,
  COUNT(*) FILTER (WHERE status = 'FRAUD') AS fraud,
  COUNT(*) FILTER (WHERE created_at > NOW() - $window) AS in_window,
  ROUND(
    COUNT(*) FILTER (WHERE status = 'VALID')::NUMERIC / NULLIF(COUNT(*), 0),
    3
  ) AS valid_rate
FROM referrals;

-- Fraud breakdown
SELECT reason, COUNT(*) AS count
FROM fraud_events
GROUP BY reason;

-- Average latency (resolved_at - created_at)
SELECT ROUND(
  AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) * 1000)
) AS avg_latency_ms
FROM referrals
WHERE status = 'VALID'
  AND resolved_at IS NOT NULL
  AND created_at > NOW() - INTERVAL '1 hour';
```

### WebSocket Server (FastAPI)

```python
from fastapi import WebSocket
import asyncio
import redis.asyncio as aioredis

active_connections: List[WebSocket] = []

@app.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    
    # Start Redis pub/sub listener for this connection
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("activity_events")
    
    try:
        async def listen_redis():
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    await websocket.send_text(message['data'])
        
        async def heartbeat():
            while True:
                await asyncio.sleep(15)
                await websocket.send_json({
                    "type": "ping",
                    "timestamp": datetime.utcnow().isoformat()
                })
        
        # Run both concurrently
        await asyncio.gather(listen_redis(), heartbeat())
    
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        await pubsub.unsubscribe("activity_events")


# Publishing events (called by referral/fraud services)
async def publish_activity_event(event: ActivityEvent):
    # Write to PG
    await db.execute("""
        INSERT INTO activity_events (id, event_type, actor_id, target_id, payload)
        VALUES ($1, $2, $3, $4, $5)
    """, event.id, event.event_type, event.actor_id, event.target_id,
         json.dumps(event.payload))
    
    # Publish to Redis channel (WebSocket clients receive)
    await redis_client.publish(
        "activity_events",
        json.dumps({
            "type": "event",
            "channel": "activity_feed",
            "data": event.to_dict()
        })
    )
```

---

## Frontend Architecture (React)

### Component Tree

```
<App>
  <DashboardLayout>
    <Sidebar navigation />
    <MainContent>
      ├── <MetricsPanel>
      │     ├── <StatCard title="Total Users" />
      │     ├── <StatCard title="Valid Referrals" />
      │     ├── <StatCard title="Fraud Events" />
      │     ├── <StatCard title="Rewards Distributed" />
      │     └── <TimeRangeSelector />
      │
      ├── <GraphView>
      │     ├── <UserSearchBar />
      │     ├── <ForceDirectedGraph nodes edges />  (D3 or react-force-graph)
      │     └── <NodeDetailPanel />
      │
      ├── <FraudPanel>
      │     ├── <FraudFilter reason severity reviewed />
      │     ├── <FraudEventTable />
      │     └── <FraudEventDetail />
      │
      └── <ActivityFeed>
            ├── <WebSocketStatus />
            └── <EventList events />
    </MainContent>
  </DashboardLayout>
</App>
```

### WebSocket Client Hook

```typescript
function useDashboardWebSocket() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    function connect() {
      const ws = new WebSocket(`wss://${host}/ws/dashboard`);
      
      ws.onopen = () => {
        setConnected(true);
        ws.send(JSON.stringify({ action: 'subscribe', channel: 'activity_feed' }));
      };
      
      ws.onmessage = (msg) => {
        const data = JSON.parse(msg.data);
        if (data.type === 'event') {
          setEvents(prev => [data.data, ...prev].slice(0, 50));
        }
        if (data.type === 'metrics_update') {
          // Update live metrics counters
        }
      };
      
      ws.onclose = () => {
        setConnected(false);
        setTimeout(connect, 3000); // Auto-reconnect
      };
      
      wsRef.current = ws;
    }
    
    connect();
    return () => wsRef.current?.close();
  }, []);

  return { events, connected };
}
```

### Graph Visualization

```typescript
// Uses react-force-graph or D3 force simulation
// Node color encoding:
//   Root user: #3B82F6 (blue)
//   Direct referral (depth 1): #10B981 (green)
//   Depth 2: #F59E0B (yellow)
//   Depth 3: #6B7280 (gray)
//
// Edge: directed arrow, labeled with referral date
// Click node: fetch /dashboard/graph/{node_id} and re-render
// Hover node: tooltip with username, referral count, join date
```

---

## Edge Cases

| Case | Handling |
|---|---|
| WebSocket connection drops | Client auto-reconnects after 3s with exponential backoff |
| Metrics cache miss | Compute synchronously from DB; cache result for 30s |
| Graph request for user with 0 referrals | Return single root node, empty edges array |
| Graph request for very popular user (1000+ referrals) | Depth-limited query prevents overload; warn in UI |
| Activity feed empty (new system) | Return empty array, UI shows "No events yet" |
| Multiple dashboard tabs open | Each tab maintains its own WebSocket; server broadcasts to all |
| Neo4j down during graph view request | Return 503 with message; UI shows "Graph temporarily unavailable" |

---

## Constraints

- C-D-01: Metrics endpoint must serve from cache (max 30s stale); never block on real-time computation
- C-D-02: Graph view depth is capped at 5 levels via query param validation
- C-D-03: Activity feed via WebSocket only; HTTP polling for activity feed is not supported
- C-D-04: Dashboard endpoints are read-only (no data mutations, except fraud review)
- C-D-05: WebSocket server must handle 1000 concurrent dashboard connections

---

## Acceptance Criteria

- AC-D-01: Metrics panel loads in <100ms with accurate counts for selected time window
- AC-D-02: Graph view renders referral tree for a user within 500ms, correctly structured
- AC-D-03: Clicking a node in the graph view re-renders the tree centered on that node
- AC-D-04: Fraud panel shows all unreviewed high-severity events by default
- AC-D-05: Activity feed receives new events via WebSocket within 500ms of occurrence
- AC-D-06: WebSocket reconnects automatically after disconnect, without page refresh
- AC-D-07: Metrics update in real time (every 30s) without user interaction
- AC-D-08: Dashboard remains functional (degraded mode) when Neo4j is unavailable (graph view shows error; metrics still work)
- AC-D-09: 1000 concurrent WebSocket connections do not degrade API response times
