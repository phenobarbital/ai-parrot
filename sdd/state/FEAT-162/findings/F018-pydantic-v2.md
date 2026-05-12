---
id: F018
query_id: Q018
type: grep
intent: Confirm Pydantic v2 is the project standard (look for BaseModel imports + pydantic version pin).
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F018 — Pydantic pinned to 2.12.5

## Summary

`packages/ai-parrot/pyproject.toml` pins `pydantic==2.12.5` (line 47). The
brainstorm's "Pydantic v2 — all new models must be v2" is confirmed. All
existing Pydantic models in the security toolkits already use v2 patterns
(`Field(default=..., description=...)`, `model_dump(mode="json")`).

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 47
  symbol: pydantic pin
  excerpt: |
    "pydantic==2.12.5",

## Notes

- No further investigation needed.
- The brainstorm's models (`ReportRef`, `ReportFilter`, etc.) use v2-compatible
  syntax (`Literal`, `BaseModel`, `Field`, `model_dump(mode="json")`).
