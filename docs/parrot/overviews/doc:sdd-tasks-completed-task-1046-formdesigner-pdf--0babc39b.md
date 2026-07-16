---
type: Wiki Overview
title: 'TASK-1046: PDF AcroForm fillable renderer (`reportlab`)'
id: doc:sdd-tasks-completed-task-1046-formdesigner-pdf-renderer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wave 2b of FEAT-152 — parallelizable with TASK-1045 / 1047 / 1048.
---

# TASK-1046: PDF AcroForm fillable renderer (`reportlab`)

**Feature**: FEAT-152 — parrot-formdesigner Structural Refactor
**Spec**: `sdd/specs/formdesigner-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1044
**Assigned-to**: unassigned

---

## Context

Wave 2b of FEAT-152 — parallelizable with TASK-1045 / 1047 / 1048.

Adds a new `PdfRenderer` (subclass of `AbstractFormRenderer`) that
emits a fillable PDF (AcroForm) using `reportlab`. Registers under
the `"pdf"` key on the render dispatcher. Per Q4 (resolved): fields
not natively expressible in AcroForm (`FILE`, `IMAGE`, `ARRAY`,
`GROUP`) get a flat textfield placeholder + a form-level meta note
listing them.

Spec sections: §1 Goals (PDF AcroForm); §3 Module 7; §6 Codebase
Contract; §8 Q4 (resolved with the brainstorm recommendation).

---

## Scope

1. **Create** `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py`
   defining `class PdfRenderer(AbstractFormRenderer)` with
   `async def render(self, form, style=None, *, locale="en",
   prefilled=None, errors=None) -> RenderedForm`.
2. **Layout**: vertical single column, A4 portrait. Section header
   per `FormSection` (bold + horizontal rule). Per `FormField`: label
   above input, single-line.
3. **Field type mapping**:

   | FieldType | AcroForm element | Notes |
   |---|---|---|
   | TEXT, EMAIL, URL, PHONE, PASSWORD | `acroForm.textfield` | width ≈ 400pt |
   | NUMBER, INTEGER | `acroForm.textfield` | tooltip="number" |
   | TEXT_AREA | `acroForm.textfield(fieldFlags="multiline")` | height ≈ 60pt |
   | BOOLEAN | `acroForm.checkbox` | |
   | SELECT | `acroForm.choice` | options from `field.options` |
   | MULTI_SELECT | `acroForm.listbox(fieldFlags="multiSelect")` | |
   | DATE, DATETIME, TIME | `acroForm.textfield` | tooltip="date format hint" |
   | COLOR | `acroForm.textfield` | tooltip="hex color" |
   | HIDDEN | `acroForm.textfield(fieldFlags="hidden")` | |
   | FILE, IMAGE, ARRAY, GROUP | flat `acroForm.textfield` placeholder + form-level meta note | per Q4 |

4. **Unsupported-field meta note (Q4)**: collect every `field_id`
   whose type is in `{FILE, IMAGE, ARRAY, GROUP}`. After rendering all
   pages, draw a final paragraph at the bottom of the last page (or a
   new "Notes" page) titled "Fields not fillable in this PDF"
   listing each as `<section_id>.<field_id>`. Also include them in
   `RenderedForm.metadata` as
   `{"unsupported_fields": [{"section_id": ..., "field_id": ...,
   "field_type": ...}, ...]}`.
5. **Output**: `RenderedForm(content=<pdf-bytes>,
   content_type="application/pdf",
   metadata={"unsupported_fields": [...]})`.
6. **Wire into dispatcher**: extend `api/render.py:_seed_renderers`
   (or whatever the lazy-seed shape is after TASK-1045 lands) to
   register `PdfRenderer()` under `"pdf"`. Coordinate with TASK-1045
   on the wiring file — both tasks edit `api/render.py`. If TASK-1045
   has already landed, extend its `_seed_renderers` function. If
   TASK-1045 has not yet landed, follow the same lazy-seed pattern
   (see TASK-1045 §Implementation Notes).
7. **Tests** at `packages/parrot-formdesigner/tests/unit/renderers/test_pdf.py`:
   - Output has `content_type == "application/pdf"`.
   - Output is a valid PDF (parseable by `pypdf.PdfReader`).
   - AcroForm dict is present (`reader.trailer["/Root"]["/AcroForm"]`).
   - `FieldType.TEXT` field → AcroForm textfield with name == `field_id`.
   - `FieldType.BOOLEAN` field → AcroForm checkbox.
   - `FieldType.FILE` field → flat textfield placeholder + entry in
     `RenderedForm.metadata["unsupported_fields"]`.
8. **Integration test** at
   `packages/parrot-formdesigner/tests/integration/test_render_pdf.py`:
   - Boot aiohttp app, register a sample form, hit
     `GET /api/v1/forms/{id}/render/pdf`, verify response is a valid
     PDF with AcroForm.

**NOT in scope:**
- HTML→PDF static rendering (Non-Goal — `weasyprint` is rejected for
  V1).
- Multi-page form layout beyond simple "spill to next page" — V1 is
  vertical single-column; if content exceeds one page, `reportlab`'s
  `canvas.showPage()` flow is fine.
- Localization of labels beyond resolving `LocalizedString` to the
  given `locale`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py` | CREATE | `PdfRenderer` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | MODIFY | Register `pdf` under `"pdf"` |
| `packages/parrot-formdesigner/tests/unit/renderers/test_pdf.py` | CREATE | Unit tests |
| `packages/parrot-formdesigner/tests/integration/test_render_pdf.py` | CREATE | E2E |
| `packages/parrot-formdesigner/pyproject.toml` | MODIFY (test extra) | Add `pypdf>=6.0` to test extras |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_formdesigner.core.schema import (
    FormSchema, FormSection, FormField, RenderedForm,
)
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.base import AbstractFormRenderer
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py:14

from io import BytesIO
from reportlab.pdfgen import canvas         # already installed (4.1.0)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
```

### `reportlab` AcroForm API

```python
# Reportlab 4.1 — verified from docs.
c = canvas.Canvas(buffer, pagesize=A4)
form = c.acroForm
form.textfield(name="field_id", tooltip="...", x=20*mm, y=200*mm,
               width=160*mm, height=8*mm, fontSize=10)
form.checkbox(name="field_id", x=20*mm, y=200*mm, size=4*mm)
form.choice(name="field_id", options=[("Label", "value"), ...],
            x=20*mm, y=200*mm, width=160*mm, height=8*mm)
form.listbox(name="field_id", options=[...], x=..., y=..., ...)
c.showPage()
c.save()
```

`fieldFlags` examples: `"multiline"`, `"password"`, `"multiSelect"`,
`"hidden"` (or pass via the `fieldFlags=` kwarg).

### Does NOT Exist

- ~~`reportlab.acroform.PdfForm`~~ — that's pyfpdf's API. The
  `reportlab` API is `canvas.acroForm.<method>()`.
- ~~`pypdf.AcroFormReader`~~ — use `PdfReader(BytesIO(content))` and
  inspect `reader.trailer["/Root"].get("/AcroForm")`.
- ~~`AbstractFormRenderer.format_name`~~ — not on the base class.
- ~~`canvas.acroForm.upload(...)`~~ — there is no native AcroForm
  file-upload widget; that's why Q4's Non-Goal is a flat textfield
  placeholder.
- ~~A `pypdf` dep already in `pyproject.toml`~~ — verify; it may
  be transitive only. Add `pypdf>=6.0` to the test extras to make
  the test dep explicit.

---

## Implementation Notes

### Layout helper

A small layout helper that tracks `(x, y)` cursor and calls
`canvas.showPage()` when y < margin works fine. Keep it inside
`pdf.py`; don't over-engineer a layout engine.

### Locale resolution

Match the existing pattern in `html5.py`:

```python
def _localize(value: LocalizedString | None, locale: str, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return value.get(locale) or value.get("en") or next(iter(value.values()), default)
```

Same helper or a copy is fine; don't refactor to a shared utility in
this task — out of scope.

### Key Constraints

- Async signature required even though body is sync. Wrap in
  `await asyncio.to_thread(...)` if profiling shows > 50 ms.
- `RenderedForm.content` is `bytes` (PDF). The dispatcher passes it
  to `web.Response(body=..., content_type="application/pdf")`.
- Logger: `logger = logging.getLogger(__name__)` at module top; log
  warnings when an unsupported field is downgraded to a placeholder.

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.renderers.pdf import PdfRenderer`
      succeeds.
- [ ] `PdfRenderer` is a subclass of `AbstractFormRenderer`.
- [ ] `await PdfRenderer().render(form)` returns
      `RenderedForm(content=<bytes>, content_type="application/pdf")`.
- [ ] Returned bytes parse via `pypdf.PdfReader(BytesIO(content))`.
- [ ] `reader.trailer["/Root"]["/AcroForm"]` exists.
- [ ] `FieldType.TEXT` field → AcroForm textfield with name ==
      `field_id`.
- [ ] `FieldType.BOOLEAN` field → AcroForm checkbox.
- [ ] `FieldType.SELECT` field → AcroForm choice with one entry per
      option.
- [ ] `FieldType.FILE` / `IMAGE` / `ARRAY` / `GROUP` field →
      placeholder textfield + the field listed in
      `RenderedForm.metadata["unsupported_fields"]`.
- [ ] After wiring, `GET /api/v1/forms/{id}/render/pdf` returns 200
      with `Content-Type: application/pdf`.
- [ ] All unit tests in `tests/unit/renderers/test_pdf.py` pass.
- [ ] Integration test passes:
      `pytest packages/parrot-formdesigner/tests/integration/test_render_pdf.py -v`.
- [ ] Metadata-only init test (TASK-1044) still green — `__init__.py`
      does NOT pull `pdf.py` or `reportlab`.
- [ ] No linting errors.

---

## Test Specification

```python
# tests/unit/renderers/test_pdf.py
import pytest
from io import BytesIO
from pypdf import PdfReader
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.pdf import PdfRenderer


@pytest.fixture
def form_with_unsupported() -> FormSchema:
    return FormSchema(
        form_id="t", title={"en": "T"},
        sections=[FormSection(section_id="s", fields=[
            FormField(field_id="name", field_type=FieldType.TEXT,
                      label={"en": "Name"}),
            FormField(field_id="active", field_type=FieldType.BOOLEAN,
                      label={"en": "Active"}),
            FormField(field_id="avatar", field_type=FieldType.FILE,
                      label={"en": "Avatar"}),
        ])],
    )


async def test_returns_pdf(form_with_unsupported):
    out = await PdfRenderer().render(form_with_unsupported)
    assert out.content_type == "application/pdf"
    reader = PdfReader(BytesIO(out.content))
    assert len(reader.pages) >= 1


async def test_acroform_present(form_with_unsupported):
    out = await PdfRenderer().render(form_with_unsupported)
    reader = PdfReader(BytesIO(out.content))
    root = reader.trailer["/Root"]
    assert "/AcroForm" in root


async def test_unsupported_field_listed_in_meta(form_with_unsupported):
    out = await PdfRenderer().render(form_with_unsupported)
    unsupported = out.metadata["unsupported_fields"]
    types = {f["field_type"] for f in unsupported}
    assert "file" in types
```

---

## Agent Instructions

1. Read the spec, especially Module 7 + §8 Q4.
2. Verify TASK-1044 (Wave 1 finalize) is in `tasks/completed/`.
3. If TASK-1045 (xforms) has already landed and refactored
   `api/render.py` to use `_seed_renderers`, extend that helper.
   Otherwise, set up the lazy-seed pattern yourself per
   TASK-1045 §Implementation Notes.
4. Read `reportlab` AcroForm docs / source if any kwarg is unclear.
5. Move this task to `sdd/tasks/completed/`, update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-05-07
**Notes**:
- Created `parrot_formdesigner/renderers/pdf.py` with `PdfRenderer(AbstractFormRenderer)`. Uses `reportlab.pdfgen.canvas.Canvas` + `canvas.acroForm` for fillable PDF output. A4 portrait, single-column vertical layout with section headers and label-above-input.
- Field-type → AcroForm mapping per spec:
  - `TEXT/NUMBER/INTEGER/EMAIL/URL/PHONE/DATE/DATETIME/TIME/COLOR` → `acroForm.textfield`
  - `TEXT_AREA` → `textfield(fieldFlags="multiline")`
  - `BOOLEAN` → `checkbox`
  - `SELECT` → `choice`
  - `MULTI_SELECT` → `listbox(fieldFlags="multiSelect")`
  - `PASSWORD` → `textfield(fieldFlags="password")`
  - `HIDDEN` → `textfield(fieldFlags="hidden")`
- **Q4 RESOLVED**: `FILE`/`IMAGE`/`ARRAY`/`GROUP` get a flat textfield placeholder + form-level meta note ("Fields not fillable in this PDF (use the web UI):") + listed in `RenderedForm.metadata["unsupported_fields"]`.
- Multi-page support via `_maybe_new_page` helper that calls `canvas.showPage()` when content overflows the bottom margin.
- Wired into `api/render.py:_seed_default_renderers` under `"pdf"` (alongside the xforms wiring from TASK-1045).
- All 9 unit tests pass; 1 integration test passes (E2E via `setup_form_api` dispatcher).
- Test extras already include `pypdf>=6.0` (added in TASK-1040).
- Metadata-only init contract (TASK-1044) verified still green.
