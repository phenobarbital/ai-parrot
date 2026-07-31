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

import asyncio
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


def test_001_add_form_uid_sql_guards_are_schema_scoped() -> None:
    """Regression (code review): the file's own header documents running
    this migration once PER PHYSICAL SCHEMA (epson.form_schemas,
    pokemon.form_schemas, ...). An unscoped `WHERE table_name = '...'` /
    `WHERE conname = '...'` guard would see ANY schema's already-migrated
    table/constraint and silently skip a DIFFERENT, not-yet-migrated
    schema's own Step 3/4/5 — leaving that schema's form_uid nullable and
    unconstrained. Every idempotency guard must scope to the schema
    actually resolved by search_path at run time.
    """
    sql = (MIGRATIONS_DIR / "001_add_form_uid.sql").read_text()
    assert "table_schema = current_schema()" in sql
    assert "conrelid = 'form_schemas'::regclass" in sql
    # Both constraint guards (Step 4 and Step 5) must be scoped, not just
    # one — each ADD CONSTRAINT's own DO block needs its own IF NOT EXISTS
    # check against pg_constraint filtered by conrelid.
    assert sql.count("WHERE conrelid = 'form_schemas'::regclass") == 2


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

    Models real Postgres semantics closely enough to catch the class of bug
    an earlier version of this stub masked: rows only leave the
    `WHERE form_uid IS NULL` result set once actually WRITTEN (never for
    orphans, never in `--dry-run` mode). `fetch()` re-evaluates that
    predicate — plus the keyset cursor (`fd.id > $last_id`) the real query
    now uses — on every call, so a stub that just "consumed" a fixed list
    up front (regardless of write outcome) would let a genuinely-infinite
    production loop pass silently. `schema_lookup` maps form_id -> form_uid
    for the per-row "find the owning form_schemas row" query; a missing key
    simulates an orphan.
    """

    def __init__(self, form_data_rows, schema_lookup) -> None:
        # row_id -> {"form_id": ..., "form_uid": None}
        self._rows: dict[str, dict] = {
            row["row_id"]: {"form_id": row["form_id"], "form_uid": None}
            for row in form_data_rows
        }
        self._schema_lookup = dict(schema_lookup)
        self.executed: list[tuple[str, tuple]] = []
        self.backfilled_ids: list[str] = []
        self.fetch_call_count = 0

    async def fetch(self, sql: str, *args):
        """Simulate both call shapes `backfill_form_uid()` issues:
        `fetch(sql, limit)` on the first page, `fetch(sql, last_id, limit)`
        on every subsequent page.
        """
        self.fetch_call_count += 1
        if len(args) == 1:
            (limit,) = args
            last_id = None
        else:
            last_id, limit = args

        candidates = sorted(
            row_id
            for row_id, data in self._rows.items()
            if data["form_uid"] is None and (last_id is None or row_id > last_id)
        )
        page = candidates[:limit]
        return [
            {"row_id": row_id, "form_id": self._rows[row_id]["form_id"]}
            for row_id in page
        ]

    async def fetchrow(self, sql: str, form_id: str):
        form_uid = self._schema_lookup.get(form_id)
        if form_uid is None:
            return None
        return {"form_uid": form_uid}

    async def execute(self, sql: str, form_uid: str, row_id: str) -> str:
        self.executed.append((sql, (form_uid, row_id)))
        self.backfilled_ids.append(row_id)
        self._rows[row_id]["form_uid"] = form_uid
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


@pytest.mark.asyncio
async def test_backfill_all_orphans_multi_batch_terminates(migration_003) -> None:
    """Regression test: an all-orphan run spanning multiple batches must
    terminate. Orphaned rows are never written, so a plain re-fetch of
    `WHERE form_uid IS NULL` (with no keyset cursor) would return the SAME
    batch forever — this used to hang indefinitely against a real database
    (confirmed via code review). Guarded by asyncio.wait_for so a
    regression fails fast instead of hanging the test suite.
    """
    conn = _StubConn(
        form_data_rows=[
            {"row_id": f"sub-{i}", "form_id": "deleted-form"} for i in range(5)
        ],
        schema_lookup={},  # every row is an orphan
    )
    pool = _StubPool(conn)

    report = await asyncio.wait_for(
        migration_003.backfill_form_uid(pool, schema="navigator", batch_size=2),
        timeout=2.0,
    )

    assert report.backfilled == 0
    assert sorted(report.orphaned) == [f"sub-{i}" for i in range(5)]
    # 5 orphans / batch_size=2 -> 3 pages, then one empty page to stop.
    assert conn.fetch_call_count == 4


@pytest.mark.asyncio
async def test_backfill_dry_run_multi_batch_terminates(migration_003) -> None:
    """Regression test: `--dry-run` never writes, so a plain re-fetch of
    `WHERE form_uid IS NULL` would return the SAME rows forever whenever
    ANY row in the run matches — this used to hang indefinitely on
    essentially any real, non-empty dataset in dry-run mode (confirmed via
    code review). Guarded by asyncio.wait_for so a regression fails fast.
    """
    conn = _StubConn(
        form_data_rows=[
            {"row_id": f"sub-{i}", "form_id": "my-form"} for i in range(5)
        ],
        schema_lookup={"my-form": "uid-1"},  # every row matches
    )
    pool = _StubPool(conn)

    report = await asyncio.wait_for(
        migration_003.backfill_form_uid(
            pool, schema="navigator", batch_size=2, dry_run=True
        ),
        timeout=2.0,
    )

    assert report.backfilled == 5
    assert report.orphaned == []
    assert conn.executed == []  # dry-run: zero writes, but still terminates
    assert conn.fetch_call_count == 4


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
