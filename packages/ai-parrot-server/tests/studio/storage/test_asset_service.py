"""FEAT-621 M5 — asset service (AC4, AC8, AC13). Validation paths on both backends; concurrency on real PG."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parrot.handlers.studio.storage.models import (
    StudioAgentDefinition,
    StudioAssetInput,
    StudioAssetTooLarge,
    StudioPartition,
    StudioToolingRecord,
    StudioToolingRefused,
    StudioVersionConflict,
    StudioWriteGuard,
)
from parrot.handlers.studio.storage.repositories import build_studio_repositories, studio_transaction
from parrot.handlers.studio.storage.services._common import (
    StudioClassAllowlist,
    StudioAgentAssetsQuota,
    StudioLimits,
    StudioToolingGate,
    StudioValidationError,
)
from parrot.handlers.studio.storage.services.assets import StudioAssetService
from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories

ACME = StudioPartition("acme")
GLOBAL = StudioPartition.GLOBAL
NO_GUARD = StudioWriteGuard()
SKILL = "---\nname: s1\ndescription: does things\ntriggers:\n  - /s1\n---\nBody of the skill.\n"


@pytest.fixture(params=["memory", "postgres"])
def repos(request):
    if request.param == "memory":
        return InMemoryStudioRepositories()
    return build_studio_repositories(request.getfixturevalue("studio_pool"))


def _svc(repos, limits=None):
    return StudioAssetService(repos, limits=limits or StudioLimits(), tooling_gate=StudioToolingGate({}))


async def _agent(repos, part=GLOBAL, name="a1"):
    async with studio_transaction(repos.pool) as conn:
        return await repos.agents.insert(
            conn, part, name=name, owner="u1", definition=StudioAgentDefinition(), visibility="private",
            allowed_groups=(),
        )


def _asset(kind="kb", name="n.md", content="hello"):
    return StudioAssetInput(kind=kind, name=name, content=content)


async def test_put_validates_kind_and_filename(repos):
    svc = _svc(repos)
    await _agent(repos)
    rec, _ = await svc.put(GLOBAL, "a1", _asset("identity", "role.md", "You are X"), actor="u1", guard=NO_GUARD)
    assert rec.size == 9 and rec.sha256 and rec.content_type == "text/markdown"
    for bad in (
        _asset("identity", "other.md"), _asset("kb", "sub/n.md"), _asset("kb", "n.pdf"), _asset("skills", "a/b/c.md"),
        _asset("kb", "../n.md"), _asset("kb", "/abs.md"), _asset("kb", "a\\b.md"), _asset("kb", "n\x00.md"),
        _asset("skills", "../x/SKILL.md"), _asset("skills", "x//SKILL.md"),
    ):
        with pytest.raises(StudioValidationError) as exc:
            await svc.put(GLOBAL, "a1", bad, actor="u1", guard=NO_GUARD)
        assert exc.value.code == "invalid_asset_name", bad.name
    with pytest.raises(StudioValidationError) as exc:
        await svc.put(GLOBAL, "a1", StudioAssetInput(kind="kb", name="n.md", content="x", content_type="image/png"),
                      actor="u1", guard=NO_GUARD)
    assert exc.value.status == 415
    assert [a.name for a in await svc.list(GLOBAL, "a1")] == ["role.md"]


async def test_oversize_maps_to_asset_too_large_before_any_write(repos):
    svc = _svc(repos, StudioLimits(kb_max=8))
    await _agent(repos)
    with pytest.raises(StudioAssetTooLarge) as exc:
        await svc.put(GLOBAL, "a1", _asset(content="123456789"), actor="u1", guard=NO_GUARD)
    assert exc.value.code == "asset_too_large" and await svc.list(GLOBAL, "a1") == []


async def test_skill_frontmatter_required(repos):
    svc = _svc(repos)
    await _agent(repos)
    with pytest.raises(StudioValidationError) as exc:
        await svc.put(GLOBAL, "a1", _asset("skills", "s1.md", "no frontmatter at all"), actor="u1", guard=NO_GUARD)
    assert exc.value.code == "invalid_skill"
    await svc.put(GLOBAL, "a1", _asset("skills", "s1.md", SKILL), actor="u1", guard=NO_GUARD)
    await svc.put(GLOBAL, "a1", _asset("skills", "s1/helper.txt", "adjacent asset, unvalidated"), actor="u1",
                  guard=NO_GUARD)
    assert sorted(a.name for a in await svc.list(GLOBAL, "a1", "skills")) == ["s1.md", "s1/helper.txt"]


async def test_quota_counts_replacement_not_addition(repos):
    svc = _svc(repos, StudioLimits(kb_max=10, agent_total_max=15))
    await _agent(repos)
    await svc.put(GLOBAL, "a1", _asset(name="a.md", content="x" * 10), actor="u1", guard=NO_GUARD)
    with pytest.raises(StudioAgentAssetsQuota) as exc:
        await svc.put(GLOBAL, "a1", _asset(name="b.md", content="x" * 10), actor="u1", guard=NO_GUARD)
    assert exc.value.code == "agent_assets_quota"
    await svc.put(GLOBAL, "a1", _asset(name="a.md", content="y" * 10), actor="u1", guard=NO_GUARD)   # replace: 10 - 10 + 10
    await svc.put(GLOBAL, "a1", _asset(name="b.md", content="z" * 5), actor="u1", guard=NO_GUARD)    # exactly 15
    assert [a.name for a in await svc.list(GLOBAL, "a1")] == ["a.md", "b.md"]


async def test_version_bumps_on_asset_write(repos):
    svc = _svc(repos)
    rec = await _agent(repos)
    _, v1 = await svc.put(GLOBAL, "a1", _asset(), actor="u1", guard=NO_GUARD)
    existed, v2 = await svc.delete(GLOBAL, "a1", "kb", "n.md", actor="u1", guard=NO_GUARD)
    assert existed is True and rec.version < v1 < v2
    assert (await repos.agents.get_version(GLOBAL, "a1")).version == v2
    assert (await svc.delete(GLOBAL, "a1", "kb", "n.md", actor="u1", guard=NO_GUARD))[0] is False


async def test_get_returns_content(repos):
    svc = _svc(repos)
    await _agent(repos)
    await svc.put(GLOBAL, "a1", _asset(content="body"), actor="u1", guard=NO_GUARD)
    assert (await svc.get(GLOBAL, "a1", "kb", "n.md")).content == "body"
    assert await svc.get(ACME, "a1", "kb", "n.md") is None


async def test_asset_write_rechecks_tooling(repos):
    svc = _svc(repos)
    rec = await _agent(repos, ACME)
    async with studio_transaction(repos.pool) as conn:
        await repos.tooling.replace(
            conn, rec.agent_id, toolkits=[],
            mcp_servers=[StudioToolingRecord(None, "mcp", "s", 0, {"transport": "stdio", "command": "/bin/sh"}, {},
                                             None, datetime.now(timezone.utc))],
        )
    with pytest.raises(StudioToolingRefused):
        await svc.put(ACME, "a1", _asset(), actor="u1", guard=NO_GUARD)
    with pytest.raises(StudioToolingRefused):
        await svc.delete(ACME, "a1", "kb", "n.md", actor="u1", guard=NO_GUARD)
    assert await svc.list(ACME, "a1") == []


async def test_stale_expected_version_assets(repos):
    svc = _svc(repos)
    rec = await _agent(repos)
    stale = StudioWriteGuard(expected_version=rec.version + 4)
    with pytest.raises(StudioVersionConflict):
        await svc.put(GLOBAL, "a1", _asset(), actor="u1", guard=stale)
    with pytest.raises(StudioVersionConflict):
        await svc.delete(GLOBAL, "a1", "kb", "n.md", actor="u1", guard=stale)
    assert await svc.list(GLOBAL, "a1") == []


async def test_nothing_under_agents_dir(repos):
    from parrot.conf import AGENTS_DIR

    root = Path(AGENTS_DIR)
    before = sorted(str(p) for p in root.rglob("*")) if root.exists() else []
    svc = _svc(repos)
    await _agent(repos)
    await svc.put(GLOBAL, "a1", _asset(), actor="u1", guard=NO_GUARD)
    assert (sorted(str(p) for p in root.rglob("*")) if root.exists() else []) == before


async def test_concurrent_quota(studio_pool):
    repos = build_studio_repositories(studio_pool)
    svc = _svc(repos, StudioLimits(kb_max=10, agent_total_max=15))
    await _agent(repos)
    results = await asyncio.gather(
        svc.put(GLOBAL, "a1", _asset(name="a.md", content="x" * 10), actor="u1", guard=NO_GUARD),
        svc.put(GLOBAL, "a1", _asset(name="b.md", content="y" * 10), actor="u1", guard=NO_GUARD),
        return_exceptions=True,
    )
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(failures) == 1 and isinstance(failures[0], StudioAgentAssetsQuota)
    assert len(await svc.list(GLOBAL, "a1")) == 1


@pytest.mark.parametrize("content", ["bad\x00nul", "lone \ud800 surrogate", "\udfff"])
async def test_nul_and_lone_surrogates_are_a_422_not_a_500(repos, content):
    svc = _svc(repos)
    await _agent(repos)
    with pytest.raises(StudioValidationError) as exc:
        await svc.put(GLOBAL, "a1", _asset(content=content), actor="u1", guard=NO_GUARD)
    assert exc.value.code == "invalid_asset_content" and exc.value.status == 422
    assert await svc.list(GLOBAL, "a1") == []
    from parrot.handlers.studio.storage.services.agents import StudioAgentService  # the bundle path validates too

    agents = StudioAgentService(
        repos, limits=StudioLimits(), class_allowlist=StudioClassAllowlist(), tooling=None,
        tooling_gate=StudioToolingGate({}),
    )
    with pytest.raises(StudioValidationError):
        agents.validate_assets([_asset(content=content)])
