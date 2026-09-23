"""Tests for per-user Agent Studio toolkit overrides."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.handlers.studio import toolkit_overrides as overrides
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.toolkit_persistence import ToolkitConfigService, UserToolkitOverride
from parrot.tools.spec import ToolkitSpec


def _unwrap(method):
    """Remove auth decorators to exercise handler method bodies directly."""
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _decode(response: web.Response) -> dict:
    """Decode an aiohttp JSON response body."""
    return json.loads(response.body)


def _handler(method: str, body: dict | None = None, session: dict | None = None):
    """Build a handler with authentication and PBAC seams stubbed."""
    request = make_mocked_request(
        method,
        "/x",
        match_info={"name": "agent", "slug": "jira"},
        app=web.Application(),
    )
    if body is not None:
        request.json = AsyncMock(return_value=body)
    handler = overrides.StudioUserToolkitOverrideHandler(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="user-1"))
    handler._pbac_gate = AsyncMock(return_value=None)
    handler._resolve_session = AsyncMock(return_value=session if session is not None else {})
    return handler


def _store(monkeypatch, spec: ToolkitSpec, schema: dict):
    """Install a deterministic agent tooling store fake."""

    class Store:
        def __init__(self, handler):
            self.handler = handler

        async def load(self, name):
            return SimpleNamespace(tooling=SimpleNamespace(toolkits=[spec]))

        def schema_for(self, slug):
            return object, schema

    monkeypatch.setattr(overrides, "AgentToolingStore", Store)


@pytest.mark.asyncio
async def test_revision_empty(monkeypatch):
    """Revision is empty when the user has no overrides."""
    service = ToolkitConfigService()

    async def load(user_id, agent_id):
        return []

    monkeypatch.setattr(service, "load", load)
    assert await service.revision("u", "a") == ""


@pytest.mark.asyncio
async def test_put_rejects_non_overridable(monkeypatch):
    """PUT reports all submitted parameters the operator did not allow."""
    _store(monkeypatch, ToolkitSpec(slug="jira", user_overridable=["token"]), {"properties": {}})
    handler = _handler("PUT", {"params": {"server_url": "https://example.test"}})

    response = await _unwrap(overrides.StudioUserToolkitOverrideHandler.put)(handler)

    assert response.status == 422
    assert await _decode(response) == {
        "message": "One or more parameters are not user-overridable.",
        "code": "not_overridable",
        "details": {"params": ["server_url"]},
    }


@pytest.mark.asyncio
async def test_put_stores_secret_for_calling_user_and_clears_revision(monkeypatch):
    """Secrets use the caller's vault namespace and invalidate the session marker."""
    _store(
        monkeypatch,
        ToolkitSpec(slug="jira", user_overridable=["token"]),
        {"properties": {"token": {"x-secret": True}}},
    )
    saved = AsyncMock()
    stored = AsyncMock()
    monkeypatch.setattr(overrides.ToolkitConfigService, "load", AsyncMock(return_value=[]))
    monkeypatch.setattr(overrides.ToolkitConfigService, "save", saved)
    monkeypatch.setattr(overrides, "retrieve_vault_credential", AsyncMock(return_value={}))
    monkeypatch.setattr(overrides, "store_vault_credential", stored)
    session = {"agent_toolkit_overrides_rev": "old"}
    handler = _handler("PUT", {"params": {"token": "secret"}}, session)

    response = await _unwrap(overrides.StudioUserToolkitOverrideHandler.put)(handler)

    assert response.status == 200
    stored.assert_awaited_once_with("user-1", "toolkit_jira_agent_user", {"token": "secret"})
    override = saved.await_args.args[0]
    assert override.params == {} and override.secret_refs == {"token": "toolkit_jira_agent_user"}
    assert "agent_toolkit_overrides_rev" not in session


@pytest.mark.asyncio
async def test_get_masks_override_and_delete_removes_vault(monkeypatch):
    """GET masks stored secrets and DELETE removes both persistent resources."""
    _store(monkeypatch, ToolkitSpec(slug="jira", user_overridable=["token"]), {"properties": {}})
    stored = UserToolkitOverride(
        user_id="user-1", agent_id="agent", slug="jira", params={"server_url": "https://example.test"},
        secret_refs={"token": "toolkit_jira_agent_user"},
    )
    monkeypatch.setattr(overrides.ToolkitConfigService, "load", AsyncMock(return_value=[stored]))
    get_handler = _handler("GET")

    get_response = await _unwrap(overrides.StudioUserToolkitOverrideHandler.get)(get_handler)

    assert await _decode(get_response) == {
        "slug": "jira",
        "overridable": ["token"],
        "params": {"server_url": "https://example.test", "token": "********"},
        "configured": True,
    }
    removed = AsyncMock(return_value=True)
    deleted = AsyncMock()
    monkeypatch.setattr(overrides.ToolkitConfigService, "remove", removed)
    monkeypatch.setattr(overrides, "delete_vault_credential", deleted)
    session = {"agent_toolkit_overrides_rev": "old"}
    delete_handler = _handler("DELETE", session=session)

    delete_response = await _unwrap(overrides.StudioUserToolkitOverrideHandler.delete)(delete_handler)

    assert delete_response.status == 200
    removed.assert_awaited_once_with("user-1", "agent", "jira")
    deleted.assert_awaited_once_with("user-1", "toolkit_jira_agent_user")
    assert "agent_toolkit_overrides_rev" not in session
