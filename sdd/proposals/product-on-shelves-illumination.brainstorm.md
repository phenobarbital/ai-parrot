# Brainstorm: Product-On-Shelves Illumination Support

**Date**: 2026-04-12
**Author**: Juan2coder + Claude
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

Epson scanner displays at Office Depot have a **backlit header panel** ("Scan & Done" with Shaq photo) above 3 shelves of physical scanner products. The `product_on_shelves` planogram type already handles product detection and compliance scoring for the shelves, but it has **zero illumination support** — the backlit header's ON/OFF state is completely ignored.

The business requirement is:
- **50% score** for the header shelf if the correct graphic is present (visual features + text match)
- **100% score** for the header shelf if the graphic is present AND the backlight is ON
- **0% score** if the graphic is missing entirely

This is currently a single config (`epson_scanner_backlit_planogram_config`, planogram_id=15) but the solution must be opt-in to avoid breaking existing `product_on_shelves` configs already in production.

## Constraints & Requirements

- **Backwards compatible**: existing `product_on_shelves` configs must not be affected. The illumination check must be opt-in via config fields.
- **Scoring model**: illumination penalty = 0.5 (presence = 50%, illumination ON = remaining 50%). Must be configurable per shelf/product.
- **Illumination check uses crop**: crop the header zone and send to LLM (like `endcap_no_shelves_promotional`), not the full image.
- **Header-only for now**: illumination only applies to the header shelf (`is_background: True`). Non-header shelves are unaffected.
- **No new pipeline type**: must reuse existing `product_on_shelves` type.
- **Reuse existing infrastructure**: `_check_illumination()` from `EndcapNoShelvesPromotional` and `_extract_illumination_state()` from base class.

---

## Options Explored

### Option A: Add illumination flag to ProductOnShelves (detect_objects + compliance penalty)

Add opt-in `illumination_required` field to the header product config. During `detect_objects()`, if any product has `illumination_required`, run `_check_illumination()` with the header zone crop and seed the product's `visual_features` with the result. During `check_planogram_compliance()`, apply configurable penalty when detected state mismatches expected state.

This follows the exact pattern already proven in `EndcapNoShelvesPromotional` and `GraphicPanelDisplay`.

The config would add:
```json
{
  "name": "Epson Scanners Header Graphic (backlit)",
  "illumination_required": "on",
  "illumination_penalty": 0.5
}
```

Implementation touches:
1. `detect_objects()` / `_detect_legacy()`: after building identified_products, check for promotional items with `illumination_required`, call `_check_illumination()`, seed visual_features.
2. `check_planogram_compliance()`: in the per-shelf loop, after product matching, extract illumination state from config and detected features, apply penalty if mismatch.
3. Promote `_check_illumination()` from `EndcapNoShelvesPromotional` to `AbstractPlanogramType` base class (it's already generic enough).

Pros:
- Minimal code change (~50-60 lines added to `product_on_shelves.py`)
- Follows proven pattern from 2 other types
- 100% opt-in — no impact on existing configs
- Reuses `_check_illumination()` and `_extract_illumination_state()` directly
- Configurable penalty per product (0.5 for this case, 1.0 for others)

Cons:
- Requires promoting `_check_illumination()` to base class (minor refactor)
- The header zone crop depends on reliable shelf boundary detection for y-coordinates

Effort: Low

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| No new dependencies | All existing | Uses Gemini LLM via existing GoogleGenAIClient |

Existing Code to Reuse:
- `types/abstract.py:125-143` — `_extract_illumination_state()` static method (already inherited)
- `types/endcap_no_shelves_promotional.py:454-558` — `_check_illumination()` method (promote to base)
- `types/graphic_panel_display.py:849-870` — `_get_illumination_penalty()` helper pattern

---

### Option B: New planogram type `product_on_shelves_backlit`

Create a subclass of `ProductOnShelves` that overrides `detect_objects()` and `check_planogram_compliance()` to add illumination logic. Register as a new `planogram_type` in the dispatch map.

Pros:
- Zero risk to existing `product_on_shelves` code
- Clean separation of concerns

Cons:
- Code duplication — the subclass would copy significant logic from the parent
- New type to maintain, register, document
- The config already declares `planogram_type: 'product_on_shelves'` — changing it requires config migration
- Overkill for adding a single optional feature flag
- Sets a bad precedent: every new feature flag would spawn a new type

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| No new dependencies | All existing | — |

Existing Code to Reuse:
- `types/product_on_shelves.py` — entire class as parent
- `types/endcap_no_shelves_promotional.py:454-558` — `_check_illumination()` method

---

### Option C: Composition — run two pipeline types on the same image

Split the config into two: run `endcap_no_shelves_promotional` for the header (illumination check) and `product_on_shelves` for the shelves (product compliance). Merge the results.

Pros:
- No changes to either existing pipeline type
- Each type does what it's best at

Cons:
- Requires a new orchestration layer to merge results from two types
- Two LLM calls for ROI detection (one per type) = higher cost and latency
- Scoring merge logic is complex and untested
- The header shelf would need to be removed from the `product_on_shelves` config and duplicated in a separate `endcap_no_shelves_promotional` config
- Fragile — two configs that must stay in sync

Effort: High

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| No new dependencies | All existing | — |

Existing Code to Reuse:
- `types/endcap_no_shelves_promotional.py` — full type for header
- `types/product_on_shelves.py` — full type for shelves

---

## Recommendation

**Option A** is recommended because:

- It's the lowest effort path (~50-60 lines) with zero risk to existing configs
- The illumination infrastructure already exists and is battle-tested in production (endcap + graphic_panel types)
- The pattern is identical to what `EndcapNoShelvesPromotional` and `GraphicPanelDisplay` already do — promoting `_check_illumination()` to the base class is a natural refactor that benefits all types
- The 50/50 scoring model maps directly to `illumination_penalty: 0.5` — the penalty mechanism already supports this
- Option B creates unnecessary type proliferation. Option C is architecturally complex for a simple flag.

The tradeoff is that we touch `product_on_shelves.py` (production code) rather than isolating in a new type. This is acceptable because the change is entirely opt-in — `illumination_required` defaults to `None`, and the penalty logic only fires when the field is present.

---

## Feature Description

### User-Facing Behavior

From the operator perspective: when a planogram config for `product_on_shelves` includes `illumination_required: "on"` (or `"off"`) on a product, the compliance report will:
- Check whether the backlit panel is physically illuminated
- Penalize the header shelf score by the configured `illumination_penalty` (default 0.5) if the state doesn't match
- Show the actual state in `found_products`, e.g., `"Epson Scanners Header Graphic (backlit) (LIGHT_OFF)"`
- Include a human-readable violation in the `missing` list, e.g., `"Epson Scanners Header Graphic (backlit) — backlight OFF (required: ON)"`

If `illumination_required` is not set in the config, behavior is identical to today — no illumination check runs.

### Internal Behavior

**During detect_objects() (Step 2):**
1. After building the identified_products list from LLM detection
2. For each product with `product_type == "promotional_graphic"`: check if the raw config has `illumination_required`
3. If yes: crop the header zone using the product's DetectionBox coordinates
4. Call `_check_illumination(crop)` — sends the crop to Gemini with a chain-of-thought prompt asking about internal glow, frame halo, color saturation
5. Cache the result (one LLM call per image, reused across products)
6. Seed the product's `visual_features` with `"illumination_status: ON"` or `"illumination_status: OFF"`

**During check_planogram_compliance() (Step 4):**
1. In the per-shelf product matching loop, after a product is matched
2. Read `illumination_required` from the product's config
3. Read detected illumination state from the matched product's `visual_features` via `_extract_illumination_state()`
4. If `expected != detected`: multiply the product's contribution to the shelf score by `(1 - illumination_penalty)`
5. Record the mismatch in the `missing` list and update `found_names` with the actual state label

**Scoring example (illumination_penalty = 0.5):**
- Header graphic present + light ON → shelf score contribution = 1.0 (100%)
- Header graphic present + light OFF → shelf score contribution = 0.5 (50%)
- Header graphic missing → shelf score contribution = 0.0 (0%)

### Edge Cases & Error Handling

- **`illumination_required` not in config**: no illumination check runs. Fully backwards compatible.
- **`_check_illumination()` LLM call fails**: log warning, default to `None` (no penalty applied). The graphic is still scored on presence/text alone.
- **Header zone crop has invalid coordinates**: fall back to full ROI image (same as EndcapNoShelvesPromotional behavior).
- **Multiple promotional_graphic products on same shelf**: each gets its own illumination check (unlikely scenario today but safe).
- **`illumination_penalty` not in config**: default to 0.5 for `product_on_shelves` (unlike 1.0 default in other types). This matches the 50/50 business requirement.

---

## Capabilities

### New Capabilities
- `product-on-shelves-illumination`: opt-in illumination checking for `product_on_shelves` planogram type header panels

### Modified Capabilities
- `abstract-planogram-type`: promote `_check_illumination()` from `EndcapNoShelvesPromotional` to base class
- `product-on-shelves-compliance`: add illumination penalty logic to scoring

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `types/abstract.py` | extends | Add `_check_illumination()` method (moved from EndcapNoShelvesPromotional) |
| `types/product_on_shelves.py` | modifies | Add illumination check in detect_objects + penalty in check_planogram_compliance |
| `types/endcap_no_shelves_promotional.py` | modifies | Remove `_check_illumination()` (now in base), keep call sites |
| `types/graphic_panel_display.py` | modifies | Update to call base `_check_illumination()` instead of local `_check_illumination_from_roi()` (optional, can be done later) |
| Planogram config JSON | extends | New optional fields: `illumination_required`, `illumination_penalty` on product entries |

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# From types/abstract.py:19
class AbstractPlanogramType(ABC):
    # line 125-143: _extract_illumination_state() — static method, parses "illumination_status: ON/OFF" from features list
    @staticmethod
    def _extract_illumination_state(features: List[str]) -> Optional[str]:
        ...

# From types/product_on_shelves.py:38
class ProductOnShelves(AbstractPlanogramType):
    # line 122-178: detect_objects() — routes to _detect_with_grid() or _detect_legacy()
    # line 344-678: check_planogram_compliance() — per-shelf scoring
    # line 640-648: header shelf score = adjusted_product_weight * basic_score + text_weight * text_score + brand_weight * brand_confidence + visual_weight * visual_feature_score
    # line 649-658: non-header shelf score = product_weight * basic_score + text_weight * text_score + visual_weight * visual_feature_score

# From types/endcap_no_shelves_promotional.py:454-558
async def _check_illumination(self, img, roi, planogram_description) -> Optional[str]:
    # Crops to zone bbox or full ROI
    # Sends LLM prompt with chain-of-thought reasoning
    # Returns "illumination_status: ON" or "illumination_status: OFF"

# From types/endcap_no_shelves_promotional.py:669-699
# Illumination penalty logic:
#   expected_illum from config `illumination_required` or visual_features
#   detected_illum from matched product's visual_features
#   zone_score *= (1.0 - penalty) when mismatch
```

#### Verified Imports
```python
# These imports are confirmed to work:
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType  # types/__init__.py
from parrot.models.google import GoogleModel  # parrot/models/google.py:12
```

#### Key Attributes & Constants
- `_ILLUMINATION_FEATURE_PREFIX = "illumination_status: "` — used by `_extract_illumination_state()` (abstract.py)
- `_DEFAULT_ILLUMINATION_PENALTY = 1.0` — default in endcap/graphic_panel (for ProductOnShelves, recommend 0.5)
- `advertisement_endcap.product_weight` = 0.8, `text_weight` = 0.2 — header shelf weights in scanner config
- `shelf_cfg.is_background` — True for header shelves, preserved through fact-tag refinement

### Does NOT Exist (Anti-Hallucination)
- ~~`ProductOnShelves._check_illumination()`~~ — does NOT exist, must be added (or inherited from base)
- ~~`ProductOnShelves.illumination_penalty`~~ — not a class attribute, must be read from config per-product
- ~~`ShelfProduct.illumination_required`~~ — not a declared Pydantic field; must be read from raw `planogram_config` dict (same pattern as `text_requirements` in plan.py)
- ~~`AbstractPlanogramType._check_illumination()`~~ — does NOT exist in base class yet; currently only in EndcapNoShelvesPromotional

---

## Parallelism Assessment

- **Internal parallelism**: Low — TASK-1 (promote _check_illumination to base) must complete before TASK-2 (add to ProductOnShelves). TASK-3 (tests) depends on both.
- **Cross-feature independence**: No conflicts with in-flight specs. The endcap_no_shelves_promotional changes from PR #785 are already merged to dev.
- **Recommended isolation**: `per-spec` — all tasks sequential in one worktree
- **Rationale**: 3 files in the same module, each task depends on the previous. No benefit from splitting.

---

## Open Questions

- [x] Illumination penalty value — *Resolved: 0.5 (50% presence, 50% illumination)*
- [x] Header-only or any shelf — *Resolved: header only for now*
- [x] Crop vs full image — *Resolved: crop header zone*
- [ ] Should `_check_illumination_from_roi()` in GraphicPanelDisplay also be refactored to use the base class method? — *Owner: juanfran — can be deferred to follow-up*
- [ ] Should `vision_model: 'gemini-2.5-flash'` in the scanner config be updated to use `GoogleModel` enum? — *Owner: juanfran — separate from this feature*
