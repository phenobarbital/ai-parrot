# TASK-2792: Tests — build_map_document(), clustering, offline data-URI swap, FoliumMapRenderer regression

**Feature**: FEAT-522 — Interactive-HTML Map Rendering + Tailwind CSS Coverage
**Spec**: `sdd/specs/interactive-html-map-tailwind.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2787
**Assigned-to**: unassigned

---

## Context

Spec §4 Unit Tests table lists the full set this task must implement:
`test_build_map_document_basic`, `test_build_map_document_marker_cluster_above_threshold`,
`test_build_map_document_marker_cluster_below_threshold`,
`test_build_map_document_per_layer_threshold_override`,
`test_build_map_document_zero_network_resources`,
`test_build_map_document_empty_layers`,
`test_folium_map_renderer_unchanged_public_behavior`. TASK-2786/2787 already
sketched a few of these inline in their own Test Specification sections as
scaffolding — this task is the authoritative, complete implementation covering
every row in the spec's table, not just what TASK-2786/2787 sketched.

## Scope

- Implement all 7 tests from spec §4's Unit Tests table (Module 1 rows) in
  `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py`
  (extend the existing file — do not create a parallel test file for the same
  module).
- `test_build_map_document_zero_network_resources` must introspect the
  CURRENTLY INSTALLED `folium`/`folium.plugins` package live (via
  `folium.Map().default_js`/`default_css` and
  `folium.plugins.MarkerCluster().default_js`/`default_css`) to build its list
  of URLs to assert absent — NOT a hardcoded list of the 13 URLs recorded in
  the spec, so this test keeps working correctly even if a future `folium`
  version changes its exact CDN URLs (as long as the vendoring/swap keeps up,
  which is Module 6/TASK-2791's job to catch if it doesn't).
- `test_folium_map_renderer_unchanged_public_behavior` is a regression guard on
  TASK-2786's extraction: assert `FoliumMapRenderer.render()`'s returned
  `RenderedArtifact` has the same fields/shape (`artifact_id`, `mime_type`,
  `filename`, `title`, `surface`, `metadata` structure) it had before the
  refactor — compare against the existing `TestFoliumMapRenderer` test class's
  expectations already in this file (read it first).
- `test_build_map_document_empty_layers` verifies a Map with zero layers
  produces an empty-state map (no exception) — if `build_map_document()` as
  implemented by TASK-2786/2787 actually raises on this input instead, that is
  a legitimate finding to report in this task's Completion Note (do not
  silently patch `folium_map.py` from within a "tests" task — flag it).

**NOT in scope**:
- Any change to `folium_map.py`/`_map_vendor.py`/`interactive_html.py` source —
  this task only adds tests. If a test reveals a genuine implementation bug,
  document it in the Completion Note rather than silently fixing production
  code from within a test-only task.
- Integration-level tests for `InteractiveHTMLRenderer`'s dispatch (TASK-2793).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py` | MODIFY | Add the 7 unit tests listed above |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui_renderers.folium_map import (
    build_map_document,      # TASK-2786/2787 output
    DEFAULT_CLUSTER_THRESHOLD,  # TASK-2786 output, default 500
    FoliumMapRenderer,        # existing, unchanged public surface
)
```

### Existing Signatures to Use
```python
# From TASK-2786/2787 (by the time this task starts, both are complete):
def build_map_document(
    props: dict[str, Any],
    *,
    cluster_threshold: int = DEFAULT_CLUSTER_THRESHOLD,
    cluster_threshold_by_layer: dict[str, int] | None = None,
) -> tuple[bytes, list[dict[str, Any]]]: ...

class FoliumMapRenderer(AbstractA2UIRenderer):
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact: ...
    # public signature UNCHANGED from before TASK-2786's extraction.
```

### Does NOT Exist
- ~~A pre-existing offline/self-contained test in `test_folium_map.py`~~ —
  confirmed absent at spec time (spec §1/§6: "`test_folium_map.py` has no
  offline/self-contained assertion at all today"). This task adds the first
  one for THIS module's unit-level tests (the surface-level equivalent is
  TASK-2793's `test_folium_map_surface_zero_external_resources`).

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py (additions)
from parrot.outputs.a2ui_renderers.folium_map import build_map_document, DEFAULT_CLUSTER_THRESHOLD


class TestBuildMapDocument:
    def test_basic(self):
        props = {"layers": [{"layer": "stores", "data": [{"lat": 1.0, "lon": 2.0}]}]}
        document, degradations = build_map_document(props)
        assert document
        assert degradations == []

    def test_marker_cluster_above_threshold(self):
        points = [{"lat": float(i), "lon": float(i)} for i in range(DEFAULT_CLUSTER_THRESHOLD + 1)]
        props = {"layers": [{"layer": "stores", "data": points}]}
        document, _ = build_map_document(props)
        assert b"markerClusterGroup" in document

    def test_marker_cluster_below_threshold(self):
        points = [{"lat": float(i), "lon": float(i)} for i in range(10)]
        props = {"layers": [{"layer": "stores", "data": points}]}
        document, _ = build_map_document(props)
        assert b"markerClusterGroup" not in document

    def test_per_layer_threshold_override(self):
        points = [{"lat": float(i), "lon": float(i)} for i in range(20)]
        props = {"layers": [{"layer": "stores", "data": points}]}
        document, _ = build_map_document(props, cluster_threshold_by_layer={"stores": 10})
        assert b"markerClusterGroup" in document

    def test_zero_network_resources(self):
        import folium
        import folium.plugins as fp

        m = folium.Map()
        mc = fp.MarkerCluster()
        urls = [u for _, u in [*m.default_js, *m.default_css, *mc.default_js, *mc.default_css]]
        props = {"layers": [{"layer": "stores", "data": [{"lat": 1.0, "lon": 2.0}]}]}
        document, _ = build_map_document(props)
        text = document.decode("utf-8")
        for url in urls:
            assert url not in text

    def test_empty_layers(self):
        props = {"layers": []}
        document, degradations = build_map_document(props)  # must not raise
        assert document


class TestFoliumMapRendererUnchangedPublicBehavior:
    async def test_render_shape_unchanged(self, ...):  # reuse existing fixture(s)
        # Compare RenderedArtifact field shape against pre-refactor expectations
        # already asserted elsewhere in this file's TestFoliumMapRenderer class.
        ...
```

### Key Constraints
- Read the existing `test_folium_map.py` and `test_folium_layers.py` fixtures
  in full first and reuse their existing envelope/fixture-building helpers
  rather than inventing new ones.
- Introspect `folium`/`folium.plugins` live in tests that check "no CDN URL
  present" — do not hardcode the URL strings from the spec, for the reason
  given in Scope above.

### References in Codebase
- `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py` — file being extended; read in full first.
- `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_layers.py` — sibling test file, multi-layer fixture precedent.

---

## Acceptance Criteria

- [ ] All 7 tests from spec §4's Unit Tests table (Module 1 rows) exist and pass.
- [ ] `test_build_map_document_zero_network_resources` introspects the live
  `folium`/`folium.plugins` package rather than a hardcoded URL list.
- [ ] `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py -v` passes.
- [ ] Any implementation gap discovered while writing these tests (e.g. an
  empty-layers exception) is documented in the Completion Note, not silently
  patched.
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py`

---

## Test Specification

See Implementation Notes above — that IS this task's test scaffold.

---

## Agent Instructions

1. Read the spec at `sdd/specs/interactive-html-map-tailwind.spec.md` §4 Unit
   Tests table (Module 1 rows), §5 Acceptance Criteria.
2. **Check dependencies** — verify TASK-2787 is in `sdd/tasks/completed/`
   before starting.
3. Read the existing `test_folium_map.py`/`test_folium_layers.py` in full to
   match fixture conventions before writing new tests.
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
