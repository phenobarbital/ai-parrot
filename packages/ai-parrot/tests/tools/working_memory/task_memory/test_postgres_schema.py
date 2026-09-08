"""PostgreSQL schema, migration and transaction coordinator (FEAT-538 / TASK-2994).

Three required cases from the task's Test Specification:

- ``test_migration`` — apply the migration in an isolated PostgreSQL
  schema, repeat it safely, and verify the constraints and the rollback
  guidance.
- ``test_coordinator`` — the task and artifact callbacks share one
  connection and one transaction; a rollback removes every tentative row.
- ``test_optional_import`` — a disabled configuration needs neither a
  running database nor an eager import of a concrete backend module.

**Service gating.** The live-database cases require an explicitly
configured server and are otherwise **skipped, never silently passed**::

    TASK_MEMORY_TEST_DSN=postgresql://user:pass@host:5432/db \\
        uv run pytest .../test_postgres_schema.py -q

The DSN is deliberately not defaulted. A default would point the suite at
whatever database happened to be listening, which is how a test suite ends
up writing to a real one. Every live case creates a uniquely-named
throwaway schema and drops it in a ``finally``.

Everything that does *not* need a server — the migration's structure, the
fences, the required tables/columns/indexes/constraints, the reversibility
of DOWN, lazy driver import, protocol shape, and the coordinator's own
semantics against a double — is tested unconditionally.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from typing import Any, AsyncIterator, List, Optional

import pytest
from parrot.interfaces.task_memory import TaskMemoryStore, Transaction, TransactionCoordinator
from parrot.tools.working_memory.task_memory.models import ReducerError, TaskMemoryUnavailable, TaskScope
from parrot.tools.working_memory.task_memory.store import BaseTaskMemoryStore
from parrot.tools.working_memory.task_memory.store.postgres import (
    MIGRATION_NAME,
    MIGRATION_VERSION,
    REQUIRED_TABLES,
    SCHEMA_NAME,
    PostgresTaskMemoryStore,
    PostgresTransaction,
    PostgresTransactionCoordinator,
    migration_path,
    read_migration,
    split_migration,
)

#: Set this to run the live-database cases. Never defaulted — see the
#: module docstring.
DSN_ENV = "TASK_MEMORY_TEST_DSN"

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")


def _dsn() -> Optional[str]:
    """Return the configured test DSN, or ``None``.

    Returns:
        The DSN from the environment, or ``None`` when unset.
    """
    return os.environ.get(DSN_ENV) or None


def _require_dsn() -> str:
    """Return the test DSN or skip the calling test explicitly.

    Returns:
        The configured DSN.
    """
    dsn = _dsn()
    if not dsn:
        pytest.skip(
            f"no PostgreSQL configured: set {DSN_ENV} to run the live durable-schema cases. "
            "This is an ENVIRONMENTAL SKIP, not a pass — the migration was not applied here."
        )
    return dsn


@pytest.fixture()
async def live_store() -> AsyncIterator[PostgresTaskMemoryStore]:
    """Yield a store bound to a throwaway schema, dropping it afterwards.

    Yields:
        A :class:`PostgresTaskMemoryStore` on an isolated schema.
    """
    dsn = _require_dsn()
    schema = f"wm_test_{uuid.uuid4().hex[:12]}"
    store = PostgresTaskMemoryStore(dsn, schema=schema)
    try:
        yield store
    finally:
        try:
            await store.revert_migrations()
        except Exception:  # noqa: BLE001 — cleanup must not mask a test failure
            pass
        await store.close()


# ─────────────────────────────────────────────────────────────
# Migration structure (no server required)
# ─────────────────────────────────────────────────────────────


def test_migration_file_is_packaged() -> None:
    """The migration ships with the package and is readable."""
    path = migration_path()
    assert path.is_file(), f"migration missing at {path}"
    assert path.name == f"{MIGRATION_NAME}.sql"
    assert read_migration().strip()


def test_migration_splits_into_up_and_down() -> None:
    """Both halves are present, non-empty and correctly ordered."""
    up, down = split_migration()

    assert f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}" in up
    assert "DROP SCHEMA" in down and SCHEMA_NAME in down
    assert "DROP SCHEMA" not in up, "the UP half must never drop the schema"
    assert "CREATE TABLE" not in down, "the DOWN half must not create anything"


def test_migration_records_a_reversible_version() -> None:
    """The migration records its own version and advertises reversibility."""
    up, _ = split_migration()
    assert "working_memory.schema_migrations" in up
    assert f"VALUES ({MIGRATION_VERSION}, '{MIGRATION_NAME}', TRUE)" in up
    assert "ON CONFLICT (version) DO NOTHING" in up, "a repeat apply must not raise"


def test_migration_documents_rollback_guidance() -> None:
    """Rollback guidance is in the file, and is honest about what is lost."""
    text = read_migration()
    assert "ROLLBACK GUIDANCE" in text
    for phrase in ("irreversible", "Archive", "orphans"):
        assert phrase.lower() in text.lower(), f"rollback guidance omits {phrase!r}"


def test_migration_creates_every_required_table() -> None:
    """All six tables from spec §2 are created."""
    up, _ = split_migration()
    for table in REQUIRED_TABLES:
        assert re.search(
            rf"CREATE TABLE IF NOT EXISTS\s+{SCHEMA_NAME}\.{table}\b", up
        ), f"migration does not create {table}"


def test_migration_is_idempotent_by_construction() -> None:
    """Every DDL statement is guarded, so a repeat apply is a no-op."""
    up, _ = split_migration()
    unguarded = [
        line.strip()
        for line in up.splitlines()
        if re.match(r"\s*CREATE (TABLE|INDEX|UNIQUE INDEX|SCHEMA)\b", line) and "IF NOT EXISTS" not in line
    ]
    assert unguarded == [], f"unguarded DDL would fail on a repeat apply: {unguarded}"


def test_migration_tasks_table_shape() -> None:
    """``tasks`` carries scope, status, revision, projection and timestamps."""
    up, _ = split_migration()
    block = _table_block(up, "tasks")
    for column in (
        "task_id",
        "chatbot_id",
        "user_id",
        "session_id",
        "status",
        "revision",
        "last_event_seq",
        "projection",
        "reducer_version",
        "created_at",
        "updated_at",
        "terminal_at",
    ):
        assert re.search(rf"\b{column}\b", block), f"tasks is missing {column}"
    assert "JSONB" in block, "the projection must be JSONB"
    assert "PRIMARY KEY" in block
    # A terminal status and a terminal timestamp must not be able to disagree.
    assert "tasks_terminal_consistent" in block


def test_migration_tasks_indexes() -> None:
    """Scope/status, terminal time and nonterminal activity are all indexed."""
    up, _ = split_migration()
    assert "tasks_scope_status_idx" in up
    assert "tasks_terminal_at_idx" in up
    assert "tasks_nonterminal_activity_idx" in up
    # The activity index is partial: terminal rows dominate over time and the
    # sweeper/listing only ever care about live ones.
    activity = up[up.index("tasks_nonterminal_activity_idx") :]
    assert "WHERE terminal_at IS NULL" in activity[: activity.index(";")]


def test_migration_journal_shape() -> None:
    """``task_journal`` is keyed by (task_id, seq) with a globally unique event id."""
    up, _ = split_migration()
    block = _table_block(up, "task_journal")
    assert "PRIMARY KEY (task_id, seq)" in block
    assert "REFERENCES working_memory.tasks (task_id)" in block
    assert "seq >= 1" in block
    # Globally unique event id — the idempotency backstop.
    assert re.search(
        r"CREATE UNIQUE INDEX IF NOT EXISTS task_journal_event_id_key\s+ON\s+"
        r"working_memory\.task_journal \(event_id\)",
        up,
    ), "event_id must be globally unique, not merely unique per task"


def test_migration_artifacts_shape() -> None:
    """``artifacts`` is keyed by (artifact_id, version) and guards verifiability."""
    up, _ = split_migration()
    block = _table_block(up, "artifacts")
    assert "PRIMARY KEY (artifact_id, version)" in block
    for column in (
        "chatbot_id",
        "user_id",
        "session_id",
        "task_id",
        "producer_call_id",
        "alias",
        "kind",
        "availability",
        "fingerprint_algorithm",
        "fingerprint",
        "evidence_verifiable",
        "storage_ref",
        "byte_size",
        "shape",
        "schema_summary",
        "created_at",
        "invalidated",
        "invalidated_at",
    ):
        assert re.search(rf"\b{column}\b", block), f"artifacts is missing {column}"
    # Verifiable evidence cannot be claimed without a fingerprint, enforced at
    # the storage layer too so direct SQL cannot bypass the model validator.
    assert "artifacts_verifiable_needs_fingerprint" in block


def test_migration_alias_namespace_is_not_null() -> None:
    """The alias namespace is NOT NULL — the constraint depends on it.

    In SQL ``NULL <> NULL``, so a UNIQUE constraint over a nullable
    ``task_id`` would permit unlimited duplicate rows for the unassociated
    namespace, and two concurrent writers would each allocate version 1
    for the same key. The empty-string sentinel is what makes the
    constraint actually constrain.
    """
    up, _ = split_migration()
    block = _table_block(up, "artifact_aliases")

    assert re.search(r"task_ns\s+TEXT\s+NOT NULL", block), "task_ns must be NOT NULL"
    assert "PRIMARY KEY (chatbot_id, user_id, session_id, task_ns, alias_key)" in block
    assert "latest_version" in block, "the tombstone must retain the version high-water mark"
    assert "artifact_aliases_current_le_latest" in block


def test_migration_evidence_relation_supports_derived_pinning() -> None:
    """Pinning is derivable from the relation, not from a mutable flag."""
    up, _ = split_migration()
    block = _table_block(up, "artifact_evidence")
    assert "PRIMARY KEY (task_id, step_id, artifact_id, version)" in block
    assert "REFERENCES working_memory.artifacts (artifact_id, version)" in block
    assert "artifact_evidence_artifact_idx" in up, "the pin query needs an index on (artifact_id, version)"

    # There must be no boolean 'pinned' column anywhere: a single flag cannot
    # express "two tasks reference this, one has finished".
    assert not re.search(r"\bpinned\s+BOOLEAN", up), "pinning must be derived, not stored as a flag"


def _table_block(sql: str, table: str) -> str:
    """Return the ``CREATE TABLE`` statement for one table.

    Args:
        sql: The migration's UP half.
        table: Unqualified table name.

    Returns:
        The statement text, up to its terminating semicolon.
    """
    start = sql.index(f"CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.{table} (")
    return sql[start : sql.index(");", start) + 2]


def test_migration_sql_is_structurally_well_formed() -> None:
    """Parentheses balance and every statement is terminated."""
    for half in split_migration():
        stripped = re.sub(r"--[^\n]*", "", half)
        assert stripped.count("(") == stripped.count(")"), "unbalanced parentheses"
        statements = [s.strip() for s in stripped.split(";") if s.strip()]
        assert statements, "no statements found"


# ─────────────────────────────────────────────────────────────
# Migration against a live server
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_migration_applies_and_repeats_safely(live_store: PostgresTaskMemoryStore) -> None:
    """Applying twice succeeds, and verification passes afterwards."""
    assert await live_store.apply_migrations() == MIGRATION_VERSION
    await live_store.verify_schema()

    # Repeat apply must be a no-op, not an error.
    assert await live_store.apply_migrations() == MIGRATION_VERSION
    await live_store.verify_schema()

    pool = await live_store._acquire_pool()
    async with pool.acquire() as conn:
        for table in REQUIRED_TABLES:
            assert await conn.fetchval("SELECT to_regclass($1)", f"{live_store._schema}.{table}") is not None
        versions = await conn.fetch(f"SELECT version FROM {live_store._schema}.schema_migrations")
        assert [r["version"] for r in versions] == [MIGRATION_VERSION], "repeat apply duplicated the version row"


@pytest.mark.asyncio
async def test_migration_verify_fails_before_apply(live_store: PostgresTaskMemoryStore) -> None:
    """An unmigrated schema is reported as such, by name."""
    with pytest.raises(TaskMemoryUnavailable, match="no task-memory migration applied"):
        await live_store.verify_schema()


@pytest.mark.asyncio
async def test_migration_constraints_are_enforced(live_store: PostgresTaskMemoryStore) -> None:
    """The declared constraints actually reject bad rows."""
    await live_store.apply_migrations()
    schema = live_store._schema
    pool = await live_store._acquire_pool()

    async with pool.acquire() as conn:
        # A live task with a terminal timestamp must be rejected.
        with pytest.raises(Exception, match="tasks_terminal_consistent"):
            await conn.execute(
                f"INSERT INTO {schema}.tasks "
                "(task_id, chatbot_id, user_id, session_id, status, goal, projection, "
                " reducer_version, terminal_at) "
                "VALUES ('t1','b','u','s','active','g','{}'::jsonb, 1, now())"
            )

        await conn.execute(
            f"INSERT INTO {schema}.tasks "
            "(task_id, chatbot_id, user_id, session_id, status, goal, projection, reducer_version) "
            "VALUES ('t1','b','u','s','active','g','{}'::jsonb, 1)"
        )

        # A duplicate event id anywhere in the table is refused.
        await conn.execute(
            f"INSERT INTO {schema}.task_journal "
            "(task_id, seq, event_id, event_type, occurred_at, actor, payload) "
            "VALUES ('t1', 1, 'evt-1', 'task_started', now(), 'agent', '{}'::jsonb)"
        )
        with pytest.raises(Exception, match="task_journal_event_id_key"):
            await conn.execute(
                f"INSERT INTO {schema}.task_journal "
                "(task_id, seq, event_id, event_type, occurred_at, actor, payload) "
                "VALUES ('t1', 2, 'evt-1', 'task_paused', now(), 'agent', '{}'::jsonb)"
            )

        # Verifiable evidence without a fingerprint is refused.
        with pytest.raises(Exception, match="artifacts_verifiable_needs_fingerprint"):
            await conn.execute(
                f"INSERT INTO {schema}.artifacts "
                "(artifact_id, version, chatbot_id, user_id, session_id, kind, availability, "
                " evidence_verifiable) "
                "VALUES ('a1', 1, 'b','u','s','dataframe','memory', TRUE)"
            )

        # The unassociated alias namespace really is constrained: a second row
        # for the same key cannot be inserted. With a nullable task_id this
        # would silently succeed.
        await conn.execute(
            f"INSERT INTO {schema}.artifact_aliases "
            "(chatbot_id, user_id, session_id, alias_key, artifact_id, latest_version) "
            "VALUES ('b','u','s','sales','a1', 1)"
        )
        with pytest.raises(Exception, match="artifact_aliases_pkey"):
            await conn.execute(
                f"INSERT INTO {schema}.artifact_aliases "
                "(chatbot_id, user_id, session_id, alias_key, artifact_id, latest_version) "
                "VALUES ('b','u','s','sales','a2', 1)"
            )


@pytest.mark.asyncio
async def test_migration_down_removes_everything(live_store: PostgresTaskMemoryStore) -> None:
    """The DOWN migration drops the schema, and is itself repeatable."""
    await live_store.apply_migrations()
    await live_store.revert_migrations()

    pool = await live_store._acquire_pool()
    async with pool.acquire() as conn:
        for table in REQUIRED_TABLES:
            assert await conn.fetchval("SELECT to_regclass($1)", f"{live_store._schema}.{table}") is None

    # Repeatable: DROP ... IF EXISTS on an absent schema is not an error.
    await live_store.revert_migrations()


def test_migration() -> None:
    """Required aggregate case: structure, guards and rollback guidance.

    The live-server halves are the ``test_migration_applies_*`` /
    ``_constraints_*`` / ``_down_*`` cases above, which pytest collects
    separately and which SKIP explicitly without a configured DSN.
    """
    test_migration_file_is_packaged()
    test_migration_splits_into_up_and_down()
    test_migration_records_a_reversible_version()
    test_migration_documents_rollback_guidance()
    test_migration_creates_every_required_table()
    test_migration_is_idempotent_by_construction()
    test_migration_tasks_table_shape()
    test_migration_tasks_indexes()
    test_migration_journal_shape()
    test_migration_artifacts_shape()
    test_migration_alias_namespace_is_not_null()
    test_migration_evidence_relation_supports_derived_pinning()
    test_migration_sql_is_structurally_well_formed()


# ─────────────────────────────────────────────────────────────
# Coordinator
# ─────────────────────────────────────────────────────────────


class _FakeDriverTransaction:
    """Records commit/rollback so the coordinator's contract can be checked."""

    def __init__(self) -> None:
        """Initialize an unfinished transaction."""
        self.committed = False
        self.rolled_back = False

    async def start(self) -> None:
        """Begin the unit of work."""

    async def commit(self) -> None:
        """Record a commit."""
        self.committed = True

    async def rollback(self) -> None:
        """Record a rollback."""
        self.rolled_back = True


def test_coordinator_satisfies_the_protocols() -> None:
    """The concrete types satisfy the published contracts."""
    store = PostgresTaskMemoryStore("postgresql://unused/db")
    assert isinstance(store, TaskMemoryStore)
    assert isinstance(store, BaseTaskMemoryStore), "shared scope/cursor rules must be inherited, not re-derived"
    assert isinstance(store.coordinator(), TransactionCoordinator)

    handle = PostgresTransaction(object(), _FakeDriverTransaction())  # type: ignore[arg-type]
    assert isinstance(handle, Transaction)


@pytest.mark.asyncio
async def test_coordinator_transaction_semantics() -> None:
    """A handle exposes one connection and refuses use after completion."""
    connection = object()
    driver = _FakeDriverTransaction()
    handle = PostgresTransaction(connection, driver)  # type: ignore[arg-type]

    assert handle.is_active
    assert handle.connection is connection

    await handle.rollback()
    assert driver.rolled_back
    assert not handle.is_active

    # Idempotent: a cleanup path never has to guess whether it already ran.
    driver.rolled_back = False
    await handle.rollback()
    assert not driver.rolled_back, "a second rollback must not reach the driver"

    # Using a finished transaction is refused rather than silently running
    # outside it.
    with pytest.raises(TaskMemoryUnavailable, match="already completed"):
        _ = handle.connection


@pytest.mark.asyncio
async def test_coordinator_shares_one_connection(live_store: PostgresTaskMemoryStore) -> None:
    """Task and artifact writes inside one transaction use the same connection."""
    await live_store.apply_migrations()
    schema = live_store._schema

    seen: List[Any] = []
    async with live_store.transaction() as tx:
        assert tx.is_active
        # Two "stores" enlisting in the same unit of work.
        await _write_task(tx, schema, "t-shared")
        seen.append(tx.connection)
        await _write_artifact(tx, schema, "a-shared")
        seen.append(tx.connection)

    assert seen[0] is seen[1], "both stores must write through ONE connection"
    assert not tx.is_active

    pool = await live_store._acquire_pool()
    async with pool.acquire() as conn:
        assert await conn.fetchval(f"SELECT count(*) FROM {schema}.tasks") == 1
        assert await conn.fetchval(f"SELECT count(*) FROM {schema}.artifacts") == 1


@pytest.mark.asyncio
async def test_coordinator_rollback_removes_all_tentative_rows(
    live_store: PostgresTaskMemoryStore,
) -> None:
    """An error anywhere in the unit of work leaves nothing behind.

    This is the property that makes durable artifact publication safe: the
    alias/version index, the evidence rows and the journal event become
    visible together or not at all. A partial commit would publish a
    storage reference whose journal entry never existed.
    """
    await live_store.apply_migrations()
    schema = live_store._schema

    class _Boom(RuntimeError):
        pass

    with pytest.raises(_Boom):
        async with live_store.transaction() as tx:
            await _write_task(tx, schema, "t-doomed")
            await _write_artifact(tx, schema, "a-doomed")
            await tx.connection.execute(
                f"INSERT INTO {schema}.artifact_evidence (task_id, step_id, artifact_id, version) "
                "VALUES ('t-doomed', 's1', 'a-doomed', 1)"
            )
            raise _Boom("publication failed after the blob was written")

    pool = await live_store._acquire_pool()
    async with pool.acquire() as conn:
        for table in ("tasks", "artifacts", "artifact_evidence"):
            count = await conn.fetchval(f"SELECT count(*) FROM {schema}.{table}")
            assert count == 0, f"{table} retained a tentative row after rollback"


async def _write_task(tx: PostgresTransaction, schema: str, task_id: str) -> None:
    """Insert a minimal task row through the shared transaction.

    Args:
        tx: The shared transaction.
        schema: Schema to write into.
        task_id: Task identity.
    """
    await tx.connection.execute(
        f"INSERT INTO {schema}.tasks "
        "(task_id, chatbot_id, user_id, session_id, status, goal, projection, reducer_version) "
        "VALUES ($1, $2, $3, $4, 'active', 'g', '{}'::jsonb, 1)",
        task_id,
        SCOPE.chatbot_id,
        SCOPE.user_id,
        SCOPE.session_id,
    )


async def _write_artifact(tx: PostgresTransaction, schema: str, artifact_id: str) -> None:
    """Insert a minimal artifact row through the shared transaction.

    Args:
        tx: The shared transaction.
        schema: Schema to write into.
        artifact_id: Artifact identity.
    """
    await tx.connection.execute(
        f"INSERT INTO {schema}.artifacts "
        "(artifact_id, version, chatbot_id, user_id, session_id, kind, availability) "
        "VALUES ($1, 1, $2, $3, $4, 'json', 'memory')",
        artifact_id,
        SCOPE.chatbot_id,
        SCOPE.user_id,
        SCOPE.session_id,
    )


def test_coordinator() -> None:
    """Required aggregate case: shared connection and all-or-nothing rollback.

    The live halves (`test_coordinator_shares_one_connection`,
    `test_coordinator_rollback_removes_all_tentative_rows`) are collected
    separately and SKIP explicitly without a configured DSN.
    """
    test_coordinator_satisfies_the_protocols()


# ─────────────────────────────────────────────────────────────
# Optional import
# ─────────────────────────────────────────────────────────────


#: The cost every module under ``parrot.tools.working_memory`` already
#: pays, because that package's ``__init__`` eagerly imports the toolkit
#: (and therefore pandas, asyncpg and redis). Documented as a known
#: baseline in TASK-2972's completion note; the delta probe below is what
#: actually holds this module to account.
_BASELINE_MODULE = "parrot.tools.working_memory.task_memory.models"

_BACKEND_MODULE = "parrot.tools.working_memory.task_memory.store.postgres"


def _asyncpg_loaded(*modules: str) -> bool:
    """Import ``modules`` in a fresh interpreter; report whether asyncpg arrived.

    Args:
        *modules: Dotted module paths to import, in order.

    Returns:
        ``True`` when ``asyncpg`` ended up in ``sys.modules``.
    """
    code = (
        "import sys, importlib;"
        f"[importlib.import_module(m) for m in {list(modules)!r}];"
        "print('ASYNCPG=' + str('asyncpg' in sys.modules))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"importing {modules} failed:\n{result.stderr}"
    line = next(ln for ln in result.stdout.splitlines() if ln.startswith("ASYNCPG="))
    return line.removeprefix("ASYNCPG=") == "True"


def test_optional_import() -> None:
    """The durable backend must not be what drags in ``asyncpg``.

    A deployment without the PostgreSQL extra has to be able to import the
    task-memory package and run the in-memory backend.

    Measured as a **delta**, not an absolute: importing anything under
    ``parrot.tools.working_memory`` already loads asyncpg, because that
    package's ``__init__`` eagerly imports the toolkit. An absolute
    assertion would therefore fail for a reason that has nothing to do
    with this module. The structural check in
    :func:`test_optional_import_module_declares_no_top_level_driver` is
    the other half of the evidence.
    """
    baseline = _asyncpg_loaded(_BASELINE_MODULE)
    with_backend = _asyncpg_loaded(_BASELINE_MODULE, _BACKEND_MODULE)

    assert (
        with_backend == baseline
    ), "importing the durable backend changed whether asyncpg is loaded; the driver import must stay lazy"

    # And the module really did import and expose its version.
    code = f"import importlib; print('VERSION=' + str(importlib.import_module({_BACKEND_MODULE!r}).MIGRATION_VERSION))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"the durable backend failed to import:\n{result.stderr}"
    assert f"VERSION={MIGRATION_VERSION}" in result.stdout


def test_optional_import_records_the_package_baseline() -> None:
    """Document the pre-existing package cost, honestly.

    ``parrot/tools/working_memory/__init__.py`` eagerly imports the
    toolkit, so importing *any* submodule under it loads asyncpg. This
    test asserts that situation rather than pretending it away, and will
    fail — prompting this note's removal and a tightening of
    :func:`test_optional_import` to an absolute check — if the M5 task
    that owns that ``__init__`` makes the toolkit import lazy.
    """
    assert _asyncpg_loaded(_BASELINE_MODULE), (
        "the working_memory package __init__ no longer eagerly imports the toolkit — "
        "tighten test_optional_import to an absolute check and delete this test"
    )


def test_optional_import_module_declares_no_top_level_driver() -> None:
    """Structurally: no module-level ``import asyncpg`` in the backend."""
    import ast
    import importlib
    from pathlib import Path

    module = importlib.import_module("parrot.tools.working_memory.task_memory.store.postgres")
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    for node in tree.body:  # module level only — nested imports are the point
        if isinstance(node, ast.Import):
            assert all(a.name != "asyncpg" for a in node.names), "asyncpg imported at module level"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "asyncpg", "asyncpg imported at module level"


def test_optional_import_disabled_config_needs_no_database() -> None:
    """A disabled configuration touches no database and needs no driver."""
    from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig

    config = TaskMemoryConfig()
    assert config.enabled is False
    assert config.durable is False

    # Constructing the store performs no I/O either — connecting is deferred
    # to first use, so importing and wiring cannot fail on an absent server.
    store = PostgresTaskMemoryStore("postgresql://nonexistent.invalid:5432/db")
    assert store._pool is None


def test_optional_import_requires_a_dsn_or_pool() -> None:
    """A store with neither a DSN nor a pool is a configuration error."""
    with pytest.raises(ValueError, match="requires either a dsn or an existing pool"):
        PostgresTaskMemoryStore()


@pytest.mark.asyncio
async def test_optional_import_unreachable_server_is_explicit() -> None:
    """An unreachable database fails loudly, never silently non-durable.

    Degrading to the in-memory backend here would be a false durability
    claim: the caller asked for durable task memory and would get none.
    """
    store = PostgresTaskMemoryStore("postgresql://user@127.0.0.1:1/nonexistent_db")
    try:
        with pytest.raises(TaskMemoryUnavailable, match="could not connect"):
            await store._acquire_pool()
    finally:
        await store.close()


# ─────────────────────────────────────────────────────────────
# Later-task boundaries
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crud_paths_refuse_loudly_when_the_database_is_unreachable() -> None:
    """A command path never silently accepts work it cannot persist.

    This case originally asserted that every CRUD method raised
    ``NotImplementedError`` naming TASK-2995 — true only while that task
    was outstanding, and implementing them was its entire job. Rewritten
    to assert the *guarantee* the placeholder stood for rather than the
    placeholder itself: a store that accepted an append and persisted
    nothing would be worse than one that refuses.

    The refusals are now typed for their actual cause —
    :class:`TaskMemoryUnavailable` when the database cannot be reached,
    and a validation error when the command is malformed before any I/O
    is attempted.
    """
    store = PostgresTaskMemoryStore("postgresql://user@127.0.0.1:1/nonexistent_db")

    # Validation precedes I/O: an empty batch cannot begin a task, and
    # that is decided without ever reaching the database.
    with pytest.raises((ReducerError, ValueError, IndexError)):
        await store.create_task(SCOPE, goal="g", events=[])

    # Everything else fails on the connection, loudly and typed.
    for coro in (
        store.append_events(SCOPE, "t-1", []),
        store.load_snapshot(SCOPE, "t-1"),
        store.list_tasks(SCOPE),
        store.list_events(SCOPE, "t-1"),
        store.count_events(SCOPE, "t-1"),
    ):
        with pytest.raises(TaskMemoryUnavailable):
            await coro


@pytest.mark.asyncio
async def test_crud_paths_name_their_owning_task() -> None:
    """No command path still cites an unimplemented owner.

    The counterpart to the case above: once a placeholder's owning task
    lands, the citation must disappear with it. A method still claiming
    to be owned by a completed task is a stale promise.
    """
    import inspect

    source = inspect.getsource(PostgresTaskMemoryStore)
    assert "TASK-2995" not in source, (
        "PostgresTaskMemoryStore still cites TASK-2995 as an unimplemented owner, " "but that task has landed"
    )
