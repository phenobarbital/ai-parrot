"""Tests for parrot.bots.flows.core.checkpoint.store.durable (TASK-2050).

The sqlite driver suite always runs (file-backed, no external service).
Postgres/Mongo suites are skipped cleanly when the corresponding service
is not USABLE at the configured DSN — see :func:`_service_usable`.
"""
import asyncio
import os
import socket
from datetime import UTC, datetime
from urllib.parse import urlparse

import pytest
from parrot import conf
from parrot.bots.flows.core.checkpoint import ContextSnapshot, FlowCheckpoint
from parrot.bots.flows.core.checkpoint.store.durable import DurableCheckpointStore
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition

#: Seconds allowed for a probe connection. Long enough for a DNS lookup
#: of a LAN hostname, short enough not to stall collection.
_PROBE_TIMEOUT = 3.0


def _port_open(dsn: str, default_port: int) -> bool:
    """Whether something is listening on the DSN's host:port.

    A fast pre-check only — see :func:`_service_usable` for why this is
    not sufficient on its own.
    """
    parsed = urlparse(dsn)
    host = parsed.hostname or "localhost"
    port = parsed.port or default_port
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _postgres_usable(dsn: str) -> bool:
    """Whether Postgres is reachable AND these credentials work.

    A TCP handshake proves a port is open, not that the DSN is usable.
    The guard used to stop there, so on any machine already running its
    own Postgres the suite ran against the hardcoded
    ``postgres:postgres@localhost`` fallback and failed with "password
    authentication failed for user 'postgres'" — an environment mismatch
    reported as two broken tests, on every full-suite run.

    Returns:
        True only when a connection can actually be opened.
    """
    if not _port_open(dsn, 5432):
        return False
    try:
        import asyncpg
    except ImportError:
        return False

    async def _probe() -> None:
        connection = await asyncpg.connect(dsn, timeout=_PROBE_TIMEOUT)
        await connection.close()

    try:
        asyncio.run(_probe())
        return True
    except Exception:  # noqa: BLE001 - any failure means "not usable here"
        return False


def _mongo_usable(dsn: str) -> bool:
    """Whether MongoDB answers a ping at ``dsn``.

    Same reasoning as :func:`_postgres_usable`: an open port is not an
    authenticated, writable server.

    Returns:
        True only when the server answers ``ping``.
    """
    if not _port_open(dsn, 27017):
        return False
    try:
        from pymongo import MongoClient
    except ImportError:
        return False
    try:
        client = MongoClient(dsn, serverSelectionTimeoutMS=int(_PROBE_TIMEOUT * 1000))
        try:
            client.admin.command("ping")
            return True
        finally:
            client.close()
    except Exception:  # noqa: BLE001 - any failure means "not usable here"
        return False


@pytest.fixture
def flow_definition() -> FlowDefinition:
    return FlowDefinition(
        flow="durable-store-test-flow",
        nodes=[NodeDefinition(id="start", type="start")],
    )


def make_checkpoint(
    flow_id: str,
    checkpoint_id: int,
    definition: FlowDefinition,
    status: str = "running",
) -> FlowCheckpoint:
    return FlowCheckpoint(
        flow_id=flow_id,
        flow_name=definition.flow,
        checkpoint_id=checkpoint_id,
        created_at=datetime.now(UTC),
        status=status,
        definition=definition,
        context=ContextSnapshot(initial_task="do the thing"),
    )


# ---------------------------------------------------------------------------
# sqlite — always runs (file-backed, no external service)
# ---------------------------------------------------------------------------


@pytest.fixture
async def sqlite_store(tmp_path):
    store = DurableCheckpointStore(driver="sqlite", dsn=str(tmp_path / "ckpt.db"))
    yield store
    await store.close()


@pytest.mark.asyncio
async def test_durable_store_put_get_list_suspended(sqlite_store, flow_definition):
    flow_id = "durable-flow-1"
    await sqlite_store.put(make_checkpoint(flow_id, 1, flow_definition, status="running"))
    await sqlite_store.put(
        make_checkpoint(flow_id, 2, flow_definition, status="suspended")
    )

    latest = await sqlite_store.latest(flow_id)
    assert latest is not None
    assert latest.checkpoint_id == 2
    assert latest.status == "suspended"

    history = await sqlite_store.history(flow_id)
    assert len(history) == 2
    assert history[0].checkpoint_id == 2

    suspended = await sqlite_store.list_flows(status="suspended")
    assert any(f["flow_id"] == flow_id for f in suspended)

    running = await sqlite_store.list_flows(status="running")
    assert not any(f["flow_id"] == flow_id for f in running)


@pytest.mark.asyncio
async def test_durable_store_get_specific_and_missing(sqlite_store, flow_definition):
    flow_id = "durable-flow-2"
    await sqlite_store.put(make_checkpoint(flow_id, 1, flow_definition))
    await sqlite_store.put(make_checkpoint(flow_id, 2, flow_definition))

    cp = await sqlite_store.get(flow_id, 1)
    assert cp is not None
    assert cp.checkpoint_id == 1

    assert await sqlite_store.get(flow_id, 999) is None
    assert await sqlite_store.get("nonexistent-flow", 1) is None


@pytest.mark.asyncio
async def test_durable_store_upsert_no_duplicates(sqlite_store, flow_definition):
    flow_id = "durable-flow-3"
    await sqlite_store.put(make_checkpoint(flow_id, 1, flow_definition, status="running"))
    await sqlite_store.put(
        make_checkpoint(flow_id, 1, flow_definition, status="completed")
    )

    history = await sqlite_store.history(flow_id, limit=20)
    assert len(history) == 1
    assert history[0].status == "completed"


@pytest.mark.asyncio
async def test_durable_store_delete_flow(sqlite_store, flow_definition):
    flow_id = "durable-flow-4"
    await sqlite_store.put(make_checkpoint(flow_id, 1, flow_definition))
    await sqlite_store.delete_flow(flow_id)
    assert await sqlite_store.latest(flow_id) is None
    assert await sqlite_store.history(flow_id) == []


@pytest.mark.asyncio
async def test_durable_store_lease_methods_not_implemented(sqlite_store):
    with pytest.raises(NotImplementedError):
        await sqlite_store.acquire_lease("f1", "holder-a")
    with pytest.raises(NotImplementedError):
        await sqlite_store.renew_lease("f1", "holder-a")
    with pytest.raises(NotImplementedError):
        await sqlite_store.release_lease("f1", "holder-a")


def test_unknown_driver_raises():
    with pytest.raises(ValueError, match="Unknown DurableCheckpointStore driver"):
        DurableCheckpointStore(driver="etcd")


# ---------------------------------------------------------------------------
# postgres — skipped cleanly when unreachable
# ---------------------------------------------------------------------------

#: Resolution order: an explicit test DSN, then the project's own
#: configured database (``conf.default_dsn``, built from DBUSER/DBHOST/
#: DBNAME), then a bare localhost default for a CI container. The middle
#: rung is the point: a developer with a working local Postgres does not
#: also run one as `postgres:postgres`, so the hardcoded default could
#: only ever fail for them.
_PG_DSN = (
    os.environ.get("FLOW_CHECKPOINT_TEST_PG_DSN")
    or conf.default_dsn
    or "postgres://postgres:postgres@localhost:5432/postgres"
)
pg_pytestmark = pytest.mark.skipif(
    not _postgres_usable(_PG_DSN), reason="Postgres is not usable at the configured DSN"
)


@pytest.fixture
async def postgres_store():
    """Yield a Postgres-backed store, refusing to touch a real table.

    ``DurableCheckpointStore`` hardcodes ``_TABLE = "flow_checkpoints"``
    (there is no per-instance table name), and this fixture DROPs it on
    teardown. That was harmless while the suite only ever pointed at a
    throwaway ``postgres:postgres@localhost`` container; now that it
    defaults to the project's OWN database, a pre-existing table would be
    someone's real checkpoints — written into, then dropped. So: skip
    instead, and only drop what this fixture created.
    """
    import asyncpg

    probe = await asyncpg.connect(_PG_DSN, timeout=_PROBE_TIMEOUT)
    try:
        pre_existing = await probe.fetchval(
            "SELECT to_regclass('flow_checkpoints') IS NOT NULL"
        )
    finally:
        await probe.close()
    if pre_existing:
        pytest.skip(
            "a flow_checkpoints table already exists at the configured DSN; "
            "refusing to write to and drop a table this suite did not create"
        )

    store = DurableCheckpointStore(driver="postgres", dsn=_PG_DSN)
    yield store
    conn = await store._ensure()
    await conn.execute("DROP TABLE IF EXISTS flow_checkpoints")
    await store.close()


@pg_pytestmark
@pytest.mark.asyncio
async def test_durable_store_postgres_put_get_list_suspended(
    postgres_store, flow_definition
):
    flow_id = "durable-pg-flow-1"
    await postgres_store.put(
        make_checkpoint(flow_id, 1, flow_definition, status="running")
    )
    await postgres_store.put(
        make_checkpoint(flow_id, 2, flow_definition, status="suspended")
    )

    latest = await postgres_store.latest(flow_id)
    assert latest is not None
    assert latest.checkpoint_id == 2

    history = await postgres_store.history(flow_id)
    assert len(history) == 2

    suspended = await postgres_store.list_flows(status="suspended")
    assert any(f["flow_id"] == flow_id for f in suspended)


@pg_pytestmark
@pytest.mark.asyncio
async def test_durable_store_postgres_upsert_no_duplicates(
    postgres_store, flow_definition
):
    flow_id = "durable-pg-flow-2"
    await postgres_store.put(make_checkpoint(flow_id, 1, flow_definition, status="running"))
    await postgres_store.put(
        make_checkpoint(flow_id, 1, flow_definition, status="completed")
    )
    history = await postgres_store.history(flow_id, limit=20)
    assert len(history) == 1
    assert history[0].status == "completed"


# ---------------------------------------------------------------------------
# mongodb — skipped cleanly when unreachable
# ---------------------------------------------------------------------------

_MONGO_DSN = (
    os.environ.get("FLOW_CHECKPOINT_TEST_MONGO_DSN")
    or conf.PARROT_MONGODB_DSN
    or "mongodb://localhost:27017/ai_parrot_checkpoints_test"
)
mongo_pytestmark = pytest.mark.skipif(
    not _mongo_usable(_MONGO_DSN), reason="MongoDB is not usable at the configured DSN"
)


@pytest.fixture
async def mongo_store():
    store = DurableCheckpointStore(driver="mongodb", dsn=_MONGO_DSN)
    yield store
    conn = await store._ensure()
    await conn.execute("flow_checkpoints", "delete_many", {})
    await store.close()


@mongo_pytestmark
@pytest.mark.asyncio
async def test_durable_store_mongo_put_get_list_suspended(mongo_store, flow_definition):
    flow_id = "durable-mongo-flow-1"
    await mongo_store.put(make_checkpoint(flow_id, 1, flow_definition, status="running"))
    await mongo_store.put(
        make_checkpoint(flow_id, 2, flow_definition, status="suspended")
    )

    latest = await mongo_store.latest(flow_id)
    assert latest is not None
    assert latest.checkpoint_id == 2

    history = await mongo_store.history(flow_id)
    assert len(history) == 2

    suspended = await mongo_store.list_flows(status="suspended")
    assert any(f["flow_id"] == flow_id for f in suspended)


@mongo_pytestmark
@pytest.mark.asyncio
async def test_durable_store_mongo_upsert_no_duplicates(mongo_store, flow_definition):
    flow_id = "durable-mongo-flow-2"
    await mongo_store.put(make_checkpoint(flow_id, 1, flow_definition, status="running"))
    await mongo_store.put(
        make_checkpoint(flow_id, 1, flow_definition, status="completed")
    )
    history = await mongo_store.history(flow_id, limit=20)
    assert len(history) == 1
    assert history[0].status == "completed"
