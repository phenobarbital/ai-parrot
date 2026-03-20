# TASK-038: ScrapingPlan Pydantic Model

**Feature**: FEAT-012 — ScrapingPlan & PlanRegistry
**Spec**: `sdd/specs/scrapingplan-planregistry.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> This task implements Module 1 from the spec: the `ScrapingPlan` Pydantic model.
> This is the foundational data model that all other tasks depend on. It represents
> the declarative contract for scraping plans — a value object that is immutable
> once saved to disk. It also includes the `PlanRegistryEntry` model used by the
> registry index.

---

## Scope

- Implement `ScrapingPlan` Pydantic v2 `BaseModel` with all fields from spec Section 2 (Data Models)
- Implement URL normalization (strip query params and fragments) as a `computed_field`
- Implement fingerprint generation (SHA-256 prefix of normalized URL, 16 chars)
- Implement `model_post_init` for auto-populating `domain`, `name`, and `fingerprint`
- Implement `PlanRegistryEntry` Pydantic model
- Write unit tests for model validation, auto-population, fingerprint stability, and JSON round-trip

**NOT in scope**: Registry logic (TASK-039), file I/O (TASK-040), WebScrapingTool integration (TASK-041)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/plan.py` | CREATE | ScrapingPlan and PlanRegistryEntry models |
| `tests/tools/scraping/test_plan_model.py` | CREATE | Unit tests for the models |

---

## Implementation Notes

### Pattern to Follow
```python
# Follow Pydantic v2 patterns used in parrot/tools/scraping/models.py
from pydantic import BaseModel, Field, computed_field
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse, urlunparse
import hashlib

class ScrapingPlan(BaseModel):
    # Identity
    name: Optional[str] = None
    version: str = "1.0"
    tags: List[str] = []

    # Target
    url: str
    domain: str = ""
    objective: str

    # Execution contract
    steps: List[Dict[str, Any]]
    selectors: Optional[List[Dict[str, Any]]] = None
    browser_config: Optional[Dict[str, Any]] = None

    # Crawl hints
    follow_selector: Optional[str] = None
    follow_pattern: Optional[str] = None
    max_depth: Optional[int] = None

    # Metadata
    created_at: datetime
    updated_at: Optional[datetime] = None
    source: str = "llm"
    fingerprint: str = ""

    @computed_field
    @property
    def normalized_url(self) -> str:
        """Strip query params and fragments for stable fingerprinting."""
        parsed = urlparse(self.url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

    def model_post_init(self, __context):
        """Auto-populate domain, name, and fingerprint."""
        ...
```

### Key Constraints
- Use Pydantic v2 `BaseModel` with `computed_field`
- Fingerprint: first 16 chars of SHA-256 hex digest of `normalized_url`
- `domain`: extracted via `urlparse(url).netloc`
- `name`: if not provided, sanitize domain (replace dots with hyphens)
- `created_at` should default to `datetime.now(timezone.utc)` if not provided via `default_factory`
- Document the 16-char fingerprint prefix collision limitation

### References in Codebase
- `parrot/tools/scraping/models.py` — existing Pydantic models in the scraping module
- `parrot/tools/scraping/options.py` — existing options/config patterns

---

## Acceptance Criteria

- [ ] `ScrapingPlan` model validates with all required fields
- [ ] `domain` auto-populated from URL
- [ ] `name` auto-populated from domain when not provided
- [ ] `fingerprint` auto-generated as 16-char SHA-256 prefix of normalized URL
- [ ] `normalized_url` strips query params and fragments
- [ ] Same URL with different query params produces same fingerprint
- [ ] JSON round-trip: `model_dump_json()` → `model_validate_json()` preserves all fields
- [ ] `PlanRegistryEntry` model validates correctly
- [ ] All tests pass: `pytest tests/tools/scraping/test_plan_model.py -v`
- [ ] Import works: `from parrot.tools.scraping.plan import ScrapingPlan, PlanRegistryEntry`

---

## Test Specification

```python
# tests/tools/scraping/test_plan_model.py
import pytest
from datetime import datetime, timezone
from parrot.tools.scraping.plan import ScrapingPlan, PlanRegistryEntry


@pytest.fixture
def sample_plan():
    return ScrapingPlan(
        url="https://example.com/products",
        objective="Extract product listings",
        steps=[
            {"action": "navigate", "url": "https://example.com/products"},
            {"action": "wait", "condition": ".product-list", "condition_type": "selector"},
            {"action": "get_html", "selector": ".product-list"},
        ],
        tags=["ecommerce", "products"],
    )


class TestScrapingPlan:
    def test_auto_populate_domain(self, sample_plan):
        """Domain auto-derived from URL."""
        assert sample_plan.domain == "example.com"

    def test_auto_populate_name(self, sample_plan):
        """Name defaults to sanitized domain when not provided."""
        assert sample_plan.name is not None
        assert "example" in sample_plan.name

    def test_fingerprint_stability(self):
        """Same URL with different query params produces same fingerprint."""
        plan1 = ScrapingPlan(
            url="https://example.com/page?utm_source=google",
            objective="test", steps=[],
        )
        plan2 = ScrapingPlan(
            url="https://example.com/page?ref=twitter&v=2",
            objective="test", steps=[],
        )
        assert plan1.fingerprint == plan2.fingerprint
        assert len(plan1.fingerprint) == 16

    def test_normalized_url_strips_params(self, sample_plan):
        """Normalized URL has no query params or fragments."""
        plan = ScrapingPlan(
            url="https://example.com/page?q=1#section",
            objective="test", steps=[],
        )
        assert plan.normalized_url == "https://example.com/page"

    def test_json_roundtrip(self, sample_plan):
        """model_dump_json → model_validate_json preserves all fields."""
        json_str = sample_plan.model_dump_json()
        restored = ScrapingPlan.model_validate_json(json_str)
        assert restored.url == sample_plan.url
        assert restored.fingerprint == sample_plan.fingerprint
        assert restored.domain == sample_plan.domain
        assert restored.steps == sample_plan.steps


class TestPlanRegistryEntry:
    def test_entry_creation(self):
        entry = PlanRegistryEntry(
            name="example-com",
            plan_version="1.0",
            url="https://example.com/products",
            domain="example.com",
            path="example.com/example-com_v1.0_abcdef0123456789.json",
            created_at=datetime.now(timezone.utc),
        )
        assert entry.use_count == 0
        assert entry.last_used_at is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scrapingplan-planregistry.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-038-scraping-plan-model.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Implemented `ScrapingPlan` and `PlanRegistryEntry` Pydantic v2 models in
`parrot/tools/scraping/plan.py`. Added helper functions `_normalize_url`, `_compute_fingerprint`,
and `_sanitize_domain`. All 16 unit tests pass covering: auto-population of domain/name/fingerprint,
fingerprint stability across query params, URL normalization, JSON round-trip, and PlanRegistryEntry
creation/serialization. Added `fingerprint` field to `PlanRegistryEntry` (not explicitly in spec
but needed for registry lookup operations).

**Deviations from spec**: Added `fingerprint` field to `PlanRegistryEntry` for registry lookup support.
