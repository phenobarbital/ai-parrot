---
id: F006
query_id: Q006
type: read
intent: Renderer registry exports
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F006 — renderers/__init__.py exports

## Summary

Package re-exports AdaptiveCardRenderer, HTML5Renderer, JsonSchemaRenderer eagerly and TelegramRenderer lazily via PEP 562 `__getattr__` (heavy aiogram import). A new renderer would be added to `_LAZY_EXPORTS` if its deps are heavy.

## Citations

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py`
  lines: 9-44
  symbol: `_LAZY_EXPORTS`
  excerpt: |
    _LAZY_EXPORTS = {
        "TelegramRenderer": ".telegram",
    }
