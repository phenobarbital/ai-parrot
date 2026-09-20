# TASK-3442: AbstractPlanogramType cycle hooks, validate_contract and legacy adapter

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3421, TASK-3424, TASK-3429
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 14** (Type hooks & legacy adapter), goals **G1** and **G3**. The new
`run()` is a three-stage template — perceive → identify → compare — that calls
async hooks on the type handler. The four unmigrated types
(`GraphicPanelDisplay`, `ProductCounter`, `EndcapNoShelvesPromotional`,
`EndcapBacklitMultitier`) must keep working **unchanged**, so
`AbstractPlanogramType` gains the hooks as *concrete* methods whose default
implementation wraps the legacy contract:

- `perceive` → the complete legacy preparation + detection sequence that is
  inlined today in `PlanogramCompliance.run()` (steps 5-17, `plan.py:98-343`),
  moved **behaviour-preserving** into a new module `types/legacy_adapter.py`;
- `identify` → pass-through (legacy types identify during detection);
- `compare` → `check_planogram_compliance` + today's aggregation
  (`plan.py:346-351`), with the single intended deviation that an **empty
  result list is never a pass**.

`run()` itself is **not** edited here — it keeps its inlined copy until TASK-3443
switches it over to the hooks. The orchestration being copied is pinned by the
characterization test of TASK-3424; after TASK-3443 that test runs through this
adapter, so order and guards must be identical.

---

## Scope

- In `types/abstract.py`: class attributes `identify_strategy`,
  `requires_slots_definition`, `min_usable_shapes`, `uses_enhanced_image`;
  methods `validate_contract`, `perceive`, `identify`, `compare`,
  `fallback_detection_prompt`; call `validate_contract()` from `__init__`.
- Remove `@abstractmethod` from `compute_roi`, `detect_objects_roi`,
  `detect_objects`, `check_planogram_compliance`; their default body raises
  `NotImplementedError("<Type> does not implement the legacy contract")`.
- Create `types/legacy_adapter.py` with `legacy_perceive(...)` and its private helpers.
- Write `test_type_hooks.py`.

**NOT in scope**:
- Editing `planogram/plan.py` — `run()` is switched to the hooks by TASK-3443.
- Overriding the hooks in any concrete type (InkWall / ProductOnShelves tasks).
- Validating the *content* of `slots_definition` — here only its **presence** is
  checked for types with `requires_slots_definition = True`; schema validation
  belongs to the migrated-type tasks.
- Changing any legacy algorithm, prompt or private helper.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` | MODIFY | hook contract, `validate_contract`, legacy methods no longer abstract |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/legacy_adapter.py` | CREATE | `legacy_perceive` + helpers (steps 5-17 of today's `run()`) |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py` | CREATE | contract validation, default hooks, adapter order |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from abc import ABC                                                          # types/abstract.py:6 (today: `from abc import ABC, abstractmethod`)
from typing import Any, ClassVar, Dict, List, Optional, Sequence, Tuple, Union, TYPE_CHECKING   # :7 today lacks ClassVar, Sequence
from pathlib import Path
from PIL import Image, ImageDraw                                             # plan.py:4 uses the same
from parrot.models.detections import Detection, DetectionBox, IdentifiedProduct, ShelfRegion    # types/abstract.py:14-19
from parrot.models.compliance import ComplianceResult, ComplianceStatus      # packages/ai-parrot/src/parrot/models/compliance.py:32, :9
# Created by TASK-3421 (dependency) — parrot_pipelines/planogram/contracts.py
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus, ComparisonResult, CycleContext, IdentificationResult,
    IdentifyStrategy, LegacyPayload, PerceptionResult,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py  (478 lines before TASK-3429)
class AbstractPlanogramType(ABC):                                            # :30
    def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None:   # :48-55
        self.pipeline = pipeline; self.config = config; self.logger = pipeline.logger
    @abstractmethod  async def compute_roi(self, img: Image.Image) -> Tuple[...]          # decorator :57, def :58-76
    @abstractmethod  async def detect_objects_roi(self, img, roi) -> List[Detection]      # decorator :78, def :79-95
    @abstractmethod  async def detect_objects(self, img, roi, macro_objects) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]  # :97, :98-113
    @abstractmethod  def check_planogram_compliance(self, identified_products, planogram_description) -> List[ComplianceResult]    # :115, :116-129 (SYNC)
    #   all four bodies are DOCSTRING-ONLY today (no `pass`, no `...`)
    #   grep -c '    @abstractmethod' == 4
    def _refine_shelves_from_fact_tags(self, shelf_regions, identified_products) -> List[ShelfRegion]   # :359 (concrete, on the base)
    def _vision_kwargs(self, **extra: Any) -> Dict[str, Any]                 # created by TASK-3429 (dependency), sits above get_render_colors
    def get_render_colors(self) -> Dict[str, Tuple[int, int, int]]           # :448

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py — the sequence to reproduce (line numbers BEFORE
# TASK-3429; after it, everything below :214 is shifted by -1)
#  5  :98-102   endcap, ad, brand, panel_text, raw_dets = await handler.compute_roi(img)   bare `except Exception` → logger.error only
#  6  :104-130  if output_dir: debug overlay → Path(output_dir)/f"debug_step1_roi{_sfx}.png"  (inner try/except → logger.warning)
#  7  :132-138  identified_products, shelf_regions = await handler.detect_objects(img, roi=endcap, macro_objects=None)
#  8  :139-143  logger.info("Step 2 detected %d products, %d shelf regions", ...)
#  9  :145-157  _cfg_visuals_by_name / _cfg_visuals_fallback from planogram_description.shelves[*].products[*].visual_features
# 10  :159-170  _cfg_text_reqs_by_name from RAW config dict ["shelves"][*]["products"][*]["text_requirements"]
# 11  :172-264  promo OCR loop (trigger: "logo ad"/"backlit" in product_model.lower() or product_type == "promotional_graphic");
#               call site (after TASK-3429): `async with self.llm as client:` + `**self._type_handler._vision_kwargs(), max_tokens=1024`
#               parses "CONFIRMED:" / "TEXT_FOUND:" lines; sets p.ocr_text, extends p.visual_features, forces
#               p.product_type = "promotional_graphic" (:250), brand verification (:252-262); outer `except Exception` → logger.warning
# 12  :266-278  if endcap and endcap.bbox: hasattr(handler, "_generate_virtual_shelves") → shelf_regions REPLACED (:273); else debug log
# 13  :281-283  _pg_cfg = getattr(planogram_config, "planogram_config", {}) or {};
#               if _pg_cfg.get("use_fact_tag_boundaries") and shelf_regions: handler._refine_shelves_from_fact_tags(...)   (NO hasattr guard)
# 14  :286-290  hasattr "_assign_products_to_shelves" → (identified_products, shelf_regions, use_y1_assignment=_pg_cfg.get("use_fact_tag_boundaries", False))
# 15  :293-304  if use_fact_tag_boundaries: hasattr "_ocr_fact_tags" → await (..., img, planogram_description, shelf_regions=shelf_regions);
#               then hasattr "_corroborate_products_with_fact_tags" → (identified_products, _ft_shelf_map, planogram_description)
# 16  :307-324  panel_text.content → IdentifiedProduct(product_type="text_overlay", product_model="poster_text", shelf_location="header",
#               visual_features=[f"ocr:{content}"], detection_box from normalised bbox * img size)
# 17  :326-343  brand → IdentifiedProduct(product_type="brand_logo", product_model=brand.label or "brand_logo",
#               brand=planogram_description.brand, shelf_location="header")
# 18  :345-351  compliance_results = handler.check_planogram_compliance(identified_products, planogram_description)   (SYNC)
#               overall_score = mean(r.compliance_score) ; overall_compliant = all(status == ComplianceStatus.COMPLIANT)
#               TODAY: empty results ⇒ score 0.0 but overall_compliant True  ← the quirk this task fixes in the default compare

# packages/ai-parrot-pipelines/src/parrot_pipelines/models.py
class PlanogramConfig(BaseModel):                                            # :29
    planogram_config: Dict[str, Any]                                         # :50
    roi_detection_prompt / object_identification_prompt                      # Optional[str] after TASK-3426 (ancestor of TASK-3429)
    slots_definition: Optional[Union[Dict[str, Any], str, Path]] = None      # added by TASK-3426 (ancestor)
    config_name: str                                                         # :39
    def get_planogram_description(self) -> PlanogramDescription              # :102-108

# Created by TASK-3421 (dependency) — planogram/contracts.py  (field names from spec §2 Data Models)
class IdentifyStrategy(str, Enum):  FULL_IMAGE, STRIPS
class AssessmentStatus(str, Enum):  COMPLETE, INCONCLUSIVE, LEGACY_UNMEASURED
class LegacyPayload(BaseModel):     identified_products: List[IdentifiedProduct]; shelf_regions: List[ShelfRegion]
class PerceptionResult(BaseModel):  image_id, image_size, shapes, slots, zones, row_count, detection_source, ocr_available,
                                    legacy: Optional[LegacyPayload], errors
class IdentificationResult(BaseModel): image_id, identifications, added, errors
class ComparisonResult(BaseModel):  compliance_results, position_results, shelf_scores, overall_compliance_score,
                                    strict_compliance_score, overall_compliant, coverage, definition_coverage,
                                    evidence_quality, assessment_status, errors
class CycleContext(BaseModel):      vision, executor, ocr, definition=None, bindings=[], credit_policy, evidence_weights,
                                    output_dir: Optional[Path] = None, errors: List[str] = []
```

Existing tests that constrain the design (verified — do **not** edit them, they must keep passing):
```python
# packages/ai-parrot-pipelines/tests/test_planogram_types.py:169-183
with pytest.raises(TypeError, match="abstract"):  AbstractPlanogramType(pipeline=..., config=...)      # direct instantiation
with pytest.raises(TypeError, match="abstract"):  IncompleteType(...)   # implements only compute_roi
# :185-196 CompleteType implementing the four legacy methods with `pass` must still construct.
# tests/pipelines/test_abstract_type_grid.py:20-31 builds a concrete type with MagicMock pipeline AND MagicMock config.
```
⇒ `validate_contract()` must raise `TypeError` whose message contains the word **"abstract"**, and
must tolerate a `MagicMock` config (truthy auto-attributes).

### Does NOT Exist
- ~~`types/legacy_adapter.py`~~ — created by THIS task.
- ~~`AbstractPlanogramType.perceive / identify / compare / validate_contract / fallback_detection_prompt`~~ — created by THIS task.
- ~~a call to `detect_objects_roi` from `run()`~~ — never invoked; it is therefore **not** part of the required legacy contract.
- ~~a `hasattr` guard around `_refine_shelves_from_fact_tags`~~ — step 13 has none (the method is on the base class); keep it unguarded.
- ~~a global/numeric compliance threshold~~ — aggregation is `mean` + `all(status == COMPLIANT)`.
- ~~`CycleContext.image_id` / `CycleContext.file_suffix`~~ — not fields; the suffix is derived from the `image_id` argument.
- ~~`self.pipeline.roi_client` in new code~~ — use `handler.pipeline.llm` with `handler._vision_kwargs()`.
- ~~`PlanogramConfig.required_prompts`~~ — no such field; the two prompt attribute names are checked literally.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/legacy_adapter.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType.compute_roi",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType.detect_objects_roi",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType.detect_objects",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType.check_planogram_compliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType._refine_shelves_from_fact_tags",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance.run",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/models.py#PlanogramConfig",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#IdentifiedProduct",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#DetectionBox",
    "sym:packages/ai-parrot/src/parrot/models/compliance.py#ComplianceStatus"
  ]
}
```

---

## Implementation Notes

### Substitution table for code copied out of `run()`
| In `plan.py` | In `legacy_adapter.py` |
|---|---|
| `self._type_handler` | `handler` |
| `self.logger` | `handler.logger` |
| `self.planogram_config` | `handler.config` (same object — `plan.py:69` passes it as `config=`) |
| `async with self.llm as client:` | `async with handler.pipeline.llm as client:` |
| `**self._type_handler._vision_kwargs(),` | `**handler._vision_kwargs(),` |
| `img = self.open_image(image)` | `img = image` — the caller already opened (and, for legacy types, enhanced) it |
| `output_dir` | `ctx.output_dir` |

### Key Constraints
- **Behaviour-preserving move**: same step order, same `hasattr` guards, same bare `except`
  handlers, same log messages, same in-place mutation of `identified_products`. Do not "clean up".
- The only additions: failures that today are only logged are *also* appended to the returned
  `PerceptionResult.errors` (additive; nothing reads it on the legacy path yet).
- `detection_source` is passed as the plain string `"legacy_llm"` — it validates whether the
  contract types the field as `str` or as the `ObservationSource` str-enum.
- A method counts as "implemented" when `getattr(type(self), name) is not getattr(AbstractPlanogramType, name)`.
- Prompt presence check uses `getattr(self.config, name, None)`; a falsy value fails. Both prompts were
  mandatory before this feature, so requiring both for legacy types is backward compatible.
- The `ValueError` messages name "the FEAT-574 planogram cycle migration runbook under docs/pipelines"
  (words, not a file path — that document is written by another task).
- Async throughout; `self.logger`; Google-style docstrings; no `print`.
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` inside the
  worktree. Never `uv sync`.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:84-351` — the source being moved.
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_legacy_run_orchestration.py` (TASK-3424) — pins the order.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `types/legacy_adapter.py` from blocks B1-B4 — *why*: the default `perceive` imports it lazily; having it first lets you unit-test the move in isolation.
2. Fill the COPY markers strictly by copy + substitution table — *why*: TASK-3424's test compares behaviour, any "improvement" is a regression.
3. Edit `types/abstract.py` imports (A1) — *why*: hook signatures reference the contract models at class-definition time.
4. Drop the four `@abstractmethod` decorators and add the `raise NotImplementedError` bodies (A2) — *why*: `InkWall` will implement none of the legacy methods, so they can no longer be abstract.
5. Add class attributes + `validate_contract()` call in `__init__` (A3) and the hook methods (A4) — *why*: with the decorators gone, `validate_contract` is what keeps half-implemented types out.
6. Write `test_type_hooks.py`; run it plus the two existing suites named in AC-6.

### A1 — `.../planogram/types/abstract.py` (MODIFY) — imports
```python
# occurrences: 1 (verified: grep -c '^from abc import ABC, abstractmethod' .../types/abstract.py)
# REPLACE `from abc import ABC, abstractmethod` (verified: :6) with:
from abc import ABC
# occurrences: 1 (verified: grep -c '^from typing import' .../types/abstract.py)
# REPLACE the typing import (verified: :7) with:
from typing import Any, ClassVar, Dict, List, Optional, Sequence, Tuple, Union, TYPE_CHECKING
# occurrences: 1 (verified: grep -c '^from parrot.models.compliance import ComplianceResult' .../types/abstract.py)
# REPLACE `from parrot.models.compliance import ComplianceResult` (verified: :20) with:
from parrot.models.compliance import ComplianceResult, ComplianceStatus
from ..contracts import (
    AssessmentStatus,
    ComparisonResult,
    CycleContext,
    IdentificationResult,
    IdentifyStrategy,
    PerceptionResult,
)
```
**Why**: `contracts` imports only `parrot.models.*`, so a module-level import creates no cycle.
`abstractmethod` is no longer used anywhere in the file after A2.

### A2 — `.../planogram/types/abstract.py` (MODIFY) — legacy methods stop being abstract
```python
# occurrences: 4 (verified: grep -c '    @abstractmethod' .../types/abstract.py)
# N > 1 — disambiguation NOT needed: DELETE ALL 4 decorator lines (:57, :78, :97, :115).
# Then append ONE line as the body of each of the four methods, right after its closing docstring `"""`
# (the bodies are docstring-only today). Signatures and docstrings stay byte-identical:
    async def compute_roi(self, img: Image.Image) -> Tuple[...]:
        """...unchanged docstring..."""
        raise NotImplementedError(f"{type(self).__name__} does not implement the legacy contract")
    # same line for: detect_objects_roi, detect_objects, check_planogram_compliance
```
**Why**: spec Module 14 fixes both the removal and the exact message. Keep `ABC` as the base class.

### A3 — `.../planogram/types/abstract.py` (MODIFY) — class attributes, `__init__`
```python
# occurrences: 1 (verified: grep -c '        self.logger = pipeline.logger' .../types/abstract.py)
# AFTER — insert below `        self.logger = pipeline.logger` (verified: :55):
        self.validate_contract()

# occurrences: 1 (verified: grep -c '    def __init__(' .../types/abstract.py)
# BEFORE — insert above `    def __init__(` (verified: :48), after the class docstring:
    identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.FULL_IMAGE
    requires_slots_definition: ClassVar[bool] = False
    min_usable_shapes: ClassVar[int] = 0  # fallback threshold; 0 disables the LLM-detector fallback
    uses_enhanced_image: ClassVar[bool] = True  # legacy default; migrated types set False

    _LEGACY_CONTRACT: ClassVar[Tuple[str, ...]] = ("compute_roi", "detect_objects", "check_planogram_compliance")
    _CYCLE_HOOKS: ClassVar[Tuple[str, ...]] = ("perceive", "identify", "compare")
    _LEGACY_PROMPTS: ClassVar[Tuple[str, ...]] = ("roi_detection_prompt", "object_identification_prompt")

```
**Why**: the four public class attributes and their defaults come verbatim from the spec skeleton.
`detect_objects_roi` is deliberately absent from `_LEGACY_CONTRACT` — `run()` never calls it.

### A4 — `.../planogram/types/abstract.py` (MODIFY) — hooks
```python
# occurrences: 1 (verified after TASK-3429: grep -c '    def _vision_kwargs(self' .../types/abstract.py)
# BEFORE — insert above `    def _vision_kwargs(self, **extra: Any) -> Dict[str, Any]:`
    def _implements(self, name: str) -> bool:
        """Return True when the concrete class overrides ``name``."""
        return getattr(type(self), name, None) is not getattr(AbstractPlanogramType, name)

    def validate_contract(self) -> None:
        """Reject incomplete types and unusable configurations at construction.

        Raises:
            TypeError: The type supplies neither the complete legacy contract nor all cycle hooks.
            ValueError: A legacy type lacks a required prompt, or a type that requires a
                slots definition has none.
        """
        legacy = all(self._implements(n) for n in self._LEGACY_CONTRACT)
        cycle = all(self._implements(n) for n in self._CYCLE_HOOKS)
        if not (legacy or cycle):
            raise TypeError(
                f"Can't instantiate {type(self).__name__} with an incomplete planogram contract: implement the "
                f"abstract legacy contract {self._LEGACY_CONTRACT} or all cycle hooks {self._CYCLE_HOOKS}"
            )
        # FILL IN: prompt check — only when `legacy and not cycle`; for each name in _LEGACY_PROMPTS,
        #          falsy getattr(self.config, name, None) ⇒ ValueError naming type, config_name, the missing
        #          prompt and the runbook (wording in Implementation Notes) — bounded by AC-2
        # FILL IN: slots check — when requires_slots_definition and getattr(self.config, "slots_definition", None)
        #          is None ⇒ ValueError naming the runbook; presence only, no schema validation — bounded by AC-2

    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
        """Stage 1. Default: the complete legacy preparation + detection sequence (``detection_source='legacy_llm'``)."""
        from .legacy_adapter import legacy_perceive  # lazy: legacy_adapter imports this module

        return await legacy_perceive(self, image, image_id, ctx)

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Stage 2. Default: pass-through — legacy types identify during detection."""
        return IdentificationResult(image_id=perception.image_id, identifications=[], added=[], errors=[])

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Stage 3. Default: ``check_planogram_compliance`` on the first image's legacy payload."""
        payload = perceptions[0].legacy if perceptions else None
        results: List[ComplianceResult] = []
        errors: List[str] = []
        if payload is None:
            errors.append("legacy compare: no legacy payload to evaluate")
        else:
            description = self.config.get_planogram_description()
            results = self.check_planogram_compliance(payload.identified_products, description)
        score = sum(r.compliance_score for r in results) / len(results) if results else 0.0
        compliant = bool(results) and all(r.compliance_status == ComplianceStatus.COMPLIANT for r in results)
        return ComparisonResult(
            compliance_results=results, position_results=[], shelf_scores=[],
            overall_compliance_score=score, strict_compliance_score=None, overall_compliant=compliant,
            coverage=None, definition_coverage=None, evidence_quality=None,
            assessment_status=AssessmentStatus.LEGACY_UNMEASURED, errors=errors,
        )

    def fallback_detection_prompt(self) -> Optional[str]:
        """Prompt for the LLM detector fallback; ``None`` selects the generic prompt."""
        return None

```
**Why this shape**: signatures are the spec skeleton's. `bool(results) and all(...)` is the one
intended deviation from `plan.py:347-351` (empty list ⇒ not compliant). Coverage-type fields are
`None` and the status is `LEGACY_UNMEASURED` because the legacy contract cannot establish them —
full coverage is never fabricated. The `TypeError` text contains "abstract" so the two existing
ABC tests keep passing unedited.

### B1 — `.../planogram/types/legacy_adapter.py` (CREATE) — header + entry point
```python
"""Legacy cycle adapter: the ROI-first orchestration formerly inlined in ``PlanogramCompliance.run()``.

Behaviour-preserving move of steps 5-17 (``plan.py:98-343``). Same order, same ``hasattr`` guards.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from PIL import Image, ImageDraw

from parrot.models.detections import DetectionBox, IdentifiedProduct, ShelfRegion
from ..contracts import CycleContext, LegacyPayload, PerceptionResult

if TYPE_CHECKING:
    from .abstract import AbstractPlanogramType


async def legacy_perceive(
    handler: "AbstractPlanogramType", image: Image.Image, image_id: str, ctx: CycleContext
) -> PerceptionResult:
    """Run the legacy preparation and detection sequence for one image.

    Args:
        handler: The legacy type composable.
        image: The already-opened (enhanced) PIL image.
        image_id: Image identifier; also drives the debug-file suffix.
        ctx: Per-run context (only ``output_dir`` is read here).

    Returns:
        PerceptionResult with ``detection_source='legacy_llm'`` and the ``LegacyPayload``.
    """
    img = image
    errors: List[str] = []
    sfx = f"_{image_id}" if image_id else ""
    planogram_description = handler.config.get_planogram_description()
    endcap = ad = brand = panel_text = None
    raw_dets: List[Any] = []
    try:  # step 5 — failure is logged, never raised (plan.py:98-102)
        endcap, ad, brand, panel_text, raw_dets = await handler.compute_roi(img)
    except Exception as e:  # noqa: BLE001 - preserved legacy behaviour
        handler.logger.error(f"Step 1 Failed: {e}")
        errors.append(f"compute_roi failed: {e}")
    if ctx.output_dir:  # step 6
        _save_roi_debug(handler, img, endcap, raw_dets, Path(ctx.output_dir), sfx)
    identified_products, shelf_regions = await handler.detect_objects(img, roi=endcap, macro_objects=None)  # step 7
    handler.logger.info(
        "Step 2 detected %d products, %d shelf regions", len(identified_products), len(shelf_regions)
    )
    lookups = _config_lookups(handler, planogram_description)  # steps 9-10
    await _promo_ocr(handler, img, identified_products, planogram_description, lookups)  # step 11
    shelf_regions = await _shelves_and_fact_tags(  # steps 12-15
        handler, img, endcap, identified_products, shelf_regions, planogram_description
    )
    _inject_header_items(handler, img, identified_products, panel_text, brand, planogram_description)  # 16-17
    return PerceptionResult(
        image_id=image_id or "img0", image_size=img.size, shapes=[], slots=[], zones=[], row_count=0,
        detection_source="legacy_llm", ocr_available=False,
        legacy=LegacyPayload(identified_products=identified_products, shelf_regions=shelf_regions),
        errors=errors,
    )
```
**Why this shape**: one entry point with the spec's fixed signature; each numbered step of today's
`run()` maps to one helper so every block stays under the size cap and the order is visible at a glance.

### B2 — `legacy_adapter.py` — steps 6, 9-10
```python
def _save_roi_debug(handler, img: Image.Image, endcap: Any, raw_dets: List[Any], output_dir: Path, sfx: str) -> None:
    """Step 6: save the ROI debug overlay; failures are warnings only."""
    try:
        debug_img = img.copy()
        debug_draw = ImageDraw.Draw(debug_img)
        w, h = debug_img.size
        # FILL IN: COPY plan.py:110-125 verbatim (dataset loop over `raw_dets`, then the red ENDCAP ROI box);
        #          `detections_step1["dataset"]` becomes `raw_dets` — bounded by "behaviour-preserving move"
        debug_path = output_dir / f"debug_step1_roi{sfx}.png"
        debug_img.save(debug_path)
        handler.logger.info(f"Saved Step 1 Debug Image to {debug_path}")
    except Exception as e:  # noqa: BLE001
        handler.logger.warning(f"Failed to save Step 1 debug image: {e}")


def _config_lookups(handler, planogram_description: Any) -> Tuple[Dict[str, list], Set[str], Dict[str, list]]:
    """Steps 9-10: visual-feature and text-requirement lookups keyed by product name."""
    visuals_by_name: Dict[str, list] = {}
    visuals_fallback: Set[str] = set()
    text_reqs_by_name: Dict[str, list] = {}
    # FILL IN: COPY plan.py:148-157 (visual_features, own try/except → warning) and plan.py:162-170
    #          (text_requirements from the RAW dict `getattr(handler.config, "planogram_config", {}) or {}`,
    #          own try/except → warning) — bounded by "behaviour-preserving move"
    return visuals_by_name, visuals_fallback, text_reqs_by_name
```
**Why**: note a subtlety of step 6 — today the overlay draws `detections_step1["dataset"]`, which is
only populated when `compute_roi` succeeded; `raw_dets` is `[]` on failure, so passing it is equivalent.

### B3 — `legacy_adapter.py` — step 11
```python
async def _promo_ocr(handler, img: Image.Image, identified_products: List[IdentifiedProduct],
                     planogram_description: Any, lookups: Tuple[Dict[str, list], Set[str], Dict[str, list]]) -> None:
    """Step 11: OCR + visual verification of promotional items (mutates products in place)."""
    visuals_by_name, visuals_fallback, text_reqs_by_name = lookups
    for p in identified_products:
        model_lower = (p.product_model or "").lower()
        if not ("logo ad" in model_lower or "backlit" in model_lower or p.product_type == "promotional_graphic"):
            continue
        try:
            p_box = p.detection_box
            crop_box = (int(p_box.x1), int(p_box.y1), int(p_box.x2), int(p_box.y2))
            if not (crop_box[0] < crop_box[2] and crop_box[1] < crop_box[3]):
                continue
            p_img = img.crop(crop_box)
            handler.logger.info(f"Running OCR & Visual verification on promotional item: {p.product_model}")
            ocr_prompt = _build_ocr_prompt(
                visuals_by_name.get(p.product_model) or list(visuals_fallback),
                text_reqs_by_name.get(p.product_model, []),
            )
            async with handler.pipeline.llm as client:
                msg = await client.ask_to_image(
                    image=p_img, prompt=ocr_prompt, **handler._vision_kwargs(), max_tokens=1024
                )
            found_content = msg.output if msg else ""
            if found_content:
                _apply_ocr_result(handler, p, found_content, planogram_description)
        except Exception as e:  # noqa: BLE001
            handler.logger.warning(f"Failed OCR fallback for {p.product_model}: {e}")


def _build_ocr_prompt(item_visuals: list, item_text_reqs: list) -> str:
    """Build the promo OCR prompt exactly as today."""
    # FILL IN: COPY plan.py:188-209 verbatim (visuals_prompt, text_reqs_prompt, final f-string) — bounded by
    #          "prompt text must be byte-identical" (TASK-3424 may assert on it)
    raise NotImplementedError


def _apply_ocr_result(handler, p: IdentifiedProduct, found_content: str, planogram_description: Any) -> None:
    """Parse CONFIRMED:/TEXT_FOUND: lines and enrich ``p`` in place."""
    # FILL IN: COPY plan.py:220-262 verbatim with the substitution table (sets p.ocr_text, extends
    #          p.visual_features, forces p.product_type = "promotional_graphic", brand verification) —
    #          bounded by "behaviour-preserving move"
    raise NotImplementedError
```
**Why**: the `continue` guards are the inverted form of today's nested `if`s — same truth table,
flatter code. In today's code the parsing runs *inside* the `async with`; it touches no client
state, so running it after the context exits is equivalent. The vision call already uses the
provider-neutral idiom introduced by TASK-3429.

### B4 — `legacy_adapter.py` — steps 12-17
```python
async def _shelves_and_fact_tags(handler, img: Image.Image, endcap: Any,
                                 identified_products: List[IdentifiedProduct], shelf_regions: List[ShelfRegion],
                                 planogram_description: Any) -> List[ShelfRegion]:
    """Steps 12-15: virtual shelves, fact-tag refinement, shelf assignment, fact-tag corroboration."""
    if endcap and endcap.bbox:  # step 12
        if hasattr(handler, "_generate_virtual_shelves"):
            handler.logger.info("Generating virtual shelves from Endcap ROI...")
            shelf_regions = handler._generate_virtual_shelves(endcap.bbox, img.size, planogram_description)
        else:
            handler.logger.debug(
                "Type %s does not use _generate_virtual_shelves; skipping.", type(handler).__name__
            )
    pg_cfg = getattr(handler.config, "planogram_config", {}) or {}
    if pg_cfg.get("use_fact_tag_boundaries") and shelf_regions:  # step 13 — NO hasattr guard, as today
        shelf_regions = handler._refine_shelves_from_fact_tags(shelf_regions, identified_products)
    if hasattr(handler, "_assign_products_to_shelves"):  # step 14
        handler._assign_products_to_shelves(
            identified_products, shelf_regions, use_y1_assignment=pg_cfg.get("use_fact_tag_boundaries", False)
        )
    if pg_cfg.get("use_fact_tag_boundaries") and hasattr(handler, "_ocr_fact_tags"):  # step 15
        ft_shelf_map = await handler._ocr_fact_tags(
            identified_products, img, planogram_description, shelf_regions=shelf_regions
        )
        if hasattr(handler, "_corroborate_products_with_fact_tags"):
            handler._corroborate_products_with_fact_tags(identified_products, ft_shelf_map, planogram_description)
    return shelf_regions


def _inject_header_items(handler, img: Image.Image, identified_products: List[IdentifiedProduct],
                         panel_text: Any, brand: Any, planogram_description: Any) -> None:
    """Steps 16-17: append the poster-text and brand-logo pseudo products."""
    if panel_text and getattr(panel_text, "content", None):
        # FILL IN: COPY plan.py:308-325 verbatim (text_overlay / poster_text / shelf_location="header") —
        #          bounded by "behaviour-preserving move"
        pass
    if brand:
        # FILL IN: COPY plan.py:329-343 verbatim (brand_logo, brand=planogram_description.brand) —
        #          bounded by "behaviour-preserving move"
        pass
```
**Why**: steps 12-15 are short enough to be written out, which makes the guard structure (three
`hasattr`, one deliberate non-guard) explicit for review against TASK-3424's test.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py` (CREATE)
```python
"""AbstractPlanogramType cycle hooks, validate_contract and the legacy adapter (TASK-3442)."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from parrot.models.compliance import ComplianceResult, ComplianceStatus
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus, CreditPolicy, CycleContext, EvidenceWeights, LegacyPayload, PerceptionResult,
)
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType


def _pipeline():
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.type_hooks")
    pipeline.resolved_backend = MagicMock(provider="google", model=None)
    return pipeline


def _ctx(tmp_path=None) -> CycleContext:
    return CycleContext(vision=None, executor=None, ocr=None, credit_policy=CreditPolicy.default(),
                        evidence_weights=EvidenceWeights(), output_dir=tmp_path)


class _RecordingLegacy(AbstractPlanogramType):
    """Legacy type that records the order in which the adapter calls it."""

    def __init__(self, pipeline, config, results=None):
        self.calls = []
        self._results = results if results is not None else []
        super().__init__(pipeline, config)

    async def compute_roi(self, img):
        self.calls.append("compute_roi")
        return None, None, None, None, []

    async def detect_objects(self, img, roi, macro_objects):
        self.calls.append("detect_objects")
        return [], []

    def check_planogram_compliance(self, identified_products, planogram_description):
        self.calls.append("check_planogram_compliance")
        return self._results
    # NOTE: build configs as MagicMock() with `config.planogram_config = {}` (or a real dict) — a bare MagicMock makes
    #       `.get("use_fact_tag_boundaries")` truthy and silently enables the fact-tag branch.
    # FILL IN: add recording _generate_virtual_shelves / _assign_products_to_shelves / _ocr_fact_tags /
    #          _corroborate_products_with_fact_tags variants as needed by the order test — bounded by AC-4
```
**Why this shape**: a hand-written recording type exercises the real adapter without any LLM and
makes the order assertion a plain list comparison.

### FILL IN checklist
- [ ] `abstract.py::validate_contract` — prompt check (legacy-only types) and slots presence check; bounded by AC-2
- [ ] `legacy_adapter.py::_save_roi_debug` — copy `plan.py:110-125`; bounded by behaviour-preserving move
- [ ] `legacy_adapter.py::_config_lookups` — copy `plan.py:148-157`, `:162-170`; same
- [ ] `legacy_adapter.py::_build_ocr_prompt` — copy `plan.py:188-209`; prompt byte-identical
- [ ] `legacy_adapter.py::_apply_ocr_result` — copy `plan.py:220-262`; same
- [ ] `legacy_adapter.py::_inject_header_items` — copy `plan.py:308-325`, `:328-343`; same
- [ ] `test_type_hooks.py` — recording helpers + test bodies per Test Specification; bounded by AC-1..AC-5

---

## Acceptance Criteria

- [ ] AC-1: a subclass implementing neither the three legacy methods nor all three hooks raises `TypeError` (message contains "abstract") at construction; so does direct instantiation of `AbstractPlanogramType`. A subclass implementing only `perceive`/`identify`/`compare` constructs.
- [ ] AC-2: a legacy-only type whose config lacks `roi_detection_prompt` or `object_identification_prompt` raises `ValueError` naming the prompt; a type with `requires_slots_definition = True` and `config.slots_definition is None` raises `ValueError` mentioning the migration runbook. A `MagicMock` config passes.
- [ ] AC-3: the un-overridden legacy methods raise `NotImplementedError("<Type> does not implement the legacy contract")`.
- [ ] AC-4: `legacy_perceive` calls, in order: `compute_roi` → `detect_objects` → (promo OCR) → `_generate_virtual_shelves` → `_refine_shelves_from_fact_tags` → `_assign_products_to_shelves` → `_ocr_fact_tags` → `_corroborate_products_with_fact_tags` → header injections; a `compute_roi` exception is logged, recorded in `errors`, and the sequence continues. Result has `detection_source == "legacy_llm"` and a `LegacyPayload`.
- [ ] AC-5: default `compare` — mean score and all-`COMPLIANT` rule; **empty results ⇒ `overall_compliant is False`, score `0.0`**; `assessment_status == LEGACY_UNMEASURED`; `coverage`, `definition_coverage`, `strict_compliance_score`, `evidence_quality` are `None`. Default `identify` returns an empty pass-through.
- [ ] AC-6: unedited existing suites pass: `pytest packages/ai-parrot-pipelines/tests/test_planogram_types.py tests/pipelines/test_abstract_type_grid.py -q`, plus TASK-3424's orchestration test.
- [ ] AC-7: `planogram/plan.py` is untouched by this task (`git diff --stat` shows only the three declared files).
- [ ] `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types` passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py -q`

---

## Test Specification

```python
def test_validate_contract_rejects_incomplete_type():
    class Half(AbstractPlanogramType):
        async def compute_roi(self, img): return None, None, None, None, []
    with pytest.raises(TypeError, match="abstract"):
        Half(pipeline=_pipeline(), config=MagicMock())

def test_cycle_only_type_constructs():            # overrides perceive/identify/compare, none of the legacy methods
def test_legacy_type_missing_prompts_fails_at_construction():   # config with roi_detection_prompt=None ⇒ ValueError
def test_type_requiring_slots_definition_fails_without_it():    # requires_slots_definition=True, slots_definition=None
def test_unimplemented_legacy_method_raises_not_implemented():

async def test_legacy_perceive_order_and_payload(tmp_path):
    handler = _RecordingLegacy(_pipeline(), MagicMock())
    result = await handler.perceive(Image.new("RGB", (64, 64)), "img0", _ctx(tmp_path))
    assert handler.calls[:2] == ["compute_roi", "detect_objects"]
    assert result.detection_source == "legacy_llm" and isinstance(result.legacy, LegacyPayload)

async def test_legacy_perceive_survives_compute_roi_failure():
async def test_default_identify_is_passthrough():

async def test_legacy_adapter_empty_results_not_compliant():
    handler = _RecordingLegacy(_pipeline(), MagicMock(), results=[])
    perception = PerceptionResult(image_id="img0", image_size=(64, 64), shapes=[], slots=[], zones=[], row_count=0,
                                  detection_source="legacy_llm", ocr_available=False,
                                  legacy=LegacyPayload(identified_products=[], shelf_regions=[]), errors=[])
    out = await handler.compare([perception], [], _ctx())
    assert out.overall_compliant is False and out.overall_compliance_score == 0.0
    assert out.assessment_status == AssessmentStatus.LEGACY_UNMEASURED and out.coverage is None

async def test_default_compare_mean_and_all_compliant():        # two ComplianceResult(0.9 COMPLIANT, 0.5 NON_COMPLIANT) ⇒ 0.7, False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Re-read `plan.py` `run()`; the quoted line numbers are from before TASK-3429 (−1 below `:214` afterwards)
   - Open `planogram/contracts.py` and confirm the exact field names/defaults of `PerceptionResult`,
     `IdentificationResult`, `ComparisonResult`, `CycleContext`; if they differ, follow the file and update this contract FIRST
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/new-planogram-pipeline.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3442-type-hooks-legacy-adapter.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (FEAT-574 orchestrator)
**Date**: 2026-09-19

Implemented in fallback sequential mode (parrot-sdd-coder server unresponsive).
types/abstract.py: ClassVars identify_strategy/requires_slots_definition/min_usable_shapes/uses_enhanced_image; the four legacy methods are no longer @abstractmethod and raise NotImplementedError('<Type> does not implement the legacy contract'); validate_contract() called from __init__ (TypeError containing 'abstract' unless the full legacy contract or all three cycle hooks are overridden; legacy-only types need both prompts; requires_slots_definition needs a slots_definition — ValueErrors name the FEAT-574 migration runbook under docs/pipelines); hooks perceive (lazy legacy_adapter), identify (pass-through), compare (mean + all-COMPLIANT, EMPTY list never a pass, LEGACY_UNMEASURED, coverage fields None), fallback_detection_prompt. noqa B024 (ABC kept per spec, contract enforced by validate_contract) and E402 (import follows existing module constants).
types/legacy_adapter.py: legacy_perceive = verbatim move of plan.py steps 5-17 (same order, hasattr guards, bare excepts, logs, prompt text byte-identical) with the substitution table; compute_roi failure also recorded in PerceptionResult.errors.
Deviation (files outside the declared list — test fixtures only): the spec'd legacy prompt check rejects configs with an empty prompt, so fixtures that built configs with object_identification_prompt=None / '' were given prompt strings: tests/pipelines/test_endcap_no_shelves.py::_make_config, tests/pipelines/test_product_on_shelves_grid.py::_make_config, and my own planogram_cycle/test_neutral_{shelf,panel}_types.py::_config. Production configs always had both prompts (NOT NULL columns before FEAT-574), so runtime behaviour is unchanged for existing rows; a legacy-type row with a NULL prompt now fails fast by design.
Tests: test_type_hooks.py 11 passed; full packages/ai-parrot-pipelines/tests 287 passed (+1 pre-existing failure); tests/pipelines 138 passed; test_graphic_panel_display 13; plan.py untouched. No new ruff findings in planogram/types.

Seat: orchestrator (fallback) · Backend: native · Model: claude-opus-5 · Attempts: 1
