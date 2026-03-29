# API v1 Handover

## Purpose
- Holds versioned API routes for the first public backend contract.

## Current State
- Version prefix is configured through `Settings.api_v1_prefix`.
- Route files under `endpoints/` are scaffolded and mounted by the root API router.

## Handoff Notes
- Keep breaking API changes isolated behind a new version package.
- Reuse shared schemas and envelope helpers rather than building ad hoc response shapes.

