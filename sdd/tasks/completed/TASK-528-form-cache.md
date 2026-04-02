# TASK-528: Form Cache

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-518, TASK-527
**Assigned-to**: unassigned

---

## Context

Implements Module 11 from the spec. Migrates the existing `FormDefinitionCache` from `parrot/integrations/dialogs/cache.py` to `parrot/forms/cache.py`. Provides in-memory caching for `FormSchema` with TTL, optional Redis backend, and file system watching for YAML auto-invalidation.

---

## Scope

- Implement `parrot/forms/cache.py` with `FormCache`
- Migrate logic from `parrot/integrations/dialogs/cache.py`:
  - In-memory cache with TTL-based expiration
  - Optional Redis backend for distributed caching
  - File system watcher for auto-invalidation on YAML changes
  - Async-safe with `asyncio.Lock`
- Integrate with `FormRegistry` — cache sits between registry and storage
- Adapt to use `FormSchema` instead of `FormDefinition`
- Write unit tests

**NOT in scope**: Storage backend (TASK-529), registry (TASK-527 handles core registry).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/cache.py` | CREATE | FormCache implementation |
| `packages/ai-parrot/src/parrot/forms/__init__.py` | MODIFY | Export FormCache |
| `packages/ai-parrot/tests/unit/forms/test_cache.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

Migrate from `parrot/integrations/dialogs/cache.py` which has `FormDefinitionCache` with `get()`, `set()`, `invalidate()`, `invalidate_all()`, `load_directory()`, Redis helpers, and file watcher.

```python
class FormCache:
    def __init__(self, ttl_seconds: int = 3600, redis_url: str | None = None): ...
    async def get(self, form_id: str) -> FormSchema | None: ...
    async def set(self, form: FormSchema) -> None: ...
    async def invalidate(self, form_id: str) -> None: ...
    async def invalidate_all(self) -> None: ...
```

### Key Constraints
- TTL default: 1 hour (3600 seconds)
- Redis backend is optional — works purely in-memory if not configured
- File watcher uses `watchdog` or simple polling (match existing approach)
- Serialization: use `FormSchema.model_dump_json()` for Redis storage

### References in Codebase
- `parrot/integrations/dialogs/cache.py` — existing cache implementation

---

## Acceptance Criteria

- [ ] Cache get/set works with TTL expiration
- [ ] Invalidation works (single and all)
- [ ] Async-safe with lock
- [ ] Import works: `from parrot.forms import FormCache`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/forms/test_cache.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_cache.py
import pytest
from parrot.forms import FormSchema, FormField, FormSection, FieldType
from parrot.forms.cache import FormCache


@pytest.fixture
def cache():
    return FormCache(ttl_seconds=1)


@pytest.fixture
def sample_form():
    return FormSchema(
        form_id="cached-form", title="Cached",
        sections=[FormSection(section_id="s", fields=[
            FormField(field_id="f", field_type=FieldType.TEXT, label="F")
        ])],
    )


class TestFormCache:
    async def test_set_and_get(self, cache, sample_form):
        await cache.set(sample_form)
        result = await cache.get("cached-form")
        assert result is not None
        assert result.form_id == "cached-form"

    async def test_invalidate(self, cache, sample_form):
        await cache.set(sample_form)
        await cache.invalidate("cached-form")
        result = await cache.get("cached-form")
        assert result is None

    async def test_miss_returns_none(self, cache):
        result = await cache.get("nonexistent")
        assert result is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-518 and TASK-527 are in `tasks/completed/`
3. **Read** `parrot/integrations/dialogs/cache.py` for existing logic to migrate
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-528-form-cache.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: FormCache with in-memory TTL (_CacheEntry dataclass with loaded_at), asyncio.Lock, optional Redis backend via aioredis (lazy init), FormSchema.model_dump_json() serialization. get/set/invalidate/invalidate_all/size, on_invalidate callbacks. Redis helpers _redis_get/_redis_set/_redis_delete/_redis_clear. close() for cleanup. 13 tests pass.

**Deviations from spec**: none
