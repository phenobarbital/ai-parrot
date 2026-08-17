# TASK-2228: Deterministic deck renderer — slides, charts, print-CSS document, optional PDF

**Feature**: FEAT-425 — "Thales" Research Flow with Structured Citations, Decks & Final Report
**Spec**: `sdd/specs/agentcrew-tales-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2226
**Assigned-to**: unassigned

---

## Context

Module 4 of FEAT-425. Pure-Python rendering: `SlideSpec` → slide HTML,
slides + `Bibliography` → one print-CSS final document, optional `.pdf` via
lazy weasyprint. No LLM anywhere in this module — determinism is an
acceptance criterion (golden-file byte-identical HTML). Visual identity:
the hanademi.com deck page is the layout reference (resolved in brainstorm).
Charts follow the FEAT-273/SPK-1 convention: ECharts option-JSON for the
browser path, static SVG for anything that must survive weasyprint (it
executes no JavaScript).

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/thales/rendering/` with:
  - `templates/` — Jinja2 slide template(s) (`slide.html.j2`) and document
    shell (`document.html.j2`) with `@page` rules and
    `page-break-after` per slide; bibliography as the final section.
    Layout reference: hanademi.com deck pages (headline, bullets, chart/
    table/quote regions, source footer).
  - `charts.py` — `echarts_option_block(chart: dict) -> str` (embedded
    option-JSON + init snippet for the browser path) and
    `static_svg_chart(chart: dict) -> str` (dependency-free SVG builder for
    the print/PDF path: bar/line minimum).
  - `slides.py` — `render_slide(spec: SlideSpec) -> str` (deterministic;
    charts only when the spec carries chart payloads; table/quote fallback).
  - `document.py` — `render_document(slides_html: list[str],
    bibliography: Bibliography, *, title: str) -> str` (print-CSS composer)
    and `rasterize_pdf(html: str) -> bytes | None` — lazy weasyprint import
    mirroring `_import_weasyprint` (`a2ui_renderers/pdf.py:36`); returns
    `None` (with a warning log) when weasyprint is unavailable.
- Templates rendered via `parrot.template.engine.TemplateEngine`
  (`template_dirs=` pointing at the package's `templates/`).
- Golden-file unit tests for determinism.

**NOT in scope**: the APA-ish bibliography *formatter* (TASK-2230 — this task
receives an already-formatted `Bibliography.entries` list); flow nodes;
persistence (`ArtifactStore` calls live in nodes/runner); the infographic
(InfographicToolkit renders that, TASK-2230).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/thales/rendering/__init__.py` | CREATE | Public render API |
| `packages/ai-parrot/src/parrot/flows/thales/rendering/slides.py` | CREATE | SlideSpec → HTML |
| `packages/ai-parrot/src/parrot/flows/thales/rendering/charts.py` | CREATE | ECharts option-JSON + static SVG |
| `packages/ai-parrot/src/parrot/flows/thales/rendering/document.py` | CREATE | print-CSS composer + optional PDF |
| `packages/ai-parrot/src/parrot/flows/thales/rendering/templates/slide.html.j2` | CREATE | Slide template (hanademi-style) |
| `packages/ai-parrot/src/parrot/flows/thales/rendering/templates/document.html.j2` | CREATE | Document shell, @page rules |
| `packages/ai-parrot/tests/flows/thales/test_rendering.py` | CREATE | Golden-file determinism tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-17 against `dev`.

### Verified Imports
```python
from parrot.template.engine import TemplateEngine     # parrot/template/engine.py
from parrot.flows.thales.models import SlideSpec, Bibliography  # TASK-2226
```

### Existing Signatures to Use
```python
# parrot/template/engine.py — TemplateEngine
#   TemplateEngine(template_dirs=...)  — accepts dir or list of dirs
#   .add_templates({name: source})     — in-memory registration
#   async .render(template_name, context) -> str
#   (usage precedent: parrot/tools/infographic_toolkit.py:520 render_template)

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py
def _import_weasyprint(): ...          # L36 — lazy-import pattern to MIRROR
class PDFRenderer(AbstractA2UIRenderer):  # L99 — weasyprint backend (SPK-1)
# SPK-1 decision (artifacts/spikes/spk1-rasterization/results.md):
#   weasyprint executes NO JavaScript → charts on the PDF path MUST be
#   static SVG; ECharts init HTML is fine for browser surfaces only.
```

### Does NOT Exist
- ~~`matplotlib`~~ — PURGED from this codebase
  (`sdd/specs/purge-matplotlib-renderer-libs.spec.md`). Do NOT import it,
  even behind try/except.
- ~~A shared slide/deck template registry~~ — `infographic_registry` holds
  infographic templates (`multi_tab`, `crew_report`) only; Thales ships its
  own Jinja templates in this package.
- ~~A reusable SVG chart builder in core~~ — the only static-SVG chart
  precedent is the spike fixture; this task writes its own minimal builder.
- ~~`weasyprint` as a hard dependency~~ — optional extra; import must stay
  lazy and failure non-fatal.

---

## Implementation Notes

### Pattern to Follow
```python
# Lazy optional dependency (mirror a2ui_renderers/pdf.py:36):
def _import_weasyprint():
    try:
        import weasyprint
        return weasyprint
    except ImportError:
        return None
```

### Key Constraints
- **Determinism**: no timestamps, no uuids, no dict-ordering surprises in
  rendered HTML — same input model → byte-identical output (golden test).
- Escape all model text through Jinja autoescape; never `|safe` on
  research-derived strings (only on the SVG/option-JSON blocks this module
  itself generates).
- Print CSS: `@page { size: A4 landscape; margin: ... }`,
  `.slide { page-break-after: always; }`; bibliography last.
- `rasterize_pdf` returns `None` + `logger.warning` when weasyprint is
  missing — callers surface a manifest warning (spec AC).

### References in Codebase
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py` —
  `_build_echarts_option` styling precedent for the option-JSON path.
- `artifacts/spikes/spk1-rasterization/results.md` — static-SVG constraint.

---

## Acceptance Criteria

- [ ] `render_slide(spec)` is deterministic: golden-file test byte-compares two runs
- [ ] Charts emitted only when `SlideSpec.charts` non-empty; table/quote fallback otherwise
- [ ] Document HTML contains `@page` rules, per-slide page breaks, bibliography as final section
- [ ] `rasterize_pdf` yields PDF bytes when weasyprint importable; `None` + warning otherwise (test both via monkeypatch)
- [ ] No matplotlib import anywhere: `grep -r matplotlib packages/ai-parrot/src/parrot/flows/thales/` is empty
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/thales/test_rendering.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/thales/`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/thales/test_rendering.py
import pytest
from parrot.flows.thales.models import SlideSpec, Bibliography
from parrot.flows.thales.rendering import slides, document

@pytest.fixture
def sample_slide_spec():
    return SlideSpec(deck_ref="d1", layout="default", headline="H",
                     bullets=["b1"], charts=[{"type": "bar",
                     "labels": ["a"], "series": [{"name": "s", "data": [1]}]}],
                     tables=[], quotes=[])

@pytest.mark.asyncio
async def test_slide_render_deterministic(sample_slide_spec):
    one = await slides.render_slide(sample_slide_spec)
    two = await slides.render_slide(sample_slide_spec)
    assert one == two and "<svg" in one or "echarts" in one

@pytest.mark.asyncio
async def test_document_print_css(sample_slide_spec):
    html = await document.render_document(
        ["<section class='slide'>s1</section>"],
        Bibliography(entries=["Doe, J. (2024)..."], claims=[]),
        title="T")
    assert "@page" in html and "page-break" in html
    assert html.rstrip().find("Doe, J.") > html.find("slide")  # bibliography last

def test_pdf_optional(monkeypatch):
    monkeypatch.setattr(document, "_import_weasyprint", lambda: None)
    assert document.rasterize_pdf("<html></html>") is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2226 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code
4. **Update status** in `sdd/tasks/index/agentcrew-tales-research.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2228-thales-deck-renderer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-08-17
**Notes**: Implemented `rendering/charts.py` (`echarts_option_block` +
`static_svg_chart`, bar/line, deterministic content-derived element ids —
no uuids/timestamps), `rendering/slides.py` (`render_slide`, TemplateEngine-
backed, chart/table/quote fallback), `rendering/document.py`
(`render_document` print-CSS composer + `rasterize_pdf` lazy-weasyprint,
returns `None`+warning when unavailable per the task's own
`_import_weasyprint` snippet — patchable to `None` directly, matching the
test spec), and the two Jinja templates. 11 unit tests pass, including
golden-file determinism (byte-identical repeat renders) and a
`test_no_matplotlib_import` AST-based guard. `ruff check` on `rendering/`
is fully clean (0 findings). `grep -r matplotlib` empty.

Note: both charts follow FEAT-273/SPK-1 — every chart emits BOTH an
ECharts (`.thales-chart-screen`) and a static-SVG (`.thales-chart-print`)
variant, toggled via `@media print` CSS, since a single chart call site
can't know at render time whether it will hit the browser or the
weasyprint PDF path.

**Deviations from spec**: none
