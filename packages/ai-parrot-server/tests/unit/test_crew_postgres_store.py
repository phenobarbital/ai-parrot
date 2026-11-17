"""FEAT-860 regression tests; use isolated fakes unless explicitly live."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import pytest

from parrot.handlers.crew.models import AgentDefinition, CrewDefinition, FlowRelation, ToolNodeDefinition
from parrot.handlers.crew.postgres_persistence import CrewPostgres, CrewStoredRow


class FakeConnection:
    """Minimal AsyncDB connection fake with explicitly queued outcomes."""

    def __init__(
        self,
        *,
        execute_results: list[Any] | None = None,
        fetchval_results: list[Any] | None = None,
        fetch_one_results: list[Any] | None = None,
        fetch_all_results: list[Any] | None = None,
    ) -> None:
        self.execute_results = iter(execute_results or [])
        self.fetchval_results = iter(fetchval_results or [])
        self.fetch_one_results = iter(fetch_one_results or [])
        self.fetch_all_results = iter(fetch_all_results or [])
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []

    @staticmethod
    def _outcome(outcomes: Iterator[Any], default: Any = None) -> Any:
        """Return or raise one queued fake outcome."""
        outcome = next(outcomes, default)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def execute(self, sql: str, *args: Any) -> Any:
        """Record an execute call and return its queued adapter result."""
        self.calls.append(("execute", sql, args))
        return self._outcome(self.execute_results)

    async def fetchval(self, sql: str, *args: Any) -> Any:
        """Record a fetchval call and return its queued result."""
        self.calls.append(("fetchval", sql, args))
        return self._outcome(self.fetchval_results)

    async def fetch_one(self, sql: str, *args: Any) -> Any:
        """Record a fetch_one call and return its queued result."""
        self.calls.append(("fetch_one", sql, args))
        return self._outcome(self.fetch_one_results)

    async def fetch_all(self, sql: str, *args: Any) -> Any:
        """Record a fetch_all call and return its queued result."""
        self.calls.append(("fetch_all", sql, args))
        return self._outcome(self.fetch_all_results)


class FakeConnectionContext:
    """Track entry and cleanup of one fake connection."""

    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> FakeConnection:
        self.entered += 1
        return self.connection

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.exited += 1


class FakeDB:
    """AsyncDB fake returning a dedicated, observable context manager."""

    def __init__(self, connection: FakeConnection) -> None:
        self.context = FakeConnectionContext(connection)

    async def connection(self) -> FakeConnectionContext:
        """Return the configured fake connection context."""
        return self.context


def _crew(*, name: str = "research", crew_id: str = "crew-1", tenant: str = "acme") -> CrewDefinition:
    """Build a complete definition that exercises all nested model imports."""
    return CrewDefinition(
        crew_id=crew_id,
        tenant=tenant,
        name=name,
        description="Research crew",
        agents=[AgentDefinition(agent_id="collector", name="Collector")],
        tool_nodes=[ToolNodeDefinition(node_id="publish", tool="publish_report")],
        flow_relations=[FlowRelation(source="Collector", target="publish")],
    )


def _row(crew: CrewDefinition, *, deleted_at: datetime | None = None, definition: Any = None) -> dict[str, Any]:
    """Build the exact row projection returned by the store queries."""
    return {
        "tenant": crew.tenant,
        "name": crew.name,
        "crew_id": crew.crew_id,
        "definition": crew.model_dump(mode="json") if definition is None else definition,
        "deleted_at": deleted_at,
    }


def _store(connection: FakeConnection) -> tuple[CrewPostgres, FakeDB]:
    """Build a schema-ready store bound to one fake database."""
    store = CrewPostgres("postgresql://test")
    store._schema_ensured = True
    database = FakeDB(connection)
    store._get_db = lambda: database
    return store, database


@pytest.mark.asyncio
async def test_upsert_and_tombstone_identity() -> None:
    """Explicit saves clear tombstones and deletes retain the same identity."""
    crew = _crew()
    connection = FakeConnection(fetchval_results=[crew.crew_id, crew.crew_id])
    store, database = _store(connection)

    original_updated_at = crew.updated_at
    assert await store.save_crew(crew) is True
    assert crew.updated_at > original_updated_at
    assert await store.delete_crew(crew) is True

    save_call, delete_call = connection.calls
    assert save_call[0] == delete_call[0] == "fetchval"
    assert "ON CONFLICT (tenant, name) DO UPDATE" in save_call[1]
    assert "deleted_at = NULL" in save_call[1]
    assert isinstance(save_call[2][5], dict)
    assert save_call[2][5]["updated_at"] == save_call[2][7].isoformat()
    assert "WHERE navigator.crew_definitions.crew_id = EXCLUDED.crew_id" in delete_call[1]
    assert delete_call[2][0:3] == (crew.tenant, crew.name, crew.crew_id)
    assert delete_call[2][5]["updated_at"] == delete_call[2][7].isoformat()
    assert database.context.entered == database.context.exited == 2


@pytest.mark.asyncio
async def test_name_conflict_does_not_swallow_id_conflict() -> None:
    """Only a targeted name conflict returns False; integrity causes propagate."""
    crew = _crew()
    integrity_error = RuntimeError("uq_crew_definitions_tenant_crew_id")
    connection = FakeConnection(fetchval_results=[None, integrity_error])
    store, _ = _store(connection)

    assert await store.insert_if_absent(crew) is False
    with pytest.raises(RuntimeError) as raised:
        await store.insert_if_absent(_crew(name="other"))

    assert raised.value is integrity_error
    assert all("ON CONFLICT (tenant, name) DO NOTHING" in call[1] for call in connection.calls)


@pytest.mark.asyncio
async def test_delete_rejects_stale_identity_and_is_idempotent() -> None:
    """A stale cached ID cannot tombstone the replacement stored at that name."""
    crew = _crew()
    connection = FakeConnection(fetchval_results=[None, crew.crew_id, crew.crew_id])
    store, _ = _store(connection)

    with pytest.raises(ValueError, match="no longer has identity"):
        await store.delete_crew(crew)
    assert await store.delete_crew(crew) is True
    assert await store.delete_crew(crew) is True


@pytest.mark.asyncio
async def test_malformed_row_reserves_identity() -> None:
    """Typed row APIs retain malformed/tombstoned identities while public reads skip them."""
    crew = _crew()
    malformed = _row(crew, definition="not-json")
    tombstone = _row(_crew(name="deleted", crew_id="crew-2"), deleted_at=datetime.now(timezone.utc))
    connection = FakeConnection(
        fetch_one_results=[malformed, malformed, malformed, tombstone],
        fetch_all_results=[[malformed, tombstone], [malformed, tombstone], [malformed, tombstone]],
    )
    store, _ = _store(connection)

    by_name = await store._load_row(crew.name, crew.tenant)
    by_id = await store._load_row_by_id(crew.crew_id, crew.tenant)
    assert isinstance(by_name, CrewStoredRow)
    assert isinstance(by_id, CrewStoredRow)
    assert by_name.crew_id == by_id.crew_id == crew.crew_id
    assert await store.load_crew(crew.name, crew.tenant) is None
    assert await store.load_crew_by_id("crew-2", crew.tenant) is None

    rows = await store._list_rows()
    assert [row.crew_id for row in rows] == ["crew-1", "crew-2"]
    assert await store.list_all_crews() == [{"tenant": "acme", "name": "research"}]
    assert await store.get_all_crews() == []


@pytest.mark.asyncio
async def test_active_rows_decode_for_all_public_read_shapes() -> None:
    """Name, ID and list APIs return validated active definitions."""
    crew = _crew()
    active = _row(crew)
    connection = FakeConnection(
        fetch_one_results=[active, active],
        fetch_all_results=[[active], [active]],
    )
    store, _ = _store(connection)

    assert await store.load_crew(crew.name, crew.tenant) == crew
    assert await store.load_crew_by_id(crew.crew_id, crew.tenant) == crew
    assert await store.list_all_crews() == [{"tenant": crew.tenant, "name": crew.name}]
    assert await store.get_all_crews(crew.tenant) == [crew]
    assert connection.calls[-1][2] == (crew.tenant,)


@pytest.mark.asyncio
async def test_schema_write_failure_closes_connection_and_retries() -> None:
    """Adapter-returned DDL errors leave schema retryable and clean up connections."""
    ddl_error = RuntimeError("ddl failed")
    failed_connection = FakeConnection(execute_results=[("CREATE", ddl_error)])
    successful_connection = FakeConnection(execute_results=[None, None])
    databases = iter([FakeDB(failed_connection), FakeDB(successful_connection)])
    store = CrewPostgres("postgresql://test")
    store._get_db = lambda: next(databases)

    with pytest.raises(RuntimeError) as raised:
        await store.ensure_schema()
    assert raised.value is ddl_error
    assert store._schema_ensured is False
    assert await store.ensure_schema() is None
    assert store._schema_ensured is True
    assert "deleted_at TIMESTAMPTZ" in successful_connection.calls[1][1]
    assert "PRIMARY KEY (tenant, name)" in successful_connection.calls[1][1]
    assert "UNIQUE (tenant, crew_id)" in successful_connection.calls[1][1]


@pytest.mark.asyncio
async def test_ping_without_dsn_does_not_open_connection() -> None:
    """An explicitly unavailable store reports unhealthy without database I/O."""
    store = CrewPostgres("postgresql://test")
    store.dsn = ""
    store._get_db = lambda: pytest.fail("ping opened a connection without a DSN")

    assert store.configured is False
    assert await store.ping() is False


@pytest.mark.asyncio
async def test_write_requires_returning_confirmation() -> None:
    """A swallowed write failure cannot be reported as a successful save."""
    store, _ = _store(FakeConnection(fetchval_results=[None]))

    with pytest.raises(RuntimeError, match="did not confirm"):
        await store.save_crew(_crew())


@pytest.mark.asyncio
async def test_create_only_replaces_tombstones() -> None:
    """Create inserts or revives a tombstone, reports a live name, and keeps driver errors intact."""
    crew = _crew()
    integrity_error = RuntimeError("uq_crew_definitions_tenant_crew_id")
    connection = FakeConnection(fetchval_results=[crew.crew_id, None, integrity_error])
    store, database = _store(connection)

    before = crew.updated_at
    assert await store.create_crew(crew) is True
    assert crew.updated_at > before
    assert await store.create_crew(_crew(name="other", crew_id="crew-2")) is False
    with pytest.raises(RuntimeError) as raised:
        await store.create_crew(_crew(name="third", crew_id="crew-3"))
    assert raised.value is integrity_error

    sql = connection.calls[0][1]
    assert "WHERE navigator.crew_definitions.deleted_at IS NOT NULL" in sql
    assert "deleted_at = NULL" in sql
    assert isinstance(connection.calls[0][2][5], dict)
    assert database.context.entered == database.context.exited == 3


@pytest.mark.asyncio
async def test_tombstone_identity_requires_matching_identity() -> None:
    """A tombstone by identity succeeds only while the row still has the resolved crew_id."""
    connection = FakeConnection(fetchval_results=["crew-1", None])
    store, _ = _store(connection)

    assert await store.tombstone_identity("acme", "research", "crew-1") is True
    with pytest.raises(ValueError, match="no longer has identity"):
        await store.tombstone_identity("acme", "research", "stale-id")

    sql, args = connection.calls[0][1], connection.calls[0][2]
    assert "WHERE tenant = $1 AND name = $2 AND crew_id = $3" in sql
    assert args[:3] == ("acme", "research", "crew-1")
    assert isinstance(args[3], datetime)


@pytest.mark.asyncio
async def test_lock_release_and_retry_after_failure() -> None:
    """The dedicated lock session releases on errors/cancellation and does not run DDL."""
    connection = FakeConnection(fetchval_results=[True, True, True, True])
    store, database = _store(connection)
    store._schema_ensured = False

    with pytest.raises(RuntimeError, match="migration failed"):
        async with store.migration_lock() as acquired:
            assert acquired is True
            raise RuntimeError("migration failed")

    with pytest.raises(asyncio.CancelledError):
        async with store.migration_lock() as acquired:
            assert acquired is True
            raise asyncio.CancelledError

    assert [call[0] for call in connection.calls] == ["fetchval"] * 4
    assert "pg_try_advisory_lock" in connection.calls[0][1]
    assert "pg_advisory_unlock" in connection.calls[1][1]
    assert "pg_try_advisory_lock" in connection.calls[2][1]
    assert "pg_advisory_unlock" in connection.calls[3][1]
    assert connection.calls[0][2] == connection.calls[1][2]
    assert database.context.entered == database.context.exited == 2
    assert store._schema_ensured is False
