"""FEAT-621 M5 — tooling service (AC12, AC13)."""
import json

import pytest
from pydantic import BaseModel, ConfigDict

from parrot.handlers.studio import tooling_store as store_module
from parrot.handlers.studio.storage.models import (
    StudioAgentDefinition,
    StudioPartition,
    StudioToolingRefused,
    StudioVersionConflict,
    StudioWriteGuard,
)
from parrot.handlers.studio.storage.repositories import build_studio_repositories, studio_transaction
from parrot.handlers.studio.storage.services import tooling as tooling_module
from parrot.handlers.studio.storage.services._common import StudioToolingGate
from parrot.handlers.studio.storage.services.tooling import StudioToolingService

ACME = StudioPartition("acme")
GLOBAL = StudioPartition.GLOBAL
NO_GUARD = StudioWriteGuard()


class _JiraConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_url: str | None = None
    token: str | None = None


class _JiraToolkit:
    config_model = _JiraConfig


_SCHEMA = {
    "type": "object",
    "properties": {"server_url": {"type": "string"}, "token": {"type": "string", "x-secret": True}},
}


@pytest.fixture
def vault(monkeypatch):
    data: dict = {}

    async def _store(user_id, name, secrets):
        data[(user_id, name)] = dict(secrets)

    async def _retrieve(user_id, name):
        return dict(data[(user_id, name)])

    deleted: list = []

    async def _delete(user_id, name):
        deleted.append((user_id, name))
        data.pop((user_id, name), None)

    monkeypatch.setattr(store_module, "store_vault_credential", _store)
    monkeypatch.setattr(store_module, "retrieve_vault_credential", _retrieve)
    monkeypatch.setattr(tooling_module, "delete_vault_credential", _delete)
    monkeypatch.setattr(tooling_module, "toolkit_schema_for", lambda slug: (_JiraToolkit, _SCHEMA))
    data["__deleted__"] = deleted
    return data


@pytest.fixture
async def env(studio_pool):
    repos = build_studio_repositories(studio_pool)
    app: dict = {}
    service = StudioToolingService(repos, gate=StudioToolingGate(app))
    return repos, service, app


async def _agent(repos, part, name="a1", owner="u1"):
    async with studio_transaction(repos.pool) as conn:
        return await repos.agents.insert(
            conn, part, name=name, owner=owner, definition=StudioAgentDefinition(), visibility="private",
            allowed_groups=(),
        )


async def _config_rows(pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch_all("SELECT kind, slug, config::text AS config, secret_refs::text AS refs, "
                                    "vault_owner FROM navigator.ai_agent_tooling ORDER BY kind, slug")
    return list(rows or [])


async def test_toolkit_secrets_never_in_db(env, vault):
    repos, service, _ = env
    rec = await _agent(repos, GLOBAL)
    await service.put_toolkit(GLOBAL, "a1", "jira", {"server_url": "https://x", "token": "t0k"}, ["token"],
                              actor="u1", guard=NO_GUARD)
    ref = f"toolkit_jira_studio-agent:{rec.agent_id}"
    assert vault[("u1", ref)] == {"token": "t0k"}
    rows = await _config_rows(repos.pool)
    assert len(rows) == 1 and "t0k" not in rows[0]["config"] and "t0k" not in rows[0]["refs"]
    assert json.loads(rows[0]["refs"]) == {"token": ref} and rows[0]["vault_owner"] == "u1"
    view = await service.load(GLOBAL, "a1")
    assert view.tooling.toolkits[0].params == {"server_url": "https://x"}


async def test_delete_toolkit_and_version(env, vault):
    repos, service, _ = env
    rec = await _agent(repos, GLOBAL)
    v1 = await service.put_toolkit(GLOBAL, "a1", "jira", {"server_url": "https://x"}, [], actor="u1", guard=NO_GUARD)
    v2 = await service.delete_toolkit(GLOBAL, "a1", "jira", actor="u1", guard=NO_GUARD)
    assert v1 > rec.version and v2 > v1 and await _config_rows(repos.pool) == []
    assert vault["__deleted__"] == [("u1", f"toolkit_jira_studio-agent:{rec.agent_id}")]


async def test_put_mcp_servers_vaults_secrets(env, vault):
    repos, service, _ = env
    rec = await _agent(repos, GLOBAL)
    await service.put_mcp_servers(
        GLOBAL, "a1", [{"name": "remote", "url": "https://m/", "headers": {"X-Key": "x"}}], actor="u1", guard=NO_GUARD
    )
    assert vault[("u1", f"mcp_agent_remote_studio-agent:{rec.agent_id}")] == {"headers": {"X-Key": "x"}}
    rows = await _config_rows(repos.pool)
    assert "X-Key" not in rows[0]["config"] and rows[0]["kind"] == "mcp"


async def test_tooling_policy_on_tooling_writes(env, vault, no_subprocess):
    repos, service, _ = env
    await _agent(repos, ACME)
    for server in (
        {"name": "s", "transport": "stdio", "command": "/bin/sh", "headers": {"X-Key": "secret"}},
        {"name": "s", "transport": "http", "url": "https://m/", "params": {"transport": "stdio", "command": "/bin/sh"}},
    ):
        with pytest.raises(StudioToolingRefused) as exc:
            await service.put_mcp_servers(ACME, "a1", [server], actor="u1", guard=NO_GUARD)
        assert exc.value.code == "tooling_not_permitted"
    assert await _config_rows(repos.pool) == [] and not [k for k in vault if k != "__deleted__"]


async def test_tenant_toolkit_refused_without_policy_entry(env, vault):
    repos, service, _ = env
    await _agent(repos, ACME)
    with pytest.raises(StudioToolingRefused):
        await service.put_toolkit(ACME, "a1", "jira", {"server_url": "https://x"}, [], actor="u1", guard=NO_GUARD)
    assert await _config_rows(repos.pool) == []


async def test_stale_expected_version(env, vault):
    repos, service, _ = env
    rec = await _agent(repos, GLOBAL)
    with pytest.raises(StudioVersionConflict):
        await service.put_toolkit(GLOBAL, "a1", "jira", {"token": "zzz"}, [], actor="u1",
                                  guard=StudioWriteGuard(expected_version=rec.version + 5))
    assert await _config_rows(repos.pool) == [] and not [k for k in vault if k != "__deleted__"]


async def test_replace_from_state_bridge(env, vault):
    repos, service, _ = env
    rec = await _agent(repos, GLOBAL)
    view = await service.load(GLOBAL, "a1")
    from parrot.tools.spec import ToolkitSpec

    view.tooling.toolkits = [ToolkitSpec(slug="jira", params={"server_url": "u"})]
    version = await service.replace_from_state(GLOBAL, "a1", view.tooling, actor="u1",
                                               guard=StudioWriteGuard(authorized_version=rec.version))
    assert version > rec.version and len(await _config_rows(repos.pool)) == 1


async def test_tenant_allowed_server_without_secrets_carries_no_vault_trace(env, vault):
    from parrot.tools.tooling_policy import TenantToolingPolicy, set_tenant_tooling_policy

    repos, service, app = env
    set_tenant_tooling_policy(app, TenantToolingPolicy(mcp_endpoints=("https://m.example.com/",)))
    await _agent(repos, ACME)
    await service.put_mcp_servers(
        ACME, "a1", [{"name": "s", "url": "https://m.example.com/mcp"}], actor="u1", guard=NO_GUARD
    )
    rows = await _config_rows(repos.pool)
    assert len(rows) == 1 and rows[0]["vault_owner"] is None and json.loads(rows[0]["refs"]) == {}
