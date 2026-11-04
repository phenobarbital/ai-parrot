# TASK-5163: PDF renderer — BOOLEAN prints Yes / No radio choices

**Feature**: FEAT-800 — Form Designer — boolean questions render as Yes / No (HTML5 + PDF)
**Spec**: `sdd/specs/formdesigner-boolean-yes-no.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2 (decision D2). `PdfRenderer._render_field` emits a single bare
`form.checkbox(...)` for BOOLEAN; it must emit two AcroForm radio buttons of one group with `Yes` / `No`
labels. It also carries a latent bug: prefill is stringified, so `bool("False")` is `True`.

---

## Scope

- Add a module-level `_boolean_selected(raw) -> str` helper in `pdf.py` (do NOT import from html5.py — renderers stay independent).
- Replace the BOOLEAN branch body with two `form.radio(...)` widgets (same `name`, values `"true"`/`"false"`) plus `c.drawString` text `Yes` / `No`.
- Use the RAW prefilled value (`prefilled[field.field_id]`), not `prefilled_value`.

**NOT in scope**: HTML5 (TASK-5162), tests (TASK-5165), other field types, `_UNSUPPORTED_TYPES`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py` | MODIFY | BOOLEAN → two radios + labels |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from reportlab.lib.units import mm          # verified: pdf.py:22
from reportlab.pdfgen import canvas         # verified: pdf.py:23
from typing import Any                      # verified: pdf.py:19
from ..core.types import FieldType          # verified: pdf.py:35
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py
def PdfRenderer._render_field(self, c: canvas.Canvas, section_id, field: FormField, cursor_y: float, locale, prefilled: dict[str, Any] | None, unsupported, render_warnings=None) -> float   # line 325
# in scope inside the method: label (str), form = c.acroForm, x = self.MARGIN_X, y = cursor_y, width, height,
#   _has_prefilled = bool(prefilled) and field.field_id in prefilled   (line ~351), prefilled_value (str, stringified)
elif field.field_type == FieldType.BOOLEAN:      # line 394
    form.checkbox(name=field.field_id, tooltip=label, x=x, y=y, size=4 * mm, checked=bool(prefilled_value))   # 395-401
# class constants: MARGIN_X = 20*mm, LINE_HEIGHT = 6*mm, FIELD_WIDTH = 160*mm, FIELD_HEIGHT = 8*mm  (pdf.py:130-135)
# reportlab 4.1.0: acroForm.radio(value=None, selected=False, buttonStyle='circle', shape='circle', ..., size=20, x=0, y=0,
#                   tooltip=None, name=None, annotationFlags='print', fieldFlags='noToggleToOff required radio', ...)
```

### Does NOT Exist
- ~~`form.radiogroup(...)`~~ — reportlab has only `radio()`; a group is formed by repeating the same `name`.
- ~~`PdfRenderer._boolean_selected`~~ — the helper is module-level and new.
- ~~`renderers.base` boolean helper~~ — none exists; do not import one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py#PdfRenderer"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `radio()` default `fieldFlags` contains `required` — pass `fieldFlags="noToggleToOff radio"` and append `" required"` only when `field.required`.
- Prefill comes from the raw mapping because `bool("False")` is `True`.
- Lay the two choices on the field line: radio #1 at `x`, its text right of it, radio #2 offset (e.g. +30 mm); text via `c.setFont("Helvetica", 10)` then `c.drawString`. Keep inside the page width.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_boolean_selected` near `_localize` (module level) — *why*: pure helper, unit-testable.
2. Replace the BOOLEAN branch body — *why*: D2 requires two labelled choices.
3. Run the existing PDF tests — *why*: the `test_pdf.py` fixture contains a BOOLEAN.

### `pdf.py` — helper (MODIFY)
```python
# AFTER the `def _localize(` function (anchor `def _localize(value: LocalizedString | None, locale: str, default: str = "") -> str:`
# occurrences: verify with grep -c -F 'def _localize(' pdf.py (expected 1), line 99) — insert below its body:
def _boolean_selected(raw: Any) -> str:
    """Return ``"true"``, ``"false"`` or ``""`` for a raw (unstringified) prefilled boolean.

    Args:
        raw: Prefilled value (bool, int, str or None).

    Returns:
        ``"true"`` for True/"true"/"True"/1/"1"; ``"false"`` for False/"false"/"False"/0/"0"; else ``""``.
    """
    # FILL IN: check bool/int/str forms — bounded by "False must never select Yes; None selects nothing"
    raise NotImplementedError
```

### `pdf.py` — BOOLEAN branch (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'elif field.field_type == FieldType.BOOLEAN:' pdf.py), line 394
# Replace the whole branch body (the form.checkbox(...) call, lines 395-401) with:
        elif field.field_type == FieldType.BOOLEAN:
            selected = _boolean_selected(prefilled.get(field.field_id) if prefilled else None)
            flags = "noToggleToOff radio" + (" required" if field.required else "")
            size = 4 * mm
            c.setFont("Helvetica", 10)
            for idx, (value, text) in enumerate((("true", "Yes"), ("false", "No"))):
                cx = x + idx * 30 * mm
                form.radio(
                    name=field.field_id,
                    value=value,
                    selected=(selected == value),
                    x=cx,
                    y=y,
                    size=size,
                    tooltip=f"{label}: {text}",
                    fieldFlags=flags,
                )
                c.drawString(cx + size + 2 * mm, y + 0.8 * mm, text)
```
**Why**: two radios sharing `name` form one AcroForm radio group; the drawn text makes `Yes`/`No` visible in print and extractable by `pypdf`. Raw prefill avoids the `bool("False")` bug.

### FILL IN checklist
- [ ] `_boolean_selected` body — bounded by the value table in spec §2.
- [ ] Verify the text baseline offset renders aligned (cosmetic; `y + 0.8*mm` is a starting value) — bounded by "no overlap with radio widget".

---

## Acceptance Criteria

- [ ] BOOLEAN yields a radio group with Yes and No kids and visible `Yes`/`No` text; no lone checkbox
- [ ] Prefilled `False` selects No (not Yes); no prefill selects neither
- [ ] `required` flag only when `field.required`
- [ ] Existing `test_pdf.py` passes; `ruff check` clean on `pdf.py`

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/renderers/test_pdf.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_renderers.py -q`

---

## Test Specification

Written in TASK-5165. Smoke: render a one-field form with `FieldType.BOOLEAN` and confirm `PdfReader(...).get_fields()` contains the field id.

---

## Agent Instructions

Standard procedure: worktree via `parrot sdd worktree ensure`, verify contract, mark `in-progress` in `sdd/tasks/index/formdesigner-boolean-yes-no.json`, implement from the blueprint, run Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`, commit only the listed file, close with `parrot sdd task close TASK-5163 formdesigner-boolean-yes-no verified`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
