# Tasks Handover

## Purpose
- Background job definitions for asynchronous backend workflows.

## Current State
- Celery task stubs exist for reward distribution and graph divergence detection.
- Worker app is configured in `csre.worker`.

## Handoff Notes
- Keep task payloads small and pass stable identifiers rather than large objects.
- Add retries, idempotency, and monitoring before production use.
