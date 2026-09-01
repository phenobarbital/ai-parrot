---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Backend HTML Design System (tokens + layout presets)

**Feature ID**: FEAT-493
**Date**: 2026-09-01
**Author**: Jesus Lara (jlara@trocglobal.com) + Claude
**Status**: draft
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

Every lane in which the backend acts as an HTML renderer emits visually poor
output. The A2UI `interactive-html` renderer — used by infographics, widgets,
A2UI surfaces and dashboards alike — ships a single hardcoded, minified
30-line stylesheet (`interactive_html.py:108-138`). It emits no
`<meta viewport>`, no page wrapper, no design tokens, no responsive rules and
no typographic hierarchy: top-level blocks fall directly into `<body>` with
`margin:1rem`. `ssr-html` carries a near-identical 19-line `_STYLE`
(`ssr_html.py:61-79`), and `PDFRenderer` inherits it wholesale
(`pdf.py:99` — `class PDFRenderer(SSRHTMLRenderer)`).

The gap is not merely "no CSS". **The semantic layer already exists
end-to-end and the renderers discard it.** The catalog's `lower()` methods
already emit a vocabulary of 8 `parrot_variant` values (`card`, `chart`,
`infographic`, `kpi`, `map`, `report`, `table`, `timeline`) and 27
`parrot_role` values (`title`, `subtitle`, `heading`, `body`, `summary`,
`caption`, `label`, `value`, `delta`, `column-header`, `cell`, `row`,
`series`, `axis`, `event-title`, `timestamp`, `notice`, …), plus
`parrot_unit` and `parrot_trend` on KPICard. Three concrete consequences:

- `_render_prim_Card` (`interactive_html.py:529`) and `_render_Card`
  (`ssr_html.py:331`) drop `parrot_variant` entirely, so a `KPICard` — whose
  `lower()` deliberately tags itself `parrot_variant: "kpi"`
  (`catalog/parrot/kpicard.py:94`) — renders as a generic bordered box
  with three loose `<p>` elements.
- `_render_prim_Text` (`interactive_html.py:478-484`) *does* map
  `parrot_role` to an `a2ui-<role>` class, but `_STYLE` defines **no rule
  whatsoever** for `.a2ui-label`, `.a2ui-value` or `.a2ui-delta`. The
  classes are emitted into a stylesheet that ignores them.
- `_render_datatable` (`interactive_html.py:653-687`) ignores
  `TableColumn.type` and `TableColumn.format`, whose own docstring
  (`models/outputs.py:496-498`) states they carry *"the minimum information
  a frontend grid library needs to render a column correctly"*. Every cell
  is `str(v)` raw: no numeric alignment, no currency/percent formatting, no
  `tabular-nums`. `total_rows` / `truncated` are likewise dropped, so a
  capped result set silently presents as complete.

Meanwhile a genuine design system already exists in a sibling lane and is
not shared: `formats/infographic_html.py:176` defines a ~180-line `BASE_CSS`
(commented *"extracted from reference HTML"*) with `.container`, `.hero`,
`.kpi-grid`, `.kpi-card`, `.kpi-value`, `.kpi-trend.up/.down/.flat`,
`.chart-container`, zebra + hover tables, callouts, timeline and progress
bars, themed through `ThemeConfig.to_css_variables()`
(`models/infographic.py:1457`) with five registered themes (`light`, `dark`,
`corporate`, `midnight`, `petrol`). The A2UI renderers do not use any of it.

The reference artifact for the target quality bar is
`docs/flex_program_report (39).html` — hand-authored, ~170 lines of CSS
custom properties, native grid, `font-variant-numeric: tabular-nums`,
sticky solid table headers, a filter bar with searchable multiselects, tabs,
and Chart.js bundled inline. Notably it uses **neither Tailwind, nor shadcn,
nor grid.js**: its quality comes from tokens and disciplined hand-written
CSS, which is also the only approach compatible with this renderer's
self-contained invariant (see Non-Goals).

### Goals

- One shared design system for every backend-rendered HTML lane:
  `interactive-html`, `ssr-html`, `pdf`, and `formats/infographic_html.py`.
- Two orthogonal axes: **`theme`** = palette (the five existing registered
  themes) and **`layout`** = density/structure (`report`, `analytics`,
  `print` — new names, deliberately disjoint from theme names).
- CSS authored as CSS in packaged assets, composed in Python from
  `ThemeConfig` tokens, with per-`(theme, layout)` caching and file I/O at
  import time only.
- Renderers honour the `parrot_variant` / `parrot_role` / `parrot_unit` /
  `parrot_trend` vocabulary that the catalog already emits, **without
  modifying any `lower()`**.
- A rich `DataTable` (sticky header, numeric alignment and formatting,
  total/group rows, truncation notice, and search + pagination above a row
  threshold) implemented in-house, with no new external dependency.
- A KPI hero row: `parrot_variant: "kpi"` cards laid out on a real grid.
- A new `FilterBar` composite with client-side filtering on
  `interactive-html`, degrading honestly (not to a dead control) on the
  JS-less surfaces.
- A shared page shell emitting `<meta viewport>` and a
  `div.ds-page[data-layout][data-theme]` wrapper.

### Non-Goals (explicitly out of scope)

- **No CDN-delivered CSS or JS.** The output must stay fully
  self-contained: `test_interactive_html.py:64-67` asserts the absence of
  `<script src=`, `<link ` and `@import`. This rules out Tailwind's play
  CDN, grid.js, and Google Fonts. System font stacks only.
- **No Tailwind build step and no utility-class markup.** Rejected during
  brainstorming: it would require a Node build in a Python repo, rewrite
  the markup of every renderer, and break the `a2ui-*` class assertions —
  and it is not what the reference artifact does.
- **No vendored grid.js.** Rejected: ~40KB plus a companion stylesheet per
  artifact, on top of the ~200KB inline Chart.js bundle, to buy features
  (virtual scroll) that the in-house table does not need.
- **No changes to any catalog `lower()` method.** The lowering golden
  fixtures in `packages/ai-parrot/tests/outputs/a2ui/golden/` (8 files) must
  remain valid; all work happens in the render layer. The single exception
  is the net-new `FilterBar` composite, which adds its own golden.
- **No changes to the A2UI wire contract.** `CreateSurface` is
  `extra="forbid"` (`a2ui/models.py:463`); no top-level `theme` field is
  added to it.
- **No frontend work.** `packages/ai-parrot-server/ui` (Svelte + shadcn +
  Tailwind) consumes structured A2UI, not this HTML, and is untouched.

---

## 2. Architectural Design

### Overview

Two pieces, placed according to what each package already owns.

**Core (`ai-parrot`)** — `ThemeConfig` (`models/infographic.py:1375`) gains
layout tokens (`content_width`, `radius`, `density`, `shadow`,
`mono_family`, `panel_bg`, `panel_border`, `header_bg`, `header_text`), all
optional with derivations from existing colour tokens so the five registered
themes keep working unchanged. `to_css_variables()` (`:1457`) emits them
alongside the colour variables. `theme_registry` (`:1574`) remains the sole
theme registry.

**Satellite (`ai-parrot-visualizations`)** — a new package
`parrot/outputs/formats/assets/design_system/` containing plain CSS —
`base.css` (reset, typography, page shell, table skeleton),
`components.css` (card variants, KPI, panel, tabs, callouts, timeline,
progress, filter bar), and `layout-report.css` / `layout-analytics.css` /
`layout-print.css` — plus an `__init__.py` exposing the composer:

`DesignSystem.stylesheet(theme, layout) -> str` resolves the theme via
`theme_registry`, concatenates `theme.to_css_variables()` + `base.css` +
`components.css` + `layout-<layout>.css`, and caches per
`(theme_name, layout)`. Asset files are read **once at import**, mirroring
`_CHART_JS_SOURCE` (`interactive_html.py:97`), whose own comment explains
the rule: `render()` is async and re-reading assets per call would block the
event loop for no benefit.

Each renderer replaces its `_STYLE` constant with a composer call, and both
HTML renderers share a `_document_shell()` helper emitting `<meta charset>`,
`<meta viewport>`, `<title>`, the composed `<style>`, and
`<body><div class="ds-page" data-layout="…" data-theme="…">`. The two data
attributes let layout and theme CSS scope themselves without injecting a
bespoke `:root`, and let an embedding container (iframe / `srcdoc`)
override.

**Layout defaults**: `analytics` for `interactive-html`, `ssr-html` and
`infographic_html`; `print` forced by `PDFRenderer`. The current `BASE_CSS`
migrates 1:1 into `layout-report.css`, available as an opt-in for anyone
wanting today's appearance. This is a deliberate, user-approved visual
change of default for existing `infographic_html` consumers (§8).

**Class-name compatibility is additive, never substitutive.** The `a2ui-*`
classes are load-bearing across package boundaries —
`test_e2e_ssr_html.py:75` counts `class="a2ui-text a2ui-cell"`,
`test_interactive_html.py:248` asserts `<hr class="a2ui-divider-h">`, and
core's `test_finance_reporter_narrative_e2e.py:231-288` asserts `a2ui-body`,
`a2ui-summary`, `a2ui-value` and `a2ui-card`. Emitters keep producing every
class they produce today and **append** the semantic one: a `value`-role
Text goes from `class="a2ui-text a2ui-value"` to
`class="a2ui-text a2ui-value kpi-value"`.

### Component Diagram

```
ThemeConfig (core, +layout tokens) ──to_css_variables()──┐
                                                         ▼
assets/design_system/*.css ────────────────────► DesignSystem.stylesheet(theme, layout)
                                                         │  (cached per pair)
                            ┌────────────────────────────┼────────────────────────────┐
                            ▼                            ▼                            ▼
              InteractiveHTMLRenderer          SSRHTMLRenderer            InfographicHTMLRenderer
                     │                            │  └──► PDFRenderer (layout=print)
                     │                            │
                     └──────► _document_shell() ◄─┘
                                    │
                     div.ds-page[data-layout][data-theme]
                                    │
        variant/role → semantic classes · rich DataTable · KPI grid · FilterBar
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ThemeConfig` (`models/infographic.py:1375`) | extends | New optional layout-token fields; `to_css_variables()` emits them |
| `theme_registry` (`models/infographic.py:1574`) | uses | Sole theme resolver for the composer |
| `InteractiveHTMLRenderer` (`interactive_html.py:295`) | modifies | `_STYLE` → composer; shell; variant/role mapping; rich table; FilterBar |
| `SSRHTMLRenderer` (`ssr_html.py:120`) | modifies | Same, minus JS behaviours |
| `PDFRenderer` (`pdf.py:99`) | inherits | Forces `layout="print"`; no other change |
| `InfographicHTMLRenderer` (`formats/infographic_html.py`) | modifies | `BASE_CSS` → `layout-report.css`; default becomes `analytics` |
| `RecipeRunner._render_or_raise` (`runner.py:631-635`) | modifies | `renderer_cls()` → `renderer_cls(theme=…, layout=…)` |
| `Infographic.theme` prop (`catalog/parrot/infographic.py:39`) | uses | Existing "theme hint" prop, now actually honoured |
| `degradation_record` (`renderers/degrade.py:46`) | uses | FilterBar degradation on JS-less surfaces |
| `ChoicePicker` (`catalog/basic/inputs.py:100`) | uses | `FilterBar` lowers to a Row of these |

### Data Models

```python
# packages/ai-parrot/src/parrot/models/infographic.py — ThemeConfig additions
class ThemeConfig(BaseModel):
    # ... 24 existing colour/font fields unchanged ...
    content_width: Optional[str] = Field(None, description="Max content width, e.g. '1400px'")
    radius: Optional[str] = Field(None, description="Base border-radius, e.g. '10px'")
    density: Optional[str] = Field(None, description="'comfortable' | 'compact'")
    shadow: Optional[str] = Field(None, description="Base box-shadow; 'none' for print")
    mono_family: Optional[str] = Field(None, description="Monospace stack for numerics")
    panel_bg: Optional[str] = Field(None, description="Panel surface (derives from surface_bg)")
    panel_border: Optional[str] = Field(None, description="Panel border (derives from neutral_border)")
    header_bg: Optional[str] = Field(None, description="Table header fill (derives from primary)")
    header_text: Optional[str] = Field(None, description="Table header ink (derives from on_primary)")
```

Every new field is `Optional` with a documented derivation, so the five
registered themes stay valid without edits and no consumer constructing a
`ThemeConfig` by hand breaks.

### New Public Interfaces

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py
class DesignSystem:
    """Composes a themed stylesheet from packaged CSS assets."""

    LAYOUTS: ClassVar[frozenset[str]] = frozenset({"report", "analytics", "print"})
    DEFAULT_THEME: ClassVar[str] = "light"
    DEFAULT_LAYOUT: ClassVar[str] = "analytics"

    @classmethod
    def stylesheet(cls, theme: str | ThemeConfig | None = None, layout: str | None = None) -> str:
        """Return the composed CSS for a (theme, layout) pair.

        An unknown theme or layout logs a warning and falls back to the
        default — a missing theme is a cosmetic failure, never a render
        exception.
        """

    @classmethod
    def resolve(cls, envelope: CreateSurface, *, theme_default: str, layout_default: str) -> tuple[str, str]:
        """Resolve the effective (theme, layout) pair for an envelope."""


# Shared shell — packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_shell.py
def document_shell(*, title: str, style: str, body: str, theme: str, layout: str,
                   scripts: Sequence[str] = ()) -> str:
    """Build a complete, self-contained HTML document."""


# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py
@register_component("FilterBar")
class FilterBarComponent:
    """Lowers to Row{ChoicePicker...} with parrot_variant='filter-bar'."""
```

**`(theme, layout)` resolution precedence** (first hit wins):

1. `envelope.metadata.extensions["parrot_theme"]` / `["parrot_layout"]`
2. The `Infographic.theme` prop, when the top-level component is an
   `Infographic` (existing schema field, `catalog/parrot/infographic.py:39`)
3. The renderer constructor's `theme=` / `layout=` arguments
4. The renderer's class defaults

---

## 3. Module Breakdown

### Module 1: ThemeConfig layout tokens
- **Path**: `packages/ai-parrot/src/parrot/models/infographic.py`
- **Responsibility**: Add the nine optional layout tokens, their colour
  validators, and their emission in `to_css_variables()` with documented
  derivations. Add a `print`-safe derivation (`shadow: none`).
- **Depends on**: nothing (pure core addition)

### Module 2: Design-system assets + composer + packaging
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/`
  (`__init__.py`, `base.css`, `components.css`, `layout-report.css`,
  `layout-analytics.css`, `layout-print.css`)
- **Responsibility**: The CSS itself plus `DesignSystem`. `layout-report.css`
  is the current `BASE_CSS` migrated 1:1. `layout-analytics.css` carries the
  dense aesthetic (wide content width, flat panels, `tabular-nums`, solid
  sticky table headers). Extend `[tool.setuptools.package-data]`
  (`pyproject.toml:78-79`) with the new package's `*.css`.
- **Depends on**: Module 1

### Module 3: Shared page shell + variant/role class mapping
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_shell.py`
  (new), `interactive_html.py`, `ssr_html.py`
- **Responsibility**: `document_shell()`; replace both `_STYLE` constants
  with composer calls; map `parrot_variant` on Card, `parrot_role` on Text
  (appending semantic classes), `parrot_trend` → `data-trend`,
  `parrot_unit` → `<span class="kpi-unit">`; a `Row` whose children are all
  `kpi`-variant Cards emits `kpi-grid`. Implement the resolution precedence.
  **Note**: the two renderers use divergent dispatch naming —
  `_render_prim_<Component>` in `interactive_html.py` vs
  `_render_<Component>` in `ssr_html.py` — so shared logic goes in helpers
  the two dispatchers call, not in a name-dependent mixin.
- **Depends on**: Module 2

### Module 4: Rich DataTable
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`,
  `ssr_html.py`, and the shared formatting helper
- **Responsibility**: Read `TableColumn.type` / `format`; format
  `currency` / `percent` / thousands **in Python** so `ssr-html` and `pdf`
  come out formatted without JS; emit `<td class="num" data-v="<raw>">` so
  the existing client sort compares numbers rather than separator-laden
  text; sticky `<thead>`; total/group rows; render the `truncated` /
  `total_rows` notice; search + pagination in the behaviour JS, enabled
  only above 100 rows.
- **Depends on**: Module 3

### Module 5: Infographic HTML lane migration
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py`
- **Responsibility**: Drop the in-module `BASE_CSS` in favour of the
  composer; default `layout="analytics"`; keep `report` reachable. Verify
  every `BASE_CSS` selector still resolves after the move.
- **Depends on**: Module 2

### Module 6: PDF / print layout
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py`,
  `layout-print.css`
- **Responsibility**: Force `layout="print"`; author `layout-print.css`
  without shadows, without `auto-fit`/`minmax`, with `@page` and controlled
  break behaviour. **Empirically verify** what WeasyPrint 69.0 actually
  supports rather than trusting documentation, and record the findings.
- **Depends on**: Module 3

### Module 7: Theme/layout plumbing through the recipe runner
- **Path**: `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py`,
  `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py`
- **Responsibility**: `RenderSpec` gains `layout: Optional[str]`;
  `_render_or_raise` (`:631-635`) constructs
  `renderer_cls(theme=recipe.render.theme, layout=recipe.render.layout)`.
  Today `recipe.render.theme` only reaches `build_infographic(theme=…)`
  (`:616`) on the `Infographic` layout branch and is dropped entirely on the
  `build_surface` branch (`:621`); no renderer ever reads it.
- **Depends on**: Module 3

### Module 8: FilterBar composite + client-side filtering
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py`
  (new), `packages/ai-parrot/tests/outputs/a2ui/golden/filterbar_lowered.json`
  (new), `interactive_html.py`, `ssr_html.py`
- **Responsibility**: The composite (lowering to `Row{ChoicePicker…}` with
  `parrot_variant: "filter-bar"`, each picker carrying
  `parrot_role: "filter"` and `parrot_filter_column`); the
  searchable-multiselect + chips + reset markup and its filtering JS over
  the embedded `dataModel`, where a filter affects only charts/tables whose
  dataset declares that column; and the honest degradation on `ssr-html` /
  `pdf` to a filter-state summary line plus a `degradation_record`.
- **Depends on**: Modules 3, 4
- **Note**: This is the only non-presentational module (it carries state,
  interaction and data semantics). It is deliberately last, and it is the
  designated cut line if scope must shrink — nothing else depends on it.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_layout_tokens_emitted` | 1 | `to_css_variables()` contains the nine new custom properties |
| `test_registered_themes_still_valid` | 1 | All five registered themes construct and emit without error |
| `test_layout_token_derivations` | 1 | Unset optional tokens derive from existing colour tokens |
| `test_assets_packaged_and_non_empty` | 2 | Each of the five CSS assets loads and is non-empty (catches a `package-data` regression) |
| `test_stylesheet_cached_per_pair` | 2 | Two calls with the same `(theme, layout)` return the identical object; assets read once |
| `test_unknown_theme_falls_back_with_warning` | 2 | Unknown theme/layout logs a warning and returns the default sheet, raising nothing |
| `test_shell_emits_viewport_and_wrapper` | 3 | Output carries `<meta name="viewport"`, `div.ds-page`, `data-layout`, `data-theme` |
| `test_legacy_a2ui_classes_preserved` | 3 | Every `a2ui-*` class asserted by existing tests is still present |
| `test_kpicard_variant_honoured` | 3 | A `KPICard` envelope yields `kpi-card`, `kpi-label`, `kpi-value` and `data-trend` |
| `test_kpi_row_becomes_grid` | 3 | A `Row` of `kpi`-variant Cards emits `kpi-grid` |
| `test_resolution_precedence` | 3 | Envelope extensions beat the `Infographic.theme` prop, which beats the constructor, which beats the class default |
| `test_numeric_columns_formatted_and_aligned` | 4 | `type=number`/`format=currency` cells carry `class="num"`, a formatted body and a raw `data-v` |
| `test_truncation_notice_rendered` | 4 | `truncated=True` with `total_rows` renders the "N of M" notice |
| `test_pagination_threshold` | 4 | ≤100 rows renders no pager; >100 rows does |
| `test_infographic_default_layout_is_analytics` | 5 | The infographic lane defaults to `analytics` and `report` remains selectable |
| `test_report_layout_matches_legacy_selectors` | 5 | Every selector from the old `BASE_CSS` is present in `layout-report.css` |
| `test_pdf_forces_print_layout` | 6 | `PDFRenderer` composes with `layout="print"`; the sheet has no `box-shadow` and no `auto-fit` |
| `test_render_spec_layout_field` | 7 | `RenderSpec` accepts `layout` and the runner forwards both values |
| `test_filterbar_lowering_golden` | 8 | `FilterBar.lower()` matches `filterbar_lowered.json` |
| `test_filterbar_degrades_without_js` | 8 | `ssr-html` emits a filter-state summary and a `degradation_record`, and no `<select>`/dropdown control |

### Integration Tests

| Test | Description |
|---|---|
| `test_self_contained_invariant_holds` | Extends the existing check: no `<script src=`, `<link `, `@import` in any `(theme, layout)` combination |
| `test_all_theme_layout_pairs_render` | The full 5 × 3 matrix renders a non-trivial envelope without exception or degradation |
| `test_pdf_renders_with_weasyprint` | The print layout produces a valid PDF through WeasyPrint 69.0 |
| `test_finance_reporter_e2e_still_passes` | The existing core E2E suite asserting `a2ui-*` classes is unaffected |
| `test_flex_dashboard_envelope_renders` | A FEAT-491-shaped envelope (KPI hero row + month charts + pay-code table) renders with KPI grid, formatted numerics and no degradation |

### Test Data / Fixtures

```python
@pytest.fixture
def kpi_dashboard_envelope() -> CreateSurface:
    """Hero row of 4 KPICards + a Chart + a DataTable with typed numeric columns."""

@pytest.fixture(params=sorted(theme_registry.list_themes()))
def theme_name(request) -> str:
    """Every registered theme, so the matrix test cannot silently skip one."""
```

---

## 5. Acceptance Criteria

- [ ] `DesignSystem.stylesheet()` composes all 15 `(theme, layout)` pairs without error
- [ ] The five CSS assets are present and non-empty when imported from an installed wheel (not just from the source tree)
- [ ] `interactive-html` output contains `<meta name="viewport">` and a `div.ds-page[data-layout][data-theme]` wrapper
- [ ] Every `a2ui-*` class asserted by any pre-existing test is still emitted; no existing test is modified to accommodate this feature
- [ ] The 8 lowering golden fixtures in `tests/outputs/a2ui/golden/` are unchanged, and no catalog `lower()` method is modified (except the new `FilterBar`)
- [ ] A `KPICard` renders with `kpi-card` / `kpi-label` / `kpi-value`, its unit, and a `data-trend` attribute
- [ ] `DataTable` numeric columns are right-aligned with `tabular-nums`, formatted per `TableColumn.format`, and carry a raw `data-v` so sorting is numeric
- [ ] A `truncated` DataTable renders its "showing N of M" notice
- [ ] Search and pagination appear only above 100 rows
- [ ] `PDFRenderer` composes with `layout="print"` and produces a valid PDF under WeasyPrint 69.0
- [ ] `RenderSpec.theme` and the new `RenderSpec.layout` reach the renderer constructor from `RecipeRunner`
- [ ] An unknown theme or layout logs a warning and renders with the default; it never raises
- [ ] `FilterBar` filters the embedded `dataModel` on `interactive-html`, and degrades on `ssr-html`/`pdf` to a filter-state summary plus a `degradation_record` — never a non-functional control
- [ ] Output remains fully self-contained: no `<script src=`, no `<link `, no `@import`, in every `(theme, layout)` pair
- [ ] `pytest packages/ai-parrot-visualizations/tests/ packages/ai-parrot/tests/outputs/ -v` passes
- [ ] `ruff check` and `mypy` clean on all changed files
- [ ] Documentation updated: a design-system section covering the two axes, the token list, and how to add a layout

---

## 6. Codebase Contract

### Verified Imports

```python
# core (ai-parrot)
from parrot.models.infographic import ThemeConfig, ThemeRegistry, theme_registry  # models/infographic.py:1375,1510,1574
from parrot.models.outputs import StructuredTableConfig, TableColumn               # models/outputs.py:530,493
from parrot.outputs.a2ui.models import Component, ComponentMetadata, CreateSurface, SurfaceMetadata  # a2ui/models.py:446,364,378
from parrot.outputs.a2ui.catalog import get_component, register_component          # a2ui/catalog/__init__.py:107
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, TabSpec, to_components
from parrot.outputs.a2ui.renderers import (                                        # a2ui/renderers/__init__.py:51,78,108,141
    AbstractA2UIRenderer, RendererCapabilities, register_a2ui_renderer, get_a2ui_renderer,
)
from parrot.outputs.a2ui.renderers.degrade import degrade, degradation_record      # renderers/degrade.py:24,46
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.artifacts import RenderedArtifact

# satellite (ai-parrot-visualizations)
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer                 # ssr_html.py:120
from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer # interactive_html.py:295
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/models/infographic.py
class ThemeConfig(BaseModel):                       # line 1375
    name: str                                       # line 1382
    primary: str = "#6366f1"                        # line 1383
    neutral_bg / neutral_border / neutral_muted / neutral_text / body_bg: str
    surface_bg / soft_primary / on_primary: Optional[str]
    font_family: str
    code_palette: Optional[CodePalette]             # CodePalette at line 1292
    method_badge_palette: Optional[MethodBadgePalette]   # line 1317
    def to_css_variables(self) -> str: ...          # line 1457

class ThemeRegistry:                                # line 1510
    def register(self, theme: ThemeConfig) -> None: ...
    def get(self, name: str) -> ThemeConfig: ...    # raises KeyError with available names
    def list_themes(self) -> List[str]: ...
    def list_themes_detailed(self) -> List[Dict[str, str]]: ...

theme_registry = ThemeRegistry()                    # line 1574
# registered: light (1579), dark (1594), corporate (1609), midnight (1624), petrol (1643)

# packages/ai-parrot/src/parrot/models/outputs.py
class TableColumn(BaseModel):                       # line 493
    name: str                                       # line 513
    type: str    # string|integer|number|boolean|date|datetime|time|duration|any   # line 514
    title: str                                      # line 521
    format: Optional[str] = None  # currency|percent|email|uri|enum|id|code        # line 522

class StructuredTableConfig(BaseModel):             # line 530
    columns: List[TableColumn]                      # line 551
    data: List[dict]                                # line 554 (INPUT-ONLY)
    explanation / total_rows / truncated

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class ComponentMetadata(BaseModel):                 # line 364
    extensions: Extensions | None = None            # line 373
SurfaceMetadata = ComponentMetadata                 # line 378
class CreateSurface(A2UIMessageBase):               # line 446
    model_config = ConfigDict(populate_by_name=True, extra="forbid")   # line 463
    surface_id: str                                 # line 465
    components: list[Component]                     # line 468
    data_model: dict[str, Any]                      # line 469
    metadata: SurfaceMetadata | None = None         # line 470

# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
class AbstractA2UIRenderer(ABC):                    # line 78
    capabilities: RendererCapabilities              # line 86
    @abstractmethod
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> "Any | str": ...  # line 89

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class RenderSpec(BaseModel):                        # line 158
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    profile: str = "interactive-html"               # line 170
    theme: Optional[str] = None                     # line 171

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py
_SURFACE_NAME = "interactive-html"                  # line 82
_INTERCEPTED = {"Chart", "DataTable", "Infographic"}    # line 86
_CHART_JS_SOURCE = _CHART_JS_PATH.read_text(...)    # line 97 (read ONCE at import — the pattern to copy)
_STYLE = (...)                                      # lines 108-138 (to be replaced)
_CONTAINER_COMPONENTS = {"Column": "a2ui-col", "Row": "a2ui-row"}   # line 140
_BEHAVIOR_JS = r"""..."""                           # line 142
class InteractiveHTMLRenderer(AbstractA2UIRenderer):    # line 295
    async def render(self, envelope, *, bake=True) -> RenderedArtifact: ...   # line 298
    def _render_prim_Text(self, node, degradations) -> str: ...   # line 478 (maps parrot_role)
    def _render_prim_Row(self, node, degradations) -> str: ...    # line 517
    def _render_prim_Card(self, node, degradations) -> str: ...   # line 529 (DROPS parrot_variant)
    def _render_chart(self, props) -> str: ...       # line 600
    def _render_datatable(self, props) -> str: ...   # line 653 (IGNORES type/format/total_rows/truncated)
    def _render_infographic(self, props) -> str: ...  # line 690 (IGNORES the theme prop)

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py
_STYLE = (...)                                      # lines 61-79 (to be replaced)
class SSRHTMLRenderer(AbstractA2UIRenderer):        # line 120
    async def render(self, ...)                     # line 128
    # NOTE: dispatch is named _render_<Component>, WITHOUT the _prim_ infix
    def _render_Card(self, node, degradations) -> str: ...   # line 331 (DROPS parrot_variant)
    def _render_ChoicePicker(self, node, degradations) -> str: ...   # line 375

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py
class PDFRenderer(SSRHTMLRenderer):                 # line 99 — inherits SSR dispatch AND its CSS
    async def render(self, ...)                     # line 113
    async def _build_intermediate_html(self, envelope, *, deep_links=None) -> tuple[str, list[dict]]: ...  # line 135

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
    def _assemble_envelope_or_raise(self, recipe, data_model): ...   # line 607
        # line 616: theme=props.get("theme") or recipe.render.theme  (Infographic branch ONLY)
        # line 621: build_surface(...)  — theme DROPPED on this branch
    async def _render_or_raise(self, recipe, envelope) -> RenderedArtifact: ...   # line 631
        # line 634: renderer_cls = get_a2ui_renderer(recipe.render.profile)
        # line 635: renderer = renderer_cls()   — no theme/layout passed

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/kpicard.py
class KPICardComponent:                             # line 50
    def lower(self, component, data_model) -> BasicTree: ...   # line 56
        # emits parrot_role label/value/delta (+ parrot_unit, parrot_trend)
        # returns Card with metadata extensions parrot_variant="kpi"   # line 94
```

### Semantic vocabulary already emitted by `lower()` (verified by grep over `catalog/parrot/*.py` and `renderers/degrade.py`)

- **`parrot_variant` (8)**: `card`, `chart`, `infographic`, `kpi`, `map`, `report`, `table`, `timeline`
- **`parrot_role` (27)**: `axis`, `axis-label`, `body`, `caption`, `cell`, `column-header`, `delta`, `description`, `event`, `event-description`, `event-title`, `header`, `heading`, `label`, `layer`, `layer-summary`, `notice`, `row`, `rows`, `series`, `series-list`, `subtitle`, `summary`, `timestamp`, `title`, `trendline`, `value`
- **Extras**: `parrot_unit`, `parrot_trend` (`kpicard.py`), `parrot_component_id` (datatable), `parrot_optional` (narrative bindings)

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DesignSystem.stylesheet()` | `ThemeConfig.to_css_variables()` | method call | `models/infographic.py:1457` |
| `DesignSystem.stylesheet()` | `theme_registry.get()` | method call | `models/infographic.py:1528` |
| `document_shell()` | `InteractiveHTMLRenderer.render()` | replaces inline document build | `interactive_html.py:333-343` |
| `document_shell()` | `SSRHTMLRenderer.render()` | replaces inline document build | `ssr_html.py:173` |
| Rich table formatter | `TableColumn.type` / `.format` | property read | `models/outputs.py:514,522` |
| Variant mapping | `metadata.extensions["parrot_variant"]` | dict read | `kpicard.py:94` |
| `FilterBar` | `register_component` | decorator | `a2ui/catalog/__init__.py:107` |
| `FilterBar` degradation | `degradation_record()` | function call | `renderers/degrade.py:46` |
| Runner plumbing | `renderer_cls(theme=…, layout=…)` | constructor call | `runner.py:635` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.outputs.formats.assets.design_system`~~ — the package is net-new (0 hits repo-wide)
- ~~`DesignSystem`~~ — no such class anywhere (0 hits)
- ~~`FilterBar` / `FilterBarComponent`~~ — not a registered component (0 hits); the 8 registered Parrot composites are Chart, DataTable, KPICard, Report, InfoCard, Map, Infographic, Timeline
- ~~`parrot_theme` / `parrot_layout` / `parrot_filter_column`~~ — no such extension keys today (0 hits)
- ~~`CreateSurface.theme`~~ / ~~`CreateSurface.style`~~ — no such field; the model is `extra="forbid"` (`a2ui/models.py:463`)
- ~~`RenderSpec.layout`~~ — does not exist yet; only `profile` and `theme` (`recipes/models.py:170-171`)
- ~~`ThemeConfig.content_width` / `.density` / `.radius` / `.panel_bg`~~ — no layout tokens exist today; `ThemeConfig` is colour + font only
- ~~any `.css` file under `packages/ai-parrot-visualizations/src`~~ — none exists; `package-data` declares only `["*.js"]` (`pyproject.toml:79`)
- ~~`_render_prim_Card` honouring variants~~ — it does not; it emits a bare `<div class="a2ui-card">` (`interactive_html.py:529-531`)
- ~~a `_STYLE` rule for `.a2ui-label` / `.a2ui-value` / `.a2ui-delta`~~ — the classes are emitted, the rules do not exist
- ~~`ssr_html._render_prim_Card`~~ — wrong name; SSR dispatch omits the `_prim_` infix (`ssr_html.py:331`)
- ~~a golden fixture for rendered HTML~~ — the 8 goldens are *lowering* JSON only; there is no HTML snapshot test to update

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Read packaged assets **once at import**, never inside an async `render()` —
  the rule and its rationale are documented at `interactive_html.py:92-97`.
- Style through CSS custom properties emitted by `ThemeConfig`; never
  hardcode a colour in a renderer.
- Additive class emission only; treat every existing `a2ui-*` class as a
  public API with external consumers.
- Degrade through `degradation_record()` (`renderers/degrade.py:46`) rather
  than emitting a control that cannot work on that surface.
- Pydantic models for all structured data; Google-style docstrings and
  strict type hints; `self.logger`, never `print`.

### Known Risks / Gotchas

- **Packaging silently drops the CSS.** `[tool.setuptools.package-data]`
  (`pyproject.toml:78-79`) declares only `"parrot.outputs.formats.assets" =
  ["*.js"]`. Without a matching entry for the new package, source-tree tests
  pass and the installed wheel renders unstyled HTML. *Mitigation*: the
  `test_assets_packaged_and_non_empty` criterion, and an `__init__.py` in
  `design_system/` so setuptools treats it as a package.
- **Theme/layout namespace collision.** `corporate` is already a registered
  *theme* (`models/infographic.py:1609`). Layout names must stay disjoint:
  `report`, `analytics`, `print`. *Mitigation*: `DesignSystem.LAYOUTS` is a
  closed set, and a test asserts it does not intersect
  `theme_registry.list_themes()`.
- **WeasyPrint CSS support is not assumable.** WeasyPrint is pinned at
  `69.0` (`packages/ai-parrot/pyproject.toml:199`,
  `ai-parrot-visualizations` requires `>=68.0`). Whether
  `grid-template-columns: repeat(auto-fit, minmax(...))` renders correctly
  must be established by running it, not by reading release notes.
  *Mitigation*: `layout-print.css` avoids `auto-fit`/`minmax` outright and
  Module 6 records the empirical findings.
- **The default visual change is intentional and user-approved.** Existing
  `infographic_html` consumers see a different appearance the moment this
  lands, because `analytics` becomes the default everywhere. `report`
  reproduces the previous look, and the migration doc must say so
  prominently. Any stored screenshot or visual baseline outside this repo
  will differ.
- **`PDFRenderer` inherits SSR's CSS by subclassing** (`pdf.py:99`), so any
  change to the SSR stylesheet reaches PDF whether intended or not. The
  print layout must be forced in `PDFRenderer`, not left to a default.
- **Divergent dispatch naming** between the two renderers
  (`_render_prim_<C>` vs `_render_<C>`) makes a naive shared mixin silently
  no-op on one of them. Share helpers, not dispatch method names.
- **Artifact size.** Chart.js already adds ~200KB inline per artifact; the
  composed stylesheet adds single-digit KB. This is the explicit reason
  grid.js was rejected, and any future proposal to vendor a library should
  be weighed against the same budget.
- **Client-side filtering is the one stateful piece.** Module 8 owns data
  semantics, not presentation. It is last in dependency order and is the
  designated cut line.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | **No new runtime dependency.** The rejection of Tailwind, grid.js and CDN fonts is what keeps this table empty; the in-house table and filter JS are vanilla ES2017, consistent with `_BEHAVIOR_JS` today. |

---

## 8. Open Questions

- [x] Scope of the unification — *Resolved in brainstorming*: all A2UI HTML renderers (`interactive-html`, `ssr-html`, `pdf`) **and** the `formats/infographic_html.py` lane converge on one design system.
- [x] One aesthetic or several — *Resolved in brainstorming*: several, via a preset system — `ThemeConfig` carries layout tokens and layouts are registered presets, with `theme` and `layout` as orthogonal axes.
- [x] Component scope — *Resolved in brainstorming*: in-house rich tables (grid.js explicitly rejected), KPI hero row / card variants, and a filter bar with multiselect.
- [x] How the caller selects theme/layout — *Resolved in brainstorming*: both channels — `envelope.metadata.extensions` takes precedence, the renderer constructor supplies the default, and the runner feeds it from `RenderSpec`.
- [x] Backward compatibility of the infographic lane — *Resolved in brainstorming*: the new look becomes the default everywhere; the previous appearance stays reachable as `layout="report"`. The user accepted the visual change for existing consumers.
- [ ] Should `layout-analytics.css` set a fixed `content_width` or inherit the theme's token unmodified? — *Owner: implementer, Module 2* — decide once the first real dashboard renders; it does not block the design.
- [ ] Do any of the five registered themes need bespoke `header_bg` / `panel_bg` values, or do the derivations suffice for all? — *Owner: implementer, Module 1* — resolve empirically by rendering the 5 × 3 matrix.
- [ ] Does the pagination threshold belong in `ThemeConfig`, a renderer constant, or a `DataTable` property? — *Owner: implementer, Module 4* — a renderer constant unless a caller asks for control.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree, `.claude/worktrees/feat-493-html-renderer-design-system`.
- **Rationale**: the modules form a near-linear dependency chain
  (1 → 2 → 3 → {4, 5, 6, 7} → 8) and most of them edit the same two files
  (`interactive_html.py`, `ssr_html.py`). Parallel worktrees would spend
  more time in conflict resolution than they would save.
- **Partially parallelizable**: Modules 5, 6 and 7 are independent of each
  other once Module 3 lands (different files: `infographic_html.py`,
  `pdf.py`, `runner.py`). They may be assigned concurrently if a pool is
  available.
- **Cross-feature dependencies**: none blocking. **FEAT-491**
  (`flex-agent-infographic-a2ui`, 7 tasks in progress) does not conflict:
  its spec's Non-Goals explicitly exclude changes to core packages,
  including the A2UI runtime and renderers, and its filters are
  `RecipeParam` + `refresh_dashboard` server-side replay rather than
  client-side UI. FEAT-491 produces the envelopes this feature renders, so
  it is a consumer, not a competitor. Landing FEAT-491 first is convenient
  (it supplies the `test_flex_dashboard_envelope_renders` fixture shape)
  but not required.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-01 | Jesus Lara + Claude | Initial draft from in-chat brainstorming (approach A: CSS assets + token composer) |
