# TASK-658: Pre-built ExtractionPlans

**Feature**: intelligent-scraping-pipeline
**Spec**: `sdd/specs/intelligent-scraping-pipeline.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-653, TASK-655
**Assigned-to**: unassigned

---

## Context

> Implements Module 7 from the spec. Creates hand-authored JSON ExtractionPlan files
> for common site patterns. These are loaded into the ExtractionPlanRegistry at
> initialization with `source="developer"`, providing instant extraction capabilities
> for known site types without requiring LLM reconnaissance.

---

## Scope

- Create `extraction_plans/_prebuilt/` directory structure
- Create `generic_ecommerce.json` ExtractionPlan (product entities with name, price, rating, description, URL)
- Create `generic_telecom.json` ExtractionPlan (plan entities with name, price, data, features, restrictions)
- Validate both JSON files parse into valid `ExtractionPlan` objects
- Write tests that load pre-built plans and verify they are valid

**NOT in scope**:
- Site-specific plans (att.com, amazon.com, bestbuy.com) — future work
- CLI for plan authoring
- ExtractionPlanRegistry (TASK-655) — but depends on it for loading

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_plans/_prebuilt/generic_ecommerce.json` | CREATE | Generic e-commerce ExtractionPlan |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_plans/_prebuilt/generic_telecom.json` | CREATE | Generic telecom plans ExtractionPlan |
| `packages/ai-parrot-tools/tests/scraping/test_prebuilt_plans.py` | CREATE | Validation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.extraction_models import ExtractionPlan, EntitySpec, EntityFieldSpec  # created by TASK-653
from parrot_tools.scraping.extraction_registry import ExtractionPlanRegistry  # created by TASK-655
```

### Existing Signatures to Use
```python
# Created by TASK-653 — ExtractionPlan JSON schema
# Plans must validate against ExtractionPlan.model_json_schema()

# Created by TASK-655 — ExtractionPlanRegistry
class ExtractionPlanRegistry:
    async def load_prebuilt(self, directory: Path) -> int:
        """Load pre-built JSON plans from directory."""
```

### Does NOT Exist
- ~~`extraction_plans/_prebuilt/`~~ -- does not exist yet; THIS TASK creates it
- ~~`generic_ecommerce.json`~~ -- does not exist yet
- ~~`generic_telecom.json`~~ -- does not exist yet

---

## Implementation Notes

### generic_ecommerce.json Structure
```json
{
  "url": "https://*.example.com/products/*",
  "objective": "Extract product listings from e-commerce pages",
  "page_category": "ecommerce_product_listing",
  "source": "developer",
  "extraction_strategy": "hybrid",
  "entities": [
    {
      "entity_type": "product",
      "description": "A product listing on an e-commerce page",
      "repeating": true,
      "container_selector": ".product-card, .product-item, [data-product]",
      "fields": [
        {"name": "product_name", "description": "Product title/name", "selector": "h2, h3, .product-title", "required": true},
        {"name": "price", "description": "Current price", "field_type": "currency", "selector": ".price, .product-price", "required": true},
        {"name": "original_price", "description": "Original/strikethrough price", "field_type": "currency", "selector": ".original-price, .was-price", "required": false},
        {"name": "rating", "description": "Star rating", "field_type": "number", "selector": ".rating, .stars", "required": false},
        {"name": "review_count", "description": "Number of reviews", "field_type": "number", "selector": ".review-count", "required": false},
        {"name": "description", "description": "Short product description", "selector": ".description, .product-desc", "required": false},
        {"name": "product_url", "description": "Link to product detail page", "field_type": "url", "selector": "a", "extract_from": "attribute", "attribute": "href", "required": false}
      ]
    }
  ],
  "ignore_sections": ["nav", "footer", ".cookie-banner", "#newsletter-popup"]
}
```

### Key Constraints
- Plans must be valid JSON that `ExtractionPlan.model_validate()` accepts
- Use generic CSS selectors that work across many sites (multiple fallback selectors)
- `source` must be `"developer"`
- URL patterns use wildcards for broad matching

---

## Acceptance Criteria

- [ ] `generic_ecommerce.json` exists and validates as `ExtractionPlan`
- [ ] `generic_telecom.json` exists and validates as `ExtractionPlan`
- [ ] Both plans have `source="developer"`
- [ ] Both plans load via `ExtractionPlanRegistry.load_prebuilt()`
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_prebuilt_plans.py -v`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/scraping/test_prebuilt_plans.py
import json
import pytest
from pathlib import Path
from parrot_tools.scraping.extraction_models import ExtractionPlan

PREBUILT_DIR = Path(__file__).parent.parent.parent / "src" / "parrot_tools" / "scraping" / "extraction_plans" / "_prebuilt"


class TestPrebuiltPlans:
    @pytest.mark.parametrize("filename", ["generic_ecommerce.json", "generic_telecom.json"])
    def test_plan_validates(self, filename):
        plan_path = PREBUILT_DIR / filename
        assert plan_path.exists(), f"Pre-built plan {filename} not found"
        with open(plan_path) as f:
            data = json.load(f)
        plan = ExtractionPlan.model_validate(data)
        assert plan.source == "developer"
        assert len(plan.entities) > 0

    @pytest.mark.parametrize("filename", ["generic_ecommerce.json", "generic_telecom.json"])
    def test_plan_has_selectors(self, filename):
        plan_path = PREBUILT_DIR / filename
        with open(plan_path) as f:
            data = json.load(f)
        plan = ExtractionPlan.model_validate(data)
        for entity in plan.entities:
            assert len(entity.fields) > 0
            has_selector = any(f.selector for f in entity.fields)
            assert has_selector, f"Entity {entity.entity_type} has no selectors"
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** -- verify TASK-653 and TASK-655 are completed
2. **Read ExtractionPlan model** from TASK-653 output to understand the schema
3. **Create directory structure** and JSON files
4. **Validate** both files parse correctly
5. **Move to completed**, update index

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
