# TASK-2786: Extract build_map_document() from FoliumMapRenderer.render() + add MarkerCluster wrapping

**Feature**: FEAT-522 — Interactive-HTML Map Rendering + Tailwind CSS Coverage
**Spec**: `sdd/specs/interactive-html-map-tailwind.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Why a new shared builder": `FoliumMapRenderer.render()`
(`folium_map.py:76`) is declared `async def` but contains ZERO `await`
statements in its body — it's async only for `AbstractA2UIRenderer` interface
conformance. `InteractiveHTMLRenderer`'s entire internal render chain
(`_render_top`/`_render_descriptor`/`_render_chart`, `interactive_html.py:679-762`)
is fully synchronous (a list comprehension with no `await`,
`interactive_html.py:609`). A later task (TASK-2788) needs to call the map-building
logic from that synchronous chain, so this task extracts the current body of
`FoliumMapRenderer.render()` into a new synchronous, module-level function,
`build_map_document()`, which both `FoliumMapRenderer.render()` (thin async
wrapper, unchanged public behavior) and, later, `InteractiveHTMLRenderer._render_map()`
will call directly with no coroutine involved.

This task ALSO adds `folium.plugins.MarkerCluster` wrapping (spec §8 resolved:
threshold 500, per-layer overridable) — not present in the current
`folium_map.py` at all (spec §6 "Does NOT Exist": "Marker clustering in
`folium_map.py` — not present today").

This task does NOT add the offline data-URI swap (TASK-2787) — at the end of
this task, `build_map_document()`'s output HTML still contains folium's default
CDN URLs; that's expected and covered by the next task.

## Scope

- In `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py`,
  add a new module-level constant `DEFAULT_CLUSTER_THRESHOLD: int = 500`.
- Add a new module-level, SYNCHRONOUS function:
  ```python
  def build_map_document(
      props: dict[str, Any],
      *,
      cluster_threshold: int = DEFAULT_CLUSTER_THRESHOLD,
      cluster_threshold_by_layer: dict[str, int] | None = None,
  ) -> tuple[bytes, list[dict[str, Any]]]:
  ```
  containing the extracted logic currently inline in `FoliumMapRenderer.render()`
  (lines ~113-176: viewport/center/zoom resolution, the multi-layer
  `FeatureGroup`/`_add_feature` loop and the legacy single-layer `_iter_points`
  loop, `fmap.get_root().render()`). `props` is what `render()` currently calls
  `map_comp` (the single baked Map component dict) — the caller (this task's
  updated `render()`) still does its own `bake_envelope`/`next(...)` resolution
  and degradation-record building; only the actual folium-construction-and-render
  logic moves into `build_map_document()`. Return `(document.encode("utf-8"),
  degradations_placeholder)` — actually: the sibling-degradation logic
  (`degradations = [degradation_record(...) for item in baked if item is not
  map_comp]`) stays in `FoliumMapRenderer.render()` since it needs the full
  `baked` list and `envelope`, not just `props`; `build_map_document()` should
  return `(document_bytes, [])` (an empty list — the "degradations" element of
  its return tuple is reserved for a FUTURE case where the builder itself might
  skip something, e.g. an unrenderable layer; for THIS task it's always `[]`,
  since layer-level failures aren't in scope here). Keep the return shape as
  `tuple[bytes, list[dict[str, Any]]]` for forward compatibility rather than
  just `bytes`, per spec §2 "New Public Interfaces".
- Inside `build_map_document()`, for each layer in `props.get("layers")` (or the
  legacy single-layer path), wrap markers in `folium.plugins.MarkerCluster` when
  that layer's point count exceeds the effective threshold: use
  `cluster_threshold_by_layer.get(layer["layer"], cluster_threshold)` if
  `cluster_threshold_by_layer` is provided, else `cluster_threshold`. Below
  threshold: render individual markers exactly as `_add_feature` does today
  (unchanged). Above threshold: create one `folium.plugins.MarkerCluster()`,
  `.add_to(fmap)` (or `.add_to(group)`, matching the existing per-layer
  `FeatureGroup` structure), and add each feature's marker to the cluster
  instead of directly to the map/group.
- Update `FoliumMapRenderer.render()` to become a thin wrapper: keep its existing
  `folium = _load_folium()`, `baked = bake_envelope(envelope)`, `map_comp =
  next(...)`, degradation-record construction, and `RenderedArtifact(...)`
  return — but replace the inline map-building block with a call to
  `document, _ = build_map_document(map_comp, cluster_threshold=DEFAULT_CLUSTER_THRESHOLD)`
  and use `content=document` in the returned `RenderedArtifact`.
- Preserve the existing bug-fix comment about `viewport.get("zoom")` (the
  `None`-vs-missing-key handling, folium_map.py:116-124) verbatim inside the
  extracted function — do not regress that fix.

**NOT in scope**:
- The offline data-URI swap (TASK-2787 — depends on this task's output).
- Any change to `InteractiveHTMLRenderer`/`interactive_html.py` (TASK-2788).
- Any change to `_iter_points`/`_iter_layer_features`/`_add_feature` static
  methods' own signatures — reuse them as-is from inside `build_map_document()`.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py` | MODIFY | Extract `build_map_document()`, add `DEFAULT_CLUSTER_THRESHOLD`, add MarkerCluster wrapping, `render()` becomes a thin wrapper |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already present in folium_map.py:22-35 — no new imports needed for this task
# beyond `folium.plugins` (already imported as `import folium.plugins` per spec §6):
import parrot.outputs.a2ui.catalog.basic
import parrot.outputs.a2ui.catalog.parrot  # noqa: F401
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog.base import BasicNode
from parrot.outputs.a2ui.models import CreateSurface
from parrot.outputs.a2ui.renderers import AbstractA2UIRenderer, RendererCapabilities, register_a2ui_renderer
```

### Existing Signatures to Use
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py
@register_a2ui_renderer(
    "folium-map",  # _SURFACE_NAME module constant
    RendererCapabilities(interactive=False, supports_actions=False, supports_updates=False,
                          output="text/html", supported_components={"Map"}),
)
class FoliumMapRenderer(AbstractA2UIRenderer):
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact:
        # line 76 — CURRENT full body (verified at spec time, re-verify line
        # numbers before editing):
        #   folium = _load_folium()                                    # line 98
        #   baked = bake_envelope(envelope)                             # line 99
        #   map_comp = next((c for c in baked if c["component"]=="Map"), None)  # line 100
        #   if map_comp is None: raise ValueError(...)                  # lines 101-102
        #   degradations = [degradation_record(...) for item in baked if item is not map_comp]  # lines 104-111
        #   props = map_comp                                            # line 113
        #   viewport = props.get("viewport") or {}                      # line 114
        #   center = viewport.get("center") or [0.0, 0.0]                # line 115
        #   zoom = viewport.get("zoom"); if zoom is None: zoom = 2       # lines 122-124 (KEEP this exact fix — do not regress)
        #   fmap = folium.Map(location=list(center), zoom_start=zoom)    # line 126
        #   layers = props.get("layers"); has_layer_data = ...           # lines 128-131
        #   if has_layer_data: ... FeatureGroup + _add_feature loop      # lines 132-153
        #   else: ... legacy _iter_points + folium.Marker loop           # lines 154-165
        #   document = fmap.get_root().render()                         # line 167
        #   return RenderedArtifact(..., content=document.encode("utf-8"), ...)  # lines 168-176
        ...

    @staticmethod
    def _iter_points(data: Any) -> list[dict[str, Any]]: ...   # line 179 — reuse as-is
    # (also present, verify signature before use): _iter_layer_features, _add_feature — static methods
    # used by the extracted logic; call them exactly as render() currently does.
```

### Does NOT Exist
- ~~Marker clustering in `folium_map.py`~~ — confirmed absent before this task;
  this task ADDS it.
- ~~Any `await` inside `FoliumMapRenderer.render()`'s current body~~ — confirmed
  absent (spec §6). Do not add one; `build_map_document()` must be fully
  synchronous.
- ~~A `build_map_document` function anywhere in the codebase today~~ — this task
  creates it.

---

## Implementation Notes

### Pattern to Follow
```python
# folium_map.py, AFTER this task:
DEFAULT_CLUSTER_THRESHOLD: int = 500

def build_map_document(
    props: dict[str, Any],
    *,
    cluster_threshold: int = DEFAULT_CLUSTER_THRESHOLD,
    cluster_threshold_by_layer: dict[str, int] | None = None,
) -> tuple[bytes, list[dict[str, Any]]]:
    """Build one folium HTML document from baked Map properties. Synchronous —
    see spec §2 for why this must not be async."""
    folium = _load_folium()
    viewport = props.get("viewport") or {}
    center = viewport.get("center") or [0.0, 0.0]
    zoom = viewport.get("zoom")
    if zoom is None:
        zoom = 2
    fmap = folium.Map(location=list(center), zoom_start=zoom)
    # ... layer loop, now choosing MarkerCluster vs direct marker add based on
    # threshold ...
    document = fmap.get_root().render()
    return document.encode("utf-8"), []


class FoliumMapRenderer(AbstractA2UIRenderer):
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact:
        folium = _load_folium()
        baked = bake_envelope(envelope)
        map_comp = next((c for c in baked if c["component"] == "Map"), None)
        if map_comp is None:
            raise ValueError("folium_map renderer requires a 'Map' component in the envelope.")
        degradations = [degradation_record(...) for item in baked if item is not map_comp]
        document, _ = build_map_document(map_comp, cluster_threshold=DEFAULT_CLUSTER_THRESHOLD)
        return RenderedArtifact(
            artifact_id=f"{_SURFACE_NAME}-{envelope.surface_id}",
            mime_type="text/html",
            content=document,
            filename=f"{envelope.surface_id}.html",
            title=map_comp.get("title") or envelope.surface_id,
            surface=_SURFACE_NAME,
            metadata={"degraded": degradations} if degradations else {},
        )
```

### Key Constraints
- `build_map_document()` MUST remain synchronous (no `async def`, no `await`
  inside it) — this is the entire point of the extraction (spec §2).
- Do not change `FoliumMapRenderer.render()`'s public signature or its
  `RenderedArtifact` output shape/fields — existing tests (`test_folium_map.py`)
  must keep passing unmodified.
- `folium.plugins.MarkerCluster` ships with `folium` already (no new pyproject
  dependency — spec §7 External Dependencies).

### References in Codebase
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py` — file being modified; read it in full before editing.
- `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py` — existing tests that must keep passing (regression guard for the extraction).
- `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_layers.py` — existing multi-layer tests, same regression guard.

---

## Acceptance Criteria

- [ ] `build_map_document()` exists, is synchronous, and returns
  `tuple[bytes, list[dict[str, Any]]]`.
- [ ] `FoliumMapRenderer.render()`'s public signature and `RenderedArtifact`
  output are byte-for-byte unchanged for a Map with no layer above the cluster
  threshold (i.e. existing tests pass without modification).
- [ ] A layer whose point count exceeds `cluster_threshold` (default 500) has
  its markers wrapped in a `folium.plugins.MarkerCluster` in the output HTML.
- [ ] A layer whose point count is below threshold renders unchanged (individual
  markers, no `MarkerCluster`).
- [ ] `cluster_threshold_by_layer={"some_layer": N}` overrides the default for
  that one named layer only.
- [ ] `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_layers.py -v` passes unmodified.
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py`

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py (additions)
from parrot.outputs.a2ui_renderers.folium_map import build_map_document, DEFAULT_CLUSTER_THRESHOLD


class TestBuildMapDocument:
    def test_basic_single_layer(self):
        props = {"layers": [{"layer": "stores", "data": [{"lat": 1.0, "lon": 2.0}]}]}
        document, degradations = build_map_document(props)
        assert b"<html" in document.lower() or b"<!doctype" in document.lower()
        assert degradations == []

    def test_marker_cluster_above_threshold(self):
        points = [{"lat": float(i), "lon": float(i)} for i in range(DEFAULT_CLUSTER_THRESHOLD + 1)]
        props = {"layers": [{"layer": "stores", "data": points}]}
        document, _ = build_map_document(props)
        assert b"markerClusterGroup" in document or b"MarkerCluster" in document

    def test_no_cluster_below_threshold(self):
        points = [{"lat": float(i), "lon": float(i)} for i in range(10)]
        props = {"layers": [{"layer": "stores", "data": points}]}
        document, _ = build_map_document(props)
        assert b"markerClusterGroup" not in document

    def test_per_layer_threshold_override(self):
        points = [{"lat": float(i), "lon": float(i)} for i in range(20)]
        props = {"layers": [{"layer": "stores", "data": points}]}
        document, _ = build_map_document(props, cluster_threshold_by_layer={"stores": 10})
        assert b"markerClusterGroup" in document
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/interactive-html-map-tailwind.spec.md` §2, §3
   Module 1, §6.
2. No dependencies — start immediately. (Independent of TASK-2785's vendoring
   work — this task does not touch offline assets at all.)
3. Verify the Codebase Contract's line numbers/signatures against the current
   `folium_map.py` before editing — they may have drifted.
4. Update status in the per-spec index → `"in-progress"`.
5. Implement per scope.
6. Verify all acceptance criteria.
7. Move this file to `sdd/tasks/completed/`.
8. Update the per-spec index → `"done"`.
9. Fill in the Completion Note below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
