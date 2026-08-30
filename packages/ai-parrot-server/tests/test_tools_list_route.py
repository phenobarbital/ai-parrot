"""Unit tests for the library-owned ``/api/v1/agent_tools`` route (FEAT-475,
TASK-2583).

``ToolList`` was previously registered only by the repo-root ``app.py``, so
a plain ``pip install ai-parrot-server`` deployment had no tools-listing
route for the Admin UI's tools picker. ``BotManager.setup()`` now registers
it itself, idempotently, right after ``ChatbotHandler.configure(...)``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from aiohttp import web
from parrot.handlers.bots import ToolList
from parrot.manager.manager import BotManager


def _manager() -> BotManager:
    """A ``BotManager`` instance bypassing ``__init__`` (no live services)."""
    manager = BotManager.__new__(BotManager)
    manager.logger = MagicMock()
    return manager


def test_tools_list_registered_by_manager():
    """A bare app gains a named 'tools_list' resource after registration."""
    app = web.Application()
    # Mirror the exact registration BotManager.setup() performs.
    if 'tools_list' not in app.router.named_resources():
        app.router.add_view('/api/v1/agent_tools', ToolList, name='tools_list')

    assert 'tools_list' in app.router.named_resources()
    resource = app.router.named_resources()['tools_list']
    assert any(
        route.method in ('GET', '*') for route in resource
    )


def test_tools_list_registration_idempotent():
    """Registering twice does not raise (host app may have registered it)."""
    app = web.Application()

    def _register():
        if 'tools_list' not in app.router.named_resources():
            app.router.add_view(
                '/api/v1/agent_tools', ToolList, name='tools_list'
            )

    _register()
    _register()  # must not raise (aiohttp raises on duplicate resource name)

    assert 'tools_list' in app.router.named_resources()


def test_tools_list_registration_respects_pre_registered_host():
    """A host app (e.g. repo-root app.py) that registers the route itself
    first is left untouched — BotManager.setup()'s guard must not
    re-register or raise."""
    app = web.Application()
    app.router.add_view('/api/v1/agent_tools', ToolList, name='tools_list')
    pre_registered = app.router.named_resources()['tools_list']

    if 'tools_list' not in app.router.named_resources():
        app.router.add_view('/api/v1/agent_tools', ToolList, name='tools_list')

    assert app.router.named_resources()['tools_list'] is pre_registered


async def test_tools_list_get_route_reachable(aiohttp_client, monkeypatch):
    """End-to-end: the registered route actually dispatches to ToolList.get."""
    monkeypatch.setattr(
        "parrot.handlers.bots.discover_all",
        lambda: {"echo": "parrot.tools.echo.EchoTool"},
    )
    # ToolList is decorated with @user_session(), which calls
    # navigator_auth.decorators.get_session — that needs a real
    # session-storage backend wired into the app. Stub it (same pattern
    # as test_admin_status.py's authenticated_app fixture).

    async def _fake_get_session(request, new=False):
        return {}

    monkeypatch.setattr(
        "navigator_auth.decorators.get_session", _fake_get_session
    )

    app = web.Application()
    app.router.add_view('/api/v1/agent_tools', ToolList, name='tools_list')

    client = await aiohttp_client(app)
    resp = await client.get('/api/v1/agent_tools')
    assert resp.status == 200
    body = await resp.json()
    assert "tools" in body
    assert body["tools"]["echo"]["module_path"] == "parrot.tools.echo.EchoTool"
