---
id: F014
query_id: Q014
type: read
intent: Adaptive Card FormSchema renderer precedent
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F014 — renderers/adaptive_card.py — FieldType→element map

## Summary

The AdaptiveCardRenderer keeps a module-level `FieldType -> element` mapping (TEXT→Input.Text, NUMBER→Input.Number, BOOLEAN→Input.Toggle, DATE→Input.Date, SELECT→Input.ChoiceSet, ...) with `None` for GROUP/ARRAY/FILE/IMAGE and an explicit set of unsupported types (SIGNATURE, REST, FORMULA, TREE_SELECT, ...). It is the closest precedent for a dict-output, card-shaped renderer.

## Citations

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
  lines: 71-119
  excerpt: |
    FieldType.TEXT: "Input.Text",
    FieldType.BOOLEAN: "Input.Toggle",
    FieldType.SELECT: "Input.ChoiceSet",
    FieldType.GROUP: None,
    FieldType.FILE: None,
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
  lines: 121
  symbol: `AdaptiveCardRenderer`
