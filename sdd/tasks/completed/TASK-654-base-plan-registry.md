# TASK-654: BasePlanRegistry Generic Extraction

**Feature**: intelligent-scraping-pipeline
**Spec**: `sdd/specs/intelligent-scraping-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-653
**Assigned-to**: unassigned

---

## Context

> Implements Module 2 from the spec. The existing `PlanRegistry` is tightly coupled to
> `ScrapingPlan`. This task extracts a generic `BasePlanRegistry[T]` that both the existing
> `PlanRegistry` and the new `ExtractionPlanRegistry` can inherit from. This avoids code
> duplication while supporting different plan types with the same disk-backed, 3-tier
> lookup architecture.

---

## Scope

- Extract a generic `BasePlanRegistry[T]` from the existing `PlanRegistry`
- Parameterize on plan type `T` (must be a Pydantic BaseModel with `url`, `fingerprint`, `name` fields)
- Move shared logic into `BasePlanRegistry[T]`: `load()`, `lookup()` (3-tier), `register()`, `touch()`, `remove()`, `list_all()`, `_save_index()`
- Add `invalidate()` method for cache lifecycle management
- Refactor existing `PlanRegistry` to inherit from `BasePlanRegistry[ScrapingPlan]`
- Ensure existing `PlanRegistry` behavior is unchanged (backwards compatible)
- Write unit tests for the generic base

**NOT in scope**:
- ExtractionPlanRegistry (TASK-655)
- Data models (TASK-653)
- ScrapingAgent changes (TASK-659)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/base_registry.py` | CREATE | Generic BasePlanRegistry[T] |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/registry.py` | MODIFY | Refactor PlanRegistry to inherit from BasePlanRegistry |
| `packages/ai-parrot-tools/tests/scraping/test_base_registry.py` | CREATE | Unit tests for generic base |
| `packages/ai-parrot-tools/tests/scraping/test_registry.py` | MODIFY | Verify PlanRegistry still passes existing tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.plan import ScrapingPlan, PlanRegistryEntry  # plan.py:59, :112
from parrot_tools.scraping.plan import _normalize_url, _compute_fingerprint  # plan.py:18, :31
from parrot_tools.scraping.registry import PlanRegistry  # registry.py:23
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/registry.py
class PlanRegistry:  # line 23
    def __init__(self, plans_dir: Optional[Path] = None) -> None:  # line 31
        self.plans_dir = plans_dir or Path("scraping_plans")
        self._index_path = self.plans_dir / "registry.json"
        self._entries: dict[str, PlanRegistryEntry] = {}  # keyed by fingerprint
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    async def load(self) -> None:  # line 38
    def lookup(self, url: str) -> Optional[PlanRegistryEntry]:  # line 60
        # 3-tier: exact fingerprint -> path-prefix -> domain-only
    def get_by_name(self, name: str) -> Optional[PlanRegistryEntry]:  # line 102
    def list_all(self) -> List[PlanRegistryEntry]:  # line 116
    async def register(self, plan: ScrapingPlan, relative_path: str) -> None:  # line 124
    async def touch(self, fingerprint: str) -> None:  # line 146
    async def remove(self, name: str) -> bool:  # line 161
    async def _save_index(self) -> None:  # line 183

# packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py
class PlanRegistryEntry(BaseModel):  # line 112
    name: str              # line 115
    plan_version: str      # line 116
    url: str               # line 117
    domain: str            # line 118
    fingerprint: str = ""  # line 119
    path: str              # line 120
    created_at: datetime   # line 121
    last_used_at: Optional[datetime] = None  # line 122
    use_count: int = 0     # line 123
    tags: List[str] = Field(default_factory=list)  # line 124
```

### Does NOT Exist
- ~~`BasePlanRegistry`~~ -- does not exist yet; THIS TASK creates it
- ~~`PlanRegistry.invalidate()`~~ -- PlanRegistry has `remove()` but no `invalidate()`
- ~~`ExtractionPlanRegistry`~~ -- does not exist yet; created in TASK-655

---

## Implementation Notes

### Pattern to Follow
```python
# Generic base with TypeVar
from typing import TypeVar, Generic

T = TypeVar("T", bound=BaseModel)

class BasePlanRegistry(Generic[T]):
    """Generic disk-backed plan registry with 3-tier URL lookup."""

    # Subclasses define:
    #   _entry_type: Type for registry entries
    #   _plan_type: Type for plan objects
    #   _index_filename: str for the JSON index file

    def __init__(self, plans_dir: Optional[Path] = None, index_filename: str = "registry.json") -> None:
        ...

# Then refactor PlanRegistry:
class PlanRegistry(BasePlanRegistry[ScrapingPlan]):
    def __init__(self, plans_dir: Optional[Path] = None) -> None:
        super().__init__(plans_dir=plans_dir, index_filename="registry.json")
```

### Key Constraints
- `PlanRegistry` must remain backwards compatible -- same constructor signature, same method signatures
- Existing tests for `PlanRegistry` must continue to pass without modification
- `BasePlanRegistry` must use `asyncio.Lock` for concurrent writes
- Use `aiofiles` for async file I/O (already used by PlanRegistry)
- The `invalidate()` method should: mark entry as stale, optionally remove from registry
- `lookup()` 3-tier logic must be in the base class (shared by all registries)

---

## Acceptance Criteria

- [ ] `BasePlanRegistry[T]` generic class created with all shared methods
- [ ] `PlanRegistry` refactored to inherit from `BasePlanRegistry[ScrapingPlan]`
- [ ] Existing `PlanRegistry` tests pass without modification
- [ ] `invalidate()` method implemented in base class
- [ ] 3-tier lookup (exact, prefix, domain) works in base class
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_base_registry.py -v`
- [ ] No breaking changes to PlanRegistry public API

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/scraping/test_base_registry.py
import pytest
from parrot_tools.scraping.base_registry import BasePlanRegistry
from parrot_tools.scraping.registry import PlanRegistry


class TestBasePlanRegistry:
    @pytest.fixture
    def registry(self, tmp_path):
        reg = PlanRegistry(plans_dir=tmp_path)
        return reg

    async def test_lookup_exact_match(self, registry):
        """Exact fingerprint match returns correct entry."""
        ...

    async def test_lookup_prefix_match(self, registry):
        """Path-prefix match works for URL variants."""
        ...

    async def test_lookup_domain_match(self, registry):
        """Domain-only fallback works."""
        ...

    async def test_register_and_lookup(self, registry):
        """Register a plan and look it up."""
        ...

    async def test_invalidate(self, registry):
        """Invalidate removes entry from registry."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/intelligent-scraping-pipeline.spec.md` for full context
2. **Check dependencies** -- verify TASK-653 is completed
3. **Read `registry.py` in full** before refactoring -- understand every method
4. **Verify the Codebase Contract** -- confirm PlanRegistry signatures match
5. **Run existing registry tests FIRST** to establish baseline
6. **Refactor carefully** -- extract base, then verify existing tests still pass
7. **Update status** in `tasks/.index.json` -> `"in-progress"`
8. **Implement** following the scope
9. **Move this file** to `tasks/completed/TASK-654-base-plan-registry.md`
10. **Update index** -> `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
