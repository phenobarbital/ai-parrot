# TASK-653: ExtractionPlan Data Models

**Feature**: intelligent-scraping-pipeline
**Spec**: `sdd/specs/intelligent-scraping-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This is the foundational task for FEAT-096. All other tasks depend on these data models.
> Implements Module 1 from the spec: Pydantic models for the intelligent extraction pipeline.
> The ExtractionPlan is a richer representation than ScrapingPlan — it describes WHAT entities
> and fields to extract, with rationale. It translates to a ScrapingPlan for mechanical execution.

---

## Scope

- Implement `EntityFieldSpec` Pydantic model (field within an entity)
- Implement `EntitySpec` Pydantic model (entity type to extract)
- Implement `ExtractionPlan` Pydantic model with:
  - Auto-populated `domain`, `name`, `fingerprint` from URL (reuse `_normalize_url`, `_compute_fingerprint`, `_sanitize_domain` from `plan.py`)
  - `to_scraping_plan()` method that translates to a valid `ScrapingPlan`
  - Cache lifecycle fields (`success_count`, `failure_count`)
- Implement `ExtractedEntity` Pydantic model (single extracted entity)
- Implement `ExtractionResult` Pydantic model (complete extraction run result)
- Write unit tests for all models

**NOT in scope**:
- Registry (TASK-654, TASK-655)
- LLM plan generation (TASK-656)
- Recall processing (TASK-657)
- ScrapingAgent integration (TASK-659)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_models.py` | CREATE | All extraction data models |
| `packages/ai-parrot-tools/tests/scraping/test_extraction_models.py` | CREATE | Unit tests |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/__init__.py` | MODIFY | Export new models |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Use these VERBATIM:
from parrot_tools.scraping.plan import ScrapingPlan  # verified: plan.py:59
from parrot_tools.scraping.plan import _normalize_url  # verified: plan.py:18
from parrot_tools.scraping.plan import _compute_fingerprint  # verified: plan.py:31
from parrot_tools.scraping.plan import _sanitize_domain  # verified: plan.py:47
from pydantic import BaseModel, Field, computed_field  # used throughout plan.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py

def _normalize_url(url: str) -> str:  # line 18
    """Strip query params and fragments for stable fingerprinting."""

def _compute_fingerprint(normalized_url: str) -> str:  # line 31
    """Compute a 16-char SHA-256 hex prefix of a normalized URL."""

def _sanitize_domain(domain: str) -> str:  # line 47
    """Convert a domain into a valid name slug."""

class ScrapingPlan(BaseModel):  # line 59
    name: Optional[str] = None          # line 67
    version: str = "1.0"               # line 68
    tags: List[str] = Field(default_factory=list)  # line 69
    url: str                            # line 72
    domain: str = ""                    # line 73
    objective: str                      # line 74
    steps: List[Dict[str, Any]]         # line 77
    selectors: Optional[List[Dict[str, Any]]] = None  # line 78
    browser_config: Optional[Dict[str, Any]] = None  # line 79
    follow_selector: Optional[str] = None  # line 82
    follow_pattern: Optional[str] = None   # line 83
    max_depth: Optional[int] = None        # line 84
    created_at: datetime                   # line 87
    updated_at: Optional[datetime] = None  # line 88
    source: str = "llm"                    # line 89
    fingerprint: str = ""                  # line 90
    def model_post_init(self, __context: Any) -> None:  # line 98
```

### Does NOT Exist
- ~~`ScrapingPlan.extraction_strategy`~~ -- not a field on ScrapingPlan
- ~~`ScrapingPlan.entities`~~ -- not a field on ScrapingPlan
- ~~`ExtractionPlan`~~ -- does not exist yet; THIS TASK creates it
- ~~`ExtractedEntity`~~ -- does not exist yet; THIS TASK creates it
- ~~`ExtractionResult`~~ -- does not exist yet; THIS TASK creates it

---

## Implementation Notes

### Pattern to Follow
```python
# Follow ScrapingPlan's model_post_init pattern from plan.py:98
class ExtractionPlan(BaseModel):
    url: str
    domain: str = ""
    fingerprint: str = ""
    # ...

    def model_post_init(self, __context: Any) -> None:
        parsed = urlparse(self.url)
        if not self.domain:
            self.domain = parsed.netloc
        if self.name is None:
            self.name = _sanitize_domain(self.domain)
        if not self.fingerprint:
            self.fingerprint = _compute_fingerprint(_normalize_url(self.url))
```

### to_scraping_plan() Translation Rules
- `steps`: Generate `[{"action": "navigate", "url": plan.url}, {"action": "wait", "condition": "body", "condition_type": "selector"}]`
- `selectors`: Build from EntitySpec fields:
  - Each `EntityFieldSpec` with a non-None `selector` becomes a selector dict
  - Format: `{"name": "{entity_type}__{field_name}", "selector": "{container} {field_selector}", "extract_type": field.extract_from, "multiple": entity.repeating}`
  - When `container_selector` exists, compose: `f"{container_selector} {field_selector}"`
- `objective`: Copy from ExtractionPlan
- `source`: Set to `"extraction_plan"`

### Key Constraints
- All models must use Pydantic v2 BaseModel
- Reuse utility functions from `plan.py` -- do NOT duplicate them
- Google-style docstrings on all classes and public methods
- Type hints on all fields and methods

---

## Acceptance Criteria

- [ ] All 5 models created: EntityFieldSpec, EntitySpec, ExtractionPlan, ExtractedEntity, ExtractionResult
- [ ] `ExtractionPlan.to_scraping_plan()` produces valid ScrapingPlan with correct selectors
- [ ] Auto-populated fields (domain, name, fingerprint) work correctly
- [ ] JSON round-trip serialization/deserialization works
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_extraction_models.py -v`
- [ ] Models exported from `parrot_tools.scraping`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/scraping/test_extraction_models.py
import pytest
from parrot_tools.scraping.extraction_models import (
    EntityFieldSpec, EntitySpec, ExtractionPlan, ExtractedEntity, ExtractionResult
)
from parrot_tools.scraping.plan import ScrapingPlan


class TestEntityFieldSpec:
    def test_defaults(self):
        spec = EntityFieldSpec(name="price", description="Monthly price")
        assert spec.field_type == "text"
        assert spec.required is True
        assert spec.selector is None

    def test_all_field_types(self):
        for ft in ("text", "number", "currency", "url", "boolean", "list"):
            spec = EntityFieldSpec(name="f", description="d", field_type=ft)
            assert spec.field_type == ft


class TestExtractionPlan:
    def test_auto_fields(self):
        plan = ExtractionPlan(
            url="https://www.att.com/prepaid/",
            objective="Extract plans",
            entities=[],
        )
        assert plan.domain == "www.att.com"
        assert plan.fingerprint != ""
        assert plan.name is not None

    def test_to_scraping_plan(self):
        plan = ExtractionPlan(
            url="https://example.com/plans",
            objective="Extract plans",
            entities=[
                EntitySpec(
                    entity_type="plan",
                    description="A plan",
                    fields=[
                        EntityFieldSpec(name="title", description="Plan name", selector="h3"),
                        EntityFieldSpec(name="price", description="Price", selector=".price"),
                    ],
                    container_selector=".plan-card",
                )
            ],
        )
        sp = plan.to_scraping_plan()
        assert isinstance(sp, ScrapingPlan)
        assert len(sp.steps) >= 1
        assert sp.selectors is not None
        assert len(sp.selectors) == 2

    def test_serialization_roundtrip(self):
        plan = ExtractionPlan(
            url="https://example.com",
            objective="test",
            entities=[],
        )
        json_str = plan.model_dump_json()
        restored = ExtractionPlan.model_validate_json(json_str)
        assert restored.url == plan.url
        assert restored.fingerprint == plan.fingerprint
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/intelligent-scraping-pipeline.spec.md` for full context
2. **Check dependencies** -- this task has none; it can start immediately
3. **Verify the Codebase Contract** -- before writing ANY code:
   - Confirm `_normalize_url`, `_compute_fingerprint`, `_sanitize_domain` exist in `plan.py`
   - Confirm `ScrapingPlan` model structure matches the contract
   - **NEVER** reference an import not listed in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` -> `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-653-extraction-plan-models.md`
8. **Update index** -> `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
