# TASK-3424: Characterization test of the complete legacy run() orchestration

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3420
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 3**: "Legacy adapter characterization tests must cover the
**complete** old orchestration, including enhancement, promotional OCR,
poster/logo injection, virtual shelves, shelf assignment, fact-tag refinement
and corroboration. Delegating only the three named public methods is
insufficient." Today that orchestration is inlined in
`PlanogramCompliance.run()` (`plan.py:71-370`, the 20 steps listed in spec §6).
Later tasks move steps 5-17 behind the type's default *perceive* hook and
replace `run()` with a three-stage template. This test is the regression net
that proves — **at the public `run()` level** — that a legacy type still goes
through exactly the same sequence with exactly the same effects.

Because it must stay green across those refactors, the test:
- drives only the **public** entry point (`PlanogramCompliance(...)` +
  `await pipeline.run(...)`), never an internal helper of `run()`;
- observes the sequence through **spies installed on the type-handler and
  pipeline instances** (the handler methods keep their names and are still
  called by whoever owns the orchestration);
- uses the shared fake from TASK-3420
  (`packages/ai-parrot-pipelines/tests/conftest.py`) as **both** `pipeline.llm`
  and `pipeline.roi_client`, and never asserts the `model=` kwarg.

---

## Scope

- Create one test module that runs a real `PlanogramCompliance`
  (`planogram_type="product_on_shelves"`) offline and pins:
  1. **Order** of the orchestration steps (spec §6 steps 2→19).
  2. `open_image` **enhances** the image (`_enhance_image` called once) on this legacy path.
  3. `compute_roi` failure is **swallowed** (bare `except`, log only) and the run continues.
  4. `detect_objects` is called with `roi=<endcap>`, `macro_objects=None`; `detect_objects_roi` is **never** called.
  5. **Promotional OCR**: trigger rule, one vision call per promo item on its crop, `no_memory=True`, `max_tokens=1024`, parsing of `CONFIRMED:` / `TEXT_FOUND:` lines, `ocr_text` / `visual_features` enrichment, forced `product_type="promotional_graphic"`, brand verification.
  6. **Virtual shelves replace** the detector's shelf regions when an endcap ROI exists.
  7. `use_fact_tag_boundaries` gates `_refine_shelves_from_fact_tags`, `use_y1_assignment`, `_ocr_fact_tags` and `_corroborate_products_with_fact_tags`.
  8. **Poster-text** and **brand-logo** injection (exact `IdentifiedProduct` shapes) *before* compliance.
  9. Aggregation: `overall_compliance_score` = plain mean; `overall_compliant` = all shelves `COMPLIANT`.
  10. The **eight result keys**, `compliance_results is step3_compliance_results`, render/overlay file naming with and without `image_id`.
  11. Today's quirk, **isolated in its own function** `test_legacy_empty_results_is_compliant_today`: empty `compliance_results` ⇒ score `0.0` **and** `overall_compliant is True`.

**NOT in scope**: per-shelf scoring math (TASK-3422); helper internals
(TASK-3423); other planogram types; any production code change.

> ⚠ `test_legacy_empty_results_is_compliant_today` is the **only** expectation a
> later task (TASK-3442, the type-hooks task) is allowed to flip — spec §2 makes
> "an empty result list is never a pass" the single intended legacy deviation.
> Keep it in its own function so that flip is a one-function edit.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_legacy_run_orchestration.py` | CREATE | Public-level characterization of the legacy `run()` sequence |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (re-read 2026-09-18 on `dev`).

### Verified Imports
```python
import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from PIL import Image
from parrot_pipelines.models import PlanogramConfig                                    # models.py:29
from parrot_pipelines.planogram import PlanogramCompliance                             # planogram/__init__.py:16-18 (lazy)
from parrot.models.detections import (BoundingBox, Detection, DetectionBox,
                                      IdentifiedProduct, ShelfRegion)                  # detections.py:5, :24, :37, :71, :62
from parrot.models.compliance import ComplianceResult, ComplianceStatus                # compliance.py:32, :9
```
Fixtures `fake_vision_client`, `synthetic_shelf_image`: from
`packages/ai-parrot-pipelines/tests/conftest.py` (**created by TASK-3420 — dependency**).

### Existing Signatures to Use
```python
# Created by TASK-3420 (dependency) — packages/ai-parrot-pipelines/tests/conftest.py
class FakeVisionClient:            # client_name = "fake"; model = None; truthy instance
    calls: List[Dict[str, Any]]    # {"method","prompt","image","image_size","kwargs"}
    def queue(self, method: str, *responses: Any) -> None
    def calls_to(self, method: str) -> List[Dict[str, Any]]
    async def ask_to_image(self, prompt: str, image: Any, **kwargs: Any) -> Any     # str → obj.output; empty queue → output ""
    async def detect_objects(self, image, prompt, reference_images=None, output_dir=None, **kwargs) -> List[Dict[str, Any]]
    async def __aenter__(self) -> "FakeVisionClient"                                  # returns self

# packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py
class AbstractPipeline(ABC):                                                          # :13
    def __init__(self, llm: Any = None, llm_provider: str = "google", llm_model: Optional[str] = None, **kwargs)  # :16-40
    #   llm given ⇒ self.llm_provider = llm.client_name.lower() :33-34
    #   :38-40 lazy `from parrot.clients.google import GoogleGenAIClient`; self.roi_client = GoogleGenAIClient(...)  UNCONDITIONAL today
    def open_image(self, image_path: Union[Path, Image.Image]) -> Image.Image          # :73-87 → self._enhance_image(img) :82
    def _enhance_image(self, pil_img, brightness: float = 1.10, contrast: float = 1.20)   # :134-144

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py
class PlanogramCompliance(AbstractPipeline):                                          # :24
    def __init__(self, planogram_config: PlanogramConfig, llm: Any = None, llm_provider: str = "google",
                 llm_model: Optional[str] = None, **kwargs: Any)                      # :45-69 → self._type_handler :69
    async def run(self, image, output_dir=None, image_id: Optional[str] = None, **kwargs) -> Dict[str, Any]   # :71-370
    def render_evaluated_image(self, image, *, shelf_regions=None, detections=None, identified_products=None,
                               mode="identified", show_shelves=True, save_to=None) -> Image.Image   # :376-485 (SYNC)
# run() TODAY (line anchors):
#   _sfx = f"_{image_id}" if image_id else ""                                          :82
#   img = self.open_image(image)                                                       :88
#   compute_roi in bare try/except → logger.error only                                 :98-102
#   debug overlay → Path(output_dir)/f"debug_step1_roi{_sfx}.png"                      :104-130
#   detect_objects(img, roi=endcap, macro_objects=None)                                :132-136
#   promo OCR trigger: "logo ad" in model.lower() or "backlit" in model.lower() or product_type == "promotional_graphic"  :175
#     crop = detection_box; `async with self.roi_client as client` :210;
#     client.ask_to_image(image=p_img, prompt=ocr_prompt, model="gemini-3.5-flash", no_memory=True, max_tokens=1024) :211-217
#     "CONFIRMED:" lines → visual_features; "TEXT_FOUND:" lines → visual_features; other lines → clean_text →
#       p.ocr_text = clean_text; p.visual_features += [f"ocr:{clean_text}", clean_text]            :225-248
#     p.product_type = "promotional_graphic" :250; brand in OCR text / model / confirmed feature ⇒ p.brand = planogram brand :252-262
#   if endcap and endcap.bbox: hasattr "_generate_virtual_shelves" ⇒ shelf_regions = virtual_shelves (REPLACES)   :266-273
#   planogram_config["use_fact_tag_boundaries"] and shelf_regions ⇒ _refine_shelves_from_fact_tags(...) (no hasattr guard) :281-283
#   hasattr "_assign_products_to_shelves" ⇒ (products, shelf_regions, use_y1_assignment=<flag>)                   :286-290
#   flag ⇒ hasattr "_ocr_fact_tags" (…, shelf_regions=shelf_regions) ⇒ hasattr "_corroborate_products_with_fact_tags"  :293-304
#   panel_text.content ⇒ IdentifiedProduct(product_type="text_overlay", product_model="poster_text",
#       shelf_location="header", visual_features=[f"ocr:{content}"], detection_box from FRACTIONAL bbox × image size)  :307-324
#   brand ⇒ IdentifiedProduct(product_type="brand_logo", product_model=brand.label or "brand_logo",
#       brand=planogram.brand, shelf_location="header")                                                          :326-343
#   compliance_results = handler.check_planogram_compliance(products, description)  (SYNC)                        :346
#   overall_score = mean(compliance_score); overall_compliant = all(status == COMPLIANT); defaults 0.0 / True     :347-351
#   render → save_to = Path(output_dir)/f"compliance_render{_sfx}.png"                                            :353-359
#   return keys: step3_compliance_results, compliance_results (SAME list), overall_compliance_score,
#                overall_compliant, identified_products, shelf_regions, rendered_image, overlay_path              :361-370

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py
async def compute_roi(self, img) -> Tuple[endcap_det, panel_det, brand_det, text_det, raw_dets]    # :58-82
#   endcap_det is a parrot.models.detections.Detection whose .bbox is a FRACTIONAL BoundingBox (:958-969)
async def detect_objects_roi(self, img, roi) -> List[Detection]                                     # :84-103 (returns []; NEVER called by run())
async def detect_objects(self, img, roi, macro_objects) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]   # :119-222
def check_planogram_compliance(self, identified_products, planogram_description) -> List[ComplianceResult]     # :384-795 SYNC
def _generate_virtual_shelves(self, roi_bbox, image_size, planogram) -> List[ShelfRegion]          # :1132-1217 (fractions ⇒ scaled :1143-1147)

# packages/ai-parrot/src/parrot/models/detections.py
class BoundingBox(BaseModel)   # :5-22   x1,y1,x2,y2: float in [0,1]
class Detection(BaseModel)     # :24-29  label: Optional[str], confidence: float (req), content: Optional[str], bbox: BoundingBox (req)
```

### Does NOT Exist
- ~~a call to `detect_objects_roi` from `run()`~~ — declared abstract, never invoked; pin that it is **not** called.
- ~~a numeric global compliance threshold~~ — `overall_compliant` is a boolean AND over shelf statuses.
- ~~an `_enhance_image` call inside `run()`~~ — enhancement happens inside `open_image` (`abstract.py:82`); spy `_enhance_image` on the pipeline instance.
- ~~a `hasattr` guard around `_refine_shelves_from_fact_tags`~~ — it is a base-class method, called unguarded.
- ~~`structured_output` in the promotional OCR call~~ — plain text in `msg.output`.
- ~~a network-free `GoogleGenAIClient()` guarantee~~ — the constructor is invoked unconditionally today; **patch it** during pipeline construction (the patch stays harmless once a later task deletes that line).
- ~~other tasks' new modules~~ — this test must import nothing beyond the Verified Imports; it may not reference the future hook/adapter/contract modules, precisely so it survives their introduction unchanged.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_legacy_run_orchestration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance.run",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance.render_evaluated_image",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py#AbstractPipeline.__init__",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py#AbstractPipeline.open_image",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py#AbstractPipeline._enhance_image",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves.compute_roi",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves.detect_objects",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves.detect_objects_roi",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves.check_planogram_compliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._generate_virtual_shelves",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._assign_products_to_shelves",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._ocr_fact_tags",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._corroborate_products_with_fact_tags",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType._refine_shelves_from_fact_tags",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/models.py#PlanogramConfig",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#Detection",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#BoundingBox",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#IdentifiedProduct",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#ShelfRegion",
    "sym:packages/ai-parrot/src/parrot/models/compliance.py#ComplianceResult",
    "sym:packages/ai-parrot/src/parrot/models/compliance.py#ComplianceStatus"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Public level only.** Build `PlanogramCompliance(planogram_config=cfg, llm=fake)`
  and call `run()`. Stub exactly the three legacy *type* methods
  (`compute_roi`, `detect_objects`, and — where the test needs canned shelf
  results — `check_planogram_compliance`) **on the handler instance**
  (`pipeline._type_handler`). Everything else runs for real.
- **Spies on instances, not on modules**: install them with the `spy` helper
  below on `pipeline._type_handler` / `pipeline`. Do **not** `patch` a name
  inside the `plan` module — the orchestration is about to move out of that module.
- **Same fake on both attributes**: after construction set
  `pipeline.roi_client = fake` (and `pipeline.llm` already is `fake`).
  Never assert `kwargs["model"]`.
- Construct inside `patch("parrot.clients.google.GoogleGenAIClient", MagicMock())`
  so no real Google client is built today.
- `compute_roi` stubs return **fractional** `Detection`/`BoundingBox` objects
  (that is what `_find_poster` returns); `detect_objects` stubs return pixel
  `DetectionBox`es on the 800×1000 `synthetic_shelf_image`.
- Order is asserted as a **subsequence** of the spy log (extra calls are
  tolerated, reordering is not).
- `pytest.ini` has `asyncio_mode = auto`. Use `tmp_path` for `output_dir`.
- Run with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src pytest <file> -q` inside a worktree.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:71-370` — the sequence under test
- `packages/ai-parrot-pipelines/tests/conftest.py` — fixtures (TASK-3420)

---

## Implementation Blueprint

> Write the blocks (consecutive parts of ONE file), then complete every `# FILL IN:`.
> Never rename `test_legacy_empty_results_is_compliant_today`.

### Steps (in order)
1. Write Part 1 (config, stubs, `spy`, `build_pipeline`) — *why*: all tests share one construction path, so the Google-client patch and the dual fake assignment exist once.
2. Write Part 2 (order + promo OCR + injections) and make it pass — *why*: this is the core regression net for moving steps 5-17 out of `run()`.
3. Write Part 3 (fact-tag gating, ROI failure, aggregation, keys/files, empty-results quirk) — *why*: these are the branches most likely to be dropped in a refactor.
4. For each `FILL IN`, run once, inspect, pin the observed value if it satisfies the bound in the marker; otherwise pin what the code does and note it.
5. Run the Validation Command and `ruff check` on the file.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_legacy_run_orchestration.py` (CREATE) — Part 1: construction helpers
```python
"""Characterization test: the COMPLETE legacy run() orchestration, observed at the public level (FEAT-574)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from parrot.models.compliance import ComplianceResult, ComplianceStatus
from parrot.models.detections import BoundingBox, Detection, DetectionBox, IdentifiedProduct, ShelfRegion
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram import PlanogramCompliance


def raw_config(**flags: Any) -> Dict[str, Any]:
    """header (promo) + top (two products); ``flags`` e.g. use_fact_tag_boundaries=True."""
    return {
        "brand": "TestBrand", "category": "Scanners",
        "aisle": {"name": "Electronics > Test", "lighting_conditions": "normal"},
        "shelves": [
            {"level": "header", "height_ratio": 0.2,
             "products": [{"name": "TestBrand Backlit", "product_type": "promotional_graphic",
                           "visual_features": ["illuminated logo"],
                           "text_requirements": [{"required_text": "Hello Savings"}]}]},
            {"level": "top", "height_ratio": 0.8,
             "products": [{"name": "ES-400", "product_type": "product"}, {"name": "RR-60", "product_type": "product"}]},
        ],
        **flags,
    }


def spy(obj: Any, name: str, log: List[str]) -> None:
    """Wrap ``obj.<name>`` (sync or async) so every call appends ``name`` to ``log`` and still runs for real."""
    original = getattr(obj, name)
    if asyncio.iscoroutinefunction(original):
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            log.append(name)
            return await original(*args, **kwargs)
    else:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            log.append(name)
            return original(*args, **kwargs)
    setattr(obj, name, wrapper)


def roi_stub() -> Tuple[Detection, None, Detection, Detection, list]:
    """(endcap, ad, brand, panel_text, raw_dets) with FRACTIONAL boxes, as _find_poster returns them."""
    endcap = Detection(label="endcap", confidence=0.9, bbox=BoundingBox(x1=0.1, y1=0.0, x2=0.9, y2=1.0))
    brand = Detection(label="TestBrand", confidence=0.8, bbox=BoundingBox(x1=0.4, y1=0.02, x2=0.6, y2=0.08))
    text = Detection(label="poster_text", confidence=0.7, content="  Hello Savings  ",
                     bbox=BoundingBox(x1=0.2, y1=0.1, x2=0.8, y2=0.18))
    return endcap, None, brand, text, []


def detected_stub() -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
    """A backlit promo on the header + one product, and ONE detector shelf that virtual shelves must replace."""
    promo = IdentifiedProduct(product_type="graphic", product_model="TestBrand Backlit", confidence=0.9,
                              detection_box=DetectionBox(x1=100, y1=10, x2=700, y2=190, confidence=0.9))
    es400 = IdentifiedProduct(product_type="product", product_model="ES-400", confidence=0.9,
                              detection_box=DetectionBox(x1=120, y1=300, x2=320, y2=700, confidence=0.9))
    detector_shelf = ShelfRegion(shelf_id="detector_only", level="detector_only",
                                 bbox=DetectionBox(x1=0, y1=0, x2=800, y2=1000, confidence=1.0))
    return [promo, es400], [detector_shelf]


def build_pipeline(fake: Any, log: List[str], **flags: Any) -> PlanogramCompliance:
    """Real pipeline + real ProductOnShelves handler; legacy public methods stubbed, everything else spied."""
    cfg = PlanogramConfig(config_name="legacy", planogram_type="product_on_shelves", planogram_config=raw_config(**flags),
                          roi_detection_prompt="roi", object_identification_prompt="objects")
    with patch("parrot.clients.google.GoogleGenAIClient", MagicMock()):
        pipeline = PlanogramCompliance(planogram_config=cfg, llm=fake)
    pipeline.roi_client = fake                      # SAME object as pipeline.llm — refactor-proof
    handler = pipeline._type_handler
    handler.compute_roi = AsyncMock(return_value=roi_stub())
    handler.detect_objects = AsyncMock(return_value=detected_stub())
    handler.detect_objects_roi = AsyncMock(return_value=[])
    for name in ("compute_roi", "detect_objects", "_generate_virtual_shelves", "_refine_shelves_from_fact_tags",
                 "_assign_products_to_shelves", "_ocr_fact_tags", "_corroborate_products_with_fact_tags",
                 "check_planogram_compliance"):
        spy(handler, name, log)
    for name in ("_enhance_image", "render_evaluated_image"):
        spy(pipeline, name, log)
    return pipeline


def assert_subsequence(log: List[str], expected: List[str]) -> None:
    """Every name of ``expected`` appears in ``log`` in that relative order."""
    it = iter(log)
    assert all(name in it for name in expected), f"order broken: {log}"
```
**Why this shape**: spies live on **instances** because the code that calls
these methods is about to move from `run()` into the type's default hook — the
callee names are the stable seam, the caller module is not. `AsyncMock` objects
are wrapped by `spy` too (`asyncio.iscoroutinefunction(AsyncMock())` is true),
so stubbed and real methods land in one ordered log.

### same file — Part 2: order, promotional OCR, injections
```python
async def test_legacy_run_orchestration_order(fake_vision_client, synthetic_shelf_image, tmp_path: Path) -> None:
    """Spec §6 steps 2→19 happen in order; detect_objects_roi is never called."""
    log: List[str] = []
    pipeline = build_pipeline(fake_vision_client, log, use_fact_tag_boundaries=True)
    await pipeline.run(synthetic_shelf_image, output_dir=tmp_path)
    assert_subsequence(log, ["_enhance_image", "compute_roi", "detect_objects", "_generate_virtual_shelves",
                             "_refine_shelves_from_fact_tags", "_assign_products_to_shelves", "_ocr_fact_tags",
                             "_corroborate_products_with_fact_tags", "check_planogram_compliance",
                             "render_evaluated_image"])
    assert log.count("_enhance_image") == 1                              # legacy path works on the ENHANCED image
    pipeline._type_handler.detect_objects_roi.assert_not_called()
    # FILL IN: assert detect_objects call arguments — bounded by plan.py:132-136: kwargs roi is the endcap
    #          Detection returned by compute_roi and macro_objects is None (inspect the AsyncMock kept before spying,
    #          or make roi_stub()/AsyncMock module-level so the test can reach await_args).
    # FILL IN: the promo OCR vision call happens AFTER detect_objects and BEFORE _generate_virtual_shelves —
    #          bounded by: record the fake's call count inside a side_effect of the _generate_virtual_shelves spy
    #          (or add "ask_to_image" to the log by spying fake.ask_to_image with the same `spy` helper).


async def test_legacy_promotional_ocr_enrichment(fake_vision_client, synthetic_shelf_image) -> None:
    """One vision call per promo item, on its crop; answer lines are parsed into the product."""
    fake_vision_client.queue("ask_to_image", "TestBrand EcoTank\nCONFIRMED: illuminated logo\nTEXT_FOUND: Hello Savings")
    log: List[str] = []
    pipeline = build_pipeline(fake_vision_client, log)
    result = await pipeline.run(synthetic_shelf_image)
    promo = next(p for p in result["identified_products"] if p.product_model == "TestBrand Backlit")
    assert promo.product_type == "promotional_graphic"                   # forced (was "graphic")
    assert promo.ocr_text == "TestBrand EcoTank"
    assert promo.brand == "TestBrand"                                    # verified via OCR text
    for feature in ("ocr:TestBrand EcoTank", "TestBrand EcoTank", "illuminated logo", "Hello Savings"):
        assert feature in promo.visual_features
    call = fake_vision_client.calls_to("ask_to_image")[0]
    assert call["image_size"] == (600, 180)                              # the promo's detection_box crop
    assert call["kwargs"]["no_memory"] is True and call["kwargs"]["max_tokens"] == 1024     # never assert "model"
    # FILL IN: prompt content — bounded by plan.py:188-209: contains "- illuminated logo" and '- "Hello Savings"'.
    # FILL IN: non-promo products trigger NO call — bounded by: exactly one ask_to_image call in this run
    #          (use_fact_tag_boundaries is off, and detect_objects is stubbed).


async def test_legacy_promo_ocr_failure_is_swallowed(fake_vision_client, synthetic_shelf_image) -> None:
    """A failing promo OCR call is logged; the run completes and the product keeps its original type."""
    fake_vision_client.queue("ask_to_image", RuntimeError("503"))
    pipeline = build_pipeline(fake_vision_client, [])
    result = await pipeline.run(synthetic_shelf_image)
    promo = next(p for p in result["identified_products"] if p.product_model == "TestBrand Backlit")
    assert promo.product_type == "graphic"


async def test_legacy_virtual_shelves_replace_detector_shelves(fake_vision_client, synthetic_shelf_image) -> None:
    """With an endcap ROI the virtual shelves REPLACE whatever detect_objects returned."""
    pipeline = build_pipeline(fake_vision_client, [])
    result = await pipeline.run(synthetic_shelf_image)
    levels = [s.level for s in result["shelf_regions"]]
    assert "detector_only" not in levels
    # FILL IN: pin `levels` — bounded by: one virtual shelf per configured shelf ⇒ ["header", "top"].
    # FILL IN: ES-400 was assigned to a shelf — bounded by: its shelf_location == "top".


async def test_legacy_poster_text_and_brand_logo_injection(fake_vision_client, synthetic_shelf_image) -> None:
    """panel_text and brand detections become synthetic header products BEFORE compliance runs."""
    seen: List[List[str]] = []
    pipeline = build_pipeline(fake_vision_client, [])
    original = pipeline._type_handler.check_planogram_compliance

    def capture(products: List[IdentifiedProduct], description: Any) -> List[ComplianceResult]:
        seen.append([p.product_type for p in products])
        return original(products, description)

    pipeline._type_handler.check_planogram_compliance = capture
    result = await pipeline.run(synthetic_shelf_image)
    assert "text_overlay" in seen[0] and "brand_logo" in seen[0]
    text = next(p for p in result["identified_products"] if p.product_type == "text_overlay")
    assert (text.product_model, text.shelf_location, text.visual_features) == ("poster_text", "header", ["ocr:Hello Savings"])
    # FILL IN: pin text.detection_box — bounded by plan.py:311-317: fractions × (800, 1000) ⇒ (160, 100, 640, 180),
    #          ocr_text "Hello Savings" (stripped), confidence 0.7.
    # FILL IN: pin the brand_logo product — bounded by plan.py:326-341: product_model "TestBrand", brand "TestBrand",
    #          shelf_location "header", box (320, 20, 480, 80), confidence 0.8.
```
**Why**: the injection test captures the list **as seen by**
`check_planogram_compliance`, because "injected before compliance" is the
behaviour that matters — asserting only on the returned list would not catch an
adapter that injects too late.

### same file — Part 3: gating, failure, aggregation, keys, empty-results quirk
```python
async def test_legacy_fact_tag_steps_are_gated_by_config_flag(fake_vision_client, synthetic_shelf_image) -> None:
    """Without use_fact_tag_boundaries: no refine, no fact-tag OCR, no corroboration, use_y1_assignment False."""
    log: List[str] = []
    pipeline = build_pipeline(fake_vision_client, log)
    await pipeline.run(synthetic_shelf_image)
    for name in ("_refine_shelves_from_fact_tags", "_ocr_fact_tags", "_corroborate_products_with_fact_tags"):
        assert name not in log
    assert "_assign_products_to_shelves" in log
    # FILL IN: pin use_y1_assignment — bounded by plan.py:286-290: False here, True when the flag is set
    #          (capture kwargs by wrapping handler._assign_products_to_shelves before running, in both configs).


async def test_legacy_compute_roi_failure_is_swallowed(fake_vision_client, synthetic_shelf_image) -> None:
    """compute_roi raising is only logged: detection still runs with roi=None and no virtual shelves are built."""
    log: List[str] = []
    pipeline = build_pipeline(fake_vision_client, log)
    pipeline._type_handler.compute_roi = AsyncMock(side_effect=RuntimeError("no poster"))
    result = await pipeline.run(synthetic_shelf_image)
    assert "_generate_virtual_shelves" not in log
    assert [s.level for s in result["shelf_regions"]] == ["detector_only"]
    # FILL IN: bounded by plan.py:91-102 + :307/:327 — detect_objects received roi=None; no text_overlay and no
    #          brand_logo product was injected.


def _shelf_result(level: str, status: ComplianceStatus, score: float) -> ComplianceResult:
    return ComplianceResult(shelf_level=level, expected_products=[], found_products=[], missing_products=[],
                            unexpected_products=[], compliance_status=status, compliance_score=score)


async def test_legacy_overall_aggregation(fake_vision_client, synthetic_shelf_image) -> None:
    """overall score = unweighted mean of shelf scores; overall_compliant = every shelf COMPLIANT (no threshold)."""
    pipeline = build_pipeline(fake_vision_client, [])
    pipeline._type_handler.check_planogram_compliance = MagicMock(return_value=[
        _shelf_result("header", ComplianceStatus.COMPLIANT, 1.0), _shelf_result("top", ComplianceStatus.NON_COMPLIANT, 0.5)])
    result = await pipeline.run(synthetic_shelf_image)
    assert result["overall_compliance_score"] == pytest.approx(0.75)
    assert result["overall_compliant"] is False
    # FILL IN: second run with both shelves COMPLIANT (scores 0.9 and 0.81) ⇒ mean 0.855 and overall_compliant True
    #          — bounded by plan.py:350-351 (a high mean alone never makes it compliant; statuses do).


async def test_legacy_empty_results_is_compliant_today(fake_vision_client, synthetic_shelf_image) -> None:
    """TODAY's quirk (plan.py:347-351): an empty result list ⇒ score 0.0 but overall_compliant True.

    The type-hooks task (TASK-3442) intentionally flips ONLY this expectation to False — keep it isolated here.
    """
    pipeline = build_pipeline(fake_vision_client, [])
    pipeline._type_handler.check_planogram_compliance = MagicMock(return_value=[])
    result = await pipeline.run(synthetic_shelf_image)
    assert result["overall_compliance_score"] == 0.0
    assert result["overall_compliant"] is True


EIGHT_KEYS = {"step3_compliance_results", "compliance_results", "overall_compliance_score", "overall_compliant",
              "identified_products", "shelf_regions", "rendered_image", "overlay_path"}


async def test_legacy_result_keys_and_output_files(fake_vision_client, synthetic_shelf_image, tmp_path: Path) -> None:
    """Eight keys, same list object twice, and the render/overlay naming with and without image_id."""
    pipeline = build_pipeline(fake_vision_client, [])
    plain = await pipeline.run(synthetic_shelf_image, output_dir=tmp_path)
    assert EIGHT_KEYS <= set(plain)                                       # additive keys are allowed later
    assert plain["compliance_results"] is plain["step3_compliance_results"]
    assert isinstance(plain["rendered_image"], Image.Image)
    assert plain["overlay_path"] == str(tmp_path / "compliance_render.png") and Path(plain["overlay_path"]).is_file()
    assert (tmp_path / "debug_step1_roi.png").is_file()
    # FILL IN: image_id suffix — bounded by plan.py:82/:358/:369: run(..., image_id="store7") ⇒
    #          "compliance_render_store7.png" and "debug_step1_roi_store7.png" exist.
    # FILL IN: no output_dir ⇒ overlay_path is None and nothing is written (run once more without output_dir).
```
**Why**: `EIGHT_KEYS <= set(result)` (not `==`) because spec G2 makes new keys
**additive** — the run-template task will add keys, and this test must not
break when it does. The empty-results quirk lives alone in
`test_legacy_empty_results_is_compliant_today` so the one sanctioned legacy
deviation (spec §2, §5 "an empty result list is never a pass") is a one-function flip.

### FILL IN checklist
- [ ] `test_legacy_run_orchestration_order` — `detect_objects` arguments (`roi=<endcap>`, `macro_objects=None`)
- [ ] `test_legacy_run_orchestration_order` — promo OCR call positioned between `detect_objects` and `_generate_virtual_shelves`
- [ ] `test_legacy_promotional_ocr_enrichment` — prompt content; exactly one vision call
- [ ] `test_legacy_virtual_shelves_replace_detector_shelves` — levels `["header", "top"]`; ES-400 on `"top"`
- [ ] `test_legacy_poster_text_and_brand_logo_injection` — text box `(160,100,640,180)`; brand-logo product shape
- [ ] `test_legacy_fact_tag_steps_are_gated_by_config_flag` — `use_y1_assignment` False/True
- [ ] `test_legacy_compute_roi_failure_is_swallowed` — `roi=None`; no injections
- [ ] `test_legacy_overall_aggregation` — all-COMPLIANT case
- [ ] `test_legacy_result_keys_and_output_files` — `image_id` suffix; no-`output_dir` case

---

## Acceptance Criteria

- [ ] All tests pass against **unmodified** production code
- [ ] The run is driven only through `PlanogramCompliance(...)` + `run()`; spies are installed on instances; nothing is patched inside the `plan` module
- [ ] `pipeline.roi_client is pipeline.llm` (same fake) in every test; no assertion reads `kwargs["model"]`
- [ ] The test module imports nothing beyond this task's Verified Imports
- [ ] Order, enhancement, ROI-failure swallow, promo OCR enrichment, virtual-shelf replacement, fact-tag gating, both injections, aggregation, eight keys and file naming are all pinned
- [ ] `test_legacy_run_orchestration_order` exists verbatim (spec §4) and `test_legacy_empty_results_is_compliant_today` exists verbatim and is the **only** place asserting the empty-results quirk
- [ ] No production file changed; deviations listed in the Completion Note
- [ ] No linting errors: `ruff check packages/ai-parrot-pipelines/tests/planogram_cycle/test_legacy_run_orchestration.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_legacy_run_orchestration.py -q`

---

## Test Specification

The blueprint **is** the scaffold: 10 test functions —
`test_legacy_run_orchestration_order`, `test_legacy_promotional_ocr_enrichment`,
`test_legacy_promo_ocr_failure_is_swallowed`,
`test_legacy_virtual_shelves_replace_detector_shelves`,
`test_legacy_poster_text_and_brand_logo_injection`,
`test_legacy_fact_tag_steps_are_gated_by_config_flag`,
`test_legacy_compute_roi_failure_is_swallowed`, `test_legacy_overall_aggregation`,
`test_legacy_empty_results_is_compliant_today`,
`test_legacy_result_keys_and_output_files`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 3, §6 "run() TODAY", §2 legacy-adapter bullets)
2. **Check dependencies** — TASK-3420 must be done (its conftest provides the fixtures)
3. **Verify the Codebase Contract** — re-read `plan.py:71-370` once; confirm the step anchors
4. **Implement** — blueprint parts in order, complete every `# FILL IN:`
5. **Never edit production code**; never import a module that does not exist on `dev` today
6. **Commit code only** — never touch `sdd/`
7. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (FEAT-574 orchestrator)
**Date**: 2026-09-19

Implemented in fallback sequential mode (parrot-sdd-coder server unresponsive).
10 public-level characterization tests driving PlanogramCompliance(...).run() with spies on instances only (handler + pipeline + fake.ask_to_image), GoogleGenAIClient patched during construction, roi_client is llm (same fake). Pinned: step order incl. promo OCR between detect_objects and _generate_virtual_shelves; single _enhance_image; detect_objects(roi=<endcap>, macro_objects=None); detect_objects_roi never called; promo OCR enrichment (crop 600x180, no_memory, max_tokens=1024, prompt lines, one call only); OCR failure swallowed; virtual shelves ['header','top'] replace detector shelves; poster-text/brand-logo injection before compliance with exact boxes; fact-tag gating (use_y1_assignment False/True); compute_roi failure swallowed (roi=None, no injections); aggregation mean + all-COMPLIANT; empty-results quirk isolated in test_legacy_empty_results_is_compliant_today; eight keys, same list object, render/debug file naming with/without image_id, no output_dir => overlay_path None.
Deviation from the blueprint expectation: the poster-text product's ocr_text is None; the stripped 'Hello Savings' is on text.detection_box.ocr_text (plan.py builds DetectionBox(..., ocr_text=...)). Pinned as observed.
Note: the task's contract still describes AbstractPipeline.__init__ with llm_provider='google'; TASK-3427 already changed it (sentinel). Irrelevant here since llm=fake is injected.

Seat: orchestrator (fallback) · Backend: native · Model: claude-opus-5 · Attempts: 1
