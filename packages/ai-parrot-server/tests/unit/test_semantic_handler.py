"""Regression contract: authenticated semantic HTTP views (M11a)."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

import pytest

from parrot.handlers.semantic import SemanticLayerHandler


class _Request:
    """Minimal authenticated request for direct handler behavior tests."""

    def __init__(self, *, tail: str = "", body: object | None = None) -> None:
        self.app: dict[str, object] = {}
        self.match_info = {"agent_id": "trusted-agent", "tail": tail}
        self._body = body
        self.user = SimpleNamespace(user_id="trusted-user", tenant_id="trusted-tenant", roles=("analyst",))

    async def json(self) -> object:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _handler(request: _Request) -> SemanticLayerHandler:
    """Create a handler without framework routing setup."""
    handler = SemanticLayerHandler.__new__(SemanticLayerHandler)
    handler._request = request
    handler.logger = logging.getLogger("test.semantic_handler")
    return handler


def _enable_semantic_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expose the task-local optional satellite without changing the shared environment."""
    import parrot

    source = str(Path(__file__).parents[3] / "ai-parrot-semantic" / "src" / "parrot")
    monkeypatch.setattr(parrot, "__path__", [*parrot.__path__, source])


def _unwrap(method):
    """Return the undecorated view method for unit-level behavior coverage."""
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _response_body(response) -> dict:
    """Decode a JSON aiohttp response."""
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_routes_session_401_and_no_satellite(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject absent server session and malformed client input before toolkit use."""
    request = _Request(body={"model": "orders", "metrics": ["revenue"]})
    handler = _handler(request)
    monkeypatch.setattr("parrot.handlers.semantic.get_session", AsyncMock(return_value=None))

    response = await _unwrap(SemanticLayerHandler.get)(handler)
    assert response.status == 401
    assert (await _response_body(response))["error"] == "authenticated session is required"

    malformed = _handler(_Request(tail="compile", body=[]))
    response = await _unwrap(SemanticLayerHandler.post)(malformed)
    assert response.status == 400
    assert (await _response_body(response))["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_trusted_agent_session_and_local_class_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use trusted path/session state and reject local-only toolkit registrations."""
    _enable_semantic_source(monkeypatch)
    from parrot.semantic.bootstrap import LocalSemanticLayerToolkit

    request = _Request(tail="compile", body={"model": "orders", "metrics": ["revenue"], "agent_id": "attacker"})
    handler = _handler(request)
    server_session = {"session_id": "server-session", "user_id": "trusted-user", "tenant_id": "trusted-tenant"}
    monkeypatch.setattr("parrot.handlers.semantic.get_session", AsyncMock(return_value=server_session))

    context = await handler._pctx()
    identity = await handler._identity(context, "trusted-agent")
    assert identity.agent_id == "trusted-agent"
    assert identity.session_id == "server-session"
    assert identity.ctx.user_id == "trusted-user"

    class _Toolkit:
        """Observe the context held around a direct HTTP toolkit call."""

        async def compile_query(self, query):
            from parrot.semantic.context import current_identity

            bound = current_identity()
            assert bound is not None
            assert bound.agent_id == "trusted-agent"
            assert bound.session_id == "server-session"
            return {"model": query.model}

    monkeypatch.setattr(handler, "_toolkit", AsyncMock(return_value=_Toolkit()))
    response = await _unwrap(SemanticLayerHandler.post)(handler)
    assert response.status == 200
    assert await _response_body(response) == {"model": "orders"}
    monkeypatch.setattr(handler, "_toolkit", SemanticLayerHandler._toolkit.__get__(handler, SemanticLayerHandler))

    tool_manager = MagicMock()
    tool_manager.find_registered_toolkit.side_effect = lambda cls: (
        object() if cls is LocalSemanticLayerToolkit else None
    )
    bot_manager = MagicMock()
    bot_manager.get_bot = AsyncMock(return_value=SimpleNamespace(tool_manager=tool_manager))
    request.app["bot_manager"] = bot_manager
    response = await _unwrap(SemanticLayerHandler.post)(handler)
    assert response.status == 403
    assert (await _response_body(response))["error"] == "local_toolkit_rejected"


@pytest.mark.asyncio
async def test_handoff_unavailable_without_guarded_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return the stable unavailable result when no guarded sink is configured."""
    _enable_semantic_source(monkeypatch)
    from parrot.semantic.errors import SemanticResultError

    request = _Request(tail="results/result-1/dataset", body={"name": "published"})
    handler = _handler(request)
    server_session = {"session_id": "server-session", "user_id": "trusted-user", "tenant_id": "trusted-tenant"}
    monkeypatch.setattr("parrot.handlers.semantic.get_session", AsyncMock(return_value=server_session))
    toolkit = MagicMock()
    toolkit.save_result_as_dataset = AsyncMock(
        side_effect=SemanticResultError("handoff_unavailable", "Dataset hand-off is not configured")
    )
    monkeypatch.setattr(handler, "_toolkit", AsyncMock(return_value=toolkit))

    response = await _unwrap(SemanticLayerHandler.post)(handler)
    assert response.status == 503
    assert await _response_body(response) == {"error": "handoff_unavailable"}
    toolkit.save_result_as_dataset.assert_awaited_once_with("result-1", "published", None)
