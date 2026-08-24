# TASK-2413: Extractor Mappings — YAML `relation:` Block + JSON Schema `x-relation`

**Feature**: FEAT-456 — Relational Field Cardinality for parrot-formdesigner
**Spec**: `sdd/specs/formbuilder-fieldtype-cardinality.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2411
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. Form authors declare relations in YAML and JSON Schema;
both extractors must parse (and the JSON Schema side must round-trip with
TASK-2414's renderer emission). The `x-options-source` handling introduced
by FEAT-167 is the exact pattern to mirror for `x-relation`.

---

## Scope

- `extractors/yaml.py`: in `_parse_field`, parse an optional `relation:`
  block (keys mirror `RelationSpec`: `cardinality`, `mode`, `target:
  {namespace, entity, key_field}`, `display_field`, `inverse_field`,
  `on_delete`, `filters`) into a `RelationSpec` on the produced `FormField`.
  Invalid blocks raise with the field name in the message (do NOT silently
  drop — a mistyped relation must not degrade to a plain select).
- `extractors/jsonschema.py`: in the property loop where
  `x-options-source` is handled, parse an `x-relation` dict into
  `RelationSpec` the same way.
- Unit tests for both, including full-field round-trips.

**NOT in scope**: renderer emission of `x-relation` (TASK-2414);
`pydantic.py` / `tool.py` extractors (deferred — spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/yaml.py` | MODIFY | parse `relation:` block in `_parse_field` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py` | MODIFY | parse `x-relation` |
| `packages/parrot-formdesigner/tests/unit/extractors/test_relation_extraction.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.relations import EntityRef, RelationSpec  # TASK-2410
# yaml.py already imports FormField, FieldType, FieldOption, OptionsSource, etc.
```

### Existing Signatures to Use
```python
# extractors/yaml.py (class YamlExtractor) — verified 2026-08-24:
    def extract(self, content: str) -> FormSchema:              # line 131
    def _parse_field(self, data: Any) -> FormField | None:      # line 267
    #   supports three input formats (new: field_id/field_type; legacy: name/type;
    #   legacy alternate: {field_name: {...}}) — docstring at 268-279.
    #   Parse `relation` from field_config the same way _parse_constraints (line 377)
    #   and _parse_options (line 416) read their blocks.

# extractors/jsonschema.py:240-253 — the x-options-source pattern to MIRROR:
    x_src = prop.get("x-options-source")
    if x_src and isinstance(x_src, dict):
        options_source = OptionsSource(source_type=x_src.get("source_type", "endpoint"), ...)
# For x-relation prefer strict construction: RelationSpec(**relation_dict)
# inside try/except with a field-named error, NOT per-key .get() defaults —
# RelationSpec has required keys (cardinality, target).
```

### Does NOT Exist
- ~~A `_parse_relation` helper~~ — create it (private method, either extractor).
- ~~`x-relation` handling anywhere~~ — greenfield in both files.
- ~~YAML alias keys~~ (`rel:`, `foreign_key:`) — only `relation:` is spec'd.
- ~~`_LEGACY_FIELD_TYPE_MAP` involvement~~ — relations do not interact with
  type mapping; do not touch it.

---

## Implementation Notes

### Pattern to Follow
`YamlExtractor._parse_constraints` (yaml.py:377) shows the read-and-build
style for a sub-block. For nested `target`, build `EntityRef` first and let
Pydantic validation errors propagate wrapped with the field id.

### Key Constraints
- Round-trip fidelity: every `RelationSpec` field must survive
  YAML→FormField and x-relation→FormField.
- The `FormField` model-validator from TASK-2411 will reject illegal
  (type × relation) combos — let that error propagate; do not pre-validate.
- Fields without `relation:`/`x-relation` must parse byte-identically to
  today (regression: existing extractor tests stay green).

---

## Acceptance Criteria

- [ ] YAML field with `relation:` block → `FormField.relation` equivalent `RelationSpec`
- [ ] JSON Schema property with `x-relation` → same
- [ ] Malformed relation block → error naming the field (not silent drop)
- [ ] All `RelationSpec` fields round-trip (incl. `on_delete`, `filters`, `key_field`)
- [ ] Existing extractor tests green: `pytest packages/parrot-formdesigner/tests/unit/ -k "yaml or jsonschema" -v`
- [ ] New tests pass: `pytest packages/parrot-formdesigner/tests/unit/extractors/test_relation_extraction.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
import pytest
from parrot_formdesigner.extractors.yaml import YamlExtractor

YAML_FORM = """
form_id: order
title: Order
sections:
  - section_id: main
    fields:
      - field_id: customer
        field_type: select
        label: Customer
        relation:
          cardinality: one
          mode: reference
          target: {namespace: odoo, entity: res.partner}
          display_field: name
          on_delete: restrict
"""


def test_yaml_relation_block_parses():
    form = YamlExtractor().extract(YAML_FORM)
    field = form.sections[0].fields[0]
    rel = field.relation
    assert rel.cardinality == "one" and rel.mode == "reference"
    assert rel.target.namespace == "odoo" and rel.target.entity == "res.partner"
    assert rel.display_field == "name" and rel.on_delete == "restrict"


def test_yaml_malformed_relation_raises():
    bad = YAML_FORM.replace("cardinality: one", "cardinality: banana")
    with pytest.raises(Exception, match="customer"):
        YamlExtractor().extract(bad)
```

---

## Agent Instructions

1. Verify TASK-2411 is in `sdd/tasks/completed/`; read spec §2/§3 Module 4.
2. Verify the contract (`_parse_field` formats, x-options-source block) before coding.
3. Update index → `in-progress`; implement, test, lint.
4. Move this file to `sdd/tasks/completed/`, update index → `done`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
