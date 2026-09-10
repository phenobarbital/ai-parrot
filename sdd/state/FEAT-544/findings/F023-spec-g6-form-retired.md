---
id: F023
query_id: Q022
type: grep
intent: Spec G6: Form retired
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F023 — a2ui-v1-dialect.spec.md — G6 acceptance

## Summary

Spec goal G6 states `Form` is no longer a registered component: `build_form()` yields primitives + `Button.action.event`; a deep link's `action` validates as `A2UIRendererMessage`; Adaptive Cards emits native inputs and `Action.Submit{a2ui_action}`; the Teams wrapper routes it as a structured turn. Any FormDesigner A2UI renderer must follow this composition rule rather than introduce a `Form` component.

## Citations

- path: `sdd/specs/a2ui-v1-dialect.spec.md`
  lines: 74
  excerpt: |
    G6. **Acciones**: todos los mensajes modelados; `Form` pasa a composición de primitivas
- path: `sdd/specs/a2ui-v1-dialect.spec.md`
  lines: 479
  excerpt: |
    AC-G6: `Form` ya no está registrado; `build_form()` produce primitivas + `Button.action.event`; ...
