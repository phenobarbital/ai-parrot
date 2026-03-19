# TASK-054: Package Init & Deprecation

**Feature**: FEAT-014 — WebScrapingToolkit
**Spec**: `sdd/specs/scraping-toolkit.spec.md`
**Status**: in-progress
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-053
**Assigned-to**: claude-session

---

## Context

> This task implements Module 6 from the spec: updating package exports and adding
> a deprecation warning to the legacy `WebScrapingTool`.

---

## Scope

- Update `parrot/tools/scraping/__init__.py` to export `WebScrapingToolkit` and new models
- Add `DeprecationWarning` to `WebScrapingTool.__init__()` in `tool.py`
- Ensure backward compatibility — existing `WebScrapingTool` imports still work
- Write test for deprecation warning

**NOT in scope**: Any changes to WebScrapingTool behavior (only add warning)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/__init__.py` | MODIFY | Add new exports |
| `parrot/tools/scraping/tool.py` | MODIFY | Add DeprecationWarning to WebScrapingTool |
| `tests/tools/scraping/test_deprecation.py` | CREATE | Test deprecation warning |

---

## Implementation Notes

### Changes to `__init__.py`
```python
from .tool import WebScrapingTool, WebScrapingToolArgs, ScrapingResult
from .toolkit import WebScrapingToolkit
from .toolkit_models import DriverConfig, PlanSummary, PlanSaveResult
from .plan import ScrapingPlan
from .registry import PlanRegistry

__all__ = (
    "WebScrapingTool",
    "WebScrapingToolArgs",
    "ScrapingResult",
    "WebScrapingToolkit",
    "DriverConfig",
    "PlanSummary",
    "PlanSaveResult",
    "ScrapingPlan",
    "PlanRegistry",
)
```

### Changes to `tool.py`
```python
import warnings

class WebScrapingTool(AbstractTool):
    def __init__(self, *args, **kwargs):
        warnings.warn(
            "WebScrapingTool is deprecated. Use WebScrapingToolkit instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)
```

### Key Constraints
- Do NOT change any `WebScrapingTool` behavior — only add the warning
- Existing code that imports `WebScrapingTool` must continue to work
- New imports must also work: `from parrot.tools.scraping import WebScrapingToolkit`

---

## Acceptance Criteria

- [ ] `from parrot.tools.scraping import WebScrapingToolkit` works
- [ ] `from parrot.tools.scraping import WebScrapingTool` still works (backward compat)
- [ ] `WebScrapingTool()` emits `DeprecationWarning`
- [ ] All new models are exported from the package
- [ ] All tests pass: `pytest tests/tools/scraping/test_deprecation.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/tools/scraping/test_deprecation.py
import pytest
import warnings


class TestDeprecation:
    def test_webscraping_tool_emits_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from parrot.tools.scraping.tool import WebScrapingTool
            # Instantiation triggers warning
            # (may need to mock dependencies)
            assert any(issubclass(warning.category, DeprecationWarning) for warning in w)

    def test_toolkit_importable(self):
        from parrot.tools.scraping import WebScrapingToolkit
        assert WebScrapingToolkit is not None

    def test_all_exports(self):
        from parrot.tools.scraping import (
            WebScrapingToolkit, DriverConfig, PlanSummary,
            PlanSaveResult, ScrapingPlan, PlanRegistry,
        )
```

---

## Agent Instructions

When you pick up this task:

1. **Read** current `parrot/tools/scraping/__init__.py` and `tool.py`
2. **Check dependencies** — verify TASK-053 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** the changes above
5. **Verify** all imports work and deprecation warning fires
6. **Move this file** to `sdd/tasks/completed/TASK-054-package-init-deprecation.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Updated `__init__.py` with new exports (WebScrapingToolkit, DriverConfig, PlanSummary, PlanSaveResult, ScrapingPlan, PlanRegistry, CrawlEngine, and driver abstraction types). Added `import warnings` and DeprecationWarning to `WebScrapingTool.__init__()` in `tool.py`. Created 6 tests covering deprecation warning emission, import compatibility, and export completeness. All tests pass, lint clean.

**Deviations from spec**: `__init__.py` exports additional types beyond the spec (CrawlEngine, CrawlResult, CrawlNode, crawl strategies, LinkDiscoverer, normalize_url, DriverFactory, AbstractDriver, PlaywrightConfig, PlaywrightDriver, SeleniumDriver) — these were already present from prior tasks and retained for completeness.
