# Referral Module Handover

## Purpose
- Owns referral claims, DAG enforcement, distributed locking, and graph writes.

## Current State
- Placeholder repository, schemas, and service exist.
- API route currently exposes only a scaffold response.

## Spec Alignment
- This is the core module for cycle prevention using Redis and Neo4j.
- Dual-write behavior with PostgreSQL and Neo4j must remain consistent with the saga flow in the spec.

## Next Steps
- Implement referral claim request handling and validation.
- Add lock acquisition, Redis ancestor cache checks, and Neo4j DFS checks.
- Add transactional PG writes and compensating graph rollback behavior.

