"""FEAT-621 M5 — agent service (AC6, AC8, AC12, AC13). Runs on the in-memory repositories and on real Postgres."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from parrot.handlers.studio.storage.models import (
    StudioAgentBundle,
    StudioAgentDefinition,
    StudioAgentPatch,
    StudioAssetInput,
    StudioModelParams,
    StudioNameConflict,
    StudioPartition,
    StudioStaleAuthorization,
    StudioToolingRecord,
    StudioToolingRefused,
    StudioVersionConflict,
    StudioWriteGuard,
)
from parrot.handlers.studio.storage.repositories import build_studio_repositories, studio_transaction
from parrot.handlers.studio.storage.services._common import (
    StudioAgentAssetsQuota,
    StudioClassAllowlist,
    StudioLimits,
    StudioToolingGate,
    StudioValidationError,
)
from parrot.handlers.studio.storage.services.agents import StudioAgentService
from parrot.handlers.studio.storage.services.tooling import StudioToolingService
from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories
from parrot.handlers.toolkit_persistence import ToolkitConfigService, UserToolkitOverride
from parrot.tools.spec import AgentMCPServerSpec, ToolkitSpec

ACME = StudioPartition("acme")
GLOBAL = StudioPartition.GLOBAL
NO_GUARD = StudioWriteGuard()


@pytest.fixture(params=["memory", "postgres"])
def repos(request):
    if request.param == "memory":
        return InMemoryStudioRepositories()
    return build_studio_repositories(request.getfixturevalue("studio_pool"))


def _service(repos, limits=None):
    app: dict = {}
    gate = StudioToolingGate(app)
    tooling = StudioToolingService(repos, gate=gate)
    return StudioAgentService(
        repos, limits=limits or StudioLimits(), class_allowlist=StudioClassAllowlist(), tooling=tooling,
        tooling_gate=gate,
    )


@pytest.fixture
def svc(repos):
    return _service(repos)


def _identity(content="You are a role."):
    return StudioAssetInput(kind="identity", name="role.md", content=content)


async def test_create_without_bundle(svc):
    rec = await svc.create(
        ACME, name="a1", owner="u1", definition=StudioAgentDefinition(description="d"), visibility="groups",
        allowed_groups=["g1"],
    )
    assert (rec.tenant, rec.name, rec.owner, rec.visibility, rec.allowed_groups) == ("acme", "a1", "u1", "groups", ("g1",))
    assert rec.definition.description == "d" and rec.version >= 1
    assert (await svc.get(ACME, "a1")).agent_id == rec.agent_id and await svc.get(GLOBAL, "a1") is None
    assert [r.name for r in await svc.list(ACME)] == ["a1"] and await svc.list(ACME, owner="zz") == []
    head = await svc.get_version(ACME, "a1")
    assert head.agent_id == rec.agent_id and head.version == rec.version


async def test_create_name_conflict(svc):
    await svc.create(ACME, name="a1", owner="u1", definition=StudioAgentDefinition())
    with pytest.raises(StudioNameConflict):
        await svc.create(ACME, name="a1", owner="u2", definition=StudioAgentDefinition())
    await svc.create(StudioPartition("other"), name="a1", owner="u2", definition=StudioAgentDefinition())


async def test_create_is_atomic(repos, svc, monkeypatch):
    bad = StudioAssetInput(kind="identity", name="role.md", content="x", content_type="application/pdf")
    with pytest.raises(StudioValidationError):
        await svc.create(GLOBAL, name="a1", owner="u1", definition=StudioAgentDefinition(), assets=[bad])
    assert await svc.get(GLOBAL, "a1") is None
    monkeypatch.setattr(repos.assets, "replace_all", AsyncMock(side_effect=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        await svc.create(
            GLOBAL, name="a2", owner="u1", definition=StudioAgentDefinition(),
            toolkits=[ToolkitSpec(slug="jira", params={"a": 1})], assets=[_identity()],
        )
    assert await svc.get(GLOBAL, "a2") is None and await repos.tooling.list(GLOBAL, "a2") == []


async def test_create_with_bundle_children(repos, svc):
    bundle = StudioAgentBundle(
        name="a1", definition=StudioAgentDefinition(), toolkits=[ToolkitSpec(slug="jira", params={"k": 1})],
        mcp_servers=[AgentMCPServerSpec(name="m", url="https://m/")], assets=[_identity()],
    )
    rec = await svc.create_from_bundle(GLOBAL, owner="u1", bundle=bundle)
    assert sorted(t.slug for t in await repos.tooling.list(GLOBAL, "a1")) == ["jira", "m"]
    assert [a.name for a in await repos.assets.list(GLOBAL, "a1")] == ["role.md"] and rec.name == "a1"


async def test_create_validations(svc):
    d = StudioAgentDefinition()
    with pytest.raises(StudioValidationError) as exc:
        await svc.create(GLOBAL, name="Bad:Name", owner="u", definition=d)
    assert exc.value.code == "invalid_name"
    with pytest.raises(StudioValidationError) as exc:
        await svc.create(ACME, name="a1", owner="u", definition=StudioAgentDefinition(bot_class="Foo"))
    assert exc.value.code == "bot_class_not_allowed"
    with pytest.raises(StudioValidationError) as exc:
        await svc.create(GLOBAL, name="a1", owner="u", definition=d, visibility="tenant")
    assert exc.value.code == "invalid_visibility"
    with pytest.raises(StudioValidationError) as exc:
        await svc.create(GLOBAL, name="a1", owner="u", definition=d,
                         toolkits=[ToolkitSpec(slug="jira", secret_refs={"token": "x"}, vault_owner="u")])
    assert exc.value.code == "secrets_not_allowed"
    dup = [_identity(), _identity("again")]
    with pytest.raises(StudioValidationError) as exc:
        await svc.create(GLOBAL, name="a1", owner="u", definition=d, assets=dup)
    assert exc.value.code == "duplicate_asset"


async def test_create_quota_over_all_assets(repos):
    svc = _service(repos, StudioLimits(identity_max=10, kb_max=10, skills_max=10, agent_total_max=15))
    assets = [StudioAssetInput(kind="kb", name="a.md", content="x" * 10),
              StudioAssetInput(kind="kb", name="b.md", content="x" * 10)]
    with pytest.raises(StudioAgentAssetsQuota) as exc:
        await svc.create(GLOBAL, name="a1", owner="u", definition=StudioAgentDefinition(), assets=assets)
    assert exc.value.code == "agent_assets_quota" and await svc.get(GLOBAL, "a1") is None


async def test_create_tooling_policy_refusal(repos, svc):
    mcp = AgentMCPServerSpec(name="s", transport="stdio", command="/bin/sh")
    with pytest.raises(StudioToolingRefused) as exc:
        await svc.create(ACME, name="a1", owner="u", definition=StudioAgentDefinition(), mcp_servers=[mcp])
    assert exc.value.code == "tooling_not_permitted"
    assert await svc.get(ACME, "a1") is None
    smuggled = AgentMCPServerSpec(name="s", url="https://m/", params={"transport": "stdio", "command": "/bin/sh"})
    with pytest.raises(StudioToolingRefused):
        await svc.create_from_bundle(
            ACME, owner="u", bundle=StudioAgentBundle(name="a2", definition=StudioAgentDefinition(),
                                                      mcp_servers=[smuggled]),
        )
    assert await svc.get(ACME, "a2") is None


async def test_patch_merges_general_fields(svc):
    d = StudioAgentDefinition(description="old", model_params=StudioModelParams(temperature=0.2, top_k=5))
    rec = await svc.create(GLOBAL, name="a1", owner="u1", definition=d)
    patched = await svc.patch(
        GLOBAL, "a1",
        StudioAgentPatch(description="new", system_prompt="sp", model_params=StudioModelParams(max_tokens=9)),
        guard=NO_GUARD,
    )
    assert patched.definition.description == "new" and patched.definition.system_prompt == "sp"
    mp = patched.definition.model_params
    assert (mp.temperature, mp.top_k, mp.max_tokens) == (0.2, 5, 9)
    assert patched.version > rec.version and patched.definition.bot_class == d.bot_class
    again = await svc.patch(GLOBAL, "a1", StudioAgentPatch(llm="openai:gpt"), guard=NO_GUARD)
    assert again.definition.description == "new" and again.definition.llm == "openai:gpt"


async def test_patch_stale_expected_version(svc):
    rec = await svc.create(GLOBAL, name="a1", owner="u1", definition=StudioAgentDefinition(description="d"))
    with pytest.raises(StudioVersionConflict):
        await svc.patch(GLOBAL, "a1", StudioAgentPatch(description="x"),
                        guard=StudioWriteGuard(expected_version=rec.version + 3))
    with pytest.raises(StudioVersionConflict):   # the body field counts when the guard carries none
        await svc.patch(GLOBAL, "a1", StudioAgentPatch(description="x", expected_version=rec.version + 3), guard=NO_GUARD)
    assert (await svc.get(GLOBAL, "a1")).definition.description == "d"


async def test_patch_rechecks_tooling_policy(repos, svc):
    rec = await svc.create(ACME, name="a1", owner="u1", definition=StudioAgentDefinition())
    now = datetime.now(timezone.utc)
    async with studio_transaction(repos.pool) as conn:
        await repos.tooling.replace(
            conn, rec.agent_id, toolkits=[],
            mcp_servers=[StudioToolingRecord(None, "mcp", "s", 0, {"transport": "stdio", "command": "/bin/sh"}, {}, None, now)],
        )
    with pytest.raises(StudioToolingRefused):
        await svc.patch(ACME, "a1", StudioAgentPatch(description="x"), guard=NO_GUARD)


async def test_update_visibility_guarded(svc):
    rec = await svc.create(ACME, name="a1", owner="u1", definition=StudioAgentDefinition())
    with pytest.raises(StudioVersionConflict):
        await svc.update_visibility(ACME, "a1", visibility="tenant", allowed_groups=(),
                                    guard=StudioWriteGuard(expected_version=rec.version + 1))
    with pytest.raises(StudioValidationError):
        await svc.update_visibility(GLOBAL, "a1", visibility="tenant", allowed_groups=(), guard=NO_GUARD)
    out = await svc.update_visibility(ACME, "a1", visibility="groups", allowed_groups=["g"],
                                      guard=StudioWriteGuard(authorized_version=rec.version))
    assert (out.visibility, out.allowed_groups) == ("groups", ("g",)) and out.version > rec.version


async def test_stale_authorization_signal(svc):
    rec = await svc.create(ACME, name="a1", owner="u1", definition=StudioAgentDefinition())
    await svc.update_visibility(ACME, "a1", visibility="tenant", allowed_groups=(), guard=NO_GUARD)
    for call in (
        svc.update_visibility(ACME, "a1", visibility="private", allowed_groups=(),
                              guard=StudioWriteGuard(authorized_version=rec.version)),
        svc.patch(ACME, "a1", StudioAgentPatch(description="z"), guard=StudioWriteGuard(authorized_version=rec.version)),
        svc.delete(ACME, "a1", guard=StudioWriteGuard(authorized_version=rec.version)),
    ):
        with pytest.raises(StudioStaleAuthorization):
            await call
    now = await svc.get(ACME, "a1")
    assert now.visibility == "tenant" and now.definition.description is None


async def test_delete_cleans_vault_and_overrides_after_commit(repos, svc, monkeypatch):
    rec = await svc.create(GLOBAL, name="a1", owner="u1", definition=StudioAgentDefinition())
    ref = rec.tooling_ref
    vault_name = f"toolkit_jira_{ref}"
    now = datetime.now(timezone.utc)
    async with studio_transaction(repos.pool) as conn:
        await repos.tooling.replace(
            conn, rec.agent_id,
            toolkits=[StudioToolingRecord(None, "toolkit", "jira", 0, {}, {"token": vault_name}, "u1", now)],
            mcp_servers=[],
        )
    deleted: list = []
    seen_gone: list = []

    async def _delete(user_id, name):
        seen_gone.append(await svc.get(GLOBAL, "a1") is None)
        deleted.append((user_id, name))

    monkeypatch.setattr("parrot.security.vault_utils.delete_vault_credential", _delete)
    purge = AsyncMock(return_value=[UserToolkitOverride(user_id="u9", agent_id=ref, slug="jira")])
    monkeypatch.setattr(ToolkitConfigService, "purge_agent", purge)
    assert await svc.delete(GLOBAL, "a1", guard=NO_GUARD) is True
    assert deleted == [("u1", vault_name), ("u9", f"toolkit_jira_{ref}_user")]
    assert all(seen_gone) and purge.await_args.args == (ref,)
    assert await svc.delete(GLOBAL, "a1", guard=NO_GUARD) is False


async def test_delete_cleanup_failure_is_swallowed(svc, monkeypatch):
    await svc.create(GLOBAL, name="a1", owner="u1", definition=StudioAgentDefinition())
    monkeypatch.setattr(ToolkitConfigService, "purge_agent", AsyncMock(side_effect=RuntimeError("db down")))
    assert await svc.delete(GLOBAL, "a1", guard=NO_GUARD) is True
    assert await svc.get(GLOBAL, "a1") is None


async def test_delete_respects_guard(svc):
    rec = await svc.create(GLOBAL, name="a1", owner="u1", definition=StudioAgentDefinition())
    with pytest.raises(StudioVersionConflict):
        await svc.delete(GLOBAL, "a1", guard=StudioWriteGuard(expected_version=rec.version + 1))
    assert await svc.get(GLOBAL, "a1") is not None
