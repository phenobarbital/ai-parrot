# TASK-049: DriverConfig, PlanSummary & PlanSaveResult Models

**Feature**: FEAT-014 — WebScrapingToolkit
**Spec**: `sdd/specs/scraping-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> This task implements Module 1 from the spec: the Pydantic data models used
> throughout the `WebScrapingToolkit`. These are value objects that carry
> configuration and result data between toolkit methods.

---

## Scope

- Implement `DriverConfig` Pydantic model with all browser configuration fields and a `merge()` method
- Implement `PlanSummary` Pydantic model (slim projection of `PlanRegistryEntry`)
- Implement `PlanSaveResult` Pydantic model (result of plan save operations)
- Write unit tests for all three models

**NOT in scope**: Driver context manager (TASK-050), WebScrapingToolkit class (TASK-053)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/toolkit_models.py` | CREATE | DriverConfig, PlanSummary, PlanSaveResult |
| `tests/tools/scraping/test_toolkit_models.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
from typing import Any, Dict, List, Literal, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class DriverConfig(BaseModel):
    """Frozen browser configuration passed to driver factory."""
    driver_type: Literal["selenium", "playwright"] = "selenium"
    browser: Literal["chrome", "firefox", "edge", "safari",
                     "undetected", "webkit"] = "chrome"
    headless: bool = True
    mobile: bool = False
    mobile_device: Optional[str] = None
    auto_install: bool = True
    default_timeout: int = 10
    retry_attempts: int = 3
    delay_between_actions: float = 1.0
    overlay_housekeeping: bool = True
    disable_images: bool = False
    custom_user_agent: Optional[str] = None

    def merge(self, overrides: Optional[Dict[str, Any]] = None) -> "DriverConfig":
        """Return a new DriverConfig with overrides applied.

        Does NOT mutate the original instance.
        """
        if not overrides:
            return self.model_copy()
        data = self.model_dump()
        data.update(overrides)
        return DriverConfig.model_validate(data)


class PlanSummary(BaseModel):
    """Slim projection of PlanRegistryEntry for plan_list results."""
    name: str
    version: str
    url: str
    domain: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    use_count: int = 0
    tags: List[str] = Field(default_factory=list)

    @classmethod
    def from_registry_entry(cls, entry) -> "PlanSummary":
        """Create a PlanSummary from a PlanRegistryEntry."""
        return cls(
            name=entry.name,
            version=entry.plan_version,
            url=entry.url,
            domain=entry.domain,
            created_at=entry.created_at,
            last_used_at=entry.last_used_at,
            use_count=entry.use_count,
            tags=entry.tags,
        )


class PlanSaveResult(BaseModel):
    """Result of a plan_save operation."""
    success: bool
    path: str
    name: str
    version: str
    registered: bool
    message: str
```

### Key Constraints
- Use Pydantic v2 `BaseModel`
- `DriverConfig.merge()` must return a new instance, never mutate
- `PlanSummary.from_registry_entry()` factory method for convenient conversion
- All fields must have Google-style docstrings on the class

### References in Codebase
- `parrot/tools/scraping/plan.py` — existing Pydantic model patterns
- `parrot/tools/scraping/driver.py` — existing `SeleniumSetup` constructor params to match

---

## Acceptance Criteria

- [ ] `DriverConfig` has all fields matching spec §2 Data Models
- [ ] `DriverConfig.merge()` returns new instance with overrides, doesn't mutate original
- [ ] `PlanSummary.from_registry_entry()` correctly converts a `PlanRegistryEntry`
- [ ] `PlanSaveResult` has all required fields
- [ ] All tests pass: `pytest tests/tools/scraping/test_toolkit_models.py -v`
- [ ] No linting errors: `ruff check parrot/tools/scraping/toolkit_models.py`
- [ ] Import works: `from parrot.tools.scraping.toolkit_models import DriverConfig, PlanSummary, PlanSaveResult`

---

## Test Specification

```python
# tests/tools/scraping/test_toolkit_models.py
import pytest
from datetime import datetime, timezone
from parrot.tools.scraping.toolkit_models import DriverConfig, PlanSummary, PlanSaveResult
from parrot.tools.scraping.plan import PlanRegistryEntry


class TestDriverConfig:
    def test_defaults(self):
        config = DriverConfig()
        assert config.driver_type == "selenium"
        assert config.browser == "chrome"
        assert config.headless is True

    def test_merge_applies_overrides(self):
        config = DriverConfig()
        merged = config.merge({"headless": False, "browser": "firefox"})
        assert merged.headless is False
        assert merged.browser == "firefox"
        # Original unchanged
        assert config.headless is True

    def test_merge_none_returns_copy(self):
        config = DriverConfig(browser="edge")
        merged = config.merge(None)
        assert merged.browser == "edge"
        assert merged is not config


class TestPlanSummary:
    def test_from_registry_entry(self):
        entry = PlanRegistryEntry(
            name="example-com",
            plan_version="1.0",
            url="https://example.com",
            domain="example.com",
            fingerprint="abc123",
            path="example.com/plan.json",
            created_at=datetime.now(timezone.utc),
        )
        summary = PlanSummary.from_registry_entry(entry)
        assert summary.name == "example-com"
        assert summary.domain == "example.com"


class TestPlanSaveResult:
    def test_creation(self):
        result = PlanSaveResult(
            success=True, path="plans/x.json", name="example",
            version="1.0", registered=True, message="Saved"
        )
        assert result.success is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scraping-toolkit.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-049-toolkit-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Implemented all three Pydantic models in `parrot/tools/scraping/toolkit_models.py`: `DriverConfig` (12 fields + `merge()` method that returns a new instance), `PlanSummary` (with `from_registry_entry()` factory method), and `PlanSaveResult`. 12 unit tests pass covering defaults, merge behavior, factory methods, JSON roundtrip, and edge cases.

**Deviations from spec**: none
