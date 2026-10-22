"""FEAT-621 M3 — drafts and catalogue (AC6, AC7)."""

from uuid import uuid4

import pytest

from parrot.handlers.studio.storage.models import (
    StudioAgentBundle,
    StudioAgentDefinition,
    StudioNameConflict,
    StudioNotFound,
    StudioPartition,
    StudioStaleAuthorization,
    StudioStorageError,
    StudioVersionConflict,
    StudioWriteGuard,
)
from parrot.handlers.studio.storage.repositories import (
    StudioDraftRepository,
    StudioRepositories,
    StudioSkillCatalogRepository,
    build_studio_repositories,
    studio_transaction,
)

ACME, BETA, GLOBAL = StudioPartition("acme"), StudioPartition("beta"), StudioPartition.GLOBAL


@pytest.fixture
async def repos(studio_pool) -> StudioRepositories:
    from .conftest import _truncate_studio_tables

    await _truncate_studio_tables(studio_pool)
    return build_studio_repositories(studio_pool)


def _bundle(name: str = "sales") -> StudioAgentBundle:
    return StudioAgentBundle(name=name, definition=StudioAgentDefinition(description="d"))


async def _draft(repos, part, name, *, owner="u1", visibility="private", groups=()):
    async with studio_transaction(repos.pool) as conn:
        return await repos.drafts.insert(
            conn, part, name=name, owner=owner, bundle=_bundle(name), visibility=visibility, allowed_groups=groups
        )


async def _skill(repos, part, name, **kw):
    async with studio_transaction(repos.pool) as conn:
        return await repos.skills.insert(
            conn, part, owner=kw.pop("owner", "u1"), name=name, description="d", body="b", **kw
        )


async def test_build_studio_repositories(studio_pool) -> None:
    built = build_studio_repositories(studio_pool)
    assert built.pool is studio_pool
    assert all(r.pool is studio_pool for r in (built.agents, built.assets, built.tooling, built.drafts, built.skills))
    assert isinstance(built.drafts, StudioDraftRepository) and isinstance(built.skills, StudioSkillCatalogRepository)


async def test_unique_per_tenant_drafts_and_skills(repos) -> None:
    await _draft(repos, ACME, "sales")
    await _draft(repos, BETA, "sales")
    with pytest.raises(StudioNameConflict):
        await _draft(repos, ACME, "sales")
    await _draft(repos, GLOBAL, "sales")
    with pytest.raises(StudioNameConflict):
        await _draft(repos, GLOBAL, "sales")
    await _skill(repos, ACME, "triage")
    await _skill(repos, BETA, "triage")
    with pytest.raises(StudioNameConflict):
        await _skill(repos, ACME, "triage")
    await _skill(repos, GLOBAL, "triage")
    with pytest.raises(StudioNameConflict):
        await _skill(repos, GLOBAL, "triage")


async def test_partition_isolation_drafts_catalog(repos) -> None:
    draft = await _draft(repos, ACME, "sales")
    skill = await _skill(repos, ACME, "triage")
    assert await repos.drafts.get(BETA, "sales") is None and await repos.drafts.list(BETA) == []
    assert await repos.skills.get(BETA, skill.skill_id) is None
    assert await repos.skills.get_by_name(BETA, "triage") is None and await repos.skills.list(BETA) == []
    assert await repos.skills.list_stale(BETA) == []
    async with studio_transaction(repos.pool) as conn:
        with pytest.raises(StudioNotFound):
            await repos.drafts.lock(conn, BETA, "sales", StudioWriteGuard())
        with pytest.raises(StudioNotFound):
            await repos.drafts.update_bundle(conn, BETA, "sales", _bundle())
        with pytest.raises(StudioNotFound):
            await repos.drafts.set_status(conn, BETA, "sales", "failed")
        with pytest.raises(StudioNotFound):
            await repos.drafts.update_visibility(conn, BETA, "sales", visibility="private", allowed_groups=())
        assert await repos.drafts.delete(conn, BETA, "sales") is False
        assert await repos.skills.update(conn, BETA, skill.skill_id, description="x") is None
        assert (
            await repos.skills.update_visibility(conn, BETA, skill.skill_id, visibility="private", allowed_groups=())
            is None
        )
        assert await repos.skills.mark_stale(conn, BETA, skill.skill_id) is False
        assert await repos.skills.delete(conn, BETA, skill.skill_id) is False
    assert await repos.drafts.get(ACME, "sales") == draft
    assert await repos.skills.get(ACME, skill.skill_id) == skill


async def test_draft_roundtrip_and_owner_filter(repos) -> None:
    created = await _draft(repos, ACME, "sales", owner="u1", visibility="groups", groups=("g",))
    assert created.version == 1 and created.status == "draft" and created.activated_agent_id is None
    assert created.bundle == _bundle() and created.allowed_groups == ("g",) and created.validation == {}
    assert await repos.drafts.get(ACME, "sales") == created
    await _draft(repos, ACME, "other", owner="u2")
    assert [d.name for d in await repos.drafts.list(ACME)] == ["other", "sales"]
    assert [d.name for d in await repos.drafts.list(ACME, owner="u2")] == ["other"]


async def test_draft_lock_guard_and_version_bump(repos) -> None:
    await _draft(repos, ACME, "sales")
    async with studio_transaction(repos.pool) as conn:
        head = await repos.drafts.lock(conn, ACME, "sales", StudioWriteGuard(expected_version=1, authorized_version=1))
        assert head.version == 1
        with pytest.raises(StudioNotFound):
            await repos.drafts.lock(conn, ACME, "ghost", StudioWriteGuard(expected_version=9))
        with pytest.raises(StudioVersionConflict):
            await repos.drafts.lock(conn, ACME, "sales", StudioWriteGuard(expected_version=2, authorized_version=2))
        with pytest.raises(StudioStaleAuthorization):
            await repos.drafts.lock(conn, ACME, "sales", StudioWriteGuard(authorized_version=2))
    new_bundle = StudioAgentBundle(name="sales", definition=StudioAgentDefinition(description="v2"))
    async with studio_transaction(repos.pool) as conn:
        upd = await repos.drafts.update_bundle(conn, ACME, "sales", new_bundle, validation={"ok": True})
    assert upd.version == 2 and upd.bundle == new_bundle and upd.validation == {"ok": True}
    async with studio_transaction(repos.pool) as conn:
        again = await repos.drafts.update_bundle(conn, ACME, "sales", _bundle())  # validation kept when omitted
    assert again.version == 3 and again.validation == {"ok": True}
    async with studio_transaction(repos.pool) as conn:
        vis = await repos.drafts.update_visibility(conn, ACME, "sales", visibility="tenant", allowed_groups=[])
    assert vis.version == 4 and vis.visibility == "tenant"
    agent_id = uuid4()
    with pytest.raises(StudioStorageError):  # FK to ai_agents
        async with studio_transaction(repos.pool) as conn:
            await repos.drafts.set_status(conn, ACME, "sales", "activated", activated_agent_id=agent_id)
    assert (await repos.drafts.get(ACME, "sales")).status == "draft"
    async with studio_transaction(repos.pool) as conn:
        agent = await repos.agents.insert(
            conn,
            ACME,
            name="sales",
            owner="u1",
            definition=StudioAgentDefinition(),
            visibility="private",
            allowed_groups=(),
        )
        done = await repos.drafts.set_status(conn, ACME, "sales", "activated", activated_agent_id=agent.agent_id)
    assert done.status == "activated" and done.activated_agent_id == agent.agent_id and done.version == 5
    async with studio_transaction(repos.pool) as conn:
        assert await repos.drafts.delete(conn, ACME, "sales") is True
        assert await repos.drafts.delete(conn, ACME, "sales") is False
    assert await repos.drafts.get(ACME, "sales") is None


async def test_draft_constraints(repos) -> None:
    with pytest.raises(StudioStorageError):  # shared visibility needs a tenant
        await _draft(repos, GLOBAL, "g", visibility="tenant")
    assert await repos.drafts.get(GLOBAL, "g") is None


async def test_catalog_crud_and_versions(repos) -> None:
    sid = uuid4()
    skill = await _skill(repos, ACME, "triage", skill_id=sid, category="ops", triggers=["/t", {"k": 1}], owner="u1")
    assert skill.skill_id == sid and skill.version == 1 and skill.status == "active" and not skill.search_index_stale
    assert skill.triggers == ["/t", {"k": 1}] and skill.category == "ops" and skill.visibility == "private"
    assert await repos.skills.get(ACME, sid) == skill and await repos.skills.get_by_name(ACME, "triage") == skill
    other = await _skill(repos, ACME, "alpha", owner="u2")
    assert [s.name for s in await repos.skills.list(ACME)] == ["alpha", "triage"]
    assert [s.name for s in await repos.skills.list(ACME, category="ops")] == ["triage"]
    assert [s.name for s in await repos.skills.list(ACME, owner="u2")] == ["alpha"]
    assert other.category == "general"
    async with studio_transaction(repos.pool) as conn:
        upd = await repos.skills.update(conn, ACME, sid, description="new", body="B2", triggers=[])
    assert (upd.description, upd.body, upd.triggers, upd.category, upd.version) == ("new", "B2", [], "ops", 2)
    async with studio_transaction(repos.pool) as conn:
        vis = await repos.skills.update_visibility(conn, ACME, sid, visibility="groups", allowed_groups=["g"])
    assert (vis.visibility, vis.allowed_groups, vis.version) == ("groups", ("g",), 3)
    with pytest.raises(StudioNameConflict):  # rename onto an existing name
        async with studio_transaction(repos.pool) as conn:
            await repos.skills.update(conn, ACME, sid, name="alpha")
    async with studio_transaction(repos.pool) as conn:
        assert await repos.skills.delete(conn, ACME, sid) is True
        assert await repos.skills.delete(conn, ACME, sid) is False
    assert await repos.skills.get(ACME, sid) is None


async def test_catalog_constraints(repos) -> None:
    with pytest.raises(StudioStorageError):
        await _skill(repos, GLOBAL, "s", visibility="tenant")
    with pytest.raises(StudioStorageError):
        await _skill(repos, ACME, "s", visibility="public")


async def test_catalog_mark_and_list_stale(repos) -> None:
    a = await _skill(repos, ACME, "a")
    await _skill(repos, ACME, "b")
    assert await repos.skills.list_stale(ACME) == []
    async with studio_transaction(repos.pool) as conn:
        assert await repos.skills.mark_stale(conn, ACME, a.skill_id) is True
        assert await repos.skills.mark_stale(conn, ACME, uuid4()) is False
    stale = await repos.skills.list_stale(ACME)
    assert [(s.name, s.search_index_stale, s.version) for s in stale] == [("a", True, 1)]
    async with studio_transaction(repos.pool) as conn:
        await repos.skills.mark_stale(conn, ACME, a.skill_id, False)
    assert await repos.skills.list_stale(ACME) == []
