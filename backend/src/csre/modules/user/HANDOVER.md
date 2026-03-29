# User Module Handover

## Purpose
- Manages registration, profile operations, referral code resolution, and user graph node creation.

## Current State
- Placeholder repository, schemas, and service exist.
- API route currently exposes only a scaffold response.

## Spec Alignment
- User creation must coordinate PostgreSQL and Neo4j.
- Referral code lookup is expected to be Redis-cached for fast resolution.

## Next Steps
- Implement registration and profile endpoints.
- Add PostgreSQL persistence plus Neo4j node creation flow.
- Introduce rollback or retry behavior when graph creation fails.

