# CSRE build progress

- **global**: Architecture and API envelope defined in specs (reference).
- **user**: Registration, profile, by-code, referral tree (`/api/v1/users/*`).
- **referral**: Complete — claim (JWT), velocity (Redis), suspended-user guard, Redis or PG advisory lock, ancestor cache + Neo4j cycle check, dual-write with compensation, depth from referrer chain, activity events (`REFERRAL_CREATED` / `REFERRAL_REJECTED`), GET by id + list by-user (nested `referrer`/`referred`), admin `PATCH /referrals/{id}/review` (`X-Admin-Key` + `ADMIN_API_KEY`), Celery reward enqueue.

Next in build order: **fraud** (full module), **reward**, **dashboard**.
