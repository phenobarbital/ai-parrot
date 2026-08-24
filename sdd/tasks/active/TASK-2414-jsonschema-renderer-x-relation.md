# TASK-2414: JsonSchemaRenderer `x-relation` Emission + Renderer No-Op Notes

**Feature**: FEAT-456 — Relational Field Cardinality for parrot-formdesigner
**Spec**: `sdd/specs/formbuilder-fieldtype-cardinality.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2411
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. The JSON Schema renderer is the ONLY renderer that
surfaces relation metadata in v1 (`x-relation` extension, symmetric with
TASK-2413's extractor parsing). The other six renderers must ignore
`relation` — enforced by the spec's strictest criterion: their output for a
relational field is **byte-identical** to the same field without `relation`.

---

## Scope

- `renderers/jsonschema.py`: for any field where `field.relation is not
  None`, emit `prop["x-relation"] = field.relation.model_dump(exclude_none=True)`
  (place it beside the `x-options-source` emission for DYNAMIC_SELECT,
  jsonschema.py:510-512).
- Add a one-line docstring note to the six other renderers' `render()`
  docstrings: `relation` is intentionally ignored (same convention as
  XFormsRenderer's documented no-ops for style/prefilled).
- Regression tests proving byte-identical output on HTML5 and AdaptiveCard
  for a relational vs non-relational SELECT; round-trip test with the
  extractor (extractor(renderer(form)) preserves RelationSpec).

**NOT in scope**: `data-relation-*` attributes in HTML5 (open question §8,
default NO — do not add); extractor-side parsing (TASK-2413).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py` | MODIFY | emit `x-relation` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/{html5,adaptive_card,xforms,pdf,audio}.py`, `renderers/telegram/renderer.py` | MODIFY (docstring only) | no-op note |
| `packages/parrot-formdesigner/tests/unit/renderers/test_relation_rendering.py` | CREATE | emission + byte-identical regression + round-trip |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.relations import EntityRef, RelationSpec  # TASK-2410
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer
```

### Existing Signatures to Use
```python
# renderers/base.py — every renderer implements (verified 2026-08-24):
async def render(self, form: FormSchema, style: StyleSchema | None = None,
                 *, locale: str = "en", prefilled: dict[str, Any] | None = None,
                 errors: dict[str, str] | None = None) -> RenderedForm

# renderers/jsonschema.py:510-512 — the emission point to extend:
#   if ft == FieldType.DYNAMIC_SELECT and field.options_source:
#       prop["x-options-source"] = field.options_source.model_dump()
# x-relation emission goes beside this, but UNCONDITIONALLY on field.relation
# (any field type the TASK-2411 validator allowed), not gated on one FieldType.

# renderers/xforms.py — docstring precedent: documents ignoring style/prefilled
# (TASK-1045 convention). Mirror that wording for `relation`.
```

### Does NOT Exist
- ~~`RenderedForm.relations`~~ / ~~renderer-level relation registry~~ —
  the extension key inside the field property is the ONLY surface.
- ~~`data-relation-*` HTML attributes~~ — explicitly out of scope (spec §7
  "byte-identical" risk note); adding them FAILS an acceptance criterion.
- ~~`x-relation` emission in the structural style output~~ — only the field
  property dict.

---

## Implementation Notes

### Pattern to Follow
`model_dump(exclude_none=True)` keeps the extension compact and makes the
round-trip with TASK-2413's strict `RelationSpec(**d)` construction clean
(absent optional keys, not nulls).

### Key Constraints
- Byte-identical regression is the contract for the six untouched
  renderers: build one form, render twice (with/without `relation` on the
  field), compare `RenderedForm.content` for equality on HTML5 and
  AdaptiveCard at minimum.
- Do not import lxml/aiogram in the test module beyond what existing
  renderer tests already do (telegram pulls aiogram lazily — renderers
  `__init__` uses PEP 562 for `TelegramRenderer`).

---

## Acceptance Criteria

- [ ] Relational SELECT/MULTI_SELECT/ARRAY fields carry `x-relation` in
      JsonSchemaRenderer output; non-relational fields do not
- [ ] Round-trip: JSON Schema extractor parses the emitted `x-relation` back
      to an equal `RelationSpec` (with TASK-2413 merged)
- [ ] HTML5 and AdaptiveCard output byte-identical with vs without `relation`
- [ ] Six renderer docstrings note the intentional no-op
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/renderers/test_relation_rendering.py -v`
- [ ] Existing renderer tests green: `pytest packages/parrot-formdesigner/tests/unit/renderers/ -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
import copy
import json
import pytest
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.relations import EntityRef, RelationSpec
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
from parrot_formdesigner.renderers.html5 import HTML5Renderer

REL = RelationSpec(cardinality="one",
                   target=EntityRef(namespace="odoo", entity="res.partner"))


def _form(with_relation: bool) -> FormSchema:
    f = FormField(field_id="customer", field_type=FieldType.SELECT,
                  label="Customer", relation=REL if with_relation else None)
    return FormSchema(form_id="t", title="T",
                      sections=[FormSection(section_id="s", fields=[f])])


async def test_jsonschema_emits_x_relation():
    out = await JsonSchemaRenderer().render(_form(True))
    # locate the property dict for "customer" in out.content and assert:
    #   prop["x-relation"]["cardinality"] == "one"
    #   prop["x-relation"]["target"] == {"namespace": "odoo", "entity": "res.partner"}


async def test_html5_byte_identical_with_relation():
    with_rel = await HTML5Renderer().render(_form(True))
    without = await HTML5Renderer().render(_form(False))
    assert with_rel.content == without.content
```

---

## Agent Instructions

1. Verify TASK-2411 is in `sdd/tasks/completed/`; read spec §3 Module 5 + §7 risks.
2. Verify the contract (jsonschema.py:510 area, RenderedForm shape) before coding.
3. Update index → `in-progress`; implement, test, lint.
4. Move this file to `sdd/tasks/completed/`, update index → `done`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
