# TASK-2793: Tests — Map dispatch integration (top-level, Infographic-nested, offline srcdoc, folium_map surface)

**Feature**: FEAT-522 — Interactive-HTML Map Rendering + Tailwind CSS Coverage
**Spec**: `sdd/specs/interactive-html-map-tailwind.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2788, TASK-2790
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests table lists 5 tests this task must implement:
`test_map_top_level_renders_iframe`, `test_map_nested_in_infographic_renders_iframe`
(the exact `flex_dashboard.py` Proximity Staffing regression), `test_map_iframe_srcdoc_has_zero_external_resources`
(closes the escaping loophole in the existing `test_document_shell.py:44-46`
guardrail — the core spec-time discovery this whole feature's offline design
hinges on), `test_all_a2ui_classes_have_css_rule` (Tailwind coverage-audit —
depends on TASK-2789/2790 also being complete since it inspects
`DesignSystem.stylesheet()`'s output), and `test_folium_map_surface_zero_external_resources`
(closes the SAME offline gap on the standalone `folium_map` surface, not just
the `interactive-html`-embedded case).

Because this task spans both the Map track (Modules 1-3) and needs the CSS
track's output (Module 4/5) for one test, its full completion effectively also
depends on TASK-2789/2790 for that ONE test
(`test_all_a2ui_classes_have_css_rule`) — implement the other 4 Map-track tests
first; if TASK-2789/2790 aren't complete yet when this task starts, implement
everything else and leave `test_all_a2ui_classes_have_css_rule` as the last
addition (or coordinate scheduling so this task starts after both TASK-2788
AND TASK-2789/2790 land — see `depends_on` note below).

## Scope

- Implement in
  `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py`
  (extend existing file):
  - `test_map_top_level_renders_iframe` — a top-level `Map` component renders
    `<iframe sandbox="allow-scripts allow-popups"` (not the old text
    degradation `"stores | label=..."`).
  - `test_map_nested_in_infographic_renders_iframe` — same assertion, for a
    `Map` nested inside an `Infographic` section's `sections`/descriptor list
    (mirrors `agents/flex_dashboard.py`'s Proximity Staffing shape — read that
    file's Map-producing section to match its actual envelope shape, or the
    closest existing Infographic-with-nested-Map test fixture already in this
    test file, if one exists for another component type, as the structural
    template).
  - `test_map_iframe_srcdoc_has_zero_external_resources` — render a Map, extract
    the `<iframe srcdoc="...">` attribute value, `html.unescape()` it, and
    assert zero `<script src="http`/`<link ... href="http` substrings inside
    the DECODED content (this is the test that actually closes the loophole:
    `test_document_shell.py:44-46`'s existing assertion only inspects the
    OUTER, still-escaped document and would pass even with a CDN leak inside
    the iframe).
- Implement in
  `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_semantic_classes.py`
  (or a new dedicated test file if that one's existing structure doesn't fit —
  match whichever is the better home after reading both):
  - `test_all_a2ui_classes_have_css_rule` — AST-scan (reuse
    `scripts/generate_a2ui_css.py`'s own scanning logic, imported as a module,
    not reimplemented — TASK-2789's script should expose its scan function
    importably for exactly this purpose; if it does not, import it anyway via
    `importlib`/`sys.path` manipulation of the `scripts/` directory, or flag
    the gap in the Completion Note if neither is clean) `interactive_html.py`'s
    emitted class vocabulary, assert every class appears as a selector
    somewhere in `DesignSystem.stylesheet()`'s output.
- Implement in `test_folium_map.py`:
  - `test_folium_map_surface_zero_external_resources` — call
    `FoliumMapRenderer.render()` directly (the standalone surface, not through
    `interactive-html`), assert its `RenderedArtifact.content` contains zero
    live-introspected CDN URLs (same technique as TASK-2792's
    `test_build_map_document_zero_network_resources`, applied at the
    `render()`-return level instead of `build_map_document()` directly — this
    is deliberately a SEPARATE test from TASK-2792's, since it exercises the
    full `FoliumMapRenderer.render()` path end-to-end, not just the extracted
    builder function).

**NOT in scope**:
- Any change to production code — this task only adds tests. Flag genuine
  implementation gaps found in the Completion Note.
- The unit-level Module 1 tests already covered by TASK-2792.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py` | MODIFY | 3 Map dispatch/offline integration tests |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_semantic_classes.py` | MODIFY | `test_all_a2ui_classes_have_css_rule` (or new file if better fit) |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_folium_map.py` | MODIFY | `test_folium_map_surface_zero_external_resources` |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer
from parrot.outputs.a2ui_renderers.folium_map import FoliumMapRenderer
from parrot.outputs.formats.assets.design_system import DesignSystem
import html
```

### Existing Signatures to Use
```python
# By the time this task starts, TASK-2788 has added:
class InteractiveHTMLRenderer(AbstractA2UIRenderer):
    def _render_map(self, props: dict[str, Any]) -> str: ...
    # _INTERCEPTED and supported_components both include "Map"

# From TASK-2786/2787:
class FoliumMapRenderer(AbstractA2UIRenderer):
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact: ...
```

### Does NOT Exist
- ~~A `test_map_*`/`test_all_a2ui_classes_have_css_rule` test anywhere in this
  repo today~~ — confirmed absent by direct read of the current test files at
  spec time; this task creates them all.
- ~~An offline-resource test on the standalone `folium_map` surface~~ —
  confirmed absent (spec §1/§6). This task's
  `test_folium_map_surface_zero_external_resources` is the first one.

---

## Implementation Notes

### Pattern to Follow
```python
# test_interactive_html.py additions
import html as html_module

class TestMapDispatchOffline:
    async def test_map_iframe_srcdoc_has_zero_external_resources(self, renderer, envelope_factory):
        envelope = envelope_factory(components=[{
            "id": "map1", "component": "Map",
            "layers": [{"layer": "stores", "data": [{"lat": 1.0, "lon": 2.0}]}],
        }])
        artifact = await renderer.render(envelope)
        doc = artifact.content.decode("utf-8")
        import re
        m = re.search(r'srcdoc="([^"]*)"', doc)
        assert m, "expected an iframe srcdoc attribute"
        decoded = html_module.unescape(m.group(1))
        assert '<script src="http' not in decoded
        assert '<link ' not in decoded or 'href="http' not in decoded
```

Match `test_interactive_html.py`'s actual existing fixture/envelope-building
API — read the file in full before writing (do not invent a fixture signature
that doesn't match the file's real conventions).

### Key Constraints
- `test_map_iframe_srcdoc_has_zero_external_resources` MUST decode
  (`html.unescape`) the `srcdoc` attribute value before asserting — asserting
  on the raw, still-escaped document (as `test_document_shell.py`'s existing
  guardrail does) is exactly the loophole this task's whole purpose is to
  close; do not accidentally reproduce that gap in the new test.
- `test_all_a2ui_classes_have_css_rule` should reuse TASK-2789's actual
  AST-scanning logic (import it), not a hand-duplicated copy — duplicated scan
  logic can drift from the real generator and give false confidence.

### References in Codebase
- `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_document_shell.py:42-46` — the EXISTING (narrower) guardrail this task's new test supersedes/extends for the Map case specifically; do not modify that file's existing test, add a new one.
- `agents/flex_dashboard.py` — real-world shape reference for the Infographic-nested-Map regression test.

---

## Acceptance Criteria

- [ ] All 5 tests from spec §4's Integration Tests table exist and pass.
- [ ] `test_map_iframe_srcdoc_has_zero_external_resources` decodes the
  `srcdoc` attribute before asserting (verify by reading the test itself, not
  just its name).
- [ ] `test_map_nested_in_infographic_renders_iframe` genuinely exercises the
  `_render_descriptor` code path (not `_render_top`) — verify the envelope
  shape used actually nests the Map inside an Infographic's section
  descriptors, matching `_render_descriptor`'s real dispatch shape.
- [ ] `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/ -v` passes (full directory, to catch any regression in files this task touches).
- [ ] No linting errors on all modified test files.

---

## Test Specification

See Implementation Notes above — that IS this task's test scaffold.

---

## Agent Instructions

1. Read the spec at `sdd/specs/interactive-html-map-tailwind.spec.md` §4
   Integration Tests table, §5 Acceptance Criteria.
2. **Check dependencies** — verify TASK-2788 is in `sdd/tasks/completed/`
   before starting. For `test_all_a2ui_classes_have_css_rule`, also verify
   TASK-2789 and TASK-2790 are complete — if not yet, implement the other 4
   tests first and note the remaining one as blocked in your progress, or
   coordinate with the task scheduler to defer this task until all three
   (TASK-2788, TASK-2789, TASK-2790) are done.
3. Read the existing `test_interactive_html.py`, `test_semantic_classes.py`,
   and `test_folium_map.py` fixture conventions in full before writing new
   tests.
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
