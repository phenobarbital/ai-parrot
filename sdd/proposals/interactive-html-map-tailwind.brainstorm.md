---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Interactive-HTML Map Rendering + Tailwind CSS Coverage (FEAT-493 follow-up)

**Date**: 2026-09-03
**Author**: Jesus Lara (jesuslarag@gmail.com)
**Status**: exploration — user-owned open questions resolved 2026-09-03 (2 implementer-owned items deferred to `/sdd-spec`)
**Recommended Option**: A

---

## Problem Statement

FEAT-493 (`html-renderer-design-system`, PR #1296, merged 2026-09-02) shipped a real
design-system CSS pipeline for the `interactive-html` A2UI renderer
(`packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`)
but left two gaps that surfaced immediately on the first real dashboard exercised end-to-end
against production data (`agents/flex_dashboard.py`, six real Flex QuerySource datasets):

1. **No real Map rendering.** `InteractiveHTMLRenderer.supported_components`
   (interactive_html.py:537-559) does not include `"Map"`. The A2UI catalog's
   `MapComponent.lower()` (`packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/map.py:78-114`)
   unconditionally degrades any `Map` node into a static `Card → Column → Text` layer-summary
   before `interactive_html.py` ever sees it — by design, for renderers that don't declare
   Map support. A dashboard's "Proximity Staffing" map (store/employee geolocation) therefore
   renders as plain text (`"stores | label=store_name | color=#1f77b4"`) instead of an actual
   map, even though a real interactive Leaflet map renderer already exists as a *separate*
   renderer surface: `folium_map.py` (`supported_components={"Map"}`).

2. **Base primitive CSS classes have zero styling.** The FEAT-493 design-system CSS
   (`DesignSystem.stylesheet()`,
   `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py:107-119`)
   covers composite classes (`.kpi-card`, `.ds-title`, `.filter-*`, `.msf-*`, …) but has **zero**
   rules for the base primitives `interactive_html.py` emits constantly:
   `.a2ui-text`, `.a2ui-label`, `.a2ui-value`, `.a2ui-col`, `.a2ui-title`, `.a2ui-heading`,
   `.a2ui-section`, `.a2ui-chart-wrap`, `.a2ui-table-wrap` (e.g. interactive_html.py:776, 878,
   1101). This is systemic — the two class vocabularies (`a2ui-*` primitives vs. `ds-*`/`kpi-*`
   composites) barely overlap — so most of any dashboard renders with browser-default,
   unstyled appearance despite a real `<style>` block being present and correctly wired.

Both gaps were invisible in FEAT-493's own test suite (which asserts specific composite
classes exist, never that *every* emitted class has a rule) and only became visible once a
real, data-heavy, mixed-component dashboard was rendered end-to-end. This feature closes both
gaps as one combined follow-up to FEAT-493.

## Constraints & Requirements

- **Must stay fully self-contained/offline.** `test_document_shell.py:44-46` already asserts
  `"<script src="` / `"<link "` / `"@import"` are absent from the rendered document — this is
  a passing guardrail test today and must keep passing. Any Map or CSS approach that depends
  on a runtime CDN fetch (e.g. `<script src="https://cdn.tailwindcss.com">`) fails this test
  outright and is disqualified.
- **One renderer per render pass.** `RecipeRunner._render_or_raise`
  (`packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py:652-667`) resolves and
  invokes exactly one renderer class per run — there is no multi-renderer composition at the
  `RecipeRunner` level. Map support must be implemented entirely inside
  `InteractiveHTMLRenderer`, not by having `RecipeRunner` invoke both `interactive-html` and
  `folium_map` and stitch results.
- **Preserve existing class names in markup.** `test_document_shell.py:39` and
  `test_interactive_html.py:248` assert specific class strings appear in the rendered output
  (`.kpi-card`, `a2ui-divider-h`). Any CSS rework must keep the current semantic class names
  in the emitted markup — style them via `@apply`/rule authorship, don't rename them.
- **No new install-time dependency for the shipped wheel.** `ai-parrot-visualizations`'
  `pyproject.toml` uses plain `setuptools.build_meta` with CSS shipped as a static
  `package-data` asset (`design_system/*.css`). A Tailwind build step must run at CI/dev
  time and commit its output, not run inside `pip install` for downstream consumers.
- **`.lower()` opt-out is already a proven mechanism** — `_INTERCEPTED = {"Chart", "DataTable",
  "Infographic"}` (interactive_html.py:110) already lets specific component types skip
  catalog-level `.lower()` degradation. Map support is an extension of this exact mechanism,
  not a new pipeline capability.
- Both call sites that can encounter a `Map` node must be covered: `_render_top` (line 679,
  top-level components) **and** `_render_descriptor` (line 692, components nested inside an
  `Infographic` section — this is the actual path `agents/flex_dashboard.py`'s Proximity
  Staffing section takes, and the one that produced the text degradation the user observed).
- Real production dashboards can embed real PII (employee/store geolocation) in the Map's
  data — any inlining approach must not make that data easier to exfiltrate than it already is
  in the current text-degradation form. **Resolved 2026-09-03**: the embedding `<iframe>` uses
  `sandbox="allow-scripts allow-popups"` — script execution stays allowed (required for
  Leaflet to draw the map) and popups are allowed (so a marker tooltip/link can open in a new
  tab), while top-navigation, forms, and same-origin access remain blocked.

---

## Options Explored

### Option A: Iframe-isolated folium composition + CI-compiled, repo-committed Tailwind CSS

Extend `InteractiveHTMLRenderer` to treat `"Map"` as a fourth intercepted, natively-rendered
component type (alongside Chart/DataTable/Infographic). When a Map node is encountered (in
either `_render_top` or `_render_descriptor`), build a synthetic single-Map `CreateSurface`
envelope from the node's already-baked properties (`layers`, `labelField`, `markerColor`,
`data`, …) and delegate to the existing `FoliumMapRenderer.render()` — wrapping each layer's
markers in `folium.plugins.MarkerCluster` when a layer's point count crosses a threshold. The
resulting standalone folium HTML document (bytes) is escaped and embedded as
`<iframe srcdoc="...">`, giving hard CSS/JS isolation between folium's Leaflet assets and the
rest of the document — no shared global namespace, no collision risk.

For CSS: add a CI job (mirroring the Node/pnpm pattern `.github/workflows/release.yml:280-295`
already runs for `ai-parrot-server/ui`) that runs the Tailwind CLI against a safelist derived
from `interactive_html.py`'s finite, literal class vocabulary (confirmed closed-set: every
class is a literal or f-string built from Python constants, never user-controlled — greppable
directly from the renderer source), `@apply`s the resulting utilities onto the *existing*
semantic selectors (`.a2ui-text`, `.a2ui-col`, etc.) so markup and existing substring tests are
untouched, and commits the generated, purged CSS file into `design_system/` alongside
`base.css`/`components.css` — following the package's existing "CSS as a static, committed
asset" precedent rather than compiling at `pip install` time.

✅ **Pros:**
- Reuses `_INTERCEPTED` — an already-proven, already-tested extension point (zero new pipeline
  mechanism).
- `iframe srcdoc` gives hard isolation: folium's own CSS/JS can never collide with
  `interactive_html`'s design-system CSS or `filter-bar`/`multiselect` JS.
- Passes the offline/self-contained guardrail test as-is (`srcdoc` is inline, no network fetch).
- Zero new install-time dependency; CSS ships as a committed static file exactly like today.
- Existing substring-based tests (`test_document_shell.py`, `test_interactive_html.py`) keep
  passing unchanged because class names in the markup don't change.

❌ **Cons:**
- Each Map component duplicates a full copy of folium's inlined Leaflet JS/CSS in its
  `srcdoc` — N maps in one document means N copies (acceptable for the common 0-2 maps/
  dashboard case, worth flagging for a dashboard with many maps).
- The committed Tailwind CSS file can silently drift from the class vocabulary if a developer
  adds a new `a2ui-*` class in Python without re-running the Tailwind build — needs a CI
  staleness check (see Open Questions), not automatic.

📊 **Effort:** Medium — Map track ≈ TASK-2709/2710-sized (2-3 tasks); Tailwind track ≈
similarly sized (safelist script, CI job, `@apply` authorship, coverage audit test).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `folium>=0.14` | Already-declared extra (`map`) in `ai-parrot-visualizations`; renders the actual Leaflet map | No version change needed |
| `folium.plugins.MarkerCluster` | Marker clustering for high-point-count layers | Ships with `folium`, not a new dependency |
| Tailwind CLI (standalone binary or `npx tailwindcss`) | Compiles/purges utility CSS at CI/dev time | No permanent `npm`/`pnpm` runtime dep needed — the CLI has a standalone-binary distribution; only needed transiently in CI, mirrors existing `ai-parrot-server/ui` Node/pnpm CI step |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py` —
  `FoliumMapRenderer.render(envelope, *, bake=True) -> RenderedArtifact` (line 76), used
  as-is via a synthetic envelope; only change needed here is wrapping markers in
  `MarkerCluster`.
- `interactive_html.py:110` (`_INTERCEPTED`), `:679` (`_render_top` dispatch), `:692`
  (`_render_descriptor` dispatch) — the exact three sites to extend.
- `.github/workflows/release.yml:280-295` — the Node/pnpm CI pattern to mirror for the
  Tailwind build step.
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py:107-119`
  (`DesignSystem.stylesheet()`) — where the new generated CSS file gets concatenated in,
  same mechanism as `base.css`/`components.css`/`layout-*.css` today.

---

### Option B: Native Leaflet integration in `interactive_html.py` + hand-authored CSS (no folium, no Tailwind)

Implement Map rendering natively inside `interactive_html.py` (a new `_render_prim_Map`),
independent of `folium_map.py`: vendor Leaflet's JS/CSS as static package assets (same
pattern as the existing design-system CSS files), emit a `<div>` + inline `<script>` calling
`L.map()`/`L.markerClusterGroup()` directly against the Map node's baked properties. For CSS,
skip Tailwind entirely — hand-author the missing `.a2ui-text`/`.a2ui-col`/etc. rules directly
in `components.css`/`base.css`, following the exact style already used for the composite
classes.

✅ **Pros:**
- No new toolchain at all — neither a `folium` composition step nor a Node/Tailwind CI job.
- Smaller total bundle when a document has one Leaflet load shared across every map (if built
  without per-map iframe isolation).
- CSS fix is trivially low-risk, low-effort, and matches the existing hand-authored convention
  exactly — no new build artifact to keep in sync.

❌ **Cons:**
- Duplicates marker-building/tooltip/geodesic logic that `folium_map.py` already implements
  and tests (`test_folium_map.py`, `test_folium_layers.py`) — two independent
  implementations of "draw markers from Map properties" to keep behaviorally consistent going
  forward.
- Hand-authored CSS closes today's gap but doesn't prevent it recurring: nothing forces future
  primitives to get a rule (this is exactly how the FEAT-493 gap happened in the first place).
- Needs Leaflet.js/css vendored and license-reviewed as static assets (BSD-2, small, but a new
  asset-maintenance surface).

📊 **Effort:** Medium-High for Map (re-implements what `folium_map.py` already provides);
Low for CSS.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Leaflet.js / leaflet.css (vendored) | Native map rendering, no folium dependency | ~40KB JS + ~15KB CSS gzipped; needs to be checked into the repo as a static asset |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/components.css`
  — pattern to follow for hand-authoring the missing primitive rules.
- `folium_map.py`'s marker/tooltip-building logic as a *reference* for feature parity, even
  though it would not be called directly under this option.

---

### Option C (unconventional): Inline (non-iframe) folium fragment sharing one Leaflet load + hand-rolled "utility-lite" CSS shim (no Node/Tailwind toolchain)

Instead of a full standalone folium document per `iframe`, extract just folium's generated
map `<div>` + initialization `<script>` fragment (folium's internal `Figure` render supports
fragment-level access) and inline it directly into the document body, loading Leaflet's JS/CSS
**once per document** and sharing it across every Map component — cheaper in bytes than
Option A's per-map `iframe` duplication. Namespace/scope isolation (`.folium-map-container`
wrapper, verifying folium's `uuid4`-based element ids don't collide across maps in one
document) replaces `iframe`'s hard boundary. For CSS, skip a Tailwind build pipeline entirely;
instead hand-author a small, static, Tailwind-*flavored* utility layer (~30-40 atomic classes:
`.u-flex`, `.u-gap-2`, `.u-text-sm`, …) as a plain committed CSS file — closing the same
systemic base-primitive gap without introducing any Node/npm tooling into the discussion.

✅ **Pros:**
- Smallest file-size footprint of all three options (one shared Leaflet load, no per-map or
  per-build duplication).
- Zero new build-time tooling — most consistent with the package's current
  CSS-as-static-asset precedent.
- Fastest to ship.

❌ **Cons:**
- Does not satisfy the user's explicit requirement for real Tailwind (a hand-rolled,
  Tailwind-flavored substitute is not Tailwind, and would need re-doing later if genuine
  Tailwind is wanted).
- Inline fragment composition is more fragile than `iframe` isolation — exactly the
  CSS/JS-collision risk the user already weighed and explicitly rejected in favor of
  isolation when deciding on this feature's scope.

📊 **Effort:** Low-Medium.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `folium>=0.14` | Same as Option A, but only its fragment output is used | Requires verifying folium's `Figure` exposes a fragment-only render path |

🔗 **Existing Code to Reuse:**
- Same `folium_map.py` reuse as Option A, plus `components.css` as the base for the
  hand-rolled utility layer.

---

## Recommendation

**Option A** is recommended because it is the only option that satisfies every constraint the
user explicitly locked in during discovery — `iframe`-isolated Map composition (safety over
file size) and *real*, build-time-compiled, purged Tailwind CSS (not a hand-rolled
substitute) — while reusing two already-proven codebase mechanisms end-to-end:
`_INTERCEPTED`'s catalog-lowering opt-out (already exercised by Chart/DataTable/Infographic)
and `release.yml`'s existing Node/pnpm CI pattern (already exercised for `ai-parrot-server/ui`).
Nothing in Option A requires touching `RecipeRunner`, the A2UI catalog's lowering pipeline, or
the wheel's install-time dependency graph.

The trade-off being accepted is per-map Leaflet duplication inside each `iframe srcdoc` (a
real but bounded cost for the realistic 0-2-maps-per-dashboard case) in exchange for
eliminating CSS/JS namespace-collision risk entirely — Option C's inline-fragment approach
would save bytes but reintroduces exactly the fragility the isolation requirement was meant to
avoid. Option B's from-scratch Leaflet reimplementation is rejected mainly because it
duplicates logic `folium_map.py` already implements and tests, for no isolation or tooling
benefit over Option A.

---

## Feature Description

### User-Facing Behavior

A dashboard containing a `Map` component (e.g. `agents/flex_dashboard.py`'s Proximity
Staffing section) renders an actual interactive Leaflet map — pan, zoom, markers grouped into
clusters at high density, per-layer marker colors/tooltips as declared — inline in the same
single, standalone HTML file, instead of a static text layer-summary. Every other component
on the same page (KPI cards, charts, tables, section headings, columns) renders with complete,
consistent visual styling — no more unstyled `a2ui-text`/`a2ui-col`/etc. elements with
browser-default appearance.

### Internal Behavior

**Map track:** `InteractiveHTMLRenderer._INTERCEPTED` gains `"Map"`. Both `_render_top` and
`_render_descriptor` gain a `name == "Map"` branch that reads the node's already-baked
properties (`layers`, `viewport`, `title`), constructs a synthetic single-Map `CreateSurface`
envelope, and calls `FoliumMapRenderer().render(envelope)` (now internally wrapping each
layer's markers in `folium.plugins.MarkerCluster` once a layer's point count passes a
threshold — default **500**, overridable per-layer). The returned standalone HTML document's
bytes are HTML-escaped and written into an
`<iframe sandbox="allow-scripts allow-popups" srcdoc="...">` in place of the old
`.lower()`-produced text card.

**CSS track:** a new CI job installs Node + the Tailwind CLI (mirroring
`release.yml`'s existing `ai-parrot-server/ui` step), runs it against a safelist generated
from `interactive_html.py`'s literal class vocabulary, and `@apply`s the resulting utilities
onto the *existing* semantic selectors that currently have no rule
(`.a2ui-text`, `.a2ui-col`, `.a2ui-label`, `.a2ui-value`, `.a2ui-title`, `.a2ui-heading`,
`.a2ui-section`, `.a2ui-chart-wrap`, `.a2ui-table-wrap`). The generated, purged CSS file is
committed into `design_system/` and concatenated into `DesignSystem.stylesheet()` exactly like
`base.css`/`components.css`/`layout-*.css` are today — no runtime or install-time build step.

### Edge Cases & Error Handling

- **Marker count above the clustering threshold**: wrapped in `MarkerCluster` automatically;
  below threshold, rendered as individual markers (current `folium_map.py` behavior,
  unchanged). **Resolved 2026-09-03**: default threshold is **500** points per layer,
  overridable per-layer via the layer's properties.
- **Empty/zero-layer Map data**: renders an empty-state map card rather than raising —
  mirrors how Chart/DataTable already degrade gracefully on empty data today.
- **Map nested in an `Infographic` section vs. top-level**: both `_render_top` and
  `_render_descriptor` call sites must be covered — a fix in only one silently leaves the
  other producing the old text degradation (this is exactly how the flex_dashboard's
  Proximity Staffing case, which is *nested* inside an Infographic section, was missed if
  only the top-level path is patched).
- **Tailwind CSS/class-vocabulary drift**: **Resolved 2026-09-03** — the CI check **fails the
  build** if the committed generated CSS file is stale relative to the current class vocabulary
  scraped from `interactive_html.py` (no warn-and-allow-merge fallback); prevents the gap from
  silently reopening as new primitives are added later.
- **Real PII in embedded map data**: production dashboards (e.g. flex_dashboard's real store/
  employee geolocation) end up inlined inside the `iframe srcdoc` — no worse than today's text
  degradation, which already inlines the same coordinates. **Resolved 2026-09-03**: the
  `iframe` uses `sandbox="allow-scripts allow-popups"` (see Constraints above).

---

## Capabilities

### New Capabilities
- `interactive-html-map-render`: Map components render as real, isolated, clustered
  interactive Leaflet maps (via composed `folium_map` output) inside `interactive-html`
  documents, at both the top-level and Infographic-nested call sites.
- `interactive-html-tailwind-css`: a CI-compiled, purged, repo-committed Tailwind CSS layer
  gives complete style coverage to every class `interactive_html.py` emits, applied via
  `@apply` onto the existing semantic class names.

### Modified Capabilities
- `html-renderer-design-system` (FEAT-493, `sdd/specs/html-renderer-design-system.spec.md`) —
  its CSS concatenation (`DesignSystem.stylesheet()`) gains one more source file; its renderer
  (`interactive_html.py`) gains Map as a fourth intercepted component type.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `interactive_html.py` (`_INTERCEPTED`, `_render_top`, `_render_descriptor`, `supported_components`) | extends | Adds Map as a 4th natively-rendered component type; no existing dispatch logic removed. |
| `folium_map.py` | extends | Adds `MarkerCluster` wrapping above a configurable point-count threshold; `FoliumMapRenderer.render()` signature unchanged, reused as-is for the composition. |
| `design_system/__init__.py` (`DesignSystem.stylesheet()`) + `design_system/*.css` | modifies | Adds one new generated, committed CSS file to the existing concatenation. |
| `.github/workflows/*.yml` | new CI step | New Node/pnpm + Tailwind CLI job, mirroring `release.yml:280-295`'s existing `ai-parrot-server/ui` pattern; does not touch the Python package's install-time build. The staleness check **fails the build** (no warn-only fallback) when the committed generated CSS is out of sync with the scraped class vocabulary. |
| `ai-parrot-visualizations/pyproject.toml` | none expected | `package-data` already globs `design_system/*.css` — the new generated file should be picked up automatically; verify during spec/task. |
| `test_document_shell.py`, `test_interactive_html.py`, `test_semantic_classes.py` | depends on (must keep passing) | Substring-based; safe as long as existing class names are preserved in markup (they are, per this design). |
| New tests | new | Map rendering + clustering behavior; a coverage-audit test asserting every emitted class has a CSS rule (closes the systemic-gap risk going forward). |
| `agents/flex_dashboard.py`, `agents/flex_dashboard/transformers.py` | NOT modified | The ~27k-unfiltered-marker data issue in `proximity_staffing` (transformers.py:406-485) is a separate, already-identified data-shaping gap — explicitly out of scope here; clustering in this feature makes that data usable to render, but does not fix the underlying filter bug. |

---

## Code Context

### User-Provided Code

None — this feature originated from the user directly inspecting a real generated dashboard's
HTML output and pasting an observed markup fragment (the unstyled hero-card snippet) plus a
GitHub PR link (#1296) during discovery; no code snippets were provided for reuse.

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py:76
class FoliumMapRenderer:
    def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact:
        # line 100: finds the FIRST Map component in the envelope
        # line 107: only renders a single Map component per surface — every other
        #           component in that envelope is degraded
        # line 167: fmap.get_root().render() -> standalone HTML document string
        ...

# From packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py
class InteractiveHTMLRenderer:
    _INTERCEPTED = {"Chart", "DataTable", "Infographic"}  # line 110 — Map extension point
    supported_components = {...}  # lines 537-559, "Map" currently absent

    def _render_top(self, node, ...):  # line 679
        # if name == "Chart": ...
        # if name == "DataTable": ...
        # if name == "Infographic": ...
        # else: falls through to _render_basic / .lower()-based reconstruction
        ...

    def _render_descriptor(self, ...):  # line 692
        # special-cases ONLY "Chart"/"DataTable" (lines 696-699)
        # anything else (Map included) -> entry.component_cls().lower(component, {})  # line 710
        # THIS is the exact call site that produced the "stores | label=..." text
        # the user observed (Map nested inside an Infographic section).
        ...

    def _render_basic(self, ...):  # lines 752-758
        # generic no-renderer fallback via degradation_record(...) — distinct from
        # MapComponent.lower()'s own degradation; not the code path actually hit here.
        ...

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/map.py
@register_component("Map")  # line 71
class MapComponent:
    def lower(self, component, ctx) -> ComponentTree:  # lines 78-114
        # degrades to Card -> Column -> [Text(title), Text(description),
        # Column[layer-summary Texts]]
        ...
    def _layer_summary_text(self, layer) -> str:  # lines 46-68
        # builds "{layer} | label={labelField} | color={markerColor} | total={totalCount}"

# From packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py:652-667
class RecipeRunner:
    async def _render_or_raise(self, ...):
        # resolves exactly ONE renderer via get_a2ui_renderer(recipe.render.profile)
        # and invokes it once — no multi-renderer composition exists here.
        ...

# From packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py:107-119
class DesignSystem:
    @staticmethod
    def stylesheet(theme_config, layout) -> str:
        # concatenates: theme_config.to_css_variables() + base.css (19 rules)
        #   + components.css (57 rules) + layout-{report,analytics,print}.css
        #   (169/11/11 rules respectively)
        ...
```

#### Verified Imports
```python
# Confirmed to work:
from parrot.outputs.a2ui_renderers.folium_map import FoliumMapRenderer  # folium_map.py
from parrot.outputs.a2ui.catalog.parrot.map import MapComponent  # map.py:71 (@register_component("Map"))
import folium.plugins  # MarkerCluster ships with folium>=0.14 — no new pyproject dependency
```

#### Key Attributes & Constants
- `InteractiveHTMLRenderer._INTERCEPTED` → `set[str]` (interactive_html.py:110) — add `"Map"`
  here.
- `InteractiveHTMLRenderer.supported_components` → `set[str]` (interactive_html.py:537-559) —
  add `"Map"` here too (declaration, separate from the dispatch fix).
- Map component properties schema (from `folium_map.py` + `map.py`):
  `layers: list[{layer, labelField, markerColor, dataShape, columns, data, tooltipTemplate?, geodesic?}]`,
  `viewport: {center, zoom}`, `title`.
- `DesignSystem.stylesheet()` CSS source files, with rule counts: `base.css` (19),
  `components.css` (57), `layout-report.css` (169), `layout-analytics.css` (11),
  `layout-print.css` (11) — none currently define `.a2ui-text`/`.a2ui-col`/etc.
- `.github/workflows/release.yml:280-295` — existing, working Node/pnpm CI pattern
  (`actions/setup-node` @ node 24, `corepack enable && corepack prepare pnpm@9`,
  `pnpm install --frozen-lockfile`, `pnpm build`) to mirror for the Tailwind CI job.

### Does NOT Exist (Anti-Hallucination)
- ~~Marker clustering in `folium_map.py`~~ — not present today; every feature becomes an
  individual `folium.Marker`/`CircleMarker` (lines 138-153, 296-314). Must be added.
- ~~A Node/Tailwind toolchain wired into `ai-parrot-visualizations`~~ — does not exist.
  `packages/ai-parrot-visualizations/pyproject.toml` uses plain `setuptools.build_meta` with
  no build hooks. Node/pnpm exists elsewhere in the monorepo (`ai-parrot-server/ui`) but is
  fully independent.
- ~~Multi-renderer composition in `RecipeRunner`~~ — `_render_or_raise` resolves and invokes
  exactly one renderer per run; there is no mechanism to have `interactive-html` and
  `folium_map` both render into the same pass at the `RecipeRunner` level.
- ~~`.golden`/`.snapshot` HTML fixture files for this renderer~~ — none exist; all existing
  tests are substring/count assertions on the live-rendered string, not byte-snapshot
  comparisons. (One unrelated `NAV-9372.golden.md` exists elsewhere in wiki tests — not
  related to this renderer.)
- ~~An unconditional `.lower()` call before every renderer sees a component~~ — false; the
  `_INTERCEPTED` opt-out (interactive_html.py:110) already exists and is exercised by
  Chart/DataTable/Infographic today.

---

## Parallelism Assessment

- **Internal parallelism**: high. The Map track (`interactive_html.py`'s dispatch branches +
  `folium_map.py`'s `MarkerCluster` wrapping) and the Tailwind track (CI workflow + safelist
  script + `@apply` CSS authorship + coverage-audit test) touch almost entirely disjoint
  files. The only shared touchpoint is `design_system/__init__.py`'s `stylesheet()`
  concatenation function, which the CSS track alone needs to extend by one line.
- **Cross-feature independence**: no known in-flight spec touches `interactive_html.py`,
  `folium_map.py`, or `design_system/` as of this writing. No conflicts identified.
- **Recommended isolation**: `mixed` — the two tracks can be assigned to individual worktrees/
  agents and developed concurrently, converging only at the final `stylesheet()` one-line
  integration and a shared PR.
- **Rationale**: the user explicitly confirmed Map and Tailwind are independent/parallelizable
  during discovery (no technical dependency between them), and the codebase research confirms
  near-zero file overlap between the two tracks — `per-spec` sequential-in-one-worktree would
  leave real concurrency on the table for no isolation benefit.

---

## Open Questions

- [x] What `iframe sandbox` attribute policy (if any) should the embedded folium map use,
  given production Map data can contain real employee/store PII inlined in the `srcdoc`? —
  *Owner: user* — **Resolved 2026-09-03**: `sandbox="allow-scripts allow-popups"` (script
  execution required for Leaflet; popups allowed for marker links/tooltips; top-navigation,
  forms, and same-origin access remain blocked).
- [x] What marker-count threshold triggers `MarkerCluster` wrapping (e.g. 200? 500? configurable
  per-layer)? — *Owner: user* — **Resolved 2026-09-03**: default **500**, configurable
  per-layer.
- [ ] Tailwind v3 (needs `tailwind.config.js` + content globs) vs. v4 (CSS-first config, no
  PostCSS required for `@apply`) — which major version should the CI job target? — *Owner:
  implementer, quick eval during spec*
- [x] How should the CI staleness check for the committed generated CSS file work — fail the
  build outright, or warn-and-allow-merge with a follow-up ticket? — *Owner: user* —
  **Resolved 2026-09-03**: fail the build outright, no warn-and-allow-merge fallback.
- [ ] Should the safelist-generation script live as a small Python utility (scraping
  `interactive_html.py`'s literal class strings via AST/regex) or be manually maintained as an
  explicit list — the former stays in sync automatically but is more code to review; the
  latter is simpler but can drift silently. — *Owner: implementer, propose in spec*
