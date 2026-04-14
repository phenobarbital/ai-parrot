# TASK-655: ExtractionPlanRegistry

**Feature**: intelligent-scraping-pipeline
**Spec**: `sdd/specs/intelligent-scraping-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-653, TASK-654
**Assigned-to**: unassigned

---

## Context

> Implements Module 3 from the spec. Creates a disk-backed registry for ExtractionPlans
> using `BasePlanRegistry[ExtractionPlan]` from TASK-654. Adds extraction-specific cache
> lifecycle: success/failure counting, invalidation after 3 consecutive failures,
> and pre-built plan loading from a well-known directory.

---

## Scope

- Implement `ExtractionPlanRegistry` inheriting from `BasePlanRegistry[ExtractionPlan]`
- Add extraction-specific cache lifecycle:
  - `record_success(fingerprint)`: increment `success_count`, reset `failure_count`, update `last_used_at`
  - `record_failure(fingerprint)`: increment `failure_count`; if `failure_count > 3`, call `invalidate()`
- Add pre-built plan loading: `load_prebuilt(directory)` scans a directory for JSON ExtractionPlan files and registers them with `source="developer"`
- Separate index file: `extraction_registry.json`
- Write unit tests

**NOT in scope**:
- Creating pre-built plan JSON files (TASK-658)
- ExtractionPlan model itself (TASK-653)
- BasePlanRegistry itself (TASK-654)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_registry.py` | CREATE | ExtractionPlanRegistry class |
| `packages/ai-parrot-tools/tests/scraping/test_extraction_registry.py` | CREATE | Unit tests |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/__init__.py` | MODIFY | Export new registry |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.extraction_models import ExtractionPlan  # created by TASK-653
from parrot_tools.scraping.base_registry import BasePlanRegistry  # created by TASK-654
from parrot_tools.scraping.plan import _normalize_url, _compute_fingerprint  # plan.py:18, :31
```

### Existing Signatures to Use
```python
# Created by TASK-654 — BasePlanRegistry[T]
class BasePlanRegistry(Generic[T]):
    def __init__(self, plans_dir: Optional[Path] = None, index_filename: str = "registry.json") -> None:
    async def load(self) -> None:
    def lookup(self, url: str) -> Optional[PlanRegistryEntry]:
    async def register(self, plan: T, relative_path: str) -> None:
    async def touch(self, fingerprint: str) -> None:
    async def remove(self, name: str) -> bool:
    async def invalidate(self, fingerprint: str) -> None:
    def list_all(self) -> List[PlanRegistryEntry]:

# Created by TASK-653 — ExtractionPlan
class ExtractionPlan(BaseModel):
    url: str
    domain: str = ""
    fingerprint: str = ""
    name: Optional[str] = None
    objective: str
    entities: List[EntitySpec]
    source: str = "llm"
    success_count: int = 0
    failure_count: int = 0
```

### Does NOT Exist
- ~~`ExtractionPlanRegistry`~~ -- does not exist yet; THIS TASK creates it
- ~~`BasePlanRegistry.record_success()`~~ -- not in base; THIS TASK adds it to ExtractionPlanRegistry
- ~~`BasePlanRegistry.record_failure()`~~ -- not in base; THIS TASK adds it to ExtractionPlanRegistry
- ~~`BasePlanRegistry.load_prebuilt()`~~ -- not in base; THIS TASK adds it to ExtractionPlanRegistry

---

## Implementation Notes

### Pattern to Follow
```python
class ExtractionPlanRegistry(BasePlanRegistry[ExtractionPlan]):
    """Disk-backed registry for ExtractionPlans with cache lifecycle."""

    FAILURE_THRESHOLD = 3

    def __init__(self, plans_dir: Optional[Path] = None) -> None:
        super().__init__(plans_dir=plans_dir, index_filename="extraction_registry.json")

    async def record_success(self, fingerprint: str) -> None:
        """Record successful extraction. Resets failure count."""
        ...

    async def record_failure(self, fingerprint: str) -> None:
        """Record failed extraction. Invalidates after 3 consecutive failures."""
        ...

    async def load_prebuilt(self, directory: Path) -> int:
        """Load pre-built ExtractionPlan JSON files from directory.
        Returns count of plans loaded."""
        ...
```

### Key Constraints
- Invalidation threshold: exactly 3 consecutive failures
- Pre-built plans must be loaded with `source="developer"` and high priority
- Use `aiofiles` for async file operations
- `asyncio.Lock` for concurrent write safety (inherited from base)

---

## Acceptance Criteria

- [ ] `ExtractionPlanRegistry` inherits from `BasePlanRegistry[ExtractionPlan]`
- [ ] 3-tier lookup works (exact, prefix, domain)
- [ ] `record_success()` increments count and resets failures
- [ ] `record_failure()` invalidates after 3 consecutive failures
- [ ] `load_prebuilt()` loads JSON files with `source="developer"`
- [ ] Separate `extraction_registry.json` index file
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_extraction_registry.py -v`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/scraping/test_extraction_registry.py
import pytest
from parrot_tools.scraping.extraction_registry import ExtractionPlanRegistry
from parrot_tools.scraping.extraction_models import ExtractionPlan


class TestExtractionPlanRegistry:
    @pytest.fixture
    def registry(self, tmp_path):
        return ExtractionPlanRegistry(plans_dir=tmp_path)

    async def test_register_and_lookup(self, registry):
        """Register an ExtractionPlan and look it up by URL."""
        ...

    async def test_record_success_resets_failures(self, registry):
        """Recording success resets the failure count."""
        ...

    async def test_invalidation_after_3_failures(self, registry):
        """Plan is invalidated after 3 consecutive failures."""
        ...

    async def test_load_prebuilt_plans(self, registry, tmp_path):
        """Pre-built JSON plans are loaded with source='developer'."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/intelligent-scraping-pipeline.spec.md`
2. **Check dependencies** -- verify TASK-653 and TASK-654 are completed
3. **Read TASK-654's output** -- understand BasePlanRegistry interface
4. **Verify imports** from TASK-653 and TASK-654 outputs exist
5. **Implement** following scope and contract
6. **Move to completed**, update index

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
