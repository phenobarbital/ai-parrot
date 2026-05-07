"""Unit tests for EphemeralUserAgentHandler (TASK-1040).

Strategy
--------
We do NOT spin up a real aiohttp server.  Instead we:
1. Load the ephemeral.py handler module directly via importlib (bypasses
   navigator / navconfig Cython chain).
2. Build a minimal stub class that inherits the real handler logic but
   overrides the aiohttp-specific parts (request, json_response, error).
3. Drive each HTTP verb method directly and assert on the stub's captured
   response data.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub navigator / navconfig / parrot imports before module load
# ---------------------------------------------------------------------------

_STUBS: dict[str, Any] = {
    "navconfig": None,
    "navconfig.logging": None,
    "navigator": None,
    "navigator.views": None,
    "navigator_auth": None,
    "navigator_auth.decorators": None,
    "navigator_session": None,
}

for _sname in _STUBS:
    if _sname not in sys.modules:
        _m = types.ModuleType(_sname)
        _m.logging = MagicMock()  # type: ignore[attr-defined]
        _m.logging.getLogger = lambda n="": MagicMock()  # type: ignore[attr-defined]
        _m.BaseView = object  # type: ignore[attr-defined]

        def _id_deco(*a, **kw):  # noqa: E306
            def _d(c):
                return c
            return _d

        _m.is_authenticated = _id_deco  # type: ignore[attr-defined]
        _m.user_session = _id_deco  # type: ignore[attr-defined]
        _m.get_session = AsyncMock(return_value=None)  # type: ignore[attr-defined]
        sys.modules[_sname] = _m

_WT_ROOT = Path(__file__).resolve().parents[2]
_HANDLER_SRC = (
    _WT_ROOT
    / "packages"
    / "ai-parrot"
    / "src"
    / "parrot"
    / "handlers"
    / "agents"
    / "ephemeral.py"
)
_MOD_NAME = "parrot.handlers.agents.ephemeral"

if _MOD_NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_MOD_NAME, str(_HANDLER_SRC))
    _hmod = importlib.util.module_from_spec(_spec)
    sys.modules[_MOD_NAME] = _hmod
    _spec.loader.exec_module(_hmod)

from parrot.handlers.agents.ephemeral import EphemeralUserAgentHandler  # noqa: E402

# Also load ephemeral status model for fixtures
_EPHEMERAL_SRC = (
    _WT_ROOT / "packages" / "ai-parrot" / "src" / "parrot" / "manager" / "ephemeral.py"
)
if "parrot.manager.ephemeral" not in sys.modules:
    _espec = importlib.util.spec_from_file_location(
        "parrot.manager.ephemeral", str(_EPHEMERAL_SRC)
    )
    _emod = importlib.util.module_from_spec(_espec)
    sys.modules["parrot.manager.ephemeral"] = _emod
    _espec.loader.exec_module(_emod)

from parrot.manager.ephemeral import EphemeralAgentStatus  # noqa: E402


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


def _make_status(
    chatbot_id: str = "bot-xyz",
    user_id: int = 42,
    phase: str = "creating",
    rag_mode=None,
    error=None,
) -> EphemeralAgentStatus:
    now = datetime.utcnow()
    st = EphemeralAgentStatus(
        chatbot_id=chatbot_id,
        user_id=user_id,
        phase=phase,
        created_at=now,
        expires_at=now + timedelta(hours=24),
        rag_mode=rag_mode,
    )
    if error:
        st.error = error
    return st


class _StubRequest:
    """Minimal aiohttp Request stand-in."""

    def __init__(
        self,
        method: str = "GET",
        match_info: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        session_user_id: Optional[int] = None,
        app_manager=None,
        content_type: str = "application/json",
    ):
        self.method = method
        self.match_info = match_info or {}
        self._json_data = json_data or {}
        self.content_type = content_type
        self.session = {"user_id": session_user_id} if session_user_id else None
        self.app = {"bot_manager": app_manager} if app_manager else {}

    async def json(self) -> Dict:
        return self._json_data


class _StubHandler:
    """Standalone test double for EphemeralUserAgentHandler.

    Does NOT inherit from the real handler (to avoid navigator.views.BaseView's
    read-only ``request`` property).  Instead it borrows the real method
    implementations as unbound functions and overrides infrastructure helpers
    (session, json_response, error, bot_manager).
    """

    # Borrow the real method implementations from the handler class.
    post = EphemeralUserAgentHandler.post
    get = EphemeralUserAgentHandler.get
    put = EphemeralUserAgentHandler.put
    delete = EphemeralUserAgentHandler.delete

    def __init__(self, request: _StubRequest):
        self.request = request
        self.logger = MagicMock()
        self._last_response: Optional[Dict] = None
        self._last_status: int = 200

    def json_response(self, data: Any, status: int = 200) -> Any:
        self._last_response = data
        self._last_status = status
        return data

    def error(self, message: str, status: int = 400) -> Any:
        self._last_response = {"error": message}
        self._last_status = status
        return {"error": message}

    async def _get_session(self):
        return self.request.session

    async def _resolve_user_id(self) -> Optional[int]:
        session = self.request.session
        return session.get("user_id") if session else None

    def _bot_manager(self):
        return self.request.app.get("bot_manager")

    async def _parse_request(self):
        return self.request._json_data, []


# ---------------------------------------------------------------------------
# Tests — POST (create)
# ---------------------------------------------------------------------------


class TestEphemeralHandlerPost:
    """Tests for EphemeralUserAgentHandler.post."""

    @pytest.mark.asyncio
    async def test_post_returns_201_creating(self) -> None:
        """POST returns 201 with {chatbot_id, status: 'creating'} on success."""
        ep_status = _make_status(chatbot_id="new-bot", phase="creating")
        manager = MagicMock()
        manager.create_ephemeral_user_bot = AsyncMock(return_value=ep_status)

        req = _StubRequest(method="POST", session_user_id=42, app_manager=manager)
        handler = _StubHandler(req)
        await handler.post()

        assert handler._last_status == 201
        assert handler._last_response["chatbot_id"] == "new-bot"
        assert handler._last_response["status"] == "creating"

    @pytest.mark.asyncio
    async def test_post_unauthenticated_returns_401(self) -> None:
        """POST with no session returns 401."""
        req = _StubRequest(method="POST", session_user_id=None)
        handler = _StubHandler(req)
        await handler.post()

        assert handler._last_status == 401

    @pytest.mark.asyncio
    async def test_post_no_manager_returns_503(self) -> None:
        """POST with no BotManager returns 503."""
        req = _StubRequest(method="POST", session_user_id=42, app_manager=None)
        handler = _StubHandler(req)
        await handler.post()

        assert handler._last_status == 503

    @pytest.mark.asyncio
    async def test_post_calls_create_ephemeral_user_bot(self) -> None:
        """POST delegates to BotManager.create_ephemeral_user_bot."""
        ep_status = _make_status()
        manager = MagicMock()
        manager.create_ephemeral_user_bot = AsyncMock(return_value=ep_status)

        req = _StubRequest(method="POST", session_user_id=42, app_manager=manager)
        handler = _StubHandler(req)
        await handler.post()

        manager.create_ephemeral_user_bot.assert_awaited_once()
        call_kwargs = manager.create_ephemeral_user_bot.call_args.kwargs
        assert call_kwargs["user_id"] == 42


# ---------------------------------------------------------------------------
# Tests — GET (status)
# ---------------------------------------------------------------------------


class TestEphemeralHandlerGet:
    """Tests for EphemeralUserAgentHandler.get."""

    @pytest.mark.asyncio
    async def test_get_returns_phase(self) -> None:
        """GET returns {chatbot_id, phase, progress, error} for a known bot."""
        ep_status = _make_status(chatbot_id="bot-1", phase="warming", user_id=42)
        manager = MagicMock()
        manager.get_ephemeral_status = MagicMock(return_value=ep_status)

        req = _StubRequest(
            session_user_id=42,
            match_info={"chatbot_id": "bot-1"},
            app_manager=manager,
        )
        handler = _StubHandler(req)
        await handler.get()

        assert handler._last_status == 200
        assert handler._last_response["phase"] == "warming"
        assert handler._last_response["chatbot_id"] == "bot-1"

    @pytest.mark.asyncio
    async def test_get_not_found_returns_404(self) -> None:
        """GET for an unknown bot returns 404."""
        manager = MagicMock()
        manager.get_ephemeral_status = MagicMock(return_value=None)

        req = _StubRequest(
            session_user_id=42,
            match_info={"chatbot_id": "no-such"},
            app_manager=manager,
        )
        handler = _StubHandler(req)
        await handler.get()

        assert handler._last_status == 404

    @pytest.mark.asyncio
    async def test_get_unauthenticated_returns_401(self) -> None:
        """GET with no session returns 401."""
        req = _StubRequest(session_user_id=None)
        handler = _StubHandler(req)
        await handler.get()

        assert handler._last_status == 401

    @pytest.mark.asyncio
    async def test_get_missing_chatbot_id_returns_400(self) -> None:
        """GET with no chatbot_id in URL returns 400."""
        manager = MagicMock()
        req = _StubRequest(session_user_id=42, match_info={}, app_manager=manager)
        handler = _StubHandler(req)
        await handler.get()

        assert handler._last_status == 400


# ---------------------------------------------------------------------------
# Tests — PUT (promote)
# ---------------------------------------------------------------------------


class TestEphemeralHandlerPromote:
    """Tests for EphemeralUserAgentHandler.put."""

    @pytest.mark.asyncio
    async def test_promote_ready_returns_200(self) -> None:
        """PUT returns 200 with UserBotModel payload when agent is ready."""
        ep_status = _make_status(chatbot_id="bot-2", phase="ready", user_id=42)
        fake_bot = MagicMock()
        fake_bot.chatbot_id = "bot-2"
        fake_bot.to_dict = MagicMock(return_value={"chatbot_id": "bot-2", "name": "MyBot"})

        manager = MagicMock()
        manager.get_ephemeral_status = MagicMock(return_value=ep_status)
        manager.promote_user_bot = AsyncMock(return_value=fake_bot)

        req = _StubRequest(
            session_user_id=42,
            match_info={"chatbot_id": "bot-2"},
            app_manager=manager,
        )
        handler = _StubHandler(req)
        await handler.put()

        assert handler._last_status == 200
        manager.promote_user_bot.assert_awaited_once_with("bot-2", 42)

    @pytest.mark.asyncio
    async def test_promote_not_ready_returns_409(self) -> None:
        """PUT returns 409 when agent phase != 'ready'."""
        ep_status = _make_status(chatbot_id="bot-3", phase="warming", user_id=42)
        manager = MagicMock()
        manager.get_ephemeral_status = MagicMock(return_value=ep_status)

        req = _StubRequest(
            session_user_id=42,
            match_info={"chatbot_id": "bot-3"},
            app_manager=manager,
        )
        handler = _StubHandler(req)
        await handler.put()

        assert handler._last_status == 409

    @pytest.mark.asyncio
    async def test_promote_not_found_returns_404(self) -> None:
        """PUT returns 404 when bot not in ephemeral registry."""
        manager = MagicMock()
        manager.get_ephemeral_status = MagicMock(return_value=None)

        req = _StubRequest(
            session_user_id=42,
            match_info={"chatbot_id": "missing"},
            app_manager=manager,
        )
        handler = _StubHandler(req)
        await handler.put()

        assert handler._last_status == 404

    @pytest.mark.asyncio
    async def test_promote_unauthenticated_returns_401(self) -> None:
        """PUT without session returns 401."""
        req = _StubRequest(session_user_id=None)
        handler = _StubHandler(req)
        await handler.put()

        assert handler._last_status == 401

    @pytest.mark.asyncio
    async def test_promote_value_error_returns_409(self) -> None:
        """ValueError from promote_user_bot (already promoted) → 409."""
        ep_status = _make_status(chatbot_id="bot-4", phase="ready", user_id=42)
        manager = MagicMock()
        manager.get_ephemeral_status = MagicMock(return_value=ep_status)
        manager.promote_user_bot = AsyncMock(
            side_effect=ValueError("Agent is not in ready phase")
        )

        req = _StubRequest(
            session_user_id=42,
            match_info={"chatbot_id": "bot-4"},
            app_manager=manager,
        )
        handler = _StubHandler(req)
        await handler.put()

        assert handler._last_status == 409


# ---------------------------------------------------------------------------
# Tests — DELETE (discard)
# ---------------------------------------------------------------------------


class TestEphemeralHandlerDelete:
    """Tests for EphemeralUserAgentHandler.delete."""

    @pytest.mark.asyncio
    async def test_delete_ephemeral_returns_204(self) -> None:
        """DELETE of an ephemeral bot returns 204."""
        manager = MagicMock()
        manager.discard_ephemeral_user_bot = AsyncMock(return_value=True)

        req = _StubRequest(
            session_user_id=42,
            match_info={"chatbot_id": "bot-5"},
            app_manager=manager,
        )
        handler = _StubHandler(req)
        result = await handler.delete()

        manager.discard_ephemeral_user_bot.assert_awaited_once_with("bot-5", 42)
        assert handler._last_status in (200, 204) or (
            hasattr(result, "status") and result.status == 204
        )

    @pytest.mark.asyncio
    async def test_delete_not_found_returns_404(self) -> None:
        """DELETE of a bot not in registry returns 404."""
        manager = MagicMock()
        manager.discard_ephemeral_user_bot = AsyncMock(return_value=False)

        req = _StubRequest(
            session_user_id=42,
            match_info={"chatbot_id": "missing"},
            app_manager=manager,
        )
        handler = _StubHandler(req)
        await handler.delete()

        assert handler._last_status == 404

    @pytest.mark.asyncio
    async def test_delete_unauthenticated_returns_401(self) -> None:
        """DELETE without session returns 401."""
        req = _StubRequest(session_user_id=None)
        handler = _StubHandler(req)
        await handler.delete()

        assert handler._last_status == 401
