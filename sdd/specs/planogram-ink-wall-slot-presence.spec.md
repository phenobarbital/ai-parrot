---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot-pipelines, ai-parrot]
tags: [planogram, ink-wall, compliance]
---

# Feature Specification: Planogram Ink Wall — model-based labels and slot presence

**Feature ID**: FEAT-645
**Date**: 2026-10-08
**Author**: Jesus Lara
**Status**: approved
**Target version**: ai-parrot-pipelines 1.4.0 (released in lockstep with the ai-parrot family)

> Exploration: `flowtask/sdd/proposals/planogram-ink-wall-changes.brainstorm.md` (Option A).
> Split into two specs by decision: this spec (ai-parrot, FEAT-645) and its consumer
> `flowtask/sdd/specs/planogram-ink-wall-changes.spec.md` (flowtask, FEAT-564), which
> depends on this one.

---

## 1. Motivation & Business Requirements

### Problem Statement

The `epson_inkwall_config` planogram (`planogram_type: ink_wall`, row in
`troc.planograms_configurations`) is defined slot by slot in `slots_definition`. Each
facing has a `product` (the model, e.g. `T212XL120-S`, `C2P04AN#140`), a `brand` and
`descriptors` (`sku`, `display_name`, `identifiers`, …). The compliance output does not
show, per slot, which model is on the shelf and which is not:

1. **Per-shelf `found_products` / `expected_products` are display names**, which are
   free text and cannot be joined against `product_model` / `sku`.
2. **`found_products` leaks brand-only identities.** `merge_positions` sets
   `identity = deciding.product or deciding.brand` (`scoring.py:212-213`). When the
   vision stage reads the brand but not the model, `project_compliance` lists the
   brand (`projection.py:110`). Real shelf-1 output is `…, "Epson", "Epson", "Epson",
   "Epson", "Epson"`.
3. **No slot-level presence list exists** in `ComparisonResult` or in the pipeline result.
4. **`sku` is silently dropped** when the definition loads: `Descriptors` has no `sku`
   field and ignores extra keys, and `_DESCRIPTOR_KEYS` omits it for the page1 layout.

### Goals
- G1: Under an opt-in reporting policy, label expected/found/missing products by the
  facing **model** (`FacingDefinition.product`). Never use a brand-only identity in
  `found_products`.
- G2: Produce a slot-level `products_found` list: one entry per occupied-expected slot
  (facings grouped by `(shelf_id, position)`), carrying `model`, `sku`, `display_name`,
  `brand`, `found` (true / false / null), `misplaced`, `status`, `confidence`,
  `facings`, `facings_found` and `observed`.
- G3: Keep `sku` from the slots definition (native and page1 layouts).
- G4: Configure the policy in two levels. The type's `LayoutProfile` sets the default,
  and `slots_definition.meta` overrides it per configuration row. Only `ink_wall` enables
  it by default.
- G5: Change nothing for any other planogram type. Scores, statuses and
  `overall_compliant` stay identical for **every** type, ink_wall included.

### Non-Goals (explicitly out of scope)
- Improving identification accuracy, e.g. constraining the LLM to the shelf's model/SKU
  vocabulary or matching SKUs from price-tag OCR. That was rejected for this feature
  (brainstorm Option D) and is a candidate follow-up.
- Any change to `_decide`, credits, `score_shelves`, `summarize` or `finalize_comparison`.
- Persisting results (flowtask's job, FEAT-564).
- Rebuilding presence outside the engine (brainstorm Option B, rejected).

---

## 2. Architectural Design

### Overview

A new **`ReportingPolicy`** (Pydantic, `extra="forbid"`) has three fields:
- `product_label: "display_name" | "product"` (default `"display_name"`)
- `slot_presence: bool` (default `False`)
- `misplaced_min_confidence: float` in [0, 1] (default `0.9`)

It lives in `comparison/definition.py`, because `layout.py` already imports from that
module and the reverse import would be a cycle. Configuration and wiring:
- **Default:** `LayoutProfile` gains `reporting: ReportingPolicy`.
  `InkWall.default_layout_profile()` sets `product_label="product"` and
  `slot_presence=True`. Every other type keeps the defaults, so its output is unchanged.
- **Overrides:** `planogram_config.layout_profile.reporting` already works through
  `resolve_layout_profile`. `slots_definition.meta["reporting"]` adds a per-row partial
  override that wins over the profile.
- **Validation:** `SlotsDefinition` validates `meta["reporting"]` at construction and
  raises `SlotsDefinitionError` on an unknown key or a bad value, so the run fails fast.
- **Effective policy:** `effective_reporting(layout, definition)` merges the profile
  (or defaults, when `ctx.layout` is `None`) with the meta override.
- **Wiring:** `compare_observations` resolves the policy once and passes it to
  `project_compliance(..., policy=...)`. When `slot_presence` is on, it also calls the
  new `build_slot_presence(positions, definition, policy)`. The result is attached as
  the additive `ComparisonResult.products_found`, which `plan.py::_assemble` exposes as
  the result key `"products_found"`.

**Per-facing presence** (applies to the `product` label and to slot presence):

| FacingStatus | `found` | `misplaced` |
|---|---|---|
| `MATCH`, `VARIANT_UNRESOLVED`, `INFERRED_PRESENT` | `true` | `false` |
| `MISPLACED`, deciding `raw_confidence >= misplaced_min_confidence` | `true` | `true` |
| `MISPLACED`, below the threshold or no deciding observation | `null` | `false` |
| `MISMATCH`, `EMPTY` | `false` | `false` |
| `NOT_VISIBLE`, `NOT_ASSESSED`, `CONFLICT`, `OCCUPIED_UNASSIGNED` | `null` | `false` |
| `EXPECTED_EMPTY`, `UNEXPECTED_OCCUPIED` (expected-empty facings) | excluded | — |

The **deciding observation** is `PositionResult.observations[0]` when the position has a
deciding view (the `merge_positions` contract). Its `ObservationRef.raw_confidence` is
the confidence. Without a deciding view the confidence is `None`, which counts as below
the threshold.

**Per-slot aggregation**, for facings sharing `(shelf_id, position)`:
- `found`: `true` if any facing is `true`. Otherwise `null` if any facing is `null`.
  Otherwise `false`.
- `facings_found`: the count of facings that are `true`.
- `misplaced`: `true` if the representative facing is misplaced.
- The **representative facing** is the first facing in definition order whose `found`
  equals the slot's `found`. Its `status`, `confidence` and `observed`
  (`PositionResult.identity`) describe the slot.

**Labels under `product_label="product"`** (`project_compliance`; per facing, the same
cardinality as today):
- `expected_products` = `[f.product for occupied-expected facings]`.
- `found_products` = `[f.product for facings whose presence is true]`, always the
  **expected** model, never `identity` and never a brand.
- `missing_products` = `[f.product for EMPTY facings]`, plus illumination pseudo-entries
  as today.
- `unexpected_products` stays the observed identity of `UNEXPECTED_OCCUPIED`
  expected-empty facings. No expected model exists there, so this is the only list
  that can carry an observed identity.

Under `"display_name"` (the default), every list is computed exactly as today, using
the current `_FOUND` set and `identity or _label(f)`.

### Component Diagram
```
compare_observations(perceptions, idents, ctx, description)          stages/compare.py:187
   ├─ merge_positions → positions                                   (unchanged)
   ├─ score_shelves  → shelves                                      (unchanged)
   ├─ summarize      → comparison                                   (unchanged)
   ├─ policy = effective_reporting(ctx.layout, definition)          NEW (definition.py)
   ├─ project_compliance(shelves, positions, definition, description, policy=policy)   MODIFIED
   ├─ products_found = build_slot_presence(positions, definition, policy) if policy.slot_presence   NEW (presence.py)
   └─ finalize_comparison(comparison(+products_found), results)     (unchanged)
InkWall.compare → model_copy(update={"position_results": …})        keeps products_found
plan._assemble → result["products_found"]                           MODIFIED (additive key)
handlers/planogram_compliance.py → serialisable["products_found"]   MODIFIED (additive)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `comparison/definition.py` `Descriptors`, `_DESCRIPTOR_KEYS`, `SlotsDefinition` | modifies | `sku`; `ReportingPolicy`; `meta["reporting"]` validation; `effective_reporting` |
| `layout.py` `LayoutProfile` (`extra="forbid"`) | modifies | declares `reporting: ReportingPolicy` |
| `comparison/projection.py` `project_compliance` | modifies | keyword-only `policy`; model labels under `product` |
| `comparison/presence.py` | new | `facing_presence`, `build_slot_presence` |
| `contracts.py` `ComparisonResult` | extends | `SlotPresence` model; `products_found: List[SlotPresence] = []` |
| `stages/compare.py` `compare_observations` | modifies | resolves policy, passes it on, attaches presence |
| `types/ink_wall.py` `InkWall.default_layout_profile` | modifies | enables `product` + `slot_presence` |
| `plan.py` `_assemble` | extends | additive key `"products_found"` |
| `handlers/planogram_compliance.py` | extends | additive `products_found` in the job JSON |
| `parrot/models/compliance.py` `ComplianceResult` | unchanged | lists stay `List[str]` |

### Data Models
```python
class ReportingPolicy(BaseModel):              # comparison/definition.py
    model_config = ConfigDict(extra="forbid")
    product_label: Literal["display_name", "product"] = "display_name"
    slot_presence: bool = False
    misplaced_min_confidence: float = Field(default=0.9, ge=0.0, le=1.0)

class SlotPresence(BaseModel):                 # contracts.py
    shelf_id: str
    shelf_level: Optional[str] = None
    slot: int
    position: Optional[int] = None
    facing_ids: List[str]
    model: str
    sku: Optional[str] = None
    brand: Optional[str] = None
    display_name: Optional[str] = None
    found: Optional[bool] = None
    misplaced: bool = False
    status: FacingStatus
    confidence: Optional[float] = None
    facings: int = 1
    facings_found: int = 0
    observed: Optional[str] = None
```

### New Public Interfaces
- `ReportingPolicy`, `effective_reporting()` (definition.py)
- `SlotPresence`, `ComparisonResult.products_found` (contracts.py)
- `facing_presence()`, `build_slot_presence()` (comparison/presence.py)
- `project_compliance(..., *, policy=None)`
- pipeline result key `"products_found"`

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Descriptors.sku | yes | `sku: Optional[str]`, int coerced to str; `"sku"` appended to `_DESCRIPTOR_KEYS` | — |
| M2: ReportingPolicy + override | yes | model and `effective_reporting` below; `SlotsDefinitionError` on a bad meta | — |
| M3: LayoutProfile.reporting + InkWall default | yes | field `reporting: ReportingPolicy = Field(default_factory=ReportingPolicy)` | — |
| M4: SlotPresence + presence builder | yes | truth table and aggregation in §2 | — |
| M5: project_compliance policy | yes | label rules in §2; default path byte-identical | — |
| M6: wiring (compare, plan, handler) | yes | additive only | — |

### Module 1: `Descriptors.sku`
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py`
- **Responsibility**: keep `sku` from both layouts and coerce numeric SKUs to `str`.
- **Interface Skeleton**:
  ```python
  # modifies comparison/definition.py:28 and :45
  _DESCRIPTOR_KEYS = (..., "attributes", "sku")      # verified: definition.py:28-38
  class Descriptors(BaseModel):                       # verified: definition.py:45
      sku: Optional[str] = None
      @field_validator("sku", mode="before")
      @classmethod
      def _sku_to_str(cls, value: Any) -> Optional[str]:
          """int/str → stripped str; blank → None."""
  ```

### Module 2: `ReportingPolicy` and the per-definition override
- **Path**: `…/comparison/definition.py`
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  REPORTING_META_KEY = "reporting"
  class ReportingPolicy(BaseModel):
      """How compliance results are labelled and whether slot presence is produced."""
  class SlotsDefinition(BaseModel):                   # verified: definition.py:131 (meta: Dict[str, Any] at :135)
      @model_validator(mode="after")
      def _check_reporting_meta(self) -> "SlotsDefinition":
          """meta['reporting'] must be a dict valid for ReportingPolicy (partial); raises SlotsDefinitionError."""
  def effective_reporting(layout: Optional[Any], definition: Optional[SlotsDefinition]) -> ReportingPolicy:
      """layout.reporting (or defaults) updated with the keys explicitly set in definition.meta['reporting']."""
  ```
  Note: if `SlotsDefinition` already has an `after` validator, add the check to it rather
  than registering a second validator. Read the class first.

### Module 3: `LayoutProfile.reporting` and the ink-wall default
- **Paths**: `…/planogram/layout.py`, `…/planogram/types/ink_wall.py`
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # layout.py:66 (extra="forbid" at :69)
  class LayoutProfile(BaseModel):
      reporting: ReportingPolicy = Field(default_factory=ReportingPolicy)
  # types/ink_wall.py:64-77
  def default_layout_profile(cls) -> LayoutProfile:
      # adds reporting=ReportingPolicy(product_label="product", slot_presence=True)
  ```

### Module 4: `SlotPresence` and the presence builder
- **Paths**: `…/planogram/contracts.py` (model + `ComparisonResult.products_found`), `…/planogram/comparison/presence.py` (new)
- **Depends on**: M1, M2
- **Interface Skeleton**:
  ```python
  # contracts.py — next to PositionResult (:218); ComparisonResult at :325
  class SlotPresence(BaseModel): ...                 # fields in §2 Data Models
  class ComparisonResult(BaseModel):
      products_found: List[SlotPresence] = Field(default_factory=list)

  # comparison/presence.py (new)
  def facing_presence(position: Optional[PositionResult], policy: ReportingPolicy
                      ) -> Tuple[Optional[bool], bool, Optional[float]]:
      """(found, misplaced, confidence) for one facing per the §2 truth table; None position → (None, False, None)."""
  def build_slot_presence(positions: Sequence[PositionResult], definition: SlotsDefinition,
                          policy: ReportingPolicy) -> List[SlotPresence]:
      """One SlotPresence per occupied-expected (shelf_id, position) group, definition order."""
  ```
  A facing with `position is None` is grouped by `(shelf_id, slot)` as the fallback key.
  The `shelf_level` comes from `ShelfDefinition.level`.

### Module 5: Label policy in `project_compliance`
- **Path**: `…/comparison/projection.py`
- **Depends on**: M2, M4 (`facing_presence`)
- **Interface Skeleton**:
  ```python
  def project_compliance(shelf_scores: Sequence[ShelfScore], positions: Sequence[PositionResult],
                         definition: SlotsDefinition, description: PlanogramDescription,
                         *, policy: Optional[ReportingPolicy] = None) -> List[ComplianceResult]:  # verified: projection.py:55
      """policy None or product_label='display_name' → current behaviour, byte-identical.
      product_label='product' → model labels per spec §2; status/score/assessment unchanged."""
  ```

### Module 6: Wiring
- **Paths**: `…/stages/compare.py:187-222`, `…/plan.py:461` (`_assemble`), `…/handlers/planogram_compliance.py:~179`
- **Depends on**: M3, M4, M5
- **Contract**: `compare_observations` computes `policy = effective_reporting(ctx.layout, definition)`,
  passes `policy=policy` to `project_compliance`, and when `policy.slot_presence` is on
  sets `products_found` on the comparison before `finalize_comparison`. The `_assemble`
  result adds `"products_found": comparison.products_found`. The handler adds
  `serialisable["products_found"] = [p.model_dump(mode="json") for p in result.get("products_found", [])]`.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_descriptor_sku_kept_native_and_page1` | M1 | native and page1 layouts keep `sku`; int `6347569` → `"6347569"`; missing → None |
| `test_reporting_meta_override_validated` | M2 | unknown key / `product_label="x"` / threshold 1.5 raise `SlotsDefinitionError` |
| `test_effective_reporting_precedence` | M2 | defaults < layout.reporting < meta; `layout=None` → defaults |
| `test_layout_profile_reporting_override` | M3 | `planogram_config.layout_profile.reporting.slot_presence=false` turns presence off for ink_wall |
| `test_ink_wall_default_reporting` | M3 | `InkWall.default_layout_profile().reporting` is `product` + `slot_presence` |
| `test_other_types_default_reporting` | M3 | every other registered type keeps `display_name`, presence off |
| `test_facing_presence_truth_table` | M4 | every `FacingStatus` row of §2, both sides of the 0.9 threshold, no deciding view |
| `test_slot_presence_grouping_closeout` | M4 | 3 facings at position 97 → one entry, `facings=3`, `facings_found` counted, found if one is true |
| `test_slot_presence_mixed_unknown_and_empty` | M4 | {EMPTY, NOT_VISIBLE} → `found=None`; {EMPTY, EMPTY} → `False` |
| `test_slot_presence_mismatch_observed` | M4 | MISMATCH → `found=False`, `observed` = identity |
| `test_slot_presence_excludes_expected_empty` | M4 | expected-empty facings produce no entry |
| `test_project_compliance_product_labels` | M5 | expected/found/missing are models; brand identity never in found; VARIANT_UNRESOLVED → expected model |
| `test_project_compliance_default_unchanged` | M5 | existing `test_scoring_projection.py` assertions (e.g. `found_products == ["Product top 1"]`, :176) pass unmodified |
| `test_scores_identical_across_policies` | M5 | status, score, assessment identical between `display_name` and `product` |

### Integration Tests
| Test | Description |
|---|---|
| `test_ink_wall_products_found_end_to_end` | `test_ink_wall_example.py`-style run with a fake vision client: result dict has `products_found`, per-shelf lists are models, no brand-only entries |
| `test_non_ink_wall_result_unchanged` | an endcap / product_on_shelves fixture run: `products_found == []`, lists identical to before |
| `test_handler_serialises_products_found` | `handlers/planogram_compliance.py` job JSON contains `products_found` |

### Test Data / Fixtures
- A slots definition built from the user-provided `epson_inkwall_config` excerpt
  (shelf_1 slots 10–12, shelf_5 slot 4 `951CMY/950XL` without `sku`, shelf_5 position
  97 CLOSEOUT ×3), in native layout.
- Hand-built `PositionResult` lists covering every `FacingStatus`, with
  `observations[0].raw_confidence` of 0.95 and 0.5.

---

## 5. Acceptance Criteria

- [ ] `Descriptors.sku` exists; `sku` survives native and page1 loading; numeric SKUs become `str`.
- [ ] `ReportingPolicy` exists; `LayoutProfile.reporting` defaults to `display_name` / presence off / 0.9.
- [ ] `InkWall.default_layout_profile()` enables `product_label="product"` and `slot_presence=True`; **no other type** enables either.
- [ ] `slots_definition.meta["reporting"]` overrides the profile key by key; an invalid value raises `SlotsDefinitionError` at definition construction.
- [ ] Under `product`, `found_products` contains only expected models and never a bare brand; `expected_products` / `missing_products` are models.
- [ ] VARIANT_UNRESOLVED and INFERRED_PRESENT count as found and are labelled with the expected model.
- [ ] MISPLACED is found/misplaced only when the deciding `raw_confidence >= 0.9`; otherwise `found=None`, `misplaced=False`.
- [ ] NOT_VISIBLE / NOT_ASSESSED / CONFLICT / OCCUPIED_UNASSIGNED → `found=None`; MISMATCH / EMPTY → `found=False` with `observed` set.
- [ ] `products_found` has exactly one entry per occupied-expected `(shelf_id, position)`; a slot is found when at least one facing is found; `facings_found` counts them.
- [ ] Scores, `compliance_status`, `assessment`, `overall_compliant` are identical under both policies (asserted by a test).
- [ ] With the default policy, all existing `tests/planogram_cycle/` tests pass **unmodified**.
- [ ] The pipeline result dict and the aiohttp handler expose `products_found` (empty list when presence is off).
- [ ] `pytest packages/ai-parrot-pipelines/tests/planogram_cycle -q` passes; `ruff` clean on touched files.

---

## 6. Codebase Contract

> All paths relative to `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/` unless stated. Re-verified 2026-10-08 on `dev` (`bebd26973`).

### Verified Imports
```python
from parrot.models.compliance import ComplianceResult, ComplianceStatus, ShelfAssessment  # projection.py:8
from parrot.models.detections import PlanogramDescription                                   # projection.py:9
from parrot_pipelines.planogram.comparison.definition import FacingDefinition, SlotsDefinition  # projection.py:11
from parrot_pipelines.planogram.contracts import (AssessmentStatus, ComparisonResult, FacingStatus,
                                                  PositionResult, ShelfScore)                # projection.py:12-18
from parrot_pipelines.planogram.comparison.projection import finalize_comparison, project_compliance  # stages/compare.py:11
```
`layout.py` imports `SlotsDefinition` (used by `validate_zone_selectors`, layout.py:205), so
`ReportingPolicy` must live in `definition.py`, not `layout.py`.

### Existing Class Signatures
```python
# comparison/definition.py
_DESCRIPTOR_KEYS: Tuple[str, ...] = ("display_name","family","xl","colors","pack","identifiers","aliases","price","attributes")  # :28
class SlotsDefinitionError(ValueError)                                       # :41
class Descriptors(BaseModel):                                                # :45 (no model_config → extra ignored)
    display_name: Optional[str]; family; xl; colors; pack; identifiers; aliases; price; attributes  # :48-56
    def _no_typed_collision(self) -> "Descriptors"                           # :58-65 (attributes may not shadow typed fields)
class FacingDefinition(BaseModel):                                           # :78
    facing_id: str; shelf_id: str; slot: int; product: Optional[str]; brand: Optional[str]
    facings: int = 1; facing_index: int = 1; position: Optional[int]; descriptors: Descriptors
    expected_occupancy: Literal["occupied", "empty"] = "occupied"            # :81-90
class ShelfDefinition(BaseModel): shelf_id: str; shelf_number: int; level: Optional[str]; ordered: bool  # :100-108
class SlotsDefinition(BaseModel):                                            # :131
    version: str = "1"; meta: Dict[str, Any]; shelves: List[ShelfDefinition]; zones: List[ZoneDefinition]  # :134-137
    def all_facings(self) -> List[FacingDefinition]                          # :139
def _normalise_page1(data: Dict[str, Any]) -> Dict[str, Any]                 # :144 (descriptors from _DESCRIPTOR_KEYS at :168)

# contracts.py
class FacingStatus(str, Enum): MATCH, MISPLACED, VARIANT_UNRESOLVED, MISMATCH, EMPTY, INFERRED_PRESENT,
    OCCUPIED_UNASSIGNED, CONFLICT, NOT_ASSESSED, NOT_VISIBLE, EXPECTED_EMPTY, UNEXPECTED_OCCUPIED  # :170-184
class ObservationRef(BaseModel): image_id: str; shape_id: str; source; raw_confidence: float = 0.0
    product: Optional[str]; occupancy: str                                   # :195-203
class PositionResult(BaseModel): facing_id: str; shelf_id: str; status: FacingStatus; strict_credit; lenient_credit
    identity: Optional[str]; observations: List[ObservationRef]; notes: List[str]  # :218-228
class ComparisonResult(BaseModel): compliance_results; position_results; shelf_scores; overall_compliance_score
    strict_compliance_score; overall_compliant; coverage; detected_products; definition_coverage
    evidence_quality; assessment_status; errors                              # :325-339
class CycleContext(BaseModel): definition: Optional[Any]  # :360;  layout: Any = None  # :365

# comparison/scoring.py
def merge_positions(definition, registrations, identifications, policy) -> List[PositionResult]  # :160
    # deciding observation is FIRST in PositionResult.observations (docstring); identity = deciding.product or deciding.brand (:212-213)

# comparison/projection.py
_FOUND = {MATCH, MISPLACED, MISMATCH, VARIANT_UNRESOLVED, INFERRED_PRESENT}   # :32-38
def _label(facing: FacingDefinition) -> str                                  # :42-44
def project_compliance(shelf_scores, positions, definition, description) -> List[ComplianceResult]  # :55
    # missing :108, found :110, ComplianceResult(...) :137-147
def finalize_comparison(comparison, compliance_results) -> ComparisonResult  # :152

# layout.py
class LayoutProfile(BaseModel): model_config = ConfigDict(extra="forbid")    # :66-69 (fields :71-95)
def resolve_layout_profile(defaults: LayoutProfile, config: dict[str, Any], *, config_name: str) -> LayoutProfile  # :150
    # deep-merges config[LAYOUT_KEY] over defaults.model_dump() and validates

# stages/compare.py
def compare_observations(perceptions, identifications, ctx: CycleContext, description) -> ComparisonResult  # :187-222

# types/ink_wall.py
class InkWall(AbstractPlanogramType)                                         # :55
    def default_layout_profile(cls) -> LayoutProfile                         # :64-77
    def _ensure_layout(self, ctx) -> LayoutProfile                           # :79-87 (sets ctx.layout)
    async def compare(self, perceptions, identifications, ctx) -> ComparisonResult  # :117-133 (model_copy only updates position_results)

# plan.py
def _assemble(self, perceptions, identifications, comparison, renders, ctx) -> Dict[str, Any]  # :461-498

# packages/ai-parrot/src/parrot/models/compliance.py
class ComplianceResult(BaseModel): expected_products/found_products/missing_products/unexpected_products: List[str]  # :52-70
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `effective_reporting` | `CycleContext.layout`, `SlotsDefinition.meta` | call in `compare_observations` | contracts.py:365, definition.py:135 |
| `project_compliance(policy=)` | `compare_observations` | keyword arg | stages/compare.py:222 |
| `build_slot_presence` | `positions`, `definition` | call in `compare_observations` | stages/compare.py:215 |
| `ComparisonResult.products_found` | `plan._assemble` | result key | plan.py:461 |
| ink_wall default | `resolve_layout_profile` | `default_layout_profile()` | ink_wall.py:64, layout.py:150 |

### Does NOT Exist (Anti-Hallucination)
- ~~`Descriptors.sku`~~, ~~`ReportingPolicy`~~, ~~`effective_reporting`~~, ~~`SlotPresence`~~, ~~`ComparisonResult.products_found`~~, ~~`comparison/presence.py`~~, ~~`LayoutProfile.reporting`~~ — all created by this spec.
- ~~A confidence gate in `_decide`~~: MISPLACED is returned without any confidence check (scoring.py:120-121). This spec gates **reporting only**, never the status.
- ~~`ComplianceResult.found_models` / `expected_models`~~ — not fields; none are added.
- ~~result key `"products_found"`~~ — not in `_assemble` today.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Pydantic v2, `extra="forbid"` for the policy (same as `LayoutProfile`).
- Pure functions in `comparison/` with no I/O, matching `projection.py`.
- Additive output keys only, as with FEAT-574's additive keys in `_assemble`.
- `logger.debug` for policy resolution, as `resolve_layout_profile` does.

### Known Risks / Gotchas
- **Attribute collision:** a stored definition with `descriptors.attributes.sku` now fails
  `_no_typed_collision`. Mitigation: before merging, grep the `slots_definition` rows of
  `troc.planograms_configurations` for `"attributes": {"sku"` (ops check).
- **InkWall.compare model_copy:** it updates only `position_results`, so `products_found`
  survives. Note that presence is computed from positions **before** `_price_notes`.
  That is fine because price notes change only `notes`.
- **`ctx.layout` may be `None`** for types or orchestrators that do not resolve the
  layout; `effective_reporting` then falls back to defaults plus the meta override.
- **Per-facing cardinality:** under `product`, `expected_products` / `found_products`
  keep one entry per facing (CLOSEOUT ×3 appears 3 times), as today. Slot-level
  dedup exists only in `products_found`.
- **Multi-facing edge case:** a slot with {EMPTY, NOT_VISIBLE} reports `found=None`,
  never `false`, because unknown visibility must not be reported as absent.
- **Release ordering:** ai-parrot is released in lockstep. FEAT-564 (flowtask) degrades
  gracefully when the key is missing, so there is no hard pin coupling.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | v2 (already) | models / validators |

---

## Worktree Strategy

- **Isolation**: `per-spec` — one worktree in `ai-parrot` from `dev`; M1→M6 run sequentially (same files).
- **Cross-feature dependencies**: FEAT-564 (flowtask) consumes this spec's result key and is built against a mocked result, so it does not block. Check in-flight ai-parrot work on `planogram/comparison/` (recent: FEAT-612, fact-tag-rule) before starting.

---

## 8. Open Questions

- [x] Flow type / base branch — *Resolved in brainstorm*: feature → dev.
- [x] Identifier — *Resolved in brainstorm*: both; entries carry `model` and `sku`; per-shelf lists use the model.
- [x] Unresolved variants — *Resolved in brainstorm*: counted as found and labelled with the slot's expected model.
- [x] Where the change lives — *Resolved in brainstorm*: ai-parrot (semantics) + flowtask (exposure); split into FEAT-645 + FEAT-564.
- [x] Coverage — *Resolved in brainstorm*: every expected slot, with a `found` flag and status.
- [x] MISMATCH — *Resolved in brainstorm*: `found: false`, observed model/brand in `observed`.
- [x] Per-shelf lists — *Resolved in brainstorm*: expected/found switch to the model.
- [x] Multi-facing — *Resolved in brainstorm*: one entry per slot/position with `facings` / `facings_found`.
- [x] Scope — *Resolved in brainstorm*: opt-in by configuration, enabled by default only for `ink_wall`.
- [x] Policy location — *Resolved in brainstorm*: both; `LayoutProfile` default, overridden by `slots_definition.meta`.
- [x] MISPLACED — *Resolved in brainstorm*: `found: true, misplaced: true` only at high confidence; below it `found: null`.
- [x] Unknown visibility — *Resolved in brainstorm*: `found: null`.
- [x] MISPLACED threshold — *Resolved in brainstorm*: 0.9 on the deciding observation.
- [x] Multi-facing rule — *Resolved in brainstorm*: found if at least one facing is found.
- [x] Separate column — *Resolved in brainstorm*: yes (flowtask side, FEAT-564).
- [x] missing/unexpected — *Resolved in brainstorm*: also by model under `product`. `unexpected_products` keeps the observed identity because expected-empty positions have no expected model.

---

## 9. Design Research Cross-Check

> Status: skipped (exploration doc status is `exploration`, not `accepted`).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-08 | Jesus Lara | Initial draft from flowtask brainstorm `planogram-ink-wall-changes` (Option A) |
