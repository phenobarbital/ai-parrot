"""Unit tests for closing the streaming auth bypasses (FEAT-446 TASK-2324).

Asserts against ``navigator_auth.conf.exclude_list`` contents, not route
behavior — actual anonymous-caller rejection is proven by TASK-2325's
integration suite.
"""
from __future__ import annotations

import pytest
from aiohttp import web
from navigator_auth.conf import exclude_list
from parrot import conf
from parrot.handlers.stream import StreamHandler
from parrot.handlers.user import UserSocketManager

_STREAM_PATHS = (
    "/bots/*/stream/sse",
    "/bots/*/stream/ndjson",
    "/bots/*/stream/chunked",
    "/bots/*/stream/ws",
)


@pytest.fixture(autouse=True)
def _clean_exclude_list():
    """Snapshot/restore the shared, mutable ``exclude_list`` around each test."""
    before = list(exclude_list)
    yield
    exclude_list[:] = before


@pytest.fixture(autouse=True)
def _reset_saas_mode(monkeypatch):
    monkeypatch.setattr(conf, "PARROT_SAAS_MODE", False)
    yield


class TestStreamExclusions:
    def test_no_stream_excludes_after_setup(self):
        handler = StreamHandler()
        app = web.Application()

        handler.configure_routes(app)

        for path in _STREAM_PATHS:
            assert path not in exclude_list

    def test_stream_routes_still_registered(self):
        handler = StreamHandler()
        app = web.Application()

        handler.configure_routes(app)

        registered = {
            (route.method, route.resource.canonical)
            for route in app.router.routes()
            if route.resource is not None
        }
        assert ("POST", "/bots/{bot_id}/stream/sse") in registered
        assert ("POST", "/bots/{bot_id}/stream/ndjson") in registered
        assert ("POST", "/bots/{bot_id}/stream/chunked") in registered
        assert ("GET", "/bots/{bot_id}/stream/ws") in registered

    def test_ws_user_excluded_legacy(self, monkeypatch):
        monkeypatch.setattr(conf, "PARROT_SAAS_MODE", False)
        app = web.Application()
        route_prefix = "/ws/user_test_legacy"

        UserSocketManager(app, route_prefix=route_prefix)

        assert route_prefix in exclude_list

    def test_ws_user_not_excluded_saas(self, monkeypatch):
        monkeypatch.setattr(conf, "PARROT_SAAS_MODE", True)
        app = web.Application()
        route_prefix = "/ws/user_test_saas"

        UserSocketManager(app, route_prefix=route_prefix)

        assert route_prefix not in exclude_list
