# TASK-2435: `FormSubmission.extra_data` + the `extra_data` JSONB column

**Feature**: FEAT-458 — Unknown-Field Capture Policy for Form Submissions
**Spec**: `sdd/specs/formdesigner-unknown-fields-capture.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 4

---

## Context

Where captured extras actually live. A dedicated column — not a corner of `data`
and not the audit `context` — because `keep` retains anonymous, unvalidated,
caller-controlled JSON from an unauthenticated endpoint, and "which of these keys
did a caller choose?" must stay answerable for retention and access decisions.

This task is self-contained storage work: no validator, no handler, no policy. It
is independent of FEAT-457 and of every other FEAT-458 task, so it can run in
parallel with TASK-2433.

Implements spec section 3 Module 4.

---

## Scope

- Add `extra_data: dict[str, Any] | None = None` to `FormSubmission`
  (`services/submissions.py:50`), documented in the `Attributes:` block: captured
  undeclared keys, verbatim; `None` when the policy was not `keep` **or** when
  `keep` was active and no extras arrived (resolved — `None`, never `{}`, spec AC23).
- Add `extra_data JSONB` to `_create_table_sql` (`:173`), placed next to `context`
  (`:205`).
- Add `ADD COLUMN IF NOT EXISTS extra_data JSONB` to the `_alter_table_sql` block
  (`:237-247`) so legacy tables pick it up on `initialize()` (`:301-303`).
- Extend `_insert_sql` (`:254`) with the column and a **`$22::text::jsonb`**
  parameter. The cast is mandatory — see Key Constraints.
- In `store()` (`:308`), serialize with `json.dumps(...)` when not `None`, mirroring
  the existing `context_json` handling at `:327-331`, and pass it as the new
  positional argument in the same order as `_insert_sql`.
- Extend `_SELECT_COLUMNS` (`:372`) and map the column back in
  `_row_to_submission` (`:380`) using its existing `_load_json` helper.
- Write unit tests in `packages/parrot-formdesigner/tests/unit/services/test_submission_extra_data.py`.

**NOT in scope**: Reading `form.unknown_fields` or deciding when to populate the
field (TASK-2436). `RESERVED_COLUMNS` / sink mapping (TASK-2438). Any change to
`api/audio_ws.py` — its `_finish_session` (`:1115`) builds `data` from
manifest-keyed session answers and never from a client payload, so `extra_data`
correctly stays `None` there with no code change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py` | MODIFY | Model field, DDL, ALTER, insert, store, read mapping |
| `packages/parrot-formdesigner/tests/unit/services/test_submission_extra_data.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. Do NOT invent an import or attribute.

### Verified Imports

```python
# Already present at services/submissions.py:17-25 — do not re-add:
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from pydantic import BaseModel, Field
from ._identifiers import qualified_table, validate_identifier
```

### Existing Signatures to Use

```python
# services/submissions.py:31-32
DEFAULT_SCHEMA = "navigator"
DEFAULT_TABLE = "form_data"

# services/submissions.py:39-47 — order is significant; matches _insert_sql column order.
# NOTE: extra_data is NOT a metadata column — do NOT add it here.
CORE_METADATA_COLUMNS: tuple[str, ...] = (
    "user_id", "username", "org_id", "submitted_at", "ip", "user_agent", "locale",
)

# services/submissions.py:50 — the model to extend (last field is `context`, :115)
class FormSubmission(BaseModel):
    submission_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    form_uid: uuid.UUID = Field(..., description="Immutable UUID of the parent form")
    form_id: str
    form_version: str
    data: dict[str, Any]                    # line 97 — "The validated (sanitized) submission data."
    is_valid: bool                          # line 98
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tenant: str | None = None
    user_id: str | None = None
    username: str | None = None
    org_id: int | None = None
    submitted_at: datetime | None = None
    ip: str | None = None
    user_agent: str | None = None
    locale: str | None = None
    root_submission_id: str | None = None
    revision: int | None = None
    context: dict[str, Any] | None = None   # line 115  ← add extra_data after this

# services/submissions.py:118
class FormSubmissionStorage:
    def __init__(self, pool: Any, *, schema: str = DEFAULT_SCHEMA,
                 table_name: str = DEFAULT_TABLE, tenant: str | None = None): ...
    def _create_table_sql(self, tenant: str | None) -> str: ...   # line 173; data JSONB :190, context JSONB :205
    def _alter_table_sql(self, tenant: str | None) -> str: ...    # line 216; ADD COLUMN block :237-247
    def _insert_sql(self, tenant: str | None) -> str: ...         # line 254
    async def initialize(self, *, tenant: str | None = None) -> None: ...  # line 289; CREATE then ALTER :301-303
    async def store(self, submission: FormSubmission, *,
                    tenant: str | None = None) -> str: ...        # line 308
    _SELECT_COLUMNS: str = ...                                    # line 372
    @staticmethod
    def _row_to_submission(row: Any) -> FormSubmission: ...       # line 380

# The EXACT current insert parameter list (:275-283) — extra_data becomes $22:
#   INSERT INTO {qt} (
#       submission_id, form_uid, form_id, form_version, data,
#       is_valid, forwarded, forward_status, forward_error,
#       tenant, created_at,
#       user_id, username, org_id, submitted_at, ip, user_agent, locale,
#       root_submission_id, revision, context
#   ) VALUES (
#       $1, $2, $3, $4, $5::text::jsonb, $6, $7, $8, $9, $10, $11,
#       $12, $13, $14, $15, $16, $17, $18,
#       $19, $20, $21::text::jsonb
#   )

# The EXACT existing context serialization in store() (:327-331) — mirror it:
#   context_json = (
#       json.dumps(submission.context)
#       if submission.context is not None
#       else None
#   )

# _row_to_submission's existing helper (inside the method):
#   def _load_json(value: Any) -> Any:
#       if value is None or isinstance(value, (dict, list)):
#           return value
#       return json.loads(value)
```

### Does NOT Exist

- ~~`FormSubmission.extra_data`~~ and ~~the `extra_data` column~~ — neither the
  model field nor the DDL exists. The only JSONB columns today are `data` (`:190`)
  and `context` (`:205`).
- ~~A migration script directory for this table~~ — `initialize()` (`:289`) runs
  CREATE then ALTER at `:301-303`; that is the whole migration path. Do NOT write
  a standalone migration script.
- ~~`RESERVED_COLUMNS`~~ — planned by FEAT-457/TASK-2420, not landed. Not this
  task's concern (TASK-2438 handles it).
- ~~A third `store()` caller~~ — only two exist: `api/handlers.py:1617` and
  `api/audio_ws.py:1149`. There is no revision-insert path to update.
- ~~`asyncpg` json codec being safe to rely on~~ — it is NOT. See Key Constraints.

---

## Implementation Notes

### Pattern to Follow

```python
# _insert_sql — the new parameter MUST carry the cast, exactly like $5 and $21:
#   ..., root_submission_id, revision, context, extra_data
# ) VALUES (
#   ..., $19, $20, $21::text::jsonb, $22::text::jsonb
# )

# store() — mirror the existing context_json block at :327-331:
extra_data_json = (
    json.dumps(submission.extra_data)
    if submission.extra_data is not None
    else None
)

# _row_to_submission — reuse the existing helper:
extra_data=_load_json(row["extra_data"]),   # None stays None; no `or {}` — see below
```

### Key Constraints

- **`$22::text::jsonb` is mandatory, not stylistic.** `_insert_sql`'s own comment
  (`:255-273`) records a measured 2026-08-14 production defect: a host-provided
  asyncpg pool with a registered json codec re-encoded a bare parameter, storing a
  jsonb **string** instead of an object (`jsonb_typeof = 'string'`), after which
  `get_submission` raised `ValidationError` reading back its own rows. A bare `$22`
  reintroduces exactly that bug.
- **`None`, never `{}`** (spec AC23). Do NOT write `_load_json(row["extra_data"]) or {}`
  — note `data` uses `or {}` at its mapping site, and copying that line here would
  silently convert `NULL` into `{}` and destroy the distinction between "policy off"
  and "policy on, nothing arrived".
- The column must be **nullable with no default**, which is what makes
  `ADD COLUMN IF NOT EXISTS` metadata-only on existing rows — the property
  `_alter_table_sql`'s docstring (`:217-221`) depends on.
- Keep the insert argument order in `store()` exactly aligned with the column list
  in `_insert_sql`. A silent off-by-one here writes values into the wrong columns.
- No new index. Extras are not a query key in this scope.

### References in Codebase

- `services/submissions.py:255-273` — the double-encoding comment; read it before
  touching the insert.
- `services/submissions.py:217-221` — why `ADD COLUMN IF NOT EXISTS` is cheap.
- `services/submissions.py:327-331` — the `context_json` serialization to mirror.
- `services/storage.py` — `PostgresFormStorage._upsert_sql` applied the same
  `::text::jsonb` fix for `form_schemas`.

---

## Acceptance Criteria

- [ ] `FormSubmission(...)` built without `extra_data` works and yields `None`.
- [ ] `_create_table_sql()` output contains `extra_data JSONB`.
- [ ] `_alter_table_sql()` output contains `ADD COLUMN IF NOT EXISTS extra_data JSONB`.
- [ ] `_insert_sql()` output contains `$22::text::jsonb` and NOT a bare `$22`.
- [ ] `store()` passes `json.dumps(extra_data)` when set and `None` when not.
- [ ] `_SELECT_COLUMNS` includes `extra_data`.
- [ ] `_row_to_submission` returns a `dict` for a JSONB dict, a `dict` for a JSON
      **string** (codec-registered pool), and `None` for SQL `NULL` — never `{}`
      (spec AC23).
- [ ] A legacy row with no `extra_data` value maps to `extra_data is None` (spec AC3).
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/services/test_submission_extra_data.py -v`
- [ ] Existing submission tests still pass:
      `pytest packages/parrot-formdesigner/tests/ -k submission -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/services/test_submission_extra_data.py
import json
import uuid
import pytest
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage


def _sub(**kw):
    return FormSubmission(
        form_uid=uuid.uuid4(), form_id="f", form_version="1.0",
        data={"name": "Ana"}, is_valid=True, **kw,
    )


class TestModel:
    def test_extra_data_optional(self):
        assert _sub().extra_data is None

    def test_extra_data_roundtrip(self):
        s = _sub(extra_data={"legacy_id": 42})
        assert FormSubmission(**s.model_dump()).extra_data == {"legacy_id": 42}


class TestSQL:
    @pytest.fixture
    def storage(self):
        return FormSubmissionStorage(pool=object())

    def test_create_table_includes_column(self, storage):
        assert "extra_data JSONB" in storage._create_table_sql(None)

    def test_alter_table_adds_column(self, storage):
        assert "ADD COLUMN IF NOT EXISTS extra_data JSONB" in storage._alter_table_sql(None)

    def test_insert_casts_extra_data(self, storage):
        """The ::text::jsonb cast is mandatory — see :255-273."""
        sql = storage._insert_sql(None)
        assert "$22::text::jsonb" in sql
        assert "extra_data" in sql

    def test_select_columns_includes_extra_data(self, storage):
        assert "extra_data" in storage._SELECT_COLUMNS


class TestRowMapping:
    def _row(self, value):
        return {
            "submission_id": "s", "form_uid": uuid.uuid4(), "form_id": "f",
            "form_version": "1.0", "data": {"name": "Ana"}, "is_valid": True,
            "forwarded": False, "forward_status": None, "forward_error": None,
            "tenant": None, "created_at": None, "user_id": None, "username": None,
            "org_id": None, "submitted_at": None, "ip": None, "user_agent": None,
            "locale": None, "root_submission_id": None, "revision": None,
            "context": None, "extra_data": value,
        }

    def test_dict_passthrough(self):
        s = FormSubmissionStorage._row_to_submission(self._row({"a": 1}))
        assert s.extra_data == {"a": 1}

    def test_json_string_parsed(self):
        """Codec-registered pool hands back a str."""
        s = FormSubmissionStorage._row_to_submission(self._row(json.dumps({"a": 1})))
        assert s.extra_data == {"a": 1}

    def test_null_stays_none_not_empty_dict(self):
        """Spec AC23 — NULL must NOT become {}."""
        s = FormSubmissionStorage._row_to_submission(self._row(None))
        assert s.extra_data is None


class TestStore:
    async def test_serializes_extra_data(self, fake_pool):
        storage = FormSubmissionStorage(pool=fake_pool)
        await storage.store(_sub(extra_data={"legacy_id": 42}))
        assert json.dumps({"legacy_id": 42}) in fake_pool.last_args

    async def test_none_passed_as_none(self, fake_pool):
        storage = FormSubmissionStorage(pool=fake_pool)
        await storage.store(_sub())
        assert fake_pool.last_args[-1] is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-unknown-fields-capture.spec.md` for full context.
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code: confirm each import
   still resolves and each listed signature still has the listed attributes. Line
   numbers were verified on `dev` at `72490fa14` (2026-08-24) and WILL drift once
   FEAT-456/FEAT-457 land — re-`grep` rather than trusting a number.
4. **Update status** in `sdd/tasks/index/formdesigner-unknown-fields-capture.json` → `"in-progress"`.
5. **Implement** following the scope and contract above. Nothing outside scope.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
