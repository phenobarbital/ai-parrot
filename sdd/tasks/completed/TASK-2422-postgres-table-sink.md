# TASK-2422: `PostgresTableSink` - write, read, list, provision, extend

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2418, TASK-2419, TASK-2420
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 6

---

## Context

The reference sink and the only v1 backend with the full capability set. It is
also where the additive-provisioning guarantee is actually enforced, so its generated SQL is
the thing to get right: `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, and
**never** `DROP` or `RENAME`.

Implements spec section 3 Module 6.

---

## Scope

- Create `services/sinks/postgres_table.py` with `PostgresTableSink(AbstractSubmissionSink)`.
- Declare capabilities `{WRITE, READ, LIST, PROVISION, EXTEND}`.
- Implement `ensure_target(form)`: `CREATE TABLE IF NOT EXISTS` from `column_names_for(form)`, then additive `ADD COLUMN IF NOT EXISTS` for columns the table lacks. Index `form_uid` and `root_submission_id`.
- Raise `SinkTargetMismatchError` when an existing column's type is incompatible with the value the form will send.
- Implement `write(submission, payload)` inserting one row; return `submission_id`.
- Implement `read(submission_id)` and `list_revisions(root_submission_id)` returning `FormSubmission` objects.
- Resolve the DSN through `SinkAliasRegistry.resolve_dsn`; own the asyncpg pool and close it in `close()`.
- Map connection/transport failures to `SinkUnavailableError`.
- Write unit tests in `tests/unit/test_postgres_table_sink.py` using a fake pool that records executed SQL.

**NOT in scope**: Registration in the dispatch table (TASK-2426). Coordinate-immutability checks (TASK-2426). The generic `FormSubmissionStorage` - leave it untouched. Any handler wiring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/postgres_table.py` | CREATE | Postgres table sink |
| `packages/parrot-formdesigner/tests/unit/test_postgres_table_sink.py` | CREATE | Unit tests with a fake pool |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.
>
> Verified against `dev` on 2026-08-24. All paths are relative to the repo root.
> Line numbers shift as soon as anything above them changes — **re-`grep` before editing**.

### Verified Imports

```python
# Verified to resolve today:
from parrot_formdesigner.services._identifiers import validate_identifier, qualified_table
                                                      # services/_identifiers.py:24, :45
from parrot_formdesigner.services.submissions import FormSubmission   # services/submissions.py:50
from parrot_formdesigner.core.schema import FormSchema               # core/schema.py:313
# Created by earlier tasks in this spec:
from parrot_formdesigner.core.persistence import SinkCapability, PostgresTableTarget  # TASK-2417
from parrot_formdesigner.services.sinks.base import (                                 # TASK-2419
    AbstractSubmissionSink, SinkUnavailableError, SinkTargetMismatchError,
)
from parrot_formdesigner.services.sinks.mapper import (                               # TASK-2420
    flatten_submission, column_names_for,
)
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry               # TASK-2418
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:118 - PLAIN class, NOT an ABC.
# Copy these two SQL builders' shape; do NOT subclass or modify this class.
class FormSubmissionStorage:
    def _create_table_sql(self, tenant: str | None) -> str: ...  # line 173  <- DDL template
    def _alter_table_sql(self, tenant: str | None) -> str: ...   # line 216  <- ADDITIVE-migration precedent
    def _insert_sql(self, tenant: str | None) -> str: ...        # line 254
    def _resolve_schema(self, tenant: str | None) -> str: ...    # line 159
    def _qualified(self, tenant: str | None) -> str: ...         # line 166
# Module-level constants (NOT class attributes):
DEFAULT_SCHEMA = "navigator"   # line 31
DEFAULT_TABLE = "form_data"    # line 32
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py:178 - READ THIS COMMENT BEFORE WRITING ANY JSONB PARAMETER.
def _upsert_sql(self, tenant: str | None) -> str: ...
#   Use `$n::text::jsonb`, NEVER `$n::jsonb`: a host-provided pool may register a
#   json/jsonb codec (encoder=json.dumps), and a `::jsonb`-typed parameter is then
#   re-encoded by that codec, storing a double-encoded jsonb STRING instead of an
#   object (`jsonb_typeof = 'string'`, every `->>'key'` read returns NULL).

# packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:380 - row -> model conversion idiom to mirror
@staticmethod
def _row_to_submission(row: Any) -> FormSubmission: ...
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/_identifiers.py
def validate_identifier(value: str, *, kind: str = "identifier") -> str: ...  # line 24
def qualified_table(schema: str, table: str) -> str: ...                      # line 45
_IDENTIFIER_RE = r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"                           # line 21
```

### Does NOT Exist

- ~~`AbstractSubmissionSink` / `FormSubmissionSink` / `SubmissionSink`~~ - no sink abstraction exists anywhere in `parrot-formdesigner` before TASK-2419. `FormSubmissionStorage` (`packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:118`) is a **plain class, NOT an ABC** - there is no existing interface to implement.
- ~~`FormSubmissionStorage.DEFAULT_SCHEMA`~~ / ~~`PostgresFormStorage.DEFAULT_SCHEMA`~~ as **class attributes** - they are **module-level** constants (`services/submissions.py:31-32`, `services/storage.py:65-66`), despite the dotted form used in the `FormRegistry.__init__` docstring (`services/registry.py:293`).
- ~~`PostgresFormStorage` auto-creating its schema~~ - it explicitly does NOT (`packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py:80-82`: *"The target schema is assumed to exist"*). This sink deliberately departs from that convention; the departure is sanctioned by spec section 2 and bounded by the alias allowlist plus the additive-only rule.
- ~~`asyncdb` for this sink~~ - use `asyncpg` directly, mirroring `PostgresFormStorage` (`packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py:102` takes `pool` / `dsn` / `min_size` / `max_size`). The `asyncdb` route is TASK-2423's job.
- ~~a shared connection pool with `FormSubmissionStorage`~~ - the generic storage's pool belongs to the host app and points at a different database. Own your pool.

---

## Implementation Notes

### Pattern to Follow

DDL templated on `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:173`, extension on `:216`:

```python
def _create_table_sql(self) -> str:
    qt = qualified_table(self._target.schema_name, self._target.table)
    return f"""
    CREATE TABLE IF NOT EXISTS {qt} (
        submission_id VARCHAR(255) PRIMARY KEY,
        form_uid UUID NOT NULL,
        ...                       -- reserved columns
        <form columns>            -- from column_names_for(form)
    );
    CREATE INDEX IF NOT EXISTS ... ON ...(form_uid);
    """

def _add_column_sql(self, column: str, sql_type: str) -> str:
    qt = qualified_table(self._target.schema_name, self._target.table)
    validate_identifier(column, kind="column")
    return f'ALTER TABLE {qt} ADD COLUMN IF NOT EXISTS "{column}" {sql_type}'
```

### Key Constraints

- Generated SQL must NEVER contain `DROP` or `RENAME`. Assert this in a test over the generated strings.
- Every identifier goes through `validate_identifier()` / `qualified_table()` before interpolation - identifiers cannot be parameterised; this is the injection boundary.
- Use `$n::text::jsonb` for JSON parameters, never `$n::jsonb` (see the signature note).
- Values are always passed as bound parameters, never interpolated.
- `ensure_target` must be idempotent and safe to call before every write.
- Connection failures become `SinkUnavailableError` - the handler turns that into 503.
- Async throughout; `self.logger` at provision, extend and failure points.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:173` - DDL template
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:216` - additive ALTER precedent
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:254` - INSERT shape
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:380` - row -> `FormSubmission`
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py:178` - the `::text::jsonb` codec trap
- `packages/parrot-formdesigner/tests/test_submission_jsonb_shape.py` - existing JSONB assertions to model tests on

---

## Acceptance Criteria

- [ ] `capabilities == frozenset({WRITE, READ, LIST, PROVISION, EXTEND})`
- [ ] `_create_table_sql()` contains `CREATE TABLE IF NOT EXISTS` and quoted identifiers
- [ ] No generated statement contains `DROP` or `RENAME` (asserted over all SQL builders)
- [ ] Adding a field to the form produces an `ADD COLUMN IF NOT EXISTS` on the next `ensure_target`
- [ ] Removing a field produces NO statement at all (the column is left alone)
- [ ] An incompatible existing column type raises `SinkTargetMismatchError`
- [ ] JSON parameters use `::text::jsonb` (asserted on the generated SQL)
- [ ] A simulated connection failure raises `SinkUnavailableError`
- [ ] `write()` -> `read()` round-trips a `FormSubmission`
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_postgres_table_sink.py -v` passes
- [ ] `ruff` and `mypy` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_postgres_table_sink.py
import pytest

from parrot_formdesigner.core.persistence import SinkCapability
from parrot_formdesigner.services.sinks.base import (
    SinkTargetMismatchError, SinkUnavailableError,
)


class TestDDL:
    def test_create_is_idempotent_sql(self, sink):
        assert "CREATE TABLE IF NOT EXISTS" in sink._create_table_sql()

    def test_no_destructive_sql_anywhere(self, sink):
        for sql in sink._all_sql_for_test():
            assert "DROP" not in sql.upper()
            assert "RENAME" not in sql.upper()

    def test_jsonb_uses_text_cast(self, sink):
        assert "::text::jsonb" in sink._insert_sql()

    async def test_new_field_adds_column(self, sink, fake_pool, form_with_extra_field):
        await sink.ensure_target(form_with_extra_field)
        assert any("ADD COLUMN IF NOT EXISTS" in s for s in fake_pool.executed)

    async def test_removed_field_emits_nothing(self, sink, fake_pool, form_with_fewer_fields):
        fake_pool.executed.clear()
        await sink.ensure_target(form_with_fewer_fields)
        assert not any("DROP" in s.upper() for s in fake_pool.executed)


class TestFailure:
    async def test_connection_error_maps_unavailable(self, sink_with_broken_pool, submission):
        with pytest.raises(SinkUnavailableError):
            await sink_with_broken_pool.write(submission, {})

    async def test_type_mismatch_raises(self, sink_with_int_column, form_sending_text):
        with pytest.raises(SinkTargetMismatchError):
            await sink_with_int_column.ensure_target(form_sending_text)


class TestCapabilities:
    def test_full_capability_set(self, sink):
        assert sink.capabilities == frozenset({
            SinkCapability.WRITE, SinkCapability.READ, SinkCapability.LIST,
            SinkCapability.PROVISION, SinkCapability.EXTEND,
        })
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** - verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** - before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
4. **Update status** in `sdd/tasks/index/formbuilder-formschema-persistency.json` ->
   `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** -> `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-24
**Notes**: Implemented `PostgresTableSink` (full capability set). DDL
templated on `FormSubmissionStorage`'s DDL/ALTER precedent: idempotent
`CREATE TABLE IF NOT EXISTS` for the reserved columns, additive
`ADD COLUMN IF NOT EXISTS` per new form field via
`information_schema.columns` introspection, raising
`SinkTargetMismatchError` on an incompatible existing column type (a small
local `FieldType -> (ddl_type, compatible information_schema types)` map).
`_insert_sql`/`write()` use `$n::text::jsonb` for `context` and any
ARRAY-typed form column. Pool is lazily created via `asyncpg.create_pool`
(lazy runtime import, mirroring `PostgresFormStorage`), or injected
directly for tests; connection/query failures map to
`SinkUnavailableError`. `read`/`list_revisions` reconstruct a
`FormSubmission` by folding non-reserved columns back into `data`.
11 unit tests in `tests/unit/test_postgres_table_sink.py` using a fake
pool/conn double that records executed SQL and simulates
`information_schema.columns`/`fetchrow`/`fetch` — covering DDL shape, no
`DROP`/`RENAME` anywhere, `::text::jsonb` usage, additive column addition,
no-op on field removal, connection-failure mapping, type-mismatch
detection, and a write/read round trip. `ruff` and targeted `mypy` clean.

**Deviations from spec**: Duplicated a small local
`_walk_field_types`/`_field_types_for` traversal in this file instead of
importing `services/sinks/mapper.py`'s private walker, to keep this
sink's file self-contained per the task's own file boundary (only
`column_names_for` and `flatten_submission` are the mapper's public
surface per the Codebase Contract).
