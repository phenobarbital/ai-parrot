"""FEAT-621 — the fake raises the same signals as Postgres."""
import inspect
import os
from hashlib import sha256

import pytest

from parrot.handlers.studio.storage import repositories as real
from parrot.handlers.studio.storage.models import (
    StudioAgentBundle,
    StudioAgentDefinition,
    StudioAssetInput,
    StudioNameConflict,
    StudioNotFound,
    StudioPartition,
    StudioStaleAuthorization,
    StudioStorageError,
    StudioToolingRecord,
    StudioVersionConflict,
    StudioWriteGuard,
)
from parrot.handlers.studio.storage.repositories import build_studio_repositories, studio_transaction
from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories

ACME, BETA, GLOBAL = StudioPartition("acme"), StudioPartition("beta"), StudioPartition.GLOBAL
PAIRS = [
    ("agents", real.StudioAgentRepository),
    ("assets", real.StudioAssetRepository),
    ("tooling", real.StudioToolingRepository),
    ("drafts", real.StudioDraftRepository),
    ("skills", real.StudioSkillCatalogRepository),
]


def _shape(fn):
    return [(p.name, p.kind, p.default) for p in inspect.signature(fn).parameters.values() if p.name != "self"]


def test_fake_signatures_match() -> None:
    fake = InMemoryStudioRepositories()
    for attr, cls in PAIRS:
        public = [n for n, f in inspect.getmembers(cls, inspect.iscoroutinefunction) if not n.startswith("_")]
        assert public, cls
        fake_repo = getattr(fake, attr)
        for name in public:
            assert inspect.iscoroutinefunction(getattr(fake_repo, name)), f"{attr}.{name} missing in the fake"
            assert _shape(getattr(fake_repo, name)) == _shape(getattr(cls, name)), f"{attr}.{name} signature drifted"
        extra = [n for n, _ in inspect.getmembers(type(fake_repo), inspect.iscoroutinefunction) if not n.startswith("_")]
        assert sorted(extra) == sorted(public), f"{attr}: public async methods differ"
    assert fake.pool is not None


@pytest.fixture(params=["fake", "pg"])
async def repos(request):
    if request.param == "fake":
        yield InMemoryStudioRepositories()
        return
    dsn = os.environ.get("TEST_STUDIO_PG_DSN")
    if not dsn:
        pytest.skip("TEST_STUDIO_PG_DSN not set; the Postgres half of the contract needs a database")
    from asyncdb import AsyncPool

    from parrot.handlers.studio.storage.migrate import apply_studio_migrations

    from .conftest import _truncate_studio_tables

    pool = AsyncPool("pg", dsn=dsn)
    await pool.connect()
    await apply_studio_migrations(pool)
    await _truncate_studio_tables(pool)
    yield build_studio_repositories(pool)
    await _truncate_studio_tables(pool)
    await pool.close()


def _def(**kw) -> StudioAgentDefinition:
    return StudioAgentDefinition(**kw)


async def _agent(repos, part, name, **kw):
    async with studio_transaction(repos.pool) as conn:
        return await repos.agents.insert(
            conn, part, name=name, owner="u1", definition=_def(), visibility=kw.get("visibility", "private"),
            allowed_groups=(),
        )


def _tool(slug: str) -> StudioToolingRecord:
    from datetime import datetime, timezone

    return StudioToolingRecord(None, "toolkit", slug, 0, {}, {}, None, datetime.now(timezone.utc))


async def test_same_signals_uniqueness(repos) -> None:
    await _agent(repos, ACME, "sales")
    await _agent(repos, BETA, "sales")
    with pytest.raises(StudioNameConflict):
        await _agent(repos, ACME, "sales")
    await _agent(repos, GLOBAL, "sales")
    with pytest.raises(StudioNameConflict):
        await _agent(repos, GLOBAL, "sales")
    bundle = StudioAgentBundle(name="d", definition=_def())
    for part in (ACME, GLOBAL):
        async with studio_transaction(repos.pool) as conn:
            await repos.drafts.insert(conn, part, name="d", owner="u", bundle=bundle, visibility="private", allowed_groups=())
        with pytest.raises(StudioNameConflict):
            async with studio_transaction(repos.pool) as conn:
                await repos.drafts.insert(conn, part, name="d", owner="u", bundle=bundle, visibility="private", allowed_groups=())
        async with studio_transaction(repos.pool) as conn:
            await repos.skills.insert(conn, part, owner="u", name="s", description="d", body="b")
        with pytest.raises(StudioNameConflict):
            async with studio_transaction(repos.pool) as conn:
                await repos.skills.insert(conn, part, owner="u", name="s", description="d", body="b")


async def test_same_signals_checks(repos) -> None:
    with pytest.raises(StudioStorageError):                      # tenant NULL ⇒ private
        await _agent(repos, GLOBAL, "g", visibility="tenant")
    with pytest.raises(StudioStorageError):                      # visibility domain
        await _agent(repos, ACME, "p", visibility="public")
    with pytest.raises(StudioStorageError):                      # name format
        await _agent(repos, ACME, "a:b")
    await _agent(repos, GLOBAL, "ok")
    with pytest.raises(StudioStorageError):
        async with studio_transaction(repos.pool) as conn:
            await repos.agents.update_visibility(conn, GLOBAL, "ok", visibility="groups", allowed_groups=["g"])
    assert (await repos.agents.get(GLOBAL, "ok")).visibility == "private"
    with pytest.raises(StudioStorageError):
        async with studio_transaction(repos.pool) as conn:
            await repos.skills.insert(conn, GLOBAL, owner="u", name="s", description="d", body="b", visibility="tenant")


async def test_same_signals_versions_guards_and_absent(repos) -> None:
    rec = await _agent(repos, ACME, "sales")
    assert rec.version == 1
    async with studio_transaction(repos.pool) as conn:
        head = await repos.agents.lock(conn, ACME, "sales", StudioWriteGuard(expected_version=1, authorized_version=1))
        asset = StudioAssetInput(kind="kb", name="a.md", content="héllo")
        stored = await repos.assets.put(conn, head.agent_id, asset, sha256=sha256(b"x").hexdigest())
        assert stored.size == 6
        await repos.tooling.replace(conn, head.agent_id, toolkits=[_tool("jira")], mcp_servers=[])
    after_child = (await repos.agents.get_version(ACME, "sales")).version
    assert after_child == 3                                       # one bump per child row write
    async with studio_transaction(repos.pool) as conn:
        upd = await repos.agents.update_definition(conn, ACME, "sales", _def(description="x"))
    assert upd.version == after_child + 1
    with pytest.raises(StudioVersionConflict):
        async with studio_transaction(repos.pool) as conn:
            await repos.agents.lock(conn, ACME, "sales", StudioWriteGuard(expected_version=1))
    with pytest.raises(StudioStaleAuthorization):
        async with studio_transaction(repos.pool) as conn:
            await repos.agents.lock(conn, ACME, "sales", StudioWriteGuard(authorized_version=1))
    with pytest.raises(StudioNotFound):
        async with studio_transaction(repos.pool) as conn:
            await repos.agents.lock(conn, ACME, "ghost", StudioWriteGuard())
    # absent / foreign-partition rows
    assert await repos.agents.get(BETA, "sales") is None and await repos.agents.list(BETA) == []
    assert await repos.assets.list(BETA, "sales") == [] and await repos.tooling.list(BETA, "sales") == []
    assert await repos.assets.get(ACME, "sales", "kb", "zzz") is None
    async with studio_transaction(repos.pool) as conn:
        assert await repos.agents.delete(conn, BETA, "sales") is None
        assert await repos.drafts.delete(conn, ACME, "nope") is False
    snap = await repos.agents.load_snapshot(ACME, "sales")
    assert [(a.kind, a.name, a.content) for a in snap.assets] == [("kb", "a.md", "héllo")]
    assert [(t.kind, t.slug, t.position) for t in snap.tooling] == [("toolkit", "jira", 0)]
    assert [a.content for a in await repos.assets.list(ACME, "sales")] == [None]
    async with studio_transaction(repos.pool) as conn:
        deleted = await repos.agents.delete(conn, ACME, "sales")
    assert deleted.record.name == "sales" and len(deleted.assets) == 1 and len(deleted.tooling) == 1
    assert await repos.agents.get(ACME, "sales") is None and await repos.assets.list(ACME, "sales") == []


async def _draft(repos, name):
    async with studio_transaction(repos.pool) as conn:
        return await repos.drafts.insert(
            conn, ACME, name=name, owner="u1", bundle=StudioAgentBundle(name=name, definition=_def()),
            visibility="private", allowed_groups=(),
        )


@pytest.mark.parametrize("table", ["agents", "drafts"])
async def test_same_signals_delete_recreate_at_same_version_is_stale(repos, table) -> None:
    """The guard's ``authorized_id`` catches what versions cannot: a re-created row restarts at version 1."""
    make = (lambda: _agent(repos, ACME, "sales")) if table == "agents" else (lambda: _draft(repos, "sales"))
    repo = getattr(repos, table)
    old = await make()
    guard = StudioWriteGuard.for_record(old)
    async with studio_transaction(repos.pool) as conn:
        await repo.lock(conn, ACME, "sales", guard)                                # still the authorized row
        assert await repo.delete(conn, ACME, "sales")
    new = await make()
    assert new.version == old.version == 1 and getattr(new, "agent_id" if table == "agents" else "draft_id") != (
        getattr(old, "agent_id" if table == "agents" else "draft_id")
    )
    with pytest.raises(StudioStaleAuthorization):
        async with studio_transaction(repos.pool) as conn:
            await repo.lock(conn, ACME, "sales", guard)
    async with studio_transaction(repos.pool) as conn:
        await repo.lock(conn, ACME, "sales", StudioWriteGuard.for_record(new))     # the new row's own guard passes


async def test_same_signals_rollback_restores_state(repos) -> None:
    await _agent(repos, ACME, "keep")
    with pytest.raises(RuntimeError):
        async with studio_transaction(repos.pool) as conn:
            await repos.agents.insert(
                conn, ACME, name="gone", owner="u", definition=_def(), visibility="private", allowed_groups=()
            )
            await repos.agents.set_status(conn, ACME, "keep", "disabled")
            raise RuntimeError("boom")
    assert await repos.agents.get(ACME, "gone") is None
    kept = await repos.agents.get(ACME, "keep")
    assert kept.status == "active" and kept.version == 1
    with pytest.raises(StudioStorageError):                      # a failing statement rolls back the whole transaction
        async with studio_transaction(repos.pool) as conn:
            await repos.agents.insert(
                conn, ACME, name="half", owner="u", definition=_def(), visibility="private", allowed_groups=()
            )
            await repos.agents.insert(
                conn, ACME, name="bad:name", owner="u", definition=_def(), visibility="private", allowed_groups=()
            )
    assert await repos.agents.get(ACME, "half") is None
