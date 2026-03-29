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
