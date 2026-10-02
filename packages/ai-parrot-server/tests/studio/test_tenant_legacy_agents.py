"""PR #1564 F2: a tenant caller never reaches the global (legacy ``ai_bots`` / registry) agents' tooling.

Every route answers the one ``404 not_found`` an absent agent gets (FEAT-605), whoever the caller is.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.studio import toolkit_config as tc
from parrot.handlers.studio import toolkit_overrides as overrides
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.storage.models import StudioPartition
from parrot.handlers.studio.toolkits import StudioToolkitsHandler
from parrot.handlers.studio.tooling_store import AgentToolingStore

AGENT = "legacy-agent"


class _Row:
    """A legacy ``ai_bots`` row owned by someone else, with one overridable toolkit."""

    created_by = "someone-else"
    mcp_servers: list = []
    toolkit_config = {"wiki": {"slug": "wiki", "params": {}, "user_overridable": ["x"]}}

    def set(self, key, value):
        setattr(self, key, value)

    async def update(self):  # pragma: no cover - a write here is the bug
        raise AssertionError("a tenant must never write a legacy row")


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


def _wire(handler, tenant: str | None, *, superuser: bool = False, row: object | None = _Row()):
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="tenant-user", is_superuser=superuser))
    handler._pbac_gate = AsyncMock(return_value=None)
    handler._get_db_agent = AsyncMock(return_value=row)
    handler._studio_partition = AsyncMock(return_value=StudioPartition(tenant))
    handler._resolve_session = AsyncMock(return_value={})
    return handler


def _request(method: str, name: str = AGENT, slug: str = "wiki", body: dict | None = None):
    request = make_mocked_request(method, "/x", match_info={"name": name, "slug": slug}, app=web.Application())
    if body is not None:
        request.json = AsyncMock(return_value=body)
    return request


def _body(response: web.Response) -> dict:
    return json.loads(response.body)


async def test_store_load_refuses_legacy_db_agent_for_a_tenant():
    handler = _wire(SimpleNamespace(), "acme")
    handler._registry = lambda: None
    with pytest.raises(LookupError):
        await AgentToolingStore(handler).load(AGENT)
    handler._get_db_agent.assert_not_awaited()  # never even consulted


async def test_store_load_refuses_registry_agent_for_a_tenant():
    meta = SimpleNamespace(bot_config=SimpleNamespace(toolkits=[], mcp_servers=[]))
    registry = SimpleNamespace(get_metadata=lambda name: meta)
    handler = _wire(SimpleNamespace(), "acme", row=None)
    handler._registry = lambda: registry
    handler._registry_agent_owner = lambda _meta: "7"
    with pytest.raises(LookupError):
        await AgentToolingStore(handler).load(AGENT)


async def test_store_load_still_serves_legacy_agent_in_global_partition():
    handler = _wire(SimpleNamespace(), None)
    handler._registry = lambda: None
    state = await AgentToolingStore(handler).load(AGENT)
    assert state.source == "database" and state.owner == "someone-else"


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_override_routes_answer_404_for_a_legacy_agent_as_tenant(method):
    body = {"params": {"x": "1"}} if method == "PUT" else None
    handler = _wire(overrides.StudioUserToolkitOverrideHandler(_request(method, body=body)), "acme")
    handler._registry = lambda: None
    response = await _unwrap(getattr(overrides.StudioUserToolkitOverrideHandler, method.lower()))(handler)
    assert response.status == 404 and _body(response)["code"] == "not_found"


@pytest.mark.parametrize("superuser", [False, True], ids=["owner-or-member", "tenant-superuser"])
@pytest.mark.parametrize(
    ("cls", "method", "body"),
    [
        (tc.StudioAgentToolkitsHandler, "put", {"params": {}}),
        (tc.StudioAgentToolkitsHandler, "delete", None),
        (tc.StudioAgentMcpServersHandler, "put", {"servers": []}),
    ],
    ids=["put-toolkit", "delete-toolkit", "put-mcp"],
)
async def test_tenant_cannot_rewrite_a_global_agents_tooling(cls, method, body, superuser):
    handler = _wire(cls(_request(method.upper(), body=body)), "acme", superuser=superuser)
    handler._registry = lambda: None
    response = await _unwrap(getattr(cls, method))(handler)
    assert response.status == 404 and _body(response)["code"] == "not_found"


async def test_assign_owner_is_the_same_404_for_a_legacy_and_an_absent_agent_as_tenant():
    legacy = _wire(StudioToolkitsHandler(_request("POST")), "acme")
    legacy._registry = lambda: None
    absent = _wire(StudioToolkitsHandler(_request("POST", name="nope")), "acme", row=None)
    absent._registry = lambda: None
    seen = await legacy._assign_owner(AGENT)
    missing = await absent._assign_owner("nope")
    assert isinstance(seen, web.Response) and seen.status == 404
    assert (seen.status, _body(seen)["code"]) == (missing.status, _body(missing)["code"])


async def test_assign_owner_keeps_the_owner_check_for_a_legacy_agent_in_global_partition():
    handler = _wire(StudioToolkitsHandler(_request("POST")), None)
    handler._registry = lambda: None
    assert await handler._assign_owner(AGENT) == "someone-else"
