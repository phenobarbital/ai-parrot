"""FEAT-605/622 C35/C36 on the routes: tenant tooling policy, scope and confirmation, with a real tenant app."""
from __future__ import annotations

import importlib

from ._host_probe import host_plugins, no_subprocess  # noqa: F401
from .test_agents_db_mode import BASE, _offline, pool  # noqa: F401  (fixtures)
from .test_agents_visibility import create, tenant_app, who


async def test_stdio_mcp_is_refused_before_persistence_and_before_any_process(  # noqa: F811
    aiohttp_client, pool, no_subprocess  # noqa: F811
):
    client = await aiohttp_client(tenant_app(pool))
    assert (await create(client, "mine", who("u1")))[0].status == 201
    servers = {"servers": [{"name": "s", "transport": "stdio", "command": "echo", "args": ["x"]}]}
    resp = await client.put(f"{BASE}/agents/mine/mcp-servers", json=servers, headers=who("u1"))
    body = await resp.json()
    assert resp.status == 422 and body["code"] == "tooling_not_permitted", body
    listing = await client.get(f"{BASE}/agents/mine/mcp-servers", headers=who("u1"))
    assert (await listing.json())["servers"] == []        # nothing persisted
    assert no_subprocess == []                              # no process started (also asserted at fixture teardown)


async def test_builtin_toolkit_write_is_refused_for_a_tenant(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    assert (await create(client, "mine", who("u1")))[0].status == 201
    resp = await client.put(f"{BASE}/agents/mine/toolkits/wiki", json={"params": {}, "user_overridable": []},
                            headers=who("u1"))
    body = await resp.json()
    assert resp.status == 422 and body["code"] == "tooling_not_permitted"


async def test_execute_host_write_fails_closed_and_policy_applies(aiohttp_client, pool, host_plugins):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    call = lambda slug: client.post(f"{BASE}/tools/{slug}/execute", json={"args": {"value": "x"}},  # noqa: E731
                                     headers=who("u1"))
    resp = await call("tp_probe_tool_write")
    assert resp.status == 403 and (await resp.json())["code"] == "confirmation_required"
    assert importlib.import_module("plugins.tools.probe").COUNTERS["written"] == 0        # zero writes
    resp = await call("shell")
    assert resp.status == 403 and (await resp.json())["code"] == "tooling_not_permitted"
    resp = await call("tp_probe_tool")                                                   # an allowed read host tool
    assert resp.status == 200


async def test_options_scope_and_access_gates(aiohttp_client, pool, host_plugins):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    assert (await create(client, "mine", who("u1")))[0].status == 201
    for slug in ("tp_probe", "tp_tenant"):
        resp = await client.put(f"{BASE}/agents/mine/toolkits/{slug}", json={"params": {}, "user_overridable": []},
                                headers=who("u1"))
        assert resp.status == 200, await resp.text()
    counters = importlib.import_module("plugins.tools.probe").COUNTERS
    options = lambda slug, caller: client.get(  # noqa: E731
        f"{BASE}/agents/mine/toolkits/{slug}/options/project", headers=caller)
    assert (await options("tp_probe", who("u1"))).status == 200                           # not tenant-bound
    resp = await options("tp_tenant", who("u2"))                                          # not the owner's agent
    assert resp.status == 404
    assert counters["constructed"] == 0 and counters["options_calls"] == 1               # only tp_probe ran
