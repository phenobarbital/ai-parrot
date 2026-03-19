# TASK-042: Integration Tests for ScrapingPlan & PlanRegistry

**Feature**: FEAT-012 — ScrapingPlan & PlanRegistry
**Spec**: `sdd/specs/scrapingplan-planregistry.spec.md`
**Status**: in-progress
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-038, TASK-039, TASK-040, TASK-041
**Assigned-to**: claude-session

---

## Context

> This task adds end-to-end integration tests that exercise the full plan lifecycle
> across all modules. It validates that the components work together correctly:
> model creation → file I/O → registry indexing → lookup → reload.

---

## Scope

- Write integration tests covering the full lifecycle from the spec's Integration Tests table
- Test `test_full_plan_lifecycle`: Create → save → register → lookup → load → verify
- Test `test_registry_persistence`: Save registry, new instance, load, verify entries survive
- Test multi-plan scenarios (multiple domains, multiple versions)
- Verify all public exports from `parrot/tools/scraping/__init__.py`

**NOT in scope**: Implementation of any component (all done in TASK-038 through TASK-041)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/tools/scraping/test_integration.py` | CREATE | End-to-end integration tests |
| `tests/tools/scraping/__init__.py` | CREATE | Test package init (empty) |

---

## Implementation Notes

### Key Constraints
- Use `tmp_path` fixture for all disk operations (no side effects)
- Use `pytest-asyncio` for async test functions
- Tests must be self-contained — no external services
- Verify the full chain: model → save → register → lookup → load → verify equality

### References in Codebase
- `tests/tools/` — existing test patterns
- Spec Section 4 (Test Specification) — integration test requirements

---

## Acceptance Criteria

- [ ] Full plan lifecycle test passes
- [ ] Registry persistence across instances test passes
- [ ] Multi-plan / multi-domain scenario test passes
- [ ] Public exports verified: `from parrot.tools.scraping import ScrapingPlan, PlanRegistry`
- [ ] All tests pass: `pytest tests/tools/scraping/test_integration.py -v`

---

## Test Specification

```python
# tests/tools/scraping/test_integration.py
import pytest
from pathlib import Path
from parrot.tools.scraping.plan import ScrapingPlan, PlanRegistryEntry
from parrot.tools.scraping.registry import PlanRegistry
from parrot.tools.scraping.plan_io import save_plan_to_disk, load_plan_from_disk


@pytest.fixture
def tmp_plans_dir(tmp_path):
    return tmp_path / "plans"


class TestScrapingPlanIntegration:
    @pytest.mark.asyncio
    async def test_full_plan_lifecycle(self, tmp_plans_dir):
        """Create plan → save → register → lookup → load → verify."""
        plan = ScrapingPlan(
            url="https://shop.example.com/catalog/electronics",
            objective="Extract electronics catalog",
            steps=[
                {"action": "navigate", "url": "https://shop.example.com/catalog/electronics"},
                {"action": "wait", "condition": ".product-grid", "condition_type": "selector"},
                {"action": "get_html", "selector": ".product-grid"},
            ],
            tags=["ecommerce", "electronics"],
        )

        # Save to disk
        saved_path = await save_plan_to_disk(plan, tmp_plans_dir)
        assert saved_path.exists()

        # Register
        registry = PlanRegistry(plans_dir=tmp_plans_dir)
        relative = saved_path.relative_to(tmp_plans_dir)
        await registry.register(plan, str(relative))

        # Lookup (exact)
        entry = registry.lookup("https://shop.example.com/catalog/electronics")
        assert entry is not None
        assert entry.domain == "shop.example.com"

        # Load from disk
        loaded = await load_plan_from_disk(tmp_plans_dir / entry.path)
        assert loaded.url == plan.url
        assert loaded.fingerprint == plan.fingerprint
        assert loaded.steps == plan.steps

    @pytest.mark.asyncio
    async def test_registry_persistence(self, tmp_plans_dir):
        """Save registry, create new instance, load, verify entries survive."""
        plan = ScrapingPlan(
            url="https://news.example.com/articles",
            objective="Scrape articles",
            steps=[{"action": "navigate", "url": "https://news.example.com/articles"}],
        )
        saved_path = await save_plan_to_disk(plan, tmp_plans_dir)

        # First registry instance
        reg1 = PlanRegistry(plans_dir=tmp_plans_dir)
        await reg1.register(plan, str(saved_path.relative_to(tmp_plans_dir)))
        assert len(reg1.list_all()) == 1

        # Second instance — load from disk
        reg2 = PlanRegistry(plans_dir=tmp_plans_dir)
        await reg2.load()
        assert len(reg2.list_all()) == 1
        entry = reg2.lookup("https://news.example.com/articles")
        assert entry is not None

    @pytest.mark.asyncio
    async def test_multi_domain_plans(self, tmp_plans_dir):
        """Multiple plans across different domains coexist."""
        plans = [
            ScrapingPlan(
                url=f"https://site{i}.com/page",
                objective=f"Scrape site{i}",
                steps=[{"action": "navigate", "url": f"https://site{i}.com/page"}],
            )
            for i in range(3)
        ]

        registry = PlanRegistry(plans_dir=tmp_plans_dir)
        for plan in plans:
            path = await save_plan_to_disk(plan, tmp_plans_dir)
            await registry.register(plan, str(path.relative_to(tmp_plans_dir)))

        assert len(registry.list_all()) == 3
        for i in range(3):
            entry = registry.lookup(f"https://site{i}.com/page")
            assert entry is not None
            assert entry.domain == f"site{i}.com"

    def test_public_exports(self):
        """Verify public exports from __init__.py."""
        from parrot.tools.scraping import ScrapingPlan, PlanRegistry
        assert ScrapingPlan is not None
        assert PlanRegistry is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scrapingplan-planregistry.spec.md` for full context
2. **Check dependencies** — verify TASK-038 through TASK-041 are in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-042-scraping-plan-integration-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Created `tests/tools/scraping/test_integration.py` with 10 end-to-end integration
tests covering: full plan lifecycle, registry persistence across instances, multi-domain plans,
versioned plans coexistence, all three lookup tiers, touch/usage tracking with persistence,
remove then lookup, fingerprint stability with query params, and public exports verification.
Full scraping test suite: 110/110 passing.

**Deviations from spec**: Added extra tests beyond the spec's minimum (versioned plans, tiered
lookup, touch tracking, remove, fingerprint stability) for more thorough coverage.
