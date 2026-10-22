"""FEAT-621 M3 — StudioAgentRepository on real Postgres (AC6, AC7, AC8)."""
import pytest

from parrot.handlers.studio.storage.models import (
    StudioAgentDefinition,
    StudioNameConflict,
    StudioNotFound,
    StudioPartition,
    StudioStaleAuthorization,
    StudioStorageError,
    StudioVersionConflict,
    StudioWriteGuard,
)
from parrot.handlers.studio.storage.repositories import StudioAgentRepository, studio_transaction

ACME, BETA, GLOBAL = StudioPartition("acme"), StudioPartition("beta"), StudioPartition.GLOBAL


@pytest.fixture
async def repo(studio_pool):
    from .conftest import _truncate_studio_tables

    await _truncate_studio_tables(studio_pool)
    return StudioAgentRepository(studio_pool)


async def _insert(repo, part, name, *, owner="u1", visibility="private", groups=(), definition=None):
    async with studio_transaction(repo.pool) as conn:
        return await repo.insert(
            conn, part, name=name, owner=owner, definition=definition or StudioAgentDefinition(),
            visibility=visibility, allowed_groups=groups,
        )


async def _raw(pool, sql, *args):
    async with pool.acquire() as conn:
        return await conn.fetch_one(sql, *args)


async def test_insert_get_roundtrip(repo) -> None:
    definition = StudioAgentDefinition(
        bot_class="Agent", llm="openai:gpt-4o-mini", system_prompt="hi", tools=["x"], config={"k": 1},
    )
    created = await _insert(repo, ACME, "sales", visibility="groups", groups=("g1", "g2"), definition=definition)
    assert created.tenant == "acme" and created.version == 1 and created.status == "active"
    assert created.allowed_groups == ("g1", "g2") and created.definition == definition
    assert await repo.get(ACME, "sales") == created
    head = await repo.get_version(ACME, "sales")
    assert (head.agent_id, head.version, head.status) == (created.agent_id, 1, "active")
    assert await repo.get(ACME, "nope") is None and await repo.get_version(ACME, "nope") is None


async def test_unique_per_tenant(repo) -> None:
    await _insert(repo, ACME, "sales")
    await _insert(repo, BETA, "sales")                         # same name, other tenant: coexists
    with pytest.raises(StudioNameConflict):
        await _insert(repo, ACME, "sales")
    await _insert(repo, GLOBAL, "sales")
    with pytest.raises(StudioNameConflict):                    # partial index for tenant NULL
        await _insert(repo, GLOBAL, "sales")
    # the failed inserts left nothing behind and the pool is still usable
    assert len(await repo.list(ACME)) == 1 and len(await repo.list(GLOBAL)) == 1


async def test_partition_isolation_agents(repo) -> None:
    rec = await _insert(repo, ACME, "sales", owner="u1")
    await _insert(repo, GLOBAL, "other")
    assert await repo.get(BETA, "sales") is None
    assert await repo.get_version(BETA, "sales") is None
    assert await repo.load_snapshot(BETA, "sales") is None
    assert await repo.list(BETA) == []
    assert [r.name for r in await repo.list(ACME)] == ["sales"]
    assert [r.name for r in await repo.list(ACME, owner="u2")] == []
    assert [r.name for r in await repo.list(ACME, owner="u1")] == ["sales"]
    assert [r.name for r in await repo.list(GLOBAL)] == ["other"]
    async with studio_transaction(repo.pool) as conn:
        with pytest.raises(StudioNotFound):
            await repo.lock(conn, BETA, "sales", StudioWriteGuard())
        with pytest.raises(StudioNotFound):
            await repo.update_definition(conn, BETA, "sales", StudioAgentDefinition(description="x"))
        with pytest.raises(StudioNotFound):
            await repo.update_visibility(conn, BETA, "sales", visibility="private", allowed_groups=())
        with pytest.raises(StudioNotFound):
            await repo.set_status(conn, BETA, "sales", "disabled")
        assert await repo.delete(conn, BETA, "sales") is None
    after = await repo.get(ACME, "sales")
    assert after == rec                                          # untouched, version not bumped


async def test_lock_guard_order(repo) -> None:
    rec = await _insert(repo, ACME, "sales")
    async with studio_transaction(repo.pool) as conn:
        head = await repo.lock(conn, ACME, "sales", StudioWriteGuard(authorized_version=1, expected_version=1))
        assert head.agent_id == rec.agent_id
        with pytest.raises(StudioNotFound):                      # NotFound wins over any guard
            await repo.lock(conn, ACME, "ghost", StudioWriteGuard(expected_version=9, authorized_version=9))
        with pytest.raises(StudioVersionConflict):               # expected_version checked before authorized_version
            await repo.lock(conn, ACME, "sales", StudioWriteGuard(expected_version=2, authorized_version=2))
        with pytest.raises(StudioStaleAuthorization):
            await repo.lock(conn, ACME, "sales", StudioWriteGuard(authorized_version=2))
        await repo.lock(conn, ACME, "sales", StudioWriteGuard())   # no preconditions: always passes


async def test_lock_blocks_concurrent_writer(repo) -> None:
    import asyncio

    await _insert(repo, ACME, "sales")
    order: list[str] = []

    async def writer() -> None:
        async with studio_transaction(repo.pool) as conn:
            await repo.lock(conn, ACME, "sales", StudioWriteGuard())
            order.append("second-locked")

    async with studio_transaction(repo.pool) as conn:
        await repo.lock(conn, ACME, "sales", StudioWriteGuard())
        task = asyncio.create_task(writer())
        await asyncio.sleep(0.3)
        order.append("first-releasing")
    await task
    assert order == ["first-releasing", "second-locked"]


async def test_version_bumps_on_definition_update(repo) -> None:
    rec = await _insert(repo, ACME, "sales")
    new_def = StudioAgentDefinition(description="d2", system_prompt="p2")
    async with studio_transaction(repo.pool) as conn:
        updated = await repo.update_definition(conn, ACME, "sales", new_def)
    assert updated.version == 2 and updated.definition == new_def and updated.updated_at >= rec.updated_at
    async with studio_transaction(repo.pool) as conn:
        vis = await repo.update_visibility(conn, ACME, "sales", visibility="groups", allowed_groups=["g"])
    assert vis.version == 3 and (vis.visibility, vis.allowed_groups) == ("groups", ("g",))
    async with studio_transaction(repo.pool) as conn:
        disabled = await repo.set_status(conn, ACME, "sales", "disabled")
    assert disabled.version == 4 and disabled.status == "disabled"
    assert (await repo.get_version(ACME, "sales")).version == 4


async def test_constraint_violation_rolls_back_and_raises(repo) -> None:
    await _insert(repo, GLOBAL, "g1")
    with pytest.raises(StudioStorageError):                    # shared visibility needs a tenant
        async with studio_transaction(repo.pool) as conn:
            await repo.update_visibility(conn, GLOBAL, "g1", visibility="tenant", allowed_groups=())
    assert (await repo.get(GLOBAL, "g1")).visibility == "private"


async def test_delete_returns_snapshot(repo) -> None:
    rec = await _insert(repo, ACME, "sales")
    await _raw(
        repo.pool,
        "WITH r AS (INSERT INTO navigator.ai_agent_assets (agent_id, kind, name, content, size, sha256) "
        "VALUES ($1, 'kb', 'a.md', 'hello', 5, $2) RETURNING 1) SELECT count(*) FROM r", rec.agent_id, "d" * 64,
    )
    await _raw(
        repo.pool,
        "WITH r AS (INSERT INTO navigator.ai_agent_tooling (agent_id, kind, slug, position) "
        "VALUES ($1, 'mcp', 'docs', 0) RETURNING 1) SELECT count(*) FROM r", rec.agent_id,
    )
    async with studio_transaction(repo.pool) as conn:
        snap = await repo.delete(conn, ACME, "sales")
    assert snap.record.agent_id == rec.agent_id and snap.record.name == "sales"
    assert [(a.kind, a.name, a.content) for a in snap.assets] == [("kb", "a.md", "hello")]
    assert [(t.kind, t.slug) for t in snap.tooling] == [("mcp", "docs")]
    assert await repo.get(ACME, "sales") is None
    for table in ("ai_agent_assets", "ai_agent_tooling"):
        assert (await _raw(repo.pool, f"SELECT count(*) AS n FROM navigator.{table}"))["n"] == 0
    async with studio_transaction(repo.pool) as conn:
        assert await repo.delete(conn, ACME, "sales") is None


async def test_load_snapshot_single_statement(repo) -> None:
    rec = await _insert(repo, ACME, "sales")
    await _raw(
        repo.pool,
        "WITH r AS (INSERT INTO navigator.ai_agent_assets (agent_id, kind, name, content, size, sha256) "
        "VALUES ($1, 'identity', 'role.md', 'you are', 7, $2), ($1, 'kb', 'a.md', 'k', 1, $2) RETURNING 1) "
        "SELECT count(*) FROM r", rec.agent_id, "e" * 64,
    )
    await _raw(
        repo.pool,
        "WITH r AS (INSERT INTO navigator.ai_agent_tooling (agent_id, kind, slug, position, config, secret_refs) "
        "VALUES ($1, 'toolkit', 'b', 1, '{\"x\": 1}'::jsonb, '{}'::jsonb), "
        "($1, 'toolkit', 'a', 0, '{}'::jsonb, '{\"token\": \"v\"}'::jsonb), ($1, 'mcp', 'm', 0, '{}', '{}') "
        "RETURNING 1) SELECT count(*) FROM r", rec.agent_id,
    )
    calls: list[str] = []

    class Spy:
        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, attr):
            target = getattr(self._conn, attr)
            if attr in ("fetch_one", "fetch_all", "execute"):
                async def wrapped(sql, *a, **k):
                    calls.append(attr)
                    return await target(sql, *a, **k)
                return wrapped
            return target

    class SpyPool:
        def __init__(self, pool):
            self.pool = pool

        def acquire(self):
            outer = self.pool.acquire()

            class Ctx:
                async def __aenter__(self_inner):
                    return Spy(await outer.__aenter__())

                async def __aexit__(self_inner, *exc):
                    return await outer.__aexit__(*exc)

            return Ctx()

    snap = await StudioAgentRepository(SpyPool(repo.pool)).load_snapshot(ACME, "sales")
    assert calls == ["fetch_one"]                                 # ONE statement = one MVCC snapshot
    assert snap.record.agent_id == rec.agent_id and snap.record.version == 6   # 1 + five child-row touches
    assert [(a.kind, a.name, a.content, a.size) for a in snap.assets] == [
        ("identity", "role.md", "you are", 7), ("kb", "a.md", "k", 1)]
    assert all(a.updated_at.tzinfo is not None for a in snap.assets)
    assert [(t.kind, t.slug, t.position) for t in snap.tooling] == [
        ("mcp", "m", 0), ("toolkit", "a", 0), ("toolkit", "b", 1)]      # ordered by (kind, position)
    assert snap.tooling[1].secret_refs == {"token": "v"} and snap.tooling[2].config == {"x": 1}
    assert await repo.load_snapshot(ACME, "ghost") is None
    empty = await _insert(repo, ACME, "empty")
    bare = await repo.load_snapshot(ACME, "empty")
    assert bare.record == empty and bare.assets == () and bare.tooling == ()
