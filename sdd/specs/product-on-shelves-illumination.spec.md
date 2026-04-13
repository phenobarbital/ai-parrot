# Feature Specification: Product-On-Shelves Illumination Support

**Feature ID**: FEAT-091
**Date**: 2026-04-12
**Author**: Juan2coder
**Status**: draft
**Target version**: next minor release

---

## 1. Motivation & Business Requirements

### Problem Statement

Epson scanner displays at Office Depot feature a **backlit header panel** ("Scan & Done" with Shaq photo) above 3 shelves of physical scanner products. The `product_on_shelves` planogram type correctly handles the shelves but has **zero illumination support** — the backlit header's ON/OFF state is completely ignored in scoring.

The business requirement: the header shelf score must reflect BOTH presence of the correct graphic AND the backlight being ON. Currently, a header with the right graphic scores 100% even if the backlight is off — a real compliance failure that goes undetected.

This affects the `epson_scanner_backlit_planogram_config` (planogram_id=15) in production today. The solution must be opt-in to avoid breaking existing `product_on_shelves` configs already deployed.

### Goals
- Add optional illumination check to `product_on_shelves` planogram type
- Apply configurable penalty (default 0.5) when detected illumination state mismatches expected
- Reuse existing illumination check infrastructure (currently in `EndcapNoShelvesPromotional`)
- Zero impact on existing `product_on_shelves` configs that don't declare illumination

### Non-Goals (explicitly out of scope)
- Illumination checks on non-header shelves (deferred until needed)
- New planogram type — solution extends existing type
- Refactoring `GraphicPanelDisplay._check_illumination_from_roi()` (can be a follow-up)
- Changes to `vision_model` string → `GoogleModel` enum in config (separate concern)
- Multi-language illumination prompts

---

## 2. Architectural Design

### Overview

Extend `AbstractPlanogramType` with a shared `_check_illumination()` method (promoted from `EndcapNoShelvesPromotional`). Modify `ProductOnShelves.detect_objects()` to invoke illumination check for products marked with `illumination_required` in the raw config. Modify `ProductOnShelves.check_planogram_compliance()` to apply the illumination penalty when the detected state mismatches the expected state.

The feature is entirely opt-in: if `illumination_required` is absent from a product config, no behavior change occurs.

### Component Diagram
```
PlanogramCompliance (plan.py)
        │
        ▼
ProductOnShelves.detect_objects()
        │
        ├──→ _detect_legacy() / _detect_with_grid()  [existing]
        │
        └──→ [NEW] if any product has illumination_required:
                 └──→ _check_illumination(crop)  [promoted to base]
                        │
                        └──→ seeds visual_features with "illumination_status: ON/OFF"
        │
        ▼
ProductOnShelves.check_planogram_compliance()
        │
        └──→ [NEW] illumination penalty logic:
                 expected = config.illumination_required
                 detected = _extract_illumination_state(product.visual_features)
                 if expected != detected:
                     zone_score *= (1.0 - illumination_penalty)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractPlanogramType` | extends | Add `_check_illumination()` as shared base method |
| `ProductOnShelves.detect_objects()` | modifies | Adds optional illumination enrichment step |
| `ProductOnShelves.check_planogram_compliance()` | modifies | Adds illumination penalty in per-shelf scoring loop |
| `EndcapNoShelvesPromotional._check_illumination()` | removes | Now inherited from base |
| Planogram config JSON | extends | New optional fields: `illumination_required`, `illumination_penalty` |

### Data Models

No new Pydantic models. Two new optional fields on the raw `planogram_config["shelves"][*]["products"][*]` dict (not declared in `ShelfProduct` Pydantic model — read as raw dict per established pattern from FEAT-090's `text_requirements` handling):

```python
# Raw config structure (not a Pydantic model)
{
  "name": "Epson Scanners Header Graphic (backlit)",
  "product_type": "promotional_graphic",
  "visual_features": [...],
  "illumination_required": "on",        # NEW — "on" or "off" (case-insensitive), optional
  "illumination_penalty": 0.5           # NEW — float 0.0–1.0, optional, default 1.0
}
```

### New Public Interfaces

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
# Signature MUST match existing implementation verbatim — promotion is a MOVE, not a redesign.

class AbstractPlanogramType(ABC):
    async def _check_illumination(
        self,
        img: Image.Image,
        roi: Any,
        planogram_description: Any,
        illum_zone_bbox: Optional[Any] = None,
    ) -> str:
        """Check backlit illumination state using the illuminated zone crop.

        Promoted verbatim from EndcapNoShelvesPromotional (previously at
        endcap_no_shelves_promotional.py:454-558).

        Uses ``self.pipeline.roi_client.ask_to_image()`` with
        ``GoogleModel.GEMINI_3_FLASH_PREVIEW``. Reads brand from
        ``planogram_description`` to contextualize the prompt. Crops to
        ``illum_zone_bbox`` if provided, else to ``roi.bbox``, else uses full image.

        Returns:
            Always returns a string: ``'illumination_status: ON'`` or
            ``'illumination_status: OFF'``. Defaults to ``ON`` if the LLM call
            raises — NEVER returns ``None``.
        """
```

No changes to public API of `ProductOnShelves` — all modifications are internal.

---

## 3. Module Breakdown

### Module 1: Promote `_check_illumination()` to Base Class
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py`
- **Responsibility**: Move the LLM-based illumination detection method from `EndcapNoShelvesPromotional` to `AbstractPlanogramType` so all subtypes can reuse it. The method crops the zone (or falls back to ROI), sends a chain-of-thought prompt to Gemini, and parses `LIGHT_ON`/`LIGHT_OFF` from the response. Constants `_ILLUMINATION_FEATURE_PREFIX` and `_DEFAULT_ILLUMINATION_PENALTY` must live in `abstract.py` (the prefix is already there; the default is duplicated in endcap and graphic_panel — consolidate).
- **Depends on**: Existing `abstract.py` infrastructure (no new dependencies)

### Module 2: Remove Duplicate `_check_illumination()` from EndcapNoShelvesPromotional
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
- **Responsibility**: Delete local `_check_illumination()` (lines 454–558). Delete local `_DEFAULT_ILLUMINATION_PENALTY` (line 35) — import from base if still needed. Call sites already use `self._check_illumination()` so inheritance picks up the base method automatically.
- **Depends on**: Module 1

### Module 3: Add Illumination Enrichment to `ProductOnShelves.detect_objects()`
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py`
- **Responsibility**: After the legacy/grid detection returns `identified_products`, iterate through the raw `planogram_config["shelves"]` looking for products with `illumination_required`. For each matching detected product with `product_type == "promotional_graphic"` on the header shelf, call `self._check_illumination(img, zone_bbox=product.bbox, roi=roi)` once (cached per image) and prepend the result to `product.visual_features`.
- **Depends on**: Module 1

### Module 4: Add Illumination Penalty to `ProductOnShelves.check_planogram_compliance()`
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py`
- **Responsibility**: In the per-shelf product matching loop (around lines 486–513 of current file), after a product is matched, read `illumination_required` and `illumination_penalty` from the raw product config dict. Use `self._extract_illumination_state()` (base class static method) on the detected product's `visual_features`. If expected and detected both present AND mismatch: multiply that product's contribution to the shelf score by `(1.0 - illumination_penalty)`. Record mismatch in the `missing` list: `"{name} — backlight {detected} (required: {expected})"`. Update `found_names[insertion_idx] = "{name} (LIGHT_{detected})"`.
  **Default penalty for ProductOnShelves: 0.5** (differs from endcap's 1.0) — matches the 50/50 business rule.
- **Depends on**: Modules 1 and 3

### Module 5: Unit Tests
- **Path**: `packages/ai-parrot-pipelines/tests/test_product_on_shelves_illumination.py` (new file)
- **Responsibility**: Cover:
  - Config without `illumination_required` → no illumination check runs (backwards compat)
  - Config with `illumination_required: "on"` and detected ON → no penalty
  - Config with `illumination_required: "on"` and detected OFF → 0.5 penalty applied
  - Config with `illumination_required: "on"` and `illumination_penalty: 1.0` → 100% penalty
  - Illumination check failure (LLM returns None) → no penalty, graphic still scored on presence
  - `_check_illumination()` inherited from base class works on a ProductOnShelves instance
- **Depends on**: Modules 1, 3, 4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_abstract_has_check_illumination` | Module 1 | `AbstractPlanogramType` exposes `_check_illumination` as async method |
| `test_endcap_inherits_check_illumination` | Module 2 | `EndcapNoShelvesPromotional()._check_illumination` resolves to base class method |
| `test_endcap_compliance_still_works` | Module 2 | Existing endcap behavior unchanged after refactor (snapshot test) |
| `test_detect_objects_no_illumination_config` | Module 3 | `illumination_required` absent → no LLM call for illumination, no visual_features change |
| `test_detect_objects_illumination_enrichment` | Module 3 | With `illumination_required` set, `_check_illumination` called once, visual_features prepended |
| `test_compliance_illumination_match_no_penalty` | Module 4 | Expected ON + detected ON → shelf score unchanged |
| `test_compliance_illumination_mismatch_default_penalty` | Module 4 | Expected ON + detected OFF + no explicit penalty → score × 0.5 |
| `test_compliance_illumination_mismatch_custom_penalty` | Module 4 | Expected ON + detected OFF + `illumination_penalty: 1.0` → score × 0 |
| `test_compliance_illumination_llm_fails_defaults_on` | Module 4 | When `_check_illumination` exception path triggers (mock raises), returned value is `"illumination_status: ON"` and no penalty applied if expected=ON |
| `test_compliance_found_names_reflects_actual_state` | Module 4 | On mismatch, found_names contains `"{name} (LIGHT_OFF)"` |
| `test_compliance_missing_list_records_mismatch` | Module 4 | `missing` list includes `"{name} — backlight OFF (required: ON)"` |
| `test_backwards_compat_no_illumination_field` | Module 4 | Existing configs without `illumination_required` produce identical scores to current behavior |

### Integration Tests

| Test | Description |
|---|---|
| `test_scanner_config_with_backlit_on` | Full pipeline run on scanner endcap photo with backlit ON → header 100% |
| `test_scanner_config_with_backlit_off` | Full pipeline run on scanner endcap photo with backlit OFF → header 50% (presence kept) |
| `test_scanner_config_missing_graphic` | Full pipeline run with missing graphic → header 0% (presence fail dominates) |

### Test Data / Fixtures

```python
@pytest.fixture
def scanner_config_with_illumination():
    """Planogram config mimicking epson_scanner_backlit with illumination_required."""
    return {
        "shelves": [
            {
                "level": "header",
                "is_background": True,
                "products": [{
                    "name": "Epson Scanners Header Graphic (backlit)",
                    "product_type": "promotional_graphic",
                    "visual_features": ["large backlit lightbox"],
                    "illumination_required": "on",
                    "illumination_penalty": 0.5,
                }],
                "height_ratio": 0.25,
                "y_start_ratio": 0.0,
            },
            # ... product shelves
        ],
        "advertisement_endcap": {
            "enabled": True,
            "position": "header",
            "product_weight": 0.8,
            "text_weight": 0.2,
        }
    }

@pytest.fixture
def mock_illumination_on():
    """Mock _check_illumination to return ON."""
    return "illumination_status: ON"

@pytest.fixture
def mock_illumination_off():
    """Mock _check_illumination to return OFF."""
    return "illumination_status: OFF"
```

---

## 5. Acceptance Criteria

- [ ] Module 1: `AbstractPlanogramType._check_illumination()` implemented and documented with Google-style docstring
- [ ] Module 2: `EndcapNoShelvesPromotional._check_illumination()` removed; existing tests pass unchanged
- [ ] Module 3: `ProductOnShelves.detect_objects()` invokes illumination check when config declares `illumination_required`; single call per image (cached)
- [ ] Module 4: Illumination penalty applied in `check_planogram_compliance()`; default 0.5, configurable via `illumination_penalty`
- [ ] All unit tests pass (`pytest packages/ai-parrot-pipelines/tests/test_product_on_shelves_illumination.py -v`)
- [ ] Existing tests still pass (`pytest packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py -v`)
- [ ] No breaking changes: running the existing `epson_scanner_backlit_planogram_config` WITHOUT adding `illumination_required` produces identical scores to pre-feature behavior
- [ ] Adding `illumination_required: "on"` + `illumination_penalty: 0.5` to the scanner config produces: 100% header score if backlit ON, 50% header score if backlit OFF (with all other factors constant)
- [ ] Logging: `self.logger.info("Illumination check for %s: expected=%s detected=%s", name, expected, detected)` — uses lazy formatting per AI-Parrot conventions
- [ ] No new external dependencies
- [ ] Documentation: add brief note in `packages/ai-parrot-pipelines/README.md` (if exists) or inline docstring of `ProductOnShelves` class describing the new fields

---

## 6. Codebase Contract

> **Verified against dev branch at commit 84e343df on 2026-04-12.**

### Verified Imports

```python
# All imports confirmed to resolve:
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType  # verified: types/abstract.py:24
from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves  # verified: types/product_on_shelves.py:38
from parrot_pipelines.planogram.types.endcap_no_shelves_promotional import EndcapNoShelvesPromotional  # verified: types/endcap_no_shelves_promotional.py:41
from parrot.models.google import GoogleModel  # verified: parrot/models/google.py:12
```

### Existing Class Signatures

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
_ILLUMINATION_FEATURE_PREFIX = "illumination_status:"  # line 7

class AbstractPlanogramType(ABC):  # line 24
    async def detect_objects_roi(...) -> ...:  # line 73
    async def detect_objects(...) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:  # line 92
    def check_planogram_compliance(...) -> Dict[str, ComplianceResult]:  # line 110

    @staticmethod
    def _extract_illumination_state(features: List[str]) -> Optional[str]:  # line 126
        # Parses "illumination_status: ON" or "illumination_status: OFF" (case-insensitive)
        # Returns normalized "on"/"off" or None

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py
class ProductOnShelves(AbstractPlanogramType):  # line 38
    async def detect_objects_roi(...) -> ...:  # line 87
    async def detect_objects(self, img, roi, macro_objects) -> ...:  # line 122
    async def _detect_legacy(...) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:  # line 218
    def check_planogram_compliance(
        self,
        identified_products: List[IdentifiedProduct],
        planogram_description: PlanogramDescription,
    ) -> Dict[str, ComplianceResult]:  # line 344

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py
_DEFAULT_ILLUMINATION_PENALTY: float = 1.0  # line 35

class EndcapNoShelvesPromotional(AbstractPlanogramType):  # line 41
    async def detect_objects_roi(...) -> ...:  # line 214
    async def detect_objects(...) -> ...:  # line 312
    async def _check_illumination(
        self,
        img: Image.Image,
        roi: Any,
        planogram_description: Any,
        illum_zone_bbox: Optional[Any] = None,
    ) -> str:  # line 454  ← TO BE PROMOTED TO BASE (verbatim)
        # Defaults to "illumination_status: ON" on LLM exception (line 547)
        # Uses self.pipeline.roi_client.ask_to_image() + GoogleModel.GEMINI_3_FLASH_PREVIEW
    def check_planogram_compliance(...) -> Dict[str, ComplianceResult]:  # line 560
    # Illumination penalty logic at lines 669-699

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py
_DEFAULT_ILLUMINATION_PENALTY: float = 1.0  # line 34  ← DUPLICATE — consolidate in abstract.py
_ILLUMINATION_FEATURE_PREFIX = "illumination_status:"  # line 37  ← DUPLICATE — already in abstract.py

class GraphicPanelDisplay(AbstractPlanogramType):  # line 40
    async def _check_illumination_from_roi(...) -> Optional[str]:  # line 666  ← NOT refactored in this spec
```

### Integration Points

| New / Modified Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AbstractPlanogramType._check_illumination()` | Gemini via `self.pipeline.roi_client.ask_to_image()` | async method call with `GoogleModel.GEMINI_3_FLASH_PREVIEW` | `endcap_no_shelves_promotional.py:536-543` (verified current impl) |
| `ProductOnShelves.detect_objects()` | `self._check_illumination(img, roi, planogram_description, illum_zone_bbox=bbox)` | inherited method, 3 required positional + 1 optional keyword | `product_on_shelves.py:122-178` (insertion point) |
| `ProductOnShelves.check_planogram_compliance()` | `self._extract_illumination_state()` | static base method | `abstract.py:126` |
| Raw config dict `planogram_config["shelves"]` | `ProductOnShelves` | read via `self.planogram_config.planogram_config` | `plan.py:174` (established pattern from FEAT-090) |

### Does NOT Exist (Anti-Hallucination)

- ~~`ProductOnShelves._check_illumination()`~~ — does NOT currently exist; will be inherited from base after Module 1
- ~~`ShelfProduct.illumination_required`~~ — NOT a declared Pydantic field; must read from raw config dict (same pattern as `text_requirements` from FEAT-090)
- ~~`ShelfProduct.illumination_penalty`~~ — NOT a declared Pydantic field; read from raw config dict
- ~~`ShelfConfig.illumination_penalty`~~ — `GraphicPanelDisplay` uses `shelf_cfg.illumination_penalty` via a helper `_get_illumination_penalty()` at `graphic_panel_display.py:869` — this is a per-shelf field, NOT a documented Pydantic attribute. Read from raw dict for ProductOnShelves.
- ~~`AbstractPlanogramType._check_illumination()`~~ — does NOT exist yet in base class; Module 1 creates it
- ~~`_DEFAULT_ILLUMINATION_PENALTY` in `abstract.py`~~ — does NOT exist; currently duplicated in endcap.py:35 and graphic_panel.py:34. Module 1 consolidates in abstract.py.
- ~~Grid detection path `_detect_with_grid()`~~ — exists (`product_on_shelves.py:122-178` routes to it) but illumination enrichment should work regardless of detection path. Keep Module 3 insertion point in the common post-detection area, not inside `_detect_legacy()` exclusively.
- ~~`self.pipeline.llm_client.vision_completion()`~~ — does NOT exist. Real call is `self.pipeline.roi_client.ask_to_image(image, prompt, model, no_memory, max_tokens)` (verified at endcap_no_shelves_promotional.py:537-543).
- ~~`_check_illumination()` returns `Optional[str]`~~ — actual return type is `str` (non-optional). Method defaults to `"illumination_status: ON"` on LLM exception instead of returning None. Module 4 must NOT guard against `None` — the value is always present.
- ~~`_check_illumination(img, zone_bbox=..., roi=...)`~~ — keyword order wrong. Correct signature: `(img, roi, planogram_description, illum_zone_bbox=None)`. All three of `img`, `roi`, `planogram_description` are REQUIRED positional; `illum_zone_bbox` is optional.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Follow the established pattern from FEAT-090 (endcap-no-shelves-promotional-fix): read non-Pydantic config fields from raw `planogram_config` dict via `getattr(self.planogram_config, "planogram_config", {})`
- Use `self.logger.info("msg: %s", value)` lazy formatting (not f-strings) — per AI-Parrot logging convention
- Default `illumination_penalty` for ProductOnShelves = **0.5** (different from endcap's 1.0) — hardcode in Module 4 logic as the fallback when config doesn't specify
- Use `GoogleModel.GEMINI_3_FLASH_PREVIEW` from `parrot.models.google` — do NOT hardcode model strings (per FEAT-090 refactor)
- Cache illumination result per image: one LLM call even if multiple products have `illumination_required`
- Capture index of `found_names.append(name)` at insertion time to support future multi-product-per-shelf (per code review feedback on FEAT-090)

### Known Risks / Gotchas

- **Risk 1**: Promoting `_check_illumination()` from endcap to base could break the endcap if the implementation silently depends on instance attributes only in the subclass.
  *Mitigation*: Audit the existing implementation (endcap:454-558) for any `self.config` or `self.pipeline` field accesses that are endcap-specific. If any exist, abstract them as method parameters or leave a subclass override.

- **Risk 2**: `ProductOnShelves.detect_objects()` routes to either `_detect_legacy()` or `_detect_with_grid()` — injecting illumination into only one path would create inconsistent behavior.
  *Mitigation*: Add illumination enrichment AFTER both paths return, in the `detect_objects()` method itself (common post-processing).

- **Risk 3**: The header zone crop for illumination check requires a reliable bbox for the promotional_graphic product. If detection returned no bbox for the header, crop fallback must use the full ROI.
  *Mitigation*: Mirror the endcap pattern — `_check_illumination(img, zone_bbox=bbox or None, roi=roi)` — the method already handles the fallback internally.

- **Risk 4**: Existing production configs MUST NOT regress. The `epson_scanner_backlit_planogram_config` currently scores without illumination; after the feature, scores must be identical UNTIL `illumination_required` is explicitly added to the config.
  *Mitigation*: Module 3 must guard the entire illumination enrichment block with `if has_illumination_required: ...`. Add explicit regression test.

- **Risk 5**: `_check_illumination()` NEVER returns `None` — on LLM exception it defaults to `"illumination_status: ON"` (per endcap:547). This means a failed LLM call could silently hide a real OFF state.
  *Mitigation*: Keep current behavior for backwards compat, but log WARNING in the promoted base method when the exception path is taken so operators can detect systemic LLM failures. Do NOT change the fallback to `OFF` or `None` — that would break the existing endcap behavior.

- **Risk 6**: The `found_names[-1] == prod_name` fragility from FEAT-090 (multi-product per shelf) also applies here.
  *Mitigation*: Use the insertion-index-capture pattern recommended in the FEAT-090 code review.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | No new dependencies |

---

## Worktree Strategy

**Default isolation unit: `per-spec`** — all tasks run sequentially in one worktree.

**Rationale**: The 5 modules touch 3 files total (`abstract.py`, `endcap_no_shelves_promotional.py`, `product_on_shelves.py` + new test file). Module 2 depends on Module 1 (must promote before removing duplicate). Modules 3 and 4 depend on Module 1. Module 5 depends on everything. No meaningful parallelism possible.

**Cross-feature dependencies**: PR #785 (FEAT-090) is already merged to dev. No in-flight specs touch the planogram types directory.

**Worktree creation** (from dev):
```bash
cd /home/juanfran/Documents/navigator/AI-BOTS/ai-parrot
git checkout dev
git worktree add -b feat-091-product-on-shelves-illumination \
  .claude/worktrees/feat-091-product-on-shelves-illumination HEAD
```

---

## 8. Open Questions

- [x] Default illumination penalty for ProductOnShelves — *Resolved: 0.5*
- [x] Scope of illumination check — *Resolved: header shelf only (per product config)*
- [x] Combined vs separate LLM call with enrichment — *Resolved: keep separate (precision > cost)*
- [ ] Should Module 3 insertion point be in `detect_objects()` (common) or `_detect_legacy()` (specific)? — *Owner: implementing agent — resolve by reading exact structure during TASK-628*
- [ ] Does `_check_illumination()` at endcap:454-558 depend on any endcap-specific state? — *Owner: implementing agent — audit during TASK-628 before promoting*
- [ ] Should `GraphicPanelDisplay._check_illumination_from_roi()` also be consolidated into the base? — *Owner: juanfran — deferred to follow-up spec*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-12 | Juan2coder | Initial draft from brainstorm |
