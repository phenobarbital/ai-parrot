# TASK-039: PlanRegistry

**Feature**: FEAT-012 — ScrapingPlan & PlanRegistry
**Spec**: `sdd/specs/scrapingplan-planregistry.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-038
**Assigned-to**: claude-session

---

## Context

> This task implements Module 2 from the spec: the `PlanRegistry` class.
> The registry is an async, disk-backed index that maps URLs/domains to saved
> plan files via a `registry.json` file. It provides three-tier URL lookup
> (exact fingerprint → path-prefix → domain) and guards write mutations with
> `asyncio.Lock`.

---

## Scope

- Implement `PlanRegistry` class with all public methods from spec Section 2 (New Public Interfaces)
- Implement three-tier lookup: exact fingerprint match → path-prefix match → domain-only match
- Implement `registry.json` persistence (load/save)
- Guard all mutations with `asyncio.Lock`
- Implement `touch()` to update `last_used_at` and increment `use_count`
- Implement `remove()` to delete entries by name
- Write unit tests for all lookup tiers, registration, touch, remove, and concurrency

**NOT in scope**: File I/O helpers (TASK-040), ScrapingPlan model (TASK-038), WebScrapingTool integration (TASK-041)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/registry.py` | CREATE | PlanRegistry class |
| `tests/tools/scraping/test_plan_registry.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone

from .plan import ScrapingPlan, PlanRegistryEntry


class PlanRegistry:
    """Async, disk-backed index mapping URLs to saved plan files."""

    def __init__(self, plans_dir: Optional[Path] = None):
        self.plans_dir = plans_dir or Path("scraping_plans")
        self._index_path = self.plans_dir / "registry.json"
        self._entries: dict[str, PlanRegistryEntry] = {}  # keyed by fingerprint
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    async def load(self) -> None:
        """Load registry index from disk."""
        ...

    def lookup(self, url: str) -> Optional[PlanRegistryEntry]:
        """Three-tier lookup: exact fingerprint → path-prefix → domain."""
        ...

    def get_by_name(self, name: str) -> Optional[PlanRegistryEntry]:
        ...

    def list_all(self) -> List[PlanRegistryEntry]:
        ...

    async def register(self, plan: ScrapingPlan, relative_path: str) -> None:
        """Register a plan in the index and persist to disk."""
        ...

    async def touch(self, fingerprint: str) -> None:
        """Update last_used_at and increment use_count."""
        ...

    async def remove(self, name: str) -> bool:
        """Remove an entry by name."""
        ...

    async def _save_index(self) -> None:
        """Persist index to registry.json."""
        ...
```

### Key Constraints
- Use `asyncio.Lock` for all write operations (`register`, `touch`, `remove`)
- Use `aiofiles` for file I/O (async reads/writes of `registry.json`)
- Three-tier lookup must normalize the input URL before matching
- Path-prefix matching: check if the normalized URL starts with a registered plan's normalized URL
- Domain-only matching: match by domain extracted from URL
- `_save_index()` should be called after every mutation within the lock

### References in Codebase
- `parrot/memory/` — patterns for `asyncio.Lock` usage
- `parrot/tools/scraping/models.py` — existing model patterns

---

## Acceptance Criteria

- [ ] `PlanRegistry` loads and saves `registry.json` correctly
- [ ] Tier 1: exact fingerprint lookup works
- [ ] Tier 2: path-prefix lookup works (sub-path matches parent plan)
- [ ] Tier 3: domain-only lookup works as fallback
- [ ] `lookup()` returns `None` when no plan matches
- [ ] `register()` adds entry and persists to disk
- [ ] `touch()` updates `last_used_at` and increments `use_count`
- [ ] `remove()` deletes entry from index and persists
- [ ] Concurrent `register()` calls don't corrupt the index
- [ ] All tests pass: `pytest tests/tools/scraping/test_plan_registry.py -v`
- [ ] Import works: `from parrot.tools.scraping.registry import PlanRegistry`

---

## Test Specification

```python
# tests/tools/scraping/test_plan_registry.py
import pytest
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from parrot.tools.scraping.plan import ScrapingPlan, PlanRegistryEntry
from parrot.tools.scraping.registry import PlanRegistry


@pytest.fixture
def sample_plan():
    return ScrapingPlan(
        url="https://example.com/products",
        objective="Extract product listings",
        steps=[
            {"action": "navigate", "url": "https://example.com/products"},
            {"action": "wait", "condition": ".product-list", "condition_type": "selector"},
        ],
        tags=["ecommerce"],
    )


@pytest.fixture
def tmp_plans_dir(tmp_path):
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    return plans_dir


@pytest.fixture
def registry(tmp_plans_dir):
    return PlanRegistry(plans_dir=tmp_plans_dir)


class TestPlanRegistry:
    @pytest.mark.asyncio
    async def test_register_and_lookup(self, registry, sample_plan):
        """Register a plan then look it up by URL."""
        await registry.register(sample_plan, "example.com/plan_v1.0.json")
        entry = registry.lookup("https://example.com/products")
        assert entry is not None
        assert entry.domain == "example.com"

    @pytest.mark.asyncio
    async def test_lookup_exact_fingerprint(self, registry, sample_plan):
        """Tier 1: exact fingerprint match returns correct entry."""
        await registry.register(sample_plan, "example.com/plan.json")
        entry = registry.lookup("https://example.com/products")
        assert entry is not None

    @pytest.mark.asyncio
    async def test_lookup_path_prefix(self, registry, sample_plan):
        """Tier 2: sub-path URL matches parent plan."""
        await registry.register(sample_plan, "example.com/plan.json")
        entry = registry.lookup("https://example.com/products/shoes")
        assert entry is not None
        assert entry.domain == "example.com"

    @pytest.mark.asyncio
    async def test_lookup_domain_only(self, registry, sample_plan):
        """Tier 3: domain-only match as fallback."""
        await registry.register(sample_plan, "example.com/plan.json")
        entry = registry.lookup("https://example.com/about")
        assert entry is not None

    @pytest.mark.asyncio
    async def test_lookup_no_match(self, registry):
        """Returns None when no plan matches."""
        entry = registry.lookup("https://unknown.com/page")
        assert entry is None

    @pytest.mark.asyncio
    async def test_touch_increments_count(self, registry, sample_plan):
        """touch() updates last_used_at and use_count."""
        await registry.register(sample_plan, "example.com/plan.json")
        entry_before = registry.lookup(sample_plan.url)
        assert entry_before.use_count == 0
        await registry.touch(sample_plan.fingerprint)
        entry_after = registry.lookup(sample_plan.url)
        assert entry_after.use_count == 1
        assert entry_after.last_used_at is not None

    @pytest.mark.asyncio
    async def test_remove_by_name(self, registry, sample_plan):
        """remove() deletes entry from index."""
        await registry.register(sample_plan, "example.com/plan.json")
        removed = await registry.remove(sample_plan.name)
        assert removed is True
        assert registry.lookup(sample_plan.url) is None

    @pytest.mark.asyncio
    async def test_concurrent_register(self, registry):
        """Multiple async register() calls don't corrupt index."""
        plans = [
            ScrapingPlan(
                url=f"https://site{i}.com/page",
                objective=f"task {i}",
                steps=[{"action": "navigate", "url": f"https://site{i}.com/page"}],
            )
            for i in range(10)
        ]
        await asyncio.gather(*[
            registry.register(p, f"site{i}.com/plan.json")
            for i, p in enumerate(plans)
        ])
        assert len(registry.list_all()) == 10

    @pytest.mark.asyncio
    async def test_registry_persistence(self, tmp_plans_dir, sample_plan):
        """Save registry, new instance loads entries."""
        reg1 = PlanRegistry(plans_dir=tmp_plans_dir)
        await reg1.register(sample_plan, "example.com/plan.json")

        reg2 = PlanRegistry(plans_dir=tmp_plans_dir)
        await reg2.load()
        assert len(reg2.list_all()) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scrapingplan-planregistry.spec.md` for full context
2. **Check dependencies** — verify TASK-038 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-039-plan-registry.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Implemented `PlanRegistry` class in `parrot/tools/scraping/registry.py` with all public methods from the spec: `load()`, `lookup()` (three-tier: exact fingerprint → path-prefix → domain), `get_by_name()`, `list_all()`, `register()`, `touch()`, `remove()`, and `_save_index()`. All mutations guarded by `asyncio.Lock`. Uses `aiofiles` for async registry.json persistence. 14 unit tests pass covering all acceptance criteria including concurrent registration and persistence across instances.

**Deviations from spec**: none
