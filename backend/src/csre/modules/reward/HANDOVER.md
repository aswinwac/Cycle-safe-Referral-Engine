# Reward Module Handover

## Purpose
- Calculates and distributes multi-level referral rewards.

## Current State
- Placeholder repository, schema, and service classes exist.
- Background task stub exists for reward distribution.

## Spec Alignment
- Reward config and reward ledger data belong in PostgreSQL.
- Distribution is expected to run asynchronously through Celery.

## Next Steps
- Add reward config loading and caching.
- Implement reward propagation rules by referral depth.
- Persist reward issuance status and task outcomes.

