# TASK-4236: `ProductCounter` / `GraphicPanelDisplay` resolve their own layout profile

**Feature**: FEAT-651 — `ProductCounter` / `GraphicPanelDisplay` resolve their own layout profile
**Spec**: `sdd/specs/fixgroup-5725d520238f.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:0a49138a5ac3` (ledger, kind `tech_debt`, severity `low`, filed by FEAT-648 review)

---

## Context

FEAT-648 (merged via PR #1630) made every shelf-based planogram type opt in to
slot-presence reporting so `products_found` is populated for all
product-detecting types. Three of the shared-cycle types (`ProductOnShelves`,
`EndcapBacklitMultitier`, `InkWall`) define a private `_ensure_layout(ctx)`
helper and call it first in `perceive()`, `identify()` and `compare()`; when
the orchestrator has not populated `ctx.layout`, it resolves the type default
merged with `planogram_config` via `resolve_layout_profile()`.

`ProductCounter` and `GraphicPanelDisplay` lack the helper. A direct
`type.compare(..., ctx)` with `ctx.layout=None` hits
`effective_reporting(None, definition)` → `ReportingPolicy()` default
(`slot_presence=False`) → `products_found == []`. The production path in
`plan.py` always passes the layout, so only direct callers and tests observe
it — and FEAT-648 verified these two types only at profile level, never
through `compare()`. Implements spec §2 / §3 Module 1.

Reproduction on `dev` @ `ab76c651a` (same `_definition()/_perception()/
_identifications()/_ctx()` helpers as the tests below):
`endcap_backlit_multitier → 3 products_found`, `product_counter → 0`,
`graphic_panel_display → 0`.

---

## Scope

- Add `_ensure_layout(self, ctx: CycleContext) -> LayoutProfile` to
  `ProductCounter` and `GraphicPanelDisplay`, byte-for-byte the helper in
  `product_on_shelves.py:120-128`.
- Call `self._ensure_layout(ctx)` as the first statement of `perceive()`,
  `identify()` and `compare()` in both types.
- Extend the `..layout` import in both files to also import
  `resolve_layout_profile`.
- Add two parametrized `compare()`-level tests to
  `tests/planogram_cycle/test_products_found_types.py` covering both types:
  tri-state `products_found` with `ctx.layout=None`, and identity
  preservation of a pre-populated `ctx.layout`.

**NOT in scope**: hoisting `_ensure_layout` into `AbstractPlanogramType`;
touching `plan.py`, `stages/compare.py`, `effective_reporting()`,
`EndcapNoShelvesPromotional`, or docs; changing any hook docstring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py` | MODIFY | import `resolve_layout_profile`; add `_ensure_layout`; call it first in the three hooks |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py` | MODIFY | same four edits |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_products_found_types.py` | MODIFY | two new parametrized compare-level tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `43bd08d65` (2026-10-12, post FEAT-648 merge + FEAT-651 spec).

### Verified Imports
```python
from ..layout import LayoutProfile, resolve_layout_profile  # verified: types/product_on_shelves.py:28, types/endcap_backlit_multitier.py:26
# CycleContext, LayoutProfile are already imported in both target files (product_counter.py:16-24, graphic_panel_display.py:16-24)
from parrot_pipelines.planogram.contracts import FacingStatus  # verified: already imported at test_products_found_types.py:16
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py:154
def resolve_layout_profile(defaults: LayoutProfile, config: dict[str, Any], *, config_name: str) -> LayoutProfile:

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:120  (REFERENCE — copy verbatim)
def _ensure_layout(self, ctx: CycleContext) -> LayoutProfile:
    """Resolve defaults and configuration when the orchestrator has not populated the context."""
    if ctx.layout is None:
        ctx.layout = resolve_layout_profile(
            self.default_layout_profile(),
            dict(self.config.planogram_config or {}),
            config_name=str(getattr(self.config, "config_name", None) or type(self).__name__),
        )
    return ctx.layout

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py
class ProductCounter(AbstractPlanogramType):                     # line 76
    def default_layout_profile(cls) -> LayoutProfile:            # line 88 (classmethod)
    async def perceive(self, image, image_id, ctx):              # line 107 → body :109
    async def identify(self, image, perception, ctx):            # line 111 → body :115
    async def compare(self, perceptions, identifications, ctx):  # line 117 → body :124

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py
class GraphicPanelDisplay(AbstractPlanogramType):                # line 57
    def default_layout_profile(cls) -> LayoutProfile:            # line 69 (classmethod)
    async def perceive(...)                                      # line 86 → body :88
    async def identify(...)                                      # line 90 → body :94
    async def compare(...)                                       # line 96 → body :103

# packages/ai-parrot-pipelines/tests/planogram_cycle/test_products_found_types.py (module-local helpers, reuse as-is)
def _definition(meta=None) -> dict                               # line 68
def _ctx(definition, *, layout=None, bank=None) -> CycleContext   # line 127
def _perception(slots: list[int]) -> PerceptionResult            # line 141
def _identifications(by_slot: dict[int, dict]) -> IdentificationResult  # line 175
def _pipeline(type_name, definition, fake_vision_client, extra_config=None) -> PlanogramCompliance  # line 192
# pipe._type_handler  → the type instance; pipe._layout → the resolved LayoutProfile (used at :288, :292)

# packages/ai-parrot-pipelines/tests/conftest.py:159
def fake_vision_client() -> FakeVisionClient   # pytest fixture

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:81-82
"graphic_panel_display": GraphicPanelDisplay, "product_counter": ProductCounter   # registry names for _pipeline()
```

### Does NOT Exist
- ~~`AbstractPlanogramType._ensure_layout`~~ — base class has no such member; do not add one.
- ~~`PlanogramCompliance.resolve_layout()`~~ — not a method; use `pipe._layout`.
- ~~`CycleContext.ensure_layout()`~~ — `layout` is a plain attribute.
- ~~`_perception(image_id, slots)`~~ — the module helper takes only `slots`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_products_found_types.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py#resolve_layout_profile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._ensure_layout",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py#ProductCounter",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py#GraphicPanelDisplay",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#effective_reporting"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`product_on_shelves.py:120-150` — helper directly after `default_layout_profile()`,
and `self._ensure_layout(ctx)` as the first line of each hook body.

### Key Constraints
- Copy the helper verbatim (name, docstring, `getattr` fallback) so the five
  shared-cycle types stay consistent.
- Do not change hook docstrings or signatures.
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`
  inside the worktree — the shared venv points at the main checkout.
- `_description()` logs a debug Pydantic error for configs without shelves
  keys; pre-existing and expected.

### References in Codebase
- `types/endcap_backlit_multitier.py:177-223` — second reference implementation
- `comparison/definition.py:196` — `effective_reporting`, the fallback this fixes

---

## Implementation Blueprint

### Steps (in order)
1. Extend the `..layout` import in both type files — *why*: `resolve_layout_profile` is the only new symbol needed.
2. Insert `_ensure_layout` after `default_layout_profile()` in both classes — *why*: same position as the three sibling types.
3. Prepend `self._ensure_layout(ctx)` to each hook body — *why*: the helper is a no-op when `plan.py` already set the layout, and resolves it for direct callers.
4. Add the two tests after `test_endcap_backlit_multitier_products_found` — *why*: they reuse that test's exact assertion shape, closing the verification gap for both types.
5. Run the Validation Commands plus `ruff check` on the three files.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from ..layout import LayoutProfile' product_counter.py)
# REPLACE line `from ..layout import LayoutProfile` (verified: product_counter.py:24) with:
from ..layout import LayoutProfile, resolve_layout_profile
```
```python
# occurrences: 1 (verified: grep -c '            reporting=ReportingPolicy(slot_presence=True),' product_counter.py)
# AFTER — insert below the closing `        )` of default_layout_profile (verified: product_counter.py:105), before `    async def perceive`
    def _ensure_layout(self, ctx: CycleContext) -> LayoutProfile:
        """Resolve defaults and configuration when the orchestrator has not populated the context."""
        if ctx.layout is None:
            ctx.layout = resolve_layout_profile(
                self.default_layout_profile(),
                dict(self.config.planogram_config or {}),
                config_name=str(getattr(self.config, "config_name", None) or type(self).__name__),
            )
        return ctx.layout
```
```python
# occurrences: 1 each (verified: grep -c on product_counter.py:109, :115, :124)
# BEFORE each of these three lines, insert `        self._ensure_layout(ctx)`:
#   `        return await perceive_image(image, image_id, ctx)`
#   `        return await identify_image(image, perception, ctx)`
#   `        return compare_observations(perceptions, identifications, ctx, self._description())`
```
**Why this shape**: mirrors `ProductOnShelves` exactly; the helper mutates `ctx.layout` in place so the shared stages read a resolved profile (`effective_reporting(ctx.layout, …)`) instead of the global default.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from ..layout import LayoutProfile' graphic_panel_display.py)
# REPLACE line `from ..layout import LayoutProfile` (verified: graphic_panel_display.py:24) with:
from ..layout import LayoutProfile, resolve_layout_profile
```
```python
# AFTER — insert below the closing `        )` of default_layout_profile (verified: graphic_panel_display.py:84), before `    async def perceive`
# (identical helper body to the product_counter.py block above)
```
```python
# occurrences: 1 each (verified: grep -c on graphic_panel_display.py:88, :94, :103)
# BEFORE each of the three `return …` hook lines, insert `        self._ensure_layout(ctx)`.
```
**Why**: same reasoning; keeps the two FEAT-612 types consistent with the other shared-cycle types.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_products_found_types.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_layout_profile_reporting_override_disables_presence' test_products_found_types.py)
# BEFORE — insert above the `@pytest.mark.asyncio` decorator of
# `test_layout_profile_reporting_override_disables_presence` (verified: test_products_found_types.py:278-279)
_LAYOUT_SELF_RESOLVING = ["product_counter", "graphic_panel_display"]


@pytest.mark.asyncio
@pytest.mark.parametrize("type_name", _LAYOUT_SELF_RESOLVING)
async def test_counter_and_panel_products_found_without_layout(type_name: str, fake_vision_client: Any) -> None:
    """compare() with ctx.layout=None resolves the type profile and reports tri-state presence (issue:0a49138a5ac3)."""
    definition = _definition()
    pipe = _pipeline(type_name, definition, fake_vision_client)
    context = _ctx(definition)
    comparison = await pipe._type_handler.compare(
        [_perception([1, 2, 3])],
        [_identifications({1: {"product": "ET-2850", "brand": "Epson"}, 3: {"product": "ET-4850", "brand": "Epson"}})],
        context,
    )

    assert context.layout is not None
    assert [(item.found, item.status) for item in comparison.products_found] == [
        (True, FacingStatus.MATCH),
        (None, FacingStatus.NOT_VISIBLE),
        (True, FacingStatus.MATCH),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("type_name", _LAYOUT_SELF_RESOLVING)
async def test_counter_and_panel_keep_provided_layout(type_name: str, fake_vision_client: Any) -> None:
    """_ensure_layout() returns the already-populated ctx.layout unchanged (orchestrator path is a no-op)."""
    definition = _definition()
    pipe = _pipeline(type_name, definition, fake_vision_client)
    context = _ctx(definition, layout=pipe._layout)

    assert pipe._type_handler._ensure_layout(context) is pipe._layout
    assert context.layout is pipe._layout
```
**Why**: the first test is the endcap test's assertion applied to the two types that previously returned `[]` (AC2); the second pins the no-op contract for the production path (AC3). Test bodies are complete — no `FILL IN` left.

### FILL IN checklist
- [ ] none — every block is fully decided; the only judgement is confirming the anchors did not move (`grep -c` each before editing).

---

## Acceptance Criteria

- [ ] **AC1** both types define `_ensure_layout` (verbatim helper) and call it first in `perceive`, `identify`, `compare`
- [ ] **AC2** `test_counter_and_panel_products_found_without_layout[product_counter|graphic_panel_display]` pass
- [ ] **AC3** `test_counter_and_panel_keep_provided_layout[...]` pass
- [ ] **AC4** whole `test_products_found_types.py` plus the three type-cycle modules below pass; `ruff check` clean on the three files
- [ ] Imports work: `from parrot_pipelines.planogram.types import ProductCounter, GraphicPanelDisplay`

---

## Validation Commands

> Run with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` inside the worktree.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_products_found_types.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_product_counter_cycle.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_panel_types.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_shelf_types.py -q`

---

## Test Specification

See the blueprint block for `test_products_found_types.py` — the two tests
there are the complete scaffold; no additional fixture is needed.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-5725d520238f --feature-id FEAT-651`)
2. **Read the spec** at `sdd/specs/fixgroup-5725d520238f.spec.md`
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — `grep -c` every anchor before editing
5. **Update status** in `sdd/tasks/index/fixgroup-5725d520238f.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint; do not change signatures or docstrings
7. **Verify** — run the Validation Commands and `ruff check`
8. **Commit the code** — stage only the three listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4236 fixgroup-5725d520238f verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
