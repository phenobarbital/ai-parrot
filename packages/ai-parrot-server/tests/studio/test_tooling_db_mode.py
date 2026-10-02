"""FEAT-621 W3 tooling routes in database mode (AC8, AC12, AC13, §2.9).

Real aiohttp app, the real Studio routes, a session middleware installing a real ``SessionData`` and a real
Postgres pool. ``AbstractBot.configure`` is replaced so no LLM is ever started. The vault and the per-user override
document store are in-memory stand-ins (their external backends are not under test); the toolkit class is a fake
``jira`` with one ``x-secret`` field.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from .test_agents_db_mode import BASE, _app, _create, _offline, pool  # noqa: F401  (fixtures)
from parrot.handlers.studio import toolkit_overrides as overrides_module
from parrot.handlers.studio import tooling_store as store_module
from parrot.handlers.studio.agents import StudioAgentsHandler
from parrot.handlers.studio.storage.models import StudioPartition
from parrot.handlers.studio.storage.services import tooling as tooling_module
from parrot.handlers.studio.toolkit_config import StudioAgentMcpServersHandler, StudioAgentToolkitsHandler
from parrot.handlers.studio.toolkit_overrides import StudioUserToolkitOverrideHandler
from parrot.handlers import toolkit_persistence
from parrot.security import vault_utils
from parrot.tools import tooling_policy
from parrot.tools.spec import SECRET_MASK

SCHEMA = {
    "type": "object",
    "properties": {"server_url": {"type": "string"}, "token": {"type": "string", "x-secret": True}},
}


class _JiraConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_url: str | None = None
    token: str | None = None


class _JiraToolkit:
    config_model = _JiraConfig


class _Overrides:
    """In-memory ``ToolkitConfigService`` (same ``(user_id, agent_id, slug)`` document key)."""

    docs: dict = {}

    async def save(self, override):
        self.docs[(override.user_id, override.agent_id, override.slug)] = override

    async def load(self, user_id, agent_id):
        return [o for (u, a, _), o in self.docs.items() if (u, a) == (user_id, agent_id)]

    async def remove(self, user_id, agent_id, slug):
        return self.docs.pop((user_id, agent_id, slug), None) is not None

    async def purge_agent(self, agent_ref):
        gone = [o for (_, a, _), o in self.docs.items() if a == agent_ref]
        for o in gone:
            self.docs.pop((o.user_id, o.agent_id, o.slug))
        return gone


@pytest.fixture
def vault(monkeypatch):
    """One shared in-memory vault for every module that talks to it, plus the fake toolkit and override store."""
    data: dict = {}

    async def _store(user_id, name, secrets):
        data[(user_id, name)] = dict(secrets)

    async def _retrieve(user_id, name):
        return dict(data[(user_id, name)])

    async def _delete(user_id, name):
        data.pop((user_id, name), None)

    for module in (store_module, overrides_module):
        monkeypatch.setattr(module, "store_vault_credential", _store)
        monkeypatch.setattr(module, "retrieve_vault_credential", _retrieve)
        monkeypatch.setattr(module, "delete_vault_credential", _delete)
    monkeypatch.setattr(tooling_module, "delete_vault_credential", _delete)
    monkeypatch.setattr(vault_utils, "delete_vault_credential", _delete)
    for module in (store_module, tooling_module):
        monkeypatch.setattr(module, "toolkit_schema_for", lambda slug: (_JiraToolkit, SCHEMA))
    _Overrides.docs = {}
    monkeypatch.setattr(overrides_module, "ToolkitConfigService", _Overrides)
    monkeypatch.setattr(toolkit_persistence, "ToolkitConfigService", _Overrides)
    return data


@pytest.fixture
def allow_tenant_tooling(monkeypatch):
    """The host policy allows everything (the policy itself is covered by ``test_tooling_policy_http``)."""
    monkeypatch.setattr(tooling_policy, "enforce_tenant_tooling", lambda app, tooling, *, subject: None)


def _tenant(base, tenant):
    async def _partition(self):
        return StudioPartition(tenant)

    return type(f"_{tenant}_{base.__name__}", (base,), {"_studio_partition": _partition})


def _tenant_app(pool, *tenants):
    app = _app(pool)
    for tenant in tenants:
        agents = _tenant(StudioAgentsHandler, tenant)
        app.router.add_view(f"/{tenant}/agents", agents)
        app.router.add_view(f"/{tenant}/agents/{{name}}", agents)
        app.router.add_view(f"/{tenant}/agents/{{name}}/toolkits/{{slug}}", _tenant(StudioAgentToolkitsHandler, tenant))
        app.router.add_view(f"/{tenant}/agents/{{name}}/mcp-servers", _tenant(StudioAgentMcpServersHandler, tenant))
        app.router.add_view(
            f"/{tenant}/agents/{{name}}/toolkits/{{slug}}/me", _tenant(StudioUserToolkitOverrideHandler, tenant)
        )
    return app


JIRA = {"params": {"server_url": "https://x", "token": "t0k"}, "user_overridable": ["token"]}


async def _tenant_agent(client, tenant):
    resp = await client.post(f"/{tenant}/agents", json={"name": "sales", "bot_class": "BasicBot"})
    assert resp.status == 201, await resp.text()
    return (await resp.json())["agent_id"]


async def _configure(client, tenant, token):
    base = f"/{tenant}/agents/sales"
    resp = await client.put(f"{base}/toolkits/jira", json={**JIRA, "params": {**JIRA["params"], "token": token}})
    assert resp.status == 200, await resp.text()
    server = {"name": "docs", "url": "https://m.example.com/mcp", "headers": {"X-Key": f"h-{token}"}}
    resp = await client.put(f"{base}/mcp-servers", json={"servers": [server]})
    assert resp.status == 200, await resp.text()
    resp = await client.put(f"{base}/toolkits/jira/me", json={"params": {"token": f"me-{token}"}})
    assert resp.status == 200, await resp.text()


async def test_cross_tenant_tooling_identity(aiohttp_client, pool, vault, allow_tenant_tooling):
    client = await aiohttp_client(_tenant_app(pool, "acme", "beta"))
    acme_id, beta_id = await _tenant_agent(client, "acme"), await _tenant_agent(client, "beta")
    await _configure(client, "acme", "A")
    await _configure(client, "beta", "B")
    ref_a, ref_b = f"studio-agent:{acme_id}", f"studio-agent:{beta_id}"
    assert vault[("u1", f"toolkit_jira_{ref_a}")] == {"token": "A"}
    assert vault[("u1", f"toolkit_jira_{ref_b}")] == {"token": "B"}
    assert vault[("u1", f"mcp_agent_docs_{ref_a}")] == {"headers": {"X-Key": "h-A"}}
    assert vault[("u1", f"toolkit_jira_{ref_a}_user")] == {"token": "me-A"}
    assert vault[("u1", f"toolkit_jira_{ref_b}_user")] == {"token": "me-B"}
    assert ("u1", "toolkit_jira_sales") not in vault and ("u1", "toolkit_jira_sales_user") not in vault
    assert {key[1] for key in _Overrides.docs} == {ref_a, ref_b}
    # each tenant sees only its own override
    for tenant in ("acme", "beta"):
        body = await (await client.get(f"/{tenant}/agents/sales/toolkits/jira/me")).json()
        assert body["configured"] is True and body["params"] == {"token": SECRET_MASK}
    resp = await client.delete("/acme/agents/sales")
    assert resp.status == 200
    assert not [key for key in vault if ref_a in key[1]]
    assert [key for key in _Overrides.docs if key[1] == ref_a] == []
    assert vault[("u1", f"toolkit_jira_{ref_b}")] == {"token": "B"}
    assert vault[("u1", f"mcp_agent_docs_{ref_b}")] == {"headers": {"X-Key": "h-B"}}
    assert vault[("u1", f"toolkit_jira_{ref_b}_user")] == {"token": "me-B"}
    beta = await (await client.get("/beta/agents/sales/toolkits/jira/me")).json()
    assert beta["configured"] is True
    # recreate under the same name: nothing inherited
    await _tenant_agent(client, "acme")
    resp = await client.put("/acme/agents/sales/toolkits/jira", json={"params": {"server_url": "https://x"},
                                                                       "user_overridable": ["token"]})
    assert resp.status == 200
    fresh = await (await client.get("/acme/agents/sales/toolkits/jira/me")).json()
    assert fresh["configured"] is False and fresh["params"] == {}


async def _version(client, name="alpha"):
    return (await (await client.get(f"{BASE}/agents/{name}")).json())["version"]


async def _tooling_rows(client):
    async with client.app["database"].acquire() as conn:
        rows = await conn.fetch_all("SELECT kind, slug, config::text AS c FROM navigator.ai_agent_tooling ORDER BY 1,2")
    return [dict(r) for r in rows or []]


async def test_stale_tooling_writes(aiohttp_client, pool, vault):
    client = await aiohttp_client(_app(pool))
    await _create(client)
    url = f"{BASE}/agents/alpha"
    resp = await client.put(f"{url}/toolkits/jira", json=JIRA)
    assert resp.status == 200, await resp.text()
    version = await _version(client)
    rows, secrets = await _tooling_rows(client), dict(vault)
    assert len(rows) == 1 and secrets
    stale = {"expected_version": version - 1}
    resp = await client.put(f"{url}/toolkits/jira", json={**JIRA, "params": {"token": "NEW"}, **stale})
    assert resp.status == 409 and (await resp.json())["code"] == "version_conflict"
    resp = await client.delete(f"{url}/toolkits/jira", params={"expected_version": str(version - 1)})
    assert resp.status == 409 and (await resp.json())["code"] == "version_conflict"
    server = {"name": "docs", "url": "https://m.example.com/mcp", "headers": {"X-Key": "k"}}
    resp = await client.put(f"{url}/mcp-servers", json={"servers": [server], **stale})
    assert resp.status == 409 and (await resp.json())["code"] == "version_conflict"
    assert await _tooling_rows(client) == rows and vault == secrets and await _version(client) == version
    resp = await client.put(f"{url}/mcp-servers", json={"servers": [server], "expected_version": version})
    assert resp.status == 200
    resp = await client.put(f"{url}/mcp-servers", json={"servers": [], "expected_version": "nope"})
    assert resp.status == 400 and (await resp.json())["code"] == "invalid_expected_version"
    resp = await client.delete(f"{url}/toolkits/jira", params={"expected_version": str(await _version(client))})
    assert resp.status == 200


async def test_tooling_policy_http(aiohttp_client, pool, vault):
    client = await aiohttp_client(_tenant_app(pool, "acme"))
    await _tenant_agent(client, "acme")
    stdio = {"name": "s", "transport": "stdio", "command": "/bin/sh", "headers": {"X-Key": "secret"}}
    resp = await client.put("/acme/agents/sales/mcp-servers", json={"servers": [stdio]})
    assert resp.status == 422 and (await resp.json())["code"] == "tooling_not_permitted"
    resp = await client.put("/acme/agents/sales/toolkits/jira", json=JIRA)
    assert resp.status == 422 and (await resp.json())["code"] == "tooling_not_permitted"
    assert await _tooling_rows(client) == [] and vault == {}


async def test_overrides_expected_version_unsupported(aiohttp_client, pool, vault):
    client = await aiohttp_client(_app(pool))
    await _create(client)
    url = f"{BASE}/agents/alpha/toolkits/jira"
    assert (await client.put(url, json=JIRA)).status == 200
    resp = await client.put(f"{url}/me", json={"params": {"token": "x"}, "expected_version": 1})
    assert resp.status == 400 and (await resp.json())["code"] == "expected_version_unsupported"
    assert _Overrides.docs == {} and not [k for k in vault if k[1].endswith("_user")]
    assert (await client.put(f"{url}/me", json={"params": {"token": "x"}})).status == 200
    resp = await client.delete(f"{url}/me", params={"expected_version": "1"})
    assert resp.status == 400 and (await resp.json())["code"] == "expected_version_unsupported"
    assert len(_Overrides.docs) == 1
    assert (await client.delete(f"{url}/me")).status == 200 and _Overrides.docs == {}


async def test_editable_true_for_studio_rows(aiohttp_client, pool, vault):
    client = await aiohttp_client(_app(pool))
    await _create(client)
    for path in ("toolkit-config", "mcp-servers"):
        body = await (await client.get(f"{BASE}/agents/alpha/{path}")).json()
        assert body["editable"] is True and body["reason"] is None


async def test_assign_resolves_studio_row_owner(aiohttp_client, pool, vault):
    client = await aiohttp_client(_app(pool))
    await _create(client)
    resp = await client.post(f"{BASE}/agents/alpha/toolkits", json={"slug": "dataset_manager", "params": {}},
                             headers={"X-User": "u2"})
    assert resp.status == 403
    resp = await client.post(f"{BASE}/agents/alpha/toolkits", json={"slug": "dataset_manager", "params": {}})
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["agent"] == "alpha" and body["persisted"] is False
    resp = await client.post(f"{BASE}/agents/nobody/toolkits", json={"slug": "dataset_manager", "params": {}})
    assert resp.status == 404
