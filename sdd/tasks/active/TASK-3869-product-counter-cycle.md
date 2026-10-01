# TASK-3869: Migrate ProductCounter to the shared cycle

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3856, TASK-3859, TASK-3863
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 10** ("Describe product quantity by facings and background/information labels by
zones; use configured weights, no fixed three-element list") and the §2 defaults row
`product_counter`: *body and zone profiles, full image, threshold 1 — products represented as
facings; background and information label as zones; configured weights*. Today `ProductCounter`
(417 lines) is legacy-only: an LLM ROI call, macro detection, and a scorer that hardcodes
`_EXPECTED_ELEMENTS = ["product", "promotional_background", "information_label"]` with
`_DEFAULT_WEIGHTS` and reads `planogram_config["scoring_weights"]`. In the cycle, exact product
quantity is the number of expected facings in `slots_definition`, the background and the
information label are definition zones (new `ZoneKind` values from TASK-3860), and the weighting is
the shared product/text/visual weighting driven by the configured `ShelfConfig` weights.

---

## Scope

- Replace the whole legacy class with `default_layout_profile()` (classmethod), `perceive`,
  `identify`, `compare` delegating to the shared stages, plus private `_description()`.
- Delete `_DEFAULT_WEIGHTS` (:31-35), `_EXPECTED_ELEMENTS` (:38) and every legacy method.
- Define private provisional profiles: one product body profile and zone profiles (copied from the
  existing shelves candidates).
- Set the compatibility ClassVars the current orchestrator reads.
- CREATE `packages/ai-parrot-pipelines/tests/planogram_cycle/test_product_counter_cycle.py`.

**NOT in scope**: shared stages (TASK-3856/3859/3863); translating legacy
`planogram_config["scoring_weights"]` rows into `ShelfConfig` weights / facings / zones — that is
the converter (TASK-3877); `abstract.py` (TASK-3870); `plan.py` (TASK-3871); legacy test rewrites
in `test_neutral_shelf_types.py` / `test_planogram_types.py` (TASK-3876).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py` | MODIFY | Replace legacy class with thin cycle composition + body/zone default layout |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_product_counter_cycle.py` | CREATE | Offline cycle tests (facings, zones, configured weights, no fixed element list) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from PIL import Image                                        # this file :15
from .abstract import AbstractPlanogramType                  # this file :17
from parrot.models.detections import AisleConfig, PlanogramDescription   # detections.py:356, :364 (as in types/ink_wall.py:14)
from ..contracts import (ComparisonResult, CycleContext, IdentificationResult, IdentifyStrategy,
                         PerceptionResult, ShapeKind)        # contracts.py:295, :322, :137, :43, :86, :15
from ..perception.profiles import ShapeProfile               # perception/profiles.py:10
from ..perception.slots import AnchorRule                    # perception/slots.py:27
from typing import ClassVar, List, Sequence
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py (current, 417 lines)
_DEFAULT_WEIGHTS: Dict[str, float] = {"product": 1.0, "promotional_background": 0.5, "information_label": 0.3}  # :31-35 DELETE
_EXPECTED_ELEMENTS = ["product", "promotional_background", "information_label"]                               # :38   DELETE
class ProductCounter(AbstractPlanogramType):                               # :41   KEEP name + base
    def __init__(self, pipeline, config) -> None                           # :59   DELETE
    async def compute_roi(self, img)                                       # :66   DELETE
    async def detect_objects_roi(self, img, roi)                           # :175  DELETE
    async def detect_objects(self, img, roi, macro_objects)                # :271  DELETE
    def check_planogram_compliance(self, identified_products, planogram_description)  # :343-417 DELETE (reads scoring_weights :368)
# No cycle hook exists in this file today.

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
class AbstractPlanogramType(ABC):                                          # :36 (ClassVars :55-57 read by plan.py:220/:263/:248)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py
def _description(self) -> PlanogramDescription                            # :409-421 (fallback pattern)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py — how "configured weights" apply
def _weights(shelf, config: Optional[ShelfConfig], description, applies) -> Tuple[float, float, float]   # :218
    # uses ShelfConfig.product_weight / text_weight / visual_weight; ShelfConfig matched to ShelfDefinition by level (:326, :359)
# packages/ai-parrot/src/parrot/models/detections.py
class ShelfConfig(BaseModel): product_weight / text_weight / visual_weight: Optional[float]   # :302, :313-315
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py
class ShelfDefinition(BaseModel): shelf_id, shelf_number, level: Optional[str], facings      # :70 (level matches ShelfConfig.level)
class ZoneDefinition(BaseModel): zone_id, kind: ZoneKind, shelf_id, required: bool = True   # :79

# provisional values to copy (verified on dev) — product_on_shelves.py
# :287-299  ShapeProfile(name="product_body", kind=PRODUCT, min_width=0.06, max_width=0.30, min_height=0.08, max_height=0.45,
#                        min_aspect=0.5, max_aspect=2.5, polarity="edge", min_rectangularity=0.70, min_contrast_std=5.0)
# :324-337  ShapeProfile(name="backlit_zone", kind=ZONE, min_width=0.40, max_width=1.0, min_height=0.06, max_height=0.35,
#                        min_aspect=1.5, max_aspect=12.0, polarity="bright", min_rectangularity=0.80, min_contrast_std=5.0,
#                        thresholds=(200, 220, 240))
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3855 — planogram/layout.py
class LayoutProfile(BaseModel): shape_profiles; anchor_rule = SHAPE_IS_SLOT; identify_strategy = FULL_IMAGE;
    perception_mode = "cv"; min_usable_shapes: int = 1; descriptor_fields: list[str] = [];
    required_descriptor_fields: list[str] = []; ocr_targets; references; zone_selectors
# TASK-3856
async def perceive_image(image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult
# TASK-3859
async def identify_image(image: Image.Image, perception: PerceptionResult, ctx: CycleContext) -> IdentificationResult
# TASK-3863 (pure)
def compare_observations(perceptions, identifications, ctx: CycleContext, description: PlanogramDescription) -> ComparisonResult
# TASK-3860 — ZoneKind gains "graphic", "advertisement", "counter", "information_label"
# TASK-3854 — CycleContext.layout; IdentificationResult.rule_observations
```

### Does NOT Exist
- ~~`ProductCounter.perceive/identify/compare/default_layout_profile`~~ — added here.
- ~~a "count" rule kind~~ — spec §2: fixed counts are expected facings; the four rule kinds are unchanged.
- ~~`LayoutProfile.scoring_weights`~~ — weights are `ShelfConfig.product_weight/text_weight/visual_weight`.
- ~~`planogram_config["scoring_weights"]` support in the cycle~~ — accepted-but-ignored by the type; TASK-3877 converts it.

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
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_product_counter_cycle.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py#ProductCounter",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall._description",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py#_weights",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#ShelfDefinition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/profiles.py#ShapeProfile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#AnchorRule"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Thin composition identical to TASK-3867/3868, plus one product-kind profile. InkWall
(`types/ink_wall.py:163-166`, `:409-421`) shows the ClassVars and the description fallback.

### Key Constraints
- **No fixed element list** (M10): nothing in the file may name `product`/`promotional_background`/
  `information_label` as expected elements, and no weight table may be hardcoded. How many products,
  which zones exist and which are required come only from `ctx.definition`.
- **Products are facings**: the product body profile proposes product shapes; `shape_is_slot`
  turns each into a slot that the shared comparison registers against expected facings. Every
  expected facing stays in the denominator (spec §2 Stage 3) — do not special-case single products.
- **Configured weights**: the shared scorer already applies `ShelfConfig.product_weight/text_weight/
  visual_weight` (matched to `ShelfDefinition.level`, scoring.py:326/:359). The type must not
  re-weight. State in the class docstring that legacy `planogram_config["scoring_weights"]` is
  accepted-but-ignored and converted by TASK-3877.
- **Descriptor vocabulary**: set `descriptor_fields=["family", "colors", "pack"]` and
  `required_descriptor_fields=[]` — *why*: spec §2 says generic types must not inherit ink's mandatory
  `xl`; with no required fields the descriptor-signature step is disabled and identity relies on
  identifiers/aliases/references (spec §7 custom-descriptor note).
- **Provisional profiles**: `counter_product_body` = `product_body` verbatim; `counter_backlit_zone`
  = `backlit_zone` verbatim; `counter_panel_zone` = same bands, `polarity="edge"` (printed backdrop /
  label card). Fresh objects per call; no tuning; docstring says PROVISIONAL.
- **Compatibility ClassVars** until TASK-3871: `requires_slots_definition=True`, `uses_enhanced_image=False`,
  `min_usable_shapes=1`.
- No LLM or I/O in `compare` (AC8).

### Transitional breakage (accepted — do NOT fix here)
`tests/planogram_cycle/test_neutral_shelf_types.py`, `tests/test_planogram_types.py` (TASK-3876) and
`tests/planogram_cycle/test_legacy_run_orchestration.py` (TASK-3874) may fail until their owners land.
`tests/planogram_cycle/test_config_migration.py::test_check_row_legacy_type_is_ok` keeps passing
(it uses `MIGRATED_TYPES`, changed only by TASK-3877). Do not edit these files.

### References in Codebase
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py:45-72` — `_InlineExecutor`, `_ctx` helpers
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_comparison.py` (TASK-3863) — fixture patterns for `compare_observations`

---

## Implementation Blueprint

### Steps (in order)
1. Confirm the shared stage functions and `LayoutProfile` exist (grep as in TASK-3867 step 1) — *why*: they arrive via Depends-on.
2. Replace the whole file with the two blocks below — *why*: every current symbol is legacy-only.
3. Re-verify the copied numbers with `grep -n 'name="product_body"\|name="backlit_zone"' -A 12 .../types/product_on_shelves.py` — *why*: TASK-3865 may have moved them; the copy must stay verbatim.
4. Create the test file — *why*: no ProductCounter cycle test exists.
5. Run Validation Commands — *why*: AC16.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py` (MODIFY — replace whole file, block 1/2)
```python
# occurrences: 1 (verified: grep -Fxc 'class ProductCounter(AbstractPlanogramType):' packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py)
# REPLACE — lines 1-417 (whole file; class at :41)
"""ProductCounter — product-on-counter displays on the shared cycle (FEAT-612).

Products are expected facings; the promotional background and the information label are configured zones.
Scores use the shared product/text/visual weighting with the configured ``ShelfConfig`` weights.
"""

from __future__ import annotations

from typing import ClassVar, List, Sequence

from PIL import Image

from parrot.models.detections import AisleConfig, PlanogramDescription

from ..contracts import (
    ComparisonResult,
    CycleContext,
    IdentificationResult,
    IdentifyStrategy,
    PerceptionResult,
    ShapeKind,
)
from ..layout import LayoutProfile
from ..perception.profiles import ShapeProfile
from ..perception.slots import AnchorRule
from ..stages.compare import compare_observations
from ..stages.identify import identify_image
from ..stages.perceive import perceive_image
from .abstract import AbstractPlanogramType


def _counter_profiles() -> List[ShapeProfile]:
    """PROVISIONAL body + zone profiles copied from the shelves candidates (no accuracy claim).

    Returns:
        ``[counter_product_body, counter_backlit_zone, counter_panel_zone]`` as new objects on every call.
    """
    body = ShapeProfile(
        name="counter_product_body",
        kind=ShapeKind.PRODUCT.value,
        # FILL IN: remaining product_body fields VERBATIM (product_on_shelves.py dev :287-299) — spec §2
    )
    backlit = ShapeProfile(
        name="counter_backlit_zone",
        kind=ShapeKind.ZONE.value,
        # FILL IN: remaining backlit_zone fields VERBATIM (product_on_shelves.py dev :324-337) — spec §2
    )
    panel = backlit.model_copy(
        update={"name": "counter_panel_zone", "polarity": "edge", "thresholds": ShapeProfile.model_fields["thresholds"].default}
    )
    return [body, backlit, panel]
```
**Why this shape**: M10 names "body and zone profiles"; the edge-polarity zone lets a printed
backdrop or label card be proposed without a backlight. Factory → fresh objects.

### `product_counter.py` (MODIFY — block 2/2, appended after block 1)
```python
class ProductCounter(AbstractPlanogramType):
    """Counter/podium display: products as facings, background and information label as zones.

    Legacy ``planogram_config["scoring_weights"]`` is accepted and ignored; the config converter maps it to
    ``ShelfConfig`` weights, which the shared scorer applies.
    """

    requires_slots_definition: ClassVar[bool] = True  # plan.py:220 (until TASK-3871)
    uses_enhanced_image: ClassVar[bool] = False  # untouched full-resolution image (spec §2)
    min_usable_shapes: ClassVar[int] = 1  # plan.py:263 threshold (until TASK-3871); mirrors the layout

    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:
        """Body + zone profiles, shape-is-slot, full image, CV first, threshold 1 (spec §2 defaults table).

        Returns:
            A fresh profile with a neutral, non-mandatory descriptor vocabulary.
        """
        return LayoutProfile(
            shape_profiles=_counter_profiles(),
            anchor_rule=AnchorRule.SHAPE_IS_SLOT,
            fill_gaps=False,
            untagged_bottom_row=False,
            identify_strategy=IdentifyStrategy.FULL_IMAGE,
            perception_mode="cv",
            min_usable_shapes=1,
            descriptor_fields=["family", "colors", "pack"],
            required_descriptor_fields=[],
        )

    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
        """Shared CV perception (product bodies + zones) with ``ctx.layout``."""
        return await perceive_image(image, image_id, ctx)

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Shared OCR/vision identification plus neutral zone evidence."""
        return await identify_image(image, perception, ctx)

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Deterministic facing + zone comparison with configured weights; no provider call."""
        return compare_observations(perceptions, identifications, ctx, self._description())

    def _description(self) -> PlanogramDescription:
        """PlanogramDescription (ShelfConfig weights/thresholds); minimal fallback when shelves keys are absent."""
        # FILL IN: InkWall._description (ink_wall.py:409-421) verbatim; defaults "counter"; log prefix "ProductCounter"
        # — bounded by AC3/AC8. NOTE: the fallback has shelves=[] so default weights apply; configured weights need
        # planogram_config["shelves"][i]["level"] == ShelfDefinition.level.
```
**Why**: M10 skeleton signatures verbatim; weights stay in the shared scorer so the type cannot
diverge from the FEAT-574 normalized weighting.

### FILL IN checklist
- [ ] `_counter_profiles` — verbatim values; spec §2 provisional rule.
- [ ] `ProductCounter._description` — InkWall pattern; AC3/AC8.
- [ ] Test bodies — AC1/AC3/AC9.

---

## Acceptance Criteria

- [ ] `ProductCounter` has the four cycle members, no legacy method, no `_DEFAULT_WEIGHTS`, no `_EXPECTED_ELEMENTS`, and does not read `scoring_weights` (AC1, AC3).
- [ ] `default_layout_profile()` is fresh, holds exactly one `product` profile plus zone profiles, `required_descriptor_fields == []`, full image, `cv`, threshold 1 (AC3, AC4).
- [ ] A definition with N expected facings of one product scores each facing; observing fewer than N keeps the missing ones in the denominator (spec §2 Stage 3).
- [ ] An optional information-label zone that is absent does not fail the run; a required background zone judged absent in an inspected region fails (AC9).
- [ ] Changing only `ShelfConfig.product_weight`/`text_weight` in `planogram_config["shelves"]` changes the score of the same partial evidence (configured weights).
- [ ] `compare` works with a vision object that raises on every access (AC8).
- [ ] `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_product_counter_cycle.py -q` passes; ruff/black clean (AC16).
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_product_counter_cycle.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_product_counter_cycle.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_product_counter_cycle.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_product_counter_cycle.py
"""ProductCounter on the shared cycle: products as facings, zones, configured weights (FEAT-612, Module 10)."""

from __future__ import annotations

import inspect

import pytest

from parrot_pipelines.planogram.contracts import AssessmentStatus, CreditPolicy, CycleContext, EvidenceWeights
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types import product_counter as counter_module
from parrot_pipelines.planogram.types.product_counter import ProductCounter


class _RaisingVision:
    def __getattr__(self, name):
        raise AssertionError(f"compare touched vision.{name}")


def _definition(n_facings: int = 2) -> dict:
    """One counter shelf with n facings of generic product 'A' + background (required) + info label (optional)."""
    # FILL IN: {"version": 1, "shelves": [{"shelf_id": "counter", "shelf_number": 1, "level": "counter", "facings": [...]}],
    #           "zones": [{"zone_id": "background", "kind": "advertisement", "required": True},
    #                     {"zone_id": "info", "kind": "information_label", "required": False}]}
    ...


def test_default_layout_profile_body_and_zones():
    a, b = ProductCounter.default_layout_profile(), ProductCounter.default_layout_profile()
    assert a is not b
    kinds = [p.kind for p in a.shape_profiles]
    assert kinds.count("product") == 1 and "zone" in kinds and "fact_tag" not in kinds
    assert a.required_descriptor_fields == [] and a.min_usable_shapes == 1


def test_no_fixed_element_list_or_weights():
    source = inspect.getsource(counter_module)
    for literal in ("_DEFAULT_WEIGHTS", "_EXPECTED_ELEMENTS", "promotional_background", 'get("scoring_weights"', "check_planogram_compliance"):
        assert literal not in source
    for name in ("compute_roi", "detect_objects_roi", "detect_objects"):
        assert name not in ProductCounter.__dict__


async def test_hooks_delegate_to_shared_stages(monkeypatch):
    # FILL IN: monkeypatch counter_module.perceive_image / identify_image / compare_observations; assert same ctx
    ...


def test_all_facings_and_required_zone_observed_is_compliant():
    # FILL IN: 2 occupied slots identified "A" + background presence observation; ctx.vision=_RaisingVision();
    # assert overall_compliant True and detected_products == 2
    ...


def test_fewer_products_than_facings_stays_in_denominator():
    # FILL IN: _definition(3) with only 2 observed → one facing not resolved/empty; overall_compliance_score < 1.0
    ...


def test_optional_info_label_absent_does_not_fail():
    # FILL IN: no observation for "info" → no failed mandatory rule for "info"; compliance unaffected
    ...


def test_configured_weights_change_score():
    # FILL IN: same partial evidence, planogram_config shelves [{"level": "counter", "product_weight": 0.9, "text_weight": 0.1}]
    # vs [{"level": "counter", "product_weight": 0.5, "text_weight": 0.5}] with a failing text rule → scores differ
    ...


def test_type_registered():
    assert PlanogramCompliance._PLANOGRAM_TYPES["product_counter"] is ProductCounter
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug refactor-planogram-compliance --feature-id FEAT-612`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/refactor-planogram-compliance.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/refactor-planogram-compliance.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3869 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
