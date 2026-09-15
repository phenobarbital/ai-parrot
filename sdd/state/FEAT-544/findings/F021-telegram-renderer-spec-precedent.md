---
id: F021
query_id: Q021
type: read
intent: Telegram renderer spec precedent
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F021 — Telegram renderer spec — channel renderer + submit cycle pattern

## Summary

The Telegram renderer spec is the precedent for a renderer that owns a full interaction cycle: extends AbstractFormRenderer, reuses HTML5Renderer for WebApp mode, auto-selects mode from FieldType complexity, and routes submissions back through FormRegistry. It also lists explicit non-goals (not a bot framework).

## Citations

- path: `sdd/specs/parrot-formdesigner-renderer-telegram.spec.md`
  lines: 12-49
- path: `sdd/specs/parrot-formdesigner-renderer-telegram.spec.md`
  lines: 84-104
  excerpt: |
    | `AbstractFormRenderer` | extends | TelegramRenderer inherits render() |
    | `HTML5Renderer` | uses | Reused for WebApp HTML generation |
    | `FormRegistry` | uses | Lookup forms by ID for WebApp serving |
