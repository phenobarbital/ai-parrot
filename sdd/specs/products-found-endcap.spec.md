---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot-pipelines, docs]
tags: [planogram, products-found, endcap, reporting-policy, slot-presence]
---

# Feature Specification: `products_found` for every product-detecting planogram type

**Feature ID**: FEAT-648
**Date**: 2026-10-10
**Author**: Jesus Lara
**Status**: draft
**Target version**: ai-parrot-pipelines 1.4.0 (current `parrot_pipelines.__version__` is 1.3.1; released in lockstep with the ai-parrot family)

> Exploration: `sdd/proposals/products-found-endcap.proposal.md` (research-grounded,
> confidence high; audit in `sdd/state/FEAT-648/`). Builds on FEAT-645
> (`sdd/specs/planogram-ink-wall-slot-presence.spec.md`), which created the
> `products_found` contract for `ink_wall` only.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-645 added `products_found` — one `SlotPresence` per occupied-expected slot, with
`found: True | False | None` — to the compliance result and to the job JSON, but only the
`ink_wall` type produces it. Every other planogram type returns `products_found == []`
even though the shared compare stage already computes positions for them. For an endcap
where printers are identified through reference images, operators cannot tell from the
output whether each expected printer was found or not: the shelf-level
`found_products` list is free text and loses that per-slot answer.

In the author's words (proposal §0): *"para un planogram que detecta productos,
`products_found` debería siempre llenarse con los productos encontrados (o no)"*.

Research (proposal §2) established that the gap is a policy flag, not missing code:
`compare_observations` fills `products_found` for any type when
`ReportingPolicy.slot_presence` is true, and only `InkWall.default_layout_profile`
sets it.

### Goals

- G1: `products_found` is populated — with the **identical** `SlotPresence` structure
  used by `ink_wall` — for every planogram type whose definition has shelves and that
  detects products: `endcap_backlit_multitier`, `product_on_shelves`,
  `product_counter`, `graphic_panel_display`.
- G2: A printer (or any product) matched through a reference image yields a
  `SlotPresence` whose `found` / `observed` reflect the match, with no new identity path.
- G3: Activation is a **per-type opt-in** in each type's `default_layout_profile()`
  (proposal U2, Option B). The `ReportingPolicy.slot_presence` default stays `False`.
- G4: Shelf-level labels are untouched: `product_label` stays `display_name` for the
  four types, so `expected_products` / `found_products` are byte-identical to today
  (proposal U1).
- G5: Existing opt-outs keep working for the new types: `slots_definition.meta.reporting`
  and `planogram_config.layout_profile.reporting`.
- G6: The reporting policy and the `products_found` contract are documented.

### Non-Goals (explicitly out of scope)

- Changing the `ReportingPolicy.slot_presence` default to `True` (Option A — rejected
  by the user at the proposal gate, U2).
- Changing `product_label` for any type other than `ink_wall` (U1).
- Any change to `SlotPresence`, `build_slot_presence`, `compare_observations`,
  `_assemble`, the aiohttp handler, scoring, credits, `FacingStatus` semantics or
  reference selection.
- `endcap_no_shelves_promotional`: its definitions are zone-only, so
  `build_slot_presence` yields `[]` by construction; it does not opt in.
- `ink_wall` behaviour, flowtask (FEAT-564 already consumes the key without branching
  on type), database schema, production configuration rows.

---

## 2. Architectural Design

### Overview

The feature is a per-type profile change plus tests and documentation.

1. **Profile opt-in (M1).** The four shelf-based types add
   `reporting=ReportingPolicy(slot_presence=True)` to the `LayoutProfile` returned by
   their `default_layout_profile()` classmethod — exactly the pattern `InkWall` uses at
   `types/ink_wall.py:80`, minus `product_label="product"`. Because
   `PlanogramCompliance.__init__` resolves `self._layout` through
   `resolve_layout_profile(composable_cls.default_layout_profile(), planogram_config,
   ...)` (`plan.py:143-145`) and hands it to `CycleContext.layout` (`plan.py:331`),
   `effective_reporting(ctx.layout, definition)` (`comparison/definition.py:196-225`)
   now resolves `slot_presence=True` for those types, and `compare_observations`
   (`stages/compare.py:224-227`) fills `products_found` through the unchanged
   `build_slot_presence`.
2. **Opt-outs are inherited.** A configuration row can still disable presence with
   `planogram_config["layout_profile"]["reporting"]["slot_presence"] = false`
   (deep-merged by `resolve_layout_profile`, `layout.py:154-200`) or with
   `slots_definition["meta"]["reporting"]["slot_presence"] = false` (validated by
   `SlotsDefinition._check_reporting_meta`, applied last by `effective_reporting`).
3. **Tests (M2).** FEAT-645's `test_non_ink_wall_result_unchanged` (which asserts
   `products_found == []` for `product_on_shelves`) is replaced by a positive assertion,
   and a new module covers the four types, the reference-image path, the tri-state
   `found`, and both opt-outs.
4. **Docs (M3).** `docs/pipelines/planogram-compliance-cycle.md` gains a "Reporting
   policy and `products_found`" section and lists the key under "Result keys";
   the FEAT-645 spec test matrix gets a one-line supersession note.

This reverses the recorded FEAT-645 decision "other types → `[]`". The FEAT-645
acceptance criterion "empty list when presence is off" remains true: presence is now
*on* for the four types by profile, and off wherever a row says so.

### Component Diagram
```
PlanogramCompliance.__init__                              plan.py:143
  └─ resolve_layout_profile(<Type>.default_layout_profile(), planogram_config)   layout.py:154
        │   M1: reporting=ReportingPolicy(slot_presence=True)   ← endcap_backlit_multitier / product_on_shelves
        │                                                        product_counter / graphic_panel_display
        ▼
  CycleContext.layout                                     plan.py:331
        ▼
<Type>.compare() ─► compare_observations()                stages/compare.py:188
        ├─ merge_positions → PositionResult[]
        ├─ policy = effective_reporting(ctx.layout, definition)     definition.py:196
        │     (layout.reporting ◄ overridden by definition.meta["reporting"])
        ├─ products_found = build_slot_presence(positions, definition, policy)   presence.py:42
        │     if policy.slot_presence else []
        └─ finalize_comparison(...)
        ▼
PlanogramCompliance._assemble → result["products_found"]  plan.py:519   (unchanged)
PlanogramComplianceHandler   → serialisable["products_found"]  handlers/planogram_compliance.py:191  (unchanged)
flowtask FEAT-564            → compliance_analysis_json / DataFrame column   (unchanged)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `EndcapBacklitMultitier.default_layout_profile` (`types/endcap_backlit_multitier.py:160-173`) | modifies | adds `reporting=ReportingPolicy(slot_presence=True)` |
| `ProductOnShelves.default_layout_profile` (`types/product_on_shelves.py:105-117`) | modifies | same |
| `ProductCounter.default_layout_profile` (`types/product_counter.py:87-103`) | modifies | same |
| `GraphicPanelDisplay.default_layout_profile` (`types/graphic_panel_display.py:68-82`) | modifies | same |
| `ReportingPolicy` (`comparison/definition.py:49-57`) | uses | unchanged; default stays `slot_presence=False`, `product_label="display_name"` |
| `effective_reporting` (`comparison/definition.py:196-225`) | uses | unchanged merge order: defaults → layout → definition meta |
| `compare_observations` (`stages/compare.py:188-231`) | uses | unchanged gate at line 226 |
| `build_slot_presence` (`comparison/presence.py:42-99`) | uses | unchanged |
| `resolve_layout_profile` (`layout.py:154-200`) | uses | unchanged; `layout_profile.reporting` override path |
| `_reference_product` (`stages/compare.py:34-57`) | uses | unchanged; reference match → definition product |
| `tests/planogram_cycle/test_ink_wall.py::test_non_ink_wall_result_unchanged` (546-613) | replaces | becomes a positive presence assertion |
| `docs/pipelines/planogram-compliance-cycle.md` | extends | new section + result key |
| `sdd/specs/planogram-ink-wall-slot-presence.spec.md:329` | annotates | supersession note |

### Data Models

No new or changed models. The structure reused verbatim (`contracts.py:231-249`):

```python
class SlotPresence(BaseModel):            # contracts.py:231
    shelf_id: str
    shelf_level: Optional[str] = None
    slot: int
    position: Optional[int] = None
    facing_ids: List[str]
    model: str                            # = FacingDefinition.product (printer / product name)
    sku: Optional[str] = None
    brand: Optional[str] = None
    display_name: Optional[str] = None
    found: Optional[bool] = None          # True | False | None (not visible / not assessed / conflict)
    misplaced: bool = False
    status: FacingStatus
    confidence: Optional[float] = None
    facings: int = 1
    facings_found: int = 0
    observed: Optional[str] = None        # PositionResult.identity of the deciding view
```

### New Public Interfaces

None. The observable change is the value of `LayoutProfile.reporting.slot_presence`
returned by four `default_layout_profile()` classmethods, and the non-empty
`result["products_found"]` for those types.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Per-type reporting opt-in | yes | exact kwarg `reporting=ReportingPolicy(slot_presence=True)` appended to four `LayoutProfile(...)` calls; import `from ..comparison.definition import ReportingPolicy` (pattern: `types/ink_wall.py:14`) | — |
| M2: Non-ink-wall presence tests | yes | fixtures, test names and assertions fixed below; builds on `test_ink_wall.py` helpers (`_ctx`, `synthetic_slots_definition`, `fake_vision_client`, `UNDESCRIBED`) and `test_comparison_identity.py`'s `CycleContext(reference_bank=[ReferenceImage(...)])` pattern | — |
| M3: Documentation + FEAT-645 note | yes | section placement and content fixed below | — |

### Module 1: Per-type reporting opt-in
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py`, `.../types/product_on_shelves.py`, `.../types/product_counter.py`, `.../types/graphic_panel_display.py`
- **Responsibility**: make the four shelf-based types report slot presence by default,
  keeping `product_label` at its `display_name` default and leaving every other profile
  field untouched.
- **Depends on**: existing `ReportingPolicy` (`comparison/definition.py:49`), `LayoutProfile.reporting` (`layout.py:99`).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # types/endcap_backlit_multitier.py  (modifies :160-173; new import next to :25)
  from ..comparison.definition import ReportingPolicy  # verified: comparison/definition.py:49 (same import shape as types/ink_wall.py:14)

  class EndcapBacklitMultitier(AbstractPlanogramType):  # verified: types/endcap_backlit_multitier.py:151
      @classmethod
      def default_layout_profile(cls) -> LayoutProfile:  # verified: :160
          """Return a fresh profile; adds ``reporting=ReportingPolicy(slot_presence=True)``.

          Every other kwarg is unchanged. ``product_label`` keeps its ``display_name`` default.
          """

  # types/product_on_shelves.py  (modifies :105-117; new import next to :15 — extend the existing
  #   `from ..comparison.definition import SlotsDefinition` line to also import ReportingPolicy)
  class ProductOnShelves(AbstractPlanogramType):  # verified: types/product_on_shelves.py:96
      @classmethod
      def default_layout_profile(cls) -> LayoutProfile:  # verified: :105
          """Same contract as above."""

  # types/product_counter.py  (modifies :87-103; new import next to :23)
  class ProductCounter(AbstractPlanogramType):
      @classmethod
      def default_layout_profile(cls) -> LayoutProfile:  # verified: :87
          """Same contract as above."""

  # types/graphic_panel_display.py  (modifies :68-82; new import next to :23)
  class GraphicPanelDisplay(AbstractPlanogramType):
      @classmethod
      def default_layout_profile(cls) -> LayoutProfile:  # verified: :68
          """Same contract as above."""
  ```
  Each profile is **byte-identical** to today except for the added `reporting=` kwarg.
  `InkWall` (`types/ink_wall.py:80`) and `EndcapNoShelvesPromotional` are not touched.

### Module 2: Non-ink-wall presence tests
- **Path**: `packages/ai-parrot-pipelines/tests/planogram_cycle/test_products_found_types.py` (new); `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` (modify 546-613)
- **Responsibility**: prove G1–G5 with synthetic fixtures (proposal U3): no provider calls, no production rows.
- **Depends on**: Module 1.
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # tests/planogram_cycle/test_products_found_types.py  (new)
  """products_found for shelf-based, non-ink-wall types (FEAT-648)."""
  import pytest
  from parrot_pipelines.planogram.comparison.definition import ReportingPolicy, load_slots_definition  # verified: definition.py:49, :362
  from parrot_pipelines.planogram.contracts import (  # verified: contracts.py
      CycleContext, FacingStatus, FixtureMembership, Identification, IdentificationResult,
      PerceptionResult, ReferenceImage, Shape, ShapeKind, Slot,
  )
  from parrot_pipelines.planogram.layout import resolve_layout_profile  # verified: layout.py:154
  from parrot_pipelines.planogram.types import (  # verified: types/__init__.py:3-9
      EndcapBacklitMultitier, EndcapNoShelvesPromotional, GraphicPanelDisplay, InkWall,
      ProductCounter, ProductOnShelves,
  )

  @pytest.mark.parametrize("composable", [EndcapBacklitMultitier, ProductOnShelves, ProductCounter, GraphicPanelDisplay])
  def test_shelf_types_opt_in_to_slot_presence(composable) -> None:
      """default_layout_profile().reporting == ReportingPolicy(slot_presence=True) — product_label stays display_name."""

  def test_zone_and_ink_wall_profiles_unchanged() -> None:
      """EndcapNoShelvesPromotional keeps slot_presence False; InkWall keeps product_label='product', slot_presence=True."""

  def _definition() -> dict:
      """Two shelves; shelf 1 has a 2-facing position (CLOSEOUT ×2) and single facings with sku/display_name descriptors."""

  def _perception(image_id: str, slots: list[int]) -> PerceptionResult:
      """ON_FIXTURE product shapes + one Slot per slot index, as test_ink_wall.py:555-579 builds them."""

  @pytest.mark.asyncio
  async def test_product_on_shelves_products_found_tri_state(fake_vision_client) -> None:
      """Read product → found True/MATCH; wrong product → found False/MISMATCH; slot without a view → found None/NOT_VISIBLE;
      one entry per occupied-expected (shelf, position); expected_products keep display-name labels."""

  @pytest.mark.asyncio
  async def test_reference_matched_printer_is_found(fake_vision_client) -> None:
      """Identification(product=None, brand=..., reference_id='ref-0001') with CycleContext.reference_bank
      [ReferenceImage(label='ref-0001', catalog_key=<facing.product>)] → SlotPresence.found True, observed == facing.product."""

  @pytest.mark.asyncio
  async def test_endcap_backlit_multitier_products_found(fake_vision_client) -> None:
      """Same tri-state through EndcapBacklitMultitier.compare (tiered profile), via the pipeline's _type_handler."""

  @pytest.mark.asyncio
  async def test_layout_profile_reporting_override_disables_presence(fake_vision_client) -> None:
      """planogram_config={'layout_profile': {'reporting': {'slot_presence': False}}} → products_found == []."""

  @pytest.mark.asyncio
  async def test_definition_meta_reporting_override_disables_presence(fake_vision_client) -> None:
      """slots_definition['meta'] = {'reporting': {'slot_presence': False}} → products_found == [] (wins over the profile)."""

  @pytest.mark.asyncio
  async def test_assemble_and_handler_shape_for_non_ink_wall(fake_vision_client) -> None:
      """_assemble exposes result['products_found'] as List[SlotPresence]; model_dump(mode='json') round-trips."""

  # tests/planogram_cycle/test_ink_wall.py  (modifies :546-613)
  async def test_non_ink_wall_labels_unchanged_with_presence(
      synthetic_slots_definition: dict[str, Any], fake_vision_client: Any
  ) -> None:
      """Renamed from test_non_ink_wall_result_unchanged: a product_on_shelves comparison keeps display-name labels
      AND now has one SlotPresence per occupied-expected slot (found True for the two read slots)."""
  ```
  `fake_vision_client` is the package-level fixture at
  `packages/ai-parrot-pipelines/tests/conftest.py:159` (returns a `FakeVisionClient`); reuse it,
  never redefine it.

### Module 3: Documentation + FEAT-645 supersession note
- **Path**: `docs/pipelines/planogram-compliance-cycle.md`; `sdd/specs/planogram-ink-wall-slot-presence.spec.md`
- **Responsibility**: document `ReportingPolicy`, the two override paths, the
  `products_found` contract (tri-state `found`), the per-type defaults; record that
  FEAT-648 supersedes the "other types → `[]`" test row.
- **Depends on**: none (content fixed here; may land before M1).
- **Interface Skeleton** *(prose contract — no code)*:
  ```markdown
  <!-- docs/pipelines/planogram-compliance-cycle.md -->
  ## Layout profiles                                     (existing, :25)
  | Reporting | `reporting.product_label` (`display_name` | `product`), `reporting.slot_presence`, `reporting.misplaced_min_confidence` |   ← new row in the field-group table (after the References row, :39)

  ## Reporting policy and `products_found`               ← NEW section, inserted before "## OCR and references" (:52)
  - what `ReportingPolicy` controls; merge order defaults → type profile → `layout_profile.reporting` → `slots_definition.meta.reporting`
  - per-type table: ink_wall = product / on; endcap_backlit_multitier, product_on_shelves, product_counter, graphic_panel_display = display_name / on; endcap_no_shelves_promotional = display_name / off (zone-only)
  - `products_found` entry shape (SlotPresence fields) and the tri-state `found` (None = not visible / not assessed / conflict — never "absent")
  - opt-out snippets for both override paths

  ## Result keys                                          (existing, :119)
  add `products_found` to the additive-keys sentence (:125-129)

  <!-- sdd/specs/planogram-ink-wall-slot-presence.spec.md:329 -->
  | `test_non_ink_wall_result_unchanged` | … | **Superseded by FEAT-648** (`sdd/specs/products-found-endcap.spec.md`): shelf-based types now opt in; the test became `test_non_ink_wall_labels_unchanged_with_presence`. |
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_shelf_types_opt_in_to_slot_presence[…]` | M1/M2 | each of the four types' `default_layout_profile().reporting == ReportingPolicy(slot_presence=True)` |
| `test_zone_and_ink_wall_profiles_unchanged` | M1/M2 | `EndcapNoShelvesPromotional` → `slot_presence=False`; `InkWall` → `product_label="product"`, `slot_presence=True` |
| `test_layout_profile_reporting_override_disables_presence` | M2 | `planogram_config.layout_profile.reporting.slot_presence=false` → `[]` |
| `test_definition_meta_reporting_override_disables_presence` | M2 | `slots_definition.meta.reporting.slot_presence=false` → `[]` |

### Integration Tests
| Test | Description |
|---|---|
| `test_product_on_shelves_products_found_tri_state` | `ProductOnShelves.compare` + `_assemble`: one `SlotPresence` per occupied-expected (shelf, position); `found` True / False / None with the matching `FacingStatus`; multi-facing position → `facings=2`, `facings_found` counted; `expected_products` keep display-name labels |
| `test_reference_matched_printer_is_found` | identification with `product=None`, `reference_id="ref-0001"` and a `CycleContext.reference_bank` whose `catalog_key` equals the facing product → `found=True`, `observed == facing.product` |
| `test_endcap_backlit_multitier_products_found` | same tri-state through `EndcapBacklitMultitier.compare` |
| `test_assemble_and_handler_shape_for_non_ink_wall` | `result["products_found"]` is `List[SlotPresence]`; `model_dump(mode="json")` round-trips (handler path) |
| `test_non_ink_wall_labels_unchanged_with_presence` (renamed) | `test_ink_wall.py`: labels unchanged **and** `products_found` non-empty |

Existing suites that must stay green: `tests/planogram_cycle/test_ink_wall.py`,
`test_slot_presence.py`, `test_comparison_identity.py`, `test_reference_images.py`,
`packages/ai-parrot/tests/handlers/test_planogram_compliance.py`.

### Test Data / Fixtures
```python
# Reuse (verified in tests/planogram_cycle/test_ink_wall.py):
#   offline (:69, monkeypatch fixture), _ctx(definition) -> CycleContext (:74),
#   synthetic_slots_definition() -> dict (:129), UNDESCRIBED (:46), _answer_strip (:134).
# Reuse (verified in tests/conftest.py:159): fake_vision_client() -> FakeVisionClient (package-level fixture).
# Reuse (verified in tests/planogram_cycle/test_comparison_identity.py:251-253):
#   CycleContext(reference_bank=[ReferenceImage(label="ref-0001", image=b"png", catalog_key="<product>")])
# New in test_products_found_types.py:
def _definition() -> dict:
    """shelves: [ {shelf_id: "s1", level: "1", facings: [
        {facing_id: "s1:1", slot: 1, position: 1, product: "ET-2850", brand: "Epson",
         descriptors: {sku: "C11CJ63201", display_name: "EcoTank ET-2850"}},
        {facing_id: "s1:2", slot: 2, position: 2, product: "CLOSEOUT", facings: 2, facing_index: 1, ...},
        {facing_id: "s1:3", slot: 3, position: 2, product: "CLOSEOUT", facings: 2, facing_index: 2, ...},
        {facing_id: "s1:4", slot: 4, position: 3, product: "ET-4850", ...} ] } ]"""
```
No E2E gate surface (no `e2e` frontmatter key).

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `EndcapBacklitMultitier`, `ProductOnShelves`, `ProductCounter` and `GraphicPanelDisplay`
      `default_layout_profile().reporting` equals `ReportingPolicy(slot_presence=True)`
      (so `product_label == "display_name"`, `misplaced_min_confidence == 0.9`); every other
      field of each profile is unchanged (G1, G3, G4).
- [ ] `ReportingPolicy()` still has `slot_presence is False`; `InkWall` and
      `EndcapNoShelvesPromotional` profiles are unchanged (G3, Non-Goals).
- [ ] For a `product_on_shelves` and an `endcap_backlit_multitier` synthetic run,
      `result["products_found"]` has exactly one `SlotPresence` per occupied-expected
      `(shelf_id, position)`, with `found` True for MATCH, False for MISMATCH/EMPTY and
      None for NOT_VISIBLE, and `facings` / `facings_found` correct for a multi-facing
      position (G1).
- [ ] A slot identified only through a reference image (`product=None`, `reference_id`)
      reports `found=True` and `observed == FacingDefinition.product` (G2).
- [ ] `expected_products` / `found_products` of those runs are identical to the values
      produced before this feature (display-name labels) (G4).
- [ ] `planogram_config.layout_profile.reporting.slot_presence=false` and
      `slots_definition.meta.reporting.slot_presence=false` each yield `products_found == []`
      for the new types (G5).
- [ ] `test_non_ink_wall_result_unchanged` no longer exists; its replacement asserts a
      non-empty presence list; all suites in §4 pass with
      `PYTHONPATH=packages/ai-parrot-pipelines/src pytest packages/ai-parrot-pipelines/tests/planogram_cycle -q`.
- [ ] `docs/pipelines/planogram-compliance-cycle.md` has the "Reporting policy and
      `products_found`" section, the Reporting row, and `products_found` under Result keys;
      the FEAT-645 spec row 329 carries the supersession note (G6).
- [ ] No change to `contracts.py`, `comparison/presence.py`, `stages/compare.py`,
      `plan.py`, `handlers/planogram_compliance.py` (Non-Goals) — `git diff --stat` of the
      feature branch lists only the files in §6 Edit Sites.
- [ ] `ruff check` passes on every touched file.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against commit `2a2d97a62` (dev, 2026-10-10). Implementation agents MUST NOT
> reference imports, attributes, or methods not listed here without first verifying
> they exist via `grep` or `read`.

### Verified Imports
```python
# inside planogram/types/*.py (relative, as the siblings do)
from ..comparison.definition import ReportingPolicy          # verified: types/ink_wall.py:14 ; class at comparison/definition.py:49
from ..comparison.definition import SlotsDefinition          # verified: types/product_on_shelves.py:15 (extend this line)
from ..layout import LayoutProfile, resolve_layout_profile   # verified: types/endcap_backlit_multitier.py:25, types/product_on_shelves.py:28
from ..layout import LayoutProfile                           # verified: types/product_counter.py:23, types/graphic_panel_display.py:23

# tests
from parrot_pipelines.models import PlanogramConfig                                   # verified: test_ink_wall.py:18
from parrot_pipelines.planogram.plan import PlanogramCompliance                       # verified: test_ink_wall.py:37
from parrot_pipelines.planogram.comparison.definition import load_slots_definition    # verified: test_ink_wall.py:21 ; def at definition.py:362
from parrot_pipelines.planogram.comparison.definition import ReportingPolicy          # verified: definition.py:49
from parrot_pipelines.planogram.comparison.presence import build_slot_presence        # verified: stages/compare.py:11 ; def at presence.py:42
from parrot_pipelines.planogram.layout import resolve_layout_profile                  # verified: layout.py:154
from parrot_pipelines.planogram.types import (EndcapBacklitMultitier, EndcapNoShelvesPromotional,
    GraphicPanelDisplay, InkWall, ProductCounter, ProductOnShelves)                   # verified: types/__init__.py:3-9
from parrot_pipelines.planogram.contracts import (CycleContext, FacingStatus, FixtureMembership,
    Identification, IdentificationResult, PerceptionResult, ReferenceImage, Shape, ShapeKind,
    Slot, SlotPresence)                                                                # verified: contracts.py:35,51,68,87,108,123,160,170,231,374 (IdentificationResult at :160)
from parrot.models.detections import DetectionBox                                     # verified: test_ink_wall.py:16
```

### Existing Class Signatures
```python
# planogram/comparison/definition.py
class ReportingPolicy(BaseModel):                                   # line 49, extra="forbid"
    product_label: Literal["display_name", "product"] = "display_name"   # line 54
    slot_presence: bool = False                                          # line 55
    misplaced_min_confidence: float = Field(default=0.9, ge=0.0, le=1.0) # line 56
class SlotsDefinition(BaseModel):                                   # line 172
    meta: Dict[str, Any]                                                 # line 176 ; meta["reporting"] validated at :181-189 (REPORTING_META_KEY = "reporting", :46)
def effective_reporting(layout: Optional[Any], definition: Optional[SlotsDefinition]) -> ReportingPolicy   # line 196
def load_slots_definition(source: Union[Dict[str, Any], str, Path]) -> SlotsDefinition                     # line 362
class FacingDefinition(BaseModel):                                  # line 119 — product: Optional[str]; occupied ⇒ nonblank product (:134-138)

# planogram/layout.py
class LayoutProfile(BaseModel):
    references: ReferencePolicy = Field(default_factory=ReferencePolicy)   # line 98
    reporting: ReportingPolicy = Field(default_factory=ReportingPolicy)    # line 99
def resolve_layout_profile(defaults: LayoutProfile, config: dict[str, Any], *, config_name: str) -> LayoutProfile   # line 154 ; reads config["layout_profile"] (LAYOUT_KEY), deep-merges, rejects unknown keys

# planogram/comparison/presence.py
def facing_presence(position: Optional[PositionResult], policy: ReportingPolicy) -> Tuple[Optional[bool], bool, Optional[float]]   # line 20
def build_slot_presence(positions: Sequence[PositionResult], definition: SlotsDefinition, policy: ReportingPolicy) -> List[SlotPresence]   # line 42

# planogram/stages/compare.py
def _reference_product(identification, definition, ctx, candidates) -> tuple[str | None, str | None]   # line 34 — reference_id → catalog_key → resolve_identity
def compare_observations(perceptions: Sequence[PerceptionResult], identifications: Sequence[IdentificationResult],
                         ctx: CycleContext, description: PlanogramDescription) -> ComparisonResult   # line 188 ; gate at :224-227

# planogram/contracts.py
class ReferenceImage(BaseModel): label: str; image: bytes; catalog_key: str; brand: Optional[str] = None   # line 87
class Identification(BaseModel): ...; product: Optional[str]; brand: Optional[str]; reference_id: Optional[str] = None   # line 123-139
class SlotPresence(BaseModel)                                                         # line 231-249 (fields in §2)
class ComparisonResult(BaseModel): products_found: List[SlotPresence] = Field(default_factory=list)   # line 346, 351
class CycleContext(BaseModel): definition: Optional[Any]; layout: Any = None; reference_bank: List[ReferenceImage]   # line 374-390

# planogram/plan.py
class PlanogramCompliance:
    self._layout = resolve_layout_profile(composable_cls.default_layout_profile(), planogram_config.planogram_config or {}, config_name=config_name)   # line 143-145
    # CycleContext(... layout=self._layout, ...)                                      # line 331
    def _assemble(self, perceptions, identifications, comparison, renders, ctx) -> Dict[str, Any]   # line 505 ; "products_found": comparison.products_found at :519

# planogram/types/*.py
class EndcapBacklitMultitier(AbstractPlanogramType):  @classmethod default_layout_profile(cls) -> LayoutProfile   # :151, :160-173
class ProductOnShelves(AbstractPlanogramType):        @classmethod default_layout_profile(cls) -> LayoutProfile   # :96, :105-117
class ProductCounter(AbstractPlanogramType):          @classmethod default_layout_profile(cls) -> LayoutProfile   # :87-103
class GraphicPanelDisplay(AbstractPlanogramType):     @classmethod default_layout_profile(cls) -> LayoutProfile   # :68-82
class InkWall(AbstractPlanogramType):                 reporting=ReportingPolicy(product_label="product", slot_presence=True)   # :80 (pattern)

# tests/conftest.py
def fake_vision_client() -> FakeVisionClient            # line 159 (fixture)
# tests/planogram_cycle/test_ink_wall.py
UNDESCRIBED = {(1, 8), (2, 8), (3, 7), (3, 8)}            # line 46
def offline(monkeypatch)                                   # line 69 (fixture)
def _ctx(definition=None) -> CycleContext                  # line 74
def synthetic_ink_wall() -> Image.Image                    # line 86 (fixture)
def synthetic_slots_definition() -> dict                   # line 129 (fixture)
def _answer_strip(prompt, image, kwargs)                   # line 134
async def test_non_ink_wall_result_unchanged(synthetic_slots_definition, fake_vision_client)   # line 546-613 (to replace)
# tests/planogram_cycle/test_comparison_identity.py
CycleContext(reference_bank=[ReferenceImage(label="ref-0003", image=b"png", catalog_key="Unlisted model")])   # line 251-253
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| four `default_layout_profile()` edits | `resolve_layout_profile()` | `LayoutProfile(... reporting=ReportingPolicy(slot_presence=True))` | `plan.py:143-145`, `layout.py:154` |
| resolved profile | `CycleContext.layout` | `PlanogramCompliance` builds the context | `plan.py:331` |
| `CycleContext.layout.reporting` | `effective_reporting()` | `getattr(layout, "reporting", None)` | `comparison/definition.py:207-209` |
| policy | `compare_observations()` | `build_slot_presence(...) if policy.slot_presence else []` | `stages/compare.py:224-227` |
| `products_found` | `_assemble()` / handler | result key / `model_dump(mode="json")` | `plan.py:519`, `handlers/planogram_compliance.py:191-193` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot_pipelines.planogram.comparison.ReportingPolicy`~~ — `comparison/__init__.py` does **not** re-export `ReportingPolicy`, `effective_reporting` or `build_slot_presence`; import them from `comparison.definition` / `comparison.presence`.
- ~~`LayoutProfile(slot_presence=...)`~~ — `slot_presence` is **not** a top-level profile field; it lives under `reporting=ReportingPolicy(...)`.
- ~~`AbstractPlanogramType.reporting`~~ / ~~`<Type>.slot_presence`~~ — no class attribute; the only hook is `default_layout_profile()`.
- ~~`ComplianceResult.products_found`~~ — presence is on `ComparisonResult`, not on the per-shelf `ComplianceResult`.
- ~~`tests/planogram_cycle/conftest.py`~~ — does not exist; `fake_vision_client` comes from the package-level `packages/ai-parrot-pipelines/tests/conftest.py:159`.
- ~~`PlanogramConfig.reporting`~~ / ~~`planogram_config["reporting"]`~~ — the config-level override path is `planogram_config["layout_profile"]["reporting"]`, nothing else.
- ~~`SlotsDefinition.reporting`~~ — the definition override is `SlotsDefinition.meta["reporting"]`.
- ~~`ReferencePolicy` in `comparison.definition`~~ — it is in `planogram/layout.py` (used by `ink_wall.py:79`); not needed by this feature.
- ~~`docs/pipelines/planogram-compliance-cycle.md` "Reporting" section~~ — does not exist yet (M3 creates it); the file has no mention of `reporting`, `slot_presence` or `products_found` today.

### Edit Sites (Blueprint Anchors)

Verified against: `2a2d97a62`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py` | MODIFY | `            required_descriptor_fields=[],` (append `reporting=ReportingPolicy(slot_presence=True),` after it) | `:172` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py` | MODIFY | `from ..layout import LayoutProfile, resolve_layout_profile` (insert the `ReportingPolicy` import before it, keeping alphabetical order) | `:25` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` | MODIFY | `            required_descriptor_fields=[],` | `:116` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` | MODIFY | `from ..comparison.definition import SlotsDefinition` → `from ..comparison.definition import ReportingPolicy, SlotsDefinition` | `:15` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py` | MODIFY | `            descriptor_fields=["family", "colors", "pack"],` (append after the following `required_descriptor_fields=[],` line, `:102`) | `:101` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py` | MODIFY | `from ..layout import LayoutProfile` (insert the `ReportingPolicy` import before it) | `:23` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py` | MODIFY | `            min_usable_shapes=1,` (append `reporting=ReportingPolicy(slot_presence=True),` after it — last kwarg of the call) | `:81` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py` | MODIFY | `from ..layout import LayoutProfile` | `:23` | 1 |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` | MODIFY | `async def test_non_ink_wall_result_unchanged(` (rename + replace the `== []` assertions at `:600-601`) | `:544` | 1 |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_products_found_types.py` | CREATE | — | — | — |
| `docs/pipelines/planogram-compliance-cycle.md` | MODIFY | `## OCR and references` (insert the new section before it) | `:52` | 1 |
| `docs/pipelines/planogram-compliance-cycle.md` | MODIFY | `## Result keys` (extend the additive-keys sentence below it) | `:119` | 1 |
| `sdd/specs/planogram-ink-wall-slot-presence.spec.md` | MODIFY | `| \`test_non_ink_wall_result_unchanged\` |` (table row) | `:329` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Per-type behaviour is expressed through policy objects in `default_layout_profile()`
  (`ReferencePolicy`, `ReportingPolicy`, `CompletenessPolicy`); copy the `InkWall`
  pattern at `types/ink_wall.py:79-80`, omitting `product_label` (U1).
- Keep every other kwarg of the four `LayoutProfile(...)` calls byte-identical; add the
  kwarg as the last argument except where a trailing `completeness=` would normally go
  (none of the four has one).
- Tests build perceptions/identifications by hand exactly as
  `test_ink_wall.py:555-589` does, and drive `pipe._type_handler.compare(...)` +
  `pipe._assemble(...)` with `_ctx(definition)`; the reference case uses
  `CycleContext(reference_bank=[ReferenceImage(...)])` as `test_comparison_identity.py:251-253`.
- Validation inside the worktree: `PYTHONPATH=packages/ai-parrot-pipelines/src pytest
  packages/ai-parrot-pipelines/tests/planogram_cycle -q` (the shared `.venv` is editable
  against the main checkout — see `.claude/rules/worktree-management.md`).
- `black` (120 cols) + `ruff check` on touched files; Google-style docstrings on new tests.

### Known Risks / Gotchas
- **Reversal of FEAT-645.** The old test encoded "other types → `[]`" as a contract.
  Mitigation: the rename makes the reversal visible in the diff, the FEAT-645 spec row
  is annotated, and the per-row opt-outs are tested.
- **Tri-state `found`.** A slot whose only view is NOT_VISIBLE / NOT_ASSESSED / CONFLICT
  reports `found=None`, never `False` (`presence.py:35-39`). Consumers must not read
  `None` as "not found" — stated in the docs section.
- **Multi-facing positions** group by `(shelf_id, position or slot)`; `found` is True if
  any facing is found, `facings_found` counts (`presence.py:50-79`). Covered by the
  CLOSEOUT ×2 fixture.
- **`_ensure_layout` is not universal.** `ProductCounter` and `GraphicPanelDisplay` do
  not call `_ensure_layout` in `compare()`, but `ctx.layout` is always set by
  `PlanogramCompliance` (`plan.py:331`); tests that call `compare()` directly must pass a
  `CycleContext` whose `layout` is the resolved profile (`resolve_layout_profile(cls.default_layout_profile(), {}, config_name=...)`) or presence will fall back to the `False` default.
- **`reporting` override keys are strict** (`extra="forbid"`): a typo in
  `layout_profile.reporting` or `meta.reporting` raises at construction. Already the
  FEAT-645 behaviour; do not relax it.
- **`graphic_panel_display` / `product_counter` may be zone-only in production** (§8).
  If so, their opt-in is inert (`[]`), never wrong.
- **Active area.** `types/ink_wall.py` and `identification/` are moving (FEAT-646 and
  WIP commit `b12e115c3`). Do not touch them; branch from `origin/dev`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | no new dependencies (pydantic v2, pytest, pytest-asyncio already present) |

---

## 8. Open Questions

- [x] **Activation mechanism: policy default `True` (Option A) or per-type opt-in (Option B)?** — *Resolved in proposal (U2)*: Opción B, opt-in por tipo: `reporting=ReportingPolicy(slot_presence=True)` en el `default_layout_profile` de `endcap_backlit_multitier`, `product_on_shelves`, `product_counter` y `graphic_panel_display`; el default de `ReportingPolicy` queda en `False`.
- [x] **Switch `product_label` to `product` for non-ink-wall types?** — *Resolved in proposal (U1)*: No, solo `products_found`; las listas por estante siguen con `display_name`.
- [x] **Fixture for the positive test?** — *Resolved in proposal (U3)*: fixture sintético (`product_on_shelves` sintético con banco de referencias falso y `fake_vision_client`), sin datos de prod.
- [ ] **Do `graphic_panel_display` / `product_counter` have shelves-based definitions in production, or only zones?** — *Owner: Jesus Lara* (check `troc.planograms_configurations` with the `planogram-migrate` skill). Does not block implementation: a zone-only definition yields `[]` under the opt-in.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: skipped (exploration doc
> `sdd/proposals/products-found-endcap.proposal.md` has `status: review`, not `accepted`;
> `codex-cli 0.159.2` was available) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for this spec
  (`.claude/worktrees/feat-FEAT-648-products-found-endcap`, from `origin/dev`); the
  `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1: the profile tests assert `reporting.slot_presence is True` on the four
    classes and the compare-level tests rely on the resolved profile (`plan.py:143`).
  - M3 has no edge to M1 or M2 (prose only) — expected to run concurrently with M1.
- **Shared files**: none across modules. Within M1, the four type files are independent
  and may be split into parallel tasks; within M2, `test_ink_wall.py` (modify) and
  `test_products_found_types.py` (create) are independent.
- **Exclusive resources**: none (no build step, no lockfile, no migration).
- **Cross-feature dependencies**: FEAT-645 and FEAT-646 are already merged into `dev`.
  The WIP commit `b12e115c3` (neighbour spill) touches files this feature does not.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-10 | Jesus Lara | Initial draft from `sdd/proposals/products-found-endcap.proposal.md` |
