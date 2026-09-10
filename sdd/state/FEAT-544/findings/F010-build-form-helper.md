---
id: F010
query_id: Q010
type: read
intent: A2UI build_form() helper
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F010 — catalog/parrot/form.py — build_form()

## Summary

`Form` is NOT a catalog component in v1.0 (spec G6): `build_form(id_prefix, title, fields, submit)` composes a root `Column` of Basic primitives — TextField (shortText/longText/number variants), ChoicePicker, CheckBox, DateTimeInput — each bound to `dataModel` path `/<id_prefix>/<name>`, with `checks=[CheckRule(required)]`, plus a `Button` whose `action.event` names the submit event and binds every field in `context`. Supports only 6 input kinds; TOOL-origin only (emits `Button.action`).

## Citations

- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/form.py`
  lines: 1-13
  excerpt: |
    ``Form`` is NOT a registered catalog component in v1.0 (spec G6): a form is composed
    directly from Basic Catalog input primitives plus a ``Button`` whose ``action.event``
    carries the submit event name and a ``context`` binding every field's current value.
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/form.py`
  lines: 32-66
  symbol: `FormField`
  excerpt: |
    FormFieldInput = Literal["text", "number", "select", "checkbox", "date", "textarea"]
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/form.py`
  lines: 73-116
  symbol: `_lower_field`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/form.py`
  lines: 119-164
  symbol: `build_form`
  excerpt: |
    action=Action(event=EventAction(name=submit.action, context=context))
    root = Component(id=id_prefix, component="Column", children=children_ids)
