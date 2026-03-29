# Observability Handover

## Purpose
- Holds metrics and future tracing or monitoring integrations.

## Current State
- Prometheus metric placeholders exist for referrals, cycle detections, and API latency.
- `/metrics` is mounted from the FastAPI app.

## Handoff Notes
- Expand metrics here rather than declaring counters in random modules.
- Add tracing and log correlation once request middleware is in place.

