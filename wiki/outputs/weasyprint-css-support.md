# WeasyPrint 69.0 CSS Support — Empirical Findings

**FEAT-493, TASK-2713.** WeasyPrint CSS support is not assumable (spec §7) —
these findings come from actually rendering probe documents with WeasyPrint
**69.0** (the version pinned across `packages/ai-parrot/pyproject.toml`,
`packages/ai-parrot-tools/pyproject.toml`, `packages/ai-parrot-loaders/
pyproject.toml`, and confirmed installed in this project's venv) and
inspecting both the rendered PDF (via `pypdf`) and WeasyPrint's own CSS
validation warnings (`logging.getLogger("weasyprint")`), plus cross-checking
against WeasyPrint 69.0's installed source
(`weasyprint/css/validation/properties.py`, `weasyprint/layout/grid.py`).

This document exists so the next person does not repeat this — negative
results are recorded exactly like positive ones.

## Method

A minimal probe document exercising each feature in isolation was rendered
with `weasyprint.HTML(string=doc).write_pdf()`, with a logging handler
attached to WeasyPrint's own logger to capture every CSS validation warning.
A second probe rendered an 80-row table to verify multi-page row-splitting
behavior via `pypdf.PdfReader` page counts.

## Findings

| Feature | Supported? | Evidence |
|---|---|---|
| CSS Grid, fixed track count (`display: grid; grid-template-columns: repeat(4, 1fr)`) | ✅ Yes | Renders with zero WeasyPrint warnings; `weasyprint/layout/grid.py` is a real grid-layout implementation, not a no-op. |
| `minmax()` inside `repeat()` with a fixed count (`repeat(2, minmax(100px, 1fr))`) | ✅ Yes | Renders with zero warnings; `minmax()` has dedicated validation in `weasyprint/css/validation/properties.py:1355-1382`. |
| `repeat(auto-fit, minmax(...))` / `repeat(auto-fill, ...)` | ❌ **No** | WeasyPrint logs `"auto-fit" and "auto-fill" are unsupported in repeat()` and **silently substitutes a repeat count of 1** (`weasyprint/layout/grid.py:204-208`) — a KPI grid using this collapses to a **single stacked column**, not "no responsive behavior": a real visual regression, not a harmless no-op. Confirms TASK-2708's choice of fixed `repeat(4, 1fr)` / `repeat(2, 1fr)` (`@media (max-width: 900px)`) in `layout-print.css` is necessary, not merely cautious. |
| Flexbox (`display: flex`) | ✅ Yes | Renders with zero warnings; `weasyprint/layout/flex.py` is a real flex-layout implementation. Not currently used by `layout-print.css` (fixed-column grid covers the one responsive-looking construct this renderer needs), but confirmed available for future print-layout work. |
| `position: sticky` | ❌ **No** | WeasyPrint logs `Ignored `position: sticky` ..., invalid value` — the `position` property's validator (`weasyprint/css/validation/properties.py:1176-1185`) only accepts `static \| relative \| absolute \| fixed \| running(...)`; `sticky` is not in that set at all (not a partial/degraded implementation — the value is rejected outright, falling back to the property's initial value, `static`). Irrelevant for print anyway (sticky is a *screen-scrolling* concept); this repo's actual repeating-table-header technique for print, `thead { display: table-header-group }`, is the CSS-correct print idiom and is unaffected. |
| `break-inside: avoid` (and `break-before`/`break-after`) | ✅ Yes | Renders with zero warnings; validated in `weasyprint/css/validation/properties.py:313-325`) and enforced at the fragmentation/layout level — an 80-row, 2-column probe table with `tbody tr { break-inside: avoid }` + `thead { display: table-header-group }` produced a valid 3-page PDF with the header repeating on every page and no row visibly split across a page boundary. |
| `@page` (`size`, `margin`) | ✅ Yes | This is WeasyPrint's core target use case; `@page { size: A4; margin: 16mm 14mm; }` produced a valid PDF with the expected page geometry, no warnings. |
| `box-shadow` | ❌ **No — not merely avoided, technically absent** | WeasyPrint logs `Ignored `box-shadow: ...`, unknown property` — there is **zero** occurrence of "shadow" anywhere in the installed `weasyprint` 69.0 package (verified with a package-wide grep), i.e. this isn't a partial/buggy implementation to work around, the property is simply not implemented. TASK-2708's `box-shadow: none` in `layout-print.css` is inert (WeasyPrint never applied a shadow to begin with) but is kept as explicit, defensive intent — cheap insurance if this HTML is ever also opened directly in a real browser for debugging, and against a future WeasyPrint version that DOES implement it. |

## Conclusion for `layout-print.css`

Every construct TASK-2708 chose defensively for `layout-print.css` (fixed
grid columns instead of `auto-fit`/`minmax`, `break-inside: avoid` on
cards/panels/table rows, `display: table-header-group` instead of `position:
sticky`, `box-shadow: none`, real `@page` rules) is now a **verified**
choice, not an assumption — no functional change to the CSS was needed;
TASK-2713 only annotated it with these findings (see the file's own
comments) and forced `PDFRenderer` to always compose with `layout="print"`
(`pdf.py`) so no caller can accidentally get the screen (`analytics`)
stylesheet in a PDF.
