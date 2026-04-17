# TASK-746: Feature-wide unit + integration test coverage

**Feature**: FEAT-106 — NavigatorToolkit ↔ PostgresToolkit Interaction
**Spec**: `sdd/specs/navigatortoolkit-postgrestoolkit-interaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-739, TASK-740, TASK-741, TASK-742, TASK-743, TASK-744, TASK-745
**Assigned-to**: unassigned

---

## Context

Each prior task lands a narrow test module adjacent to its
implementation. This task ensures the **spec's full Test Specification
section** (spec §4) is covered, adds integration tests against a live
Postgres (skip-marked if none available), and executes the full matrix
so regressions from module interactions surface before merge.

Implements **Module 8** of the spec.

---

## Scope

### Verify prior coverage

For each test module that TASK-739..744 were supposed to produce,
confirm the file exists AND the listed cases from spec §4 are present.
Add any missing case here rather than retrofitting the earlier task.

Coverage matrix from spec §4:

| Test | Source task | Action |
|---|---|---|
| `test_validate_sql_ast_pk_presence_passes_with_pk_in_where` | TASK-739 | verify |
| `test_validate_sql_ast_pk_presence_rejects_non_pk_where` | TASK-739 | verify |
| `test_validate_sql_ast_pk_presence_accepts_any_pk_of_composite` | TASK-739 | verify |
| `test_validate_sql_ast_pk_presence_backcompat_default_false` | TASK-739 | verify |
| `test_validate_sql_ast_pk_presence_delete` | TASK-739 | verify |
| `test_table_metadata_unique_constraints_default_empty` | TASK-740 | verify |
| `test_sqltoolkit_build_table_metadata_populates_unique` | TASK-740 | verify |
| `test_build_pydantic_model_lru_hits` | TASK-741 | verify |
| `test_build_pydantic_model_rejects_unknown_field` | TASK-741 | verify |
| `test_build_pydantic_model_jsonb_accepts_dict` | TASK-741 | verify |
| `test_build_insert_sql_no_returning` | TASK-742 | verify |
| `test_build_upsert_sql_conflict_cols_default_to_pk` | TASK-742 | verify |
| `test_build_upsert_sql_explicit_conflict_cols` | TASK-742 | verify |
| `test_build_update_sql_jsonb_cast` | TASK-742 | verify |
| `test_build_select_sql_with_where_and_order` | TASK-742 | verify |
| `test_postgres_toolkit_insert_row_whitelist_rejection` | TASK-743 | verify |
| `test_postgres_toolkit_insert_row_validates_input` | TASK-743 | verify |
| `test_postgres_toolkit_upsert_row_uses_cached_template_on_second_call` | TASK-743 | verify |
| `test_postgres_toolkit_update_row_blocks_non_pk_where` | TASK-743 | verify |
| `test_postgres_toolkit_transaction_commits_on_success` | TASK-743 | verify |
| `test_postgres_toolkit_transaction_rolls_back_on_exception` | TASK-743 | verify |
| `test_postgres_toolkit_read_only_hides_write_tools` | TASK-743 | verify |
| `test_postgres_toolkit_read_only_false_exposes_write_tools` | TASK-743 | verify |
| `test_postgres_toolkit_reload_metadata_clears_entries` | TASK-743 | verify |
| `test_navigator_toolkit_init_accepts_dsn_only` | TASK-744 | verify |
| `test_navigator_toolkit_init_rejects_connection_params` | TASK-744 | verify |
| `test_navigator_toolkit_tool_names_unchanged` | TASK-744 | verify (names are now `nav_*`) |
| `test_navigator_toolkit_authorization_still_enforced` | TASK-744 | verify |

### Add integration tests (new file)

- `tests/integration/test_navigator_toolkit_refactor.py`
- Use `pytest.mark.integration` and skip cleanly if `NAVIGATOR_PG_DSN`
  env var is unset.
- Cases:
  - `test_navigator_create_program_end_to_end` — creates a program; verifies
    `auth.programs`, `auth.program_clients`, `auth.program_groups` rows; re-run
    returns `already_existed=True`.
  - `test_navigator_create_module_transaction_atomicity` — force a failure
    after the first `upsert_row` inside `transaction()`; assert all writes
    rolled back (target table row count unchanged).
  - `test_navigator_create_dashboard_returns_dashboard_id` — RETURNING threads
    the UUID back to the caller.
  - `test_navigator_update_widget_pk_required` — success with PK in WHERE;
    manually crafted update without PK (via `execute_query`) rejected.
  - `test_postgres_toolkit_crud_on_fresh_table` — create a scratch table,
    round-trip INSERT/UPSERT/UPDATE/DELETE through the new tools.

### Add scratch-table fixture

```python
# tests/conftest.py (extend, do NOT overwrite existing fixtures)
@pytest.fixture
async def pg_toolkit_with_fixture_table(pg_dsn):
    """Spin up a PostgresToolkit pointing at a scratch table.

    Creates:
        CREATE TABLE test_crud (id SERIAL PRIMARY KEY, name TEXT UNIQUE,
                                 data JSONB DEFAULT '{}');
    Yields a started toolkit; drops the table on teardown.
    """
    ...
```

### Run the acceptance-criteria matrix

After the above, run the full test suite and check against the spec's
Section 5 Acceptance Criteria:

```bash
# Unit
pytest tests/unit/test_query_validator_pk.py \
       tests/unit/test_table_metadata_unique.py \
       tests/unit/test_crud_helpers.py \
       tests/unit/test_postgres_toolkit.py \
       tests/unit/test_navigator_toolkit_refactor.py \
       -v

# Integration (only when NAVIGATOR_PG_DSN set)
pytest tests/integration/ -v -m integration
```

**NOT in scope**:
- Rewriting implementation to pass new tests — if a test reveals a bug,
  file a follow-up task rather than expanding this one.
- Performance benchmarking — out of scope.
- Security tests beyond the spec's stated criteria.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/unit/test_query_validator_pk.py` | VERIFY / EXTEND | Backfill any missing case from the matrix |
| `tests/unit/test_table_metadata_unique.py` | VERIFY / EXTEND | ditto |
| `tests/unit/test_crud_helpers.py` | VERIFY / EXTEND | ditto |
| `tests/unit/test_postgres_toolkit.py` | VERIFY / EXTEND | ditto |
| `tests/unit/test_navigator_toolkit_refactor.py` | VERIFY / EXTEND | ditto |
| `tests/integration/test_navigator_toolkit_refactor.py` | CREATE | Integration tests, `pytest.mark.integration` |
| `tests/conftest.py` | EXTEND | `pg_toolkit_with_fixture_table` + `fake_table_metadata` fixtures |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
from parrot.bots.database.toolkits.postgres import PostgresToolkit
from parrot.bots.database.models import TableMetadata
from parrot.security import QueryValidator
from parrot_tools.navigator import NavigatorToolkit
```

### Existing Signatures to Use

See TASK-739..744 contracts. Nothing new is introduced in this task —
it purely exercises the new surfaces.

### Does NOT Exist

- ~~`pytest.mark.slow` as a project-wide convention~~ — verify; if the
  project uses `pytest.mark.integration` only, don't invent a new marker.
- ~~A built-in `pg_dsn` fixture~~ — you may need to add one to `conftest.py`
  sourcing from `NAVIGATOR_PG_DSN` env var.
- ~~`pg_toolkit_with_fixture_table` fixture today~~ — this task creates it.

---

## Implementation Notes

### Integration test skip pattern

```python
# tests/integration/test_navigator_toolkit_refactor.py
import os
import pytest

pytestmark = pytest.mark.integration

skip_if_no_pg = pytest.mark.skipif(
    not os.getenv("NAVIGATOR_PG_DSN"),
    reason="NAVIGATOR_PG_DSN not set — skipping integration test",
)


@skip_if_no_pg
@pytest.mark.asyncio
async def test_navigator_create_program_end_to_end():
    ...
```

### Force-failure pattern for transaction atomicity

```python
@skip_if_no_pg
@pytest.mark.asyncio
async def test_create_module_transaction_atomicity(navigator_tk):
    """Raising inside `transaction()` rolls back every write."""
    class BoomError(RuntimeError): ...
    with patch.object(navigator_tk, "_second_write_helper", side_effect=BoomError):
        with pytest.raises(BoomError):
            await navigator_tk.create_module(...)
    # Assert target tables are unchanged since start.
    ...
```

### Key Constraints

- Integration tests MUST clean up after themselves (drop created rows,
  `DROP TABLE test_crud` on teardown). A leaked row will make the next
  run flaky.
- Prefer `pytest.mark.asyncio(mode="strict")` conventions if the project
  already uses that; otherwise plain `@pytest.mark.asyncio`.
- When a unit test uses `patch.object` on a CRUD method, pass a
  `pytest.AsyncMock` (pytest 7+) or `unittest.mock.AsyncMock`.
- Do NOT commit `NAVIGATOR_PG_DSN` values — use `os.getenv` with a
  documented placeholder.

### References in Codebase

- `tests/conftest.py` — existing fixture patterns
- `tests/integration/` — existing integration markers and skip patterns

---

## Acceptance Criteria

- [ ] Every test in spec §4 exists (verified file-by-file).
- [ ] `pytest tests/unit/test_query_validator_pk.py tests/unit/test_table_metadata_unique.py tests/unit/test_crud_helpers.py tests/unit/test_postgres_toolkit.py tests/unit/test_navigator_toolkit_refactor.py -v` passes (no failures, no errors).
- [ ] Integration tests skip cleanly when `NAVIGATOR_PG_DSN` is unset.
- [ ] Integration tests pass against a live Postgres (manually verified on maintainer's env; result documented in Completion Note).
- [ ] `pytest tests/unit/test_database_query_toolkit.py -v` (FEAT-105 regression) remains green.
- [ ] Every Section 5 acceptance criterion in the spec is supported by at least one test.

---

## Test Specification

This task doesn't add new test modules beyond what the matrix above
prescribes. Its job is to **close gaps** and **run the suite**.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — Section 4 (Test Specification) is the driving document
2. **Check dependencies** — TASK-739..745 all `done`
3. **Verify the Codebase Contract** — confirm the test files from earlier tasks exist; list gaps
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Backfill missing unit tests** first, then add integration tests, then run the full matrix
6. **Verify** every acceptance criterion
7. **Move this file** to `tasks/completed/TASK-746-feat-106-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below, including the test-run summary

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
