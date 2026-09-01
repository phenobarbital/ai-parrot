# TASK-2713: PDFRenderer forces the print layout + empirical WeasyPrint verification

**Feature**: FEAT-493 — Backend HTML Design System
**Spec**: `sdd/specs/html-renderer-design-system.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2708, TASK-2709
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. `PDFRenderer` subclasses `SSRHTMLRenderer` (`pdf.py:99`)
and builds its intermediate HTML through it (`:135`), so it silently
inherits whatever stylesheet SSR uses. After TASK-2709 that is the
`analytics` layout — screen-oriented, with shadows and `auto-fit` grids.
This task forces `print` and, more importantly, **establishes empirically
what WeasyPrint 69.0 actually renders** instead of assuming.

Spec §7 flags this explicitly: WeasyPrint CSS support is not assumable, and
the answer must come from running it.

---

## Scope

- `PDFRenderer` composes with `layout="print"` unconditionally — forced in
  the class, not left to a constructor default a caller could override into
  a screen layout by accident.
- Run a real WeasyPrint 69.0 render over a representative document (KPI grid
  + chart placeholder + a multi-page table) and record, in the completion
  note and in a short `docs/` note, which of these actually work:
  CSS grid, `repeat(auto-fit, minmax(...))`, flexbox, `position: sticky`,
  `break-inside: avoid`, `@page` margins, and `box-shadow`.
- Adjust `layout-print.css` based on those findings — this is the task that
  turns TASK-2708's defensive avoidance into a verified choice.
- Confirm the PDF pipeline still produces a valid PDF, and that the
  `a2ui-pdf` extra's actionable `ImportError` path is untouched.

**NOT in scope**: changing `SSRHTMLRenderer`'s own default (TASK-2709 owns
it); authoring `layout-print.css` from scratch (TASK-2708 created it);
paginated table logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../a2ui_renderers/pdf.py` | MODIFY | Force `layout="print"` |
| `.../formats/assets/design_system/layout-print.css` | MODIFY | Adjust per empirical findings |
| `docs/weasyprint-css-support.md` | CREATE | Recorded findings for WeasyPrint 69.0 |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf_print_layout.py` | CREATE | Print-layout + valid-PDF tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer       # line 25
    supported_components=SSRHTMLRenderer.capabilities.supported_components - {"Video", "AudioPlayer"}  # line 96
class PDFRenderer(SSRHTMLRenderer):                # line 99
    """Inherits SSRHTMLRenderer's v1.0 dispatch/reconstruction wholesale"""   # line 102
    async def render(self, ...)                    # line 113
        # line 121: document, degraded = await self._build_intermediate_html(envelope, deep_links=deep_links)
        # line 151: html_cls = _load_weasyprint()
        # line 152: return html_cls(string=document).write_pdf()
    async def _build_intermediate_html(self, envelope, *, deep_links=None) -> tuple[str, list[dict]]: ...  # line 135
```

### The pinned WeasyPrint version — verify against THIS, not against latest docs

```toml
packages/ai-parrot/pyproject.toml:199                "weasyprint==69.0"
packages/ai-parrot-visualizations/pyproject.toml:60  "weasyprint>=68.0"
packages/ai-parrot-tools/pyproject.toml:40           "weasyprint==69.0"
packages/ai-parrot-loaders/pyproject.toml:64         "weasyprint==69.0"
```

Confirmed installed in the project venv: `weasyprint 69.0`.

### An existing test to keep passing

```
packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf.py:64
    assert "ai-parrot-visualizations[a2ui-pdf]" in str(exc.value)
```

The actionable-`ImportError` behaviour for a missing extra must survive.

### Does NOT Exist

- ~~`PDFRenderer._STYLE`~~ — it never had its own; it inherits SSR's, which is precisely the problem this task addresses
- ~~a `@media print` block anywhere today~~ — the codebase has no print CSS at all before this feature
- ~~`weasyprint.CSS(...)` usage in this renderer~~ — the pipeline passes a single HTML string (`:152`, `write_pdf()`); CSS arrives inline in that string
- ~~a PDF golden/snapshot fixture~~ — none exists; assert structural validity, not bytes
- ~~documented WeasyPrint capability notes in this repo~~ — this task creates the first

---

## Implementation Notes

### How to verify rather than assume

Render a probe document per feature and inspect the resulting PDF (page
count, and whether elements land where the CSS asked). A feature that
silently degrades — a grid collapsing to stacked blocks, say — is a *finding*
to record, not a failure to hide. Write down what you observed, including
negatives; the value of `docs/weasyprint-css-support.md` is that the next
person does not repeat this.

### Key Constraints

- Force the layout in `PDFRenderer`, so no caller can accidentally get a
  screen stylesheet in a PDF.
- Keep `_build_intermediate_html`'s `tuple[str, list[dict]]` contract intact;
  the degradation list is part of the artifact metadata.
- Do not add a WeasyPrint stylesheet argument — CSS travels inline.

### References in Codebase

- `.../pdf.py:99-152` — the inheritance and the WeasyPrint call
- `.../formats/assets/design_system/layout-print.css` — the file being tuned

---

## Acceptance Criteria

- [ ] `PDFRenderer` composes with `layout="print"` and cannot be constructed into a screen layout
- [ ] `docs/weasyprint-css-support.md` records observed behaviour for grid, `auto-fit`/`minmax`, flexbox, `position: sticky`, `break-inside`, `@page`, and `box-shadow` under 69.0, including negative results
- [ ] `layout-print.css` uses only constructs the findings confirm
- [ ] A representative envelope renders to a valid, non-empty PDF
- [ ] A multi-page table does not split a row across pages
- [ ] `test_pdf.py:64` passes unmodified
- [ ] Tests pass: `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf*.py -v`

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf_print_layout.py
import pytest


class TestPdfPrintLayout:
    async def test_pdf_forces_print_layout(self):
        """The intermediate HTML must carry the print sheet, never analytics."""

    async def test_intermediate_html_has_no_shadows(self): ...
    async def test_intermediate_html_has_no_auto_fit(self): ...
    async def test_produces_valid_pdf(self):
        """Non-empty output starting with the %PDF- magic bytes."""
    async def test_multipage_table_rows_not_split(self): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 6, §7 — "WeasyPrint CSS support is not
   assumable").
2. **Check dependencies** — TASK-2708 and TASK-2709 must be completed.
3. **Verify the Codebase Contract** — in particular that `PDFRenderer` still
   subclasses `SSRHTMLRenderer` and that the installed WeasyPrint is 69.0.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** per scope. Run the probes; record what you actually saw,
   including anything that did not work.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`, update the index → `"done"`,
   fill in the Completion Note **with the empirical findings summarised**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**WeasyPrint 69.0 findings**:

**Deviations from spec**: none | describe if any
