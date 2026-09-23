"""Tests for persisted Agent Studio toolkit configuration endpoints."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.studio import toolkit_config as tc
from parrot.handlers.studio._base import StudioUser
from parrot.tools.spec import AgentMCPServerSpec, ToolkitSpec


def _unwrap(method):
    """Remove auth decorators to exercise handler method bodies directly."""
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _decode(response: web.Response) -> dict:
    """Decode an aiohttp JSON response body."""
    return json.loads(response.body)


def _handler(cls, method, match_info, body=None, query=""):
    """Build an authenticated handler with ownership and PBAC seams stubbed."""
    request = make_mocked_request(method, f"/x{query}", match_info=match_info, app=web.Application())
    if body is not None:
        request.json = AsyncMock(return_value=body)
    handler = cls(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="42"))
    handler._pbac_gate = AsyncMock(return_value=None)
    return handler


class _OptionsToolkit:
    """Minimal options toolkit used to prove persisted-only construction."""

    options_params = frozenset({"project"})
    auto_open = False

    def __init__(self, server_url):
        self.server_url = server_url
        self._opened = False

    async def config_options(self, param):
        assert param == "project"
        return [{"value": self.server_url, "label": self.server_url}]

    async def _close(self):
        self._opened = False


def _state(*, toolkits=None, servers=None, editable=True, owner="42", reason=None):
    """Create the minimal persisted tooling state consumed by handlers."""
    return SimpleNamespace(
        owner=owner,
        editable=editable,
        reason=reason,
        tooling=SimpleNamespace(toolkits=toolkits or [], mcp_servers=servers or []),
    )


def _store(monkeypatch, state, *, put_toolkit=None, delete_toolkit=None, put_mcp_servers=None, schema_for=None):
    """Install a deterministic AgentToolingStore fake for one handler test."""

    class Store:
        def __init__(self, handler):
            self.handler = handler

        async def load(self, name):
            return state

        async def put_toolkit(self, name, slug, params, user_overridable):
            if put_toolkit is not None:
                return await put_toolkit(name, slug, params, user_overridable)

        async def delete_toolkit(self, name, slug):
            if delete_toolkit is not None:
                return await delete_toolkit(name, slug)

        async def put_mcp_servers(self, name, servers):
            if put_mcp_servers is not None:
                return await put_mcp_servers(name, servers)

        def schema_for(self, slug):
            if schema_for is None:
                raise LookupError(slug)
            return schema_for(slug)

    monkeypatch.setattr(tc, "AgentToolingStore", Store)


@pytest.mark.asyncio
async def test_put_returns_persisted_reload_response(monkeypatch):
    """PUT persists one spec and requires the operator to reload the agent."""
    saved = AsyncMock()
    _store(monkeypatch, _state(), put_toolkit=saved)
    handler = _handler(
        tc.StudioAgentToolkitsHandler,
        "PUT",
        {"name": "agent", "slug": "jira"},
        {"params": {"server_url": "https://jira.example"}, "user_overridable": ["token"]},
    )

    response = await _unwrap(tc.StudioAgentToolkitsHandler.put)(handler)

    assert response.status == 200
    assert await _decode(response) == {"agent": "agent", "slug": "jira", "reload_required": True, "persisted": True}
    saved.assert_awaited_once_with("agent", "jira", {"server_url": "https://jira.example"}, ["token"])


@pytest.mark.asyncio
async def test_put_read_only_409(monkeypatch):
    """Read-only definitions map persistence refusal to the public 409 code."""

    async def reject(*args):
        raise PermissionError("py agent")

    _store(monkeypatch, _state(), put_toolkit=reject)
    handler = _handler(tc.StudioAgentToolkitsHandler, "PUT", {"name": "agent", "slug": "jira"}, {"params": {}})

    response = await _unwrap(tc.StudioAgentToolkitsHandler.put)(handler)

    body = await _decode(response)
    assert response.status == 409 and body["code"] == "read_only_definition"


@pytest.mark.asyncio
async def test_put_vault_failure_503(monkeypatch):
    """Vault failures do not leak implementation detail and return 503."""

    async def unavailable(*args):
        raise RuntimeError("vault unavailable")

    _store(monkeypatch, _state(), put_toolkit=unavailable)
    handler = _handler(tc.StudioAgentToolkitsHandler, "PUT", {"name": "agent", "slug": "jira"}, {"params": {}})

    response = await _unwrap(tc.StudioAgentToolkitsHandler.put)(handler)

    body = await _decode(response)
    assert response.status == 503 and body["code"] == "vault_unavailable"


@pytest.mark.asyncio
async def test_get_masks_specs_and_marks_unavailable(monkeypatch):
    """GET masks vaulted params and reports slugs no longer resolvable."""
    state = _state(
        toolkits=[
            ToolkitSpec(slug="gone", params={}, secret_refs={}),
            ToolkitSpec(slug="jira", params={"token": "x"}, secret_refs={"token": "vault"}),
        ]
    )
    _store(
        monkeypatch,
        state,
        schema_for=lambda slug: (_OptionsToolkit, {}) if slug == "jira" else (_ for _ in ()).throw(LookupError(slug)),
    )
    handler = _handler(tc.StudioAgentToolkitsHandler, "GET", {"name": "agent"})

    response = await _unwrap(tc.StudioAgentToolkitsHandler.get)(handler)

    body = await _decode(response)
    assert body["unavailable"] == ["gone"]
    assert body["toolkits"][1]["params"]["token"] == "********"


@pytest.mark.asyncio
async def test_options_unknown_param_404(monkeypatch):
    """Options only allow parameters explicitly declared by the toolkit."""
    _store(monkeypatch, _state(), schema_for=lambda slug: (_OptionsToolkit, {}))
    handler = _handler(tc.StudioToolkitOptionsHandler, "GET", {"name": "agent", "slug": "jira", "param": "unknown"})

    response = await _unwrap(tc.StudioToolkitOptionsHandler.get)(handler)

    assert response.status == 404 and (await _decode(response))["code"] == "not_found"


@pytest.mark.asyncio
async def test_options_unconfigured_409(monkeypatch):
    """Options cannot be evaluated before an agent persists the toolkit spec."""
    _store(monkeypatch, _state(), schema_for=lambda slug: (_OptionsToolkit, {}))
    handler = _handler(tc.StudioToolkitOptionsHandler, "GET", {"name": "agent", "slug": "jira", "param": "project"})

    response = await _unwrap(tc.StudioToolkitOptionsHandler.get)(handler)

    assert response.status == 409 and (await _decode(response))["code"] == "not_configured"


@pytest.mark.asyncio
async def test_options_failure_502(monkeypatch):
    """Toolkit option lookup failures map to the stable options_failed response."""

    class BrokenToolkit(_OptionsToolkit):
        async def config_options(self, param):
            raise OSError("network")

    state = _state(toolkits=[ToolkitSpec(slug="jira", params={"server_url": "https://saved"})])
    _store(monkeypatch, state, schema_for=lambda slug: (BrokenToolkit, {}))
    monkeypatch.setattr(tc, "hydrate_params", AsyncMock(return_value={"server_url": "https://saved"}))
    handler = _handler(tc.StudioToolkitOptionsHandler, "GET", {"name": "agent", "slug": "jira", "param": "project"})

    response = await _unwrap(tc.StudioToolkitOptionsHandler.get)(handler)

    assert response.status == 502 and (await _decode(response))["code"] == "options_failed"


@pytest.mark.asyncio
async def test_options_ignores_query(monkeypatch):
    """Options instance receives only persisted, hydrated configuration."""
    state = _state(toolkits=[ToolkitSpec(slug="jira", params={"server_url": "https://saved"})])
    _store(monkeypatch, state, schema_for=lambda slug: (_OptionsToolkit, {}))
    hydrate = AsyncMock(return_value={"server_url": "https://saved"})
    monkeypatch.setattr(tc, "hydrate_params", hydrate)
    handler = _handler(
        tc.StudioToolkitOptionsHandler,
        "GET",
        {"name": "agent", "slug": "jira", "param": "project"},
        query="?server_url=http://evil",
    )

    response = await _unwrap(tc.StudioToolkitOptionsHandler.get)(handler)

    assert (await _decode(response))["options"] == [{"value": "https://saved", "label": "https://saved"}]
    hydrate.assert_awaited_once_with(state.tooling.toolkits[0])


@pytest.mark.asyncio
async def test_mcp_get_masks_server_secrets(monkeypatch):
    """MCP GET returns masked server credentials."""
    server = AgentMCPServerSpec(
        name="source", params={"headers": {"Authorization": "secret"}}, secret_refs={"headers": "vault"}
    )
    _store(monkeypatch, _state(servers=[server]))
    handler = _handler(tc.StudioAgentMcpServersHandler, "GET", {"name": "agent"})

    response = await _unwrap(tc.StudioAgentMcpServersHandler.get)(handler)

    assert (await _decode(response))["servers"][0]["headers"] == "********"
