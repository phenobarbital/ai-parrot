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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: `PDFRenderer.__init__(self, *, theme: str = "light")` now always
calls `super().__init__(theme=theme, layout="print")` — `layout` is not a
parameter of `PDFRenderer`'s own constructor at all, so
`PDFRenderer(layout="analytics")` raises `TypeError` (verified by a new
test), satisfying "forced in the class, not left to a constructor default
a caller could override... by accident" literally rather than just by
convention. `_build_intermediate_html`'s `tuple[str, list[dict]]` contract
and the `a2ui-pdf` extra's actionable `ImportError` path are untouched
(`test_pdf.py:64` re-verified passing unmodified).

Tests: this task's new
`packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf_print_layout.py`
(6 tests) passes; the full `packages/ai-parrot-visualizations/tests/`
suite (205 tests) passes, including the pre-existing
`test_design_system_layouts.py::TestPrintLayout` (TASK-2708) which
specifically asserts `"auto-fit" not in css` and `"minmax" not in css` for
the print stylesheet — this meant `layout-print.css`'s new descriptive
comments had to avoid those exact literal tokens (rephrased to avoid
`auto-fit`/`auto-fill`/`minmax` verbatim; the precise CSS syntax lives
only in `docs/weasyprint-css-support.md`, which isn't asset-tested).
`ruff check` and `mypy` clean on `pdf.py` and the new test file.

**WeasyPrint 69.0 findings** (full detail in
`docs/weasyprint-css-support.md`, empirically verified via probe documents
+ captured WeasyPrint CSS-validation warnings + a cross-check of the
installed `weasyprint/css/validation/properties.py` and
`weasyprint/layout/grid.py`):
- ✅ CSS Grid (fixed track counts), `minmax()` with a fixed repeat count,
  Flexbox, `break-inside: avoid` (+ `break-before`/`break-after`), and
  `@page` (`size`/`margin`) all work as expected — zero WeasyPrint warnings,
  and real layout-implementation modules exist for grid/flex (not stubs).
  An 80-row/2-column probe table with `tbody tr { break-inside: avoid }` +
  `thead { display: table-header-group }` produced a clean 3-page PDF.
- ❌ The auto-fit/auto-fill repeat-track keyword is UNSUPPORTED —
  WeasyPrint logs a warning and silently substitutes a repeat count of 1,
  **collapsing a responsive grid to a single stacked column** (a real
  regression, not a harmless no-op). Confirms TASK-2708's fixed
  `repeat(4, 1fr)` / `repeat(2, 1fr)` choice was necessary, not merely
  cautious.
- ❌ `position: sticky` is rejected outright — WeasyPrint's `position`
  property validator only accepts `static | relative | absolute | fixed |
  running(...)`; `sticky` isn't in that set at all. Irrelevant for print
  regardless, since the repeating-table-header idiom already in use
  (`thead { display: table-header-group }`) is the CSS-correct choice.
- ❌ `box-shadow` is **not implemented at all** — zero occurrences of
  "shadow" anywhere in the installed `weasyprint` 69.0 package. Stronger
  than "avoided for aesthetics": the existing `box-shadow: none` /
  `--shadow: none` in `layout-print.css` is inert for WeasyPrint itself,
  kept only as explicit, harmless intent (a real browser opening the same
  HTML, or a future WeasyPrint version implementing shadows, would still
  see the correct "no shadow" declaration).

Net result: `layout-print.css` needed NO functional changes — every
TASK-2708 choice was already the empirically-correct one. This task only
annotated the file with the findings and forced `PDFRenderer`'s layout.

**Deviations from spec**: none. (The `docs/` note is at
`docs/weasyprint-css-support.md` per the task's own file list.)
