# TASK-2754: Lowering propagates `metadata.extensions` to lowered children

**Feature**: FEAT-499 — A2UI optional-binding lowering (`parrot_optional` reaches the wire)
**Spec**: `sdd/specs/a2ui-optional-binding-lowering.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2753
**Assigned-to**: unassigned

---

## Context

Implements the second half of spec §3 Module 1 — **the half that actually fixes the
`Report` profile**, and the reason TASK-2753 alone is not enough.

`InteractiveHTMLRenderer.render` calls `self._lower_composites(envelope)` (line 571)
**before** `bake_envelope` (line 572). `_lower_composites` (line 614) skips only the
composites in `_INTERCEPTED` — `Chart`, `DataTable`, `Infographic` (line 621). So:

- **`Infographic` layout** → root survives lowering intact and is baked whole (its nested
  section/KPICard/DataTable dicts live inside that ONE component's props), so
  `_optional_paths(root)` covers the whole subtree. TASK-2753 is sufficient there.
- **`Report` layout** → `Report().lower(comp, data_model)` replaces the root with a tree of
  primitives, and the `/narrative` binding lands on a lowered CHILD that carries no
  metadata. The root marker is gone before `bake_envelope` ever sees it.

`ssr_html` uses the same lowering-then-bake order (FEAT-470 TASK-2543) and `PDFRenderer`
subclasses `SSRHTMLRenderer` — fixing only `interactive_html` silently leaves the SSR and
PDF lanes broken.

---

## Scope

- In `InteractiveHTMLRenderer._lower_composites`, propagate the composite's whole
  `metadata.extensions` mapping onto every child it lowers into.
- Apply the identical change to the `ssr_html` renderer's lowering (`PDFRenderer` inherits it).
- On a key collision, the CHILD's own value wins (it is the more specific declaration);
  otherwise the child inherits the parent's entry.
- Write unit tests covering the lowered path, the intercepted path, the collision rule, and
  the still-must-raise case.

**NOT in scope**: the builder/runner plumbing (TASK-2753, a dependency); the `ui_surfaces`
handler (TASK-2755); the e2e verification sweep (TASK-2756); adding `Report` to
`_INTERCEPTED` (explicitly rejected — see "Does NOT Exist").

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py` | MODIFY | `_lower_composites` (line 614) propagates extensions |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py` | MODIFY | Same change in its lowering step |
| `packages/ai-parrot/tests/unit/outputs/test_lowering_optional_propagation.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `84932e839` (2026-09-02).

### Verified Imports
```python
from parrot.outputs.a2ui.baking import BakeError, bake_envelope            # baking.py:46, :356
from parrot.outputs.a2ui.models import Component, ComponentMetadata, CreateSurface  # models.py:400, :364
from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer
```

### Existing Signatures to Use
```python
# packages/ai-parrot-visualizations/.../a2ui_renderers/interactive_html.py
async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact:  # line 553
    lowered_envelope = self._lower_composites(envelope)               # line 571
    baked_components = bake_envelope(lowered_envelope)                # line 572
    by_id = {bc["id"]: bc for bc in baked_components}                 # line 573

def _lower_composites(self, envelope: CreateSurface) -> CreateSurface:  # line 614
    #   for comp in ...:
    #       if comp.component in _INTERCEPTED:   # line 621 — Chart / DataTable / Infographic
    #           ...keep as-is...
    #       tree = entry.component_cls().lower(comp, envelope.data_model)   # line 629

# packages/ai-parrot/src/parrot/outputs/a2ui/baking.py — the consumer. DO NOT CHANGE.
def _optional_paths(component: Component) -> set[str]:                # line 187
    if component.metadata is not None and component.metadata.extensions is not None:
        return set(component.metadata.extensions.root.get("parrot_optional") or [])
    return set()

def _bake_component(component, *, data_model, scope_path, index, id_suffix="") -> dict:  # line 194
    dumped = component.model_dump(by_alias=True, mode="json", exclude_none=True)
    resolved = _resolve_value(dumped, ..., optional_paths=_optional_paths(component))

def _resolve_value(value, *, data_model, scope_path, index, optional_paths: set[str]):    # line 96
    # a {"path": ...} whose pointer is in optional_paths returns the module-private
    # _ABSENT sentinel (line 53) and the enclosing dict/list drops the entry;
    # anything else raises BakeError.

def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]:   # line 356
    # iterates envelope.components, calling _bake_component per component
```

### Does NOT Exist
- ~~a `Report` entry in `_INTERCEPTED`~~ — it is Chart / DataTable / Infographic only
  (`interactive_html.py:621`). **Adding `Report` to it is NOT the fix**: it would change how
  Report renders, not how optional bindings resolve, and it would break the composite's
  own lowering contract.
- ~~`Component.parrot_optional`~~ / ~~`Component.optional_paths`~~ — the marker lives at
  `component.metadata.extensions.root["parrot_optional"]`.
- ~~`bake_envelope(envelope, optional_paths=...)`~~ — `bake_envelope` takes exactly one
  positional argument. Optional paths are resolved per-component inside it.
- ~~`_lower_composites` returning a list~~ — it returns a `CreateSurface`.

---

## Implementation Notes

### Pattern to Follow
```python
# Union parent extensions into each lowered child; the child's own key wins.
def _inherit_extensions(parent: Component, child: Component) -> Component:
    parent_ext = (
        parent.metadata.extensions.root
        if parent.metadata is not None and parent.metadata.extensions is not None
        else {}
    )
    if not parent_ext:
        return child
    child_ext = (
        dict(child.metadata.extensions.root)
        if child.metadata is not None and child.metadata.extensions is not None
        else {}
    )
    merged = {**parent_ext, **child_ext}   # child wins on collision
    return child.model_copy(update={"metadata": ComponentMetadata(extensions=merged)})
```
Prefer a small shared helper over duplicating the merge in both renderers — if you place it
in core (`parrot/outputs/a2ui/`), both satellites can import it; do NOT import one renderer
from the other.

### Key Constraints
- Resolved decision (spec §8 Q1): propagate the **whole** `metadata.extensions` mapping,
  not just the `parrot_optional` key — this keeps every other `parrot_*` presentation hint
  (FEAT-470 G4) alive across lowering.
- A **required** (non-optional) unresolvable binding must STILL raise `BakeError`. Widening
  the optional set beyond what was declared is a bug, not a convenience.
- If `lower()` produces a nested tree (grandchildren), propagate transitively — a binding
  can land at any depth.
- Do not modify `baking.py`. It is the one piece that was correct all along.

### References in Codebase
- `packages/ai-parrot-visualizations/.../a2ui_renderers/ssr_html.py` — the sibling lowering
  implementation that needs the identical change.
- `packages/ai-parrot/src/parrot/outputs/a2ui/compat.py:140` — precedent for writing
  `extensions["parrot_optional"]` onto a component.

---

## Acceptance Criteria

- [ ] A `Report`-layout recipe with an absent optional binding renders instead of raising
- [ ] An `Infographic`-layout recipe with an absent optional binding still renders (no
      regression from TASK-2753)
- [ ] A non-optional unresolvable binding STILL raises `BakeError`
- [ ] A lowered child with its own `parrot_optional` keeps its value and gains the parent's
      other extension keys (child wins on collision)
- [ ] Non-`parrot_optional` extension keys also survive lowering
- [ ] Propagation reaches grandchildren, not just direct children
- [ ] `ssr-html` and `pdf` behave identically to `interactive-html` for both layout shapes
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/outputs/test_lowering_optional_propagation.py -v`
- [ ] No linting errors on both modified renderer files

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/outputs/test_lowering_optional_propagation.py
import pytest
from parrot.outputs.a2ui.baking import BakeError
from parrot.outputs.a2ui.builders import build_infographic, build_surface
from parrot.outputs.a2ui.models import ComponentMetadata


OPTIONAL = ComponentMetadata(extensions={"parrot_optional": ["/narrative"]})


class TestLoweredPathHonoursOptional:
    async def test_report_layout_absent_optional_renders(self):
        """The Report composite is LOWERED before baking — the regression this fixes."""
        env = build_surface(
            "Report",
            {"title": "t", "summary": {"path": "/narrative"}},
            surface_id="s", data_model={"facts": {}}, metadata=OPTIONAL,
        )
        artifact = await InteractiveHTMLRenderer().render(env)
        assert artifact.content

    async def test_intercepted_infographic_absent_optional_renders(self):
        """Infographic is NOT lowered — covered by TASK-2753, asserted here as a guard."""

    async def test_required_binding_still_raises(self):
        """No parrot_optional declared -> BakeError, unchanged."""
        env = build_surface(
            "Report", {"title": "t", "summary": {"path": "/narrative"}},
            surface_id="s", data_model={"facts": {}},
        )
        with pytest.raises((BakeError, Exception)):
            await InteractiveHTMLRenderer().render(env)


class TestExtensionMerge:
    def test_child_key_wins_on_collision(self): ...
    def test_child_inherits_other_parent_keys(self): ...
    def test_non_optional_extension_keys_survive(self): ...
    def test_propagates_to_grandchildren(self): ...


class TestSSRAndPDFParity:
    async def test_ssr_html_matches_interactive(self): ...
    async def test_pdf_inherits_ssr_behaviour(self): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2753 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `_INTERCEPTED`'s contents and the
   lowering-then-bake order have not shifted; FEAT-493 is actively touching these renderers
4. **Update status** in `sdd/tasks/index/a2ui-optional-binding-lowering.json` → `"in-progress"`
5. **Implement** following the scope and contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2754-lowering-propagates-extensions.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
