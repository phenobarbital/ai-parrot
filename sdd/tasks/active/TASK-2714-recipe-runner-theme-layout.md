# TASK-2714: RenderSpec.layout + RecipeRunner passes the (theme, layout) pair to the renderer

**Feature**: FEAT-493 — Backend HTML Design System
**Spec**: `sdd/specs/html-renderer-design-system.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2709
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. `RenderSpec.theme` exists and is documented as *"Optional
theme name passed through to the renderer"* (`recipes/models.py:163, 171`),
but it never reaches a renderer. It is fed into `build_infographic(theme=…)`
(`runner.py:616`) on the `Infographic` layout branch only, where it becomes
an `Infographic.theme` prop that no renderer reads; on the `build_surface`
branch (`:621`) it is dropped outright. `_render_or_raise` constructs
`renderer_cls()` with no arguments (`:635`).

This task connects the declared configuration to the thing that renders.

---

## Scope

- Add `layout: Optional[str] = None` to `RenderSpec`
  (`recipes/models.py:158`), documented alongside `theme`.
- `_render_or_raise` (`runner.py:631-635`) constructs
  `renderer_cls(theme=recipe.render.theme, layout=recipe.render.layout)`.
- Handle the renderer that does not accept the kwargs. Not every registered
  renderer is an HTML one — `echarts`, `folium-map` and `adaptive-cards`
  have their own constructors. Detect support rather than assuming: inspect
  the signature, or pass only the kwargs the callee accepts, and fall back to
  `renderer_cls()` unchanged otherwise. A renderer that cannot be themed must
  keep working exactly as today.
- Keep the existing error semantics intact: an unknown/uninstalled renderer
  must still let `ImportError` propagate UNCHANGED (`:632-633` documents this
  as an acceptance criterion of a prior feature), and any render failure must
  still surface as `RecipeRunException` with `stage="render"`.
- Correct the `RenderSpec.theme` docstring so it describes what now actually
  happens.

**NOT in scope**: the renderer constructors themselves (TASK-2709); the
`Infographic.theme` prop path (TASK-2710 reads it); changing recipe files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py` | MODIFY | `RenderSpec.layout` + docstrings |
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py` | MODIFY | Pass the pair in `_render_or_raise` |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/test_render_spec_layout.py` | CREATE | Field + plumbing tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class RenderSpec(BaseModel):                       # line 158
    """Render-profile configuration for a recipe.

    Attributes:
        profile: Renderer name resolved via ``get_a2ui_renderer()``.   # line 162
        theme: Optional theme name passed through to the renderer.     # line 163
        delivery: Optional delivery config (provider/recipients).      # line 164
    """
    model_config = ConfigDict(populate_by_name=True, extra="forbid")   # NOTE: extra="forbid"
    profile: str = "interactive-html"              # line 170
    theme: Optional[str] = None                    # line 171
    delivery: Optional[dict[str, Any]] = None      # line 172

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
    def _assemble_envelope_or_raise(self, recipe, data_model):        # line 607
        if layout.component == "Infographic":
            envelope = build_infographic(
                ...,
                theme=props.get("theme") or recipe.render.theme,       # line 616 — the ONLY current use
                ...,
            )
        else:
            envelope = build_surface(layout.component, props, ...)     # line 621 — theme DROPPED here

    async def _render_or_raise(self, recipe, envelope) -> RenderedArtifact:   # line 631
        # Unknown/uninstalled renderer -> let ImportError propagate UNCHANGED
        renderer_cls = get_a2ui_renderer(recipe.render.profile)        # line 634
        renderer = renderer_cls()                                      # line 635 — no args
        try:
            return await renderer.render(envelope)
        except Exception as exc:
            raise RecipeRunException(
                RecipeRunError(recipe=recipe.name, stage="render", detail=str(exc))
            ) from exc

# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
def get_a2ui_renderer(name: str) -> type[AbstractA2UIRenderer]: ...    # line 141 — returns the CLASS
class AbstractA2UIRenderer(ABC):                   # line 78 — declares NO __init__
```

### Registered renderers that do NOT take theme/layout

The A2UI renderer registry holds more than the HTML ones. Verify the current
set with `get_a2ui_renderer` / the registry before assuming; at minimum
`echarts` (`echarts.py`), `folium-map` (`folium_map.py`) and
`adaptive-cards` (`adaptive_cards.py`) exist alongside `interactive-html`,
`ssr-html` and the PDF profile. Only the HTML ones gain the kwargs in
TASK-2709.

### Does NOT Exist

- ~~`RenderSpec.layout`~~ — created by this task; today only `profile`, `theme`, `delivery`
- ~~`RenderSpec.style` / `.palette` / `.density`~~ — do not invent adjacent fields; `extra="forbid"` will reject them at parse time anyway
- ~~`renderer.set_theme()` / `renderer.theme = ...`~~ — no such API; the pair arrives via the constructor
- ~~a `theme` parameter on `AbstractA2UIRenderer.render()`~~ — the ABC signature is `render(self, envelope, *, bake=True)` and is not changed by this feature
- ~~`recipe.render.profile` being an instance~~ — `get_a2ui_renderer` returns a **class**, which the runner then calls (`:634-635`)

---

## Implementation Notes

### Detect support; do not assume it

```python
import inspect

params = inspect.signature(renderer_cls).parameters
kwargs = {k: v for k, v in (("theme", recipe.render.theme),
                            ("layout", recipe.render.layout))
          if k in params and v is not None}
renderer = renderer_cls(**kwargs)
```

This keeps every non-HTML renderer working untouched and avoids a
`TypeError` that would surface to the user as a `stage="render"` failure.

### Key Constraints

- `RenderSpec` is `extra="forbid"`: an unknown key in a recipe file fails at
  parse time, so the new field must be spelled exactly `layout`.
- Preserve the `ImportError`-propagates-unchanged behaviour at `:632-633`;
  it is an acceptance criterion inherited from a prior feature.
- `_assemble_envelope_or_raise`'s `:616` line stays as-is — TASK-2710 makes
  the `Infographic.theme` prop meaningful; this task does not remove it.

### References in Codebase

- `.../runner.py:631-639` — the method being changed
- `.../recipes/models.py:158-172` — the model being extended

---

## Acceptance Criteria

- [ ] `RenderSpec` accepts `layout` and rejects an unknown sibling key (`extra="forbid"` still enforced)
- [ ] `RecipeRunner` constructs an HTML renderer with both `theme` and `layout` when the recipe declares them
- [ ] A renderer whose constructor accepts neither kwarg is still constructed and run exactly as before
- [ ] An unknown/uninstalled renderer profile still raises the original `ImportError`, unwrapped
- [ ] A render failure still raises `RecipeRunException` with `stage="render"`
- [ ] `recipe.render.theme` still reaches `build_infographic` on the `Infographic` branch
- [ ] The `RenderSpec.theme` docstring describes the real behaviour
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/recipes/ packages/ai-parrot/tests/integration/infographic_recipes/ -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/recipes/test_render_spec_layout.py
import pytest
from pydantic import ValidationError
from parrot.outputs.a2ui.recipes.models import RenderSpec


class TestRenderSpecLayout:
    def test_layout_field_accepted(self):
        assert RenderSpec(profile="interactive-html", layout="report").layout == "report"

    def test_layout_defaults_to_none(self):
        assert RenderSpec().layout is None

    def test_unknown_key_still_forbidden(self):
        with pytest.raises(ValidationError):
            RenderSpec(profile="interactive-html", palette="blue")


class TestRunnerPlumbing:
    async def test_pair_reaches_html_renderer(self): ...
    async def test_renderer_without_kwargs_unaffected(self): ...
    async def test_import_error_still_propagates_unchanged(self): ...
    async def test_render_failure_still_stage_render(self): ...
    async def test_infographic_theme_prop_path_intact(self): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 7) — note that `RenderSpec.theme` is
   *misrouted*, not unused; the task description depends on that distinction.
2. **Check dependencies** — TASK-2709 must be completed (the constructors
   must accept the kwargs first).
3. **Verify the Codebase Contract**, including the current registered-renderer
   set, before assuming which ones take the kwargs.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** per scope.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`, update the index → `"done"`,
   fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
