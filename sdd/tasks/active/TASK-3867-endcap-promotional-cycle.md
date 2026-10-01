# TASK-3867: Migrate EndcapNoShelvesPromotional to the shared cycle

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3856, TASK-3859, TASK-3863
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 8** and the §2 "Type defaults and genuinely specific behavior" table row
`endcap_no_shelves_promotional`: *zone profiles, full image, threshold 1 — configured promotional
zones, text and illumination; no invented product tiers*. Today
`EndcapNoShelvesPromotional` still implements only the legacy ROI contract (`compute_roi`,
`detect_objects_roi`, `detect_objects`, `check_planogram_compliance`), hardcodes two expected
elements (`_EXPECTED_ELEMENTS = ["backlit_panel", "lower_poster"]`) and a fallback shelves config,
and makes its own LLM calls through `self.pipeline.llm`. After TASK-3856 (shared perception),
TASK-3859 (shared identify + neutral rule evidence) and TASK-3863 (evidence-only compare) land,
this type becomes a thin composition of those three shared stages plus a default `LayoutProfile`.
TASK-3870 then makes the three-hook contract strict, so this migration must be complete.

---

## Scope

- Replace the whole legacy class body with the four cycle members: `default_layout_profile()`
  (classmethod), `perceive`, `identify`, `compare`.
- Delete the legacy module constant `_EXPECTED_ELEMENTS` and every legacy method
  (`__init__` pass-through, `compute_roi`, `detect_objects_roi`, `detect_objects`,
  `_generate_virtual_shelves`, `_assign_products_to_shelves`, `check_planogram_compliance`).
- Define provisional zone `ShapeProfile`s at module level (copied from the existing shelves
  candidate, see Implementation Notes) and return them from `default_layout_profile()`.
- Set the compatibility ClassVars the current orchestrator still reads
  (`requires_slots_definition`, `uses_enhanced_image`, `min_usable_shapes`).
- Rewrite `packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py` to pin the
  cycle behavior (spec §4 "type behavior" row; AC1, AC3, AC7, AC9).

**NOT in scope**: the shared stages themselves (TASK-3856/3859/3863); the strict abstract
contract and removal of `_extract_illumination_state` / `_check_illumination` /
`_vision_kwargs` / `_DEFAULT_ILLUMINATION_PENALTY` from `abstract.py` (TASK-3870); the
orchestrator/fallback/result assembly (TASK-3871); config conversion of legacy promotional rows
(TASK-3877); rewriting `test_neutral_panel_types.py` / `test_neutral_shelf_types.py` /
`test_planogram_types.py` (TASK-3876); editing `abstract.py` or `plan.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py` | MODIFY | Replace the legacy class with the thin three-hook cycle composition + default layout |
| `packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py` | MODIFY | Replace legacy `check_planogram_compliance` tests with cycle tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from PIL import Image                                        # already in this file (:16)
from .abstract import AbstractPlanogramType                  # this file :18 (DROP the `_DEFAULT_ILLUMINATION_PENALTY` name from that line)
from parrot.models.detections import AisleConfig, PlanogramDescription   # detections.py:356, :364; same import used by types/ink_wall.py:14
from ..contracts import (                                    # planogram/contracts.py
    ComparisonResult,      # :295
    CycleContext,          # :322
    IdentificationResult,  # :137
    IdentifyStrategy,      # :43  (FULL_IMAGE, STRIPS; SLOTS added by TASK-3854)
    PerceptionResult,      # :86
    ShapeKind,             # :15  (ZONE = "zone")
)
from ..perception.profiles import ShapeProfile               # perception/profiles.py:10
from ..perception.slots import AnchorRule                    # perception/slots.py:27 (SHAPE_IS_SLOT = "shape_is_slot")
from typing import ClassVar, List, Sequence
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py (current, 661 lines)
_EXPECTED_ELEMENTS = ["backlit_panel", "lower_poster"]                     # :35   DELETE
class EndcapNoShelvesPromotional(AbstractPlanogramType):                  # :38   KEEP name + base
    def __init__(self, pipeline: Any, config: Any) -> None                 # :54   DELETE (pass-through)
    async def compute_roi(self, img)                                       # :61   DELETE (legacy)
    async def detect_objects_roi(self, img, roi)                           # :206  DELETE (legacy)
    async def detect_objects(self, img, roi, macro_objects)                # :299  DELETE (legacy)
    def _generate_virtual_shelves(self, roi_bbox, image_size, planogram)   # :428  DELETE
    def _assign_products_to_shelves(self, *args, **kwargs)                 # :437  DELETE
    def check_planogram_compliance(self, identified_products, planogram_description)  # :441-661 DELETE
# Nothing in this file is a cycle hook today: every method is legacy-only.

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
class AbstractPlanogramType(ABC):                                          # :36
    identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.FULL_IMAGE   # :54
    requires_slots_definition: ClassVar[bool] = False                      # :55  read by plan.py:220
    min_usable_shapes: ClassVar[int] = 0                                   # :56  read by plan.py:263
    uses_enhanced_image: ClassVar[bool] = True                             # :57  read by plan.py:248
    def __init__(self, pipeline, config) -> None                           # :63  sets self.pipeline/config/logger, calls validate_contract()

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py
def _description(self) -> PlanogramDescription                            # :409-421  pattern to copy (minimal fallback description)

# provisional zone candidate values to copy (verified on dev):
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:324-337
ShapeProfile(name="backlit_zone", kind=ShapeKind.ZONE.value, min_width=0.40, max_width=1.0, min_height=0.06,
             max_height=0.35, min_aspect=1.5, max_aspect=12.0, polarity="bright", min_rectangularity=0.80,
             min_contrast_std=5.0, thresholds=(200, 220, 240))

# packages/ai-parrot/src/parrot/models/detections.py
class ShelfConfig(BaseModel):                                              # :302 (product_weight/text_weight/visual_weight :313-315)
class AisleConfig(BaseModel):                                              # :356
class PlanogramDescription(BaseModel):                                     # :364
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3855 — planogram/layout.py (spec §3 M1 skeleton)
class LayoutProfile(BaseModel):   # extra="forbid"
    shape_profiles: list[ShapeProfile]; anchor_rule: AnchorRule = AnchorRule.SHAPE_IS_SLOT
    fill_gaps: bool = False; untagged_bottom_row: bool = False
    identify_strategy: IdentifyStrategy = IdentifyStrategy.FULL_IMAGE
    perception_mode: Literal["cv", "llm_detector"] = "cv"; min_usable_shapes: int = 1
    min_row_items: int = 1; max_row_slope: float = 0.12; work_width: int = 2048
    substrip_max_slots: int = 8; ocr_batch_size: int = 16
    descriptor_fields: list[str] = []; required_descriptor_fields: list[str] = []
    ocr_targets: list[Literal["slot", "tag", "zone"]] = ["slot", "tag", "zone"]
    references: ReferencePolicy; zone_selectors: list[ZoneSelector] = []
class ZoneSelector(BaseModel): zone_id: str; profile: str | None; kind: str | None; ordinal: int | None; region: tuple[float, float, float, float] | None
# TASK-3856 — planogram/stages/perceive.py
async def perceive_image(image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult
# TASK-3859 — planogram/stages/identify.py
async def identify_image(image: Image.Image, perception: PerceptionResult, ctx: CycleContext) -> IdentificationResult
# TASK-3863 — planogram/stages/compare.py (pure, no I/O; works with a vision object that raises on every call)
def compare_observations(perceptions: Sequence[PerceptionResult], identifications: Sequence[IdentificationResult],
                         ctx: CycleContext, description: PlanogramDescription) -> ComparisonResult
# TASK-3854 — contracts.py: CycleContext.layout (validated LayoutProfile), IdentificationResult.rule_observations,
#             RuleObservation(image_id, target_id, kind, value, assessed, source, evidence)
# TASK-3860 — comparison/definition.py: ZoneKind gains "graphic", "advertisement", "counter", "information_label";
#             zone-only definitions (no shelves) are legal; unowned zones become virtual shelves "zone:<zone_id>"
```

### Does NOT Exist
- ~~`EndcapNoShelvesPromotional.perceive` / `.identify` / `.compare` / `.default_layout_profile`~~ — this task adds them.
- ~~a shared "zone profile" constant module~~ — no module exports provisional zone profiles; define them privately in this file.
- ~~`LayoutProfile.illumination_penalty` / `LayoutProfile.expected_zones`~~ — not layout fields; penalties are `RuleBinding.params`, expected zones come from `slots_definition`.
- ~~`self.pipeline.llm` calls in the new hooks~~ — all vision goes through `ctx.vision` inside the shared stages.
- ~~`ZoneKind` values `"backlit_panel"` / `"lower_poster"`~~ — those were legacy element labels, not definition zone kinds.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py#EndcapNoShelvesPromotional",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall._description",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/profiles.py#ShapeProfile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#AnchorRule",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CycleContext"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`types/ink_wall.py` is the reference for a migrated type (ClassVars at :163-166, `_description()`
fallback at :409-421). Unlike InkWall this type has **no** type-specific geometry or identity
rules: every hook is a one-line delegation to a shared stage. Keep it that way — the §2 table
says the type's only responsibility is "configured promotional zones, text and illumination".

### Key Constraints
- **No retailer/element hardcoding** (spec §2, AC3): no `"backlit_panel"`, `"lower_poster"`,
  brand names, zone counts or default `shelves` config in the file. Expected zones come only from
  `ctx.definition` (the loaded `slots_definition`); rules only from `ctx.bindings`.
- **Optional zones stay optional** (M8 responsibility): the type must never add a mandatory
  binding or mark a `ZoneDefinition(required=False)` as required. It simply does not touch the
  definition — `compare_observations` owns zone scoring.
- **Compare is pure** (AC8): `compare` calls `compare_observations` synchronously; it must not
  call `ctx.vision`, `self.pipeline.llm`, or any `_check_illumination` helper. Illumination and
  visual facts arrive as `IdentificationResult.rule_observations` collected during `identify`.
- **Fresh defaults**: `default_layout_profile()` builds a new `LayoutProfile` (and new
  `ShapeProfile` objects) on every call so a caller mutating one result cannot affect another run.
- **Provisional profiles** (spec §2 "Non-ink numerical profile defaults reuse the already-present
  shelves candidates as provisional starting profiles; no accuracy claim"). Copy the
  `backlit_zone` values verbatim for a bright zone profile, and add ONE edge-polarity poster
  profile with the same size bands (a printed poster is not backlit, so a bright-only profile
  would never propose it). Name them `promo_backlit_zone` and `promo_poster_zone`; mark both
  PROVISIONAL in the docstring. Do not tune numbers.
- **Compatibility ClassVars**: `plan.py` (until TASK-3871) loads the definition only when
  `requires_slots_definition` is True (plan.py:220), opens the image enhanced unless
  `uses_enhanced_image` is False (plan.py:248) and reads the fallback threshold from
  `min_usable_shapes` (plan.py:263). Set `True`, `False`, `1` respectively, mirroring
  `LayoutProfile.min_usable_shapes=1`.
- Logging via `self.logger` (set by `AbstractPlanogramType.__init__`); no `print`.

### Transitional breakage (accepted — do NOT fix here)
Deleting the legacy half makes legacy-pinning tests owned by other tasks fail until they land:
`tests/planogram_cycle/test_neutral_panel_types.py`, `tests/planogram_cycle/test_neutral_shelf_types.py`,
`tests/test_planogram_types.py` (TASK-3876) and `tests/planogram_cycle/test_legacy_run_orchestration.py`
(TASK-3874). Do not edit those files and do not add them to Validation Commands.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py` — migrated type pattern
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py:45-72` — `_InlineExecutor` / `_ctx` test helpers to copy
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_comparison.py` (created by TASK-3863) — how to build zone-only perceptions/observations for `compare_observations`

---

## Implementation Blueprint

### Steps (in order)
1. Confirm the dependency symbols exist: `grep -n "def perceive_image\|def identify_image\|def compare_observations" packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/*.py` and `grep -n "class LayoutProfile" .../planogram/layout.py` — *why*: this task only composes them; if any is missing, STOP (dependency not done).
2. Replace the entire content of `endcap_no_shelves_promotional.py` with the two blocks below (module header + class) — *why*: every existing method is legacy-only (verified list in the contract), so an in-place edit would leave dead code.
3. Re-check the `backlit_zone` numbers against source (`grep -n 'name="backlit_zone"' -A 12 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py`; TASK-3865 may have moved them into `default_layout_profile`) — *why*: the copy must be verbatim, not re-tuned.
4. Rewrite the test file per the Test Specification — *why*: the old tests call `check_planogram_compliance`, which no longer exists.
5. Run the Validation Commands; fix lint — *why*: AC16.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py` (MODIFY — replace whole file, block 1/2)
```python
# occurrences: 1 (verified: grep -Fxc 'class EndcapNoShelvesPromotional(AbstractPlanogramType):' packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py)
# REPLACE — lines 1-661 (whole file; verified: file is 661 lines, class starts at :38)
"""EndcapNoShelvesPromotional — shelf-less promotional endcap on the shared cycle (FEAT-612).

Zones (backlit panels, posters, graphics) are observed by the shared CV perception stage; their
presence, text and illumination are judged only from evidence collected during identification and
compared deterministically against the configured ``slots_definition`` zones and rule bindings.
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
    """PROVISIONAL zone profiles (no accuracy claim; calibrate on fixtures before tuning).

    ``promo_backlit_zone`` copies the shelves ``backlit_zone`` candidate verbatim; ``promo_poster_zone``
    keeps the same size bands with edge polarity so a non-illuminated printed poster can be proposed.

    Returns:
        New profile objects on every call (never shared mutable defaults).
    """
    backlit = ShapeProfile(
        name="promo_backlit_zone",
        kind=ShapeKind.ZONE.value,
        # FILL IN: copy min/max width/height/aspect, polarity="bright", min_rectangularity, min_contrast_std and
        # thresholds VERBATIM from product_on_shelves.py `backlit_zone` (dev :324-337) — bounded by spec §2 provisional rule
    )
    poster = backlit.model_copy(
        update={"name": "promo_poster_zone", "polarity": "edge", "thresholds": ShapeProfile.model_fields["thresholds"].default}
    )
    return [backlit, poster]
```
**Why this shape**: spec §2 requires zone profiles as provisional reuse of existing candidates;
a module-level factory (not a constant list) guarantees fresh objects per `default_layout_profile()`
call. `model_copy(update=...)` bypasses validation, which is safe here because only `name`,
`polarity` (a valid Literal) and the default thresholds change.

### `endcap_no_shelves_promotional.py` (MODIFY — block 2/2, appended after block 1)
```python
class EndcapNoShelvesPromotional(AbstractPlanogramType):
    """Shelf-less promotional endcap: configured zones, their text and illumination — no product tiers."""

    requires_slots_definition: ClassVar[bool] = True  # plan.py:220 loads the definition only when True (until TASK-3871)
    uses_enhanced_image: ClassVar[bool] = False  # every cycle type receives the untouched image (spec §2)
    min_usable_shapes: ClassVar[int] = 1  # mirrors LayoutProfile.min_usable_shapes for plan.py:263 (until TASK-3871)

    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:
        """Zone profiles, shape-is-slot, full image, CV first, fallback threshold 1 (spec §2 defaults table).

        Returns:
            A fresh profile; never retailer names, expected counts or shared mutable defaults.
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
        """Shared CV perception with the resolved profile in ``ctx.layout`` (fallback is orchestrator-owned)."""
        return await perceive_image(image, image_id, ctx)

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Shared OCR + vision identification + neutral zone evidence (illumination / visual facts / presence)."""
        return await identify_image(image, perception, ctx)

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Deterministic zone comparison; no provider call, no I/O."""
        return compare_observations(perceptions, identifications, ctx, self._description())

    def _description(self) -> PlanogramDescription:
        """PlanogramDescription for weights/thresholds; minimal fallback when the config has no shelves."""
        # FILL IN: copy InkWall._description (ink_wall.py:409-421) verbatim, changing only the default
        # category/aisle strings to "promotional" and the log prefix to this class name — bounded by AC3
        # (no retailer text) and AC8 (no I/O)
```
**Why**: the three hooks are the exact M8 skeleton signatures. `_description()` is needed because
promotional configs often lack the ProductOnShelves-shaped keys that
`PlanogramConfig.get_planogram_description()` requires; InkWall already solved this.

### FILL IN checklist
- [ ] `_zone_profiles` — verbatim `backlit_zone` values; bounded by spec §2 provisional-profile rule (no tuning).
- [ ] `EndcapNoShelvesPromotional._description` — InkWall pattern; bounded by AC3/AC8.
- [ ] Test bodies in the Test Specification — bounded by AC1/AC7/AC9.

---

## Acceptance Criteria

- [ ] `EndcapNoShelvesPromotional` defines `default_layout_profile`, `perceive`, `identify`, `compare` and none of the legacy methods (AC1).
- [ ] `default_layout_profile()` returns a fresh `LayoutProfile` of zone-kind profiles only, `identify_strategy=FULL_IMAGE`, `perception_mode="cv"`, `min_usable_shapes=1`; two calls return distinct objects (AC3, AC4).
- [ ] The module contains no `_EXPECTED_ELEMENTS`, no `backlit_panel`/`lower_poster` literals, no brand names and no default `shelves` config (AC3).
- [ ] `compare` produces a result with a vision object that raises on every attribute access (AC8).
- [ ] An absent optional zone does not fail compliance; a mandatory illumination rule with observed OFF vs required ON fails; unknown illumination leaves the result inconclusive and non-compliant (AC7, AC9).
- [ ] `pytest packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py -q` passes; ruff and black clean on both files (AC16).
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py
"""EndcapNoShelvesPromotional on the shared perceive → identify → compare cycle (FEAT-612, Module 8)."""

from __future__ import annotations

import inspect
import logging
from unittest.mock import MagicMock

import pytest

from parrot_pipelines.planogram.contracts import AssessmentStatus, CreditPolicy, CycleContext, EvidenceWeights
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types import endcap_no_shelves_promotional as promo_module
from parrot_pipelines.planogram.types.endcap_no_shelves_promotional import EndcapNoShelvesPromotional

LEGACY = ("compute_roi", "detect_objects_roi", "detect_objects", "check_planogram_compliance",
          "_generate_virtual_shelves", "_assign_products_to_shelves")


class _RaisingVision:
    """Any attribute access fails: proves compare never touches the provider."""

    def __getattr__(self, name):
        raise AssertionError(f"compare touched vision.{name}")


def _handler() -> EndcapNoShelvesPromotional:
    pipeline = MagicMock(); pipeline.logger = logging.getLogger("test.promo")
    config = MagicMock(); config.planogram_config = {}; config.config_name = "promo-test"
    config.slots_definition = {"version": 1, "shelves": [], "zones": []}  # presence only; hooks read ctx.definition
    return EndcapNoShelvesPromotional(pipeline=pipeline, config=config)


def test_default_layout_profile_is_fresh_zone_only():
    a, b = EndcapNoShelvesPromotional.default_layout_profile(), EndcapNoShelvesPromotional.default_layout_profile()
    assert a is not b and a.shape_profiles[0] is not b.shape_profiles[0]
    assert {p.kind for p in a.shape_profiles} == {"zone"}
    assert a.identify_strategy.value == "full_image" and a.perception_mode == "cv" and a.min_usable_shapes == 1


def test_no_legacy_methods_and_no_hardcoded_elements():
    for name in LEGACY:
        assert name not in EndcapNoShelvesPromotional.__dict__
    source = inspect.getsource(promo_module)
    for literal in ("backlit_panel", "lower_poster", "_EXPECTED_ELEMENTS", "Epson"):
        assert literal not in source


async def test_hooks_delegate_to_shared_stages(monkeypatch):
    # FILL IN: monkeypatch promo_module.perceive_image / identify_image / compare_observations with recorders;
    # assert each is awaited/called once with the SAME ctx object and compare receives a PlanogramDescription.
    ...


async def test_optional_zone_absent_still_compliant():
    # FILL IN: zone-only definition {"zones": [required backlit "header", optional poster "base"]} + mandatory
    # zone_present/illumination bindings on "header" only; observations show header present + illumination "on";
    # ctx.vision=_RaisingVision(); assert overall_compliant is True and no failed rule targets "base".
    ...


async def test_illumination_off_fails_mandatory_rule():
    # FILL IN: same fixture, illumination observation value "off" with binding params {"required": "on"};
    # assert overall_compliant is False and the illumination RuleOutcome has assessed=True, passed=False.
    ...


async def test_unknown_illumination_is_inconclusive():
    # FILL IN: no illumination observation (or assessed=False); assert assessment_status == AssessmentStatus.INCONCLUSIVE
    # and overall_compliant is False (unknown evidence never passes — AC7/AC9).
    ...


def test_type_registered():
    assert PlanogramCompliance._PLANOGRAM_TYPES["endcap_no_shelves_promotional"] is EndcapNoShelvesPromotional
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3867 refactor-planogram-compliance verified`
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
