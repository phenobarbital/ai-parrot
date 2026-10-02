---
id: F011
query_id: Q011
type: read
intent: decorators and smart_fields helper
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F011 — Decorators and smart-field helper

## Summary

`tool_schema(schema, description=None)` (`decorators.py:39`) sets `func._args_schema` and `_tool_description` (docstring fallback); `requires_permission(*permissions)` (:9). `select_smart_fields(fields_meta)` (`smart_fields.py`) is a pure scorer that skips `binary/html` fields and technical audit columns and favours `name/state/status/date…` names — reusable to pick default ticket fields.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/decorators.py`
  lines: 9-38
  symbol: `requires_permission`
- path: `packages/ai-parrot/src/parrot/tools/decorators.py`
  lines: 39-55
  symbol: `tool_schema`
  excerpt: |
    def decorator(func):
        func._args_schema = schema
        func._tool_description = description or func.__doc__ or f"Tool: {func.__name__}"
- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/smart_fields.py`
  lines: 1-40
  symbol: `select_smart_fields`, `SKIP_FIELD_TYPES`, `HIGH_VALUE_PATTERNS`

## Notes

—
