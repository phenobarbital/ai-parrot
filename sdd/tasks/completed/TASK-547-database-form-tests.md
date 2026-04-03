# TASK-547: Unit & Integration Tests for DatabaseFormTool

**Feature**: Form Builder from Database Definition
**Spec**: `sdd/specs/formbuilder-database.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-544, TASK-545
**Assigned-to**: unassigned

---

## Context

Comprehensive test suite for `DatabaseFormTool`, covering type mapping, conditional logic
translation, validation mapping, edge cases, and full form generation from mock DB results.

Implements **Module 4** from the spec.

---

## Scope

- Create test file with fixtures for mock DB results
- Unit tests for each field type mapping
- Unit tests for conditional logic translation (single condition, multi-condition OR, multi-group AND)
- Unit tests for validation mapping (`responseRequired` → `required=True`)
- Unit tests for edge cases:
  - Unsupported field types skipped
  - Questions not in metadata skipped
  - Display-only fields with correct `read_only` + `meta`
  - File upload fields with correct `meta`
- Integration tests:
  - Full `FormSchema` generation from mock DB result
  - Form not found → error `ToolResult`
  - Malformed `question_blocks` JSON → error `ToolResult`
  - Registry registration verification
- Test `question_id → column_name → field_id` resolution for conditional references

**NOT in scope**: Tool implementation (TASK-544), package exports (TASK-545), UI (TASK-546)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/forms/test_database_form.py` | CREATE | Unit and integration tests |

---

## Implementation Notes

### Pattern to Follow
```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.forms import DatabaseFormTool, FormRegistry
from parrot.forms.types import FieldType
from parrot.forms.constraints import ConditionOperator


@pytest.fixture
def registry():
    return FormRegistry()


@pytest.fixture
def sample_db_row():
    """Minimal form DB result with mixed field types and conditional logic."""
    return {
        "formid": 4,
        "form_name": "Assembly Checklist",
        "description": "Daily assembly report",
        "client_id": 1,
        "client_name": "TestClient",
        "orgid": 71,
        "question_blocks": json.dumps([...]),  # see spec for full fixture
        "metadata": [...]
    }
```

### Key Constraints
- Use `pytest` and `pytest-asyncio`
- Mock `asyncdb` connection — do NOT require a real database
- Use `unittest.mock.patch` or `AsyncMock` for DB calls
- Test the transformation logic in isolation

### References in Codebase
- `sdd/specs/formbuilder-database.spec.md` — Section 4 (Test Specification) has full fixtures
- `packages/ai-parrot/src/parrot/forms/tools/database_form.py` — implementation under test
- `tests/` — existing test patterns in the project

---

## Acceptance Criteria

- [ ] All 13+ unit tests pass (see spec Section 4)
- [ ] All 4 integration tests pass
- [ ] No real database required — all DB calls mocked
- [ ] Tests run with `pytest tests/forms/test_database_form.py -v`
- [ ] Edge cases covered: unsupported types, missing metadata, malformed JSON, empty form

---

## Test Specification

```python
class TestFieldTypeMapping:
    def test_field_text(self): ...
    def test_field_textarea(self): ...
    def test_field_integer(self): ...
    def test_field_float2(self): ...
    def test_field_yes_no(self): ...
    def test_field_multiselect(self): ...
    def test_field_image_upload(self): ...
    def test_display_text_readonly(self): ...
    def test_display_image_readonly(self): ...
    def test_unsupported_type_skipped(self): ...


class TestConditionalLogic:
    def test_single_condition_eq(self): ...
    def test_multi_conditions_or(self): ...
    def test_multi_groups_and(self): ...
    def test_question_id_to_field_id_resolution(self): ...


class TestValidationMapping:
    def test_response_required(self): ...
    def test_no_validations(self): ...


class TestQuestionBlockSections:
    def test_blocks_to_sections(self): ...
    def test_question_not_in_metadata_skipped(self): ...


class TestFullFormGeneration:
    async def test_full_form_from_mock_db(self): ...
    async def test_form_not_found(self): ...
    async def test_malformed_json(self): ...
    async def test_registry_registration(self): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formbuilder-database.spec.md` for full context
2. **Check dependencies** — TASK-544 and TASK-545 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-547-database-form-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude (sdd-worker)
**Date**: 2026-04-03
**Notes**: Created `tests/forms/test_database_form.py` with 25 tests across 5 classes:
- `TestFieldTypeMapping` (10 tests) — all 9 supported types + unsupported `FIELD_SIGNATURE_CAPTURE`
- `TestConditionalLogic` (4 tests) — single EQ, multi-condition OR, multi-group AND, question_id → field_id resolution
- `TestValidationMapping` (2 tests) — responseRequired → required=True, empty validations → required=False
- `TestQuestionBlockSections` (5 tests) — blocks→sections, missing metadata skip, header mapping, display-only fields, file upload meta
- `TestFullFormGeneration` (4 integration tests) — full pipeline, form not found, malformed JSON, registry registration
All 25 tests pass. No real DB required — all DB calls mocked with `unittest.mock.AsyncMock`.

**Deviations from spec**: none
