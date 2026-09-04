# TASK-2787: Offline data-URI swap for folium's default CDN resources

**Feature**: FEAT-522 — Interactive-HTML Map Rendering + Tailwind CSS Coverage
**Spec**: `sdd/specs/interactive-html-map-tailwind.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2785, TASK-2786
**Assigned-to**: unassigned

---

## Context

Spec §1 "Spec-time correction" / §2 "Why not `add_js_link()`/`add_css_link()`":
`build_map_document()` (added in TASK-2786) currently produces HTML that still
contains folium's default CDN URLs for Leaflet/jQuery/Bootstrap/Font
Awesome/awesome-markers/MarkerCluster — verified live against `folium==0.20.0`
to be 4 JS + 6 CSS resources on a bare `folium.Map()`, plus 1 JS + 2 CSS more
when `MarkerCluster` is used (13 total, spec §6). This violates the feature's
core "must stay fully self-contained/offline" requirement even though the
existing guardrail test (`test_document_shell.py:44-46`) would not catch it
once this HTML is embedded in an escaped `iframe srcdoc` (TASK-2788).

This task closes that gap: after `build_map_document()` builds the folium HTML
string, replace every one of the 13 known CDN URLs with an inlined `data:` URI
built from TASK-2785's vendored local files — via a plain string `.replace()`
pass over the rendered HTML, NOT via `folium.Map.add_js_link()`/`add_css_link()`
(spec §2 explicitly rejects that mechanism: it mutates a shared, class-level
mutable list on `JSCSSMixin` that every `folium.Map`/`MarkerCluster` instance in
the process shares — a global-state hazard this feature must not introduce).

## Scope

- In `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py`,
  add a module-level, read-once-at-import-time mapping from each known CDN URL
  to its base64-encoded `data:` URI, built from TASK-2785's vendored files (via
  `_map_vendor.VENDORED_ASSET_PATHS` and each file's live CDN URL, sourced from
  `folium.Map().default_js`/`default_css` and
  `folium.plugins.MarkerCluster().default_js`/`default_css`, introspected at
  import time — NOT hardcoded literal URL strings, so a future `folium` bump
  that keeps the same resource `name` but changes its pinned CDN URL is still
  matched correctly). Use the correct MIME type per file (`text/javascript` for
  `.js`, `text/css` for `.css`).
- Modify `build_map_document()` (from TASK-2786) to apply this
  `{cdn_url: data_uri}` mapping to the rendered HTML string via
  `document = document.replace(cdn_url, data_uri)` for each pair, BEFORE
  encoding/returning the final bytes.
- The swap must apply to ALL resources actually present in the given render —
  including the `MarkerCluster` resources when clustering was triggered for at
  least one layer (i.e., don't unconditionally do all 13 replacements
  regardless of whether MarkerCluster's own two JS/CSS URLs are even present in
  that particular render — a `.replace()` on a URL that isn't in the string is a
  harmless no-op, so it's fine and simpler to always run all 13 replacements
  unconditionally rather than conditionally detecting which were used).

**NOT in scope**:
- Vendoring the files themselves (TASK-2785, already done).
- Wiring this into `InteractiveHTMLRenderer`/the `iframe` embedding (TASK-2788).
- Introspecting `folium`/`MarkerCluster` resource names other than the ones
  verified in TASK-2785/spec §6 — if the installed `folium` version has drifted
  and exposes MORE default resources than the 13 already vendored, that is a
  legitimate scope gap to flag in the Completion Note, not silently patch around
  with a guess.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py` | MODIFY | Add the offline data-URI swap inside `build_map_document()` |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import base64
# TASK-2785's output:
from parrot.outputs.a2ui_renderers._map_vendor import VENDORED_ASSET_PATHS  # name -> Path
```

### Existing Signatures to Use
```python
# From TASK-2786 (this task modifies its body):
def build_map_document(
    props: dict[str, Any],
    *,
    cluster_threshold: int = DEFAULT_CLUSTER_THRESHOLD,
    cluster_threshold_by_layer: dict[str, int] | None = None,
) -> tuple[bytes, list[dict[str, Any]]]: ...

# From TASK-2785 (this task consumes it — do not modify):
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_map_vendor.py
VENDORED_ASSET_PATHS: dict[str, Path]  # keyed by folium's own resource `name`
                                        # (e.g. "leaflet", "leaflet_css",
                                        # "markerclusterjs", ...) — NOT by URL.

# folium's own JSCSSMixin (vendored dependency, read-only reference — do not
# modify folium's own source):
# class JSCSSMixin(MacroElement):
#     default_js: List[Tuple[str, str]] = []
#     default_css: List[Tuple[str, str]] = []
# `folium.Map` and `folium.plugins.MarkerCluster` are both JSCSSMixin subclasses
# with their OWN default_js/default_css class-level lists (NOT the mixin's
# empty base list) — introspect a live instance (`folium.Map().default_js`),
# never assume the mixin's base `[]`.
```

### Does NOT Exist
- ~~`folium.Map.add_js_link()`/`add_css_link()` as the mechanism used here~~ —
  deliberately NOT used (spec §2 rationale: shared class-level mutable state
  hazard). Do not reach for these methods in this task.
- ~~A `data:` URI helper already in this codebase for this purpose~~ — none
  exists; build it fresh with `base64.b64encode(...)`.

---

## Implementation Notes

### Pattern to Follow
```python
# folium_map.py, additions for this task
import base64
from parrot.outputs.a2ui_renderers._map_vendor import VENDORED_ASSET_PATHS

def _data_uri(path: Path, mime: str) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"

def _build_offline_url_map() -> dict[str, str]:
    """Read once at import time — mirrors _CHART_JS_SOURCE's convention."""
    import folium
    import folium.plugins as fp

    pairs: dict[str, str] = {}  # cdn_url -> data_uri
    m = folium.Map()
    mc = fp.MarkerCluster()
    for name, url in [*m.default_js, *mc.default_js]:
        pairs[url] = _data_uri(VENDORED_ASSET_PATHS[name], "text/javascript")
    for name, url in [*m.default_css, *mc.default_css]:
        pairs[url] = _data_uri(VENDORED_ASSET_PATHS[name], "text/css")
    return pairs

_OFFLINE_URL_MAP: dict[str, str] = _build_offline_url_map()  # read once at import time

def build_map_document(props, *, cluster_threshold=..., cluster_threshold_by_layer=None):
    ...  # existing TASK-2786 body
    document = fmap.get_root().render()
    for cdn_url, data_uri in _OFFLINE_URL_MAP.items():
        document = document.replace(cdn_url, data_uri)
    return document.encode("utf-8"), []
```

### Key Constraints
- `_build_offline_url_map()` runs ONCE at import time (module-level constant),
  not per-call — matches this codebase's established convention (`_CHART_JS_SOURCE`,
  `_BASE_CSS`) and avoids re-reading + re-encoding ~13 files on every Map render.
- Do NOT call `add_js_link()`/`add_css_link()` anywhere — the whole point of
  this task is avoiding that shared-mutable-state mechanism (spec §2).
- Base64-encoding 13 files (mostly small except `bootstrap.bundle.min.js` and
  `jquery.min.js`, each in the tens-of-KB range) at import time is a one-time,
  bounded cost — do not add caching/memoization beyond the existing
  read-once-at-import pattern; nothing more is needed.

### References in Codebase
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py:140-148` — the `_CHART_JS_SOURCE` read-once pattern this task's `_OFFLINE_URL_MAP` mirrors.
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_map_vendor.py` — TASK-2785's output, consumed here.

---

## Acceptance Criteria

- [ ] `build_map_document()`'s output HTML contains ZERO occurrences of any of
  the 13 verified CDN URLs (spec §6 "Verified Live Behavior" list).
- [ ] `build_map_document()`'s output HTML contains a `data:` URI for each
  resource actually used by that render (at minimum, Leaflet's core JS/CSS are
  always present; MarkerCluster's resources are present only when clustering
  was triggered).
- [ ] `_OFFLINE_URL_MAP` is built once at import time, not per-call (verify no
  `open()`/`read_bytes()`/`base64.b64encode()` calls happen inside
  `build_map_document()`'s own body).
- [ ] `FoliumMapRenderer.render()`'s existing tests
  (`test_folium_map.py`/`test_folium_layers.py`) still pass — the swap must not
  change the map's visual/functional output, only its resource-loading
  mechanism.
- [ ] `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_layers.py -v` passes.
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py`

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py (additions)
from parrot.outputs.a2ui_renderers.folium_map import build_map_document


class TestBuildMapDocumentOffline:
    def test_zero_external_cdn_urls(self):
        props = {"layers": [{"layer": "stores", "data": [{"lat": 1.0, "lon": 2.0}]}]}
        document, _ = build_map_document(props)
        text = document.decode("utf-8")
        assert "cdn.jsdelivr.net" not in text
        assert "cdnjs.cloudflare.com" not in text
        assert "code.jquery.com" not in text
        assert "netdna.bootstrapcdn.com" not in text

    def test_data_uris_present(self):
        props = {"layers": [{"layer": "stores", "data": [{"lat": 1.0, "lon": 2.0}]}]}
        document, _ = build_map_document(props)
        text = document.decode("utf-8")
        assert "data:text/javascript;base64," in text
        assert "data:text/css;base64," in text
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/interactive-html-map-tailwind.spec.md` §1
   (spec-time correction), §2 (rationale against `add_js_link`), §6 (verified
   live behavior — the exact 13 pairs), §7 Known Risks (folium version drift).
2. **Check dependencies** — verify TASK-2785 and TASK-2786 are in
   `sdd/tasks/completed/` before starting; this task directly consumes both
   their outputs (`VENDORED_ASSET_PATHS` and `build_map_document()`'s
   TASK-2786 body).
3. Verify the Codebase Contract's `(name, url)` pairs are still accurate against
   the currently-installed `folium` version before implementing.
4. Update status in the per-spec index → `"in-progress"`.
5. Implement per scope.
6. Verify all acceptance criteria.
7. Move this file to `sdd/tasks/completed/`.
8. Update the per-spec index → `"done"`.
9. Fill in the Completion Note below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-09-03
**Notes**: Added `_data_uri()`, `_build_offline_url_map()`, and the
module-level `_OFFLINE_URL_MAP: dict[str, str]` constant (built once at
import time, per the given pattern) to `folium_map.py`, plus the
`VENDORED_ASSET_PATHS` import from TASK-2785's `_map_vendor.py`.
`_build_offline_url_map()` introspects `folium.Map().default_js`/
`default_css` and `folium.plugins.MarkerCluster().default_js`/`default_css`
live (never a hardcoded URL list), keyed by each resource's stable `name`
against `VENDORED_ASSET_PATHS`. Confirmed 13 entries at runtime (matches
spec §6's verified count exactly — no drift in the currently-installed
`folium==0.20.0`). `build_map_document()` now applies all 13
`document.replace(cdn_url, data_uri)` swaps unconditionally right after
`fmap.get_root().render()`, before `.encode("utf-8")`. Verified no
`open()`/`read_bytes()`/`base64.b64encode()` calls exist inside
`build_map_document()`'s own body (grep confirms zero matches) — all I/O is
confined to the one-time `_build_offline_url_map()` call at module import.
Added `TestBuildMapDocumentOffline` (2 tests, matching the task's Test
Specification exactly) to `test_folium_map.py`. All 19 tests in
`test_folium_map.py` + `test_folium_layers.py` pass (17 pre-existing +
2 new). `ruff check` clean.

**Deviations from spec**: none. One design note worth flagging per the
task's own "flag it, don't silently patch around it" instruction: per the
Codebase Contract's literal "Pattern to Follow", `_build_offline_url_map()`
calls `import folium`/`import folium.plugins as fp` directly (not through
`_load_folium()`'s actionable-error wrapper), and it now runs at
`folium_map.py`'s own MODULE IMPORT time (not lazily, matching the
explicit acceptance criterion "`_OFFLINE_URL_MAP` is built once at import
time"). This means importing `folium_map.py` in an environment without
`folium` installed now raises a raw `ImportError` at import time (previously
this only happened when `.render()` was actually called, via the friendlier
`_load_folium()` message). This is a real, if narrow, behavior change
confined to this module; today nothing else in `src/` imports
`folium_map` at module scope (verified via grep), so no other module is
currently affected — but TASK-2788 (`interactive_html.py`'s Map dispatch)
should keep its own import of `folium_map`/`build_map_document` scoped
inside `_render_map()` (deferred, not at `interactive_html.py`'s top level)
to avoid making `folium` a hard, unconditional import-time dependency of
the whole `interactive-html` renderer surface.
