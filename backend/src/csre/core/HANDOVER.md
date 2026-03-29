# Core Handover

## Purpose
- Shared application configuration, exception types, and logging setup.

## Current State
- `config.py` centralizes env-driven settings for FastAPI, PostgreSQL, Neo4j, Redis, and Celery.
- `logging.py` configures JSON logging with `structlog`.
- `exceptions.py` defines shared error codes from the global spec.

## Handoff Notes
- Expand settings here before scattering new env parsing elsewhere.
- Add global exception handlers when real module errors are introduced.
- Keep security-sensitive defaults out of code for non-dev environments.

