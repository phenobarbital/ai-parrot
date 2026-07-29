---
type: Wiki Overview
title: 'TASK-1127: NetworkninjaFormService — migrate existing logic'
id: doc:sdd-tasks-completed-task-1127-networkninja-form-service-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 Module 3 of the spec. Migrates the existing NetworkNinja-specific
relates_to:
- concept: mod:parrot.conf
  rel: mentions
---

# TASK-1127: NetworkninjaFormService — migrate existing logic

**Feature**: FEAT-166 — Multi-Origin FormDesigner — Pluggable AbstractFormService
**Spec**: `sdd/specs/multi-origin-formdesigner.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1125, TASK-1126
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 3 of the spec. Migrates the existing NetworkNinja-specific
SQL query, field-type map, option-collection, conditional-logic, and section /
field mapping logic from `DatabaseFormTool` into a dedicated
`NetworkninjaFormService(AbstractFormService)`. The service also owns its own
DSN resolution per proposal Q&A (U2). This is the largest task — but the
implementation is a pure relocation; **no semantic changes** to the
transformation pipeline.

The acceptance bar is **zero behavior change for the default networkninja
case** (the relocated helpers must produce byte-identical `FormSchema` objects
for the same input rows).

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/networkninja.py`
  with class `NetworkninjaFormService(AbstractFormService)`.
- Move the following symbols **verbatim** from
  `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py`
  into the new service module (do NOT keep duplicates in `database_form.py`;
  TASK-1129 will delete them from the original location):
  - `_FORM_QUERY` (lines 43-58)
  - `_FIELD_TYPE_MAP` (lines 66-98)
  - `_OPTION_FIELD_TYPES` (lines 101-105)
- Reshape the migrated methods into the `NetworkninjaFormService` class:
  - `fetch(self, *, formid: int, orgid: int, **_: Any) -> dict[str, Any]`
    becomes the new home for the `_fetch_form_row` body (lines 289-314 of the
    current `database_form.py`). It must return the row dict, or raise
    `RuntimeError("Form not found: formid=…, orgid=…")` when the query returns
    no row — the dispatcher (TASK-1129) translates that into a failing
    `ToolResult`.
  - `to_form_schema(self, raw: dict[str, Any]) -> FormSchema` becomes the
    home for `_build_form_schema` (lines 320-367). Existing private helpers
    (`_build_metadata_index`, `_build_question_id_index`,
    `_collect_select_options`, `_map_block_to_section`,
    `_map_question_to_field`, `_map_logic_groups`) become methods on the
    service class.
- Add DSN resolution as a private method `_get_dsn()`. Resolution order
  (mirrors current `_get_dsn` at `database_form.py:179-201`):
  1. Explicit constructor `dsn=` kwarg.
  2. `PARROT_NETWORKNINJA_DSN` env var.
  3. `parrot.conf.default_dsn` (import-time fallback).
  4. Else raise `RuntimeError` with a clear message.
- Constructor signature:
  ```python
  def __init__(self, db: Any | None = None, dsn: str | None = None) -> None:
      self._db = db
      self._dsn = dsn
      self.logger = logging.getLogger(__name__)
  ```
- No tests in this task — the comprehensive test coverage is moved/extended in
  TASK-1130. Add a single smoke test verifying the service is instantiable and
  `to_form_schema` produces a valid `FormSchema` from a minimal mock row, so
  CI is green at this checkpoint.

**NOT in scope**: removing the symbols from `database_form.py` (TASK-1129);
registering the service in the sub-package `__init__` (TASK-1128); relocating
the 27 mapping tests (TASK-1130).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/networkninja.py` | CREATE | Migrated NetworkNinja form-source logic |
| `packages/parrot-formdesigner/tests/unit/test_networkninja_smoke.py` | CREATE | Single smoke test to keep CI green at this checkpoint |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Relative imports from the new module
from ...core.constraints import ConditionOperator, DependencyRule, FieldCondition  # line 33 of current database_form.py
from ...core.options import FieldOption                                            # line 34 of current database_form.py
from ...core.schema import FormField, FormSchema, FormSection                      # lines 21, 68, 108 of core/schema.py
from ...core.types import FieldType                                                # line 37 of current database_form.py
from .abstract import AbstractFormService                                          # created by TASK-1125

# Inside fetch() — lazy import preserves current pattern (database_form.py:304)
from asyncdb import AsyncDB  # noqa: PLC0415

# Inside _get_dsn() — lazy import preserves current pattern (database_form.py:195)
from parrot.conf import default_dsn  # noqa: PLC0415
```

### Existing Signatures to Use

```python
# CURRENT — packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py
# (to be migrated verbatim into NetworkninjaFormService)

_FORM_QUERY = """SELECT … FROM networkninja.forms f JOIN networkninja.form_metadata m USING(formid) WHERE …"""  # lines 43-58

_FIELD_TYPE_MAP: dict[str, tuple[FieldType, dict[str, Any]] | None] = {
    "FIELD_TEXT": (FieldType.TEXT, {}),
    "FIELD_TEXTAREA": (FieldType.TEXT_AREA, {}),
    # …                                                          # lines 66-98
}

_OPTION_FIELD_TYPES: set[str] = {
    "FIELD_SELECT", "FIELD_SELECT_RADIO", "FIELD_MULTISELECT",
}                                                                # lines 101-105

# Methods on the current DatabaseFormTool (to be moved as methods on
# NetworkninjaFormService):
async def _fetch_form_row(self, formid, orgid) -> dict[str, Any] | None: ...   # line 289
def _get_dsn(self) -> str: ...                                                  # line 179
def _build_form_schema(self, row: dict[str, Any]) -> FormSchema: ...            # line 320
def _build_metadata_index(self, raw_metadata) -> dict[str, dict[str, Any]]: ... # line 373
def _build_question_id_index(self, blocks, meta_index) -> dict[str, str]: ...   # line 395
def _collect_select_options(self, blocks, qid_idx, meta_idx) -> dict[str, list[FieldOption]]: ... # line 428
def _map_block_to_section(self, block, meta_idx, qid_idx, options) -> FormSection | None: ...     # line 524
def _map_question_to_field(self, q, meta_idx, qid_idx, options) -> FormField | None: ...          # line 565
def _map_logic_groups(self, q, qid_idx) -> DependencyRule | None: ...                              # line 654
```

### Does NOT Exist

- ~~`AsyncDB.aqueryrow()`~~ — the actual API is `conn.queryrow(query, *params)` returning `(result, errors)` (see current `database_form.py:309`).
- ~~`parrot.conf.PARROT_NETWORKNINJA_DSN`~~ — there is no `parrot.conf` constant for this. The env var is consulted via `os.environ.get(...)`.
- ~~`NetworkninjaFormService.execute()`~~ — the service has `fetch()` and `to_form_schema()`; the dispatcher tool has `_execute`. Do not confuse them.
- ~~`NetworkninjaFormService.register(registry)`~~ — registry coupling stays in the tool, not the service.

---

## Implementation Notes

### Pattern to Follow

The migration is a refactor-without-rewrite. Each helper from `database_form.py`
becomes a method on `NetworkninjaFormService` with the same body. Only the
top-level orchestration changes:

```python
class NetworkninjaFormService(AbstractFormService):
    """NetworkNinja PostgreSQL form-source service.

    Owns the SQL query against `networkninja.forms` + `networkninja.form_metadata`
    and the question_blocks → FormSchema transformation pipeline.

    DSN resolution order:
        1. constructor `dsn=` kwarg
        2. `PARROT_NETWORKNINJA_DSN` env var
        3. `parrot.conf.default_dsn`
    """

    def __init__(self, db: Any | None = None, dsn: str | None = None) -> None:
        self._db = db
        self._dsn = dsn
        self.logger = logging.getLogger(__name__)

    async def fetch(self, *, formid: int, orgid: int, **_: Any) -> dict[str, Any]:
        """Run the parameterized SQL query and return the row dict.

        Raises:
            RuntimeError: when no row matches the (formid, orgid) pair, or on DB error.
        """
        from asyncdb import AsyncDB  # noqa: PLC0415
        db = self._db or AsyncDB("pg", dsn=self._get_dsn())
        async with await db.connection() as conn:
            result, errors = await conn.queryrow(_FORM_QUERY, formid, orgid)
        if errors:
            raise RuntimeError(f"DB query failed for formid={formid}: {errors}")
        if result is None:
            raise RuntimeError(f"Form not found: formid={formid}, orgid={orgid}")
        return result

    def to_form_schema(self, raw: dict[str, Any]) -> FormSchema:
        """Transform the row dict into a FormSchema (was _build_form_schema)."""
        # … verbatim from database_form.py:320-367 …

    def _get_dsn(self) -> str:
        if self._dsn:
            return self._dsn
        env_dsn = os.environ.get("PARROT_NETWORKNINJA_DSN")
        if env_dsn:
            return env_dsn
        try:
            from parrot.conf import default_dsn  # noqa: PLC0415
            return default_dsn
        except ImportError as exc:
            raise RuntimeError(
                "No DSN provided. Pass dsn= to NetworkninjaFormService, "
                "set PARROT_NETWORKNINJA_DSN, or install parrot.conf."
            ) from exc

    # All other private helpers (_build_metadata_index, _build_question_id_index,
    # _collect_select_options, _map_block_to_section, _map_question_to_field,
    # _map_logic_groups) move verbatim.
```

### Key Constraints

- `_FORM_QUERY` must be byte-identical to the current SQL — do not reformat,
  reword, or reorder columns.
- `_FIELD_TYPE_MAP` must remain a module-level constant (not class-level) so
  `import` cost stays the same and future tests can patch it cleanly.
- Wrap `from asyncdb import AsyncDB` and `from parrot.conf import default_dsn`
  with `# noqa: PLC0415` (lazy import) — mirrors current `database_form.py:304, 195`.
- Note on `fetch` behavior change vs. current `_fetch_form_row`: the current
  method returns `None` on no-match and the tool's `_execute` translates that
  into a failing `ToolResult` (`database_form.py:228-236`). After refactor,
  the service raises `RuntimeError` and the dispatcher (TASK-1129) catches it
  to produce the same `ToolResult`. The end-to-end behavior is unchanged.
- Add `self.logger.info(...)` calls equivalent to the current ones inside the
  helpers to preserve logging output.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py` — the source-of-migration; **read it carefully before relocating**.
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:39-58` — `FormStorage.save` for async signature style.

---

## Acceptance Criteria

- [ ] `parrot_formdesigner/tools/services/networkninja.py` exists with `NetworkninjaFormService(AbstractFormService)`.
- [ ] `_FORM_QUERY`, `_FIELD_TYPE_MAP`, `_OPTION_FIELD_TYPES` defined as module-level constants in the new module, byte-identical to the originals.
- [ ] All migrated mapping helpers are methods on the service class with the same body as in `database_form.py`.
- [ ] `fetch(formid=…, orgid=…)` runs the SQL via `asyncdb` and returns the row dict; raises `RuntimeError` on no-match or DB error.
- [ ] `to_form_schema(raw)` returns a `FormSchema` Pydantic instance.
- [ ] `_get_dsn()` resolution order: explicit arg → `PARROT_NETWORKNINJA_DSN` → `parrot.conf.default_dsn`; raises `RuntimeError` if none.
- [ ] Smoke test passes: `pytest packages/parrot-formdesigner/tests/unit/test_networkninja_smoke.py -v`.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/networkninja.py` clean.
- [ ] No mention of `register_form_service` in this module — registration happens in TASK-1128.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_networkninja_smoke.py
"""Smoke tests for NetworkninjaFormService — minimal coverage at this checkpoint.
Full mapping test relocation happens in TASK-1130."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from parrot_formdesigner.tools.services.networkninja import NetworkninjaFormService
from parrot_formdesigner.core.schema import FormSchema


def test_instantiable():
    svc = NetworkninjaFormService(dsn="postgres://fake/db")
    assert svc is not None


def test_to_form_schema_returns_form_schema_for_empty_blocks():
    """to_form_schema produces a FormSchema even with zero question_blocks."""
    svc = NetworkninjaFormService(dsn="postgres://fake/db")
    row = {
        "formid": 1,
        "form_name": "Empty",
        "description": None,
        "client_id": 1,
        "client_name": "C",
        "orgid": 1,
        "question_blocks": json.dumps([]),
        "metadata": [],
    }
    form = svc.to_form_schema(row)
    assert isinstance(form, FormSchema)
    assert form.form_id == "db-form-1-1"
    assert form.sections == []


def test_get_dsn_prefers_constructor_arg(monkeypatch):
    monkeypatch.delenv("PARROT_NETWORKNINJA_DSN", raising=False)
    svc = NetworkninjaFormService(dsn="postgres://explicit")
    assert svc._get_dsn() == "postgres://explicit"


def test_get_dsn_uses_env_var(monkeypatch):
    monkeypatch.setenv("PARROT_NETWORKNINJA_DSN", "postgres://from-env")
    svc = NetworkninjaFormService()
    assert svc._get_dsn() == "postgres://from-env"
```

---

## Completion Note

Implemented as specified. Created:
- `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/networkninja.py` — `NetworkninjaFormService(AbstractFormService)` with verbatim migration of `_FORM_QUERY`, `_FIELD_TYPE_MAP`, `_OPTION_FIELD_TYPES` (module-level), and all mapping methods as instance methods.
- `packages/parrot-formdesigner/tests/unit/test_networkninja_smoke.py` — 4 smoke tests all passing.

DSN resolution order: constructor arg → `PARROT_NETWORKNINJA_DSN` → `parrot.conf.default_dsn`. Smoke tests pass: 4/4.
