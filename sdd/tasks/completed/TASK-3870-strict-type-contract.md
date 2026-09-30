# TASK-3870: Strict three-hook AbstractPlanogramType contract

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3864, TASK-3865, TASK-3866, TASK-3867, TASK-3868, TASK-3869
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 11** (abstract skeleton), §2 Integration Points ("`AbstractPlanogramType` — only
three cycle hooks plus defaults; legacy method contract removed after all six migrations") and
§7 ("Remove dead base illumination/provider helpers when the new collector replaces their last
caller"). Today `types/abstract.py` accepts EITHER the legacy contract (`compute_roi`,
`detect_objects`, `check_planogram_compliance`) OR the cycle hooks, and its default `perceive`
lazily imports `legacy_adapter.legacy_perceive` (:508) while its default `compare` scores a
`LegacyPayload`. After TASK-3864…3869 every registered type supplies `perceive`, `identify`,
`compare` and `default_layout_profile`, so the base class can become strict: four abstract
members, a definition that is always mandatory, and no legacy/grid machinery. TASK-3871 then
rewires the orchestrator; TASK-3874 deletes `legacy_adapter.py` and the grid execution classes.

---

## Scope

- Make `default_layout_profile` (classmethod), `perceive`, `identify`, `compare` abstract.
- Rewrite `validate_contract()`: `TypeError` for any missing hook; `ValueError` naming
  `config_name` and `docs/pipelines/planogram-cycle-migration.md` when `slots_definition` is missing
  (for every type, not only `requires_slots_definition` ones).
- Make `_implements()` correct for classmethods (MRO lookup).
- Delete: `_LEGACY_CONTRACT`, `_LEGACY_PROMPTS`, the four legacy methods, the default
  `perceive`/`identify`/`compare` bodies (incl. the `legacy_perceive` import), `get_grid_strategy`
  and its `TYPE_CHECKING` import of `grid.strategy`.
- Delete `_check_illumination` and `_vision_kwargs` — and the fact-tag / model-normalisation /
  illumination-parsing helpers and constants — **only when the grep check in the blueprint shows no
  remaining caller** (spec §7).
- Rewrite `tests/planogram_cycle/test_type_hooks.py` for the strict contract.

**NOT in scope**: `plan.py` (TASK-3871 — it still reads `requires_slots_definition`,
`min_usable_shapes`, `uses_enhanced_image`, `fallback_detection_prompt()` and `perception.legacy`, so
those stay); removing `LegacyPayload` from `contracts.py` (TASK-3871); deleting `legacy_adapter.py`
and `grid/` execution modules (TASK-3874); rewriting `test_vision_kwargs.py`,
`test_neutral_*_types.py`, `test_planogram_types.py` (TASK-3876); editing any concrete type.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` | MODIFY | Strict four-member contract; remove legacy contract, adapter import, grid strategy, dead helpers |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py` | MODIFY | Replace legacy-adapter tests with strict-contract tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# abstract.py today (verified)
import re                                                       # :5  (used only by _base_model_from_str)
from abc import ABC                                             # :6  → becomes `from abc import ABC, abstractmethod`
from typing import Any, ClassVar, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING   # :7
from PIL import Image                                           # :9
from parrot.models.detections import Detection, DetectionBox, IdentifiedProduct, ShelfRegion   # :11-16
from parrot.models.compliance import ComplianceResult, ComplianceStatus                    # :17 (only legacy compare uses them)
from ..contracts import (AssessmentStatus, ComparisonResult, CycleContext, IdentificationResult,
                         IdentifyStrategy, PerceptionResult)    # :18-25
if TYPE_CHECKING:                                               # :27
    from ..plan import PlanogramCompliance                      # :28
    from ..models import PlanogramConfig                        # :29
    from parrot_pipelines.planogram.grid.strategy import AbstractGridStrategy   # :30  DELETE
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py (621 lines)
_ILLUMINATION_FEATURE_PREFIX = "illumination_status:"                       # :32
_DEFAULT_ILLUMINATION_PENALTY: float = 1.0                                   # :33
class AbstractPlanogramType(ABC):  # noqa: B024 - ...                       # :36
    identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.FULL_IMAGE   # :54  KEEP (plan.py until 3871)
    requires_slots_definition: ClassVar[bool] = False                       # :55  KEEP, default → True
    min_usable_shapes: ClassVar[int] = 0                                    # :56  KEEP (plan.py:263)
    uses_enhanced_image: ClassVar[bool] = True                              # :57  KEEP (plan.py:248)
    _LEGACY_CONTRACT = ("compute_roi", "detect_objects", "check_planogram_compliance")   # :59  DELETE
    _CYCLE_HOOKS = ("perceive", "identify", "compare")                      # :60  → add "default_layout_profile"
    _LEGACY_PROMPTS = ("roi_detection_prompt", "object_identification_prompt")         # :61  DELETE
    def __init__(self, pipeline, config) -> None                            # :63-71 KEEP (calls validate_contract)
    async def compute_roi(self, img)                                        # :73-92   DELETE
    async def detect_objects_roi(self, img, roi)                            # :94-111  DELETE
    async def detect_objects(self, img, roi, macro_objects)                 # :113-129 DELETE
    def check_planogram_compliance(self, identified_products, planogram_description)   # :131-145 DELETE
    @staticmethod def _extract_illumination_state(features) -> Optional[str]            # :147-165 conditional
    async def _check_illumination(self, img, zone_bbox=None, roi=None, planogram_description=None)  # :167-264 conditional
    @staticmethod def _base_model_from_str(s, brand=None, patterns=None) -> str          # :266-339 conditional
    def _cluster_fact_tag_rows(self, fact_tags, cluster_threshold=50) -> List[int]      # :345-372 conditional
    def _refine_shelves_from_fact_tags(self, shelf_regions, identified_products)        # :374-461 conditional
    def _implements(self, name: str) -> bool                                # :463-465 REPLACE
    def validate_contract(self) -> None                                     # :467-495 REPLACE
    async def perceive(self, image, image_id, ctx) -> PerceptionResult      # :497-510 REPLACE (default → legacy_perceive at :508)
    async def identify(self, image, perception, ctx) -> IdentificationResult  # :512-525 REPLACE
    async def compare(self, perceptions, identifications, ctx) -> ComparisonResult  # :527-567 REPLACE (legacy compare)
    def fallback_detection_prompt(self) -> Optional[str]                    # :569-571 KEEP (plan.py:270 until 3871)
    def _vision_kwargs(self, **extra) -> Dict[str, Any]                     # :573-589 conditional
    def get_render_colors(self) -> Dict[str, Tuple[int, int, int]]          # :591-605 KEEP (plan.py:455)
    def get_grid_strategy(self) -> "AbstractGridStrategy"                   # :607-621 DELETE
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3855 — planogram/layout.py
class LayoutProfile(BaseModel): ...   # validated profile; each concrete type returns a fresh one
# TASK-3864…3869 — every registered type (ink_wall, product_on_shelves, endcap_backlit_multitier,
# endcap_no_shelves_promotional, graphic_panel_display, product_counter) defines:
@classmethod
def default_layout_profile(cls) -> LayoutProfile
async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult
async def identify(self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext) -> IdentificationResult
async def compare(self, perceptions: Sequence[PerceptionResult], identifications: Sequence[IdentificationResult],
                  ctx: CycleContext) -> ComparisonResult
```

### Does NOT Exist
- ~~`AbstractPlanogramType.default_layout_profile`~~ on dev — this task adds the abstract declaration.
- ~~a legacy fallback path after this task~~ — no `legacy_perceive`, no `LegacyPayload` scoring in the base.
- ~~`from abc import abstractclassmethod`~~ — deprecated; use `@classmethod` stacked over `@abstractmethod`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType.validate_contract",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType._implements",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType.perceive",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType.identify",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType.compare",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType.get_grid_strategy",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType._check_illumination",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType._vision_kwargs",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType.fallback_detection_prompt",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType.get_render_colors"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **`_implements` bug to avoid**: the current check (`getattr(type(self), name) is not getattr(AbstractPlanogramType, name)`,
  :465) is always True for classmethods, because every attribute access creates a new bound method.
  Use an MRO walk: find the first class in `type(self).__mro__` whose `__dict__` contains `name` and
  return `owner is not AbstractPlanogramType`. This works for functions, classmethods and staticmethods.
- **Abstract methods + explicit check**: `@abstractmethod` makes Python raise
  `TypeError("Can't instantiate abstract class …")` before `__init__`; keep the explicit
  `validate_contract()` TypeError as a second guard (spec skeleton names it) and so tests can call it
  on objects created with `__new__`. Order for the classmethod: `@classmethod` on top of `@abstractmethod`.
- **Definition is mandatory for every type** (spec §2 Overview, AC10): the check no longer depends on
  `requires_slots_definition`. Message must contain the type name, `config_name` and
  `docs/pipelines/planogram-cycle-migration.md`. Change the ClassVar default to `True` — *why*:
  `plan.py:220` (until TASK-3871) loads the definition only when it is True, and every type needs it.
- **Keep what plan.py still reads** until TASK-3871: `identify_strategy`, `requires_slots_definition`,
  `min_usable_shapes`, `uses_enhanced_image`, `fallback_detection_prompt()`, `get_render_colors()`.
  Removing any of them breaks the orchestrator before its own cutover.
- **Conditional dead-code removal** (spec §7): run, for each of `_check_illumination`, `_vision_kwargs`,
  `_extract_illumination_state`, `_base_model_from_str`, `_cluster_fact_tag_rows`,
  `_refine_shelves_from_fact_tags`, `_DEFAULT_ILLUMINATION_PENALTY`, `_ILLUMINATION_FEATURE_PREFIX`:
  `grep -rn "<name>" packages/ai-parrot-pipelines/src --include=*.py | grep -v "planogram/types/abstract.py\|planogram/types/legacy_adapter.py\|planogram/legacy.py"`.
  Empty ⇒ delete it (legacy_adapter/legacy.py are dead and deleted by TASK-3874/3873). Non-empty ⇒ keep it
  and list the remaining caller in the Completion Note. `_cluster_fact_tag_rows` is called only by
  `_refine_shelves_from_fact_tags` (:402): remove both together or keep both.
- Then `ruff check --select F401` on abstract.py and drop now-unused imports (`re`, `Detection`,
  `ComplianceResult`, `ComplianceStatus`, `AssessmentStatus`, `Dict`, `List`, `Optional`, `Tuple`,
  etc. — only those ruff reports).
- **Apply MODIFY blocks bottom-up** (highest line first) so the verified line numbers stay valid.

### Transitional breakage (accepted — do NOT fix here)
Until their owners land, these fail: `tests/planogram_cycle/test_run_template.py` (its `_StubCycleType`
lacks `default_layout_profile` and a definition — TASK-3871), `test_legacy_run_orchestration.py`
(deleted by TASK-3874), `test_vision_kwargs.py`, `test_neutral_panel_types.py`,
`test_neutral_shelf_types.py`, `tests/test_planogram_types.py` (TASK-3876),
`test_pos_compliance_characterization.py`, `test_pos_fact_tags_illumination_characterization.py`
(TASK-3875). **Also** `tests/planogram_cycle/test_ink_wall.py:171` reads `InkWall._LEGACY_CONTRACT`,
which this task deletes, and no task after TASK-3864 owns that file — record it in the Completion Note
(do not edit it; out of scope). Do not list any of these in Validation Commands.

---

## Implementation Blueprint

### Steps (in order)
1. Confirm every registered type implements the four members: `grep -n "def default_layout_profile\|async def perceive\|async def identify\|async def compare" packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/*.py` — *why*: this task makes them mandatory; a missing one would make `PlanogramCompliance` unconstructible. Missing ⇒ STOP.
2. Delete `get_grid_strategy` (:607-621) — *why*: grid execution is removed (M12); last override was in POS (removed by TASK-3865).
3. Run the conditional grep for `_vision_kwargs` and delete :573-589 if unused — *why*: spec §7.
4. Replace :497-567 (default hooks) and :463-495 (`_implements`, `validate_contract`) with the block below — *why*: strict contract; removes the `legacy_perceive` import (:508).
5. Conditional deletes :147-461 per the grep rule — *why*: dead helpers after all migrations.
6. Delete :73-145 (legacy methods), replace ClassVars :54-61, class line :36, drop :30, change :6 — *why*: no legacy contract remains.
7. `ruff check --fix --select F401` then full `ruff check` on the file — *why*: unused imports after deletions.
8. Rewrite `test_type_hooks.py` (Test Specification) — *why*: it pins the legacy adapter today and imports `LegacyPayload`, which TASK-3871 removes.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` (MODIFY — header)
```python
# occurrences: 1 (verified: grep -Fxc 'from abc import ABC' packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py)
# REPLACE line :6  →
from abc import ABC, abstractmethod

# occurrences: 1 (verified: grep -Fxc '    from parrot_pipelines.planogram.grid.strategy import AbstractGridStrategy' …/abstract.py)
# DELETE line :30 (inside `if TYPE_CHECKING:` :27)

# ADD next to the `from ..contracts import (...)` block (:18-25):
from ..layout import LayoutProfile

# occurrences: 1 — REPLACE line :36 (the class line with the `# noqa: B024` comment) →
class AbstractPlanogramType(ABC):
```
**Why**: `abstractmethod` is needed; `B024` no longer applies once abstract members exist;
`LayoutProfile` is imported for real (layout.py imports only contracts/perception, no cycle).

### `abstract.py` (MODIFY — ClassVars and constants inside the class)
```python
# occurrences: 1 (verified: grep -Fxc '    _LEGACY_CONTRACT: ClassVar[Tuple[str, ...]] = ("compute_roi", "detect_objects", "check_planogram_compliance")' …/abstract.py)
# REPLACE lines :54-61 →
    identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.FULL_IMAGE  # plan.py reads it until TASK-3871
    requires_slots_definition: ClassVar[bool] = True  # every cycle type needs a definition (plan.py:220 until TASK-3871)
    min_usable_shapes: ClassVar[int] = 0  # plan.py:263 until TASK-3871 (the layout profile is authoritative after)
    uses_enhanced_image: ClassVar[bool] = False  # all types receive the untouched image (spec §2)

    _CYCLE_HOOKS: ClassVar[Tuple[str, ...]] = ("default_layout_profile", "perceive", "identify", "compare")
```
**Why**: `_LEGACY_CONTRACT`/`_LEGACY_PROMPTS` disappear with the legacy path; the four ClassVars stay
because the orchestrator reads them until its cutover.

### `abstract.py` (MODIFY — contract + abstract hooks; replaces :463-567)
```python
# occurrences: 1 (verified: grep -Fxc '    def validate_contract(self) -> None:' …/abstract.py → :467)
# REPLACE lines :463-567 (`_implements`, `validate_contract`, default `perceive`/`identify`/`compare`) →
    def _implements(self, name: str) -> bool:
        """Return True when a subclass (not this base) defines ``name`` — correct for classmethods too."""
        for klass in type(self).__mro__:
            if name in klass.__dict__:
                return klass is not AbstractPlanogramType
        return False

    def validate_contract(self) -> None:
        """Reject incomplete types and configurations without a slots definition, before any inference.

        Raises:
            TypeError: A cycle hook or ``default_layout_profile`` is not implemented.
            ValueError: ``slots_definition`` is missing (names the config and the migration runbook).
        """
        missing = [name for name in self._CYCLE_HOOKS if not self._implements(name)]
        if missing:
            raise TypeError(
                f"Can't instantiate {type(self).__name__} with an incomplete planogram contract: "
                f"implement the abstract cycle members {missing}"
            )
        config_name = getattr(self.config, "config_name", None)
        if getattr(self.config, "slots_definition", None) is None:
            # FILL IN: raise ValueError whose text contains type(self).__name__, repr(config_name) and the literal
            # path "docs/pipelines/planogram-cycle-migration.md" — bounded by AC10
            ...

    @classmethod
    @abstractmethod
    def default_layout_profile(cls) -> LayoutProfile:
        """Return a fresh default LayoutProfile for this type (configuration overrides are merged by the pipeline)."""

    @abstractmethod
    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
        """Stage 1: observed geometry for one untouched image (fallback is orchestrator-owned)."""

    @abstractmethod
    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Stage 2: OCR/vision identification and neutral rule evidence for one image."""

    @abstractmethod
    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Stage 3: deterministic comparison of every processed image against the definition; no I/O."""
```
**Why**: exactly the M11 skeleton (`default_layout_profile`, `validate_contract`) plus the three hook
signatures already used by every type. Abstract bodies are docstring-only (valid Python; ruff accepts).

### `abstract.py` (MODIFY — deletions)
```python
# DELETE :607-621  get_grid_strategy (occurrences: 1 — grep -Fxc '    def get_grid_strategy(self) -> "AbstractGridStrategy":')
# CONDITIONAL DELETE :573-589  _vision_kwargs            (grep rule in Implementation Notes)
# CONDITIONAL DELETE :341-461  fact-tag helpers + section comment (_cluster_fact_tag_rows :345, _refine_shelves_from_fact_tags :374)
# CONDITIONAL DELETE :266-339  _base_model_from_str
# CONDITIONAL DELETE :167-264  _check_illumination       (occurrences: 1 — grep -Fxc '    async def _check_illumination(')
# CONDITIONAL DELETE :147-165  _extract_illumination_state
# DELETE :73-145   compute_roi, detect_objects_roi, detect_objects, check_planogram_compliance (legacy contract)
# CONDITIONAL DELETE :32-33    _ILLUMINATION_FEATURE_PREFIX / _DEFAULT_ILLUMINATION_PENALTY (module constants)
```
**Why**: line ranges were verified on dev; after TASK-3865 edits nothing in this file moves, but
re-run `grep -n` for each `def` before deleting because a dependency task may have touched the file.

### FILL IN checklist
- [ ] `validate_contract` ValueError text — AC10.
- [ ] Conditional deletions — record kept helpers + their callers in the Completion Note (spec §7).
- [ ] Test bodies — AC1/AC10.

---

## Acceptance Criteria

- [ ] `AbstractPlanogramType` has no `_LEGACY_CONTRACT`, `_LEGACY_PROMPTS`, `compute_roi`, `detect_objects_roi`, `detect_objects`, `check_planogram_compliance`, `get_grid_strategy`; the module source contains neither `legacy_adapter` nor `grid.strategy` (AC1, AC14).
- [ ] Instantiating a subclass missing any of the four members raises `TypeError`; `AbstractPlanogramType` itself cannot be instantiated (AC1).
- [ ] `_implements("default_layout_profile")` is False for a subclass that does not define it and True for one that does.
- [ ] A complete type with `slots_definition=None` raises `ValueError` mentioning the config name and `docs/pipelines/planogram-cycle-migration.md` (AC10).
- [ ] Every entry of `PlanogramCompliance._PLANOGRAM_TYPES` implements all four members and returns a fresh `LayoutProfile` (AC1).
- [ ] Removed dead helpers have no remaining source caller; kept ones are listed with their caller in the Completion Note.
- [ ] `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py -q` passes; ruff/black clean (AC16).
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py -q`
- `pytest packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py -q`
- `pytest packages/ai-parrot/tests/test_graphic_panel_display.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py
"""Strict three-hook AbstractPlanogramType contract (FEAT-612, Module 11)."""

from __future__ import annotations

import inspect
import logging
from unittest.mock import MagicMock

import pytest

from parrot_pipelines.planogram.contracts import ComparisonResult, IdentificationResult, PerceptionResult
from parrot_pipelines.planogram.layout import LayoutProfile
from parrot_pipelines.planogram.perception import PRICE_TAG_PROFILE
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types import abstract as abstract_module
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType

LEGACY = ("compute_roi", "detect_objects_roi", "detect_objects", "check_planogram_compliance",
          "get_grid_strategy", "_LEGACY_CONTRACT", "_LEGACY_PROMPTS")


def _pipeline():
    pipeline = MagicMock(); pipeline.logger = logging.getLogger("test.type_hooks")
    return pipeline


def _config(slots_definition=None, name="cfg"):
    config = MagicMock(); config.config_name = name; config.planogram_config = {}
    config.slots_definition = slots_definition
    return config


class _Complete(AbstractPlanogramType):
    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:
        return LayoutProfile(shape_profiles=[PRICE_TAG_PROFILE])

    async def perceive(self, image, image_id, ctx):
        return PerceptionResult(image_id=image_id)

    async def identify(self, image, perception, ctx):
        return IdentificationResult(image_id=perception.image_id)

    async def compare(self, perceptions, identifications, ctx):
        return ComparisonResult()


def test_legacy_members_removed():
    for name in LEGACY:
        assert not hasattr(AbstractPlanogramType, name)
    source = inspect.getsource(abstract_module)
    assert "legacy_adapter" not in source and "grid.strategy" not in source


@pytest.mark.parametrize("missing", ["default_layout_profile", "perceive", "identify", "compare"])
def test_missing_member_is_type_error(missing):
    # FILL IN: members = {k: _Complete.__dict__[k] for k in ("default_layout_profile", "perceive", "identify", "compare")
    # if k != missing}; half = type("Half", (AbstractPlanogramType,), members); assert pytest.raises(TypeError) on
    # half(pipeline=_pipeline(), config=_config({"shelves": []})). Copy ONLY these four keys (never __abstractmethods__/_abc_impl)
    ...


def test_base_is_not_instantiable():
    with pytest.raises(TypeError):
        AbstractPlanogramType(pipeline=_pipeline(), config=_config({"shelves": []}))


def test_implements_is_classmethod_safe():
    handler = _Complete(pipeline=_pipeline(), config=_config({"shelves": []}))
    assert handler._implements("default_layout_profile") and handler._implements("compare")
    assert not handler._implements("get_render_colors")


def test_missing_definition_names_config_and_runbook():
    with pytest.raises(ValueError, match="planogram-cycle-migration.md") as exc:
        _Complete(pipeline=_pipeline(), config=_config(None, name="store-42"))
    assert "store-42" in str(exc.value)


@pytest.mark.parametrize("ptype", sorted(PlanogramCompliance._PLANOGRAM_TYPES))
def test_every_registered_type_is_complete(ptype):
    cls = PlanogramCompliance._PLANOGRAM_TYPES[ptype]
    handler = cls(pipeline=_pipeline(), config=_config({"shelves": []}))
    assert all(handler._implements(n) for n in AbstractPlanogramType._CYCLE_HOOKS)
    a, b = cls.default_layout_profile(), cls.default_layout_profile()
    assert isinstance(a, LayoutProfile) and a is not b


def test_render_colors_default_kept():
    colors = _Complete(pipeline=_pipeline(), config=_config({"shelves": []})).get_render_colors()
    assert {"compliant", "non_compliant"} <= set(colors)
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3870 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Merged cleanly via sdd-worker orchestration; lint clean. TASK-3870 note: tests/planogram_cycle/test_ink_wall.py:171 reads InkWall._LEGACY_CONTRACT which TASK-3870 deleted (no task owns that file; needs follow-up). test_endcap_no_shelves_promotional.py 2 failures pre-exist.

