"""FEAT-621 M3 — child repositories (AC7, version bump)."""
from datetime import datetime, timezone
from hashlib import sha256

import pytest

from parrot.handlers.studio.storage.models import (
    StudioAgentDefinition,
    StudioAssetInput,
    StudioNameConflict,
    StudioPartition,
    StudioStorageError,
    StudioToolingRecord,
    StudioWriteGuard,
)
from parrot.handlers.studio.storage.repositories import (
    StudioAgentRepository,
    StudioAssetRepository,
    StudioToolingRepository,
    studio_transaction,
)

ACME, BETA = StudioPartition("acme"), StudioPartition("beta")


@pytest.fixture
async def repos(studio_pool):
    from .conftest import _truncate_studio_tables

    await _truncate_studio_tables(studio_pool)
    agents = StudioAgentRepository(studio_pool)
    async with studio_transaction(studio_pool) as conn:
        rec = await agents.insert(
            conn, ACME, name="sales", owner="u1", definition=StudioAgentDefinition(),
            visibility="private", allowed_groups=(),
        )
    return agents, StudioAssetRepository(studio_pool), StudioToolingRepository(studio_pool), rec


def _asset(kind: str, name: str, content: str) -> StudioAssetInput:
    return StudioAssetInput(kind=kind, name=name, content=content)


def _tool(kind: str, slug: str, **kw) -> StudioToolingRecord:
    return StudioToolingRecord(
        agent_id=None, kind=kind, slug=slug, position=-1, config=kw.get("config", {}),
        secret_refs=kw.get("secret_refs", {}), vault_owner=kw.get("vault_owner"), updated_at=datetime.now(timezone.utc),
    )


async def _put(assets, agents, conn, rec, a: StudioAssetInput):
    head = await agents.lock(conn, ACME, rec.name, StudioWriteGuard())
    return await assets.put(conn, head.agent_id, a, sha256=sha256(a.content.encode()).hexdigest())


async def test_partition_isolation_children(repos) -> None:
    agents, assets, tooling, rec = repos
    async with studio_transaction(assets.pool) as conn:
        await _put(assets, agents, conn, rec, _asset("kb", "a.md", "hello"))
        head = await agents.lock(conn, ACME, "sales", StudioWriteGuard())
        await tooling.replace(conn, head.agent_id, toolkits=[_tool("toolkit", "jira")], mcp_servers=[])
    assert [a.name for a in await assets.list(ACME, "sales")] == ["a.md"]
    assert [t.slug for t in await tooling.list(ACME, "sales")] == ["jira"]
    assert await assets.list(BETA, "sales") == []
    assert await assets.get(BETA, "sales", "kb", "a.md") is None
    assert await tooling.list(BETA, "sales") == []
    assert await assets.get(ACME, "sales", "kb", "a.md") is not None
    # an agent in beta with the same name does not see acme's children
    async with studio_transaction(assets.pool) as conn:
        await agents.insert(conn, BETA, name="sales", owner="u2", definition=StudioAgentDefinition(),
                            visibility="private", allowed_groups=())
    assert await assets.list(BETA, "sales") == [] and await tooling.list(BETA, "sales") == []


async def test_version_bumps_on_child_write(repos) -> None:
    agents, assets, tooling, rec = repos
    assert (await agents.get_version(ACME, "sales")).version == 1
    async with studio_transaction(assets.pool) as conn:
        await _put(assets, agents, conn, rec, _asset("identity", "role.md", "you are"))
    v_asset = (await agents.get_version(ACME, "sales")).version
    assert v_asset > 1
    async with studio_transaction(assets.pool) as conn:
        head = await agents.lock(conn, ACME, "sales", StudioWriteGuard())
        await tooling.replace(conn, head.agent_id, toolkits=[_tool("toolkit", "jira")], mcp_servers=[])
    v_tool = (await agents.get_version(ACME, "sales")).version
    assert v_tool > v_asset
    async with studio_transaction(assets.pool) as conn:
        head = await agents.lock(conn, ACME, "sales", StudioWriteGuard())
        assert await assets.delete(conn, head.agent_id, "identity", "role.md") is True
        assert await assets.delete(conn, head.agent_id, "identity", "role.md") is False
    assert (await agents.get_version(ACME, "sales")).version > v_tool


async def test_total_size_and_replace_all(repos) -> None:
    agents, assets, tooling, rec = repos
    async with studio_transaction(assets.pool) as conn:
        head = await agents.lock(conn, ACME, "sales", StudioWriteGuard())
        assert await assets.total_size(conn, head.agent_id) == 0
        first = await assets.put(conn, head.agent_id, _asset("kb", "a.md", "héllo"), sha256="a" * 64)
        assert first.size == len("héllo".encode()) == 6 and first.sha256 == "a" * 64 and first.content == "héllo"
        await assets.put(conn, head.agent_id, _asset("kb", "b.md", "xy"), sha256="b" * 64)
        assert await assets.total_size(conn, head.agent_id) == 8
        again = await assets.put(conn, head.agent_id, _asset("kb", "a.md", "z"), sha256="c" * 64)   # upsert
        assert again.size == 1 and await assets.total_size(conn, head.agent_id) == 3
        await assets.replace_all(conn, head.agent_id, [_asset("identity", "role.md", "R"), _asset("skills", "s/SKILL.md", "S")])
        assert await assets.total_size(conn, head.agent_id) == 2
    listed = await assets.list(ACME, "sales")
    assert [(a.kind, a.name, a.content) for a in listed] == [("identity", "role.md", None), ("skills", "s/SKILL.md", None)]
    assert [a.name for a in await assets.list(ACME, "sales", "skills")] == ["s/SKILL.md"]
    full = await assets.get(ACME, "sales", "identity", "role.md")
    assert full.content == "R" and full.sha256 == sha256(b"R").hexdigest()


async def test_asset_violation_raises_and_rolls_back(repos) -> None:
    agents, assets, tooling, rec = repos
    with pytest.raises(StudioStorageError):
        async with studio_transaction(assets.pool) as conn:
            head = await agents.lock(conn, ACME, "sales", StudioWriteGuard())
            await assets.put(conn, head.agent_id, _asset("kb", "ok.md", "fine"), sha256="a" * 64)
            await assets.put(conn, head.agent_id, _asset("kb", "../evil.md", "x"), sha256="a" * 64)   # name CHECK
    assert await assets.list(ACME, "sales") == []


async def test_tooling_replace_keeps_position_order(repos) -> None:
    agents, assets, tooling, rec = repos
    async with studio_transaction(assets.pool) as conn:
        head = await agents.lock(conn, ACME, "sales", StudioWriteGuard())
        await tooling.replace(
            conn, head.agent_id,
            toolkits=[_tool("toolkit", "zeta", config={"a": 1}), _tool("toolkit", "alpha", secret_refs={"token": "v"},
                                                                       vault_owner="u1")],
            mcp_servers=[_tool("mcp", "docs"), _tool("mcp", "web")],
        )
        locked = await tooling.list_locked(conn, head.agent_id)
    assert [(t.kind, t.slug, t.position) for t in locked] == [
        ("mcp", "docs", 0), ("mcp", "web", 1), ("toolkit", "zeta", 0), ("toolkit", "alpha", 1)]
    listed = await tooling.list(ACME, "sales")
    assert [(t.kind, t.slug, t.position) for t in listed] == [(t.kind, t.slug, t.position) for t in locked]
    by_slug = {t.slug: t for t in listed}
    assert by_slug["zeta"].config == {"a": 1}
    assert by_slug["alpha"].secret_refs == {"token": "v"} and by_slug["alpha"].vault_owner == "u1"
    async with studio_transaction(assets.pool) as conn:                       # replace is total, not a merge
        head = await agents.lock(conn, ACME, "sales", StudioWriteGuard())
        await tooling.replace(conn, head.agent_id, toolkits=[_tool("toolkit", "only")], mcp_servers=[])
    assert [(t.kind, t.slug) for t in await tooling.list(ACME, "sales")] == [("toolkit", "only")]
    with pytest.raises(StudioNameConflict):                                    # duplicate slug in one replace
        async with studio_transaction(assets.pool) as conn:
            head = await agents.lock(conn, ACME, "sales", StudioWriteGuard())
            await tooling.replace(conn, head.agent_id, toolkits=[_tool("toolkit", "d"), _tool("toolkit", "d")],
                                  mcp_servers=[])
    assert [(t.kind, t.slug) for t in await tooling.list(ACME, "sales")] == [("toolkit", "only")]
