# TASK-738: Tests — DDL guard, AbstractToolkit contract, backcompat

**Feature**: databasetoolkit-clash
**Spec**: `sdd/specs/databasetoolkit-clash.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-733, TASK-734, TASK-735, TASK-736, TASK-737
**Assigned-to**: unassigned

---

## Context

Tests currently live in `packages/ai-parrot-tools/tests/database/` and
import from `parrot.tools.database.*`. After all prior FEAT-105 tasks
land:

- The source moved to `packages/ai-parrot/src/parrot/tools/databasequery/`.
- `parrot.tools.database` is a deprecation shim.
- `DatabaseQueryToolkit` replaces `DatabaseToolkit` and inherits `AbstractToolkit`.
- A `QueryValidator` DDL guard runs before every query method.

This task moves the existing tests to the matching new path, updates
imports, and adds the new coverage required by spec Section 5.

Implements **Module 7** of the spec.

---

## Scope

- Move (`git mv`) `packages/ai-parrot-tools/tests/database/` →
  `packages/ai-parrot/tests/tools/databasequery/` (Q4 default per spec —
  tests follow the source).
- Update every import in the moved files: `parrot.tools.database` →
  `parrot.tools.databasequery`. Affected files (verified via grep):
  `test_abstract_credentials.py`, `test_base_types.py`,
  `test_cache_vector_tier.py`, `test_init_exports.py`,
  `test_integration.py`, `test_registry.py`, `test_sources.py`,
  `test_toolkit.py`.
- Update `tests/database/test_toolkit.py` if it asserted
  `DatabaseToolkit` (rename → `DatabaseQueryToolkit`).
- Add NEW test files under `packages/ai-parrot/tests/tools/databasequery/`:
  - `test_toolkit_ddl_guard.py` — DDL/DML rejection across SQL, Flux, MQL, JSON dialects.
  - `test_toolkit_abstracttoolkit_contract.py` — inherits `AbstractToolkit`, four tools, prefixing, `exclude_tools`.
  - `test_backcompat_shim.py` — `parrot.tools.database` deprecation alias + `parrot_tools.databasequery` re-export.
  - `test_tool_registry.py` — `TOOL_REGISTRY["database_query"]` resolves to the new path.
- Confirm `pytest packages/ai-parrot/tests/tools/databasequery/ -v` discovers and runs all moved + new tests.

**NOT in scope**:
- Touching production code — every prior task owns its files.
- Live-database integration tests (the existing SQLite integration test
  in `test_integration.py` already covers a real DB; preserve it).
- Adding tests for unrelated modules.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/database/` | MOVE | `git mv` → `packages/ai-parrot/tests/tools/databasequery/` |
| `.../databasequery/test_*.py` (each existing file) | MODIFY | Bulk-rewrite imports `parrot.tools.database` → `parrot.tools.databasequery`; rename `DatabaseToolkit` references |
| `packages/ai-parrot/tests/tools/databasequery/test_toolkit_ddl_guard.py` | CREATE | New DDL-guard suite |
| `packages/ai-parrot/tests/tools/databasequery/test_toolkit_abstracttoolkit_contract.py` | CREATE | New AbstractToolkit-contract suite |
| `packages/ai-parrot/tests/tools/databasequery/test_backcompat_shim.py` | CREATE | New deprecation/back-compat suite |
| `packages/ai-parrot/tests/tools/databasequery/test_tool_registry.py` | CREATE | New registry-resolution test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (post-FEAT-105)
```python
from parrot.tools.databasequery import (
    DatabaseQueryToolkit,
    DatabaseQueryTool,
    AbstractDatabaseSource,
    ValidationResult, MetadataResult, QueryResult, RowResult,
)
from parrot.tools.toolkit import AbstractToolkit
from parrot_tools import TOOL_REGISTRY
from parrot._imports import lazy_import
import warnings
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
```

### Existing Signatures to Use
```python
# From spec Section 6 — verified in TASK-733/734/735:
class DatabaseQueryToolkit(AbstractToolkit):
    tool_prefix: str = "db"
    exclude_tools: tuple[str, ...] = ("get_source", "cleanup", "start", "stop")
    async def get_database_metadata(self, driver, credentials=None, tables=None) -> dict
    async def validate_database_query(self, driver, query, credentials=None) -> dict
    async def execute_database_query(self, driver, query, credentials=None, params=None) -> dict
    async def fetch_database_row(self, driver, query, credentials=None, params=None) -> dict

# Existing (unchanged) — packages/ai-parrot/src/parrot/tools/databasequery/sources/sqlite.py
class SQLiteSource(AbstractDatabaseSource):
    driver = "sqlite"
    sqlglot_dialect = "sqlite"
    # used by tests/test_integration.py for real-DB SQLite coverage
```

### Does NOT Exist
- ~~`pytest-asyncio` is not configured in this repo~~ — it IS, all
  existing tests use `@pytest.mark.asyncio`. Verify by reading
  `packages/ai-parrot-tools/conftest.py` or `pyproject.toml`.
- ~~`pytest -W error::DeprecationWarning` is enabled by default~~ — it
  is not. The `parrot.tools.database` shim test must use
  `pytest.warns(DeprecationWarning)` to assert the warning fires.
- ~~`AbstractToolkit.tool_names` attribute~~ — to assert tool names use
  `[t.name for t in toolkit.get_tools()]`, not a phantom property.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/tests/tools/databasequery/test_toolkit_ddl_guard.py
import pytest
from unittest.mock import AsyncMock, patch

from parrot.tools.databasequery import DatabaseQueryToolkit


DDL_QUERIES = [
    "DROP TABLE users",
    "CREATE TABLE t (id int)",
    "TRUNCATE TABLE users",
    "INSERT INTO users VALUES (1)",
    "UPDATE users SET x = 1",
    "DELETE FROM users",
    "GRANT ALL ON users TO x",
    "EXEC sp_foo",
]


@pytest.fixture
def toolkit():
    return DatabaseQueryToolkit()


class TestDDLGuard:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_query", DDL_QUERIES)
    async def test_validate_rejects_ddl(self, toolkit, bad_query):
        result = await toolkit.validate_database_query(driver="pg", query=bad_query)
        assert result["valid"] is False
        assert result["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_query", DDL_QUERIES)
    async def test_execute_rejects_ddl_before_source(self, toolkit, bad_query):
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            mock_get_source.return_value = mock_source
            result = await toolkit.execute_database_query(driver="pg", query=bad_query)
        assert result["valid"] is False
        mock_source.query.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_passes_select(self, toolkit):
        # Patch the source's syntactic validate_query so we don't need a real DB
        with patch.object(toolkit, "get_source") as mock_get_source:
            mock_source = AsyncMock()
            from parrot.tools.databasequery import ValidationResult
            mock_source.validate_query = AsyncMock(
                return_value=ValidationResult(valid=True, dialect="postgres")
            )
            mock_get_source.return_value = mock_source
            result = await toolkit.validate_database_query(
                driver="pg", query="SELECT 1"
            )
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_flux_drop_rejected(self, toolkit):
        # InfluxDB Flux — drop bucket should fail safety
        result = await toolkit.validate_database_query(
            driver="influx", query="drop(bucket: \"my-bucket\")",
        )
        assert result["valid"] is False
```

```python
# test_toolkit_abstracttoolkit_contract.py
from parrot.tools.databasequery import DatabaseQueryToolkit
from parrot.tools.toolkit import AbstractToolkit


class TestAbstractToolkitContract:
    def test_inherits_abstract_toolkit(self):
        assert isinstance(DatabaseQueryToolkit(), AbstractToolkit)

    def test_tool_count_is_four(self):
        assert len(DatabaseQueryToolkit().get_tools()) == 4

    def test_tool_names_prefixed(self):
        tk = DatabaseQueryToolkit()
        names = {t.name for t in tk.get_tools()}
        assert names == {
            "db_get_database_metadata",
            "db_validate_database_query",
            "db_execute_database_query",
            "db_fetch_database_row",
        }

    def test_excluded_methods_hidden(self):
        names = {t.name for t in DatabaseQueryToolkit().get_tools()}
        assert "get_source" not in names
        assert "db_get_source" not in names
        assert "cleanup" not in names
```

```python
# test_backcompat_shim.py
import warnings
import pytest


def test_database_deprecation_alias():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # Re-import to force fresh execution path
        import importlib
        import sys
        sys.modules.pop("parrot.tools.database", None)
        from parrot.tools.database import DatabaseToolkit
    assert any(
        issubclass(w.category, DeprecationWarning)
        and "parrot.tools.databasequery" in str(w.message)
        for w in caught
    )
    from parrot.tools.databasequery import DatabaseQueryToolkit
    assert DatabaseToolkit is DatabaseQueryToolkit


def test_databasequery_shim_preserves_tool():
    from parrot_tools.databasequery import (
        DatabaseQueryTool, DriverInfo, DatabaseQueryArgs,
        QueryLanguage, QueryValidator,
    )
    assert DatabaseQueryTool.__name__ == "DatabaseQueryTool"
```

```python
# test_tool_registry.py
def test_tool_registry_database_query_path():
    from parrot_tools import TOOL_REGISTRY
    from parrot._imports import lazy_import
    assert TOOL_REGISTRY["database_query"] == "parrot.tools.databasequery.DatabaseQueryTool"
    cls = lazy_import(TOOL_REGISTRY["database_query"])
    assert cls.__name__ == "DatabaseQueryTool"
    assert cls.__module__.startswith("parrot.tools.databasequery")
```

### Key Constraints

- Do NOT delete the `tests/database/` directory before confirming the
  move completed cleanly. Use `git mv` so history is preserved.
- For DDL tests across non-SQL dialects: only assert the safety check
  fires; do NOT assert specific error wording (the wording comes from
  `QueryValidator` and may evolve).
- Mock at the `toolkit.get_source` layer — never against a real
  database. The single live-DB test stays in `test_integration.py`
  (SQLite, in-memory).
- Run each new test file in isolation first (`pytest -k <test_name>`)
  to confirm zero hidden ordering dependencies before running the full
  suite.

### References in Codebase

- Spec Sections 4 + 5 — full test list and acceptance criteria.
- `packages/ai-parrot-tools/conftest.py` — confirms pytest-asyncio
  configuration before relying on `@pytest.mark.asyncio`.

---

## Acceptance Criteria

- [ ] Directory `packages/ai-parrot-tools/tests/database/` no longer exists.
- [ ] Directory `packages/ai-parrot/tests/tools/databasequery/` exists with all moved test files plus the four new files.
- [ ] `grep -rn "parrot\.tools\.database\b" packages/ai-parrot/tests/tools/databasequery/` returns zero matches (only `databasequery` references remain).
- [ ] `pytest packages/ai-parrot/tests/tools/databasequery/ -v` passes.
- [ ] `test_validate_rejects_ddl` exercises every entry in `DDL_QUERIES`.
- [ ] `test_execute_rejects_ddl_before_source` proves the source mock's `query` method is NEVER called when the validator blocks.
- [ ] `test_database_deprecation_alias` asserts the warning fires AND the alias resolves to `DatabaseQueryToolkit`.
- [ ] `test_tool_registry_database_query_path` asserts the new registry path.

---

## Test Specification

(Tests ARE the deliverable — see Implementation Notes for canonical patterns above.)

---

## Agent Instructions

1. Confirm TASK-733/734/735/736/737 are all in `sdd/tasks/completed/`.
2. Run the bulk move + import sweep, then add the four new test files.
3. Run `pytest packages/ai-parrot/tests/tools/databasequery/ -v` until green.
4. Move file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*
