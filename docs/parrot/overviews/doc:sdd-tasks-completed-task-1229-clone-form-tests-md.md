---
type: Wiki Overview
title: 'TASK-1229: Unit + Integration Tests for clone_form'
id: doc:sdd-tasks-completed-task-1229-clone-form-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This task adds comprehensive test coverage for the form cloning feature:'
---

# TASK-1229: Unit + Integration Tests for clone_form

**Feature**: FEAT-183 — FormDesigner Clone Form
**Spec**: `sdd/specs/formdesigner-clone-form.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1227, TASK-1228
**Assigned-to**: unassigned

---

## Context

This task adds comprehensive test coverage for the form cloning feature:
unit tests for `FormRegistry.clone_form` and integration tests for the
`POST /api/v1/forms/{form_id}/clone` REST endpoint.

Implements spec §4 Test Specification.

---

## Scope

- Create `tests/unit/test_clone_form.py` with unit tests for
  `FormRegistry.clone_form`.
- Create `tests/integration/test_clone_rest.py` with integration tests for
  the REST endpoint.
- All tests must be async (`pytest-asyncio`).
- Unit tests use a plain `FormRegistry()` (no storage backend).
- Integration tests use `aiohttp.test_utils` to test the full HTTP stack
  (or mock the auth layer — follow existing integration test patterns).

### Unit tests to write

| Test | Description |
|---|---|
| `test_clone_basic` | Clone form, verify new form_id, version "1.0", created_at=None |
| `test_clone_deep_copy` | Mutating the clone does not affect the source |
| `test_clone_with_patch` | Apply merge-patch changing title and description |
| `test_clone_patch_cannot_change_form_id` | Patch with `form_id` key is ignored |
| `test_clone_source_not_found` | Raises KeyError when source does not exist |
| `test_clone_duplicate_form_id` | Raises ValueError when new_form_id already exists |
| `test_clone_validation_error` | Patch producing invalid schema raises ValueError |
| `test_clone_resets_version` | Source has version "2.3", clone has "1.0" |
| `test_clone_resets_created_at` | Source has created_at set, clone has None |
| `test_clone_sets_cloned_from_meta` | `meta["cloned_from"]` equals source form_id |
| `test_clone_preserves_sections` | All sections and fields survive the clone |
| `test_clone_with_tenant` | Tenant kwarg is passed through correctly |

### Integration tests to write

| Test | Description |
|---|---|
| `test_clone_rest_success` | POST /clone returns 201 with full FormSchema |
| `test_clone_rest_missing_new_form_id` | Returns 400 when new_form_id missing |
| `test_clone_rest_empty_new_form_id` | Returns 400 when new_form_id is "" |
| `test_clone_rest_source_not_found` | Returns 404 for unknown source |
| `test_clone_rest_with_patch` | Returns 201 with patch applied |
| `test_clone_rest_duplicate_id` | Returns 409 when new_form_id exists |
| `test_clone_rest_invalid_json` | Returns 400 for malformed JSON body |

**NOT in scope**: Implementation of clone_form or the handler (TASK-1227/1228).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/unit/test_clone_form.py` | CREATE | Unit tests for FormRegistry.clone_form |
| `packages/parrot-formdesigner/tests/integration/test_clone_rest.py` | CREATE | Integration tests for REST endpoint |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Test infrastructure
import pytest                                  # standard
import pytest_asyncio                          # for async fixtures if needed

# Models
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField  # verified: core/schema.py
from parrot_formdesigner.core.types import FieldType  # verified: core/types.py

# Service under test
from parrot_formdesigner.services.registry import FormRegistry  # verified: services/registry.py:116

# For integration tests (follow existing pattern)
from aiohttp import web                        # verified: api/routes.py:32
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop  # aiohttp standard
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:                           # line 116
    def __init__(self, storage: FormStorage | None = None) -> None:  # line 133
    async def register(self, form: FormSchema, *, persist: bool = False, overwrite: bool = True) -> None:  # line 146
    async def get(self, form_id: str) -> FormSchema | None:  # line 214
    async def contains(self, form_id: str) -> bool:  # line 244
    async def clone_form(                      # (created by TASK-1227)
        self,
        source_form_id: str,
        new_form_id: str,
        patch: dict[str, Any] | None = None,
        *,
        persist: bool = True,
        tenant: str | None = None,
    ) -> FormSchema: ...

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema(BaseModel):                  # line 153
    form_id: str                              # line 178
    version: str = "1.0"                      # line 179
    title: LocalizedString                    # line 180
    description: LocalizedString | None       # line 181
    sections: list[FormSection]               # line 182
    meta: dict[str, Any] | None = None        # line 185
    created_at: datetime | None = None        # line 186
    tenant: str | None = None                 # line 187

class FormSection(BaseModel):                 # line 101
    section_id: str
    title: LocalizedString | None = None
    fields: list[SectionItem]

class FormField(BaseModel):                   # line 23
    field_id: str
    field_type: FieldType
    label: LocalizedString
    required: bool = False

# packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py
class FieldType(str, Enum):
    TEXT = "text"
    # ... other types
```

### Existing Test Patterns to Follow

```python
# Reference: packages/parrot-formdesigner/tests/unit/test_storage_list.py
# Uses plain FormRegistry() with no storage backend for unit tests.

# Reference: packages/parrot-formdesigner/tests/integration/test_operations_e2e.py
# Uses aiohttp test client for integration tests.
```

### Does NOT Exist

- ~~`FormRegistry.clone`~~ — the method is `clone_form`, not `clone`
- ~~`FormRegistry.duplicate`~~ — does not exist
- ~~`FormSchema.clone()`~~ — no such method

---

## Implementation Notes

### Pattern to Follow

```python
# Unit test pattern for FormRegistry (no storage needed)
@pytest.fixture
def sample_form() -> FormSchema:
    return FormSchema(
        form_id="source-form",
        title="Source Form",
        version="2.3",
        sections=[
            FormSection(
                section_id="sec1",
                title="Section 1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="Full Name",
                        required=True,
                    ),
                ],
            ),
        ],
    )

@pytest.fixture
async def registry(sample_form) -> FormRegistry:
    reg = FormRegistry()
    await reg.register(sample_form)
    return reg
```

### Key Constraints

- All tests must be async — use `@pytest.mark.asyncio`.
- Unit tests do NOT require a database or storage backend.
- Integration tests must mock or bypass navigator-auth (follow existing
  integration test patterns in the package).
- Check existing test files for import patterns and conftest fixtures.

### References in Codebase

- `packages/parrot-formdesigner/tests/unit/test_storage_list.py` — registry test patterns
- `packages/parrot-formdesigner/tests/unit/test_storage_schema_tenant.py` — tenant tests
- `packages/parrot-formdesigner/tests/integration/test_operations_e2e.py` — REST test patterns

---

## Acceptance Criteria

- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_clone_form.py -v`
- [ ] All integration tests pass: `pytest packages/parrot-formdesigner/tests/integration/test_clone_rest.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/tests/`
- [ ] At least 12 unit test cases covering all edge cases
- [ ] At least 7 integration test cases covering all HTTP error paths
- [ ] Tests are async with `@pytest.mark.asyncio`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_clone_form.py
import pytest
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry


@pytest.fixture
def sample_form() -> FormSchema:
    return FormSchema(
        form_id="source-form",
        title="Source Form",
        version="2.3",
        sections=[
            FormSection(
                section_id="sec1",
                title="Section 1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="Full Name",
                        required=True,
                    ),
                ],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_clone_basic(sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    clone = await registry.clone_form("source-form", "cloned-form")
    assert clone.form_id == "cloned-form"
    assert clone.version == "1.0"
    assert clone.created_at is None


@pytest.mark.asyncio
async def test_clone_deep_copy(sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    clone = await registry.clone_form("source-form", "cloned-form")
    clone.sections[0].fields[0].label = "Changed"
    source = await registry.get("source-form")
    assert source.sections[0].fields[0].label == "Full Name"


@pytest.mark.asyncio
async def test_clone_source_not_found():
    registry = FormRegistry()
    with pytest.raises(KeyError):
        await registry.clone_form("nonexistent", "new-form")


@pytest.mark.asyncio
async def test_clone_duplicate_form_id(sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    existing = FormSchema(
        form_id="taken-id",
        title="Existing",
        sections=[],
    )
    await registry.register(existing)
    with pytest.raises(ValueError, match="already exists"):
        await registry.clone_form("source-form", "taken-id")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-clone-form.spec.md` for full context
2. **Check dependencies** — verify TASK-1227 and TASK-1228 are in `sdd/tasks/completed/`
3. **Check existing test patterns** — read a few existing test files for import
   and fixture patterns before writing
4. **Verify the Codebase Contract** — confirm `FormRegistry.clone_form` exists
   and `clone_form` handler is registered
5. **Implement** both test files
6. **Run tests** to confirm they pass
7. **Move this file** to `sdd/tasks/completed/TASK-1229-clone-form-tests.md`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: SDD Worker (claude-sonnet-4-6)
**Date**: 2026-05-18
**Notes**: Created 14 unit tests in `tests/unit/test_clone_form.py` and 7
integration tests in `tests/integration/test_clone_rest.py`. All 21 tests
pass. Unit tests cover: basic clone, version reset, created_at reset,
cloned_from meta, section preservation, deep copy isolation, patch
application, patch cannot override form_id, source not found, duplicate
form_id, validation error, tenant forwarding, registry state. Integration
tests cover: success 201, patch body, missing new_form_id, empty
new_form_id, invalid JSON, source not found 404, duplicate id 409. Auth
is bypassed in integration tests by registering the handler directly
without _wrap_auth, matching the existing test_operations_e2e.py pattern.

**Deviations from spec**: none
