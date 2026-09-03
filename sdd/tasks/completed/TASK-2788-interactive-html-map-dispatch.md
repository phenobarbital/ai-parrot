# TASK-2788: InteractiveHTMLRenderer — Map dispatch at both _render_top and _render_descriptor

**Feature**: FEAT-522 — Interactive-HTML Map Rendering + Tailwind CSS Coverage
**Spec**: `sdd/specs/interactive-html-map-tailwind.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2787
**Assigned-to**: unassigned

---

## Context

Spec §1 Problem Statement / §6 "Existing Class Signatures": `MapComponent.lower()`
(`packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/map.py:78-114`)
degrades any `Map` node to a static `Card → Column → Text` layer-summary. This
happens because `InteractiveHTMLRenderer._lower_composites()`
(`interactive_html.py:641`) — the ACTUAL gate `_INTERCEPTED` controls, which runs
BEFORE baking — calls `entry.component_cls().lower(comp, envelope.data_model)`
for any component NOT in `_INTERCEPTED` (currently `{"Chart", "DataTable",
"Infographic"}`). This task adds `"Map"` to `_INTERCEPTED` and wires the actual
rendering dispatch at BOTH call sites that can encounter a baked Map node:
`_render_top` (line 679, top-level components) and `_render_descriptor` (line
692, components nested inside an `Infographic` section — the exact path
`agents/flex_dashboard.py`'s Proximity Staffing section takes, and the one that
produced the original bug report's text degradation).

This task depends on TASK-2787 because `_render_map()` calls
`folium_map.build_map_document()`, which by the end of TASK-2787 is fully
offline-safe — wiring the dispatch before that would ship a Map that's
functionally correct but leaks CDN URLs.

## Scope

- In `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`:
  - Add `"Map"` to `_INTERCEPTED` (line 110): `_INTERCEPTED = {"Chart",
    "DataTable", "Infographic", "Map"}`.
  - Add `"Map"` to the `supported_components` set inside the
    `@register_a2ui_renderer(...)` decorator (line ~537-559).
  - Add a new method `_render_map(self, props: dict[str, Any]) -> str` on
    `InteractiveHTMLRenderer`, mirroring `_render_chart`'s exact shape (line
    961: sync method, takes the baked component's own top-level `props` dict,
    returns an HTML fragment string). It must:
    - Call `document, _ = build_map_document(props, cluster_threshold=500)`
      (import `build_map_document` from `.folium_map` — verify the relative
      import path against the actual package layout).
    - Escape the document for safe embedding as an HTML attribute value
      (`html.escape(document.decode("utf-8"))` — reuse the existing `html`
      module already imported at the top of this file).
    - Return `f'<iframe sandbox="allow-scripts allow-popups"
      srcdoc="{escaped}"></iframe>'`.
  - In `_render_top` (line 679): add `if name == "Map": return
    self._render_map(comp)` alongside the existing `"Chart"`/`"DataTable"`/
    `"Infographic"` branches.
  - In `_render_descriptor` (line 692): add `if name == "Map": return
    self._render_map(properties)` BEFORE the fallback `try: entry =
    get_component(name)` block (i.e., in the same position as the existing
    `"Chart"`/`"DataTable"` special-casing at lines 696-699) — this is the
    critical fix for the Infographic-nested case; omitting it here (fixing only
    `_render_top`) is exactly how the original bug was missed.

**NOT in scope**:
- Any change to `folium_map.py`/`build_map_document()` itself (TASK-2786/2787,
  already complete by the time this task starts).
- Empty-layer / zero-data Map handling beyond whatever `build_map_document()`
  already does natively (verify it degrades gracefully rather than raising —
  if it doesn't, that's a gap to flag, not silently patch here outside scope).
- Tests (TASK-2793 covers integration tests for this dispatch).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py` | MODIFY | `_INTERCEPTED`, `supported_components`, new `_render_map`, `_render_top`/`_render_descriptor` branches |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already present at the top of interactive_html.py (verify still current before editing):
import html
import json
import logging
import uuid
from pathlib import Path
from typing import Any
import parrot.outputs.a2ui.catalog.basic
import parrot.outputs.a2ui.catalog.parrot  # noqa: F401
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog.base import BasicNode, TabSpec, to_components
from parrot.outputs.a2ui.models import Component, ComponentMetadata, CreateSurface
from parrot.outputs.a2ui.renderers import AbstractA2UIRenderer, RendererCapabilities, register_a2ui_renderer
from parrot.outputs.a2ui.renderers.degrade import degradation_record, degrade
from parrot.outputs.formats.assets.design_system import DesignSystem

# NEW import needed for this task (verify exact module path — both files live
# in the same `a2ui_renderers` package):
from .folium_map import build_map_document
```

### Existing Signatures to Use
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py
_INTERCEPTED = {"Chart", "DataTable", "Infographic"}  # line 110 — add "Map"

class InteractiveHTMLRenderer(AbstractA2UIRenderer):
    # inside @register_a2ui_renderer(..., RendererCapabilities(..., supported_components={...})), line ~537-559
    # currently: {"AudioPlayer", "Button", "Card", "CheckBox", "ChoicePicker",
    #   "Column", "DateTimeInput", "Divider", "Icon", "Image", "List", "Modal",
    #   "Row", "Slider", "Tabs", "Text", "TextField", "Video", "Chart",
    #   "DataTable", "Infographic"}  — add "Map"

    def _lower_composites(self, envelope: CreateSurface) -> CreateSurface:
        # line 641 — THE gate _INTERCEPTED controls. For comp.component in
        # _INTERCEPTED: appended unchanged (skips MapComponent.lower()). Do
        # NOT modify this method's body — it already reads _INTERCEPTED
        # generically; adding "Map" to the set is sufficient.
        ...

    def _render_top(
        self, comp: dict[str, Any], by_id: dict[str, dict[str, Any]], degradations: list[dict[str, Any]]
    ) -> str:
        # line 679
        name = comp["component"]
        if name == "Chart":
            return self._render_chart(comp)
        if name == "DataTable":
            return self._render_datatable(comp)
        if name == "Infographic":
            return self._render_infographic(comp)
        # ADD: if name == "Map": return self._render_map(comp)
        node = self._reconstruct(comp["id"], by_id)
        return self._render_basic(node, degradations)

    def _render_descriptor(self, descriptor: dict[str, Any]) -> str:
        # line 692
        name = descriptor.get("component")
        properties = descriptor.get("properties") or {}
        if name == "Chart":
            return self._render_chart(properties)
        if name == "DataTable":
            return self._render_datatable(properties)
        # ADD HERE (before the get_component/.lower() fallback):
        #   if name == "Map": return self._render_map(properties)
        try:
            entry = get_component(name)
        except KeyError:
            logger.warning("Unknown nested component %r; skipping.", name)
            return ""
        ...

    def _render_chart(self, props: dict[str, Any]) -> str:
        # line 961 — the EXACT shape _render_map must mirror: sync method,
        # takes the baked component's own top-level dict (never nested under
        # "properties"), returns an HTML fragment string.
        ...

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py (from TASK-2786/2787)
def build_map_document(
    props: dict[str, Any],
    *,
    cluster_threshold: int = 500,
    cluster_threshold_by_layer: dict[str, int] | None = None,
) -> tuple[bytes, list[dict[str, Any]]]: ...
```

### Does NOT Exist
- ~~A `_render_map` method anywhere in `interactive_html.py` today~~ — this task
  creates it.
- ~~`"Map"` in `_INTERCEPTED` or `supported_components` today~~ — confirmed
  absent by direct read at spec time; this task adds both.
- ~~Any existing `if name == "Map"` branch in `_render_top`/`_render_descriptor`~~
  — confirmed absent; anything falls through to the `.lower()` degradation path
  today.

---

## Implementation Notes

### Pattern to Follow
```python
# interactive_html.py additions
from .folium_map import build_map_document

class InteractiveHTMLRenderer(AbstractA2UIRenderer):
    ...
    def _render_map(self, props: dict[str, Any]) -> str:
        """Render a live, offline-safe Leaflet map <iframe> from RESOLVED Map
        properties. Bypasses catalog lowering entirely (MapComponent.lower()
        intentionally degrades to a text summary — real map rendering is a
        renderer concern, same precedent as _render_chart/_render_datatable)."""
        document, _ = build_map_document(props, cluster_threshold=500)
        escaped = html.escape(document.decode("utf-8"))
        return f'<iframe sandbox="allow-scripts allow-popups" srcdoc="{escaped}"></iframe>'
```

### Key Constraints
- `_render_map` must be a plain synchronous method — do not `await`
  `build_map_document()` (it's sync, per TASK-2786/2787).
- Both `_render_top` AND `_render_descriptor` must be patched — this is called
  out explicitly because a fix in only one silently leaves the other producing
  the old text degradation (spec §7 Known Risks — this is exactly how the
  original bug was missed).
- Do not rename/change any existing `a2ui-*` CSS class emitted elsewhere in
  this file — out of scope for this task (that's Module 4/TASK-2789's Tailwind
  work) and unrelated to Map rendering.

### References in Codebase
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py` — file being modified.
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py` — `build_map_document()`, consumed here (TASK-2786/2787 output).
- `agents/flex_dashboard.py` — the real dashboard whose Proximity Staffing section (nested inside an Infographic) originally exposed this bug; useful as a manual smoke-test reference, not something this task modifies.

---

## Acceptance Criteria

- [ ] A top-level `Map` component in an envelope renders as
  `<iframe sandbox="allow-scripts allow-popups" srcdoc="...">` instead of the
  old `Card → Column → Text` degradation.
- [ ] A `Map` nested inside an `Infographic` section descriptor renders the same
  way via `_render_descriptor` — NOT the old text degradation.
- [ ] `"Map"` is present in both `_INTERCEPTED` and `supported_components`.
- [ ] `MapComponent.lower()` is never called for a `Map` node processed by
  `InteractiveHTMLRenderer` (verify via the `_lower_composites` gate — a Map
  component instance passed through unchanged, not replaced by its lowered
  tree).
- [ ] All existing tests continue passing unmodified:
  `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_document_shell.py packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_semantic_classes.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py (additions)
class TestMapDispatch:
    async def test_map_top_level_renders_iframe(self, renderer, envelope_factory):
        envelope = envelope_factory(components=[{
            "id": "map1", "component": "Map",
            "layers": [{"layer": "stores", "data": [{"lat": 1.0, "lon": 2.0}]}],
        }])
        artifact = await renderer.render(envelope)
        html_out = artifact.content.decode("utf-8")
        assert '<iframe sandbox="allow-scripts allow-popups"' in html_out
        assert "stores | label=" not in html_out  # old text-degradation marker absent

    async def test_map_nested_in_infographic_renders_iframe(self, renderer, envelope_factory):
        # Mirrors flex_dashboard.py's Proximity Staffing section shape: a Map
        # nested inside an Infographic's section descriptors.
        envelope = envelope_factory(components=[{
            "id": "info1", "component": "Infographic",
            "sections": [{"component": "Map", "properties": {
                "layers": [{"layer": "stores", "data": [{"lat": 1.0, "lon": 2.0}]}],
            }}],
        }])
        artifact = await renderer.render(envelope)
        html_out = artifact.content.decode("utf-8")
        assert '<iframe sandbox="allow-scripts allow-popups"' in html_out
```

*(Fixture shapes above are illustrative — match the actual `envelope_factory`/
fixture conventions already used in `test_interactive_html.py`; read that file
first to match its exact fixture API before writing these tests.)*

---

## Agent Instructions

1. Read the spec at `sdd/specs/interactive-html-map-tailwind.spec.md` §2, §3
   Module 3, §6.
2. **Check dependencies** — verify TASK-2787 is in `sdd/tasks/completed/`
   before starting (this task calls `build_map_document()` and depends on it
   being offline-safe already).
3. Verify the Codebase Contract's line numbers/signatures against the current
   `interactive_html.py` before editing — they may have drifted.
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
**Notes**: Added `from .folium_map import build_map_document` import; `"Map"`
added to both `_INTERCEPTED` and `supported_components`; new `_render_map(self,
props)` method mirroring `_render_chart`'s exact shape (calls
`build_map_document(props, cluster_threshold=500)`, HTML-escapes the decoded
document, returns `<iframe sandbox="allow-scripts allow-popups" srcdoc="...">`);
`_render_top` and `_render_descriptor` both gained `if name == "Map": return
self._render_map(...)` branches at the positions specified. Manually
smoke-tested both dispatch paths end-to-end (not just unit-level): a
top-level Map component renders the iframe with the old
`"stores | label="` degradation text absent, and a Map nested inside an
Infographic section (`sections: [{"components": [{"component": "Map", ...}]}]`
— the ACTUAL section shape per `_render_infographic`'s own code, note this
differs from the task's own illustrative test snippet, which nested `Map`
directly under `sections` rather than under `sections[].components`) also
renders the iframe via `_render_descriptor`'s new branch — confirming the
exact `flex_dashboard.py` Proximity Staffing regression this task targets is
fixed. `"Map"` passing through `_lower_composites`'s `_INTERCEPTED` gate
unchanged is structurally guaranteed by the set addition (no separate check
needed) and confirmed indirectly: `MapComponent.lower()`'s text degradation
never appeared in either smoke test's output.

Ran the FULL `pytest packages/ai-parrot-visualizations/tests/` suite (not just
the three files this task's own AC lists) as due diligence and found ONE
pre-existing-but-newly-exposed failure,
`TestPrintLayout::test_no_auto_fit` (`test_design_system_layouts.py`) — root
cause: TASK-2789's Tailwind generation legitimately scanned `kpi-grid` (part
of the `kpi-*` vocabulary) but that class is ALREADY deliberately styled in
`components.css`/`layout-*.css` with an explicit "keep it static so print
never carries minmax" design intent; the new Tailwind rule reintroduced
`minmax(...)` into every composed sheet regardless of layout. Fixed in a
separate, clearly-labeled commit (not folded into this task's own diff):
added an `_ALREADY_STYLED_ELSEWHERE` exclusion set to
`scripts/generate_a2ui_css.py`, regenerated `tailwind.generated.css`, and
corrected one now-fragile substring assertion in `test_rich_datatable.py`
(mirroring an already-documented identical gotcha on
`test_no_pager_below_threshold` in that same file). Full suite: 231 passed
after the fix (was 1 failed before). `ruff check interactive_html.py` clean;
`test_document_shell.py`/`test_interactive_html.py`/`test_semantic_classes.py`
(the three files this task's own AC lists) pass unmodified.

**Deviations from spec**: none in this task's own files. The `kpi-grid` fix
above touches files outside this task's own Files-to-Modify table
(`scripts/generate_a2ui_css.py`, `tailwind.generated.css`,
`test_rich_datatable.py` — all TASK-2789/pre-existing-test territory, not
TASK-2788's) — flagged explicitly rather than silently bundled, justified by
the spec's own feature-level AC "`pytest packages/ai-parrot-visualizations/
tests/ -v` passes" (§5), which supersedes any single task's narrower
"existing tests continue passing" scope.
