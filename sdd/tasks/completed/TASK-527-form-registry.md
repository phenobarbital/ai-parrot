# TASK-527: Form Registry

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-518
**Assigned-to**: unassigned

---

## Context

Implements Module 10 from the spec. Migrates the existing `FormRegistry` from `parrot/integrations/dialogs/registry.py` to `parrot/forms/registry.py`. Adds support for optional `FormStorage` backend for database persistence. The registry is the central lookup point for all registered forms.

---

## Scope

- Implement `parrot/forms/registry.py` with `FormRegistry` and `FormStorage` ABC
- Migrate logic from `parrot/integrations/dialogs/registry.py`: thread-safe registration, lookup by form_id, trigger phrase matching, directory loading
- Add `FormStorage` abstract base class with `save()`, `load()`, `delete()`, `list_forms()` methods
- Add `persist` parameter to `register()` — when True and storage is configured, saves to backend
- Add `load_from_storage()` to load all persisted forms on startup
- Add async callback support for register/unregister events
- Write unit tests

**NOT in scope**: PostgreSQL storage implementation (TASK-529), form cache (TASK-528).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/registry.py` | CREATE | FormRegistry, FormStorage ABC |
| `packages/ai-parrot/src/parrot/forms/__init__.py` | MODIFY | Export FormRegistry, FormStorage |
| `packages/ai-parrot/tests/unit/forms/test_registry.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

Migrate from `parrot/integrations/dialogs/registry.py` which has `FormRegistry` with `register()`, `unregister()`, `get()`, `get_by_trigger()`, `find_by_trigger()`, `list_forms()`, `load_from_directory()`.

```python
class FormStorage(ABC):
    @abstractmethod
    async def save(self, form: FormSchema, style: StyleSchema | None = None) -> str: ...
    @abstractmethod
    async def load(self, form_id: str, version: str | None = None) -> FormSchema | None: ...
    @abstractmethod
    async def delete(self, form_id: str) -> bool: ...
    @abstractmethod
    async def list_forms(self) -> list[dict[str, str]]: ...

class FormRegistry:
    def __init__(self, storage: FormStorage | None = None): ...
    async def register(self, form: FormSchema, *, persist: bool = False) -> None: ...
    async def get(self, form_id: str) -> FormSchema | None: ...
    async def unregister(self, form_id: str) -> None: ...
    async def load_from_directory(self, path: str | Path) -> int: ...
    async def load_from_storage(self) -> int: ...
```

### Key Constraints
- Thread-safe: use `asyncio.Lock` for concurrent access
- Directory loading uses `YamlExtractor` — but since this task shouldn't depend on TASK-522, make it optional (if YamlExtractor not available, skip YAML loading with warning)
- `persist=True` without configured storage should log warning, not raise
- Trigger phrase matching should be case-insensitive substring matching

### References in Codebase
- `parrot/integrations/dialogs/registry.py` — existing FormRegistry implementation

---

## Acceptance Criteria

- [ ] Register, get, unregister work correctly
- [ ] Thread-safe with asyncio.Lock
- [ ] Trigger phrase matching works (case-insensitive)
- [ ] `persist=True` delegates to FormStorage when configured
- [ ] `load_from_storage()` loads all persisted forms into memory
- [ ] `persist=True` without storage logs warning (no crash)
- [ ] Import works: `from parrot.forms import FormRegistry, FormStorage`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/forms/test_registry.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_registry.py
import pytest
from parrot.forms import FormSchema, FormField, FormSection, FieldType
from parrot.forms.registry import FormRegistry


@pytest.fixture
def registry():
    return FormRegistry()


@pytest.fixture
def sample_form():
    return FormSchema(
        form_id="test-form", title="Test",
        sections=[FormSection(section_id="s", fields=[
            FormField(field_id="f", field_type=FieldType.TEXT, label="F")
        ])],
    )


class TestFormRegistry:
    async def test_register_and_get(self, registry, sample_form):
        await registry.register(sample_form)
        result = await registry.get("test-form")
        assert result is not None
        assert result.form_id == "test-form"

    async def test_unregister(self, registry, sample_form):
        await registry.register(sample_form)
        await registry.unregister("test-form")
        result = await registry.get("test-form")
        assert result is None

    async def test_get_nonexistent(self, registry):
        result = await registry.get("nonexistent")
        assert result is None

    async def test_persist_without_storage_warns(self, registry, sample_form, caplog):
        await registry.register(sample_form, persist=True)
        # Should still register in-memory, but log a warning
        result = await registry.get("test-form")
        assert result is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-518 is in `tasks/completed/`
3. **Read** `parrot/integrations/dialogs/registry.py` for existing logic to migrate
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-527-form-registry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: FormStorage ABC with save/load/delete/list_forms. FormRegistry with asyncio.Lock, register/unregister/get/contains/clear/list_forms/list_form_ids/get_by_trigger/find_by_trigger/load_from_directory/load_from_storage. persist=True delegates to storage or logs warning. on_register/on_unregister async callbacks. YamlExtractor used optionally in load_from_directory(). 18 tests pass.

**Deviations from spec**: none
