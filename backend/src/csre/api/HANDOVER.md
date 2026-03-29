# API Handover

## Purpose
- Owns FastAPI routing, versioned API organization, and HTTP-facing endpoint composition.

## Current State
- Central router wires health, users, referrals, rewards, fraud, and dashboard endpoints.
- Most routes are scaffolds that return the standard response envelope.

## Key Files
- `router.py`
- `v1/endpoints/health.py`
- `v1/endpoints/users.py`
- `v1/endpoints/referrals.py`
- `v1/endpoints/rewards.py`
- `v1/endpoints/fraud.py`
- `v1/endpoints/dashboard.py`

## Handoff Notes
- Keep route shapes aligned to `/api/v1/{module}/{resource}` from the spec.
- Add auth and dependency injection at the router layer once services are implemented.
- Preserve the shared response envelope unless the team intentionally changes the API contract.

