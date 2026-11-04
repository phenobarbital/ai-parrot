# TASK-5164: Tests — HTML5 boolean Yes / No radios

**Feature**: FEAT-800 — Form Designer — boolean questions render as Yes / No (HTML5 + PDF)
**Spec**: `sdd/specs/formdesigner-boolean-yes-no.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5162
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 / §4. Proves the HTML5 behaviour added by TASK-5162 and guards the SELECT `render_as: radio` output against regression.

---

## Scope

- Create `tests/unit/renderers/test_html5_boolean.py` covering every HTML5 case listed in spec §4.
- Capture the SELECT radio golden string from the code as it is on `origin/dev` BEFORE TASK-5162 (or compute it by rendering a SELECT radio and asserting its exact markup shape built by hand from the contract below).

**NOT in scope**: source changes, PDF tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/unit/renderers/test_html5_boolean.py` | CREATE | HTML5 boolean tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.options import FieldOption                      # verified: tests/unit/renderers/test_pdf.py:9
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection  # verified: tests/unit/renderers/test_pdf.py:10-15
from parrot_formdesigner.core.types import FieldType                          # verified: tests/unit/renderers/test_pdf.py:16
from parrot_formdesigner.renderers.html5 import HTML5Renderer                 # verified: tests/unit/test_renderers.py (HTML5Renderer() used at ~l.185)
```

### Existing Signatures to Use
```python
# renderers/html5.py (after TASK-5162)
HTML5Renderer._render_boolean_radio_group(self, field, value, locale) -> str
HTML5Renderer._render_radio_group(self, field, value, locale, options=None) -> str
async HTML5Renderer.render(form, ...) -> RenderedForm   # `.content` holds the HTML (verify exact kwarg names in tests/unit/test_renderers.py)
# FormField(field_id=..., field_type=..., label=..., required=..., options=[...], meta={"render_as": "radio"}, depends_on=...)
```
Async tests run without a decorator in this package (see `tests/unit/renderers/test_pdf.py`: bare `async def test_...`); mirror that.

### Does NOT Exist
- ~~`tests/unit/renderers/conftest.py` boolean fixtures~~ — define fixtures in the new file.
- ~~An existing html5 test asserting `type="checkbox"` for BOOLEAN~~ — none (grep verified), nothing to update.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/tests/unit/renderers/test_html5_boolean.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Build forms with `FormSchema(form_id=..., title={"en": ...}, sections=[FormSection(section_id=..., fields=[...])])` as in `test_pdf.py`; render via `await HTML5Renderer().render(form, prefilled=...)` (confirm the signature in `renderers/html5.py` `render`) and assert on `out.content`, using `re`/substring counts (no HTML parser dependency needed).
- `depends_on` uses `parrot_formdesigner.core.constraints.DependencyRule` — read its constructor before using it (not listed here as verified).

---

## Implementation Blueprint

### Steps (in order)
1. Read `HTML5Renderer.render` signature — *why*: the exact prefilled kwarg name drives every test.
2. Write the fixtures and tests — *why*: spec §4 table.
3. Add the SELECT regression test with an exact expected substring — *why*: guards the shared markup.

### `tests/unit/renderers/test_html5_boolean.py` (CREATE)
```python
"""Unit tests for HTML5 boolean Yes/No radios (FEAT-800)."""
from __future__ import annotations

import pytest

from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.html5 import HTML5Renderer


def _form(*fields: FormField) -> FormSchema:
    return FormSchema(form_id="t", title={"en": "T"}, sections=[FormSection(section_id="s", fields=list(fields))])


@pytest.fixture
def boolean_field() -> FormField:
    return FormField(field_id="has_signage", field_type=FieldType.BOOLEAN, label={"en": "Has signage?"})


async def _html(field: FormField, prefilled: dict | None = None) -> str:
    out = await HTML5Renderer().render(_form(field), prefilled=prefilled)  # FILL IN: confirm kwarg name — bounded by render() signature
    return out.content if isinstance(out.content, str) else out.content.decode()


async def test_boolean_renders_two_radios_yes_no(boolean_field):
    html = await _html(boolean_field)
    # FILL IN: assert 2 × 'type="radio"', values "true"/"false", labels Yes/No, no 'type="checkbox"' — AC-1
    ...

# FILL IN: remaining tests, one per row of spec §4 Unit Tests for M3:
#   test_boolean_none_checks_nothing, test_boolean_true_checks_yes, test_boolean_false_checks_no
#   (parametrize True/"true"/"True"/1/"1" and False/"false"/"False"/0/"0"), test_boolean_required_on_radios,
#   test_boolean_label_once (count of "Has signage?" == 1), test_boolean_depends_on_emitted,
#   test_boolean_registry_path_matches (await the registry FieldRenderer for BOOLEAN — locate it as html5.py `_build_registry`),
#   test_select_radio_unchanged (SELECT meta render_as=radio: exact markup of one option label+input)
```
**Why this shape**: tests assert on rendered output of the public `render()` (plus the registry renderer) rather than mocking internals. Replace the `...` placeholder with real assertions — a test containing only `...` is a defect.

### FILL IN checklist
- [ ] every test in spec §4 for M3 has real assertions.

---

## Acceptance Criteria

- [ ] All M3 tests from spec §4 present and passing against TASK-5162's implementation
- [ ] `ruff check` clean; no test body left as `...`

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/renderers/test_html5_boolean.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_renderers.py -q`

---

## Test Specification

See blueprint; the test list is spec §4 (Module 3 rows).

---

## Agent Instructions

Standard procedure; run with `PYTHONPATH=packages/parrot-formdesigner/src`; per-package pytest only; close with `parrot sdd task close TASK-5164 formdesigner-boolean-yes-no verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
