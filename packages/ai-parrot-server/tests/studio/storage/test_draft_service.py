"""FEAT-621 M6 — draft service (AC8, AC13, AC15). Validation paths on both backends; concurrency on real PG."""
import asyncio

import pytest

from parrot.handlers.studio.storage.models import (
    StudioAgentBundle,
    StudioAgentDefinition,
    StudioAssetInput,
    StudioNameConflict,
    StudioPartition,
    StudioStorageError,
    StudioToolingRefused,
    StudioVersionConflict,
    StudioWriteGuard,
)
from parrot.handlers.studio.storage.repositories import build_studio_repositories, studio_transaction
from parrot.handlers.studio.storage.services._common import (
    StudioClassAllowlist,
    StudioLimits,
    StudioToolingGate,
    StudioValidationError,
)
from parrot.handlers.studio.storage.services.agents import StudioAgentService
from parrot.handlers.studio.storage.services.drafts import StudioDraftService
from parrot.handlers.studio.storage.services.tooling import StudioToolingService
from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories
from parrot.tools.spec import AgentMCPServerSpec, ToolkitSpec

ACME = StudioPartition("acme")
GLOBAL = StudioPartition.GLOBAL
NO_GUARD = StudioWriteGuard()


@pytest.fixture(params=["memory", "postgres"])
def repos(request):
    if request.param == "memory":
        return InMemoryStudioRepositories()
    return build_studio_repositories(request.getfixturevalue("studio_pool"))


def _services(repos):
    gate = StudioToolingGate({})
    agents = StudioAgentService(
        repos, limits=StudioLimits(), class_allowlist=StudioClassAllowlist(),
        tooling=StudioToolingService(repos, gate=gate), tooling_gate=gate,
    )
    return agents, StudioDraftService(repos, agents=agents, tooling_gate=gate)


@pytest.fixture
def svc(repos):
    return _services(repos)[1]


def _bundle(name="a1", description="d", toolkits=(), mcp_servers=(), assets=()):
    return StudioAgentBundle(
        name=name, definition=StudioAgentDefinition(description=description), toolkits=list(toolkits),
        mcp_servers=list(mcp_servers), assets=list(assets),
    )


def _asset(name="n.md", content="hello", kind="kb"):
    return StudioAssetInput(kind=kind, name=name, content=content)


async def test_python_drafts_gate(svc, monkeypatch):
    assert svc.python_drafts_allowed(GLOBAL) is True
    assert svc.python_drafts_allowed(ACME) is False
    monkeypatch.setenv("STUDIO_PYTHON_DRAFTS", "false")
    assert svc.python_drafts_allowed(GLOBAL) is False
    monkeypatch.setenv("STUDIO_PYTHON_DRAFTS", "true")
    assert svc.python_drafts_allowed(ACME) is False


async def test_save_bundle_creates_then_updates(svc):
    d1 = await svc.save_bundle(ACME, owner="u1", bundle=_bundle(), visibility="groups", allowed_groups=["g1"])
    assert (d1.status, d1.visibility, d1.allowed_groups, d1.owner) == ("draft", "groups", ("g1",), "u1")
    d2 = await svc.save_bundle(ACME, owner="u1", bundle=_bundle(description="v2"))
    assert d2.draft_id == d1.draft_id and d2.bundle.definition.description == "v2" and d2.version > d1.version
    assert (await svc.get(ACME, "a1")).bundle.definition.description == "v2" and await svc.get(GLOBAL, "a1") is None
    assert [d.name for d in await svc.list(ACME)] == ["a1"] and await svc.list(ACME, owner="zz") == []


async def test_bundle_rejects_secret_fields(svc):
    with pytest.raises(ValueError):
        _bundle(toolkits=[ToolkitSpec(slug="jira", secret_refs={"token": "x"}, vault_owner="u")])
    smuggled = StudioAgentBundle.model_construct(      # built behind the model validator: the service re-checks
        name="a1", definition=StudioAgentDefinition(),
        toolkits=[ToolkitSpec(slug="jira", params={"api_token": "s3cret"})], mcp_servers=[], assets=[],
    )
    with pytest.raises(StudioValidationError) as exc:
        await svc.save_bundle(GLOBAL, owner="u1", bundle=smuggled)
    assert exc.value.code == "secrets_not_allowed" and await svc.list(GLOBAL) == []
    with pytest.raises(StudioValidationError) as exc:
        await svc.save_bundle(GLOBAL, owner="u1", bundle=_bundle(name="Bad:Name"))
    assert exc.value.code == "invalid_name"


async def test_save_bundle_policy_refusal(svc):
    mcp = AgentMCPServerSpec(name="s", transport="stdio", command="/bin/sh")
    with pytest.raises(StudioToolingRefused) as exc:
        await svc.save_bundle(ACME, owner="u1", bundle=_bundle(mcp_servers=[mcp]))
    assert exc.value.code == "tooling_not_permitted" and await svc.list(ACME) == []


async def test_stale_draft_update(svc):
    d = await svc.save_bundle(GLOBAL, owner="u1", bundle=_bundle())
    stale = StudioWriteGuard(expected_version=d.version + 5)
    with pytest.raises(StudioVersionConflict):
        await svc.save_bundle(GLOBAL, owner="u1", bundle=_bundle(description="x"), guard=stale)
    with pytest.raises(StudioVersionConflict):
        await svc.delete(GLOBAL, "a1", guard=stale)
    with pytest.raises(StudioVersionConflict):
        await svc.update_visibility(GLOBAL, "a1", visibility="private", allowed_groups=(), guard=stale)
    assert (await svc.get(GLOBAL, "a1")).bundle.definition.description == "d"


async def test_visibility_and_delete(svc):
    await svc.save_bundle(ACME, owner="u1", bundle=_bundle())
    d = await svc.update_visibility(ACME, "a1", visibility="tenant", allowed_groups=())
    assert d.visibility == "tenant"
    with pytest.raises(StudioValidationError):
        await svc.update_visibility(GLOBAL, "a1", visibility="tenant", allowed_groups=())
    assert await svc.delete(ACME, "a1") is True and await svc.delete(ACME, "a1") is False
    assert await svc.get(ACME, "a1") is None


async def test_activate_creates_agent_with_children(repos, svc):
    bundle = _bundle(toolkits=[ToolkitSpec(slug="jira", params={"k": 1})],
                     mcp_servers=[AgentMCPServerSpec(name="m", url="https://m/")], assets=[_asset()])
    await svc.save_bundle(GLOBAL, owner="u1", bundle=bundle)
    rec = await svc.activate(GLOBAL, "a1", owner="u2")
    assert (rec.name, rec.owner, rec.visibility) == ("a1", "u2", "private")
    assert sorted(t.slug for t in await repos.tooling.list(GLOBAL, "a1")) == ["jira", "m"]
    assert [a.name for a in await repos.assets.list(GLOBAL, "a1")] == ["n.md"]
    head = await repos.agents.get_version(GLOBAL, "a1")
    assert head.agent_id == rec.agent_id and rec.version == head.version
    draft = await svc.get(GLOBAL, "a1")
    assert (draft.status, draft.activated_agent_id) == ("activated", rec.agent_id)
    with pytest.raises(StudioVersionConflict):                     # already activated
        await svc.activate(GLOBAL, "a1", owner="u2")


async def test_activate_name_clash_rolls_back(repos, svc):
    agents, _ = _services(repos)
    await agents.create(GLOBAL, name="a1", owner="u0", definition=StudioAgentDefinition())
    await svc.save_bundle(GLOBAL, owner="u1", bundle=_bundle(assets=[_asset()]))
    with pytest.raises(StudioNameConflict):
        await svc.activate(GLOBAL, "a1", owner="u1")
    assert (await svc.get(GLOBAL, "a1")).status == "draft" and await repos.assets.list(GLOBAL, "a1") == []


async def test_activation_runs_policy_before_any_write(repos, svc):
    mcp = AgentMCPServerSpec(name="s", transport="stdio", command="/bin/sh")
    async with studio_transaction(repos.pool) as conn:       # a draft stored behind the service's back
        await repos.drafts.insert(conn, ACME, name="a1", owner="u1", bundle=_bundle(mcp_servers=[mcp]),
                                  visibility="private", allowed_groups=())
    with pytest.raises(StudioToolingRefused) as exc:
        await svc.activate(ACME, "a1", owner="u1")
    assert exc.value.code == "tooling_not_permitted"
    assert await repos.agents.get(ACME, "a1") is None and (await svc.get(ACME, "a1")).status == "draft"


async def test_activation_replace_swaps_bundle(repos, svc):
    agents, _ = _services(repos)
    await agents.create(
        GLOBAL, name="a1", owner="u0", definition=StudioAgentDefinition(description="old"),
        toolkits=[ToolkitSpec(slug="jira", params={"k": 1})], assets=[_asset("old.md", "old")],
    )
    await svc.save_bundle(GLOBAL, owner="u1", bundle=_bundle(description="new", assets=[_asset("new.md", "new")]))
    rec = await svc.activate(GLOBAL, "a1", owner="u1", replace=True)
    assert rec.owner == "u0" and rec.definition.description == "new"
    assert await repos.tooling.list(GLOBAL, "a1") == []
    assert [a.name for a in await repos.assets.list(GLOBAL, "a1")] == ["new.md"]
    assert (await repos.agents.get_version(GLOBAL, "a1")).version == rec.version
    assert (await svc.get(GLOBAL, "a1")).activated_agent_id == rec.agent_id


async def test_replace_honours_target_guard(repos, svc):
    agents, _ = _services(repos)
    await agents.create(GLOBAL, name="a1", owner="u0", definition=StudioAgentDefinition())
    version = (await repos.agents.get_version(GLOBAL, "a1")).version
    await svc.save_bundle(GLOBAL, owner="u1", bundle=_bundle(description="new"))
    with pytest.raises(StudioVersionConflict):
        await svc.activate(GLOBAL, "a1", owner="u1", replace=True,
                           target_guard=StudioWriteGuard(expected_version=version + 3))
    assert (await repos.agents.get(GLOBAL, "a1")).definition.description is None
    assert (await svc.get(GLOBAL, "a1")).status == "draft"


async def test_activation_replace_is_atomic(repos, svc, monkeypatch):
    agents, _ = _services(repos)
    await agents.create(
        GLOBAL, name="a1", owner="u0", definition=StudioAgentDefinition(description="old"),
        toolkits=[ToolkitSpec(slug="jira", params={"k": 1})], assets=[_asset("old.md", "old")],
    )
    version = (await repos.agents.get_version(GLOBAL, "a1")).version
    await svc.save_bundle(GLOBAL, owner="u1", bundle=_bundle(description="new", assets=[_asset("new.md", "new")]))
    real = repos.assets.replace_all

    async def failing(conn, agent_id, assets):
        await real(conn, agent_id, assets)
        raise StudioStorageError("simulated failure after the children were written")

    monkeypatch.setattr(repos.assets, "replace_all", failing)
    with pytest.raises(StudioStorageError):
        await svc.activate(GLOBAL, "a1", owner="u1", replace=True)
    after = await repos.agents.get(GLOBAL, "a1")
    assert after.definition.description == "old" and after.version == version
    assert [a.name for a in await repos.assets.list(GLOBAL, "a1")] == ["old.md"]
    assert [t.slug for t in await repos.tooling.list(GLOBAL, "a1")] == ["jira"]
    assert (await svc.get(GLOBAL, "a1")).status == "draft"


async def test_replace_cleans_vault_of_removed_slugs(repos, svc, monkeypatch):
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock

    from parrot.handlers.studio.storage.models import StudioToolingRecord

    agents, _ = _services(repos)
    rec = await agents.create(GLOBAL, name="a1", owner="u0", definition=StudioAgentDefinition())
    async with studio_transaction(repos.pool) as conn:
        await repos.tooling.replace(
            conn, rec.agent_id, toolkits=[StudioToolingRecord(
                None, "toolkit", "jira", 0, {}, {"token": "vault-name-1"}, "u9", datetime.now(timezone.utc))],
            mcp_servers=[],
        )
    deleted = AsyncMock()
    monkeypatch.setattr("parrot.security.vault_utils.delete_vault_credential", deleted)
    await svc.save_bundle(GLOBAL, owner="u1", bundle=_bundle())
    await svc.activate(GLOBAL, "a1", owner="u1", replace=True)
    deleted.assert_awaited_once_with("u9", "vault-name-1")


async def test_concurrent_activation(studio_pool):
    repos = build_studio_repositories(studio_pool)
    _, svc = _services(repos)
    await svc.save_bundle(GLOBAL, owner="u1", bundle=_bundle(toolkits=[ToolkitSpec(slug="jira", params={"k": 1})],
                                                              assets=[_asset()]))
    results = await asyncio.gather(
        svc.activate(GLOBAL, "a1", owner="u1"), svc.activate(GLOBAL, "a1", owner="u1"), return_exceptions=True
    )
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(failures) == 1 and isinstance(failures[0], StudioVersionConflict)
    assert len(await repos.agents.list(GLOBAL)) == 1
    assert [t.slug for t in await repos.tooling.list(GLOBAL, "a1")] == ["jira"]
    assert [a.name for a in await repos.assets.list(GLOBAL, "a1")] == ["n.md"]
    draft = await svc.get(GLOBAL, "a1")
    assert draft.status == "activated" and draft.activated_agent_id == (await repos.agents.get(GLOBAL, "a1")).agent_id


async def test_policy_phases_write_then_activate(repos):
    gate = StudioToolingGate({})
    phases: list[str] = []
    real = gate.enforce

    def spy(part, tooling, *, agent_id, actor, phase):
        phases.append(phase)
        return real(part, tooling, agent_id=agent_id, actor=actor, phase=phase)

    gate.enforce = spy
    agents = StudioAgentService(
        repos, limits=StudioLimits(), class_allowlist=StudioClassAllowlist(),
        tooling=StudioToolingService(repos, gate=gate), tooling_gate=gate,
    )
    svc = StudioDraftService(repos, agents=agents, tooling_gate=gate)
    await svc.save_bundle(GLOBAL, owner="u1", bundle=_bundle())
    assert phases == ["write"]
    await svc.activate(GLOBAL, "a1", owner="u1")
    assert phases == ["write", "activate"]
