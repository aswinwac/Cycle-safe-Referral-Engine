# Endpoint Handover

## Purpose
- Contains HTTP endpoint modules grouped by bounded context.

## Current State
- `health.py` performs dependency checks for PostgreSQL, Neo4j, and Redis.
- Other endpoint modules currently expose `_scaffold` placeholder routes.

## Handoff Notes
- Replace placeholder routes incrementally with real request and response models.
- Keep endpoint modules thin: validation and transport concerns here, business logic in services.
- Add auth dependencies and request-scoped metadata once middleware is in place.

