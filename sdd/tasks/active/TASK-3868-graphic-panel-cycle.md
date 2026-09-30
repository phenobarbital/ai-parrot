# TASK-3868: Migrate GraphicPanelDisplay to the shared cycle

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3856, TASK-3859, TASK-3863
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 9** ("Zone-only assessment with arbitrary configured zones; no product-count or
fact-tag path") and the §2 defaults row `graphic_panel_display`: *zone profiles, full image,
threshold 1 — graphics/text/illumination only; no product/fact-tag counting*.
`GraphicPanelDisplay` (836 lines) is today a pure legacy type: ROI via `_find_display_roi`,
per-zone LLM enrichment (`_enrich_zone`), its own illumination call
(`_check_illumination_from_roi`) and a per-shelf scoring loop in `check_planogram_compliance`
with a hardcoded default illumination penalty of 1.0. After the shared stages land
(TASK-3856/3859/3863) the type becomes a thin composition; zone presence, text and illumination
are judged only from neutral evidence and `slots_definition` zones + rule bindings.

---

## Scope

- Replace the whole legacy class body with `default_layout_profile()` (classmethod), `perceive`,
  `identify`, `compare` delegating to the shared stages, plus a private `_description()`.
- Delete module constants `_DEFAULT_ILLUMINATION_PENALTY` (:34) and `_ILLUMINATION_FEATURE_PREFIX`
  (:37) and every legacy method (list in the contract).
- Define provisional zone profiles privately (copied from the existing shelves `backlit_zone`
  candidate) — no product, box or fact-tag profiles (M9: no product/fact-tag counting).
- Set the compatibility ClassVars the current orchestrator reads.
- Rewrite `packages/ai-parrot/tests/test_graphic_panel_display.py` for the cycle; keep its
  `TestRegistration` class unchanged.

**NOT in scope**: shared stages (TASK-3856/3859/3863); `abstract.py` helper removal (TASK-3870);
orchestrator/result assembly (TASK-3871); converting legacy panel rows and emitting the legacy
1.0 illumination penalty as explicit `RuleBinding.params` (TASK-3877); rewriting
`test_neutral_panel_types.py` (TASK-3876).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py` | MODIFY | Replace the legacy class with the zone-only three-hook composition + default layout |
| `packages/ai-parrot/tests/test_graphic_panel_display.py` | MODIFY | Replace legacy zone/illumination/text tests with cycle tests; keep `TestRegistration` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from PIL import Image                                        # this file :16
from .abstract import AbstractPlanogramType                  # this file :18
from parrot.models.detections import AisleConfig, PlanogramDescription   # detections.py:356, :364 (as in types/ink_wall.py:14)
from ..contracts import (ComparisonResult, CycleContext, IdentificationResult, IdentifyStrategy,
                         PerceptionResult, ShapeKind)        # contracts.py:295, :322, :137, :43, :86, :15
from ..perception.profiles import ShapeProfile               # perception/profiles.py:10
from ..perception.slots import AnchorRule                    # perception/slots.py:27
from typing import ClassVar, List, Sequence
# test file (core package) — proxies verified:
from parrot.pipelines.planogram.types.graphic_panel_display import GraphicPanelDisplay   # proxy star-import, packages/ai-parrot/src/parrot/pipelines/planogram/types/graphic_panel_display.py:2
from parrot.pipelines.planogram.plan import PlanogramCompliance                          # proxy star-import, packages/ai-parrot/src/parrot/pipelines/planogram/plan.py:2
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py (current, 836 lines)
_DEFAULT_ILLUMINATION_PENALTY: float = 1.0                                 # :34   DELETE
_ILLUMINATION_FEATURE_PREFIX = "illumination_status:"                      # :37   DELETE
class GraphicPanelDisplay(AbstractPlanogramType):                          # :40   KEEP name + base
    def __init__(self, pipeline, config) -> None                           # :58   DELETE (pass-through)
    async def compute_roi(self, img)                                       # :65   DELETE
    async def detect_objects_roi(self, img, roi)                           # :92   DELETE
    async def detect_objects(self, img, roi, macro_objects)                # :175  DELETE
    def _generate_virtual_shelves(...)                                     # :398  DELETE
    def _assign_products_to_shelves(self, *args, **kwargs)                 # :407  DELETE
    def check_planogram_compliance(self, identified_products, planogram_description)  # :411 DELETE
    async def _find_display_roi(self, image, planogram_description)        # :552  DELETE
    async def _check_illumination_from_roi(...)                            # :648  DELETE
    async def _enrich_zone(...)                                            # :711  DELETE
    @staticmethod def _get_illumination_penalty(shelf_cfg) -> float        # :816-836 DELETE
# No cycle hook exists in this file today.

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
class AbstractPlanogramType(ABC):                                          # :36
    requires_slots_definition: ClassVar[bool] = False                      # :55 (plan.py:220)
    min_usable_shapes: ClassVar[int] = 0                                   # :56 (plan.py:263)
    uses_enhanced_image: ClassVar[bool] = True                             # :57 (plan.py:248)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py
def _description(self) -> PlanogramDescription                            # :409-421 (minimal-description fallback pattern)

# provisional zone values to copy — product_on_shelves.py:324-337 (verified on dev)
ShapeProfile(name="backlit_zone", kind=ShapeKind.ZONE.value, min_width=0.40, max_width=1.0, min_height=0.06,
             max_height=0.35, min_aspect=1.5, max_aspect=12.0, polarity="bright", min_rectangularity=0.80,
             min_contrast_std=5.0, thresholds=(200, 220, 240))

# packages/ai-parrot/tests/test_graphic_panel_display.py (current, 367 lines)
class TestZoneDetection:        # :107  REPLACE
class TestIlluminationCheck:    # :159  REPLACE
class TestTextRequirements:     # :218  REPLACE
class TestNoFactTagLogic:       # :318  REPLACE
class TestRegistration:         # :353-367  KEEP verbatim
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3855 — planogram/layout.py
class LayoutProfile(BaseModel): shape_profiles: list[ShapeProfile]; anchor_rule: AnchorRule = SHAPE_IS_SLOT;
    identify_strategy: IdentifyStrategy = FULL_IMAGE; perception_mode: Literal["cv","llm_detector"] = "cv";
    min_usable_shapes: int = 1; descriptor_fields: list[str] = []; ocr_targets = ["slot","tag","zone"]; zone_selectors: list[ZoneSelector] = []
# TASK-3856
async def perceive_image(image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult
# TASK-3859
async def identify_image(image: Image.Image, perception: PerceptionResult, ctx: CycleContext) -> IdentificationResult
# TASK-3863 (pure)
def compare_observations(perceptions, identifications, ctx: CycleContext, description: PlanogramDescription) -> ComparisonResult
# TASK-3854 — CycleContext.layout; IdentificationResult.rule_observations; RuleObservation(image_id, target_id, kind, value, assessed, source, evidence)
# TASK-3860 — ZoneKind adds "graphic", "advertisement", "counter", "information_label"; zone-only definitions legal
```

### Does NOT Exist
- ~~`GraphicPanelDisplay.perceive/identify/compare/default_layout_profile`~~ — added here.
- ~~a shared provisional-zone-profile module~~ — define privately in this file.
- ~~`LayoutProfile.illumination_penalty`~~ — penalties live in `RuleBinding.params`.
- ~~fact-tag or product profiles for this type~~ — M9 forbids product/fact-tag counting.
- ~~`GraphicPanelDisplay._find_display_roi` after this task~~ — removed; ROI is not part of the cycle.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/test_graphic_panel_display.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py#GraphicPanelDisplay",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall._description",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/profiles.py#ShapeProfile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#AnchorRule",
    "sym:packages/ai-parrot/tests/test_graphic_panel_display.py#TestRegistration"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Same thin composition as TASK-3867 (EndcapNoShelvesPromotional) and `types/ink_wall.py`
(ClassVars :163-166, `_description` :409-421). Every hook delegates to one shared stage; the only
type-owned data is the default layout.

### Key Constraints
- **Zone-only** (M9): `default_layout_profile()` contains only `ShapeKind.ZONE` profiles. No
  product/box/fact-tag profiles, no product counting, no brand-logo logic.
- **Arbitrary configured zones**: expected zones and their count come only from
  `ctx.definition.zones`; the old header/middle/bottom assumption must not survive in code.
- **Illumination/text only from evidence** (AC7): no `ask_to_image` / `_check_illumination` /
  `_vision_kwargs` use. Illumination state, text and visual features reach `compare` as
  `IdentificationResult.rule_observations`; evaluation is `compare_observations`.
- **Legacy penalty default 1.0 is NOT carried by the type**: the old `_DEFAULT_ILLUMINATION_PENALTY = 1.0`
  must be emitted as explicit `RuleBinding.params["penalty"]` by the converter (TASK-3877); state
  that in the class docstring so the loss of the constant is intentional and traceable.
- **Provisional profiles** (spec §2): copy `backlit_zone` verbatim as `panel_backlit_zone`; add one
  `panel_graphic_zone` with the same bands and `polarity="edge"` (non-illuminated printed graphics).
  Fresh objects per call. No tuning.
- **Compatibility ClassVars** until TASK-3871: `requires_slots_definition=True` (plan.py:220 loads
  the definition only then), `uses_enhanced_image=False` (untouched image, spec §2),
  `min_usable_shapes=1` (plan.py:263 threshold; mirrors the layout).
- The core test imports through the proxy `parrot.pipelines.planogram.types.graphic_panel_display`
  (a `*` re-export): private helpers such as `_zone_profiles` are NOT re-exported — import them from
  `parrot_pipelines.planogram.types.graphic_panel_display` when a test needs them.

### Transitional breakage (accepted — do NOT fix here)
`tests/planogram_cycle/test_neutral_panel_types.py` (TASK-3876),
`tests/test_endcap_no_shelves_promotional.py::test_graphic_panel_display_inherits_extract_illumination`
(rewritten by TASK-3867) and `tests/planogram_cycle/test_legacy_run_orchestration.py` (TASK-3874)
may fail until their owners land. Do not edit them or list them in Validation Commands.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py` — migrated type pattern
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py:45-72` — inline executor / ctx helpers
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_comparison.py` (TASK-3863) — zone-only fixtures

---

## Implementation Blueprint

### Steps (in order)
1. Confirm `perceive_image`, `identify_image`, `compare_observations`, `LayoutProfile` exist (`grep -n "def perceive_image\|def identify_image\|def compare_observations" packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/*.py`) — *why*: they arrive via Depends-on; if absent, STOP.
2. Replace the entire file with the two blocks below — *why*: all 836 lines are legacy-only; nothing survives.
3. Re-check `backlit_zone` values in source (`grep -n 'name="backlit_zone"' -A 12 .../types/product_on_shelves.py`) — *why*: the copy must be verbatim even if TASK-3865 moved it.
4. Rewrite the core test file except `TestRegistration` — *why*: the old tests exercise `check_planogram_compliance`, which is gone.
5. Run Validation Commands — *why*: AC16.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py` (MODIFY — replace whole file, block 1/2)
```python
# occurrences: 1 (verified: grep -Fxc 'class GraphicPanelDisplay(AbstractPlanogramType):' packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py)
# REPLACE — lines 1-836 (whole file; class at :40, last legacy helper ends :836)
"""GraphicPanelDisplay — zone-only graphic/signage panels on the shared cycle (FEAT-612).

Compliance is decided from configured zones only: their presence, text and illumination, observed as
neutral evidence during identification. There is no product counting and no fact-tag path.
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


def _zone_profiles() -> List[ShapeProfile]:
    """PROVISIONAL zone profiles (no accuracy claim): shelves ``backlit_zone`` copy + edge-polarity graphic variant.

    Returns:
        New profile objects on every call.
    """
    backlit = ShapeProfile(
        name="panel_backlit_zone",
        kind=ShapeKind.ZONE.value,
        # FILL IN: copy the remaining backlit_zone fields VERBATIM (product_on_shelves.py dev :324-337) — spec §2
    )
    graphic = backlit.model_copy(
        update={"name": "panel_graphic_zone", "polarity": "edge", "thresholds": ShapeProfile.model_fields["thresholds"].default}
    )
    return [backlit, graphic]
```
**Why this shape**: identical mechanism to TASK-3867 so reviewers see one pattern; names are
type-prefixed so perception diagnostics show which type's profile proposed a zone.

### `graphic_panel_display.py` (MODIFY — block 2/2, appended after block 1)
```python
class GraphicPanelDisplay(AbstractPlanogramType):
    """Zone-only graphic panel: presence, text and illumination of configured zones.

    The legacy per-type illumination penalty (1.0) is no longer a code default: migrated rows carry it as
    ``RuleBinding.params["penalty"]`` (emitted by the config converter).
    """

    requires_slots_definition: ClassVar[bool] = True  # plan.py:220 (until TASK-3871)
    uses_enhanced_image: ClassVar[bool] = False  # untouched full-resolution image (spec §2)
    min_usable_shapes: ClassVar[int] = 1  # plan.py:263 threshold (until TASK-3871); mirrors the layout

    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:
        """Zone profiles only, shape-is-slot, full image, CV first, threshold 1 (spec §2 defaults table).

        Returns:
            A fresh profile with no product/fact-tag profiles and no retailer data.
        """
        return LayoutProfile(
            shape_profiles=_zone_profiles(),
            anchor_rule=AnchorRule.SHAPE_IS_SLOT,
            fill_gaps=False,
            untagged_bottom_row=False,
            identify_strategy=IdentifyStrategy.FULL_IMAGE,
            perception_mode="cv",
            min_usable_shapes=1,
        )

    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
        """Shared CV perception (zones) with ``ctx.layout``."""
        return await perceive_image(image, image_id, ctx)

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Shared zone OCR/vision identification plus neutral text/illumination/presence evidence."""
        return await identify_image(image, perception, ctx)

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Deterministic zone-only comparison; no provider call."""
        return compare_observations(perceptions, identifications, ctx, self._description())

    def _description(self) -> PlanogramDescription:
        """PlanogramDescription for thresholds; minimal fallback when the config lacks shelves keys."""
        # FILL IN: InkWall._description (ink_wall.py:409-421) verbatim, category/aisle defaults "graphic_panel",
        # log prefix "GraphicPanelDisplay" — bounded by AC3/AC8
```
**Why**: M9 skeleton signatures; the docstring records the deliberate removal of the 1.0
penalty constant so TASK-3877 knows to emit it.

### `packages/ai-parrot/tests/test_graphic_panel_display.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -Fxc 'class TestZoneDetection:' packages/ai-parrot/tests/test_graphic_panel_display.py)
# REPLACE — lines 1-352 (module docstring, imports, mock helpers :25-104 and classes TestZoneDetection :107,
#           TestIlluminationCheck :159, TestTextRequirements :218, TestNoFactTagLogic :318); KEEP :353-367 (TestRegistration)
# New content: see Test Specification below.
```
**Why**: the helpers build `ShelfConfig`/`IdentifiedProduct` mocks for the removed legacy scorer;
`TestRegistration` still asserts the public registry contract and stays byte-identical.

### FILL IN checklist
- [ ] `_zone_profiles` — verbatim values; spec §2.
- [ ] `GraphicPanelDisplay._description` — InkWall pattern; AC3/AC8.
- [ ] Test bodies — AC1/AC7/AC9.

---

## Acceptance Criteria

- [ ] `GraphicPanelDisplay` has the four cycle members and none of the ten legacy methods/constants listed in the contract (AC1).
- [ ] `default_layout_profile()` is fresh per call, contains only `kind == "zone"` profiles, full image, `cv`, threshold 1 (AC3, AC4).
- [ ] A zone-only comparison reports `detected_products == 0` and no `position_results` (no product/fact-tag counting — M9).
- [ ] Illumination OFF vs a mandatory `required: "on"` binding fails; matching state passes; unknown state is inconclusive and non-compliant; a mandatory text requirement missing from observed text fails (AC7, AC9).
- [ ] `compare` works with a vision object that raises on every access (AC8).
- [ ] `TestRegistration` passes unchanged; `pytest packages/ai-parrot/tests/test_graphic_panel_display.py -q` passes; ruff/black clean (AC16).
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py packages/ai-parrot/tests/test_graphic_panel_display.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py packages/ai-parrot/tests/test_graphic_panel_display.py`

## Validation Commands

- `pytest packages/ai-parrot/tests/test_graphic_panel_display.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_graphic_panel_display.py  (TestRegistration :353-367 kept verbatim at the end)
"""GraphicPanelDisplay on the shared cycle: zone-only, evidence-based text and illumination (FEAT-612, Module 9)."""
from __future__ import annotations

import inspect
import logging
from unittest.mock import MagicMock

import pytest

from parrot.pipelines.planogram.types.graphic_panel_display import GraphicPanelDisplay
from parrot.pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.contracts import AssessmentStatus
from parrot_pipelines.planogram.types import graphic_panel_display as panel_module

LEGACY = ("compute_roi", "detect_objects_roi", "detect_objects", "check_planogram_compliance",
          "_generate_virtual_shelves", "_assign_products_to_shelves", "_find_display_roi",
          "_check_illumination_from_roi", "_enrich_zone", "_get_illumination_penalty")


class _RaisingVision:
    def __getattr__(self, name):
        raise AssertionError(f"compare touched vision.{name}")


class TestDefaultLayout:
    def test_zone_only_and_fresh(self):
        a, b = GraphicPanelDisplay.default_layout_profile(), GraphicPanelDisplay.default_layout_profile()
        assert a is not b
        assert {p.kind for p in a.shape_profiles} == {"zone"}
        assert a.min_usable_shapes == 1 and a.perception_mode == "cv" and a.identify_strategy.value == "full_image"


class TestNoLegacyContract:
    def test_legacy_members_removed(self):
        for name in LEGACY:
            assert name not in GraphicPanelDisplay.__dict__
        source = inspect.getsource(panel_module)
        assert "_DEFAULT_ILLUMINATION_PENALTY" not in source and "ask_to_image" not in source


class TestZoneEvidence:
    @pytest.mark.asyncio
    async def test_hooks_delegate_to_shared_stages(self, monkeypatch):
        # FILL IN: monkeypatch panel_module.perceive_image/identify_image/compare_observations; assert same ctx passed
        ...

    @pytest.mark.asyncio
    async def test_all_configured_zones_present_is_compliant(self):
        # FILL IN: definition with THREE arbitrary zones (kinds "graphic", "backlit", "advertisement") and mandatory
        # zone_present bindings; observations for all three; ctx.vision=_RaisingVision(); assert overall_compliant True,
        # detected_products == 0 and position_results == []
        ...

    @pytest.mark.asyncio
    async def test_missing_zone_only_fails_when_region_inspected(self):
        # FILL IN: one zone unobserved WITH an inspected-region observation (target "<image_id>:zone-region:<zone_id>",
        # value False, assessed True) → failed; without it → INCONCLUSIVE and not compliant
        ...


class TestIllumination:
    @pytest.mark.asyncio
    async def test_off_when_on_required_fails(self): ...   # FILL IN: binding params {"required": "on", "penalty": 1.0}
    @pytest.mark.asyncio
    async def test_matching_state_passes(self): ...        # FILL IN: observation "on" → rule assessed and passed
    @pytest.mark.asyncio
    async def test_unknown_state_is_inconclusive(self): ... # FILL IN: no observation → AssessmentStatus.INCONCLUSIVE


class TestTextRequirements:
    @pytest.mark.asyncio
    async def test_mandatory_text_missing_fails(self): ...  # FILL IN: text_requirements binding; observed zone text lacks it


# class TestRegistration:  ← keep the existing :353-367 block verbatim
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3868 refactor-planogram-compliance verified`
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
