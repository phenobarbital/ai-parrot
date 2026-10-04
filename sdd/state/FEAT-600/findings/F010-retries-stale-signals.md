---
id: F010
query_id: Q009
type: read
intent: retries.py already classifies the two proven-stale error strings
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F010 — retries.py already classifies the two proven-stale error strings

## Summary

retries.py L56-57 list 'column does not exist' and 'relation does not exist' among retryable schema errors; RetryHandler L67, SQLRetryHandler L123 with _get_sample_data_for_error L135 (used L249); FluxRetryHandler L262, DSLRetryHandler L275. This is the hook point for error-driven read-repair.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/database/retries.py`
  lines: 56-57
  symbol: `schema error patterns`
  excerpt: |
    "column does not exist", "relation does not exist"
- path: `packages/ai-parrot/src/parrot/bots/database/retries.py`
  lines: 67,123,135,249
  symbol: `RetryHandler / SQLRetryHandler / _get_sample_data_for_error`
