---
id: F006
query_id: Q006
type: read
intent: Renderer package exports
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F006 — renderers/__init__.py exports

## Summary
Package re-exports `AbstractFormRenderer`, `AdaptiveCardRenderer`, `HTML5Renderer`, `JsonSchemaRenderer` eagerly and `TelegramRenderer` lazily (PEP 562) because it pulls aiogram. A Teams variant would be added here (eager is fine — no heavy deps).

## Citations
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py`
  lines: 14-21
  excerpt: |
    from .adaptive_card import AdaptiveCardRenderer
    _LAZY_EXPORTS = {"TelegramRenderer": ".telegram"}
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py`
  lines: 38-44
  symbol: `__all__`
