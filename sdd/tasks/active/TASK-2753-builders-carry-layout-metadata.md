# TASK-2753: Builders carry `LayoutSpec.metadata` onto the root wire Component

**Feature**: FEAT-499 — A2UI optional-binding lowering (`parrot_optional` reaches the wire)
**Spec**: `sdd/specs/a2ui-optional-binding-lowering.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the first half of spec §3 Module 1. `LayoutSpec.metadata.extensions.parrot_optional`
is a write-only field today: `RecipeRunner._assemble_envelope_or_raise` calls
`build_infographic`/`build_surface`, and **neither builder accepts or propagates `metadata`**,
so the wire `Component` never carries it and `baking._optional_paths(component)` returns an
empty set. Every optional binding then raises `BakeError`.

This task closes the builder→component boundary. **On its own it fixes only the
`Infographic` (dashboard) branch** — the `Report` branch is lowered before baking and needs
TASK-2754. Do not claim the feature works after this task.

---

## Scope

- Add an optional `metadata: ComponentMetadata | None = None` parameter to `build_surface`
  and pass it to the `Component(...)` constructor.
- Add the same optional `metadata` parameter to `build_infographic` and forward it to its
  internal `build_surface` call.
- Modify `RecipeRunner._assemble_envelope_or_raise` to thread `recipe.layout.metadata` into
  BOTH branches (the `Infographic` branch and the generic `build_surface` branch).
- Write unit tests for the builder plumbing and the runner threading.

**NOT in scope**: lowering propagation (TASK-2754); the `ui_surfaces` handler (TASK-2755);
any change to `baking.py` (it is already correct); any change to
`agents/finance_reporter.py`; any change to `_check_bind_drift_or_raise`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | MODIFY | `metadata=` param on `build_surface` (line 50) and `build_infographic` (line 203) |
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py` | MODIFY | `_assemble_envelope_or_raise` (line 623) threads `recipe.layout.metadata` |
| `packages/ai-parrot/tests/unit/outputs/test_builders_metadata.py` | CREATE | Unit tests for the new parameter |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `84932e839` (2026-09-02).

### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_infographic, build_surface   # builders.py:203, :50
from parrot.outputs.a2ui.models import Component, ComponentMetadata, CreateSurface  # models.py:400, :364
from parrot.outputs.a2ui.recipes.models import LayoutSpec                   # recipes/models.py:109
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
_ROOT_COMPONENT_ID = "root"                                          # line 43

def build_surface(                                                   # line 50
    component: str,
    properties: dict[str, Any],
    *,
    surface_id: str,
    component_id: str = _ROOT_COMPONENT_ID,
    data_model: dict[str, Any] | None = None,
    origin: ProducerOrigin = ProducerOrigin.LLM,
) -> CreateSurface:
    envelope = CreateSurface(
        surfaceId=surface_id,
        catalogId=DEFAULT_CATALOG_ID,
        components=[Component(id=component_id, component=component, **properties)],
        dataModel=data_model or {},
    )
    validate_envelope(envelope, origin=origin)
    return envelope

def build_infographic(                                               # line 203
    *, title: str, sections: Sequence[dict[str, Any]],
    subtitle: str | None = None, theme: str | None = None,
    surface_id: str = "infographic",
    data_model: dict[str, Any] | None = None,
) -> CreateSurface: ...
    # ends with: return build_surface("Infographic", props, surface_id=surface_id, data_model=data_model)

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class LayoutSpec(BaseModel):                                          # line 109
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    component: str
    child: Optional[str] = None
    children: Optional[list[Any]] = None
    metadata: Optional[ComponentMetadata] = None                      # line 150
    @property
    def props(self) -> dict[str, Any]: ...   # everything but component/child/children

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
    def _assemble_envelope_or_raise(self, recipe, data_model):        # line 623
        layout = recipe.layout
        props = layout.props
        try:
            if layout.component == "Infographic":
                envelope = build_infographic(
                    title=props.get("title", recipe.title),
                    sections=props.get("sections", []),
                    subtitle=props.get("subtitle"),
                    theme=props.get("theme") or recipe.render.theme,
                    surface_id=f"{recipe.name}-infographic",
                    data_model=data_model,
                )
            else:
                envelope = build_surface(
                    layout.component, props,
                    surface_id=f"{recipe.name}-{layout.component.lower()}",
                    data_model=data_model,
                )
        except CatalogValidationError as exc:
            raise RecipeRunException(...) from exc
        return envelope

# packages/ai-parrot/src/parrot/outputs/a2ui/baking.py — ALREADY CORRECT, do not change
def _optional_paths(component: Component) -> set[str]:                # line 187
    if component.metadata is not None and component.metadata.extensions is not None:
        return set(component.metadata.extensions.root.get("parrot_optional") or [])
    return set()
```

### Does NOT Exist
- ~~`build_surface(..., optional_paths=[...])`~~ — no such parameter. The marker travels
  inside `ComponentMetadata.extensions`, never as its own argument.
- ~~`CreateSurface.metadata`~~ — the envelope has NO envelope-level metadata field. Do not
  add one: `CreateSurface` is protocol-strict v1.0 and a new top-level key breaks FEAT-470
  G1 conformance.
- ~~`LayoutSpec.optional`~~ / ~~`DataBinding.optional`~~ — neither exists. The wire
  `DataBinding` is `extra="forbid"`.
- ~~`ComponentMetadata.parrot_optional`~~ — it lives one level deeper, under
  `.extensions.root["parrot_optional"]` (a `RootModel` mapping).

---

## Implementation Notes

### Pattern to Follow
Additive, defaulted parameter — every existing call site must keep working untouched:
```python
def build_surface(
    component: str,
    properties: dict[str, Any],
    *,
    surface_id: str,
    component_id: str = _ROOT_COMPONENT_ID,
    data_model: dict[str, Any] | None = None,
    origin: ProducerOrigin = ProducerOrigin.LLM,
    metadata: ComponentMetadata | None = None,
) -> CreateSurface:
    component_kwargs: dict[str, Any] = {"id": component_id, "component": component}
    if metadata is not None:
        component_kwargs["metadata"] = metadata
    envelope = CreateSurface(
        ...,
        components=[Component(**component_kwargs, **properties)],
        ...,
    )
```
Passing `metadata=None` explicitly must NOT emit a `metadata` key into the dumped
component (`Component.model_dump(exclude_none=True)` is what baking uses, but keep the
envelope clean at construction too).

### Key Constraints
- `properties` may itself contain a `metadata` key for hand-authored layouts. Decide and
  TEST the precedence: the explicit `metadata=` argument wins. Do not let
  `Component(**component_kwargs, **properties)` raise a duplicate-keyword `TypeError` —
  pop `metadata` out of `properties` first if present.
- Do not touch `_check_bind_drift_or_raise` (line 595). Its layout-level read is correct
  and is the only consumer that works today.
- FEAT-493 is landing concurrently in `runner.py` (`_render_or_raise`, line 647). Rebase
  onto latest `dev` before starting and re-check line numbers.

### References in Codebase
- `packages/ai-parrot/src/parrot/outputs/a2ui/compat.py:140` — how the LEGACY v1 path wrote
  `extensions["parrot_optional"]` onto a component. Same destination, different source.
- `packages/ai-parrot/src/parrot/outputs/a2ui/baking.py:187` — the consumer this task feeds.

---

## Acceptance Criteria

- [ ] `build_surface(..., metadata=cm)` puts `cm` on the root `Component`
- [ ] `build_infographic(..., metadata=cm)` does the same via its `build_surface` call
- [ ] Omitting `metadata` leaves the emitted component byte-identical to today
- [ ] An explicit `metadata=` wins over a `metadata` key inside `properties`, with no
      `TypeError`
- [ ] `_assemble_envelope_or_raise` threads `recipe.layout.metadata` in BOTH branches
- [ ] An `Infographic`-layout recipe with an absent optional binding now renders instead of
      raising `BakeError`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/outputs/test_builders_metadata.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/builders.py`
- [ ] Every emitted envelope still validates against v1.0 `agent_to_renderer.json`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/outputs/test_builders_metadata.py
import pytest
from parrot.outputs.a2ui.builders import build_infographic, build_surface
from parrot.outputs.a2ui.models import ComponentMetadata


@pytest.fixture
def optional_metadata():
    return ComponentMetadata(extensions={"parrot_optional": ["/narrative"]})


class TestBuildersCarryMetadata:
    def test_build_surface_sets_metadata_on_root(self, optional_metadata):
        env = build_surface("Report", {"title": "t"}, surface_id="s", metadata=optional_metadata)
        assert env.components[0].metadata.extensions.root["parrot_optional"] == ["/narrative"]

    def test_build_infographic_sets_metadata_on_root(self, optional_metadata):
        env = build_infographic(title="t", sections=[], surface_id="s", metadata=optional_metadata)
        assert env.components[0].metadata.extensions.root["parrot_optional"] == ["/narrative"]

    def test_default_emits_no_metadata(self):
        env = build_surface("Report", {"title": "t"}, surface_id="s")
        assert env.components[0].metadata is None

    def test_explicit_metadata_wins_over_properties_key(self, optional_metadata):
        env = build_surface(
            "Report",
            {"title": "t", "metadata": {"extensions": {"parrot_optional": ["/ignored"]}}},
            surface_id="s",
            metadata=optional_metadata,
        )
        assert env.components[0].metadata.extensions.root["parrot_optional"] == ["/narrative"]


class TestRunnerThreadsLayoutMetadata:
    def test_infographic_branch_threads_metadata(self, ...):
        """recipe.layout.metadata reaches the built envelope's root component."""

    def test_generic_branch_threads_metadata(self, ...):
        """Same for a non-Infographic layout component (e.g. Report)."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import and
   signature above still matches the source; FEAT-493 is actively touching `runner.py`
4. **Update status** in `sdd/tasks/index/a2ui-optional-binding-lowering.json` → `"in-progress"`
5. **Implement** following the scope and contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2753-builders-carry-layout-metadata.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
