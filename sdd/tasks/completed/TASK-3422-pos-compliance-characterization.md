# TASK-3422: Characterization tests for ProductOnShelves.check_planogram_compliance

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 3** / Goal **G17**: `ProductOnShelves.check_planogram_compliance`
(≈410 lines, `product_on_shelves.py:384-795`) has **no tests today**, yet the
feature is about to (a) rewrite every LLM call site around it and (b) migrate the
type to a new scoring formula. This task pins **today's** per-shelf scoring math
— *including its quirks* — so the provider-neutral refactor and the legacy
adapter can be proven behaviour-preserving. The quirks are **legacy behaviour to
pin, not bugs to fix**: spec §7 says "Pin the quirks as they are"; the migrated
formula in spec §2 deliberately differs.

`check_planogram_compliance` is **synchronous** and makes **no LLM call** — this
task needs no fake client and depends on nothing.

---

## Scope

- Create one test module that builds a real `ProductOnShelves` over a
  `MagicMock` pipeline and calls `check_planogram_compliance(identified_products, planogram_description)`
  directly with hand-built `IdentifiedProduct`s.
- Pin, with exact numbers (`pytest.approx`):
  1. `basic_score = n_matched / n_expected` and one `ComplianceResult` **per configured shelf, in config order**.
  2. **Weights-sum quirk**: non-header defaults `0.8 / 0.1 / 0.2` sum to 1.1 and are clamped to 1.0.
  3. **Threshold uses `basic_score` only** (never the combined score).
  4. `MISSING` status rule; `MISPLACED` is never emitted.
  5. **Zone-only shelf** (zero expected products) ⇒ `NON_COMPLIANT`, score `0.3`.
  6. **Illumination**: nested raw-dict keys, default penalty `0.5`, multiplier applied to the *unclamped* combined score, label suffix and `missing_products` pseudo-entry.
  7. **Header / endcap text**: text score formula, mandatory flag, and the "no promos on header" path where `overall_text_compliant=False` but `text_compliance_score` stays `1.0`.
  8. Header brand gate (`brand_check_ok`), header weights (`0.64 / 0.2 / 0.16`, brand weight always `0.0`).
  9. Matching rules: type equivalence (`printer`↔`product`, `product`↔`product_box`), empty base ⇒ match, greedy 1:1; skipped types (`fact_tag`, `price_tag`, `slot`, `brand_logo`, `gap`, `shelf`).
  10. Unexpected products: `allow_extra_products`, "expected on another shelf" protection, the `major_unexpected` filter.

**NOT in scope**: fact-tag OCR, corroboration, shelf assignment, illumination
*detection* (`_check_illumination`) — TASK-3423; `run()` orchestration —
TASK-3424; changing any production code (if a test reveals different numbers
than listed here, **pin what the code does** and record the deviation in the
Completion Note — never edit `product_on_shelves.py`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_compliance_characterization.py` | CREATE | Characterization tests of today's per-shelf compliance math |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (re-read 2026-09-18 on `dev`). Use these exact
> imports and signatures. Do not invent attributes.

### Verified Imports
```python
import logging
from unittest.mock import MagicMock
import pytest
from parrot_pipelines.models import PlanogramConfig                      # models.py:29
from parrot_pipelines.planogram.types import ProductOnShelves            # planogram/types/__init__.py:3
from parrot.models.detections import DetectionBox, IdentifiedProduct     # detections.py:37, :71
from parrot.models.compliance import ComplianceResult, ComplianceStatus  # compliance.py:32, :9
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py
class ProductOnShelves(AbstractPlanogramType):                              # :35
    def __init__(self, pipeline: Any, config: Any) -> None                  # :47-52 (reads config.endcap_geometry)
    def check_planogram_compliance(self, identified_products: List[IdentifiedProduct],
                                   planogram_description: Any) -> List[ComplianceResult]   # :384-795  SYNC
# AbstractPlanogramType.__init__ (types/abstract.py:48-55) sets self.pipeline, self.config, self.logger = pipeline.logger

# packages/ai-parrot-pipelines/src/parrot_pipelines/models.py
class PlanogramConfig(BaseModel):                                           # :29-108
    planogram_config: Dict[str, Any]            # REQUIRED  :50
    roi_detection_prompt: str                   # REQUIRED today :55   (pass by keyword — becomes optional later)
    object_identification_prompt: str           # REQUIRED today :60
    def get_planogram_description(self) -> PlanogramDescription             # :102-108

# packages/ai-parrot/src/parrot/models/detections.py
class IdentifiedProduct(BaseModel)   # :71-206  product_type (req), confidence (req), product_model, brand,
                                     #          visual_features: List[str], shelf_location, detection_box, ocr_text
class ShelfConfig(BaseModel)         # :302-326 level, products, compliance_threshold=0.8 :307, allow_extra_products=False :308,
                                     #          product_weight/text_weight/visual_weight = None :313-315
class TextRequirement(BaseModel)     # :328-334 required_text, match_type="contains", case_sensitive=False,
                                     #          confidence_threshold=0.7, mandatory=True
class AdvertisementEndcap(BaseModel) # :337-354 enabled=True, position="header", product_weight=0.8, text_weight=0.2, text_requirements
# raw config key for the endcap: planogram_config["advertisement_endcap"]    (factory: detections.py:566-578)

# packages/ai-parrot/src/parrot/models/compliance.py
class ComplianceStatus(str, Enum)    # :9-14  COMPLIANT | NON_COMPLIANT | MISSING | MISPLACED
class ComplianceResult(BaseModel)    # :32-52 shelf_level, expected_products, found_products, missing_products, unexpected_products,
                                     #        compliance_status, compliance_score (0..1), text_compliance_results,
                                     #        brand_compliance_result, text_compliance_score=1.0, overall_text_compliant=True
```

**Today's math** (every line re-verified; this is what the tests pin):
```
raw config is read from self.config.planogram_config (NOT from the Pydantic description)   :411-418
brand check: first product whose .brand.lower() == planogram.brand.lower(); one shared result :506-518
products bucketed by p.shelf_location                                                       :519-522
expected = shelf_cfg.products minus product_type in {fact_tag, price_tag, slot}             :545-551
found    = products on shelf minus {fact_tag, price_tag, slot, brand_logo, gap, shelf};
           "text_overlay" is an OCR carrier (promos only, never matchable)                 :557-570
matching: greedy 1:1, type equivalence + substring on normalised base; empty base ⇒ match  :438-503, :578-616
basic_score = n_matched / (len(expected) or 1.0)                                            :660
visual_feature_score = mean(matches) if any else 1.0                                        :662-664
text: only if endcap and endcap.enabled and endcap.position == shelf_level                  :668
      promos == [] and shelf_level == "header" ⇒ overall_text_ok False, text_score STAYS 1.0 :686-697
      else text_score = Σ confidence(found) / len(all requirements)                         :711
illumination: raw shelves[].products[]["illumination_required"] (:420-427),
      ["illumination_penalty"] default 0.5 (:429-436); detected from visual feature
      "illumination_status: ON|OFF" (types/abstract.py:132-149)
      label suffix f"{label} (LIGHT_{DET})" :620-628; missing entry
      f"{name} — backlight {DET} (required: {EXP})" :631-633
weights: visual_weight always 0.2 (:745 getattr of a field that does not exist)
      header and endcap: basic·(endcap.product_weight·0.8) + text·endcap.text_weight
                         + brand_conf·0.0 + visual·(endcap.product_weight·0.2)             :746-753
      other shelves: Wv = shelf.visual_weight or 0.2; Wt = shelf.text_weight or 0.1;
                     Wp = shelf.product_weight or (1 - Wv)   → defaults sum 1.1             :757-764
penalty: combined *= max(0, 1 - Σpenalty / (len(expected) or 1))                            :772-775
compliance_score = min(1, max(0, combined))                                                 :777
status (:717-743): threshold = shelf_cfg.compliance_threshold; major_unexpected = unexpected minus
      labels containing "ink" | "price tag" | "fact_tag" | "fact tag"  (:720-727)
      non-header: COMPLIANT iff basic_score >= threshold and not major_unexpected and no illum mismatch;
                  MISSING iff basic_score == 0.0 and len(expected) > 0; else NON_COMPLIANT
      header:     NON_COMPLIANT if not brand_check_ok; else same COMPLIANT rule + overall_text_ok; MISSING rule
returns one ComplianceResult per planogram_description.shelves entry, config order          :538, :780-795
```

### Does NOT Exist
- ~~any existing test of `check_planogram_compliance`~~ — none; do not look for one to extend.
- ~~`PlanogramDescription.visual_features_weight`~~, ~~`AdvertisementEndcap.brand_weight`~~ — read via `getattr` defaults (0.2 / 0.0); never set them in a config expecting an effect.
- ~~`ShelfConfig.illumination_required` / `illumination_penalty`~~ — they exist only in the **raw dict**, nested in `shelves[].products[]`.
- ~~a global numeric compliance threshold~~ — thresholds are per shelf (`compliance_threshold`).
- ~~`ComplianceStatus.MISPLACED` being produced~~ — declared, never emitted by this method.
- ~~use of `ShelfProduct.quantity_range` / `mandatory` / `position_preference`~~ — never read here; one `ShelfProduct` entry == one expected item.
- ~~fuzzy product matching~~ — substring/alias only (`TextMatcher` fuzziness applies to *text requirements* only).
- ~~an LLM call inside `check_planogram_compliance`~~ — none; do not build a fake client.
- ~~a shared test `conftest.py` in this tree~~ — assume none is available; this module is self-contained.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_compliance_characterization.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves.check_planogram_compliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType._extract_illumination_state",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType._base_model_from_str",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/models.py#PlanogramConfig",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#IdentifiedProduct",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#DetectionBox",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#ShelfConfig",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#AdvertisementEndcap",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#TextRequirement",
    "sym:packages/ai-parrot/src/parrot/models/compliance.py#ComplianceResult",
    "sym:packages/ai-parrot/src/parrot/models/compliance.py#ComplianceStatus"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Pipeline mock as in `packages/ai-parrot-pipelines/tests/test_planogram_types.py:96-109`
(a `MagicMock` with a real `logging` logger). Config dict shape as in the same
file `:26-79` (`brand`, `category`, `aisle`, `shelves[]`).

### Key Constraints
- **Characterize, do not correct.** Expected numbers below were derived by
  reading the code; if the code disagrees, the *code* wins — pin the observed
  value, and write the discrepancy in the Completion Note.
- Product names must survive `_base_model_from_str` (generic pattern
  `([a-z]+)[- ]?(\d{2,4})`): use names like `"ES-400"`, `"RR-60"`, `"DS-770"`,
  `"WF-110"`; brand `"TestBrand"` (avoids the Epson/Hisense special cases).
- Every test builds its own config through the `make_handler` helper — no shared
  mutable state; the method mutates nothing global but `globally_matched_keys`
  is order-dependent **across shelves within one call**.
- Tests must survive the later provider-neutral refactor: never touch
  `pipeline.roi_client` / `pipeline.llm` here (not needed — the method is sync
  and LLM-free).
- `pytest.ini` sets `asyncio_mode = auto`; all tests here are plain sync functions.
- Run with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src pytest <file> -q`
  inside a worktree (shared `.venv` is editable-installed against the main checkout).

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:384-795` — the method under test
- `packages/ai-parrot/src/parrot/models/detections.py:414-605` — `PlanogramDescriptionFactory.create_planogram_description` (which raw keys become Pydantic fields)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write the blocks to the declared
> path (they are consecutive parts of ONE file), then complete every `# FILL IN:`.
> Never rename a test function — later tasks and the spec reference them.

### Steps (in order)
1. Write Part 1 (imports + helpers) — *why*: every test goes through `make_handler`/`prod`, so config shape mistakes surface once.
2. Write Part 2 (score/status tests) and run them — *why*: they pin the numbers the migrated formula must visibly differ from (spec §4 `weight_normalisation`).
3. Write Part 3 (illumination, header/text, matching, unexpected) — *why*: these are the rule semantics the rule-binding migration must carry over.
4. For each `FILL IN`, first print/inspect the actual `ComplianceResult`, then assert the observed value if it matches the expectation in the marker; if it does not, pin the observed value and note it — *why*: this is a characterization suite.
5. Run the Validation Command; run `ruff check` on the file.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_compliance_characterization.py` (CREATE) — Part 1: helpers
```python
"""Characterization tests: ProductOnShelves.check_planogram_compliance as it behaves TODAY (FEAT-574).

These tests pin legacy behaviour, quirks included. Do not "fix" an expectation
without reading spec §7 — the migrated scoring formula lives elsewhere.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from parrot.models.compliance import ComplianceResult, ComplianceStatus
from parrot.models.detections import DetectionBox, IdentifiedProduct
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.types import ProductOnShelves


def shelf(level: str, products: List[Dict[str, Any]], **extra: Any) -> Dict[str, Any]:
    """Raw shelf dict; ``extra`` carries compliance_threshold, allow_extra_products, *_weight…"""
    return {"level": level, "height_ratio": 0.3, "products": products, **extra}


def expected(name: str, product_type: str = "product", **extra: Any) -> Dict[str, Any]:
    """Raw expected-product dict; ``extra`` carries illumination_required / illumination_penalty / visual_features."""
    return {"name": name, "product_type": product_type, **extra}


def make_handler(shelves: List[Dict[str, Any]], **top_level: Any) -> ProductOnShelves:
    """Build a real ProductOnShelves over a MagicMock pipeline.

    Args:
        shelves: Raw ``planogram_config["shelves"]``.
        **top_level: Extra raw keys, e.g. ``advertisement_endcap={...}``, ``product_subtypes=[...]``.
    """
    raw = {
        "brand": "TestBrand",
        "category": "TestCategory",
        "aisle": {"name": "Electronics > Test", "lighting_conditions": "normal"},
        "shelves": shelves,
        **top_level,
    }
    config = PlanogramConfig(
        config_name="characterization",
        planogram_type="product_on_shelves",
        planogram_config=raw,
        roi_detection_prompt="roi",
        object_identification_prompt="objects",
    )
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.pos.characterization")
    return ProductOnShelves(pipeline=pipeline, config=config)


def prod(model: Optional[str], shelf_location: str, product_type: str = "product", **extra: Any) -> IdentifiedProduct:
    """An identified product placed on ``shelf_location`` (extra: brand, visual_features, ocr_text)."""
    return IdentifiedProduct(
        product_type=product_type,
        product_model=model,
        confidence=0.9,
        shelf_location=shelf_location,
        detection_box=DetectionBox(x1=10, y1=10, x2=110, y2=110, confidence=0.9),
        **extra,
    )


def check(handler: ProductOnShelves, products: List[IdentifiedProduct]) -> Dict[str, ComplianceResult]:
    """Run the method under test and index the results by shelf level (order asserted separately)."""
    results = handler.check_planogram_compliance(products, handler.config.get_planogram_description())
    return {r.shelf_level: r for r in results}
```
**Why this shape**: a *real* `PlanogramConfig` + `get_planogram_description()` is
mandatory because the method reads **both** views — the Pydantic description
(shelves, endcap, thresholds) and the raw dict (`self.config.planogram_config`
for illumination keys and `product_subtypes`). Prompts are passed by keyword so
the helper keeps working once they become optional.

### same file — Part 2: scores and statuses
```python
def test_one_result_per_shelf_in_config_order() -> None:
    """Returns exactly one ComplianceResult per configured shelf, in config order."""
    handler = make_handler([shelf("top", [expected("ES-400")]), shelf("middle", [expected("RR-60")]),
                            shelf("bottom", [expected("DS-770")])])
    results = handler.check_planogram_compliance([], handler.config.get_planogram_description())
    assert [r.shelf_level for r in results] == ["top", "middle", "bottom"]
    assert all(isinstance(r, ComplianceResult) for r in results)


def test_pos_basic_score_and_status_characterization() -> None:
    """basic_score = matched/expected; COMPLIANT needs basic_score >= threshold; all-missing ⇒ MISSING."""
    handler = make_handler([shelf("top", [expected("ES-400"), expected("RR-60")]),
                            shelf("bottom", [expected("DS-770")])])
    by = check(handler, [prod("ES-400", "top"), prod("RR-60", "top")])
    assert by["top"].compliance_status == ComplianceStatus.COMPLIANT
    assert by["top"].missing_products == []
    assert by["bottom"].compliance_status == ComplianceStatus.MISSING          # basic 0.0 and expected > 0
    assert by["bottom"].missing_products == ["DS-770"]
    # FILL IN: pin by["bottom"].compliance_score — bounded by: 0.0·0.8 + 1.0·0.1 + 1.0·0.2 = 0.3 (approx).


def test_pos_weights_sum_quirk_characterization() -> None:
    """Non-header default weights are 0.8/0.1/0.2 (sum 1.1) — masked by the clamp at :777."""
    handler = make_handler([shelf("top", [expected("ES-400"), expected("RR-60")])])
    full = check(handler, [prod("ES-400", "top"), prod("RR-60", "top")])["top"]
    half = check(handler, [prod("ES-400", "top")])["top"]
    assert full.compliance_score == pytest.approx(1.0)       # 1.1 clamped
    assert half.compliance_score == pytest.approx(0.7)       # 0.5·0.8 + 0.1 + 0.2 — NOT 0.636 (normalised)
    assert half.compliance_status == ComplianceStatus.NON_COMPLIANT


def test_pos_threshold_uses_basic_score_only_characterization() -> None:
    """3 of 4 matched: combined 0.9 >= 0.8 but basic 0.75 < 0.8 ⇒ NON_COMPLIANT."""
    names = ["ES-400", "RR-60", "DS-770", "WF-110"]
    handler = make_handler([shelf("top", [expected(n) for n in names], compliance_threshold=0.8)])
    res = check(handler, [prod(n, "top") for n in names[:3]])["top"]
    assert res.compliance_score == pytest.approx(0.9)
    assert res.compliance_status == ComplianceStatus.NON_COMPLIANT
    # FILL IN: second half — bounded by: same data with compliance_threshold=0.7 ⇒ COMPLIANT (threshold is per shelf).


def test_pos_explicit_shelf_weights_characterization() -> None:
    """shelf.product_weight / text_weight / visual_weight override the defaults."""
    # FILL IN: bounded by: shelf(..., product_weight=0.5, text_weight=0.25, visual_weight=0.25), 1 of 2 matched
    #          ⇒ 0.5·0.5 + 1.0·0.25 + 1.0·0.25 = 0.75.


def test_pos_zone_only_shelf_characterization() -> None:
    """Zero expected products ⇒ basic 0.0, NON_COMPLIANT (neither COMPLIANT nor MISSING), score 0.3."""
    handler = make_handler([shelf("zone", []), shelf("top", [expected("ES-400")])])
    zone = check(handler, [prod("ES-400", "top")])["zone"]
    assert zone.compliance_status == ComplianceStatus.NON_COMPLIANT
    assert zone.compliance_score == pytest.approx(0.3)
    # FILL IN: same expectation for a shelf whose only expected entries are fact_tag / price_tag / slot
    #          — bounded by :546-547 (those types are skipped, so expected is empty).


def test_pos_never_emits_misplaced_characterization() -> None:
    """A product expected on 'top' but found on 'bottom' yields MISSING/NON_COMPLIANT, never MISPLACED."""
    # FILL IN: bounded by: no result has compliance_status == ComplianceStatus.MISPLACED; the stray product is NOT
    #          listed in bottom.unexpected_products ("expected on another shelf" protection, :642-651).
```
**Why**: `test_pos_weights_sum_quirk_characterization` and
`test_pos_zone_only_shelf_characterization` are named in spec §4 and are the
legacy counterparts of the migrated fixtures `weight_normalisation` and
`zone_only_shelf` — the two suites together document the intended semantic change.

### same file — Part 3: illumination, header/text, matching, unexpected
```python
def test_pos_illumination_penalty_characterization() -> None:
    """Nested illumination_required; default penalty 0.5 multiplies the UNCLAMPED combined score."""
    handler = make_handler([shelf("top", [expected("ES-400", illumination_required="on")])])
    res = check(handler, [prod("ES-400", "top", visual_features=["illumination_status: OFF"])])["top"]
    assert res.compliance_score == pytest.approx(0.55)        # 1.1 · (1 - 0.5/1), clamp happens AFTER
    assert res.compliance_status == ComplianceStatus.NON_COMPLIANT   # mismatch blocks COMPLIANT (:731)
    assert any("backlight OFF (required: ON)" in m for m in res.missing_products)
    assert any(label.endswith("(LIGHT_OFF)") for label in res.found_products)
    # FILL IN: three more cases — bounded by: (a) illumination_penalty=1.0 ⇒ score 0.0;
    #          (b) detected "illumination_status: ON" ⇒ no penalty, COMPLIANT, score 1.0;
    #          (c) no illumination feature on the product (detected None) ⇒ no penalty (:603).


HEADER_ENDCAP = {
    "enabled": True,
    "position": "header",
    "text_requirements": [
        {"required_text": "Hello Savings", "match_type": "contains", "mandatory": True},
        {"required_text": "Goodbye Cartridges", "match_type": "contains", "mandatory": False},
    ],
}


def test_pos_header_text_requirements_characterization() -> None:
    """Header: text_score = Σconf(found)/len(all reqs); mandatory miss ⇒ overall_text_compliant False."""
    handler = make_handler([shelf("header", [expected("TestBrand Backlit", "promotional_graphic")])],
                           advertisement_endcap=HEADER_ENDCAP)
    promo = prod("TestBrand Backlit", "header", "promotional_graphic", brand="TestBrand",
                 visual_features=["ocr:Hello Savings"])
    res = check(handler, [promo])["header"]
    assert res.text_compliance_score == pytest.approx(0.5)     # 1 of 2 found, 'contains' confidence is binary 1.0
    assert res.overall_text_compliant is True                  # the missed requirement is optional
    assert res.compliance_score == pytest.approx(0.64 + 0.5 * 0.2 + 0.16)      # header weights 0.64/0.2/0.16
    # FILL IN: pin res.compliance_status — bounded by :735-743 (brand ok, basic 1.0 >= threshold, text ok ⇒ COMPLIANT).
    # FILL IN: second case — the MANDATORY text missing ⇒ overall_text_compliant False and status NON_COMPLIANT.


def test_pos_header_no_promos_keeps_text_score_characterization() -> None:
    """No promo on the header: overall_text_compliant False, but text_compliance_score STAYS 1.0 (:686-697)."""
    handler = make_handler([shelf("header", [expected("TestBrand Backlit", "promotional_graphic")])],
                           advertisement_endcap=HEADER_ENDCAP)
    res = check(handler, [])["header"]
    assert res.overall_text_compliant is False
    assert res.text_compliance_score == pytest.approx(1.0)
    assert res.compliance_score == pytest.approx(0.0 * 0.64 + 1.0 * 0.2 + 1.0 * 0.16)   # 0.36
    assert all(t.found is False for t in res.text_compliance_results)
    # FILL IN: pin res.compliance_status — bounded by :736 (no product carries the brand ⇒ NON_COMPLIANT).


def test_pos_header_brand_gate_characterization() -> None:
    """Header is NON_COMPLIANT when no identified product carries planogram.brand — brand never SCORES (weight 0.0)."""
    # FILL IN: bounded by: same perfect header as above but promo.brand=None ⇒ NON_COMPLIANT with an UNCHANGED
    #          compliance_score; brand_compliance_result.found is False and is the same object on every shelf.


def test_pos_matching_rules_characterization() -> None:
    """Type equivalence, empty-base wildcard, greedy 1:1 and skipped types."""
    # FILL IN: four asserts — bounded by :438-503 and :557-570:
    #   (a) expected product_type "printer" is matched by a found "product" with the same model;
    #   (b) a found product with product_model=None (empty base) matches ANY expected item of an equivalent type;
    #   (c) two expected "ES-400" entries need two found products (1:1) — one found ⇒ basic 0.5;
    #   (d) found items of type fact_tag / price_tag / brand_logo / gap / shelf neither match nor count as unexpected.


def test_pos_unexpected_products_characterization() -> None:
    """allow_extra_products, 'expected elsewhere' protection and the major_unexpected filter."""
    # FILL IN: bounded by :634-658 and :720-727:
    #   (a) an unknown "ZZ-999" on a fully matched shelf ⇒ listed in unexpected_products AND status NON_COMPLIANT;
    #   (b) same with allow_extra_products=True ⇒ unexpected_products == [] and COMPLIANT;
    #   (c) an unexpected label containing "ink" is listed but is NOT 'major' ⇒ shelf stays COMPLIANT.
```
**Why**: the illumination test deliberately uses a *fully matched non-header*
shelf so one assertion (`0.55`) pins **two** quirks at once — the 1.1 weight sum
and "penalty before clamp". `HEADER_ENDCAP` uses `match_type="contains"` because
that branch of `TextMatcher` is binary (confidence 1.0 / 0.0,
`compliance.py:169-176`), giving exact expected numbers.

### FILL IN checklist
- [ ] `test_pos_basic_score_and_status_characterization` — MISSING shelf score (expect 0.3)
- [ ] `test_pos_threshold_uses_basic_score_only_characterization` — per-shelf threshold 0.7 case
- [ ] `test_pos_explicit_shelf_weights_characterization` — body (expect 0.75)
- [ ] `test_pos_zone_only_shelf_characterization` — fact_tag/price_tag/slot-only shelf
- [ ] `test_pos_never_emits_misplaced_characterization` — body
- [ ] `test_pos_illumination_penalty_characterization` — cases (a) (b) (c)
- [ ] `test_pos_header_text_requirements_characterization` — status + mandatory-miss case
- [ ] `test_pos_header_no_promos_keeps_text_score_characterization` — status
- [ ] `test_pos_header_brand_gate_characterization` — body
- [ ] `test_pos_matching_rules_characterization` — four asserts
- [ ] `test_pos_unexpected_products_characterization` — three asserts

---

## Acceptance Criteria

- [ ] All tests in the new module pass against **unmodified** production code
- [ ] The test names listed in spec §4 for this area exist verbatim: `test_pos_basic_score_and_status_characterization`, `test_pos_weights_sum_quirk_characterization`, `test_pos_zone_only_shelf_characterization`, `test_pos_illumination_penalty_characterization`, `test_pos_header_text_requirements_characterization`
- [ ] Quirks pinned with exact numbers: 1.1→1.0 clamp (`0.7` half-match), zone-only `0.3` `NON_COMPLIANT`, `basic_score`-only threshold, default illumination penalty `0.5` (`0.55`), header text score not zeroed (`1.0` with `overall_text_compliant=False`)
- [ ] No production file changed; no LLM fake, no network, no real image
- [ ] Any expectation that had to be changed to match the code is listed in the Completion Note
- [ ] No linting errors: `ruff check packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_compliance_characterization.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_compliance_characterization.py -q`

---

## Test Specification

The blueprint **is** the scaffold. Minimum set: the 13 functions above
(`test_one_result_per_shelf_in_config_order` … `test_pos_unexpected_products_characterization`)
plus any extra case the implementer needs to make a `FILL IN` unambiguous.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 3, §6 "check_planogram_compliance — TODAY's math", §7 Known Risks)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — re-read `product_on_shelves.py:384-795` once before asserting numbers
4. **Implement** — write the blueprint parts in order, complete every `# FILL IN:`
5. **Never edit production code** — a surprising number is a finding, not a bug to fix here
6. **Commit code only** — never touch `sdd/`; the orchestrator moves this file and updates the index
7. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (FEAT-574 orchestrator)
**Date**: 2026-09-19

Implemented in fallback sequential mode (parrot-sdd-coder server unresponsive).
13 characterization tests pin today's per-shelf math against unmodified product_on_shelves.py: basic_score/MISSING, 0.8/0.1/0.2 weight-sum clamp (0.7 half-match), basic-score-only threshold (0.9 combined still NON_COMPLIANT at 0.8, COMPLIANT at 0.7), explicit weights (0.75), zone-only and tags-only shelves (0.3 NON_COMPLIANT), no MISPLACED, illumination penalty before clamp (0.55; 1.0 penalty -> 0.0; ON/None -> no penalty), header text score (0.5, mandatory miss), no-promos header (text score stays 1.0, score 0.36), brand gate (status only, shared result object), matching rules (printer<->product, empty base wildcard, greedy 1:1, skipped types), unexpected products (allow_extra_products, expected-elsewhere protection, 'ink' not major).
Deviations: none — every expectation derived in the task matched the observed values.

Seat: orchestrator (fallback) · Backend: native · Model: claude-opus-5 · Attempts: 1
