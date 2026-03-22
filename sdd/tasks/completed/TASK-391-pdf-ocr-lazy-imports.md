# TASK-391: Document/PDF/OCR Tools Lazy Imports

**Feature**: runtime-dependency-reduction
**Spec**: `sdd/specs/runtime-dependency-reduction.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-386, TASK-387
**Assigned-to**: unassigned

---

## Context

PDF export (weasyprint), document conversion (markitdown), and OCR (pytesseract) tools currently import heavy dependencies at module level. These require system libraries (cairo/pango for weasyprint, tesseract for pytesseract) that make the base install fragile. Moving them to lazy imports lets users install only what they need.

Implements: Spec Module 6 — Document/PDF/OCR Tools Lazy Imports.

---

## Scope

- Convert top-level imports to `lazy_import()` in:
  - `parrot/tools/pdfprint.py` — weasyprint, fpdf → `lazy_import(..., extra="pdf")`
  - `parrot/tools/file_reader.py` — markitdown → `lazy_import(..., extra="pdf")`
  - `parrot/tools/sitesearch/tool.py` — markitdown → `lazy_import(..., extra="pdf")`
  - `parrot/tools/google/tools.py` — markitdown → `lazy_import(..., extra="pdf")`
  - `parrot/tools/ibisworld/tool.py` — markitdown → `lazy_import(..., extra="pdf")`
- Standardize lazy patterns in loaders that already have partial lazy imports:
  - `parrot/loaders/pdfmark.py` — standardize to use `lazy_import()`
  - `parrot/loaders/pdftables.py` — standardize
  - `parrot/loaders/ppt.py` — standardize
  - `parrot/loaders/markdown.py` — standardize

**NOT in scope**: pytesseract in clients (TASK-388). ML/embeddings (TASK-392).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/pdfprint.py` | MODIFY | Lazy-import weasyprint, fpdf |
| `parrot/tools/file_reader.py` | MODIFY | Lazy-import markitdown |
| `parrot/tools/sitesearch/tool.py` | MODIFY | Lazy-import markitdown |
| `parrot/tools/google/tools.py` | MODIFY | Lazy-import markitdown |
| `parrot/tools/ibisworld/tool.py` | MODIFY | Lazy-import markitdown |
| `parrot/loaders/pdfmark.py` | MODIFY | Standardize lazy import pattern |
| `parrot/loaders/pdftables.py` | MODIFY | Standardize lazy import pattern |
| `parrot/loaders/ppt.py` | MODIFY | Standardize lazy import pattern |
| `parrot/loaders/markdown.py` | MODIFY | Standardize lazy import pattern |

---

## Implementation Notes

### Pattern to Follow
```python
from parrot._imports import lazy_import

class PDFPrinter:
    def print_pdf(self, html: str) -> bytes:
        weasyprint = lazy_import("weasyprint", extra="pdf")
        return weasyprint.HTML(string=html).write_pdf()
```

### Key Constraints
- weasyprint requires cairo/pango — must not be imported at module level
- markitdown is used in 4+ tool files — consistent pattern across all
- Loaders already have partial lazy imports — standardize to use `parrot._imports`

---

## Acceptance Criteria

- [ ] All listed tool files importable without weasyprint/markitdown/fpdf
- [ ] All listed loader files importable without markitdown
- [ ] PDF export works when weasyprint is installed
- [ ] Missing dep raises: `pip install ai-parrot[pdf]`
- [ ] All existing tests pass with deps installed

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-386 and TASK-387 are completed
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Read each file** before modifying
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-391-pdf-ocr-lazy-imports.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
