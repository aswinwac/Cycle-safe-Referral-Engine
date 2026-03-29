# DB Handover

## Purpose
- Manages connectivity and health checks for PostgreSQL, Neo4j, and Redis.

## Current State
- Async connection helpers exist for all three backing services.
- Health checks are simple connectivity probes used by the health endpoints.

## Handoff Notes
- Add session management and repository dependencies on top of this layer.
- Introduce retry strategy and instrumentation carefully to avoid masking failures.
- Keep Neo4j and Redis access parameterized and centralized.

