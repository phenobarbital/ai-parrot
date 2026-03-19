# TASK-041: WebScrapingTool Integration

**Feature**: FEAT-012 — ScrapingPlan & PlanRegistry
**Spec**: `sdd/specs/scrapingplan-planregistry.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-038, TASK-039, TASK-040
**Assigned-to**: claude-session

---

## Context

> This task implements Module 4 from the spec: wiring the `PlanRegistry` into the
> existing `WebScrapingTool` workflow. The tool should check the registry cache
> before invoking LLM inference, save new LLM-generated plans automatically (non-blocking),
> and touch the registry on cache hits.

---

## Scope

- Modify `WebScrapingTool` to initialize a `PlanRegistry` instance
- Add cache-first lookup: before LLM inference, check `registry.lookup(url)`
- On cache hit: load plan from disk via `load_plan_from_disk()`, call `registry.touch()`
- On cache miss: after LLM generates a plan, save it via `save_plan_to_disk()` and `registry.register()` (non-blocking)
- Export `ScrapingPlan` and `PlanRegistry` from `parrot/tools/scraping/__init__.py`
- No breaking changes to existing `WebScrapingTool` public API

**NOT in scope**: ScrapingPlan model (TASK-038), PlanRegistry (TASK-039), Plan I/O (TASK-040)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/tool.py` | MODIFY | Wire PlanRegistry into scraping workflow |
| `parrot/tools/scraping/__init__.py` | MODIFY | Export ScrapingPlan, PlanRegistry |
| `tests/tools/scraping/test_tool_integration.py` | CREATE | Integration tests |

---

## Implementation Notes

### Pattern to Follow
```python
# In WebScrapingTool.__init__ or setup:
from .plan import ScrapingPlan
from .registry import PlanRegistry
from .plan_io import save_plan_to_disk, load_plan_from_disk

class WebScrapingTool:
    def __init__(self, ...):
        ...
        self._plan_registry = PlanRegistry(plans_dir=self._plans_dir)

    async def _get_or_create_plan(self, url: str, objective: str) -> ScrapingPlan:
        """Cache-first plan retrieval."""
        # Tier 1-3 lookup
        entry = self._plan_registry.lookup(url)
        if entry:
            plan_path = self._plan_registry.plans_dir / entry.path
            plan = await load_plan_from_disk(plan_path)
            await self._plan_registry.touch(plan.fingerprint)
            self.logger.info("Cache hit for %s (tier match)", url)
            return plan

        # Cache miss — invoke LLM
        plan = await self._generate_plan_via_llm(url, objective)

        # Auto-save (non-blocking)
        asyncio.create_task(self._save_and_register(plan))
        return plan

    async def _save_and_register(self, plan: ScrapingPlan) -> None:
        """Save plan to disk and register in index (fire-and-forget)."""
        try:
            saved_path = await save_plan_to_disk(plan, self._plan_registry.plans_dir)
            relative = saved_path.relative_to(self._plan_registry.plans_dir)
            await self._plan_registry.register(plan, str(relative))
        except Exception:
            self.logger.exception("Failed to save/register plan")
```

### Key Constraints
- Auto-save every LLM-generated plan (per open question resolution: auto-save, non-blocking)
- Use `asyncio.create_task()` for non-blocking save (fire-and-forget with error logging)
- No breaking changes to `WebScrapingTool` public API
- Load registry on first use (lazy initialization)
- Plans directory should be configurable (default: `scraping_plans/` relative to working dir or a configurable path)

### References in Codebase
- `parrot/tools/scraping/tool.py` — the existing WebScrapingTool to modify
- `parrot/tools/scraping/orchestrator.py` — orchestrator patterns

---

## Acceptance Criteria

- [ ] `WebScrapingTool` checks registry before LLM inference
- [ ] Cache hits load plan from disk and call `touch()`
- [ ] Cache misses trigger LLM inference followed by auto-save (non-blocking)
- [ ] `parrot/tools/scraping/__init__.py` exports `ScrapingPlan`, `PlanRegistry`
- [ ] No breaking changes to existing `WebScrapingTool` public API
- [ ] All tests pass: `pytest tests/tools/scraping/ -v`

---

## Test Specification

```python
# tests/tools/scraping/test_tool_integration.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from parrot.tools.scraping.plan import ScrapingPlan
from parrot.tools.scraping.registry import PlanRegistry
from parrot.tools.scraping.plan_io import save_plan_to_disk, load_plan_from_disk


@pytest.fixture
def tmp_plans_dir(tmp_path):
    return tmp_path / "plans"


class TestFullPlanLifecycle:
    @pytest.mark.asyncio
    async def test_full_plan_lifecycle(self, tmp_plans_dir):
        """Create plan → save → register → lookup → load → verify."""
        # Create
        plan = ScrapingPlan(
            url="https://example.com/products",
            objective="Extract products",
            steps=[{"action": "navigate", "url": "https://example.com/products"}],
        )

        # Save
        saved_path = await save_plan_to_disk(plan, tmp_plans_dir)

        # Register
        registry = PlanRegistry(plans_dir=tmp_plans_dir)
        relative = saved_path.relative_to(tmp_plans_dir)
        await registry.register(plan, str(relative))

        # Lookup
        entry = registry.lookup("https://example.com/products")
        assert entry is not None

        # Load
        loaded = await load_plan_from_disk(tmp_plans_dir / entry.path)
        assert loaded.url == plan.url
        assert loaded.fingerprint == plan.fingerprint

    @pytest.mark.asyncio
    async def test_registry_persistence_across_instances(self, tmp_plans_dir):
        """Registry survives across new PlanRegistry instances."""
        plan = ScrapingPlan(
            url="https://test.com/page",
            objective="Test",
            steps=[{"action": "navigate", "url": "https://test.com/page"}],
        )
        saved_path = await save_plan_to_disk(plan, tmp_plans_dir)

        reg1 = PlanRegistry(plans_dir=tmp_plans_dir)
        await reg1.register(plan, str(saved_path.relative_to(tmp_plans_dir)))

        reg2 = PlanRegistry(plans_dir=tmp_plans_dir)
        await reg2.load()
        assert len(reg2.list_all()) == 1
        assert reg2.lookup("https://test.com/page") is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scrapingplan-planregistry.spec.md` for full context
2. **Check dependencies** — verify TASK-038, TASK-039, TASK-040 are in `sdd/tasks/completed/`
3. **Read** `parrot/tools/scraping/tool.py` to understand current WebScrapingTool implementation
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-041-webscraping-tool-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Wired PlanRegistry into WebScrapingTool with three integration points:
1. `__init__`: Added `plans_dir` parameter and `PlanRegistry` initialization with lazy loading
2. `_execute` (scrape path): Cache-first lookup via `_lookup_cached_plan()` before driver init;
   auto-save via `_save_and_register_plan()` after successful scrape (non-blocking fire-and-forget)
3. `_execute` (define_plan path): Auto-save plan when base_url is provided (non-blocking)
Added `_ensure_registry_loaded`, `_lookup_cached_plan`, `_save_and_register_plan` helper methods.
Updated `__init__.py` to export `ScrapingPlan` and `PlanRegistry`.
Created 11 integration tests — all 100 tests in `tests/tools/scraping/` pass.
No breaking changes to existing WebScrapingTool public API.

**Deviations from spec**: Added `used_cached_plan` field to scrape result metadata for observability.
