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
