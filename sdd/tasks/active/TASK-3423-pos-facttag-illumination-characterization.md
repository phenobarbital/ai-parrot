# TASK-3423: Characterization tests for fact-tag OCR, corroboration, shelf assignment and illumination

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3420
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 3** / Goal **G17**: `ProductOnShelves._ocr_fact_tags`,
`_corroborate_products_with_fact_tags`, `_assign_products_to_shelves` and the
base-class `_check_illumination` have **no tests today**. Two of them make LLM
vision calls through `self.pipeline.roi_client` with a hard-coded
`model="gemini-3.5-flash"` — exactly the call sites the provider-neutral
refactor (spec Module 6) rewrites to `self.pipeline.llm`. This task pins their
behaviour **before** that refactor, using the shared fake client from TASK-3420
(`packages/ai-parrot-pipelines/tests/conftest.py`: fixtures
`fake_vision_client`, `synthetic_shelf_image`).

**Durability rule** — these tests must stay green *through* the refactor: the
**same** fake object is assigned to both `pipeline.roi_client` and
`pipeline.llm`, and assertions never look at the `model=` kwarg value.

---

## Scope

- Create one test module pinning today's behaviour of:
  1. `AbstractPlanogramType._check_illumination` — answer parsing
     (`LIGHT_OFF` ⇒ `"illumination_status: OFF"`, anything else ⇒ `… ON`),
     exception ⇒ `None`, crop selection (`zone_bbox` pixels → `roi.bbox`
     fractions → full image), call kwargs `no_memory=True`, `max_tokens=128`.
  2. `ProductOnShelves._ocr_fact_tags` — one vision call per **non-background**
     shelf region, crop geometry (fixed 55 px strip vs detected-tag rows,
     endcap x-span ±30 px), comma parsing/upper-casing, `UNKNOWN`/empty skipped,
     raw text stored on detected tags, per-shelf exception isolation.
  3. `ProductOnShelves._corroborate_products_with_fact_tags` — in-place
     injection of a synthetic product (confidence 0.85) and the four skip rules.
  4. `ProductOnShelves._assign_products_to_shelves` — max-overlap assignment,
     `use_y1_assignment=True` centre mode (bottom→top), promotional/background
     rules, no-bbox fallback, structural types skipped.

**NOT in scope**: `check_planogram_compliance` (TASK-3422); `run()` orchestration
(TASK-3424); `_refine_shelves_from_fact_tags` / `_cluster_fact_tag_rows` (already
covered indirectly by `tests/pipelines/` grid tests — leave them); any production
code change (pin what the code does; note deviations in the Completion Note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_fact_tags_illumination_characterization.py` | CREATE | Characterization tests for the four helpers |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (re-read 2026-09-18 on `dev`).

### Verified Imports
```python
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from PIL import Image
from parrot_pipelines.models import PlanogramConfig                                   # models.py:29
from parrot_pipelines.planogram.types import ProductOnShelves                         # planogram/types/__init__.py:3
from parrot.models.detections import DetectionBox, IdentifiedProduct, ShelfRegion     # detections.py:37, :71, :62
```
Fixtures `fake_vision_client` and `synthetic_shelf_image` come from
`packages/ai-parrot-pipelines/tests/conftest.py` (**created by TASK-3420 —
dependency**); do not import the conftest module, request the fixtures.

### Existing Signatures to Use
```python
# Created by TASK-3420 (dependency) — packages/ai-parrot-pipelines/tests/conftest.py
class FakeVisionClient:
    client_name: str = "fake"; model: Optional[str] = None
    calls: List[Dict[str, Any]]                  # each: {"method","prompt","image","image_size","kwargs"}
    def queue(self, method: str, *responses: Any) -> None        # "ask_to_image" | "detect_objects"
    def calls_to(self, method: str) -> List[Dict[str, Any]]
    async def ask_to_image(self, prompt: str, image: Any, **kwargs: Any) -> Any   # str → object with .output; Exception → raised
    async def __aenter__(self) -> "FakeVisionClient"             # returns self
    # empty queue ⇒ object with .output == "" (not an error)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
async def _check_illumination(self, img: Image.Image, zone_bbox: Optional[Any] = None, roi: Optional[Any] = None,
                              planogram_description: Optional[Any] = None) -> Optional[str]       # :151-249
#   crop: zone_bbox (.x1/.y1/.x2/.y2 PIXELS, clamped) :181-187 → roi.bbox (FRACTIONS × image size) :188-193 → img.copy() :195
#   roi_small = self.pipeline._downscale_image(roi_crop, max_side=800, quality=82)                 :197
#   async with self.pipeline.roi_client as client: client.ask_to_image(image=roi_small, prompt=prompt,
#        model="gemini-3.5-flash", no_memory=True, max_tokens=128)                                :234-241
#   raw_answer = (msg.output or "").strip().upper(); exception ⇒ warning + return None             :242-245
#   "LIGHT_OFF" in raw_answer ⇒ "illumination_status: OFF" else "illumination_status: ON"         :247

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py
async def _ocr_fact_tags(self, identified_products: List[Any], img: Any, planogram_description: Any,
                         shelf_regions: Optional[List[Any]] = None) -> Dict[str, List[str]]      # :1219-1383
#   detected fact tags grouped by shelf_location (product_type == "fact_tag", has box) :1263-1266
#   only NON-background shelf_regions are OCR'd :1269-1272; none supplied ⇒ levels of detected tags :1275-1276
#   STRIP_HEIGHT = 55 :1282; endcap x-span = [min x1 - 30, max x2 + 30] over boxes wider/taller than 2 px, clamped :1287-1298
#   y-span: detected tags ⇒ [min y1 - pad, max y2 + pad], pad = max(5, int(height·0.10)) :1310-1316
#           else [shelf.bbox.y2 - 55, shelf.bbox.y2 + 20] clamped :1319-1320
#   roi_client.ask_to_image(image=row_img, prompt=prompt, model="gemini-3.5-flash", no_memory=True, max_tokens=128) :1357-1364
#   raw stored on every detected tag's .ocr_text :1368-1369; "UNKNOWN"/empty ⇒ skipped :1371-1372
#   tokens: split(","), strip quotes, UPPER-cased :1375-1378; per-shelf exception ⇒ warning, loop continues :1380-1381
def _corroborate_products_with_fact_tags(self, identified_products: List[Any], fact_tag_shelf_map: Dict[str, List[str]],
                                         planogram_description: Any) -> None                     # :1385-1492 (IN PLACE)
#   skip rules, in order: already detected on that shelf :1433-1437; cannot be normalised :1445-1450;
#   not expected on this shelf :1451-1457; belongs to another shelf :1462-1468
#   injects IdentifiedProduct(product_type="product", product_model=<ocr>, confidence=0.85, shelf_location=<shelf>,
#       ocr_text=f"fact_tag_ocr:{m}", visual_features=[f"fact_tag_confirmed:{m}"],
#       detection_box=DetectionBox(x1=0,y1=0,x2=1,y2=1,confidence=0.85)) :1474-1483; duplicates in one run prevented :1485-1486
def _assign_products_to_shelves(self, products: List[IdentifiedProduct], shelves: List[ShelfRegion],
                                use_y1_assignment: bool = False)                                  # :1494-1683 (IN PLACE, returns None)
#   no shelves ⇒ return :1511-1512; shelves sorted by bbox.y1 :1515; "gap"/"shelf" skipped :1533-1536
#   promo already on "header" kept :1537-1538; promotional + background shelf + centre inside it ⇒ bg level :1570-1581
#   no detection_box: keep valid LLM shelf_location, else MIDDLE foreground shelf (len // 2) :1593-1600
#   use_y1_assignment: bbox CENTRE, searched bottom→top, y1 as secondary hint :1606-1633
#   default: max vertical overlap (inter / product height) :1641-1656; then nearest centre :1658-1665

# normalisation used by corroboration — types/abstract.py:252-324  _base_model_from_str(s, brand=None, patterns=None) -> str
#   generic fallback "([a-z]+)[- ]?(\d{2,4})" ⇒ "ES-400" → "es-400"; text without digits (e.g. "REWARDS") → ""
```

### Does NOT Exist
- ~~tests for any of these four methods~~ — none today.
- ~~`structured_output` in these two vision calls~~ — both parse plain `msg.output` text.
- ~~`pipeline.llm` being used by these methods **today**~~ — they use `pipeline.roi_client`; a later task switches them. Tests must work for both (same fake on both attributes).
- ~~a return value from `_assign_products_to_shelves` / `_corroborate_products_with_fact_tags`~~ — both mutate in place and return `None`.
- ~~`ShelfRegion.is_background` being honoured by `check_planogram_compliance`~~ — irrelevant here; it matters only in assignment/OCR.
- ~~real image content being inspected~~ — nothing here reads pixels except `crop`; the synthetic image is enough.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_fact_tags_illumination_characterization.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType._check_illumination",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType._base_model_from_str",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._ocr_fact_tags",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._corroborate_products_with_fact_tags",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._assign_products_to_shelves",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/models.py#PlanogramConfig",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#IdentifiedProduct",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#ShelfRegion",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#DetectionBox"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `pipeline.roi_client = pipeline.llm = fake_vision_client` — **one object, two
  attributes** — because a later task replaces `roi_client` with `llm` at these
  call sites. Never assert `kwargs["model"]`; do assert `no_memory is True` and
  `max_tokens == 128` (both survive the refactor by spec Module 6).
- `pipeline._downscale_image` must return its input
  (`MagicMock(side_effect=lambda img, **kw: img)`) so recorded `image_size`
  equals the crop size.
- Characterize, never correct: pin observed behaviour; list surprises in the Completion Note.
- `pytest.ini` has `asyncio_mode = auto` — `async def test_…` needs no marker.
- Run with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src pytest <file> -q` inside a worktree.

### References in Codebase
- `packages/ai-parrot-pipelines/tests/test_planogram_types.py:96-109` — today's mock pipeline shape
- `packages/ai-parrot-pipelines/tests/conftest.py` — fixtures (TASK-3420)

---

## Implementation Blueprint

> Write the blocks (consecutive parts of ONE file), then complete every `# FILL IN:`.

### Steps (in order)
1. Write Part 1 (helpers + `handler` fixture) — *why*: the "same fake on both attributes" rule lives in exactly one place.
2. Write Part 2 (illumination + fact-tag OCR) — *why*: these are the two LLM call sites the refactor touches; they are the regression net.
3. Write Part 3 (corroboration + assignment) — *why*: pure in-place logic the legacy adapter must keep calling unchanged.
4. Complete each `FILL IN` by running the code once and pinning the observed value when it matches the bound stated in the marker.
5. Run the Validation Command and `ruff check` on the file.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_fact_tags_illumination_characterization.py` (CREATE) — Part 1: helpers
```python
"""Characterization tests: fact-tag OCR, corroboration, shelf assignment, illumination — as they behave TODAY (FEAT-574)."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, List, Optional
from unittest.mock import MagicMock

import pytest
from PIL import Image

from parrot.models.detections import DetectionBox, IdentifiedProduct, ShelfRegion
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.types import ProductOnShelves

RAW_CONFIG = {
    "brand": "TestBrand",
    "category": "Scanners",
    "aisle": {"name": "Electronics > Test", "lighting_conditions": "normal"},
    "shelves": [
        {"level": "header", "height_ratio": 0.2, "is_background": True,
         "products": [{"name": "TestBrand Backlit", "product_type": "promotional_graphic"}]},
        {"level": "top", "height_ratio": 0.4,
         "products": [{"name": "ES-400", "product_type": "product"}, {"name": "RR-60", "product_type": "product"}]},
        {"level": "bottom", "height_ratio": 0.4, "products": [{"name": "DS-770", "product_type": "product"}]},
    ],
}


def box(x1: int, y1: int, x2: int, y2: int) -> DetectionBox:
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=0.9)


def prod(model: Optional[str], ptype: str = "product", b: Optional[DetectionBox] = None,
         shelf_location: Optional[str] = None, **extra: Any) -> IdentifiedProduct:
    return IdentifiedProduct(product_type=ptype, product_model=model, confidence=0.9,
                             detection_box=b, shelf_location=shelf_location, **extra)


def regions() -> List[ShelfRegion]:
    """header (background) y∈[0,200), top y∈[200,500), bottom y∈[500,1000)."""
    return [
        ShelfRegion(shelf_id="h", level="header", bbox=box(0, 0, 800, 200), is_background=True),
        ShelfRegion(shelf_id="t", level="top", bbox=box(0, 200, 800, 500)),
        ShelfRegion(shelf_id="b", level="bottom", bbox=box(0, 500, 800, 1000)),
    ]


@pytest.fixture
def handler(fake_vision_client: Any) -> ProductOnShelves:
    """Real ProductOnShelves; the SAME fake is both roi_client and llm (refactor-proof)."""
    config = PlanogramConfig(config_name="c", planogram_type="product_on_shelves", planogram_config=RAW_CONFIG,
                             roi_detection_prompt="roi", object_identification_prompt="objects")
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.pos.helpers")
    pipeline.roi_client = fake_vision_client
    pipeline.llm = fake_vision_client
    pipeline._downscale_image = MagicMock(side_effect=lambda img, **kw: img)
    return ProductOnShelves(pipeline=pipeline, config=config)
```
**Why this shape**: one fixture owns the dual assignment, so no individual test
can accidentally bind to `roi_client` only. `_downscale_image` is an identity so
`call["image_size"]` equals the crop the code produced.

### same file — Part 2: illumination and fact-tag OCR
```python
@pytest.mark.parametrize("answer,expected", [
    ("The panel is dull.\nLIGHT_OFF", "illumination_status: OFF"),
    ("Uniform glow.\nLIGHT_ON", "illumination_status: ON"),
    ("no verdict at all", "illumination_status: ON"),          # anything without LIGHT_OFF ⇒ ON (:247)
    ("", "illumination_status: ON"),
])
async def test_check_illumination_answer_parsing(handler, fake_vision_client, synthetic_shelf_image,
                                                 answer: str, expected: str) -> None:
    fake_vision_client.queue("ask_to_image", answer)
    assert await handler._check_illumination(synthetic_shelf_image) == expected
    call = fake_vision_client.calls_to("ask_to_image")[0]
    assert call["kwargs"]["no_memory"] is True and call["kwargs"]["max_tokens"] == 128   # never assert "model"


async def test_check_illumination_failure_returns_none(handler, fake_vision_client, synthetic_shelf_image) -> None:
    """LLM failure ⇒ None (caller skips the penalty), never an exception."""
    fake_vision_client.queue("ask_to_image", RuntimeError("503"))
    assert await handler._check_illumination(synthetic_shelf_image) is None


async def test_check_illumination_crop_precedence(handler, fake_vision_client, synthetic_shelf_image) -> None:
    """zone_bbox (pixels) wins over roi.bbox (fractions) which wins over the full image."""
    zone = box(100, 0, 700, 200)
    roi = SimpleNamespace(bbox=SimpleNamespace(x1=0.0, y1=0.0, x2=0.5, y2=0.5))
    await handler._check_illumination(synthetic_shelf_image, zone_bbox=zone, roi=roi)
    await handler._check_illumination(synthetic_shelf_image, roi=roi)
    await handler._check_illumination(synthetic_shelf_image)
    sizes = [c["image_size"] for c in fake_vision_client.calls_to("ask_to_image")]
    assert sizes == [(600, 200), (400, 500), (800, 1000)]
    # FILL IN: brand hint — bounded by :198-199: with planogram_description=SimpleNamespace(brand="TestBrand")
    #          the recorded prompt contains "a TestBrand backlit"; without it, "a backlit".


async def test_ocr_fact_tags_strip_per_foreground_shelf(handler, fake_vision_client, synthetic_shelf_image) -> None:
    """No detected tags: one call per NON-background shelf, fixed strip at the shelf's bottom edge."""
    fake_vision_client.queue("ask_to_image", "ES-400, 'rr-60'", "UNKNOWN")
    products = [prod("ES-400", b=box(100, 250, 300, 480)), prod("DS-770", b=box(350, 600, 500, 950))]
    got = await handler._ocr_fact_tags(products, synthetic_shelf_image,
                                       handler.config.get_planogram_description(), shelf_regions=regions())
    assert got == {"top": ["ES-400", "RR-60"]}                 # upper-cased, quotes stripped, UNKNOWN shelf absent
    calls = fake_vision_client.calls_to("ask_to_image")
    assert len(calls) == 2                                     # header is background ⇒ skipped
    assert calls[0]["image_size"] == (460, 75)                 # x: [100-30, 500+30]; y: [500-55, 500+20]
    # FILL IN: pin calls[1]["image_size"] — bounded by :1319-1320 with shelf y2=1000 and image height 1000
    #          ⇒ y: [945, 1000] ⇒ (460, 55).
    # FILL IN: assert the known-models hint — bounded by :1243-1256: prompt contains "ES-400, RR-60, DS-770"
    #          (header promo name is listed first).


async def test_ocr_fact_tags_detected_tags_refine_rows(handler, fake_vision_client, synthetic_shelf_image) -> None:
    """Detected fact tags set the y-span (±pad) and receive the raw OCR text."""
    tag = prod(None, "fact_tag", b=box(120, 470, 180, 490), shelf_location="top")
    fake_vision_client.queue("ask_to_image", "ES-400")
    got = await handler._ocr_fact_tags([tag], synthetic_shelf_image, handler.config.get_planogram_description(),
                                       shelf_regions=[regions()[1]])
    assert got == {"top": ["ES-400"]} and tag.ocr_text == "ES-400"
    # FILL IN: pin the crop size — bounded by: x [120-30, 180+30] = 120 wide; pad = max(5, int(20·0.10)) = 5
    #          ⇒ y [465, 495] = 30 tall ⇒ (120, 30).


async def test_ocr_fact_tags_isolates_shelf_failure(handler, fake_vision_client, synthetic_shelf_image) -> None:
    """An exception on one shelf is logged; the other shelf is still read."""
    fake_vision_client.queue("ask_to_image", RuntimeError("boom"), "DS-770")
    got = await handler._ocr_fact_tags([], synthetic_shelf_image, handler.config.get_planogram_description(),
                                       shelf_regions=regions())
    assert got == {"bottom": ["DS-770"]}
```
**Why**: crop sizes are asserted because the legacy adapter must keep feeding
the *same pixels* to the LLM; the `model` kwarg is deliberately never asserted
because its value is precisely what the refactor changes.

### same file — Part 3: corroboration and shelf assignment
```python
def test_corroborate_injects_missing_expected_model(handler) -> None:
    """OCR'd model expected on the shelf but not detected ⇒ synthetic product injected in place."""
    products = [prod("ES-400", shelf_location="top")]
    handler._corroborate_products_with_fact_tags(products, {"top": ["ES-400", "RR-60", "RR-60"]},
                                                 handler.config.get_planogram_description())
    assert [p.product_model for p in products] == ["ES-400", "RR-60"]          # no duplicate within one run
    injected = products[-1]
    assert (injected.product_type, injected.shelf_location, injected.confidence) == ("product", "top", 0.85)
    assert injected.visual_features == ["fact_tag_confirmed:RR-60"] and injected.ocr_text == "fact_tag_ocr:RR-60"


@pytest.mark.parametrize("ocr_model,reason", [
    ("REWARDS", "cannot be normalised"),
    ("ZZ-999", "not expected on this shelf"),
    ("DS-770", "belongs to another shelf"),
])
def test_corroborate_skip_rules(handler, ocr_model: str, reason: str) -> None:
    products: List[IdentifiedProduct] = []
    handler._corroborate_products_with_fact_tags(products, {"top": [ocr_model]},
                                                 handler.config.get_planogram_description())
    assert products == [], reason


def test_assign_products_default_max_overlap(handler) -> None:
    """Default mode: the shelf with the largest vertical overlap wins; structural types are untouched."""
    a = prod("ES-400", b=box(100, 250, 300, 480))                  # fully inside 'top'
    straddle = prod("RR-60", b=box(320, 400, 480, 900))            # 100 px in top, 400 px in bottom
    gap = prod(None, "gap", b=box(0, 250, 50, 300), shelf_location="untouched")
    handler._assign_products_to_shelves([a, straddle, gap], regions())
    assert (a.shelf_location, straddle.shelf_location, gap.shelf_location) == ("top", "bottom", "untouched")


def test_assign_products_promotional_and_missing_box(handler) -> None:
    """Promos prefer the background shelf when their centre is inside it; box-less products get the middle foreground shelf."""
    backlit = prod("TestBrand Backlit", "promotional_graphic", b=box(100, 20, 700, 180))
    low_graphic = prod("Comparison table", "promotional_graphic", b=box(100, 700, 700, 900))
    boxless = prod("ES-400")
    boxless_valid = prod("DS-770", shelf_location="bottom")
    handler._assign_products_to_shelves([backlit, low_graphic, boxless, boxless_valid], regions())
    assert backlit.shelf_location == "header"
    assert low_graphic.shelf_location == "bottom"                  # centre below the background shelf ⇒ spatial
    assert boxless_valid.shelf_location == "bottom"                # valid LLM location kept
    # FILL IN: pin boxless.shelf_location — bounded by :1598-1599: foreground = [top, bottom], len // 2 = 1 ⇒ "bottom".


def test_assign_products_y1_mode_uses_centre_bottom_up(handler) -> None:
    """use_y1_assignment=True: bbox CENTRE decides (bottom→top), bbox y1 is only the secondary hint."""
    # FILL IN: bounded by :1606-1633 — (a) a box 320..480 × 400..900 (centre y=650) ⇒ "bottom";
    #          (b) a box whose centre is outside every foreground shelf but whose y1 is inside 'top' ⇒ "top"
    #          (build it with a shelves list whose zones leave a gap, e.g. top [200,450) and bottom [550,1000),
    #           product y 440..560: centre 500 in the gap, y1 440 in 'top').


def test_assign_products_no_shelves_is_noop(handler) -> None:
    p = prod("ES-400", b=box(1, 1, 5, 5), shelf_location="keep")
    assert handler._assign_products_to_shelves([p], []) is None
    assert p.shelf_location == "keep"
```
**Why**: the three corroboration skip rules map 1:1 to the log branches at
`:1445-1468`; the parametrisation documents which guard fires first
(`"DS-770"` on `top` is rejected by *not expected on this shelf* before the
cross-shelf guard — both yield no injection, which is all the test pins).

### FILL IN checklist
- [ ] `test_check_illumination_crop_precedence` — brand-hint prompt assertions
- [ ] `test_ocr_fact_tags_strip_per_foreground_shelf` — second crop size `(460, 55)` and known-models hint
- [ ] `test_ocr_fact_tags_detected_tags_refine_rows` — crop size `(120, 30)`
- [ ] `test_assign_products_promotional_and_missing_box` — box-less product lands on `"bottom"`
- [ ] `test_assign_products_y1_mode_uses_centre_bottom_up` — body (two cases)

---

## Acceptance Criteria

- [ ] All tests pass against **unmodified** production code
- [ ] Every test pipeline uses the **same** fake for `roi_client` and `llm`; no assertion reads `kwargs["model"]`
- [ ] `_check_illumination`: parsing, `None` on failure, crop precedence, `no_memory`/`max_tokens` pinned
- [ ] `_ocr_fact_tags`: one call per non-background shelf, crop geometry, token parsing, tag `ocr_text`, failure isolation pinned
- [ ] `_corroborate_products_with_fact_tags`: injection shape (0.85, `fact_tag_confirmed:`) and all skip rules pinned
- [ ] `_assign_products_to_shelves`: default overlap, promo/background, box-less fallback, y1 mode, no-shelves no-op pinned
- [ ] No production file changed; deviations from the expectations above are listed in the Completion Note
- [ ] No linting errors: `ruff check packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_fact_tags_illumination_characterization.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_fact_tags_illumination_characterization.py -q`

---

## Test Specification

The blueprint **is** the scaffold: 13 test functions (two parametrised). Spec §4
names covered here: `test_pos_fact_tag_ocr_and_corroboration_characterization`
(split into the `test_ocr_fact_tags_*` and `test_corroborate_*` functions) and
`test_pos_assign_products_to_shelves_characterization` (the
`test_assign_products_*` functions). Add one aggregate alias test per spec name
if a reviewer asks for the literal names — the split functions are the source
of truth.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 3, §6 signatures, §7 Known Risks)
2. **Check dependencies** — TASK-3420 must be done (its conftest provides the fixtures)
3. **Verify the Codebase Contract** — re-read the four methods once; confirm whether the call sites still use `roi_client` or already `llm` (both must pass)
4. **Implement** — blueprint parts in order, complete every `# FILL IN:`
5. **Never edit production code**
6. **Commit code only** — never touch `sdd/`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
