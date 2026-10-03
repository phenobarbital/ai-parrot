"""FEAT-621 M6 — catalogue service (AC4, AC6, AC7). Runs on the in-memory repositories and on real Postgres."""
from pathlib import Path
from uuid import uuid4

import pytest

from parrot.handlers.models.skills_catalog import SkillCatalogEntry
from parrot.handlers.studio.storage.models import (
    StudioAgentDefinition,
    StudioNameConflict,
    StudioNotFound,
    StudioPartition,
    StudioVersionConflict,
    StudioWriteGuard,
)
from parrot.handlers.studio.storage.repositories import build_studio_repositories, studio_transaction
from parrot.handlers.studio.storage.services._common import (
    StudioLimits,
    StudioToolingGate,
    StudioValidationError,
)
from parrot.handlers.studio.storage.services.assets import StudioAssetService
from parrot.handlers.studio.storage.services.catalog import StudioSkillCatalogService, shared_index_location
from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories

ACME = StudioPartition("acme")
OTHER = StudioPartition("other")
GLOBAL = StudioPartition.GLOBAL
NO_GUARD = StudioWriteGuard()


@pytest.fixture(params=["memory", "postgres"])
def repos(request):
    if request.param == "memory":
        return InMemoryStudioRepositories()
    return build_studio_repositories(request.getfixturevalue("studio_pool"))


@pytest.fixture
def svc(repos):
    assets = StudioAssetService(repos, limits=StudioLimits(), tooling_gate=StudioToolingGate({}))
    return StudioSkillCatalogService(repos, assets=assets)


async def _agent(repos, part=GLOBAL, name="a1"):
    async with studio_transaction(repos.pool) as conn:
        return await repos.agents.insert(
            conn, part, name=name, owner="u1", definition=StudioAgentDefinition(), visibility="private",
            allowed_groups=(),
        )


async def _publish(svc, part=GLOBAL, name="s1", **kw):
    return await svc.publish(part, owner="u1", name=name, description="does things", body="Body text.", **kw)


async def test_publish_unique_per_partition(svc):
    first = await _publish(svc, GLOBAL)
    with pytest.raises(StudioNameConflict):                      # tenant NULL is a partition of its own
        await _publish(svc, GLOBAL)
    await _publish(svc, ACME)                                    # same name in another partition is fine
    await _publish(svc, OTHER)
    with pytest.raises(StudioNameConflict):
        await _publish(svc, ACME)
    assert [s.name for s in await svc.list(GLOBAL)] == ["s1"] and (await svc.get(GLOBAL, first.skill_id)).name == "s1"
    assert await svc.get(ACME, first.skill_id) is None            # partitioned lookup


async def test_update_list_filters_and_delete(svc):
    s = await _publish(svc, ACME, category="ops", triggers=["/s1"])
    await _publish(svc, ACME, name="s2")
    upd = await svc.update(ACME, s.skill_id, description="new", body="B2")
    assert (upd.description, upd.body, upd.name, upd.version) == ("new", "B2", "s1", s.version + 1)
    assert [x.name for x in await svc.list(ACME, category="ops")] == ["s1"]
    assert [x.name for x in await svc.list(ACME, owner="nobody")] == []
    with pytest.raises(StudioNotFound):
        await svc.update(GLOBAL, s.skill_id, description="cross-partition")
    with pytest.raises(StudioNameConflict):
        await svc.update(ACME, s.skill_id, name="s2")
    assert await svc.delete(GLOBAL, s.skill_id) is False and await svc.delete(ACME, s.skill_id) is True
    assert [x.name for x in await svc.list(ACME)] == ["s2"]


async def test_stale_flag_roundtrip(svc):
    s = await _publish(svc)
    assert await svc.list_stale(GLOBAL) == []
    assert await svc.mark_stale(GLOBAL, s.skill_id) is True
    assert [x.skill_id for x in await svc.list_stale(GLOBAL)] == [s.skill_id]
    await svc.mark_stale(GLOBAL, s.skill_id, False)
    assert await svc.list_stale(GLOBAL) == [] and await svc.mark_stale(GLOBAL, uuid4()) is False


async def test_update_visibility_tenant_null_private_only(svc):
    g = await _publish(svc, GLOBAL)
    with pytest.raises(StudioValidationError) as exc:
        await svc.update_visibility(GLOBAL, g.skill_id, visibility="tenant", allowed_groups=())
    assert exc.value.code == "invalid_visibility"
    with pytest.raises(StudioValidationError):
        await _publish(svc, GLOBAL, name="s9", visibility="groups", allowed_groups=["g1"])
    t = await _publish(svc, ACME)
    shared = await svc.update_visibility(ACME, t.skill_id, visibility="groups", allowed_groups=["g1"])
    assert (shared.visibility, shared.allowed_groups) == ("groups", ("g1",))
    with pytest.raises(StudioNotFound):
        await svc.update_visibility(ACME, uuid4(), visibility="tenant", allowed_groups=())


async def test_import_to_agent_writes_asset_row_under_lock(repos, svc):
    from parrot.handlers.studio.skills_catalog import _compose_skill_markdown

    await _agent(repos)
    skill = await _publish(svc, GLOBAL, triggers=["/s1"])
    rec, version = await svc.import_to_agent(GLOBAL, skill.skill_id, "a1", actor="u1", guard=NO_GUARD)
    assert (rec.kind, rec.name) == ("skills", "s1.md")
    stored = await repos.assets.get(GLOBAL, "a1", "skills", "s1.md")
    assert stored.content == _compose_skill_markdown(skill) and "Body text." in stored.content
    assert (await repos.agents.get_version(GLOBAL, "a1")).version == version
    stale = StudioWriteGuard(expected_version=version + 7)          # the agent lock + guard applies to the import
    with pytest.raises(StudioVersionConflict):
        await svc.import_to_agent(GLOBAL, skill.skill_id, "a1", actor="u1", guard=stale)
    with pytest.raises(StudioNotFound):
        await svc.import_to_agent(GLOBAL, uuid4(), "a1", actor="u1", guard=NO_GUARD)
    with pytest.raises(StudioNotFound):                              # another partition's skill is invisible
        await svc.import_to_agent(ACME, skill.skill_id, "a1", actor="u1", guard=NO_GUARD)


async def test_import_nothing_under_agents_dir(repos, svc):
    from parrot.conf import AGENTS_DIR

    root = Path(AGENTS_DIR)
    before = sorted(str(p) for p in root.rglob("*")) if root.exists() else []
    await _agent(repos)
    skill = await _publish(svc)
    await svc.import_to_agent(GLOBAL, skill.skill_id, "a1", actor="u1", guard=NO_GUARD)
    assert (sorted(str(p) for p in root.rglob("*")) if root.exists() else []) == before


def test_shared_index_location_not_in_agents_dir(tmp_path, monkeypatch):
    from parrot.conf import AGENTS_DIR

    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(tmp_path))
    ns, path = shared_index_location(ACME, "org1")
    assert ns == "acme/_shared" and path == tmp_path / "_shared" / "acme" / "skills"
    ns, path = shared_index_location(GLOBAL, "org1")
    assert ns == "org1/_shared" and path == tmp_path / "_shared" / "-" / "skills"
    assert Path(AGENTS_DIR).resolve() not in path.resolve().parents
    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(Path(AGENTS_DIR) / "inside"))
    with pytest.raises(StudioValidationError):
        shared_index_location(ACME, "org1")


def test_catalog_entry_model_carries_tenancy_fields():
    entry = SkillCatalogEntry(name="a", description="d", owner="o", body="b")
    assert (entry.tenant, entry.visibility, entry.allowed_groups) == (None, "private", [])
    shared = SkillCatalogEntry(name="a", description="d", owner="o", body="b", tenant="acme", visibility="groups",
                               allowed_groups=["g"])
    assert (shared.tenant, shared.visibility, shared.allowed_groups) == ("acme", "groups", ["g"])
