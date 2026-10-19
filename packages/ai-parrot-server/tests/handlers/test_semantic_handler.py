"""Route and session coverage for the optional semantic HTTP surface."""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from parrot.handlers.semantic import SemanticLayerHandler


def test_handler_routes_and_401() -> None:
    """Register semantic routes only behind the optional-satellite guard."""
    manager = Path(__file__).parents[2] / "src/parrot/manager/manager.py"
    tree = ast.parse(manager.read_text())
    guards = [node for node in ast.walk(tree) if isinstance(node, ast.If)]
    semantic_guard = next(
        node
        for node in guards
        if isinstance(node.test, ast.Compare)
        and "find_spec('parrot.semantic')" in ast.unparse(node.test)
    )
    calls = [ast.unparse(node) for node in ast.walk(semantic_guard) if isinstance(node, ast.Call)]
    assert "router.add_view('/api/v1/agents/semantic/{agent_id}', SemanticLayerHandler)" in calls
    assert "router.add_view('/api/v1/agents/semantic/{agent_id}/{tail:.*}', SemanticLayerHandler)" in calls


@pytest.mark.asyncio
async def test_handler_returns_401_without_session(monkeypatch) -> None:
    """The handler returns 401 before attempting agent or toolkit resolution."""
    handler = SemanticLayerHandler.__new__(SemanticLayerHandler)
    handler._request = type("Request", (), {"match_info": {"agent_id": "demo"}})()
    handler.json_response = lambda content, status=200: type("Response", (), {"content": content, "status": status})()
    monkeypatch.setattr("parrot.handlers.semantic.get_session", AsyncMock(return_value={}))

    response = await SemanticLayerHandler.get.__wrapped__.__wrapped__(handler)

    assert response.status == 401
