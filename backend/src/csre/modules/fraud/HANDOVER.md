# Fraud Module Handover

## Purpose
- Detects suspicious referral behavior and records fraud events.

## Current State
- Placeholder repository, schema, and service classes exist.
- API route currently exposes only a scaffold response.

## Spec Alignment
- Needs velocity checks, duplicate IP/device checks, and fraud event persistence.
- Redis is expected to support low-latency checks and counters.

## Next Steps
- Implement synchronous request-time fraud checks.
- Add persistence for fraud events and operator review state.
- Introduce scheduled pattern analysis in background tasks.

