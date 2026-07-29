# TASK-1731: Folium map + ECharts payload renderers

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1723, TASK-1724, TASK-1728
**Assigned-to**: unassigned

---

## Context

Implements two more **Module 5** renderers (spec §3): `folium_map` and `echarts`.
Both are the deterministic replacements for the two worst legacy offenders:

- Legacy `formats/map.py` `FoliumRenderer` **executes LLM-generated Python** via
  `execute_code` → the raw `exec()` sink in `BaseRenderer` (same vulnerability
  class as the `python_repl` incident). The A2UI folium renderer builds the map
  **deterministically from the Map component's data** — the LLM never contributes
  code, only (optionally) an envelope that the catalog already validated.
- Legacy `formats/echarts.py` loads ECharts from a **CDN** (:245). The A2UI
  echarts renderer emits the ECharts **option JSON payload** as its primary
  output, with an optional self-contained HTML wrap that inlines the **vendored**
  `echarts.min.js` asset.

Satellite tasks, registered into the core registry (TASK-1723), consuming Map /
Chart components from Module 3 (TASK-1724) and baking via TASK-1728.

---

## Scope

- Implement `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py`:
  - Subclass core `AbstractA2UIRenderer`; **never** legacy `BaseRenderer` /
    `BaseChart` (exec sink — cited below as the forbidden pattern).
  - Register as `folium_map`; capabilities: `interactive=False`,
    `supports_actions=False`, `supports_updates=False`, `output="text/html"`
    (browser-local pan/zoom in folium HTML is not A2UI interactivity — no live
    surface, no actions).
  - Input: the baked **Map component** data (markers/geojson/center/zoom per the
    Map component schema from TASK-1724) → build the `folium.Map` **only through
    folium's Python API from component data**. No code strings, no `exec`, no
    LLM-authored anything.
  - `folium` imported lazily with an actionable ImportError naming the extras
    (`ai-parrot-visualizations[a2ui,map]`).
  - Output: folium's generated HTML document wrapped into a `RenderedArtifact`
    (`mime_type="text/html"`); bake precondition — zero live bindings in input.
- Implement `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py`:
  - Subclass core `AbstractA2UIRenderer`; register as `echarts`.
  - Input: baked **Chart component** data → deterministic ECharts **option JSON**
    (primary output, `output="application/json"` in capabilities;
    `interactive=False`, `supports_actions=False`, `supports_updates=False`).
  - Optional HTML wrap mode (renderer option / kwarg): a self-contained HTML
    document that inlines the vendored
    `formats/assets/echarts.min.js` (verified to exist) — **never** the CDN
    `<script src=…>` used by legacy `echarts.py:245`.
  - Data values destined for HTML (titles etc. in wrap mode) HTML-escaped.
- `requires_actions` components: both renderers degrade per capabilities (deep
  links on the artifact / strip + notice) or reject with a structured error —
  same policy as TASK-1729.
- Extras wiring in `packages/ai-parrot-visualizations/pyproject.toml`: both
  renderers sit behind the new `a2ui` extra; folium additionally requires the
  existing `map` extra (`folium>=0.14`, verified at :38); echarts needs no Python
  deps (`echarts = []`, verified at :37 — asset is vendored).
- Unit tests for both renderers (determinism, no-exec construction, lazy-import
  error, wrap self-containment, escaping).

**NOT in scope**:
- SSR-HTML, Adaptive Cards, PDF renderers (TASK-1729/1730/1732).
- Chart→static-SVG pre-render for weasyprint (TASK-1732 concern, per SPK-1).
- Map/Chart component schemas + lowerings themselves (Module 3, TASK-1724).
- Any change to legacy `formats/map.py` / `formats/echarts.py` (deprecation
  warnings are Module 12).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py` | CREATE | Deterministic Map-component → folium HTML renderer |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py` | CREATE | Chart-component → ECharts option JSON (+ optional vendored-JS HTML wrap) |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/__init__.py` | MODIFY | Created by TASK-1729; create if racing (regular package init) |
| `packages/ai-parrot-visualizations/pyproject.toml` | MODIFY | Ensure `a2ui` extra; document folium requirement via existing `map` extra |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py` | CREATE | Folium renderer unit tests |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts.py` | CREATE | ECharts renderer unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified references from the actual codebase (re-checked 2026-07-10).
> Do NOT invent imports/attributes not listed here — `grep`/`read` first.

### FORBIDDEN legacy pattern (the thing this task replaces)
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/map.py
@register_renderer(OutputMode.MAP, system_prompt=FOLIUM_SYSTEM_PROMPT)   # :191
class FoliumRenderer(BaseChart):                                          # :192
    def execute_code(self, code: str, ...):                               # :380
        context, error = super().execute_code(code, ...)                  # :396
    # render path: result_obj, error = self.execute_code(...)             # :898
# super() chain ends at packages/ai-parrot/src/parrot/outputs/formats/base.py:163
#   → `exec(code, namespace, locals_dict)` — LLM code execution. NEVER copy this.
# The A2UI folium renderer receives DATA, calls folium's API itself, executes nothing.

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/echarts.py:245
#   <script src="https://cdn.jsdelivr.net/npm/echarts@{echarts_version}/dist/echarts.min.js">
# External CDN — forbidden for A2UI output (self-contained rule).
```

### Verified assets / deps
```python
# Vendored ECharts bundle EXISTS (verified 2026-07-10):
#   packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/echarts.min.js (~1.0 MB)
# In-repo inlining precedent:
#   packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py:106
#     _ECHARTS_JS_PATH = Path(__file__).parent / "assets" / "echarts.min.js"
#   (loaded lazily, embedded inline — copy this approach, referencing the SAME
#    asset file; do not duplicate the 1 MB bundle into a2ui_renderers/)

# packages/ai-parrot-visualizations/pyproject.toml (verified):
#   :37  echarts = []            # JS bundled as static asset; no Python deps
#   :38  map = ["folium>=0.14"]
```

### Packaging layout (same verified finding as TASK-1729 — summary)
- Satellite has NO `__init__.py` at `src/parrot/`, `src/parrot/outputs/`,
  `src/parrot/outputs/formats/`; core `outputs/__init__.py:23-24` /
  `formats/__init__.py:1-2` use `pkgutil.extend_path`. `a2ui_renderers/` is
  satellite-owned → regular package with its own `__init__.py`.

### Interfaces created by dependency tasks (spec §2 sketch — verify against merged code)
```python
# TASK-1723 (core): register_a2ui_renderer(name, capabilities);
#   AbstractA2UIRenderer.render(self, envelope, *, bake=True) -> RenderedArtifact | str
#   RendererCapabilities(interactive, supports_actions, supports_updates, output)
# TASK-1724 (core catalog): Map / Chart ComponentDefinitions + lower() —
#   STRUCTURED_CHART/TABLE/MAP config schemas are the starting vocabulary (spec §3 Module 3)
# TASK-1728 (core): RenderedArtifact / DeepLink; bake helper (jsonpointer via viz a2ui extra)
```

### Does NOT Exist
- ~~`parrot/outputs/a2ui_renderers/{folium_map,echarts}.py`~~ — created by THIS task.
- ~~An `a2ui` extra in the viz pyproject~~ — may have been added by
  TASK-1728/1729; create it if still absent.
- ~~A deterministic data→folium builder in the legacy pipeline~~ — legacy
  `FoliumRenderer` has data-frame helpers but its render path goes through
  `execute_code`; do not import or reuse `formats/map.py` machinery.
- ~~ECharts Python bindings (`pyecharts`)~~ — not a dependency anywhere; the
  option payload is a plain dict you construct.

---

## Implementation Notes

### Key Constraints
- **G1**: zero `exec`/`eval`; neither renderer accepts code strings in any field.
  The Map/Chart component schemas (TASK-1724) are the only input contract.
- **Determinism**: same baked component data → identical option JSON; folium HTML
  contains folium-generated element ids — normalize or seed them if folium offers
  it, otherwise assert on stable substructure (markers, coordinates, tile config)
  rather than byte equality, and document why.
- Folium tile layers reference tile-server URLs at *view* time; that is a map-tile
  runtime concern, not a rendering dependency — but do not add any `<script>`/CSS
  CDN beyond what folium itself emits; document folium's own CDN assets as a known
  limitation in the module docstring (PDF path uses SSR alternatives, TASK-1732).
- Lazy imports with actionable errors (embeddings-registry / `_markdown_to_pdf`
  style): folium → name `ai-parrot-visualizations[a2ui,map]`.
- Async `render`; Pydantic v2; Google-style docstrings; module logger, no prints.

### References in Codebase
- `formats/structured_map.py:177` (`StructuredMapRenderer`) — config-driven map
  vocabulary precedent (schema ideas only; it still inherits legacy `BaseChart`,
  so do not import it).
- `formats/infographic_html.py:106` — vendored-asset inlining.
- `packages/ai-parrot/src/parrot/embeddings/registry.py` — ImportError shape.

---

## Acceptance Criteria

- [ ] `folium_map` registered; builds folium maps deterministically from Map
      component data via the folium Python API — no code-string input path exists
- [ ] `echarts` registered; emits deterministic ECharts option JSON; optional HTML
      wrap inlines the vendored `formats/assets/echarts.min.js`, never a CDN URL
- [ ] Both declare `interactive=False`, `supports_actions=False`,
      `supports_updates=False`; outputs `text/html` (folium) / `application/json`
      (echarts primary)
- [ ] Both bake (zero live bindings) and degrade/reject `requires_actions`
      components per policy
- [ ] Missing folium → ImportError naming `ai-parrot-visualizations[a2ui,map]`
- [ ] Both return `RenderedArtifact` with correct `mime_type`/`surface`
- [ ] All tests pass: `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers`
- [ ] No exec/eval: `grep -rn "exec(\|eval(" packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers` returns nothing
- [ ] `BaseRenderer`/`BaseChart` and `formats/map.py`/`formats/echarts.py` never imported

---

## Test Specification

> Minimal scaffold — names and intent only; the agent fills in bodies.

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py
class TestFoliumMapRenderer:
    def test_capabilities_declared(self):
        """interactive=False, supports_actions=False, output='text/html'."""
        ...

    async def test_map_built_from_component_data_only(self):
        """Markers/center/zoom from the baked Map component appear in the folium
        HTML; the renderer exposes no code-string input path."""
        ...

    async def test_deterministic_map_structure(self):
        """Same component data yields the same marker/coordinate/tile structure
        across runs."""
        ...

    def test_missing_folium_actionable_error(self):
        """Without folium installed, render raises ImportError naming
        ai-parrot-visualizations[a2ui,map]."""
        ...

    async def test_requires_actions_degrades_or_rejects(self):
        """Action-bearing components degrade to deep links / stripped-with-notice
        or reject with a structured error."""
        ...


# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts.py
class TestEChartsRenderer:
    def test_capabilities_declared(self):
        """interactive=False, supports_actions=False, output='application/json'."""
        ...

    async def test_option_payload_deterministic_golden(self):
        """Baked Chart component maps to the expected ECharts option JSON (golden,
        byte-stable)."""
        ...

    async def test_html_wrap_inlines_vendored_bundle_no_cdn(self):
        """Wrap mode embeds assets/echarts.min.js inline; no external script/CDN
        URL appears in the document."""
        ...

    async def test_wrap_escapes_data_values(self):
        """Hostile strings in chart titles/labels appear only HTML-escaped in the
        wrapped document."""
        ...

    async def test_output_has_zero_live_bindings(self):
        """Option JSON contains no unresolved JSON Pointer binding syntax."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index (`sdd/tasks/index/`) → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1731-renderers-folium-echarts.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Notes**: Implemented `EChartsRenderer` (registered `echarts`, output
`application/json`) and `FoliumMapRenderer` (registered `folium_map`, output
`text/html`), both subclassing the core `AbstractA2UIRenderer` and baking first.
`EChartsRenderer` builds a deterministic ECharts option dict from the baked Chart
component data (xAxis/yAxis/series by y-columns; area→areaStyle; pie drops axes); a
`wrap_html=True` mode inlines the vendored `formats/assets/echarts.min.js` (never a
CDN) and neutralizes `<` in the embedded option JSON + escapes the title.
`FoliumMapRenderer` builds a `folium.Map` purely via folium's Python API from the baked
Map component's viewport + point data (no code strings, no exec); folium imported
lazily with actionable ImportError naming `ai-parrot-visualizations[a2ui,map]`. 13
tests pass; ruff clean; no exec/eval; legacy `map.py`/`echarts.py`/`BaseChart` never
imported.

**Deviations from spec**: `EChartsRenderer.render` adds an optional `wrap_html` kwarg
(the task's specified HTML-wrap mode). Both renderers target display-only Chart/Map
components (`requires_actions=False`), so the "degrade/reject requires_actions" policy
is not exercised — these renderers select their target component and raise `ValueError`
if it is absent.
