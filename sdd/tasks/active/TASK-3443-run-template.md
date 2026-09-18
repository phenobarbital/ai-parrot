# TASK-3443: PlanogramCompliance.run() three-stage template with multi-image support

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3427, TASK-3428, TASK-3434, TASK-3437, TASK-3439, TASK-3442
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 15** and goal **G1**: perceive → identify → compare becomes the
*only* cycle of `PlanogramCompliance.run()`. The ROI-first orchestration that
lives inline in `plan.py:82-370` is removed — not kept behind a flag. Its legacy
steps were already moved, behaviour-preserving, into the legacy adapter by
TASK-3442 and are reached through the default `perceive` hook, so after this task
`run()` contains **shared orchestration only**: load → build `CycleContext` →
perceive per image → fallback check → identify → compare → render per image →
assemble. `run()` additionally accepts a **list of images** of the same fixture
(goal G8) and returns the eight legacy keys plus additive ones (goal G2).

---

## Scope

- Replace `__init__` with the spec signature: `UNSET` sentinel for
  `llm_provider` / `llm_model`, keyword-only `cpu_workers=2`,
  `llm_concurrency=4`, `llm_timeout=120.0`, `vision_cache_dir=None`; pass
  `config_backend=planogram_config.llm_backend` to `super().__init__`.
- Replace the body of `run()` (`plan.py:71-370`) with the template, split into
  private helpers (each ≤ ~80 lines):
  1. `_normalize_inputs` — one image or a sequence; `image_id` one id or a
     matching sequence; default ids `img0..imgN`; `ValueError` when `image_id` is
     a sequence whose length differs from `image`.
  2. `_build_context` — `CpuExecutor(max_workers=cpu_workers)`,
     `OcrReader()`, `asyncio.Semaphore(llm_concurrency)`, `VisionAdapter(self.llm, self.resolved_backend, …)`,
     slots definition + rule bindings when the type requires them,
     `CreditPolicy.default()`, `EvidenceWeights()`.
  3. `_perceive_one` — load **full-resolution, untouched** unless
     `type_handler.uses_enhanced_image` (`open_image(src, enhance=…)` through
     `asyncio.to_thread`), call `type_handler.perceive`, then the **fallback
     check**.
  4. `_fallback_if_needed` — when `min_usable_shapes > 0`, the perception is not
     `legacy_llm`, and `len(usable_shapes(shapes)) < min_usable_shapes`: run
     `llm_detect_shapes`, apply `assign_membership` to the new shapes, mark
     `detection_source="llm"`. Off-fixture counts can never suppress the
     fallback. A failed fallback leaves shapes as they were and appends to
     `errors` — never an empty silent result.
  5. `_render_one` — `render_evaluated_image` per image, only with that image's
     own boxes; never draws one photo's boxes on another.
  6. `_assemble` — eight legacy keys + additive keys.
- Keep the `_sfx` filename rule of `plan.py:82` for the **single-image** call
  (`compliance_render{_sfx}.png`, `_sfx` from the caller's `image_id` or `""`);
  multi-image calls write `compliance_render_<image_id>.png`.
- Singular `rendered_image` / `overlay_path` represent the **first successfully
  processed** image; all images failed ⇒ both `None`, `compliance_results=[]`,
  score `0.0`, `overall_compliant=False`, `assessment_status="inconclusive"`.
- One failed photo is isolated and recorded in `errors`; the run continues.
- Executor and adapter resources are created per run and released in `finally`
  (success, failure and `asyncio.CancelledError`).
- `render_evaluated_image` (`plan.py:376-485`) is **not touched**.
- Offline tests with stub type handlers and the `fake_vision_client` fixture.

**Additive result keys** (spec §2 Overview): `detections`, `identifications`,
`position_results`, `shelf_scores`, `coverage`, `definition_coverage`,
`assessment_status`, `strict_compliance_score`, `evidence_quality`,
`detection_source`, `ocr_available`, `resolved_backend`, `renders`, `errors`.

**NOT in scope**: any type hook implementation; the new planogram type and its
registry entry; handler changes; the legacy adapter body; removing `roi_client`;
the promo-OCR call site (already moved by TASK-3442 — if lines of it are still
inline in `run()`, they disappear with the body replacement).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` | MODIFY | New constructor signature; `run()` body replaced by the three-stage template + private helpers |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py` | CREATE | Offline tests of the template |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_legacy_run_orchestration.py` | MODIFY | Flip ONLY `test_legacy_empty_results_is_compliant_today` (created by TASK-3424): rename it `test_legacy_empty_results_is_not_compliant` and assert `overall_compliant is False` — the single intended legacy behaviour change (spec §2). Every other test in that file must pass unedited. |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# already at the top of plan.py (verified :1-21, sha256 c39d4a1650e605f3… at authoring time)
import contextlib                                                   # :1   (still used by render_evaluated_image :431)
from typing import Any, Dict, List, Optional, Union                 # :2
from pathlib import Path                                            # :3
from PIL import Image, ImageDraw, ImageFont                         # :4   (ImageDraw/ImageFont used by render :410-412)
from ..abstract import AbstractPipeline                             # :5
from ..models import PlanogramConfig                                # :6
from parrot.models.detections import DetectionBox, ShelfRegion, IdentifiedProduct   # :7-11
from parrot.models.compliance import ComplianceStatus               # :12-14 (no longer used by run(); keep only if still referenced)
# Created by dependencies (re-verify once merged):
from .backend import UNSET, _Unset                                  # TASK-3426 (via TASK-3427)
from .contracts import (AssessmentStatus, ComparisonResult, CreditPolicy, CycleContext, EvidenceWeights,
                        IdentificationResult, ObservationSource, PerceptionResult, RenderRecord)   # TASK-3421
from .perception.executor import CpuExecutor                        # TASK-3434
from .perception.ocr import OcrReader                               # TASK-3428
from .perception.membership import assign_membership, usable_shapes # TASK-3437
from .identification.vision import VisionAdapter                    # TASK-3436 (via TASK-3439)
from .identification.detector import llm_detect_shapes              # TASK-3439
from .comparison.definition import load_slots_definition, validate_bindings   # TASK-3435 (via TASK-3439)
import numpy as np                                                  # declared directly by TASK-3428's pyproject edit
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py  (485 lines)
class PlanogramCompliance(AbstractPipeline):                        # :24-485
    _PLANOGRAM_TYPES = {...}                                        # :37-43 — DO NOT edit in this task
    def __init__(self, planogram_config, llm=None, llm_provider: str = "google",
                 llm_model: Optional[str] = None, **kwargs)         # :45-69
    #   :53 super().__init__(llm=llm, llm_provider=llm_provider, llm_model=llm_model, **kwargs)
    #   :54 self.planogram_config   :57-58 left/right_margin_ratio   :60 reference_images
    #   :63-68 type resolution + ValueError   :69 self._type_handler = composable_cls(pipeline=self, config=planogram_config)
    async def run(self, image, output_dir=None, image_id: Optional[str] = None, **kwargs) -> Dict[str, Any]   # :71-370
    #   :82 _sfx = f"_{image_id}" if image_id else ""
    #   :353-358 render call: self.render_evaluated_image(img, shelf_regions=..., identified_products=..., save_to=...)
    #   :361-370 return dict with the 8 legacy keys
    def render_evaluated_image(self, image: Union[str, Path, Image.Image], *, shelf_regions=None, detections=None,
        identified_products=None, mode: str = "identified", show_shelves: bool = True,
        save_to: Optional[Union[str, Path]] = None) -> Image.Image  # :376-485  SYNC, writes to disk :479-483

# ---- Created by TASK-3427 (dependency) — parrot_pipelines/abstract.py ----
class AbstractPipeline:
    def __init__(self, llm: Any = None, llm_provider: Union[str, _Unset] = UNSET,
                 llm_model: Union[str, None, _Unset] = UNSET, *, config_backend: Optional[str] = None, **kwargs: Any)
    #   sets self.llm, self.llm_provider, self.resolved_backend (ResolvedBackend: provider, model, origin, as_string())
    def open_image(self, image_path: Union[Path, Image.Image], *, enhance: bool = True) -> Image.Image

# ---- Created by TASK-3442 (dependency) — planogram/types/abstract.py ----
class AbstractPlanogramType(ABC):
    identify_strategy: ClassVar[IdentifyStrategy]; requires_slots_definition: ClassVar[bool] = False
    min_usable_shapes: ClassVar[int] = 0; uses_enhanced_image: ClassVar[bool] = True
    def validate_contract(self) -> None
    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult
    async def identify(self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext) -> IdentificationResult
    async def compare(self, perceptions: Sequence[PerceptionResult],
                      identifications: Sequence[IdentificationResult], ctx: CycleContext) -> ComparisonResult
    def fallback_detection_prompt(self) -> Optional[str]

# ---- Created by TASK-3421 (dependency) — planogram/contracts.py (spec §2 + Module 2 skeleton) ----
class PerceptionResult(BaseModel):   # image_id, image_size, shapes, slots, zones, row_count, detection_source,
                                     # ocr_available, legacy: Optional[LegacyPayload], errors
class LegacyPayload(BaseModel):      # identified_products: List[IdentifiedProduct]; shelf_regions: List[ShelfRegion]
class IdentificationResult(BaseModel): # image_id, identifications, added, errors
class ComparisonResult(BaseModel):   # compliance_results, position_results, shelf_scores, overall_compliance_score,
                                     # strict_compliance_score, overall_compliant, coverage, definition_coverage,
                                     # evidence_quality, assessment_status, errors
class RenderRecord(BaseModel):       # image_id, rendered_image, overlay_path
class CycleContext(BaseModel):       # vision, executor, ocr, definition=None, bindings=[], credit_policy,
                                     # evidence_weights, output_dir=None, errors=[]

# ---- Other dependency symbols ----
class CpuExecutor:    def __init__(self, max_workers: int = 2); async def run(self, fn, *args); async def aclose(self)   # TASK-3434
class OcrReader:      available: bool; def __init__(self) -> None                                                        # TASK-3428
def usable_shapes(shapes: Sequence[Shape]) -> List[Shape]                                                                # TASK-3437
def assign_membership(shapes, zones, image_size, *, llm_hints=None) -> List[Shape]                                       # TASK-3437
class VisionAdapter:  def __init__(self, client, backend, *, semaphore, cache_dir=None, max_tokens=8192,
                                   timeout=120.0, repair_retries=1)                                                      # TASK-3436
async def llm_detect_shapes(image: np.ndarray, image_id: str, ctx: CycleContext, *, prompt: str) -> List[Shape]         # TASK-3439
def load_slots_definition(source: Union[Dict[str, Any], str, Path]) -> SlotsDefinition   # BLOCKING file read       # TASK-3435
def validate_bindings(definition, planogram_config: Dict[str, Any]) -> List[RuleBinding]                                # TASK-3435
# PlanogramConfig.slots_definition / .llm_backend / .planogram_config — models.py (TASK-3426)
```
Dependency field **types** are fixed by their own tasks — read the modules before coding.

### Does NOT Exist
- ~~A flag / kwarg that re-enables the ROI-first cycle~~ — forbidden by goal G1.
- ~~`detect_objects_roi` being called from `run()`~~ — it never was; do not add it.
- ~~`PlanogramCompliance.run_legacy` / `_run_old`~~ — do not keep a copy of the old body.
- ~~A numeric global compliance threshold~~ — `overall_compliant` comes from the `compare` hook's `ComparisonResult`.
- ~~`self.roi_client` usage in `run()`~~ — must not be referenced by new code.
- ~~`PerceptionResult.image` / `.np_image`~~ — images are not stored in contracts; keep them in a local dict keyed by `image_id`.
- ~~`asyncio.to_thread` for CV/OCR~~ — CPU work belongs to hooks through `CpuExecutor`; `to_thread` is for blocking file I/O only.
- ~~An `async` `render_evaluated_image`~~ — it is synchronous; call it via `asyncio.to_thread` because it writes to disk.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_legacy_run_orchestration.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance.run",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance.render_evaluated_image",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#IdentifiedProduct",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#ShelfRegion",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#DetectionBox"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Template method: `run()` is a short orchestration that calls private helpers;
every type-specific decision lives behind `self._type_handler`. Logging through
`self.logger` (lazy `%s` formatting), Google-style docstrings, strict hints.

### Key Constraints
- **Legacy debug-file name**: `legacy_perceive` (TASK-3442) derives the `debug_step1_roi{_sfx}.png` suffix from the
  `image_id` it receives. For a single-image call where the caller gave no `image_id`, pass `image_id=""` to
  `perceive` so today's unsuffixed filename is kept (`PerceptionResult.image_id` then falls back to `"img0"`);
  key your own per-image dicts by the normalised id, not by the value passed to the hook.
- **The empty-results flip lands HERE, not earlier**: until this task replaces `run()`, the public path still
  returns `overall_compliant=True` for an empty result list. Flip the one pinned test listed in the Files table
  in the same commit — *why*: it is the only test of TASK-3424 that is supposed to change.
- `validate_contract()`: read `planogram/types/abstract.py` first. If
  `AbstractPlanogramType.__init__` already calls it, do **not** call it again;
  otherwise call `self._type_handler.validate_contract()` right after the handler
  is built (`plan.py:69`) so incomplete types fail at construction.
- Slots definition: loaded lazily on first `run()` and cached on
  `self._definition` / `self._bindings` — `load_slots_definition` does blocking
  file I/O ⇒ `await asyncio.to_thread(load_slots_definition, source)`.
  Only when `type_handler.requires_slots_definition`.
- BGR conversion for the LLM detector: `np.asarray(img.convert("RGB"))[:, :, ::-1]`.
- Fallback shapes have **no slots**: set `slots=[]` on the replaced perception
  and let the type treat every on-fixture shape as its own slot (document this in
  `_fallback_if_needed`'s docstring).
- `detection_source` result key: the single value when all perceptions agree,
  `"mixed"` otherwise.
- `identified_products` / `shelf_regions` keys: legacy types → from
  `PerceptionResult.legacy` of the first successful image; migrated types → a
  projection (FILL IN) bounded by "`render_evaluated_image` must keep working".
- `compliance_results` and `step3_compliance_results` are the **same list object**
  (today's behaviour, `plan.py:362-363`).
- Do not catch `asyncio.CancelledError`; catch `Exception` per image only.
- `**kwargs` of `run()` stays accepted and ignored (backwards compatibility).
- Tests run with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.
  Existing `packages/ai-parrot-pipelines/tests/test_planogram_types.py:243`
  constructs `PlanogramCompliance(planogram_config=config)` — it must keep working.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:71-370` — body being replaced
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/legacy_adapter.py` — where the legacy steps now live (TASK-3442)
- `packages/ai-parrot-pipelines/tests/conftest.py` — `FakeVisionClient`, `fake_vision_client`, `synthetic_shelf_image` (TASK-3420)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Re-read `plan.py` fully and the dependency modules listed in the contract — *why*: TASK-3429 and TASK-3442 edited this area; line numbers below were verified before they landed.
2. Apply block A (imports) and block B (constructor) — *why*: the sentinel must reach `AbstractPipeline` or `llm_backend` from the config is masked by the historical `"google"` default.
3. Delete the old `run()` body (from the line `    async def run(` down to the blank line before the `# Shared rendering` banner) and insert blocks C–F — *why*: goal G1 forbids keeping the old cycle; splitting into helpers keeps each unit testable and under the size cap.
4. Leave `render_evaluated_image` byte-identical — *why*: consumers and the legacy render colours depend on it.
5. Write the tests (block G) with stub handlers — *why*: the template must be verifiable without any real type, CV or LLM.
6. Run the task's validation command plus `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_legacy_run_orchestration.py -q` — *why*: the characterization test pins that legacy types behave the same through the new `run()`.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` (MODIFY) — block A: imports
```python
# occurrences: 1 (verified: grep -c 'from ..models import PlanogramConfig' plan.py)
# AFTER — insert below `from ..models import PlanogramConfig` (verified: plan.py:6)
import asyncio
from typing import Sequence, Tuple

import numpy as np

from .backend import UNSET, _Unset
from .contracts import (
    AssessmentStatus, ComparisonResult, CreditPolicy, CycleContext, EvidenceWeights,
    IdentificationResult, PerceptionResult, RenderRecord,
)
from .perception.executor import CpuExecutor
from .perception.membership import assign_membership, usable_shapes
from .perception.ocr import OcrReader
from .identification.detector import llm_detect_shapes
from .identification.vision import VisionAdapter
from .comparison.definition import load_slots_definition, validate_bindings

ImageInput = Union[str, Path, Image.Image]
```
**Why**: relative imports match the file's existing style (`from ..abstract import …`). `ComplianceStatus`
(:12-14) becomes unused once the old body is gone — remove that import if `ruff` flags it (F401).

### `plan.py` (MODIFY) — block B: constructor
```python
# occurrences: 1 (verified: grep -c '    def __init__(' plan.py)  -> plan.py:45
# REPLACE the signature + super() call (plan.py:45-53); keep plan.py:54-69 unchanged
    def __init__(
        self,
        planogram_config: PlanogramConfig,
        llm: Any = None,
        llm_provider: Union[str, _Unset] = UNSET,
        llm_model: Union[str, None, _Unset] = UNSET,
        *,
        cpu_workers: int = 2,
        llm_concurrency: int = 4,
        llm_timeout: float = 120.0,
        vision_cache_dir: Optional[Path] = None,
        **kwargs: Any,
    ):
        super().__init__(
            llm=llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
            config_backend=getattr(planogram_config, "llm_backend", None),
            **kwargs,
        )
        self.cpu_workers = cpu_workers
        self.llm_concurrency = llm_concurrency
        self.llm_timeout = llm_timeout
        self.vision_cache_dir = vision_cache_dir
        self._definition: Any = None
        self._bindings: List[Any] = []
# … existing lines plan.py:54-69 follow unchanged; then, ONLY if AbstractPlanogramType.__init__
# does not already call it:
        # FILL IN: self._type_handler.validate_contract() — bounded by AC-2 (incomplete type fails at construction)
```
**Why**: spec Module 15 skeleton. Limits are per gunicorn worker. `getattr` keeps old pickled/mocked configs working.

### `plan.py` (MODIFY) — block C: `run()`
```python
# occurrences: 1 (verified: grep -c '    async def run(' plan.py)  -> plan.py:71
# REPLACE plan.py:71-370 (whole method) with:
    async def run(
        self,
        image: Union[ImageInput, Sequence[ImageInput]],
        output_dir: Optional[Union[str, Path]] = None,
        image_id: Optional[Union[str, Sequence[str]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Run the perceive -> identify -> compare cycle on one image or several photos of one fixture.

        Returns:
            The 8 legacy keys plus the additive keys (detections, identifications, position_results,
            shelf_scores, coverage, definition_coverage, assessment_status, strict_compliance_score,
            evidence_quality, detection_source, ocr_available, resolved_backend, renders, errors).

        Raises:
            ValueError: ``image_id`` is a sequence whose length differs from ``image``.
        """
        inputs, single_sfx = self._normalize_inputs(image, image_id)
        out_dir = Path(output_dir) if output_dir else None
        self.logger.info("Planogram cycle: %d image(s), type=%s", len(inputs), type(self._type_handler).__name__)
        ctx = await self._build_context(out_dir)
        images: Dict[str, Image.Image] = {}
        perceptions: List[PerceptionResult] = []
        identifications: List[IdentificationResult] = []
        try:
            for img_id, source in inputs:
                try:
                    img, perception = await self._perceive_one(source, img_id, ctx)
                    identification = await self._type_handler.identify(img, perception, ctx)
                except Exception as exc:  # isolate one failed photo
                    self.logger.error("Image %s failed: %s", img_id, exc)
                    ctx.errors.append(f"{img_id}: {exc}")
                    continue
                images[img_id] = img
                perceptions.append(perception)
                identifications.append(identification)
            comparison = await self._compare(perceptions, identifications, ctx)
            renders = await self._render_all(images, perceptions, identifications, comparison, out_dir, single_sfx)
        finally:
            await ctx.executor.aclose()
            # FILL IN: release the VisionAdapter if it exposes aclose()/__aexit__ — bounded by AC-9
        return self._assemble(perceptions, identifications, comparison, renders, ctx)
```
**Why**: the loop isolates failures per photo (spec edge case "one strip/photo fails"); `finally` guarantees the
process pool is closed on success, failure and cancellation. `CancelledError` is not an `Exception`, so it propagates.

### `plan.py` (MODIFY) — block D: inputs and context (insert right after `run()`)
```python
    def _normalize_inputs(self, image: Any, image_id: Any) -> Tuple[List[Tuple[str, ImageInput]], Optional[str]]:
        """Return ([(image_id, source)], single_image_suffix). Suffix is None for multi-image calls."""
        if isinstance(image, (str, Path, Image.Image)):
            if image_id is not None and not isinstance(image_id, str):
                raise ValueError("image_id must be a string when a single image is given")
            return [(image_id or "img0", image)], (f"_{image_id}" if image_id else "")
        sources = list(image)
        if image_id is None:
            ids = [f"img{n}" for n in range(len(sources))]
        elif isinstance(image_id, str):
            raise ValueError("image_id must be a sequence matching the image list")
        else:
            ids = list(image_id)
        if len(ids) != len(sources):
            raise ValueError(f"image_id has {len(ids)} entries for {len(sources)} images")
        # FILL IN: reject duplicate ids and an empty image list with ValueError — bounded by AC-3
        return list(zip(ids, sources)), None

    async def _build_context(self, output_dir: Optional[Path]) -> CycleContext:
        """Create the per-run shared services."""
        handler = self._type_handler
        if handler.requires_slots_definition and self._definition is None:
            source = self.planogram_config.slots_definition
            self._definition = await asyncio.to_thread(load_slots_definition, source)
            self._bindings = validate_bindings(self._definition, self.planogram_config.planogram_config)
        vision = VisionAdapter(
            self.llm, self.resolved_backend,
            semaphore=asyncio.Semaphore(self.llm_concurrency),
            cache_dir=self.vision_cache_dir, timeout=self.llm_timeout,
        )
        return CycleContext(
            vision=vision, executor=CpuExecutor(max_workers=self.cpu_workers), ocr=OcrReader(),
            definition=self._definition, bindings=list(self._bindings),
            credit_policy=CreditPolicy.default(), evidence_weights=EvidenceWeights(),
            output_dir=output_dir, errors=[],
        )
```
**Why**: the single-image suffix reproduces `plan.py:82` exactly so existing output filenames do not change.
One semaphore per run is the spec's "one shared bounded LLM semaphore".

### `plan.py` (MODIFY) — block E: perceive + fallback + compare
```python
    async def _perceive_one(self, source: ImageInput, image_id: str, ctx: CycleContext
                            ) -> Tuple[Image.Image, PerceptionResult]:
        """Load one image (untouched unless the type wants enhancement), perceive, apply the fallback."""
        handler = self._type_handler
        img = await asyncio.to_thread(self.open_image, source, enhance=handler.uses_enhanced_image)
        perception = await handler.perceive(img, image_id, ctx)
        perception = await self._fallback_if_needed(img, perception, ctx)
        return img, perception

    async def _fallback_if_needed(self, img: Image.Image, perception: PerceptionResult,
                                  ctx: CycleContext) -> PerceptionResult:
        """LLM-detector fallback when usable on-fixture shapes are under the type threshold.

        Fallback perceptions carry no slots: the type treats every on-fixture shape as its own slot.
        """
        handler = self._type_handler
        threshold = handler.min_usable_shapes
        if threshold <= 0 or perception.legacy is not None:
            return perception
        if len(usable_shapes(perception.shapes)) >= threshold:
            return perception
        self.logger.warning("Image %s: usable shapes under %d — LLM detector fallback", perception.image_id, threshold)
        bgr = np.asarray(img.convert("RGB"))[:, :, ::-1]
        prompt = handler.fallback_detection_prompt() or _GENERIC_DETECTION_PROMPT
        shapes = await llm_detect_shapes(bgr, perception.image_id, ctx, prompt=prompt)
        if not shapes:
            # FILL IN: append a clear message to ctx.errors and return `perception` unchanged — bounded by AC-5
            return perception
        shapes = assign_membership(shapes, perception.zones, perception.image_size)
        # FILL IN: return perception.model_copy(update={shapes, slots=[], detection_source=<the "llm" value of the
        #   contract's source enum/str — read contracts.py>}) — bounded by AC-5
        raise NotImplementedError

    async def _compare(self, perceptions: List[PerceptionResult], identifications: List[IdentificationResult],
                       ctx: CycleContext) -> ComparisonResult:
        """Run the compare hook, or build the all-failed inconclusive result."""
        if perceptions:
            return await self._type_handler.compare(perceptions, identifications, ctx)
        # FILL IN: ComparisonResult with compliance_results=[], scores 0.0, overall_compliant=False, coverage fields
        #   None, assessment_status=AssessmentStatus.INCONCLUSIVE, errors=list(ctx.errors) — bounded by AC-6
        raise NotImplementedError
```
Also add at module level, below `ImageInput`:
```python
_GENERIC_DETECTION_PROMPT = (
    "Detect every retail product, product box, price tag and promotional panel that belongs to the main "
    "fixture in this photo. Return one bounding box per object with a short label."
)
```
**Why**: `perception.legacy is not None` identifies the legacy adapter path without string-matching a source
value. Membership is re-applied to fallback shapes because the fallback "does not bypass" membership (spec §2).

### `plan.py` (MODIFY) — block F: render + assemble
```python
    async def _render_all(self, images: Dict[str, Image.Image], perceptions: List[PerceptionResult],
                          identifications: List[IdentificationResult], comparison: ComparisonResult,
                          output_dir: Optional[Path], single_sfx: Optional[str]) -> List[RenderRecord]:
        """Render every successfully processed image with ITS OWN boxes only."""
        records: List[RenderRecord] = []
        for perception, identification in zip(perceptions, identifications):
            img_id = perception.image_id
            sfx = single_sfx if single_sfx is not None else f"_{img_id}"
            save_to = str(output_dir / f"compliance_render{sfx}.png") if output_dir else None
            products, shelves = self._render_inputs(perception, identification)
            rendered = await asyncio.to_thread(
                self.render_evaluated_image, images[img_id],
                shelf_regions=shelves, identified_products=products, save_to=save_to,
            )
            records.append(RenderRecord(image_id=img_id, rendered_image=rendered, overlay_path=save_to))
        return records

    def _render_inputs(self, perception: PerceptionResult, identification: IdentificationResult
                       ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        """(identified_products, shelf_regions) of ONE image for rendering and the legacy result keys."""
        if perception.legacy is not None:
            return list(perception.legacy.identified_products), list(perception.legacy.shelf_regions)
        # FILL IN: project each Identification onto IdentifiedProduct(product_type="product", product_model=<product>,
        #   brand=<brand>, confidence=<raw_confidence>, detection_box=<box of the shape with the same shape_id>);
        #   shelf_regions = [] — bounded by: render_evaluated_image must keep working (it reads detection_box,
        #   product_model, product_type; read plan.py render body before mapping).
        raise NotImplementedError

    def _assemble(self, perceptions: List[PerceptionResult], identifications: List[IdentificationResult],
                  comparison: ComparisonResult, renders: List[RenderRecord], ctx: CycleContext) -> Dict[str, Any]:
        """Eight legacy keys + additive keys."""
        first = renders[0] if renders else None
        products, shelves = (self._render_inputs(perceptions[0], identifications[0]) if perceptions else ([], []))
        sources = {p.detection_source for p in perceptions}
        results = comparison.compliance_results
        return {
            "step3_compliance_results": results,
            "compliance_results": results,
            "overall_compliance_score": comparison.overall_compliance_score,
            "overall_compliant": bool(comparison.overall_compliant and results),
            "identified_products": products,
            "shelf_regions": shelves,
            "rendered_image": first.rendered_image if first else None,
            "overlay_path": first.overlay_path if first else None,
            # additive
            "detections": [p.model_dump() for p in perceptions],
            "identifications": [i.model_dump() for i in identifications],
            "position_results": comparison.position_results,
            "shelf_scores": comparison.shelf_scores,
            "coverage": comparison.coverage,
            "definition_coverage": comparison.definition_coverage,
            "assessment_status": comparison.assessment_status,
            "strict_compliance_score": comparison.strict_compliance_score,
            "evidence_quality": comparison.evidence_quality,
            "detection_source": (sources.pop() if len(sources) == 1 else ("mixed" if sources else None)),
            "ocr_available": bool(ctx.ocr.available),
            "resolved_backend": self.resolved_backend.as_string(),
            "renders": renders,
            "errors": list(ctx.errors) + list(comparison.errors),
        }
```
**Why**: `bool(... and results)` enforces "an empty result list is never a pass" at the public boundary even if a
hook misbehaves. `identified_products` / `shelf_regions` stay populated for migrated types so existing consumers
and `render_evaluated_image` keep working (spec §7 Patterns).

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py` (CREATE) — block G
```python
"""Offline tests of the PlanogramCompliance.run() template (FEAT-574, Module 15)."""
from __future__ import annotations

from typing import Any, List

import pytest
from PIL import Image

from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType

LEGACY_KEYS = {"step3_compliance_results", "compliance_results", "overall_compliance_score", "overall_compliant",
               "identified_products", "shelf_regions", "rendered_image", "overlay_path"}
ADDITIVE_KEYS = {"detections", "identifications", "position_results", "shelf_scores", "coverage",
                 "definition_coverage", "assessment_status", "strict_compliance_score", "evidence_quality",
                 "detection_source", "ocr_available", "resolved_backend", "renders", "errors"}


class _StubCycleType(AbstractPlanogramType):
    """Migrated-style stub: records calls, returns canned contract objects."""
    uses_enhanced_image = False
    # FILL IN: perceive/identify/compare returning minimal valid PerceptionResult / IdentificationResult /
    #   ComparisonResult; class attributes `min_usable_shapes`, `fail_on` (set of image ids that raise) —
    #   bounded by the contract field names in planogram/contracts.py.


@pytest.fixture
def pipeline(monkeypatch, fake_vision_client):
    """PlanogramCompliance wired to the stub type and the fake client."""
    monkeypatch.setitem(PlanogramCompliance._PLANOGRAM_TYPES, "stub_cycle", _StubCycleType)
    config = PlanogramConfig(planogram_type="stub_cycle", planogram_config={})
    return PlanogramCompliance(planogram_config=config, llm=fake_vision_client)


async def test_run_single_image_returns_legacy_and_additive_keys(pipeline, synthetic_shelf_image): ...
async def test_run_preserves_eight_keys_for_every_type(): ...            # spec §4 — parametrised over _PLANOGRAM_TYPES with hooks patched
async def test_run_single_image_keeps_sfx_filename_rule(pipeline, synthetic_shelf_image, tmp_path): ...
async def test_run_multi_image_renders_and_failures(pipeline, synthetic_shelf_image, tmp_path): ...   # spec §4
async def test_run_all_images_failed_is_inconclusive(pipeline, synthetic_shelf_image): ...
async def test_run_image_id_length_mismatch_raises(pipeline, synthetic_shelf_image): ...
async def test_run_fallback_sets_detection_source_llm(pipeline, synthetic_shelf_image, monkeypatch): ...   # spec §4
async def test_run_fallback_failure_populates_errors(pipeline, synthetic_shelf_image, monkeypatch): ...
async def test_run_uses_untouched_image_for_migrated_types(pipeline, synthetic_shelf_image, monkeypatch): ...  # spec §4
async def test_run_closes_executor_on_cancellation(pipeline, synthetic_shelf_image, monkeypatch): ...
async def test_empty_compliance_results_never_compliant(pipeline, synthetic_shelf_image): ...
```
**Why**: four of these names are fixed by spec §4; the rest pin the acceptance criteria below.

### FILL IN checklist
- [ ] `plan.py::__init__` — call `validate_contract()` only if the base type does not; bounded by AC-2
- [ ] `plan.py::run` — release the vision adapter in `finally` if it exposes a closer; bounded by AC-9
- [ ] `plan.py::_normalize_inputs` — duplicate ids / empty list ⇒ `ValueError`; bounded by AC-3
- [ ] `plan.py::_fallback_if_needed` — failed-fallback error message; replaced perception; bounded by AC-5
- [ ] `plan.py::_compare` — all-failed inconclusive `ComparisonResult`; bounded by AC-6
- [ ] `plan.py::_render_inputs` — projection for migrated types; bounded by "render_evaluated_image must keep working"
- [ ] `test_run_template.py` — stub type + eleven test bodies

---

## Acceptance Criteria

- [ ] AC-1: `run()` returns all eight legacy keys for every planogram type and every additive key listed in Scope; `compliance_results is step3_compliance_results`.
- [ ] AC-2: `plan.py` contains no ROI-first orchestration, no `compute_roi` / `detect_objects` / `check_planogram_compliance` call and no flag that re-enables the old cycle; an incomplete type fails at construction.
- [ ] AC-3: `run(image=[...])` works; default ids `img0..imgN`; a mismatching `image_id` sequence raises `ValueError`; the single-image call keeps `compliance_render{_sfx}.png`.
- [ ] AC-4: Migrated types (`uses_enhanced_image=False`) receive the untouched image (`_enhance_image` not called); legacy types still get the enhanced image.
- [ ] AC-5: Usable on-fixture shapes under `min_usable_shapes` trigger the LLM detector, membership is applied to its shapes and `detection_source == "llm"`; a failed fallback populates `errors`; off-fixture shapes never count toward the threshold.
- [ ] AC-6: One failed photo is isolated in `errors`; all photos failed ⇒ `rendered_image`/`overlay_path` `None`, `overall_compliant=False`, `assessment_status="inconclusive"`.
- [ ] AC-7: `renders` has one `RenderRecord` per processed image; singular keys point at the first successful image; no box from one photo is drawn on another.
- [ ] AC-8: `overall_compliant` is never `True` with an empty `compliance_results`.
- [ ] AC-9: `CpuExecutor.aclose()` is awaited on success, failure and cancellation.
- [ ] AC-10: `render_evaluated_image` is byte-identical; `_PLANOGRAM_TYPES` is untouched.
- [ ] All tests pass: `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_legacy_run_orchestration.py -q`

---

## Test Specification

```python
async def test_run_multi_image_renders_and_failures(pipeline, synthetic_shelf_image, tmp_path):
    """Second photo fails: isolated in errors; renders only for successes; singular keys = first success."""
    _StubCycleType.fail_on = {"b"}
    result = await pipeline.run([synthetic_shelf_image, synthetic_shelf_image, synthetic_shelf_image],
                                output_dir=tmp_path, image_id=["a", "b", "c"])
    assert [r.image_id for r in result["renders"]] == ["a", "c"]
    assert result["overlay_path"].endswith("compliance_render_a.png")
    assert any(e.startswith("b:") for e in result["errors"])
    assert LEGACY_KEYS | ADDITIVE_KEYS <= set(result)


async def test_run_all_images_failed_is_inconclusive(pipeline, synthetic_shelf_image):
    _StubCycleType.fail_on = {"img0"}
    result = await pipeline.run(synthetic_shelf_image)
    assert result["rendered_image"] is None and result["overlay_path"] is None
    assert result["overall_compliant"] is False
    assert str(result["assessment_status"]).endswith("inconclusive")
    assert result["compliance_results"] == []


async def test_run_single_image_keeps_sfx_filename_rule(pipeline, synthetic_shelf_image, tmp_path):
    r1 = await pipeline.run(synthetic_shelf_image, output_dir=tmp_path)
    r2 = await pipeline.run(synthetic_shelf_image, output_dir=tmp_path, image_id="store7")
    assert r1["overlay_path"].endswith("compliance_render.png")
    assert r2["overlay_path"].endswith("compliance_render_store7.png")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3443-run-template.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
