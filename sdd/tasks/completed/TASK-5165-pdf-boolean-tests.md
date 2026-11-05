# TASK-5165: Tests — PDF boolean Yes / No choices

**Feature**: FEAT-800 — Form Designer — boolean questions render as Yes / No (HTML5 + PDF)
**Spec**: `sdd/specs/formdesigner-boolean-yes-no.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5163
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 / §4. Proves the PDF behaviour added by TASK-5163 by asserting on the generated PDF (fields and text), never on mocks of reportlab.

---

## Scope

- Create `tests/unit/renderers/test_pdf_boolean.py` with the three PDF tests in spec §4.

**NOT in scope**: source changes, HTML5 tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/unit/renderers/test_pdf_boolean.py` | CREATE | PDF boolean tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from io import BytesIO                                                          # stdlib
from pypdf import PdfReader                                                    # verified: tests/unit/renderers/test_pdf.py:7
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection  # verified: test_pdf.py:10-15
from parrot_formdesigner.core.types import FieldType                           # verified: test_pdf.py:16
from parrot_formdesigner.renderers.pdf import PdfRenderer                      # verified: test_pdf.py:19
```

### Existing Signatures to Use
```python
async PdfRenderer().render(form, prefilled=...?) -> RenderedForm   # `.content` = PDF bytes (test_pdf.py:63-68); confirm the prefilled kwarg name in pdf.py `render` (line 170)
PdfReader(BytesIO(out.content)).get_fields() -> dict   # field name → field object; radio groups appear under the shared name
PdfReader(...).pages[i].extract_text() -> str
```
Async tests need no decorator here (bare `async def`, as in `test_pdf.py`).

### Does NOT Exist
- ~~`PdfRenderer.render_boolean`~~ — no such method.
- ~~mocking `canvas.acroForm`~~ — forbidden by the spec: assert on the generated PDF.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/tests/unit/renderers/test_pdf_boolean.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Radio group inspection: `fields["has_signage"]` yields the parent field; its `/Kids` hold the widgets, each with an appearance-state name (`/AP` `/N` keys other than `/Off`) equal to the radio `value` (`true`/`false`) — inspect with `reader.trailer["/Root"]["/AcroForm"]["/Fields"]` and `get_object()`; confirm the exact keys empirically on a generated PDF before asserting.
- The selected state is the parent's `/V` (e.g. `/true`) — verify empirically.
- Assert checkbox absence by checking the group's `/Ff` radio flag (bit 16, value 32768) is set.

---

## Implementation Blueprint

### Steps (in order)
1. Generate one PDF per scenario and dump its field structure once (`print` is fine in an ad-hoc shell, not in the test) — *why*: pins the exact pypdf keys before asserting.
2. Write the three tests — *why*: spec §4 M4 rows.

### `tests/unit/renderers/test_pdf_boolean.py` (CREATE)
```python
"""Unit tests for PDF boolean Yes/No radios (FEAT-800)."""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.pdf import PdfRenderer


def _form(required: bool = False) -> FormSchema:
    field = FormField(field_id="has_signage", field_type=FieldType.BOOLEAN, label={"en": "Has signage?"}, required=required)
    return FormSchema(form_id="t", title={"en": "T"}, sections=[FormSection(section_id="s", fields=[field])])


async def _reader(prefilled: dict | None = None) -> PdfReader:
    out = await PdfRenderer().render(_form(), prefilled=prefilled)  # FILL IN: confirm kwarg name — bounded by pdf.py render() signature
    return PdfReader(BytesIO(out.content))


async def test_pdf_boolean_has_yes_no_choices():
    reader = await _reader()
    # FILL IN: group "has_signage" exists, is a radio group (Ff bit 32768), has exactly two kids with states true/false,
    # page text contains "Yes" and "No" — bounded by spec AC "Yes and No choices, never a lone checkbox"
    ...


async def test_pdf_boolean_prefill_false_not_selected_yes():
    reader = await _reader({"has_signage": False})
    # FILL IN: group value /V selects "false", never "true" — bounded by the bool("False") bug note in spec §7
    ...


async def test_pdf_boolean_none_selects_nothing():
    reader = await _reader()
    # FILL IN: no selected value (/V absent or /Off) — bounded by spec §2 "nothing selected without prefill"
    ...
```
**Why this shape**: three scenarios map 1:1 to spec §4 M4 rows; replace every `...` with real assertions (a `...`-only test is a defect).

### FILL IN checklist
- [ ] the three tests have real assertions on generated PDF fields/text.

---

## Acceptance Criteria

- [ ] Three PDF tests present and passing against TASK-5163
- [ ] No reportlab mocks; `ruff check` clean; no test body left as `...`

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/renderers/test_pdf_boolean.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/renderers/test_pdf.py -q`

---

## Test Specification

See blueprint; list is spec §4 (Module 4 rows).

---

## Agent Instructions

Standard procedure; run with `PYTHONPATH=packages/parrot-formdesigner/src`; per-package pytest only; close with `parrot sdd task close TASK-5165 formdesigner-boolean-yes-no verified`.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet, sequential, no coder seats)
**Date**: 2026-11-04
**Notes**: Created test_pdf_boolean.py (5 tests, pypdf). Mutation-checked: stringified prefill, always-required, single radio, None→true go RED; weak `No` substring assertion tightened to word match after a surviving mutant. Note: `pypdf` (declared dev dep) was missing in the worktree .venv; installed there with `uv pip install --python .venv/bin/python`.

**Deviations from spec**: none | describe if any
