"""Unit tests for the form_uid migration artifacts (FEAT-389, TASK-1975).

`packages/parrot-formdesigner/migrations/` is a plain directory of SQL +
a standalone Python script — NOT a Python package (no `__init__.py`, and
`003_migrate_form_data.py`'s filename isn't a valid module identifier
anyway), so `003_migrate_form_data.py` is loaded via
`importlib.util.spec_from_file_location` rather than a normal import.

No real PostgreSQL is required — `backfill_form_uid()` is exercised
against an in-memory asyncpg-like stub pool, mirroring the pattern used in
`tests/unit/test_storage_form_uid.py`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).parents[2] / "migrations"


def _load_migration_003():
    """Load 003_migrate_form_data.py as a module via its file path."""
    module_path = MIGRATIONS_DIR / "003_migrate_form_data.py"
    spec = importlib.util.spec_from_file_location("migrate_form_data_003", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["migrate_form_data_003"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def migration_003():
    return _load_migration_003()


# ---------------------------------------------------------------------------
# File existence / basic SQL content checks (no DB required)
# ---------------------------------------------------------------------------


def test_migrations_directory_exists() -> None:
    assert MIGRATIONS_DIR.is_dir()


def test_001_add_form_uid_sql_exists_and_idempotent() -> None:
    sql = (MIGRATIONS_DIR / "001_add_form_uid.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS form_uid" in sql
    assert "UPDATE form_schemas SET form_uid = id::text WHERE form_uid IS NULL" in sql
    assert "SET NOT NULL" in sql
    assert "UNIQUE (form_uid, version)" in sql
    assert "UNIQUE (tenant, form_id, version)" in sql
    # Constraint additions must be guarded (idempotent even without
    # `ADD CONSTRAINT IF NOT EXISTS`, which not all PG versions support).
    assert "IF NOT EXISTS" in sql
    assert "pg_constraint" in sql


def test_002_add_form_uid_submissions_sql_exists_and_idempotent() -> None:
    sql = (MIGRATIONS_DIR / "002_add_form_uid_submissions.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS form_uid" in sql
    assert "form_data" in sql and "form_schemas" in sql
    assert "WHERE fd.form_id = fs.form_id" in sql
    assert "fd.form_uid IS NULL" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_form_data_form_uid" in sql


def test_readme_documents_execution_order() -> None:
    readme = (MIGRATIONS_DIR / "README.md").read_text()
    assert "001_add_form_uid.sql" in readme
    assert "002_add_form_uid_submissions.sql" in readme
    assert "003_migrate_form_data.py" in readme
    assert "--dry-run" in readme
    assert "Idempotency" in readme or "idempotent" in readme.lower()


# ---------------------------------------------------------------------------
# 003_migrate_form_data.py — backfill_form_uid() unit tests
# ---------------------------------------------------------------------------


class _StubConn:
    """asyncpg connection stub for backfill_form_uid()'s batched queries.

    `form_data_rows` are consumed one LIMIT-sized batch at a time (FIFO by
    insertion order) to simulate `SELECT ... WHERE form_uid IS NULL LIMIT $1`.
    `schema_lookup` maps form_id -> form_uid for the per-row "find the
    owning form_schemas row" query; a missing key simulates an orphan.
    """

    def __init__(self, form_data_rows, schema_lookup) -> None:
        self._remaining = list(form_data_rows)
        self._schema_lookup = dict(schema_lookup)
        self.executed: list[tuple[str, tuple]] = []
        self.backfilled_ids: list[str] = []

    async def fetch(self, sql: str, limit: int):
        batch = self._remaining[:limit]
        self._remaining = self._remaining[limit:]
        return batch

    async def fetchrow(self, sql: str, form_id: str):
        form_uid = self._schema_lookup.get(form_id)
        if form_uid is None:
            return None
        return {"form_uid": form_uid}

    async def execute(self, sql: str, form_uid: str, row_id: str) -> str:
        self.executed.append((sql, (form_uid, row_id)))
        self.backfilled_ids.append(row_id)
        return "UPDATE 1"


class _StubPool:
    def __init__(self, conn: _StubConn) -> None:
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *args):
                return False

        return _Ctx()


@pytest.mark.asyncio
async def test_backfill_marks_matching_rows(migration_003) -> None:
    """Rows with a matching form_schemas entry get form_uid backfilled."""
    conn = _StubConn(
        form_data_rows=[{"row_id": "sub-1", "form_id": "my-form"}],
        schema_lookup={"my-form": "uid-1"},
    )
    pool = _StubPool(conn)

    report = await migration_003.backfill_form_uid(pool, schema="navigator")

    assert report.backfilled == 1
    assert report.orphaned == []
    assert conn.backfilled_ids == ["sub-1"]


@pytest.mark.asyncio
async def test_backfill_reports_orphans(migration_003) -> None:
    """Rows whose form_id has no form_schemas match are reported as orphans."""
    conn = _StubConn(
        form_data_rows=[{"row_id": "sub-orphan", "form_id": "deleted-form"}],
        schema_lookup={},
    )
    pool = _StubPool(conn)

    report = await migration_003.backfill_form_uid(pool, schema="navigator")

    assert report.backfilled == 0
    assert report.orphaned == ["sub-orphan"]
    assert conn.backfilled_ids == []


@pytest.mark.asyncio
async def test_backfill_dry_run_persists_nothing(migration_003) -> None:
    """--dry-run computes the report but performs zero writes."""
    conn = _StubConn(
        form_data_rows=[{"row_id": "sub-1", "form_id": "my-form"}],
        schema_lookup={"my-form": "uid-1"},
    )
    pool = _StubPool(conn)

    report = await migration_003.backfill_form_uid(pool, schema="navigator", dry_run=True)

    assert report.backfilled == 1
    assert report.dry_run is True
    assert conn.executed == []  # no UPDATE statements issued
    assert conn.backfilled_ids == []


@pytest.mark.asyncio
async def test_backfill_mixed_batch(migration_003) -> None:
    """A batch with both matched and orphaned rows reports both correctly."""
    conn = _StubConn(
        form_data_rows=[
            {"row_id": "sub-1", "form_id": "my-form"},
            {"row_id": "sub-2", "form_id": "deleted-form"},
        ],
        schema_lookup={"my-form": "uid-1"},
    )
    pool = _StubPool(conn)

    report = await migration_003.backfill_form_uid(pool, schema="navigator")

    assert report.backfilled == 1
    assert report.orphaned == ["sub-2"]


def test_migration_report_summary_lists_orphans(migration_003) -> None:
    report = migration_003.MigrationReport(backfilled=2, orphaned=["a", "b"])
    text = report.summary()
    assert "Backfilled: 2" in text
    assert "Orphaned (no matching form_schemas row): 2" in text
    assert "a" in text and "b" in text


def test_arg_parser_requires_dsn_and_schema(migration_003) -> None:
    parser = migration_003._build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_arg_parser_dry_run_flag(migration_003) -> None:
    parser = migration_003._build_arg_parser()
    args = parser.parse_args(
        ["--dsn", "postgresql://x", "--schema", "navigator", "--dry-run"]
    )
    assert args.dry_run is True
    assert args.schema == "navigator"
    assert args.batch_size == migration_003.DEFAULT_BATCH_SIZE


@pytest.mark.asyncio
async def test_main_handles_unreachable_dsn_gracefully(migration_003) -> None:
    """main() with an unparsable DSN exits 1 instead of raising/hanging."""
    exit_code = await migration_003._async_main(
        ["--dsn", "not-a-valid-dsn", "--schema", "navigator", "--dry-run"]
    )
    assert exit_code == 1
