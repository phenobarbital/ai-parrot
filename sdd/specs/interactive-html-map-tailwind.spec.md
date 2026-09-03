---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Interactive-HTML Map Rendering + Tailwind CSS Coverage

**Feature ID**: FEAT-522
**Date**: 2026-09-03
**Author**: Jesus Lara (jesuslarag@gmail.com)
**Status**: draft
**Target version**: next minor (`ai-parrot-visualizations`)

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-493 (`html-renderer-design-system`, PR #1296, merged 2026-09-02) shipped a real
design-system CSS pipeline for the `interactive-html` A2UI renderer
(`packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`)
but left two gaps that surfaced on the first real dashboard exercised end-to-end against
production data (`agents/flex_dashboard.py`, six real Flex QuerySource datasets):

1. **No real Map rendering.** `InteractiveHTMLRenderer.supported_components`
   (interactive_html.py:537-559) does not include `"Map"`. `MapComponent.lower()`
   (`packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/map.py:78-114`)
   unconditionally degrades any `Map` node to a static `Card → Column → Text`
   layer-summary before `interactive_html.py` ever sees it, even though a real
   interactive Leaflet map renderer already exists as a separate renderer surface
   (`folium_map.py`, `supported_components={"Map"}`). A dashboard's "Proximity
   Staffing" map (store/employee geolocation) therefore renders as plain text
   (`"stores | label=store_name | color=#1f77b4"`).
2. **Base primitive CSS classes have zero styling.** `DesignSystem.stylesheet()`
   (`packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py:88-119`)
   covers composite classes (`.kpi-card`, `.ds-title`, `.filter-*`, …) but has **zero**
   rules for the base primitives `interactive_html.py` emits constantly
   (`.a2ui-text`, `.a2ui-label`, `.a2ui-value`, `.a2ui-col`, `.a2ui-title`,
   `.a2ui-heading`, `.a2ui-section`, `.a2ui-chart-wrap`, `.a2ui-table-wrap`). Most of
   any dashboard renders with browser-default, unstyled appearance despite a real
   `<style>` block being present.

Both gaps were invisible in FEAT-493's own test suite and only became visible on a
real, data-heavy, mixed-component dashboard. This feature closes both gaps as one
combined follow-up to FEAT-493. Full options analysis and discovery trail:
`sdd/proposals/interactive-html-map-tailwind.brainstorm.md`.

**Spec-time correction (2026-09-03) — the "offline" constraint runs deeper than the
brainstorm assumed.** During spec research, `folium.Map()` (the installed
`folium==0.20.0`) was rendered directly and inspected: even an empty map with no
plugins emits **4 external `<script src=`/6 external `<link href=`** resources
(Leaflet, jQuery, Bootstrap, Font Awesome, Leaflet.awesome-markers — these are
`folium.Map`'s own hardcoded `JSCSSMixin.default_js`/`default_css` class-level
defaults, not something avoidable by choosing not to use those plugins); adding
`folium.plugins.MarkerCluster` (already required by this feature's resolved
threshold decision, §8) contributes one more JS + two more CSS resources. The
existing guardrail test, `test_document_shell.py:44-46`
(`assert "<script src=" not in doc`), does **not** catch this once the folium
document is embedded inside an `iframe srcdoc="..."`: HTML-escaping turns `<` into
`&lt;`, so the literal substring the test looks for never appears in the outer
document — the test would pass while a real browser still fetches from 4-6 external
CDN domains when the map renders. This is also a **pre-existing, currently
untested gap in the standalone `folium_map` renderer surface itself**
(`test_folium_map.py` has no offline/self-contained assertion at all today) — see
§7 Known Risks and the Non-Goals/Goals split below.

### Goals

- `Map` components render as real, interactive Leaflet maps — at both the top-level
  and Infographic-nested call sites — inside `interactive-html` documents.
- Every CSS class `interactive_html.py` emits has a real style rule; the coverage gap
  cannot silently reopen as new primitives are added (CI-enforced).
- The embedded Map document is **genuinely** self-contained/offline: zero runtime
  network fetch for its own rendering (JS/CSS), not just a guardrail-test pass. This
  supersedes the brainstorm's original (narrower) framing of the same constraint.
- The same offline-vendoring fix also closes the pre-existing CDN-leak gap in the
  standalone `folium_map` renderer surface, as a low-marginal-cost side effect of
  sharing one builder (§2).
- `MarkerCluster` wraps a layer's markers once its point count passes a threshold
  (default 500, per-layer overridable — resolved in brainstorm, §8).

### Non-Goals (explicitly out of scope)

- **`RecipeRunner` multi-renderer composition** — `RecipeRunner._render_or_raise`
  (`packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py:649-667`)
  resolves and invokes exactly one renderer per run. Map support is implemented
  entirely inside `InteractiveHTMLRenderer`; `RecipeRunner` is untouched.
  (Brainstorm constraint, carried forward.)
- **Native, from-scratch Leaflet reimplementation** (brainstorm Option B) and
  **inline non-iframe fragment sharing** (brainstorm Option C) — rejected during
  brainstorm in favor of Option A's `iframe`-isolated folium composition; see
  `sdd/proposals/interactive-html-map-tailwind.brainstorm.md` "Recommendation" for
  the full tradeoff.
- **Fixing `agents/flex_dashboard.py`'s `proximity_staffing` data-shaping issue**
  (the ~27k-unfiltered-marker transformer gap, `transformers.py:406-485`) — a
  separate, already-identified issue. `MarkerCluster` in this feature makes that
  volume of data renderable, but does not fix the underlying filter bug.
- **Exposing a cluster-threshold field on the `MapLayer` LLM-facing schema**
  (`parrot.models.outputs.MapLayer`, which `derive_schema()` turns into the
  structured-output generation contract for every Map-producing surface, not just
  `interactive-html`). The threshold is a rendering-only concern; it is a
  renderer-level parameter (§2 Data Models), never an LLM-settable property. Adding
  it to the schema would be a much larger surface change than this feature's scope.
- **Retrofitting `ssr_html.SSRHTMLRenderer` or `formats/infographic_html`** with Map
  support — this feature covers `interactive-html` and (as a side effect, §2)
  `folium_map` only.

---

## 2. Architectural Design

### Overview

Recommended option (brainstorm Option A, spec-corrected): extend
`InteractiveHTMLRenderer` to treat `"Map"` as a fourth intercepted,
natively-rendered component type (alongside `Chart`/`DataTable`/`Infographic`).
When a Map node is encountered — in `_render_top` (top-level) or
`_render_descriptor` (nested inside an `Infographic` section) — a **new shared,
synchronous builder function** in `folium_map.py` constructs a `folium.Map` from
the node's already-baked properties, wraps high-count layers in
`folium.plugins.MarkerCluster` (threshold 500, per-layer overridable), and
**swaps every one of folium's default external JS/CSS resource URLs for an
inlined `data:` URI built from a locally vendored copy of that same file**
(base64-encoded, read once at import time — mirrors this codebase's existing
`_CHART_JS_SOURCE` / `_BASE_CSS` "read once, never per-render" convention) before
producing the final HTML string. The result is embedded as
`<iframe sandbox="allow-scripts allow-popups" srcdoc="...">`.

**Why a new shared builder, not calling `FoliumMapRenderer.render()` directly (the
brainstorm's original plan):** `FoliumMapRenderer.render()`
(folium_map.py:76) is `async def`, but contains no `await` anywhere in its body —
it is declared async purely to satisfy the `AbstractA2UIRenderer` interface, while
every line of `InteractiveHTMLRenderer`'s internal render chain
(`_render_top`/`_render_descriptor`/`_render_chart`/…, interactive_html.py:679-762)
is a plain **synchronous** call chain (a list comprehension calling
`self._render_top(...)` with no `await`, interactive_html.py:609). Calling an
`async def` from that chain would require either bridging (bad — `asyncio.run()`
inside a running event loop, or threading `await` through every caller up to
`render()`'s own comprehension) for a function that does zero actual async I/O.
The fix: extract the current body of `FoliumMapRenderer.render()` into a new
**synchronous** module-level function, `build_map_document()` (§2 New Public
Interfaces), that both renderers call directly — `FoliumMapRenderer.render()`
becomes a thin async wrapper around it (unchanged behavior, unchanged public
surface), and `InteractiveHTMLRenderer._render_map()` calls it synchronously with
no coroutine involved.

**Why not `folium.Map.add_js_link()`/`.add_css_link()` (the mechanism floated
during spec-time discovery):** `JSCSSMixin.default_js`/`default_css`
(`folium/elements.py`, vendored dependency) are **class-level** mutable list
attributes (`List[Tuple[str, str]] = []`), shared across every `folium.Map`
instance in the process. `add_js_link()`/`add_css_link()` mutate that shared list
in place. Under `asyncio`'s cooperative scheduling this happens to be safe *as
long as* the swap-and-render sequence contains no `await` (no other task can
interleave), but it is fragile shared global state that a future refactor could
silently break, and it also mutates behavior for any *unrelated* `folium.Map`
instance created anywhere else in the same process for the rest of its lifetime.
`build_map_document()` instead does a plain, local `str.replace(cdn_url,
data_uri)` pass over the **already-rendered HTML string** it owns — no shared
mutable state touched at all.

For Tailwind: a new script, `scripts/generate_a2ui_css.py`, AST-scans
`interactive_html.py`'s literal class-string vocabulary (mirrors the existing
`scripts/generate_tool_registry.py --check` pattern exactly — same repo, same
"scan source, diff, fail in CI" shape), builds a Tailwind v4 safelist, runs the
Tailwind CLI in CSS-first mode (no `tailwind.config.js`/PostCSS needed for
`@apply` in v4 — resolves the brainstorm's deferred "v3 vs v4" open question) to
`@apply` utilities onto the *existing* semantic selectors, and writes the result
to a new committed CSS asset, `design_system/tailwind.generated.css`, folded into
`DesignSystem.stylesheet()`'s existing concatenation. `--check` mode regenerates
in-memory and fails if the committed file has drifted — wired into
`.github/workflows/ci.yml`'s existing `lint-and-registry` job (a closer match
than the brainstorm's `release.yml` Node/pnpm suggestion: that job builds and
ships the Admin UI *into the wheel* at release time; this is a "generate once,
commit, verify freshness on every PR" job, the same shape as the adjacent "Check
registry freshness" step already in that job).

### Component Diagram

```
InteractiveHTMLRenderer.render()
  └─ _render_top() / _render_descriptor()      (existing dispatch, unchanged)
       ├─ name == "Chart"     → _render_chart()      (existing, unchanged)
       ├─ name == "DataTable" → _render_datatable()  (existing, unchanged)
       ├─ name == "Map"       → _render_map()         [NEW]
       │     └─ folium_map.build_map_document(props, cluster_threshold=500)  [NEW, sync]
       │           ├─ folium.Map + folium.plugins.MarkerCluster  (existing lib)
       │           └─ _OFFLINE_ASSET_MAP swap (data: URIs)        [NEW]
       │                 sourced from _VENDORED_JS / _VENDORED_CSS
       │                 (read once at import time, formats/assets/*)  [NEW files]
       └─ else → _render_basic() / .lower()          (existing, unchanged)

FoliumMapRenderer.render()  (folium_map surface, unchanged public signature)
  └─ folium_map.build_map_document(props, cluster_threshold=500)  [NEW, shared]
        (same offline-vendoring fix now applies to this surface too — side effect)

DesignSystem.stylesheet()
  └─ concatenates: theme vars + _BASE_CSS + _COMPONENTS_CSS + _TAILWIND_CSS [NEW] + layout_css

scripts/generate_a2ui_css.py  (new, standalone — not imported at runtime)
  ├─ AST-scan interactive_html.py → literal a2ui-* class vocabulary
  ├─ Tailwind v4 CLI → @apply rules onto existing selectors
  ├─ writes design_system/tailwind.generated.css
  └─ --check mode: regenerate in-memory, diff, exit 1 on drift
        └─ wired into .github/workflows/ci.yml: lint-and-registry job [NEW step]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `InteractiveHTMLRenderer._INTERCEPTED` (interactive_html.py:110) | extends | Gains `"Map"` — read by `_lower_composites` (interactive_html.py:648), the actual pre-bake gate that decides whether `MapComponent.lower()` runs. |
| `InteractiveHTMLRenderer._render_top` / `_render_descriptor` (interactive_html.py:679, 692) | extends | Both gain a `name == "Map"` branch, mirroring the existing `"Chart"`/`"DataTable"` branches. |
| `InteractiveHTMLRenderer.supported_components` (interactive_html.py:537-559, the `RendererCapabilities` set) | extends | Gains `"Map"`. |
| `folium_map.py`'s `FoliumMapRenderer.render()` (folium_map.py:76) | refactors | Body extracted into new module-level `build_map_document()`; `render()` becomes a thin async wrapper. Public signature (`render(envelope, *, bake=True) -> RenderedArtifact`) unchanged. |
| `DesignSystem.stylesheet()` (design_system/__init__.py:88-119) | extends | Gains one more concatenated source, `_TAILWIND_CSS`, read the same way as `_BASE_CSS`/`_COMPONENTS_CSS` (module-level, read-once-at-import). |
| `ai-parrot-visualizations/pyproject.toml` package-data | extends | `"parrot.outputs.formats.assets" = ["*.js"]` → `["*.js", "*.css"]` (new vendored map CSS files land flat in `formats/assets/`, same directory as `chart.umd.min.js`/`echarts.min.js`). `design_system`'s existing `["*.css"]` entry already covers the new `tailwind.generated.css` file — no change needed there. |
| `.github/workflows/ci.yml`'s `lint-and-registry` job | new CI step | New step after "Check registry freshness" (ci.yml:29-30): `uv run python scripts/generate_a2ui_css.py --check`. |
| `test_document_shell.py`, `test_interactive_html.py`, `test_folium_map.py` | extends | New assertions; existing substring-based tests unaffected since markup class names are unchanged (styled via `@apply`, not renamed). |

### Data Models

No new Pydantic models. One new plain-function parameter (not a schema field —
see Non-Goals):

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py
DEFAULT_CLUSTER_THRESHOLD: int = 500

def build_map_document(
    props: dict[str, Any],
    *,
    cluster_threshold: int = DEFAULT_CLUSTER_THRESHOLD,
) -> tuple[bytes, list[dict[str, Any]]]:
    """Build one offline-safe folium HTML document from baked Map properties.

    Returns:
        (document_bytes, degradations) — degradations mirrors the sibling-
        component-skip records `FoliumMapRenderer.render()` already produces.
    """
```

A layer's own `clusterThreshold` (if a future feature adds one to `MapLayer`) is
explicitly out of scope here (see Non-Goals); "per-layer overridable" for this
feature means `build_map_document()` accepts a `dict[str, int]` layer-name
override map as an *additional* optional keyword, read from renderer-internal
config — never from the wire schema:

```python
def build_map_document(
    props: dict[str, Any],
    *,
    cluster_threshold: int = DEFAULT_CLUSTER_THRESHOLD,
    cluster_threshold_by_layer: dict[str, int] | None = None,
) -> tuple[bytes, list[dict[str, Any]]]:
    ...
```

### New Public Interfaces

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py
def build_map_document(
    props: dict[str, Any],
    *,
    cluster_threshold: int = 500,
    cluster_threshold_by_layer: dict[str, int] | None = None,
) -> tuple[bytes, list[dict[str, Any]]]:
    """Synchronous — see Data Models above. Called by both FoliumMapRenderer.render()
    and InteractiveHTMLRenderer._render_map()."""

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py
class InteractiveHTMLRenderer(AbstractA2UIRenderer):
    def _render_map(self, props: dict[str, Any]) -> str:
        """Mirrors _render_chart's shape (interactive_html.py:961): sync method,
        takes the baked component's own top-level props dict, returns an HTML
        fragment — here, one <iframe sandbox="allow-scripts allow-popups"
        srcdoc="..."> element."""
```

---

## 3. Module Breakdown

### Module 1: Offline-safe shared map builder (`folium_map.py`)
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py`
- **Responsibility**: Extract the current `FoliumMapRenderer.render()` body into
  `build_map_document()` (sync, module-level). Add `folium.plugins.MarkerCluster`
  wrapping above `cluster_threshold` (default 500, per-layer overridable). Add the
  offline data-URI swap: for every `(name, cdn_url)` pair in `folium.Map`'s and
  `folium.plugins.MarkerCluster`'s `default_js`/`default_css` (11 pairs without
  clustering triggered, 13 with — verified against installed `folium==0.20.0`,
  §6), replace `cdn_url` with a `data:` URI built from a locally vendored copy of
  that exact file, via a plain string `.replace()` pass over the rendered HTML —
  **not** `add_js_link()`/`add_css_link()` (§2 rationale). `FoliumMapRenderer.render()`
  becomes a 3-line async wrapper calling this function and building the
  `RenderedArtifact`; its public signature and existing tests are unchanged.
- **Depends on**: existing `folium`, `folium.plugins.MarkerCluster` (no new
  pyproject dependency — both already ship with the declared `folium>=0.14` extra).

### Module 2: Vendored offline map assets
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/`
  (flat, same directory as `chart.umd.min.js`/`echarts.min.js` — "shares the
  `formats/assets/` placement convention" per the existing `_CHART_JS_PATH`
  comment at interactive_html.py:140-141)
- **Responsibility**: One-time vendoring of the exact versions `folium==0.20.0`
  currently pins as defaults (verified §6): `leaflet@1.9.3` (js+css), `jquery-3.7.1`
  (js), `bootstrap@5.2.2` (js bundle + css), `bootstrap-glyphicons` (css, pinned
  3.0.0 per folium's own default URL), `fontawesome-free@6.2.0` (css),
  `Leaflet.awesome-markers@2.0.2` (js+css), `leaflet.awesome.rotate` (css, folium's
  own template asset), `leaflet.markercluster@1.1.0` (js+css×2) — 8 JS-or-CSS
  logical resources, 13 files total. All permissively licensed (Leaflet BSD-2,
  jQuery MIT, Bootstrap MIT, Font Awesome Free MIT/OFL/CC-BY, awesome-markers MIT,
  markercluster MIT) — same asset-maintenance caveat the brainstorm already flagged
  for its rejected Option B.
- **Depends on**: none (static files).

### Module 3: `InteractiveHTMLRenderer` Map dispatch
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`
- **Responsibility**: `_INTERCEPTED` gains `"Map"` (line 110). `supported_components`
  gains `"Map"` (line ~552). New `_render_map(self, props) -> str` method
  (mirrors `_render_chart`'s shape) calling `folium_map.build_map_document(props,
  cluster_threshold=500)` and wrapping the result in
  `f'<iframe sandbox="allow-scripts allow-popups" srcdoc="{html.escape(document.decode())}"></iframe>'`.
  `_render_top` (line 679) and `_render_descriptor` (line 692) each gain a
  `if name == "Map": return self._render_map(...)` branch, positioned identically
  to the existing `"Chart"`/`"DataTable"` branches.
- **Depends on**: Module 1.

### Module 4: Tailwind CSS generation + integration
- **Path**: `scripts/generate_a2ui_css.py` (new); output written to
  `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/tailwind.generated.css`
  (new)
- **Responsibility**: AST-scan `interactive_html.py` (mirrors
  `scripts/generate_tool_registry.py`'s `ast`-based source scanning, confirmed
  §6) for every literal `a2ui-*`/`ds-*` class string constant, build a Tailwind v4
  safelist, invoke the Tailwind v4 CLI (CSS-first `@import "tailwindcss"` config,
  no `tailwind.config.js`/PostCSS step required for `@apply` in v4 — resolves the
  brainstorm's deferred v3-vs-v4 question) to compile utilities and `@apply` them
  onto the *existing* semantic selectors (`.a2ui-text`, `.a2ui-col`, …) — markup
  class names never change, so `test_document_shell.py`/`test_interactive_html.py`'s
  substring assertions keep passing unmodified. `--check` mode: regenerate
  in-memory, diff against the committed file, exit 1 on any difference (mirrors
  `generate_tool_registry.py --check`, confirmed §6).
- **Depends on**: none (dev/CI-time only; no runtime import).

### Module 5: `DesignSystem` integration
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py`
- **Responsibility**: New `_TAILWIND_CSS: str = _read_asset("tailwind.generated.css") or ""`
  module-level constant (line ~57, alongside `_BASE_CSS`/`_COMPONENTS_CSS`),
  folded into `stylesheet()`'s `sheet = "\n\n".join(...)` tuple (line ~108-114),
  positioned after `_COMPONENTS_CSS` and before `layout_css` (base-primitive
  coverage, not layout-specific).
- **Depends on**: Module 4's output file.

### Module 6: CI freshness gate
- **Path**: `.github/workflows/ci.yml`
- **Responsibility**: New step in the existing `lint-and-registry` job (after
  "Check registry freshness", ci.yml:29-30):
  `uv run python scripts/generate_a2ui_css.py --check`. This single check covers
  BOTH the Tailwind CSS staleness (resolved: fail the build, §8) and — via the
  same script's `--check` scanning the vendored-asset name set against
  `folium.Map`/`MarkerCluster`'s currently-installed `default_js`/`default_css`
  names — a future `folium` version bump that silently adds/renames a default
  resource this feature hasn't vendored yet (closing the gap before it can
  reopen, same intent as the Tailwind staleness check).
- **Depends on**: Module 4's script existing with a `--check` mode.

### Module 7: Tests
- **Path**: `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/`
- **Responsibility**: see §4.
- **Depends on**: Modules 1-6.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_build_map_document_basic` | Module 1 | Baked single-layer Map props → valid HTML bytes, no degradations. |
| `test_build_map_document_marker_cluster_above_threshold` | Module 1 | Layer with >500 points → output contains `MarkerCluster` init call. |
| `test_build_map_document_marker_cluster_below_threshold` | Module 1 | Layer with <500 points → individual markers, no `MarkerCluster`. |
| `test_build_map_document_per_layer_threshold_override` | Module 1 | `cluster_threshold_by_layer={"stores": 10}` overrides the global default for that one layer. |
| `test_build_map_document_zero_network_resources` | Module 1 | Every `default_js`/`default_css` URL from `folium.Map`/`MarkerCluster` (introspected live from the installed `folium` package, not hardcoded) is ABSENT from the output; every corresponding `data:` URI IS present. |
| `test_build_map_document_empty_layers` | Module 1 | Zero-layer Map props → empty-state map card, no exception (mirrors Chart/DataTable empty-data degradation). |
| `test_folium_map_renderer_unchanged_public_behavior` | Module 1 | `FoliumMapRenderer.render()` (existing async surface) still returns a `RenderedArtifact` with identical shape/metadata to pre-refactor — regression guard on the extraction. |
| `test_generate_a2ui_css_check_mode_clean` | Module 4 | `--check` on an up-to-date generated file exits 0. |
| `test_generate_a2ui_css_check_mode_stale` | Module 4 | `--check` after editing `interactive_html.py` to add a new literal class (without regenerating) exits 1. |
| `test_generate_a2ui_css_vendor_check` | Module 4/6 | `--check` fails if a vendored asset file referenced by `folium`'s current `default_js`/`default_css` is missing. |

### Integration Tests
| Test | Description |
|---|---|
| `test_map_top_level_renders_iframe` | A top-level `Map` component in an envelope → `_render_top` dispatches to `_render_map`, output contains `<iframe sandbox="allow-scripts allow-popups"`. |
| `test_map_nested_in_infographic_renders_iframe` | Regression test for the exact `flex_dashboard.py` Proximity Staffing bug: a `Map` nested inside an `Infographic` section descriptor → `_render_descriptor` dispatches to `_render_map`, NOT the old `.lower()` text degradation. |
| `test_map_iframe_srcdoc_has_zero_external_resources` | Decode the `<iframe srcdoc="...">` attribute value (undo the HTML-escaping) and assert zero `<script src="http` / `<link ... href="http` substrings inside it — closes the escaping loophole in the existing `test_document_shell.py:44-46` guardrail, which only inspects the outer (unescaped) document. |
| `test_all_a2ui_classes_have_css_rule` | Coverage-audit test: scan `interactive_html.py`'s emitted class vocabulary (same AST scan Module 4's script uses), assert every class appears as a selector somewhere in `DesignSystem.stylesheet()`'s output. |
| `test_folium_map_surface_zero_external_resources` | Same offline check as above, applied to the standalone `folium_map` renderer surface directly (closes the pre-existing, currently-untested gap noted in §1). |

### Test Data / Fixtures
```python
# Reuse existing fixture shape from test_folium_map.py's TestFoliumMapRenderer
# (multi-layer envelope with baked `data` per layer). Add one fixture with
# >500 synthetic points in a single layer for the clustering tests.
```

---

## 5. Acceptance Criteria

- [ ] A top-level `Map` component renders as a real `<iframe>`-embedded Leaflet map
  in `interactive-html` output (not a text layer-summary).
- [ ] A `Map` nested inside an `Infographic` section (the `flex_dashboard.py`
  Proximity Staffing case) renders the same way via `_render_descriptor`.
- [ ] A layer's markers above the cluster threshold (default 500, per-layer
  overridable) render wrapped in `folium.plugins.MarkerCluster`.
- [ ] The embedded Map `iframe`'s decoded `srcdoc` content contains **zero**
  external `<script src=`/`<link href=` URLs — verified by a test that decodes
  the escaped attribute, not just inspects the outer document.
- [ ] The same offline-vendoring fix is verified on the standalone `folium_map`
  renderer surface too (`test_folium_map_surface_zero_external_resources`).
- [ ] The `iframe` carries `sandbox="allow-scripts allow-popups"`.
- [ ] Every CSS class `interactive_html.py` can emit has a real rule in
  `DesignSystem.stylesheet()`'s output (coverage-audit test passes).
- [ ] `scripts/generate_a2ui_css.py --check` exits 0 on a clean checkout and exits
  1 when the committed generated CSS (or the vendored asset set) is stale relative
  to source.
- [ ] `.github/workflows/ci.yml`'s `lint-and-registry` job runs the check above and
  fails the build on drift (resolved decision, §8 — no warn-and-merge fallback).
- [ ] All existing tests continue passing unmodified: `test_document_shell.py`,
  `test_interactive_html.py`, `test_semantic_classes.py`, `test_folium_map.py`,
  `test_folium_layers.py` (markup class names and `FoliumMapRenderer.render()`'s
  public signature are unchanged).
- [ ] `pytest packages/ai-parrot-visualizations/tests/ -v` passes.
- [ ] No new install-time (`pip install`) dependency added to
  `ai-parrot-visualizations`'s wheel — Tailwind CLI runs only in CI/dev; vendored
  map assets ship as static `package-data`, same mechanism as `chart.umd.min.js`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every reference below was read
> directly from the source at spec time (2026-09-03) and, where noted, verified
> by executing it against the installed `folium==0.20.0`. Line numbers may drift
> a few lines by implementation time — re-verify with `grep`/`Read` before use,
> but the *shape* (signatures, whether something is sync/async, whether a
> resource is CDN-loaded by default) is a spec-time-verified fact, not an
> assumption carried from the brainstorm.

### Verified Imports
```python
# All confirmed to resolve — packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py:22-35
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog.base import BasicNode
from parrot.outputs.a2ui.models import CreateSurface
from parrot.outputs.a2ui.renderers import AbstractA2UIRenderer, RendererCapabilities, register_a2ui_renderer
import folium.plugins  # MarkerCluster — ships with folium>=0.14, no new pyproject dependency

# interactive_html.py:76-90 (already imports get_component, to_components, Component,
# ComponentMetadata, CreateSurface, DesignSystem — all already used by the existing
# Chart/DataTable interception, no new imports needed there beyond calling into
# folium_map's new build_map_document)
from parrot.outputs.formats.assets.design_system import DesignSystem
```

### Existing Class Signatures
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py
@register_a2ui_renderer(
    "folium-map",
    RendererCapabilities(interactive=False, supports_actions=False, supports_updates=False,
                          output="text/html", supported_components={"Map"}),
)
class FoliumMapRenderer(AbstractA2UIRenderer):
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact:
        # line 76. VERIFIED: contains ZERO `await` statements in its body —
        # declared async only for interface conformance (see §2 rationale).
        # Currently inlines everything that build_map_document() must extract:
        #   - folium.Map(location=..., zoom_start=...)          line 126
        #   - per-layer folium.FeatureGroup + marker loop         lines 135-153
        #   - legacy single-layer folium.Marker loop               lines 157-165
        #   - fmap.get_root().render() -> str                      line 167
        ...

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py
_INTERCEPTED = {"Chart", "DataTable", "Infographic"}  # line 110 — Map extension point

class InteractiveHTMLRenderer(AbstractA2UIRenderer):
    supported_components = {  # inside RendererCapabilities(...), line ~537-559
        "AudioPlayer", "Button", "Card", "CheckBox", "ChoicePicker", "Column",
        "DateTimeInput", "Divider", "Icon", "Image", "List", "Modal", "Row",
        "Slider", "Tabs", "Text", "TextField", "Video", "Chart", "DataTable",
        "Infographic",  # "Map" currently ABSENT — confirmed by direct read
    }

    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact:
        # line 580 — the ONLY async entry point in this class's render chain.
        ...
        body_parts = [
            self._render_top(bc, by_id, degradations) for bc in baked_components
            if bc["id"] not in referenced
        ]  # line 609 — SYNCHRONOUS list comprehension, no await. This is why
           # _render_map() must call a SYNC builder, not `await FoliumMapRenderer().render()`.

    def _lower_composites(self, envelope: CreateSurface) -> CreateSurface:
        # line 641. THE ACTUAL gate `_INTERCEPTED` controls — runs BEFORE baking,
        # for every component NOT in `_INTERCEPTED`: calls
        # `entry.component_cls().lower(comp, envelope.data_model)` (line 656),
        # which for "Map" is exactly `MapComponent.lower()` — the text-degradation
        # path this feature must bypass for "Map" the same way it's already
        # bypassed for "Chart"/"DataTable"/"Infographic".
        ...

    def _render_top(self, comp: dict[str, Any], by_id, degradations) -> str:
        # line 679. name = comp["component"]; if "Chart": ...; if "DataTable": ...;
        # if "Infographic": ...; else falls through to _reconstruct + _render_basic.
        # Map branch goes here, mirroring the Chart/DataTable branches exactly.
        ...

    def _render_descriptor(self, descriptor: dict[str, Any]) -> str:
        # line 692. name = descriptor.get("component"); properties = descriptor.get("properties") or {}.
        # Special-cases ONLY "Chart"/"DataTable" today (lines 696-699) — anything
        # else, Map included, falls to `entry.component_cls().lower(component, {})`
        # (the degradation path) at line ~707. THIS is the exact call site that
        # produced the "stores | label=..." text the user observed (Map nested
        # inside an Infographic section, e.g. flex_dashboard.py's Proximity
        # Staffing). Map branch goes here too — both sites must be covered.
        ...

    def _render_chart(self, props: dict[str, Any]) -> str:
        # line 961. Sync method, takes the baked component's own top-level dict
        # (v1.0 — never nested under a "properties" key). _render_map() mirrors
        # this exact shape: def _render_map(self, props: dict[str, Any]) -> str.
        ...

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py
_ASSETS_DIR = Path(__file__).parent  # line 32
def _read_asset(name: str) -> str | None: ...  # line 35 — returns None + logs warning if missing, never raises
_BASE_CSS: str = _read_asset("base.css") or ""            # line 57
_COMPONENTS_CSS: str = _read_asset("components.css") or "" # line 58
# _TAILWIND_CSS follows the identical pattern, added at this same location.

class DesignSystem:
    @classmethod
    def stylesheet(cls, theme=None, layout=None) -> str:  # line 88
        # sheet = "\n\n".join(part for part in (
        #     theme_config.to_css_variables(), _BASE_CSS, _COMPONENTS_CSS, layout_css or "",
        # ) if part)                                        # lines 108-114
        # _TAILWIND_CSS inserted between _COMPONENTS_CSS and layout_css.
        ...

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py:140-148
_CHART_JS_PATH = Path(__file__).parent.parent / "formats" / "assets" / "chart.umd.min.js"
_CHART_JS_SOURCE = _CHART_JS_PATH.read_text(encoding="utf-8")  # read ONCE at import time —
# this exact pattern (Path(__file__)-relative, .read_text() once, module-level constant)
# is what the new vendored map JS/CSS assets follow, base64-encoded into data: URIs.

# scripts/generate_tool_registry.py (pattern to mirror for scripts/generate_a2ui_css.py)
# CLI: --check (CI mode: exit 1 if stale), --dry-run, --verbose  (lines 8-13)
# Uses `ast` module to scan Python source for literal constants (import ast, line 20).
```

### Verified Live Behavior (executed against the installed environment, 2026-09-03)
```python
# folium==0.20.0, executed via `source .venv/bin/activate && python -c "..."`
import folium, folium.plugins as fp
m = folium.Map(location=[0, 0], zoom_start=2)
m.default_js   # [('leaflet', 'https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js'),
                #  ('jquery', 'https://code.jquery.com/jquery-3.7.1.min.js'),
                #  ('bootstrap', 'https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/js/bootstrap.bundle.min.js'),
                #  ('awesome_markers', 'https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.js')]
m.default_css  # [('leaflet_css', '.../leaflet@1.9.3/dist/leaflet.css'),
                #  ('bootstrap_css', '.../bootstrap@5.2.2/dist/css/bootstrap.min.css'),
                #  ('glyphicons_css', 'https://netdna.bootstrapcdn.com/bootstrap/3.0.0/css/bootstrap-glyphicons.css'),
                #  ('awesome_markers_font_css', '.../fontawesome-free@6.2.0/css/all.min.css'),
                #  ('awesome_markers_css', '.../Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.css'),
                #  ('awesome_rotate_css', '.../folium/folium/templates/leaflet.awesome.rotate.min.css')]
fp.MarkerCluster().default_js   # [('markerclusterjs', '.../leaflet.markercluster/1.1.0/leaflet.markercluster.js')]
fp.MarkerCluster().default_css  # [('markerclustercss', '.../leaflet.markercluster/1.1.0/MarkerCluster.css'),
                                 #  ('markerclusterdefaultcss', '.../leaflet.markercluster/1.1.0/MarkerCluster.Default.css')]
# 11 (name, url) pairs baseline + 3 more when clustering triggers = 14 total possible;
# Module 2 vendors all of them (13 distinct files — leaflet_css and leaflet js share
# no file, all pairs are 1:1 with a distinct URL/file).
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `InteractiveHTMLRenderer._render_map` | `folium_map.build_map_document` | direct sync call | `folium_map.py` (new function), `interactive_html.py:679,692` (new branches) |
| `folium_map.build_map_document` | `folium.Map`, `folium.plugins.MarkerCluster` | existing library calls (extracted, unchanged logic) | `folium_map.py:126-167` (current inline location, pre-extraction) |
| `DesignSystem.stylesheet` | `design_system/tailwind.generated.css` | `_read_asset()` | `design_system/__init__.py:35,57-58` |
| `scripts/generate_a2ui_css.py --check` | `.github/workflows/ci.yml` `lint-and-registry` job | new CI step | `ci.yml:29-30` (insertion point, after "Check registry freshness") |

### Does NOT Exist (Anti-Hallucination)
- ~~`folium.Map(offline=True)` or any built-in "vendor everything locally" mode~~ —
  does not exist in `folium==0.20.0`. `JSCSSMixin.add_js_link()`/`add_css_link()`
  is the only supported override mechanism, and this spec deliberately does NOT
  use it (§2 rationale) — do not reach for it.
- ~~`await FoliumMapRenderer().render(envelope)` called from `_render_top`/
  `_render_descriptor`~~ — would require threading `await` through a currently
  fully-synchronous call chain (interactive_html.py:609's list comprehension has
  no `await`). Use `build_map_document()` (sync) instead.
- ~~Marker clustering in `folium_map.py`~~ — not present today (confirmed by
  reading the current file in full); every feature becomes an individual
  `folium.Marker`/`CircleMarker` today. Must be added in Module 1.
- ~~A Node/Tailwind toolchain wired into `ai-parrot-visualizations`~~ — does not
  exist. `pyproject.toml` uses plain `setuptools.build_meta`, no build hooks.
- ~~Multi-renderer composition in `RecipeRunner`~~ — `_render_or_raise` resolves
  and invokes exactly one renderer per run (confirmed, runner.py:649-667).
- ~~An unconditional `.lower()` call before every renderer sees a component~~ —
  false; `_INTERCEPTED` already exists (interactive_html.py:110) and already
  gates `_lower_composites` (line 641) for Chart/DataTable/Infographic.
- ~~An existing offline/self-contained guardrail test on the `folium_map`
  surface~~ — `test_folium_map.py` has no such test today (confirmed by reading
  the file); Module 7 adds one.
- ~~A `cluster_threshold`/similar field already on `MapLayer` or `StructuredMapConfig`~~
  (`parrot/models/outputs.py:640-768`) — confirmed absent; this feature
  deliberately does NOT add one to the wire schema (Non-Goals).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- "Read once at import time, never per-render" for all static assets — the
  established pattern (`_CHART_JS_SOURCE`, `_BASE_CSS`, `_COMPONENTS_CSS`) that
  the new vendored JS/CSS `data:` URIs and `_TAILWIND_CSS` must follow.
- `formats/assets/` flat placement for vendored binary-ish assets (mirrors
  `chart.umd.min.js`/`echarts.min.js`); `design_system/*.css` for generated
  stylesheet fragments.
- Mirror `_render_chart`'s exact method shape for `_render_map` (sync, takes a
  plain `props: dict[str, Any]`, returns an HTML fragment string) — do not
  introduce a different calling convention.
- Mirror `generate_tool_registry.py`'s `--check`/`--dry-run`/AST-scan CLI shape
  for `generate_a2ui_css.py` — this is an established, working repo convention,
  not a new one to invent.
- Async-first per `CLAUDE.md`, but do not force async where the existing code
  (verified §6) is synchronous throughout — `build_map_document()` stays sync by
  design (§2 rationale), matching the actual call chain it's invoked from.

### Known Risks / Gotchas
- **Marker count above the clustering threshold**: wrapped in `MarkerCluster`
  automatically; default 500, per-layer overridable via
  `cluster_threshold_by_layer` (renderer-internal only, never LLM-settable).
- **Empty/zero-layer Map data**: renders an empty-state map card rather than
  raising — mirrors Chart/DataTable's existing empty-data degradation.
- **Both `_render_top` and `_render_descriptor` must be patched**: a fix in only
  one silently leaves the other producing the old text degradation — this is
  exactly how `flex_dashboard.py`'s Proximity Staffing case (nested inside an
  Infographic section) was missed originally.
- **Real PII in embedded map data**: production dashboards (store/employee
  geolocation) end up inlined inside the `iframe srcdoc` — no worse than today's
  text degradation, which already inlines the same coordinates. Mitigated by
  `sandbox="allow-scripts allow-popups"` (resolved in brainstorm).
- **`folium` version drift**: if a future `folium` upgrade changes its
  `default_js`/`default_css` name/URL set (new plugin, renamed resource,
  version bump), the vendored asset set silently falls out of sync UNLESS
  Module 6's CI check (which introspects the *installed* `folium` package live,
  not a hardcoded list) catches it — this is why the check must read
  `folium.Map().default_js`/`default_css` live, not from a frozen constant.
- **`folium.plugins.MarkerCluster` shares the same `JSCSSMixin` shared-class-state
  hazard as `folium.Map`** (§2) — `build_map_document()`'s data-URI swap must
  operate on the rendered HTML string, never call `add_js_link`/`add_css_link` on
  either object.
- **Per-map Leaflet+jQuery+Bootstrap duplication**: each Map component's `iframe
  srcdoc` embeds a full copy of the vendored bundle (now larger than the
  brainstorm estimated, since it includes the base64-inlined assets, not just
  folium's own markup) — acceptable for the realistic 0-2-maps-per-dashboard
  case; a dashboard with many maps pays a real, bounded per-map byte cost.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `folium` | `>=0.14` (already declared, `map` extra) | Map rendering — no version change |
| `folium.plugins.MarkerCluster` | ships with `folium` | Marker clustering — no new dependency |
| Tailwind CLI (standalone binary) | v4 | Compiles/purges utility CSS at CI/dev time only — never a runtime or install-time dependency |
| Vendored: Leaflet 1.9.3, jQuery 3.7.1, Bootstrap 5.2.2, Bootstrap Glyphicons 3.0.0, Font Awesome Free 6.2.0, Leaflet.awesome-markers 2.0.2, Leaflet.markercluster 1.1.0 | pinned, matching folium 0.20.0's own defaults (§6) | Static package-data assets, not pip dependencies — same mechanism as `chart.umd.min.js` |

---

## 8. Open Questions

- [x] What `iframe sandbox` attribute policy should the embedded folium map use,
  given production Map data can contain real employee/store PII? — *Resolved in
  brainstorm*: `sandbox="allow-scripts allow-popups"`.
- [x] What marker-count threshold triggers `MarkerCluster` wrapping? — *Resolved
  in brainstorm*: default 500, configurable per-layer (implemented as a
  renderer-internal parameter, §2 Non-Goals — not a wire-schema field).
- [x] Tailwind v3 vs v4? — *Resolved in this spec*: v4 (CSS-first config, no
  `tailwind.config.js`/PostCSS required for `@apply`).
- [x] How should the CI staleness check behave — fail vs warn? — *Resolved in
  brainstorm*: fail the build outright.
- [x] Should the safelist-generation script be a Python AST utility or a manual
  list? — *Resolved in this spec*: Python AST utility, mirroring the existing
  `scripts/generate_tool_registry.py` pattern exactly (§6, confirmed this is an
  established, working repo convention).
- [ ] Exact set of vendored-asset licenses to record where (a `THIRD_PARTY_NOTICES`
  file vs. inline comments in each vendored file vs. a manifest JSON next to
  `formats/assets/`) — *Owner: implementer*, low-risk (all permissive licenses,
  §7), pick the lightest convention that satisfies a license audit; not
  design-blocking.

---

## Worktree Strategy

- **Isolation unit**: `mixed`. Two largely disjoint tracks:
  - **Map track** (Modules 1-3, 7's Map-related tests): touches
    `folium_map.py`, `interactive_html.py`, `formats/assets/` (new vendored
    files).
  - **Tailwind/CSS track** (Modules 4-6, 7's CSS-coverage tests): touches
    `scripts/generate_a2ui_css.py` (new), `design_system/__init__.py`,
    `.github/workflows/ci.yml`.
  - Only shared touchpoint: `design_system/__init__.py`'s `stylesheet()`
    concatenation — a one-line addition, negligible merge risk.
- **Cross-feature dependencies**: none identified. No other in-flight spec
  touches `interactive_html.py`, `folium_map.py`, `design_system/`, or
  `ci.yml`'s `lint-and-registry` job as of 2026-09-03.
- **Rationale**: matches the brainstorm's Parallelism Assessment (confirmed
  still accurate at spec time) — the two tracks can run as separate tasks
  within one worktree (sequential) or, if the executing agent pool supports
  intra-feature parallel tasks, as two concurrent tasks converging on the
  single-line `DesignSystem.stylesheet()` integration.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-03 | Jesus Lara | Initial draft, from `sdd/proposals/interactive-html-map-tailwind.brainstorm.md`; spec-time research corrected the offline-vendoring scope (folium's own CDN defaults) and the sync/async call-chain mismatch that the brainstorm's "reuse FoliumMapRenderer.render() as-is" plan did not account for. |
