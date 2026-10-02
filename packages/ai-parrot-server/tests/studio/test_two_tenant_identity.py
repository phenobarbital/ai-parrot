"""FEAT-622 M9 (R3 regression): same-named agents in two tenants never share secrets, overrides or hydration.

Real aiohttp app, real Studio routes, real Postgres (``TEST_STUDIO_PG_DSN``) and the host toolkit ``tp_probe`` (its
``token`` ctor param is an ``x-secret``). The vault and the per-user override document store are in-memory stand-ins
(their external backends are not under test); the host policy is bypassed exactly as ``test_tooling_db_mode`` does
(tenant secrets are a policy matter covered there).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from parrot.handlers import agent as agent_module
from parrot.handlers import toolkit_persistence
from parrot.handlers.studio import toolkit_overrides as overrides_module
from parrot.handlers.studio import tooling_store as store_module
from parrot.handlers.studio.storage.services import tooling as tooling_module
from parrot.security import vault_utils
from parrot.tools.manager import ToolManager
from parrot.tools.spec import SECRET_MASK, ToolkitSpec

from ._host_probe import host_plugins  # noqa: F401
from .test_agents_db_mode import _app, _offline, pool  # noqa: F401  (fixtures)
from .test_tooling_db_mode import _Overrides, _tenant_agent, _tenant_app, allow_tenant_tooling  # noqa: F401


class _RuntimeOverrides(_Overrides):
    """The same in-memory store, with the revision marker the runtime hydration reads."""

    async def revision(self, user_id, agent_id):
        return "r1"


@pytest.fixture
def host_vault(monkeypatch):
    """One in-memory vault for every module that talks to it, and the in-memory override store."""
    data: dict = {}

    async def _store(user_id, name, secrets):
        data[(user_id, name)] = dict(secrets)

    async def _retrieve(user_id, name):
        return dict(data[(user_id, name)])

    async def _delete(user_id, name):
        data.pop((user_id, name), None)

    for module in (store_module, overrides_module, agent_module):
        monkeypatch.setattr(module, "store_vault_credential", _store, raising=False)
        monkeypatch.setattr(module, "retrieve_vault_credential", _retrieve, raising=False)
        monkeypatch.setattr(module, "delete_vault_credential", _delete, raising=False)
    monkeypatch.setattr(tooling_module, "delete_vault_credential", _delete)
    monkeypatch.setattr(vault_utils, "delete_vault_credential", _delete)
    _Overrides.docs = {}
    for module in (overrides_module, toolkit_persistence):
        monkeypatch.setattr(module, "ToolkitConfigService", _Overrides)
    monkeypatch.setattr(agent_module, "ToolkitConfigService", _RuntimeOverrides)
    return data


async def _configure(client, tenant, token):
    base = f"/{tenant}/agents/sales"
    resp = await client.put(f"{base}/toolkits/tp_probe", json={"params": {"token": token}, "user_overridable": ["token"]})
    assert resp.status == 200, await resp.text()
    server = {"name": "docs", "url": "https://m.example.com/mcp", "headers": {"X-Key": f"h-{token}"}}
    resp = await client.put(f"{base}/mcp-servers", json={"servers": [server]})
    assert resp.status == 200, await resp.text()
    resp = await client.put(f"{base}/toolkits/tp_probe/me", json={"params": {"token": f"me-{token}"}})
    assert resp.status == 200, await resp.text()


class _Session(dict):
    user_id = "u1"


class _Raising:
    """Logger stand-in: hydration never raises, so surface the swallowed failure in the test."""

    def warning(self, message, *args):
        raise AssertionError(message % args)


async def _hydrated_token(ref: str) -> str:
    """Runtime hydration (``_apply_user_toolkit_overrides``) of an agent carrying ``ref``: the token it builds."""
    agent = SimpleNamespace(
        name="sales",
        _tooling_ref=ref,
        _tooling_revision="",
        _pending_toolkit_specs=[ToolkitSpec(slug="tp_probe", params={}, user_overridable=["token"])],
        tool_manager=ToolManager(),
    )
    agent._resolve_spec_class = lambda slug: __import__("parrot.interfaces.tools", fromlist=["x"]).ToolInterface._resolve_spec_class(slug)
    manager = await agent_module.AgentTalk._apply_user_toolkit_overrides(
        SimpleNamespace(logger=_Raising()), agent, _Session(), None
    )
    tool = next(t for t in manager.get_tools() if t.name == "tp_whoami")
    return tool.bound_method.__self__.token


async def test_same_names_two_tenants_independent_secrets_and_overrides(  # noqa: F811
    host_plugins, aiohttp_client, pool, host_vault, allow_tenant_tooling
):
    client = await aiohttp_client(_tenant_app(pool, "acme", "beta"))
    acme_id, beta_id = await _tenant_agent(client, "acme"), await _tenant_agent(client, "beta")
    await _configure(client, "acme", "A")
    await _configure(client, "beta", "B")
    ref_a, ref_b = f"studio-agent:{acme_id}", f"studio-agent:{beta_id}"
    # names are exactly the storage scheme, never the bare agent name
    assert host_vault[("u1", f"toolkit_tp_probe_{ref_a}")] == {"token": "A"}
    assert host_vault[("u1", f"toolkit_tp_probe_{ref_b}")] == {"token": "B"}
    assert host_vault[("u1", f"mcp_agent_docs_{ref_a}")] == {"headers": {"X-Key": "h-A"}}
    assert host_vault[("u1", f"toolkit_tp_probe_{ref_a}_user")] == {"token": "me-A"}
    assert host_vault[("u1", f"toolkit_tp_probe_{ref_b}_user")] == {"token": "me-B"}
    assert not [key for key in host_vault if key[1].endswith("_sales") or key[1].endswith("_sales_user")]
    assert {key[1] for key in _Overrides.docs} == {ref_a, ref_b}
    # each tenant sees only its own override, and runtime hydration builds its own tenant's toolkit
    for tenant in ("acme", "beta"):
        body = await (await client.get(f"/{tenant}/agents/sales/toolkits/tp_probe/me")).json()
        assert body["configured"] is True and body["params"] == {"token": SECRET_MASK}
    assert await _hydrated_token(ref_a) == "me-A" and await _hydrated_token(ref_b) == "me-B"
    # delete acme/sales: acme's secrets and override are gone, beta's are untouched
    assert (await client.delete("/acme/agents/sales")).status == 200
    assert not [key for key in host_vault if ref_a in key[1]]
    assert [key for key in _Overrides.docs if key[1] == ref_a] == []
    assert host_vault[("u1", f"toolkit_tp_probe_{ref_b}")] == {"token": "B"}
    assert host_vault[("u1", f"toolkit_tp_probe_{ref_b}_user")] == {"token": "me-B"}
    assert (await (await client.get("/beta/agents/sales/toolkits/tp_probe/me")).json())["configured"] is True
    # recreate under the same name: nothing inherited
    await _tenant_agent(client, "acme")
    resp = await client.put("/acme/agents/sales/toolkits/tp_probe", json={"params": {}, "user_overridable": ["token"]})
    assert resp.status == 200, await resp.text()
    fresh = await (await client.get("/acme/agents/sales/toolkits/tp_probe/me")).json()
    assert fresh["configured"] is False and fresh["params"] == {}
