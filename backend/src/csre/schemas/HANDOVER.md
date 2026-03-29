# Schemas Handover

## Purpose
- Shared transport schemas used across modules and routes.

## Current State
- `envelope.py` defines the standard success and error response envelope.

## Handoff Notes
- Keep shared schemas generic and stable.
- Module-specific request and response models should stay within their own module packages unless reused broadly.

