# Backend Handover

## Scope
- FastAPI backend scaffold for the Cycle-Safe Referral Engine.
- Lives under `backend/` with source in `src/csre`.

## Current State
- App bootstrap, health routes, response envelope, dependency clients, and Celery placeholders are scaffolded.
- User module fully implemented with registration, profile lookup, referral code resolution, and referral tree endpoints.
- Referral module: `ReferralService` and `ReferralRepository` implement claim flow with Redis lock, ancestor cache check, Neo4j path check (no APOC), dual-write (PG PENDING → Neo4j edge → VALID), compensation on graph failure, ancestor-cache invalidation, activity event, and Celery `distribute_referral_rewards` enqueue.
- Fraud, reward, and dashboard modules exist as placeholders and are ready for real implementation.
- Docker Compose includes `api`, `worker`, PostgreSQL, Neo4j, and Redis.

## Important Entry Points
- `src/csre/main.py`
- `src/csre/api/router.py`
- `src/csre/core/config.py`
- `docker-compose.yml`
- `pyproject.toml`

## Next Steps
- Implement **fraud** module (velocity config, events API, stats) and wire deeper referral pre-checks if needed beyond Redis velocity on claim.
- Reconciliation job for PG/Neo4j drift; full reward worker implementation.
- Replace remaining `_scaffold` routes with spec-driven endpoints (reward, dashboard).
- Add auth, middleware, and error handling enhancements.
- Implement worker tasks for reward distribution and graph synchronization.
- Add Alembic migrations for database schema evolution.