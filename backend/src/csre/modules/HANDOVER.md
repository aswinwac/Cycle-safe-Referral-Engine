# Modules Handover

## Purpose
- Groups the core business domains: user, referral, reward, fraud, and dashboard.

## Current State
- Each module has placeholder `repository.py`, `schemas.py`, and `service.py` files.
- The package structure mirrors the system architecture in `specs/global.spec.md`.

## Handoff Notes
- Treat each module as a bounded context with a thin public surface.
- Keep orchestration in services and persistence in repositories.
- Cross-module coupling should happen through explicit service boundaries, not deep imports.

