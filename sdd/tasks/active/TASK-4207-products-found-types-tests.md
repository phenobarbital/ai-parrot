# TASK-4207: Non-ink-wall `products_found` test module

**Feature**: FEAT-648 — `products_found` for every product-detecting planogram type
**Spec**: `sdd/specs/products-found-endcap.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4206
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 / §4. Proves G1–G5 for the shelf-based types with synthetic fixtures
(proposal U3): profile opt-in, the tri-state `found`, multi-facing grouping, a printer
matched only through a reference image, both opt-out paths, and the assembled /
serialised shape. No provider calls, no production rows.

---

## Scope

- Create `tests/planogram_cycle/test_products_found_types.py` with the tests listed in
  the Test Specification.
- Reuse existing fixtures (`fake_vision_client` from `tests/conftest.py`); define local
  helpers (`_definition`, `_perception`, `_ctx`) in the new module.

**NOT in scope**: any production code; `test_ink_wall.py` (TASK-4206); docs (TASK-4208).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_products_found_types.py` | CREATE | FEAT-648 presence tests for shelf-based types |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.detections import DetectionBox                                    # verified: test_ink_wall.py:16
from parrot_pipelines.models import PlanogramConfig                                   # verified: test_ink_wall.py:18
from parrot_pipelines.planogram.plan import PlanogramCompliance                       # verified: test_ink_wall.py:37
from parrot_pipelines.planogram.comparison.definition import ReportingPolicy, load_slots_definition   # verified: definition.py:49, :362
from parrot_pipelines.planogram.layout import resolve_layout_profile                  # verified: layout.py:154
from parrot_pipelines.planogram.contracts import (                                    # verified: contracts.py
    CreditPolicy, CycleContext, EvidenceWeights, FacingStatus, FixtureMembership, Identification,
    IdentificationResult, PerceptionResult, ReferenceImage, Shape, ShapeKind, Slot, SlotPresence,
)   # CreditPolicy :270, EvidenceWeights :333, IdentificationResult :160, ReferenceImage :87, Slot :68, SlotPresence :231, CycleContext :374
from parrot_pipelines.planogram.types import (                                        # verified: types/__init__.py:3-9
    EndcapBacklitMultitier, EndcapNoShelvesPromotional, GraphicPanelDisplay, InkWall,
    ProductCounter, ProductOnShelves,
)
```

### Existing Signatures to Use
```python
# tests/conftest.py:159
@pytest.fixture
def fake_vision_client() -> FakeVisionClient
# planogram/layout.py:154
def resolve_layout_profile(defaults: LayoutProfile, config: dict[str, Any], *, config_name: str) -> LayoutProfile
#   reads config["layout_profile"]; deep-merges; rejects unknown keys
# planogram/comparison/definition.py
class ShelfDefinition(BaseModel): shelf_id: str; shelf_number: int; level: Optional[str]; ordered: bool = True; facings: List[FacingDefinition]   # :141
class FacingDefinition(BaseModel): facing_id: str; shelf_id: str; slot: int; product: Optional[str]; brand: Optional[str];
    facings: int = 1; facing_index: int = 1; position: Optional[int]; descriptors: Descriptors; expected_occupancy = "occupied"   # :119
class SlotsDefinition(BaseModel): meta: Dict[str, Any]   # meta["reporting"] validated (:181), applied last by effective_reporting (:196)
# planogram/contracts.py
class ReferenceImage(BaseModel): label: str; image: bytes; catalog_key: str; brand: Optional[str] = None      # :87
class Identification(BaseModel): shape_id: str; image_id; product; brand; text; descriptors; occupancy="unknown";
    raw_confidence; evidence: List[str]; source; uncertain: bool = False; reference_id: Optional[str] = None   # :123-139
class CycleContext(BaseModel): vision; executor; ocr; definition; bindings; credit_policy; evidence_weights;
    output_dir; layout: Any = None; reference_bank: List[ReferenceImage]; ...                                 # :374
class FacingStatus(str, Enum): MATCH, MISPLACED, VARIANT_UNRESOLVED, MISMATCH, EMPTY, INFERRED_PRESENT,
    OCCUPIED_UNASSIGNED, CONFLICT, NOT_ASSESSED, NOT_VISIBLE, EXPECTED_EMPTY, UNEXPECTED_OCCUPIED            # :170
# planogram/stages/compare.py:34 _reference_product — reference_id → ctx.reference_bank[label].catalog_key →
#   resolve_identity(product=catalog_key) ; settles nothing when identification.uncertain or no reference_id
# planogram/plan.py:505 PlanogramCompliance._assemble(perceptions, identifications, comparison, renders, ctx) -> dict ; :519 "products_found"
# planogram/types/product_on_shelves.py:119 / endcap_backlit_multitier.py:175 — compare() calls _ensure_layout(ctx)
#   (resolves the profile only when ctx.layout is None). ProductCounter / GraphicPanelDisplay compare() do NOT.
```

### Patterns to Copy
- Building shapes / slots / identifications by hand and driving `pipe._type_handler.compare(...)`
  then `pipe._assemble([], [], comparison, [], context)`: `tests/planogram_cycle/test_ink_wall.py:544-605`.
- Offline context: `_InlineExecutor`, `_NoOcr`, `_ctx(definition)` at `test_ink_wall.py:49-83` —
  copy them locally (do not import private helpers across test modules).
- Reference bank: `CycleContext(reference_bank=[ReferenceImage(label="ref-0003", image=b"png", catalog_key="...")])`
  at `test_comparison_identity.py:251-253`; reference canonicalisation case at `:256`.
- Shelf-type handler with generic config: `test_neutral_shelf_types.py:73-78` (`_handler`).

### Does NOT Exist
- ~~`tests/planogram_cycle/conftest.py`~~ — fixtures come from `packages/ai-parrot-pipelines/tests/conftest.py`.
- ~~`planogram_config["reporting"]`~~ / ~~`PlanogramConfig.reporting`~~ — the override is `planogram_config["layout_profile"]["reporting"]`.
- ~~`SlotsDefinition.reporting`~~ — it is `meta["reporting"]`.
- ~~`LayoutProfile(slot_presence=...)`~~ — lives under `reporting=`.
- ~~`ComplianceResult.products_found`~~ — on `ComparisonResult` / the assembled dict only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_products_found_types.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#ReportingPolicy",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py#resolve_layout_profile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#SlotPresence",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#ReferenceImage",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CycleContext",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance._assemble",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py#_reference_product",
    "sym:packages/ai-parrot-pipelines/tests/conftest.py#fake_vision_client"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- No provider I/O: `compare()` is pure; give the context `vision=None`.
- For `ProductCounter` / `GraphicPanelDisplay` pass `layout=resolve_layout_profile(cls.default_layout_profile(), {}, config_name=...)`
  explicitly — their `compare()` does not call `_ensure_layout` (spec §7).
- The reference test must use `product=None` so identity comes ONLY from the reference
  (otherwise it proves nothing about G2).
- Never weaken a tri-state assertion to `found is not True`; `None` and `False` are distinct contracts.

---

## Implementation Blueprint

### Steps (in order)
1. Write module header, imports, local offline helpers — *why*: test modules must not import each other's privates.
2. Write the two pure profile tests — *why*: cheapest proof of G3/G4, no fixture needed.
3. Write `_definition()` / `_perception()` and the tri-state compare test — *why*: AC-3.
4. Add reference, endcap, override and assemble tests.
5. Run the Validation Commands.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_products_found_types.py` (CREATE)
```python
"""products_found for shelf-based, non-ink-wall planogram types (FEAT-648)."""

from __future__ import annotations

from typing import Any

import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.comparison.definition import ReportingPolicy, load_slots_definition
from parrot_pipelines.planogram.contracts import (
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FacingStatus,
    FixtureMembership,
    Identification,
    IdentificationResult,
    PerceptionResult,
    ReferenceImage,
    Shape,
    ShapeKind,
    Slot,
    SlotPresence,
)
from parrot_pipelines.planogram.layout import resolve_layout_profile
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types import (
    EndcapBacklitMultitier,
    EndcapNoShelvesPromotional,
    GraphicPanelDisplay,
    InkWall,
    ProductCounter,
    ProductOnShelves,
)

_SHELF_TYPES = [EndcapBacklitMultitier, ProductOnShelves, ProductCounter, GraphicPanelDisplay]


class _InlineExecutor:
    """Run CPU helpers inline."""

    async def run(self, fn: Any, *args: Any) -> Any:
        """Call the helper synchronously."""
        return fn(*args)


class _NoOcr:
    """Offline OCR marker."""

    available = False


@pytest.mark.parametrize("composable", _SHELF_TYPES)
def test_shelf_types_opt_in_to_slot_presence(composable: type[Any]) -> None:
    """The four shelf-based profiles report slot presence with display-name labels (G1, G3, G4)."""
    assert composable.default_layout_profile().reporting == ReportingPolicy(slot_presence=True)


def test_zone_and_ink_wall_profiles_unchanged() -> None:
    """Zone-only and ink-wall profiles keep their FEAT-645 reporting policies."""
    assert EndcapNoShelvesPromotional.default_layout_profile().reporting == ReportingPolicy()
    assert InkWall.default_layout_profile().reporting == ReportingPolicy(product_label="product", slot_presence=True)
    assert ReportingPolicy().slot_presence is False


def _definition(meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """One shelf: ET-2850 (pos 1), CLOSEOUT x2 (pos 2, two facings), ET-4850 (pos 3)."""
    # FILL IN: build the dict per spec §4 "Test Data / Fixtures" (shelf_id "s1", shelf_number 1, level "1";
    #   descriptors with sku + display_name; the two CLOSEOUT facings share position 2 with facings=2 and
    #   facing_index 1/2); add "meta": meta when given — bounded by FacingDefinition (definition.py:119).


def _ctx(definition: dict[str, Any], *, layout: Any = None, bank: list[ReferenceImage] | None = None) -> CycleContext:
    """Offline context; ``layout=None`` lets types with ``_ensure_layout`` resolve their own profile."""
    return CycleContext(
        vision=None,
        executor=_InlineExecutor(),
        ocr=_NoOcr(),
        definition=load_slots_definition(definition),
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
        layout=layout,
        reference_bank=bank or [],
    )


def _perception(slots: list[int]) -> PerceptionResult:
    """ON_FIXTURE product shapes and one Slot per index on row 0 (shape as test_ink_wall.py:555-579)."""
    # FILL IN: copy the Shape/Slot construction of test_ink_wall.py:555-579 for the given slot indices.


def _identifications(by_slot: dict[int, dict[str, Any]]) -> IdentificationResult:
    """One occupied Identification per slot index with the given field overrides."""
    # FILL IN: shape_id=f"img0:r0:s{slot}", image_id="img0", occupancy="occupied", evidence=["read"], **fields.


# FILL IN: the async tests below (see Test Specification) — each bounded by the AC named in its docstring.
```
**Why this shape**: the two profile tests are complete because their contract is fixed by the
spec; the compare-level fixtures are stubs because the exact slot/position mapping must be
checked against `build_slot_presence` grouping (presence.py:50-54), not assumed.

### FILL IN checklist
- [ ] `_definition` — dict per spec §4; bounded by `FacingDefinition` validators.
- [ ] `_perception` / `_identifications` — copy the verified construction; bounded by `test_ink_wall.py:555-589`.
- [ ] `test_product_on_shelves_products_found_tri_state` — AC-3 (True/False/None + facings/facings_found) and AC-5 (labels).
- [ ] `test_reference_matched_printer_is_found` — AC-4; `product=None`, `reference_id="ref-0001"`, bank `catalog_key == "ET-2850"`.
- [ ] `test_endcap_backlit_multitier_products_found` — AC-3 through `EndcapBacklitMultitier`.
- [ ] `test_layout_profile_reporting_override_disables_presence` — AC-6 (config path).
- [ ] `test_definition_meta_reporting_override_disables_presence` — AC-6 (meta path, wins over profile).
- [ ] `test_assemble_and_handler_shape_for_non_ink_wall` — `List[SlotPresence]`, `model_dump(mode="json")` round-trip.

---

## Acceptance Criteria

- [ ] All tests in the Test Specification exist and pass.
- [ ] Tri-state asserted exactly: True (MATCH), False (MISMATCH), None (NOT_VISIBLE).
- [ ] Reference-only identification yields `found is True` and `observed == "ET-2850"`.
- [ ] Both opt-out paths yield `products_found == []`.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_products_found_types.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py -q`

(Inside the worktree prefix with `PYTHONPATH=packages/ai-parrot-pipelines/src`.)

---

## Test Specification

| Test | Assertion |
|---|---|
| `test_shelf_types_opt_in_to_slot_presence[x4]` | `reporting == ReportingPolicy(slot_presence=True)` |
| `test_zone_and_ink_wall_profiles_unchanged` | zone → default policy; ink wall → product/on |
| `test_product_on_shelves_products_found_tri_state` | pos1 read ET-2850 → True/MATCH; pos3 read ET-9999 → False/MISMATCH; pos2 unseen → None/NOT_VISIBLE, `facings == 2`, `facings_found == 0`; 3 entries total; `expected_products` display names |
| `test_reference_matched_printer_is_found` | pos1 `Identification(product=None, brand="Epson", reference_id="ref-0001")` + bank `[ReferenceImage(label="ref-0001", image=b"png", catalog_key="ET-2850")]` → `found is True`, `observed == "ET-2850"` |
| `test_endcap_backlit_multitier_products_found` | same tri-state via `EndcapBacklitMultitier` |
| `test_layout_profile_reporting_override_disables_presence` | `planogram_config={"layout_profile": {"reporting": {"slot_presence": False}}}` → `[]` |
| `test_definition_meta_reporting_override_disables_presence` | `meta={"reporting": {"slot_presence": False}}` → `[]` |
| `test_assemble_and_handler_shape_for_non_ink_wall` | every item is `SlotPresence`; `SlotPresence.model_validate(p.model_dump(mode="json")) == p` |

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4206 is `done` in the per-spec index.
2. Verify the Codebase Contract, mark `in-progress`, implement from the blueprint, complete every `FILL IN`.
3. Run the Validation Commands; commit only the new test file; close with `scripts/sdd/close_task.sh TASK-4207 products-found-endcap verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
