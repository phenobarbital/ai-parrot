# TASK-040: Plan File I/O Helpers

**Feature**: FEAT-012 — ScrapingPlan & PlanRegistry
**Spec**: `sdd/specs/scrapingplan-planregistry.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-038
**Assigned-to**: claude-session

---

## Context

> This task implements Module 3 from the spec: the `save_plan_to_disk()` and
> `load_plan_from_disk()` free functions. These handle the file layout convention
> `{plans_dir}/{domain}/{name}_v{version}_{fingerprint}.json` and ensure domain
> subdirectories are created automatically.

---

## Scope

- Implement `save_plan_to_disk(plan, plans_dir) -> Path` free function
- Implement `load_plan_from_disk(path) -> ScrapingPlan` free function
- Manage the `{plans_dir}/{domain}/{name}_v{version}_{fingerprint}.json` file layout
- Auto-create domain subdirectories when saving
- Use `aiofiles` for all file I/O
- Write unit tests for save, load, file layout, and domain directory creation

**NOT in scope**: Registry logic (TASK-039), ScrapingPlan model (TASK-038), WebScrapingTool integration (TASK-041)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/plan_io.py` | CREATE | save_plan_to_disk and load_plan_from_disk functions |
| `tests/tools/scraping/test_plan_io.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
import aiofiles
import json
import logging
from pathlib import Path

from .plan import ScrapingPlan

logger = logging.getLogger(__name__)


async def save_plan_to_disk(plan: ScrapingPlan, plans_dir: Path) -> Path:
    """Save a ScrapingPlan to disk following the naming convention.

    File layout: {plans_dir}/{domain}/{name}_v{version}_{fingerprint}.json

    Args:
        plan: The ScrapingPlan to save.
        plans_dir: Root directory for plan storage.

    Returns:
        Path to the saved file.
    """
    domain_dir = plans_dir / plan.domain
    domain_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{plan.name}_v{plan.version}_{plan.fingerprint}.json"
    file_path = domain_dir / filename

    async with aiofiles.open(file_path, "w") as f:
        await f.write(plan.model_dump_json(indent=2))

    logger.info("Saved plan to %s", file_path)
    return file_path


async def load_plan_from_disk(path: Path) -> ScrapingPlan:
    """Load a ScrapingPlan from a JSON file on disk.

    Args:
        path: Path to the plan JSON file.

    Returns:
        Deserialized ScrapingPlan instance.
    """
    async with aiofiles.open(path, "r") as f:
        content = await f.read()
    return ScrapingPlan.model_validate_json(content)
```

### Key Constraints
- Use `aiofiles` for all file I/O (matches existing usage in scraping module)
- File naming: `{name}_v{version}_{fingerprint}.json`
- Domain subdirectory: extracted from `plan.domain`
- `mkdir(parents=True, exist_ok=True)` for domain dir creation
- Return the full `Path` from `save_plan_to_disk` so callers can compute the relative path for the registry

### References in Codebase
- `parrot/tools/scraping/tool.py` — existing aiofiles usage patterns

---

## Acceptance Criteria

- [ ] `save_plan_to_disk` creates correct file at `{plans_dir}/{domain}/{name}_v{version}_{fingerprint}.json`
- [ ] `save_plan_to_disk` auto-creates domain subdirectory
- [ ] `load_plan_from_disk` deserializes plan correctly with all fields preserved
- [ ] Save then load round-trip produces equivalent plan
- [ ] All tests pass: `pytest tests/tools/scraping/test_plan_io.py -v`
- [ ] Import works: `from parrot.tools.scraping.plan_io import save_plan_to_disk, load_plan_from_disk`

---

## Test Specification

```python
# tests/tools/scraping/test_plan_io.py
import pytest
from pathlib import Path
from parrot.tools.scraping.plan import ScrapingPlan
from parrot.tools.scraping.plan_io import save_plan_to_disk, load_plan_from_disk


@pytest.fixture
def sample_plan():
    return ScrapingPlan(
        url="https://example.com/products",
        objective="Extract product listings",
        steps=[
            {"action": "navigate", "url": "https://example.com/products"},
            {"action": "get_html", "selector": ".product-list"},
        ],
        tags=["ecommerce"],
    )


@pytest.fixture
def tmp_plans_dir(tmp_path):
    return tmp_path / "plans"


class TestPlanFileIO:
    @pytest.mark.asyncio
    async def test_save_and_load_plan(self, sample_plan, tmp_plans_dir):
        """Save plan to disk, reload, verify field equality."""
        saved_path = await save_plan_to_disk(sample_plan, tmp_plans_dir)
        loaded = await load_plan_from_disk(saved_path)
        assert loaded.url == sample_plan.url
        assert loaded.fingerprint == sample_plan.fingerprint
        assert loaded.steps == sample_plan.steps
        assert loaded.domain == sample_plan.domain

    @pytest.mark.asyncio
    async def test_save_creates_domain_dir(self, sample_plan, tmp_plans_dir):
        """Domain subdirectory created automatically."""
        await save_plan_to_disk(sample_plan, tmp_plans_dir)
        domain_dir = tmp_plans_dir / sample_plan.domain
        assert domain_dir.is_dir()

    @pytest.mark.asyncio
    async def test_file_naming_convention(self, sample_plan, tmp_plans_dir):
        """File follows {name}_v{version}_{fingerprint}.json convention."""
        saved_path = await save_plan_to_disk(sample_plan, tmp_plans_dir)
        expected_name = f"{sample_plan.name}_v{sample_plan.version}_{sample_plan.fingerprint}.json"
        assert saved_path.name == expected_name
        assert saved_path.parent.name == sample_plan.domain

    @pytest.mark.asyncio
    async def test_load_nonexistent_file(self, tmp_path):
        """Loading a nonexistent file raises an error."""
        with pytest.raises((FileNotFoundError, OSError)):
            await load_plan_from_disk(tmp_path / "nonexistent.json")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scrapingplan-planregistry.spec.md` for full context
2. **Check dependencies** — verify TASK-038 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-040-plan-file-io.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Implemented `save_plan_to_disk` and `load_plan_from_disk` async functions in
`parrot/tools/scraping/plan_io.py`. Uses `aiofiles` for all file I/O, creates domain
subdirectories automatically, follows `{name}_v{version}_{fingerprint}.json` naming.
All 8 unit tests pass covering: save/load round-trip, directory creation, naming convention,
valid JSON output, nonexistent file error, multi-plan coexistence, and path correctness.

**Deviations from spec**: none
