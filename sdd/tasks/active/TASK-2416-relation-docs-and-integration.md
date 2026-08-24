# TASK-2416: Relation Documentation + End-to-End Integration Tests

**Feature**: FEAT-456 — Relational Field Cardinality for parrot-formdesigner
**Spec**: `sdd/specs/formbuilder-fieldtype-cardinality.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2412, TASK-2413, TASK-2414, TASK-2415
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 + §4 Integration Tests. Closes the feature: documents the
relation aspect and proves the whole pipeline (YAML → extract → resolve →
render → validate) end to end, including persisted-schema backward
compatibility.

---

## Scope

- Docs: add a "Relational Fields" page/section to the formdesigner docs
  covering: the `relation` aspect, the legal-combination table (spec §2),
  namespace conventions (`odoo`/`db`/`api`/`formdesigner` — documented, not
  enforced), embed vs reference semantics, `on_delete` as passthrough hint,
  the renderer no-op convention, and a YAML + x-relation example each.
- Integration test `test_relational_form_end_to_end`: YAML fixture with all
  three relation kinds (Many2one SELECT, Many2many MULTI_SELECT, One2many
  ARRAY embed) → extract → `resolve_rule_references` → render html +
  jsonschema → validate a good and a bad submission. Only the jsonschema
  output differs from a non-relational baseline.
- Integration test `test_persisted_schema_backcompat`: a stored
  pre-FEAT-456 FormSchema JSON (fixture dict, no `relation` keys) loads,
  renders, and validates unchanged.
- Update `packages/parrot-formdesigner/` CHANGELOG/release notes if the
  package keeps one (check; note the one-directional forward-compat caveat
  from spec §7: old readers reject schemas carrying `relation`).

**NOT in scope**: new functionality of any kind; mkdocs nav restructuring
beyond adding the page.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/` (formdesigner section — locate existing formdesigner docs first) | CREATE/MODIFY | "Relational Fields" documentation |
| `packages/parrot-formdesigner/tests/integration/test_relational_forms.py` | CREATE | end-to-end + backcompat tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core import EntityRef, RelationSpec       # exported by TASK-2411
from parrot_formdesigner.core.resolution import resolve_rule_references  # core/resolution.py:28
from parrot_formdesigner.extractors.yaml import YamlExtractor      # extract(content) -> FormSchema (yaml.py:131)
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
from parrot_formdesigner.services.validators import FormValidator  # validators.py:101
```

### Existing Signatures to Use
```python
# All renderers: async render(form, style=None, *, locale="en", prefilled=None,
#                              errors=None) -> RenderedForm   (renderers/base.py)
# FormValidator.validate(form, data, *, locale="en", ...) -> ValidationResult
#                                                     (validators.py:122)
# Integration-test precedent: packages/parrot-formdesigner/tests/integration/
#   test_render_xml.py (TASK-1045) — aiohttp-app-free direct renderer tests OK.
```

### Does NOT Exist
- ~~A dedicated formdesigner docs site section named "Relational Fields"~~ —
  created by this task; grep `mkdocs.yml` + `docs/` for where formdesigner
  pages live before placing it.
- ~~Odoo renderer / FK extractor~~ — do NOT document them as existing; refer
  to them as planned consumers only.
- ~~Autocomplete/paginated search~~ — document the OptionsSource snapshot
  limitation explicitly.

---

## Implementation Notes

### Key Constraints
- The backcompat fixture must be a RAW dict/JSON (as storage would return),
  not built via current models — that's the point of the test.
- The end-to-end YAML fixture doubles as documentation example — keep them
  literally identical (single source, referenced from the docs page).
- Documentation follows the existing docs tone; add the page to mkdocs nav
  (note repo gotcha: `.gitignore` line 245 ignores `templates/`, unrelated
  but keep additions inside `docs/`).

---

## Acceptance Criteria

- [ ] Docs page exists, in mkdocs nav, with the combination table +
      namespaces + both authoring examples
- [ ] `test_relational_form_end_to_end` passes
- [ ] `test_persisted_schema_backcompat` passes
- [ ] Full feature suite green:
      `pytest packages/parrot-formdesigner/tests/ -v`
- [ ] All spec §5 acceptance criteria verifiably met (this is the closing
      task — walk the checklist and note each in the Completion Note)
- [ ] `ruff check` clean

---

## Test Specification

```python
# tests/integration/test_relational_forms.py — skeleton
import pytest
from parrot_formdesigner.extractors.yaml import YamlExtractor
from parrot_formdesigner.core.resolution import resolve_rule_references
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
from parrot_formdesigner.services.validators import FormValidator

RELATIONAL_YAML = "..."   # all three kinds; same fixture referenced by docs


async def test_relational_form_end_to_end():
    form = resolve_rule_references(YamlExtractor().extract(RELATIONAL_YAML))
    html = await HTML5Renderer().render(form)
    js = await JsonSchemaRenderer().render(form)
    # x-relation present in js for the three fields; html renders normally
    good = {"customer": "42", "tags": ["1", "2"],
            "lines": [{"order_id": "42", "qty": 1}]}
    bad = {"customer": ["42"], "tags": "1", "lines": [{"qty": "x"}]}
    assert (await FormValidator().validate(form, good)).valid
    assert not (await FormValidator().validate(form, bad)).valid


async def test_persisted_schema_backcompat():
    stored = {...}  # raw pre-FEAT-456 FormSchema dict, no `relation` keys
    # FormSchema(**stored) loads; renders; validates — unchanged behavior
```

---

## Agent Instructions

1. Verify TASK-2412..2415 are ALL in `sdd/tasks/completed/`.
2. Walk spec §5 acceptance criteria; anything unmet is a bug in a prior
   task — fix it there (note in Completion Note), don't paper over here.
3. Update index → `in-progress`; implement, test, lint.
4. Move this file to `sdd/tasks/completed/`, update index → `done` AND set
   the index header `completed_at`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
