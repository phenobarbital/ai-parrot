"""FEAT-605 M9 — derivative routes of an agent: the identical 404, 403 only where the route table says so."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from parrot.bots.base import BaseBot
from parrot.bots.basic import BasicBot
from parrot.utils.helpers import current_context

from ._host_probe import host_plugins  # noqa: F401
from .test_agents_db_mode import BASE, _offline, pool  # noqa: F401  (fixtures)
from .test_agents_visibility import create, tenant_app, who

# (method, path template, json body). ``wiki`` is a built-in the tenant policy refuses (422 on a write): a caller who
# passes the access gate gets that 422, never a 403/404 about the AGENT.
MANAGE_ROUTES = [
    ("post", "/agents/{n}/tools", {"tools": ["shell"], "toolkits": []}),
    ("post", "/agents/{n}/toolkits", {"slug": "wiki", "params": {}}),
    ("get", "/agents/{n}/toolkit-config", None),
    ("put", "/agents/{n}/toolkits/wiki", {"params": {}, "user_overridable": []}),
    ("delete", "/agents/{n}/toolkits/wiki", None),
    ("get", "/agents/{n}/toolkits/wiki/options/project", None),
    ("get", "/agents/{n}/mcp-servers", None),
    ("put", "/agents/{n}/mcp-servers", {"servers": []}),
    ("get", "/agents/{n}/files/kb", None),
    ("put", "/agents/{n}/files/kb/x.md", {"content": "c"}),
    ("delete", "/agents/{n}/files/kb/x.md", None),
]
OWN_OVERRIDE_ROUTES = [
    ("get", "/agents/{n}/toolkits/wiki/me", None),
    ("put", "/agents/{n}/toolkits/wiki/me", {"params": {}}),
    ("delete", "/agents/{n}/toolkits/wiki/me", None),
]
SEE_ROUTES = [("post", "/agents/{n}/test/ask", {"query": "hi"}), ("delete", "/agents/{n}/test", None)]
ALL_ROUTES = SEE_ROUTES + MANAGE_ROUTES + OWN_OVERRIDE_ROUTES


async def call(client, route, name, caller):
    method, path, body = route
    kwargs = {"json": body} if body is not None else {}
    resp = await getattr(client, method)(f"{BASE}{path.format(n=name)}", headers=caller, **kwargs)
    try:
        payload = await resp.json()
    except Exception:  # noqa: BLE001
        payload = None
    return resp.status, payload


def about_the_agent(status, body) -> bool:
    """True when the response is the access refusal of the AGENT (404 not_found / 403 not_manageable)."""
    if not isinstance(body, dict):
        return False
    return (status == 404 and body.get("code") == "not_found" and "Agent '" in str(body.get("message"))) or (
        status == 403 and body.get("code") == "not_manageable")


@pytest.fixture(autouse=True)
def _asks(monkeypatch):
    """No LLM: every ask is recorded with the ``studio_scope`` bound in its request context."""
    log: list = []

    async def _ask(self, question=None, **_kw):
        ctx = current_context()
        log.append({"bot": self.name, "scope": None if ctx is None else ctx.kwargs.get("studio_scope")})
        return SimpleNamespace(content=f"echo:{question}", metadata={})

    monkeypatch.setattr(BasicBot, "ask", _ask)
    monkeypatch.setattr(BaseBot, "ask", _ask)
    return log


async def seed(client):
    assert (await create(client, "mine", who("u1")))[0].status == 201                      # private
    assert (await create(client, "shared", who("u1"), visibility="tenant"))[0].status == 201
    assert (await create(client, "theirs", who("u9", "globex")))[0].status == 201


@pytest.mark.parametrize("route", ALL_ROUTES, ids=lambda r: f"{r[0]} {r[1]}")
async def test_invisible_is_the_identical_404(aiohttp_client, pool, route):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    outcomes = {}
    for label, name in (("hidden", "mine"), ("other_tenant", "theirs"), ("absent", "nothing")):
        status, body = await call(client, route, name, who("u2"))
        outcomes[label] = (status, body["code"] if isinstance(body, dict) else None,
                           str(body["message"]).replace(name, "X") if isinstance(body, dict) else None)
    if route in OWN_OVERRIDE_ROUTES[2:]:
        # DELETE .../me is idempotent by design: identical for hidden, other-tenant and absent agents
        assert outcomes["hidden"] == outcomes["other_tenant"] == outcomes["absent"]
        return
    assert outcomes["hidden"] == outcomes["other_tenant"] == outcomes["absent"], outcomes
    assert outcomes["absent"][0] == 404


@pytest.mark.parametrize("route", MANAGE_ROUTES, ids=lambda r: f"{r[0]} {r[1]}")
async def test_visible_not_manageable_is_403(aiohttp_client, pool, route):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    status, body = await call(client, route, "shared", who("u2"))
    assert status == 403 and body["code"] == "not_manageable", (route, status, body)


@pytest.mark.parametrize("route", SEE_ROUTES + OWN_OVERRIDE_ROUTES, ids=lambda r: f"{r[0]} {r[1]}")
async def test_visible_routes_allow_a_peer(aiohttp_client, pool, route):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    status, body = await call(client, route, "shared", who("u2"))
    assert not about_the_agent(status, body), (route, status, body)


@pytest.mark.parametrize("route", ALL_ROUTES, ids=lambda r: f"{r[0]} {r[1]}")
async def test_owner_and_admin_pass_the_access_gate(aiohttp_client, pool, route):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    for caller in (who("u1"), who("u4", admin=True)):
        status, body = await call(client, route, "mine", caller)
        assert not about_the_agent(status, body), (route, caller, status, body)


async def test_files_get_is_403_only_in_opted_in_hosts(aiohttp_client, pool):  # noqa: F811
    """FEAT-467 ``test_get_does_not_require_ownership`` stays true without a resolver."""
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    assert (await call(client, ("get", "/agents/{n}/files/kb", None), "shared", who("u2")))[0] == 403
    plain = await aiohttp_client(tenant_app(pool, resolver=False))
    assert (await create(plain, "plain", {"X-User": "u1"}))[0].status == 201
    resp = await plain.get(f"{BASE}/agents/plain/files/kb", headers={"X-User": "u2"})
    assert resp.status == 200


async def test_test_ask_binds_studio_scope_with_the_agent(aiohttp_client, pool, _asks):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    status, body = await call(client, SEE_ROUTES[0], "shared", who("u2", groups="g1"))
    assert status == 200, body
    assert len(_asks) == 1
    scope = _asks[0]["scope"]
    assert scope.caller.user_id == "u2" and scope.caller.tenant == "acme" and scope.caller.groups == {"g1"}
    assert scope.agent.name == "shared" and scope.agent.tenant == "acme" and scope.agent.owner == "u1"
    assert scope.agent.visibility == "tenant" and scope.agent.agent_id is not None
    # re-checked on every ask: once the agent is hidden again the next ask is the identical 404 and binds nothing
    resp = await client.patch(f"{BASE}/agents/shared/visibility", json={"visibility": "private"}, headers=who("u1"))
    assert resp.status in (200, 404)   # the visibility route is registered by the W4 task, not by this app
    await client.delete(f"{BASE}/agents/shared", headers=who("u1"))
    status, _ = await call(client, SEE_ROUTES[0], "shared", who("u2"))
    assert status == 404 and len(_asks) == 1


async def test_plain_host_binds_nothing(aiohttp_client, pool, _asks):  # noqa: F811
    plain = await aiohttp_client(tenant_app(pool, resolver=False))
    assert (await create(plain, "plain", {"X-User": "u1"}))[0].status == 201
    resp = await plain.post(f"{BASE}/agents/plain/test/ask", json={"query": "hi"}, headers={"X-User": "u1"})
    assert resp.status == 200 and _asks[0]["scope"] is None


async def test_me_override_needs_a_visible_agent_with_the_toolkit_configured(  # noqa: F811
    aiohttp_client, pool, host_plugins, monkeypatch
):
    """A configured toolkit makes the per-user route observable: hidden ⇒ the same 404 as absent; visible ⇒ 200."""
    from unittest.mock import AsyncMock

    from parrot.handlers.toolkit_persistence import ToolkitConfigService

    monkeypatch.setattr(ToolkitConfigService, "load", AsyncMock(return_value=[]))   # the per-user store: no DocumentDB
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    for name in ("mine", "shared"):
        resp = await client.put(f"{BASE}/agents/{name}/toolkits/tp_probe", headers=who("u1"),
                                json={"params": {}, "user_overridable": ["token"]})
        assert resp.status == 200, await resp.text()
    route = ("get", "/agents/{n}/toolkits/tp_probe/me", None)
    hidden = await call(client, route, "mine", who("u2"))
    absent = await call(client, route, "nothing", who("u2"))
    assert hidden[0] == absent[0] == 404 and hidden[1]["code"] == absent[1]["code"]
    assert hidden[1]["message"] == absent[1]["message"]
    assert (await call(client, route, "shared", who("u2")))[0] == 200            # visible: the caller's OWN override
    put = ("put", "/agents/{n}/toolkits/tp_probe/me", {"params": {"token": "t"}})
    assert (await call(client, put, "mine", who("u2")))[0] == 404
