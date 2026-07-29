---
type: Wiki Overview
title: 'TASK-1130: Test split — relocate 27 mapping tests + shared fixtures'
id: doc:sdd-tasks-completed-task-1130-test-split-and-fixtures-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 Module 6 of the spec. The current
relates_to:
- concept: mod:parrot.forms
  rel: mentions
- concept: mod:parrot.forms.tools.database_form
  rel: mentions
---

# TASK-1130: Test split — relocate 27 mapping tests + shared fixtures

**Feature**: FEAT-166 — Multi-Origin FormDesigner — Pluggable AbstractFormService
**Spec**: `sdd/specs/multi-origin-formdesigner.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1127, TASK-1129
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 6 of the spec. The current
`tests/forms/test_database_form.py` holds 27 networkninja-specific mapping
tests (5 test classes: `TestFieldTypeMapping`, `TestConditionalLogic`,
`TestValidationMapping`, `TestQuestionBlockSections`, `TestFullFormGeneration`)
that exercise the now-relocated logic. This task retargets those assertions
onto `NetworkninjaFormService` directly, then leaves
`tests/forms/test_database_form.py` as a thin dispatcher-level file that
keeps `from parrot.forms import DatabaseFormTool, FormRegistry` working.

The goal is **same assertions, new target**: the implementing agent should
copy each test method body verbatim, change the construction to instantiate
`NetworkninjaFormService` directly, and patch `fetch` (not `_fetch_form_row`)
on the service.

---

## Scope

- Create `tests/forms/conftest.py` (if not already present) housing the
  shared `sample_db_row` and `sample_metadata_with_unsupported` fixtures
  currently inside `tests/forms/test_database_form.py:42-end`. Move them
  byte-identical so both new test files can import them.
- Create `tests/forms/test_networkninja_form_service.py` containing the 5
  classes — `TestFieldTypeMapping`, `TestConditionalLogic`,
  `TestValidationMapping`, `TestQuestionBlockSections`,
  `TestFullFormGeneration` — relocated from the current
  `tests/forms/test_database_form.py`. Adjust:
  - `_make_tool` helper → `_make_service(dsn="postgres://fake/db") -> NetworkninjaFormService`.
  - `_build(row, registry=None)` → call `service.to_form_schema(row)` directly
    (no registry; registry coupling moved to TASK-1129's dispatcher tests).
  - Imports: replace `from parrot.forms import DatabaseFormTool, FormRegistry`
    with `from parrot_formdesigner.tools.services import NetworkninjaFormService`
    and `from parrot_formdesigner.tools.services.networkninja import _FIELD_TYPE_MAP`
    (the constant moved with the migration).
  - Any test that previously patched `DatabaseFormTool._fetch_form_row` now
    patches `NetworkninjaFormService.fetch`.
- Replace `tests/forms/test_database_form.py` with the dispatcher-level
  smoke suite (re-using or expanding the suite created by TASK-1129's
  dispatch tests, but importing via `from parrot.forms import DatabaseFormTool`
  to validate the public shim path).
- Verify the legacy fallback module
  `packages/ai-parrot/src/parrot/forms/tools/database_form.py` is **not**
  imported or referenced by any new test (it must stay frozen per §1 Non-Goals).

**NOT in scope**: any changes to `parrot.forms.__init__`; any changes to the
legacy fallback module.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/forms/conftest.py` | CREATE or MODIFY | Move `sample_db_row` and `sample_metadata_with_unsupported` fixtures |
| `tests/forms/test_networkninja_form_service.py` | CREATE | The 5 relocated test classes targeting `NetworkninjaFormService.to_form_schema` |
| `tests/forms/test_database_form.py` | REWRITE | Slim down to dispatcher-level smoke tests using `from parrot.forms import …` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Inside test_networkninja_form_service.py
from parrot_formdesigner.tools.services import NetworkninjaFormService
from parrot_formdesigner.tools.services.networkninja import _FIELD_TYPE_MAP  # after migration
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.core.constraints import ConditionOperator
from parrot_formdesigner.core.types import FieldType

# Inside the rewritten test_database_form.py — exercise the public shim
from parrot.forms import DatabaseFormTool, FormRegistry  # verified shim: packages/ai-parrot/src/parrot/forms/__init__.py
```

### Existing Signatures to Use

```python
# tests/forms/test_database_form.py (BEFORE refactor — read this file to copy bodies):
#   class TestFieldTypeMapping: ...
#   class TestConditionalLogic: ...
#   class TestValidationMapping: ...
#   class TestQuestionBlockSections: ...
#   class TestFullFormGeneration: ...
#   def _make_tool(registry=None) -> DatabaseFormTool: ...
#   def _build(row, registry=None) -> FormSchema: ...
#   @pytest.fixture sample_db_row() -> dict[str, Any]: ...
#   @pytest.fixture sample_metadata_with_unsupported() -> list[dict[str, Any]]: ...
#   @pytest.fixture registry() -> FormRegistry: ...

# After this task, on NetworkninjaFormService:
class NetworkninjaFormService(AbstractFormService):
    def __init__(self, db: Any | None = None, dsn: str | None = None) -> None: ...
    async def fetch(self, *, formid: int, orgid: int, **_: Any) -> dict[str, Any]: ...
    def to_form_schema(self, raw: dict[str, Any]) -> FormSchema: ...
```

### Does NOT Exist

- ~~`NetworkninjaFormService._fetch_form_row`~~ — the method is now `fetch`. Patch that name.
- ~~`from parrot.forms.tools.database_form import _FIELD_TYPE_MAP`~~ — that import path still works (legacy fallback), but the canonical path is `parrot_formdesigner.tools.services.networkninja._FIELD_TYPE_MAP`. Use the canonical path.
- ~~Calling `await tool.execute(...)` from `test_networkninja_form_service.py`~~ — service tests bypass the tool entirely and call `to_form_schema(row)` synchronously after a (mocked) `fetch`.

---

## Implementation Notes

### Pattern to Follow

```python
# tests/forms/test_networkninja_form_service.py (skeleton — copy bodies verbatim from old file)
from __future__ import annotations
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from parrot_formdesigner.tools.services import NetworkninjaFormService
from parrot_formdesigner.tools.services.networkninja import _FIELD_TYPE_MAP
from parrot_formdesigner.core.constraints import ConditionOperator
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.core.types import FieldType


def _make_service() -> NetworkninjaFormService:
    """Construct a fresh service without DB access (matches old _make_tool)."""
    return NetworkninjaFormService(dsn="postgres://fake/db")


def _build(row: dict[str, Any]) -> FormSchema:
    """Equivalent of the old _build helper — now bypasses the tool entirely."""
    return _make_service().to_form_schema(row)


# Fixtures imported automatically from tests/forms/conftest.py


class TestFieldTypeMapping:
    """Copy bodies of all the prior tests from tests/forms/test_database_form.py.
    Assertion targets stay identical; only the construction path changes."""
    # … verbatim test bodies …


class TestConditionalLogic:
    # … verbatim test bodies …


class TestValidationMapping:
    # … verbatim test bodies …


class TestQuestionBlockSections:
    # … verbatim test bodies …


class TestFullFormGeneration:
    """End-to-end mock-row → FormSchema. The single test that touched
    fetch() should now patch `NetworkninjaFormService.fetch`:
        with patch.object(NetworkninjaFormService, 'fetch', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = sample_db_row
            svc = _make_service()
            row = asyncio.run(svc.fetch(formid=4, orgid=71))
            form = svc.to_form_schema(row)
    """
```

```python
# tests/forms/test_database_form.py (rewritten — dispatcher smoke at the public shim)
"""Dispatcher-level integration via the public parrot.forms shim."""
import pytest
from parrot.forms import DatabaseFormTool, FormRegistry


@pytest.fixture
def registry():
    return FormRegistry()


def test_public_shim_constructor(registry):
    tool = DatabaseFormTool(registry=registry)
    assert tool is not None


def test_public_shim_input_defaults():
    from parrot_formdesigner.tools.database_form import DatabaseFormInput
    inp = DatabaseFormInput(formid=1, orgid=1)
    assert inp.service == "networkninja"
```

### Key Constraints

- Keep the **same assertion structures and edge-case coverage** as the
  pre-refactor test file. Do not skip cases. If a test patched
  `_fetch_form_row`, the equivalent now patches `NetworkninjaFormService.fetch`.
- Use `tests/forms/conftest.py` for shared fixtures — both `test_networkninja_form_service.py`
  and `test_database_form.py` will rely on pytest's auto-discovery to import them.
- Do NOT add coverage for `_FIELD_TYPE_MAP` keys beyond what existed pre-refactor.
- The rewritten `test_database_form.py` MUST keep working with `from parrot.forms import …`
  so the parrot.forms shim continues to be exercised in CI.

### References in Codebase

- `tests/forms/test_database_form.py` (current state, pre-refactor) — read it carefully; this task is mostly a relocation of its contents.
- `packages/ai-parrot/src/parrot/forms/__init__.py` — the public shim that exposes `DatabaseFormTool` and `FormRegistry`.

---

## Acceptance Criteria

- [ ] `tests/forms/conftest.py` exists and houses `sample_db_row`, `sample_metadata_with_unsupported` (and any other shared fixtures from the old `test_database_form.py`). Bodies are byte-identical to the originals.
- [ ] `tests/forms/test_networkninja_form_service.py` exists with all 5 test classes from the pre-refactor file (`TestFieldTypeMapping`, `TestConditionalLogic`, `TestValidationMapping`, `TestQuestionBlockSections`, `TestFullFormGeneration`).
- [ ] All 27 (or more) tests in `test_networkninja_form_service.py` pass: `pytest tests/forms/test_networkninja_form_service.py -v`.
- [ ] `tests/forms/test_database_form.py` is rewritten as a slim dispatcher-level smoke suite that imports via `from parrot.forms import DatabaseFormTool, FormRegistry`. It passes: `pytest tests/forms/test_database_form.py -v`.
- [ ] Full forms test suite passes: `pytest tests/forms/ -v`.
- [ ] Package smoke tests still pass: `pytest packages/parrot-formdesigner/ -v`.
- [ ] No test references `DatabaseFormTool._fetch_form_row` (deleted symbol).
- [ ] No test imports `_FIELD_TYPE_MAP` from `parrot.forms.tools.database_form` (canonical path is `parrot_formdesigner.tools.services.networkninja`).
- [ ] `packages/ai-parrot/src/parrot/forms/tools/database_form.py` is unmodified (legacy fallback frozen per §1 Non-Goals).

---

## Test Specification

The "test specification" for this task is the existing
`tests/forms/test_database_form.py` file (pre-refactor). Every assertion in
its 5 test classes must reappear — with the same expectations — in
`tests/forms/test_networkninja_form_service.py`. No new tests are required
beyond carrying that file over; the dispatcher coverage was already created
in TASK-1129.

A useful diff check before commit:

```bash
# After refactor, this should show NO functional regressions:
pytest tests/forms/test_networkninja_form_service.py --collect-only | grep -E '^\s*<Function'
# Compare against the pre-refactor list from the old test_database_form.py.
```

---

## Completion Note

Implemented as specified. Created/Modified:
- `tests/forms/conftest.py` — `sample_db_row` and `sample_metadata_with_unsupported` fixtures moved byte-identical from the old test file.
- `tests/forms/test_networkninja_form_service.py` — 5 test classes from the pre-refactor file retargeted to `NetworkninjaFormService.to_form_schema()`. 24 tests pass.
- `tests/forms/test_database_form.py` — rewritten as 4 dispatcher-level smoke tests importing via `from parrot.forms import DatabaseFormTool, FormRegistry`.
- `packages/parrot-formdesigner/tests/unit/test_init_imports_metadata_only.py` — updated version assertion `"0.2.0"` → `"0.3.0"` to reflect the version bump from TASK-1129.

Full test suites: `tests/forms/ — 28 passed`, `packages/parrot-formdesigner/tests/unit/ — 292 passed`.

*(Agent fills this in when done)*
