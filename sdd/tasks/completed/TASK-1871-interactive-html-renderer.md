# TASK-1871: Interactive-HTML renderer (Chart.js baked, self-contained)

**Feature**: FEAT-324 — Infographic Builder — Recipe-Driven, Replayable A2UI Infographics
**Spec**: `sdd/specs/infographic-builder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 7 of FEAT-324 (spec G7). The existing `SSRHTMLRenderer` is deliberately static
(zero `<script>`); this task adds the `interactive-html` profile in ai-parrot-visualizations:
a single self-contained HTML document with vendored Chart.js v4 and vanilla-JS behaviors
(day tabs, metric toggle, column sort), mirroring the reference template
`sdd/artifacts/budget_variance_dashboard_Template.html`. Touches ONLY the visualizations
satellite → parallelizable with the core-package tasks.

---

## Scope

- Vendor Chart.js v4.x as a minified asset in the visualizations package (alongside the
  existing vendored echarts asset — locate it and follow the same placement/licensing
  convention; keep the upstream license header in the file).
- Implement
  `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`:
  - `InteractiveHTMLRenderer(AbstractA2UIRenderer)` with
    `capabilities = RendererCapabilities(interactive=True, supports_actions=False,
    supports_updates=False, output="text/html")`.
  - `async render(envelope, *, bake=True) -> RenderedArtifact` producing ONE HTML document:
    - embedded dataModel: `<script type="application/json" id="report-data">{...}</script>`
      (the reference template's pattern — data separable from markup);
    - inline vendored Chart.js + a small vanilla-JS runtime rendering `Chart` components from
      their catalog properties (`type`, `x`, `y`, `data` binding) against the embedded JSON;
    - behaviors: tab groups (e.g. day ribbon switching the active dataset slice), metric
      toggle buttons, client-side column sort for `DataTable` components;
    - non-Chart components (KPICard, DataTable, Card, Infographic sections) rendered
      server-side from the lowered Basic tree, same as SSR-HTML does;
    - ZERO external network references (no CDN, no Google Fonts `@import` — system font
      stack; the reference template's `@import` must NOT be reproduced).
  - Module-level self-registration: `register_a2ui_renderer("interactive-html", ...)` on
    import (same mechanism as `ssr_html.py`).
- Tests: self-containment (no `http(s)://` refs), dataModel JSON embedded and parseable,
  Chart.js + behavior JS present, non-Chart components rendered, registration resolves via
  `get_a2ui_renderer("interactive-html")`.

**NOT in scope**: recipes/runner (core tasks), actions/server-push (FEAT-B non-goal),
PDF of interactive output (static profiles already cover print).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py` | CREATE | renderer |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/assets/chart.umd.min.js` | CREATE | vendored Chart.js v4 (match existing echarts asset location convention — verify actual assets dir first) |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer, RendererCapabilities, register_a2ui_renderer,
)  # core renderers/__init__.py __all__:26-31
from parrot.outputs.a2ui.models import CreateSurface        # a2ui models
from parrot.outputs.a2ui.artifacts import RenderedArtifact  # artifacts.py:41
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
class RendererCapabilities(BaseModel):
    interactive: bool; supports_actions: bool; supports_updates: bool; output: str
class AbstractA2UIRenderer(ABC):
    capabilities: RendererCapabilities
    @abstractmethod
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> "Any | str": ...
# Resolution: get_a2ui_renderer("interactive-html") importlib-imports
# "parrot.outputs.a2ui_renderers.interactive_html" if not yet registered — the module
# filename MUST therefore be interactive_html.py (name→module mapping; read the resolver
# in renderers/__init__.py to confirm the exact name normalization before finalizing).

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py — TEMPLATE
class SSRHTMLRenderer(AbstractA2UIRenderer):   # line 59
    async def render(self, envelope, ...):     # line 62
    def _render_component(self, comp: dict[str, Any]) -> str:   # line 109
    def _render_basic(self, node: BasicNode) -> str:            # line 129
# Copy its structure: lowering via catalog components, inline CSS, RenderedArtifact assembly.

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/chart.py
# Chart properties vocabulary: type (StructuredChartConfig types), x, y (list),
# data ({'$bind': '/pointer'}), showLegend, title — lines 26-49.

# REFERENCE MARKUP (visual + behavior semantics to emulate, not to copy verbatim):
# sdd/artifacts/budget_variance_dashboard_Template.html —
#   <script type="application/json" id="report-data"> pattern (line ~97),
#   .daytab / .metricbtn behaviors, ledger table with division rollup styling.
```

### Does NOT Exist
- ~~Vendored Chart.js anywhere in the repo~~ — THIS task adds it; only ECharts is vendored
  today (find its exact path with `grep -r "echarts.min" packages/ai-parrot-visualizations/`
  and mirror the convention)
- ~~`InteractiveHTMLRenderer`~~ — created by THIS task
- ~~Script support in SSRHTMLRenderer~~ — it is script-free BY DESIGN (`interactive=False`,
  ssr_html.py:53); do NOT modify it — new renderer, new file
- ~~An `interactive=True` renderer precedent~~ — this is the first; `capabilities.output`
  stays `"text/html"` (the `"live"` literal is for FEAT-B live surfaces, not this)

---

## Implementation Notes

### Key Constraints
- The behavior JS must be generic — driven by component properties and the dataModel, NOT
  hardcoded to the budget dashboard. The budget dashboard is the acceptance EXAMPLE
  (TASK-1873), not the implementation.
- Keep the JS runtime small and reviewable (single `<script>` block, no build step, ES2017);
  document each behavior hook (`data-tabs-group`, `data-sort-table`, etc.) in module docstring.
- Escape/serialize the dataModel JSON safely (`</script>` breaking — use the standard
  `json.dumps(...).replace("</", "<\\/")` guard).
- Artifact assembly: follow ssr_html.py's `RenderedArtifact` construction (mime_type
  `text/html`, `surface="interactive-html"`, inline `content` under the size threshold used
  there — read how ssr_html decides content vs path and mirror it).
- License: keep Chart.js MIT header in the vendored file; note version in a comment.

### References in Codebase
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py` — structure to copy
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py` — vendored-asset handling precedent
- `sdd/artifacts/budget_variance_dashboard_Template.html` — behavior/visual reference

---

## Acceptance Criteria

- [ ] `get_a2ui_renderer("interactive-html")` resolves after satellite import
- [ ] Output is ONE self-contained HTML: zero `http(s)://` references
      (`test_interactive_html_self_contained`), works from `file://`
- [ ] dataModel embedded as parseable JSON in `<script id="report-data">`
- [ ] Chart components render via Chart.js from catalog properties; KPICard/DataTable/Card/
      Infographic render server-side
- [ ] Day-tab, metric-toggle and column-sort behaviors present and driven by data attributes
- [ ] Chart.js vendored with license header; version pinned in comment
- [ ] All tests pass: `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py
class TestInteractiveHTML:
    async def test_registration_resolves(self): ...
    async def test_interactive_html_self_contained(self, infographic_envelope):
        html = ...; assert "http://" not in html and "https://" not in html
    async def test_datamodel_embedded_and_parseable(self, ...): ...
    async def test_chart_rendered_from_properties(self, ...): ...
    async def test_sort_and_tab_hooks_present(self, ...): ...
```

---

## Agent Instructions

1. **Read the spec** (G7 + §7 risks) and `ssr_html.py` in full first
2. **Check dependencies** — none (parallel-safe: touches only ai-parrot-visualizations)
3. **Verify the Codebase Contract** — locate the real echarts asset path before placing Chart.js
4. **Update status** in `sdd/tasks/index/infographic-builder.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-22
**Notes**: Verified the vendored ECharts asset's REAL location before placing
Chart.js — it lives at `outputs/formats/assets/echarts.min.js` (grep-verified
via `echarts.py`'s `_ECHARTS_JS_PATH`), NOT under a new `a2ui_renderers/
assets/` dir as the task's own file table guessed (its "verify actual assets
dir first" caveat was correct to flag). Vendored a legitimate local Chart.js
v4.5.1 UMD MIT build (found via an existing `node_modules/chart.js` install
already present on this machine from an unrelated frontend project — no
network fetch performed) at
`outputs/formats/assets/chart.umd.min.js`, mirroring the echarts placement
exactly; MIT license header preserved verbatim, version pinned in a renderer
comment. `ChartComponent.lower()`/`DataTableComponent.lower()` intentionally
degrade to text-summary/opaque-property Basic nodes (graphics are a
renderer concern, same precedent as `EChartsRenderer`) — the renderer
therefore intercepts `Chart`/`DataTable` BEFORE lowering (both top-level and
nested inside `Infographic` sections, which required reimplementing
Infographic's title/subtitle/section scaffolding rather than delegating to
`InfographicComponent.lower()`, which would degrade nested charts). Behavior
hooks are fully generic (`data-chart-config`, `data-tabs-for`/
`data-tab-index` for day-tabs — rendered only when a Chart's properties
carry an OPTIONAL `tabs` list, `data-metric-toggle-for`/`data-metric-index`
for y-column toggling, `data-sort-table`/`data-sort-key` for client-side
table sort), documented in the module docstring. 49/49 tests pass in
`ai-parrot-visualizations` (10 new); `ruff check` clean; no regressions in
`ai-parrot`'s own a2ui test suite (175 passed, 4 pre-existing skips).

**Deviations from spec**: Fixed a PRE-EXISTING gap in the worktree root
`conftest.py`: `ai-parrot-visualizations` was missing from `_EXTRA_PATHS`,
so `pkgutil.extend_path`-based namespace merging (`parrot.outputs.__init__`)
only ever found the main-repo editable-install copy of
`parrot.outputs.a2ui_renderers`, making ANY worktree-local change to this
satellite package invisible to tests — this silently blocked the task's own
"All tests pass" acceptance criterion. Added one path entry mirroring the
existing pattern exactly (zero behavioral change beyond making worktree
changes visible); not in the task's declared Files to Create/Modify, but
required infra correction, not scope creep into feature code.
