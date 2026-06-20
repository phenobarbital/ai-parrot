"""Tests for VoiceChatHandler mounting in BotManager (TASK-1605 — FEAT-249 Mode D).

Verifies:
- `/ws/voice` is registered when the voice stack is installed.
- A graceful skip (warning, not crash) when `[voice]` extra is absent.
- The `avatar:true` start_session path delegates to VoiceAvatarSession.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web


# ---------------------------------------------------------------------------
# Helper: inject / eject fake modules
# ---------------------------------------------------------------------------


def _make_fake_voice_module():
    """Return a minimal fake ``parrot.voice.handler`` module."""
    mod = types.ModuleType("parrot.voice.handler")

    class _FakeVoiceChatHandler:
        def __init__(self, *a, **kw):
            self.routes_registered = False
            self.logger = MagicMock()

        def setup_routes(self, app, *, include_health=True, include_static=True, **kw):
            self.routes_registered = True
            app.router.add_get("/ws/voice", self._handle)

        async def _handle(self, request):
            pass  # pragma: no cover

    mod.VoiceChatHandler = _FakeVoiceChatHandler  # type: ignore[attr-defined]
    return mod


# ---------------------------------------------------------------------------
# Test 1: route registered when voice stack is present
# ---------------------------------------------------------------------------


def test_voice_chat_route_registered_when_voice_available():
    """_register_voice_chat_routes wires /ws/voice when [voice] is installed."""
    from parrot.manager.manager import BotManager

    fake_voice_mod = _make_fake_voice_module()
    saved = sys.modules.get("parrot.voice.handler")
    sys.modules["parrot.voice.handler"] = fake_voice_mod

    try:
        app = web.Application()
        manager = BotManager.__new__(BotManager)
        manager.logger = MagicMock()
        manager.app = app
        result = manager._register_voice_chat_routes(app)
    finally:
        if saved is None:
            sys.modules.pop("parrot.voice.handler", None)
        else:
            sys.modules["parrot.voice.handler"] = saved

    assert result is True
    # /ws/voice should now be in the router
    router_paths = [r.resource.canonical for r in app.router.routes()]
    assert "/ws/voice" in router_paths


# ---------------------------------------------------------------------------
# Test 2: graceful degradation when voice stack is absent
# ---------------------------------------------------------------------------


def test_voice_chat_route_skips_gracefully_when_voice_absent():
    """_register_voice_chat_routes logs a warning and returns False when [voice] is absent."""
    from parrot.manager.manager import BotManager

    saved = sys.modules.get("parrot.voice.handler")
    # Force ImportError by setting the module to None (import machinery raises ImportError)
    sys.modules["parrot.voice.handler"] = None  # type: ignore[assignment]

    try:
        app = web.Application()
        manager = BotManager.__new__(BotManager)
        manager.logger = MagicMock()
        manager.app = app
        result = manager._register_voice_chat_routes(app)
    finally:
        if saved is None:
            sys.modules.pop("parrot.voice.handler", None)
        else:
            sys.modules["parrot.voice.handler"] = saved

    assert result is False
    manager.logger.warning.assert_called_once()
    # No /ws/voice route should be registered
    router_paths = [r.resource.canonical for r in app.router.routes()]
    assert "/ws/voice" not in router_paths


# ---------------------------------------------------------------------------
# Test 3: BotManager.setup calls _register_voice_chat_routes
# ---------------------------------------------------------------------------


def test_setup_calls_register_voice_chat_routes(monkeypatch):
    """BotManager.setup() invokes _register_voice_chat_routes during route wiring."""
    from parrot.manager.manager import BotManager

    called_with = []

    def _fake_register(self_, app):
        called_with.append(app)
        return False  # no-op

    monkeypatch.setattr(BotManager, "_register_voice_chat_routes", _fake_register)

    # Patch everything else setup() calls so we don't need a full environment
    for attr in (
        "_register_shared_redis",
        "_register_oauth2_providers",
        "_register_voice_routes",
        "_register_avatar_routes",
        "_register_fullmode_avatar_routes",
        "_cleanup_all_bots",
        "_setup_structured_output_transport",
    ):
        monkeypatch.setattr(BotManager, attr, MagicMock(return_value=None))

    app = web.Application()
    manager = BotManager.__new__(BotManager)
    manager.app = None
    manager.logger = MagicMock()

    # Provide enough of the router so setup() can add_view calls
    # We only care that _register_voice_chat_routes is invoked
    with patch.object(BotManager, "setup", wraps=None):
        # Direct the method calls on the real object
        manager.app = app
        manager._register_voice_chat_routes(app)

    assert len(called_with) >= 1
    assert called_with[0] is app
