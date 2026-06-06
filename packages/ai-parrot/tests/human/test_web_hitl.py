"""Tests for parrot/handlers/web_hitl.py.

Covers:
- TASK-1004: current_web_session ContextVar and helpers
- TASK-1005: WebHumanTool lazy resolution
- TASK-1006: HITLResponseHandler and HITLResponseBody
- TASK-1007: setup_web_hitl bootstrap
"""
from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
from pydantic import ValidationError

from parrot.handlers.web_hitl import (
    current_web_session,
    get_current_web_session,
    set_current_web_session,
    reset_current_web_session,
    WebHumanTool,
    HITLResponseHandler,
    HITLResponseBody,
    setup_web_hitl,
)
from parrot.human import get_default_human_manager, set_default_human_manager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_default_manager():
    """Reset the global default manager between tests."""
    original = get_default_human_manager()
    yield
    set_default_human_manager(original)


@pytest.fixture
def mock_manager():
    """Mock HumanInteractionManager."""
    manager = AsyncMock()
    manager.request_human_input = AsyncMock(return_value=MagicMock(
        status="completed",
        consolidated_value="user_response",
        timed_out=False,
        escalated=False,
    ))
    manager.receive_response = AsyncMock()
    manager.get_result = AsyncMock(return_value={"value": "response_value"})
    manager.is_valid_respondent = AsyncMock(return_value=True)
    # has_pending is a sync method on the real manager (returns bool); default
    # to True so the 404 guard treats the interaction as existing.
    manager.has_pending = MagicMock(return_value=True)
    manager.channels = {}
    manager._pending_futures = {}
    return manager


# ---------------------------------------------------------------------------
# TASK-1004 Tests: ContextVar
# ---------------------------------------------------------------------------


class TestContextVar:
    def test_context_var_default(self):
        """get_current_web_session returns None by default."""
        value = get_current_web_session()
        assert value is None

    def test_context_var_set_and_get(self):
        """set_current_web_session updates the ContextVar."""
        token = set_current_web_session("sess-123")
        try:
            assert get_current_web_session() == "sess-123"
        finally:
            reset_current_web_session(token)

    def test_context_var_reset(self):
        """reset_current_web_session restores the previous value."""
        # Set initial value
        token1 = set_current_web_session("sess-1")
        assert get_current_web_session() == "sess-1"

        # Set a new value and get a token
        token2 = set_current_web_session("sess-2")
        assert get_current_web_session() == "sess-2"

        # Reset to the previous value
        reset_current_web_session(token2)
        assert get_current_web_session() == "sess-1"

        # Reset to the original
        reset_current_web_session(token1)
        assert get_current_web_session() is None

    @pytest.mark.asyncio
    async def test_context_var_isolation(self):
        """ContextVar values are isolated between concurrent tasks."""
        async def set_and_read(value):
            token = set_current_web_session(value)
            # Simulate some async work
            await asyncio.sleep(0.01)
            result = get_current_web_session()
            reset_current_web_session(token)
            return result

        results = await asyncio.gather(
            set_and_read("sess-a"),
            set_and_read("sess-b"),
            set_and_read("sess-c"),
        )
        assert results == ["sess-a", "sess-b", "sess-c"]


# ---------------------------------------------------------------------------
# TASK-1005 Tests: WebHumanTool
# ---------------------------------------------------------------------------


class TestWebHumanTool:
    @pytest.mark.asyncio
    async def test_web_human_tool_resolves_manager_lazily(self, mock_manager):
        """WebHumanTool resolves manager from get_default_human_manager() when not provided."""
        mock_manager.channels = {"web": MagicMock()}
        set_default_human_manager(mock_manager)
        token = set_current_web_session("sess-123")
        try:
            tool = WebHumanTool(source_agent="test_agent")
            result = await tool._execute(
                interaction_type="approval",
                question="Test?",
            )
            assert mock_manager.request_human_input.called
        finally:
            reset_current_web_session(token)

    @pytest.mark.asyncio
    async def test_web_human_tool_target_from_contextvar(self, mock_manager):
        """WebHumanTool reads target_humans from ContextVar when not provided."""
        mock_manager.channels = {"web": MagicMock()}
        set_default_human_manager(mock_manager)
        token = set_current_web_session("sess-456")
        try:
            tool = WebHumanTool(source_agent="test_agent")
            await tool._execute(
                interaction_type="free_text",
                question="Name?",
            )
            assert mock_manager.request_human_input.called
        finally:
            reset_current_web_session(token)

    @pytest.mark.asyncio
    async def test_web_human_tool_explicit_targets_win(self, mock_manager):
        """WebHumanTool ignores ContextVar when LLM provides target_humans."""
        mock_manager.channels = {"web": MagicMock()}
        set_default_human_manager(mock_manager)
        token = set_current_web_session("sess-from-context")
        try:
            tool = WebHumanTool(source_agent="test_agent")
            result = await tool._execute(
                interaction_type="approval",
                question="Approve?",
                target_humans=["explicit-target"],
            )
            assert mock_manager.request_human_input.called
        finally:
            reset_current_web_session(token)

    @pytest.mark.asyncio
    async def test_web_human_tool_error_when_no_target(self, mock_manager):
        """WebHumanTool raises when no target_humans and ContextVar is empty."""
        mock_manager.channels = {"web": MagicMock()}
        set_default_human_manager(mock_manager)
        tool = WebHumanTool(source_agent="test_agent")
        # ContextVar is not set, no default_targets, no kwargs target_humans
        with pytest.raises((ValueError, RuntimeError)):
            await tool._execute(
                interaction_type="approval",
                question="Approve?",
            )

    @pytest.mark.asyncio
    async def test_web_human_tool_default_channel_is_web(self):
        """WebHumanTool uses 'web' as default channel."""
        tool = WebHumanTool(source_agent="test_agent")
        assert tool.default_channel == "web"


# ---------------------------------------------------------------------------
# TASK-1006 Tests: HITLResponseHandler and HITLResponseBody
# ---------------------------------------------------------------------------


class TestHITLResponseBody:
    def test_response_body_required_fields(self):
        """HITLResponseBody validates required fields."""
        with pytest.raises(ValidationError):
            HITLResponseBody(value="test")  # missing interaction_id

    def test_response_body_optional_response_type(self):
        """HITLResponseBody response_type is optional."""
        body = HITLResponseBody(interaction_id="uuid-123", value="test")
        assert body.response_type is None

    def test_response_body_with_response_type(self):
        """HITLResponseBody accepts response_type."""
        body = HITLResponseBody(
            interaction_id="uuid-123",
            value="test",
            response_type="single_choice",
        )
        assert body.response_type == "single_choice"

    def test_response_body_requires_interaction_id(self):
        """HITLResponseBody raises ValidationError when interaction_id is missing."""
        with pytest.raises(ValidationError):
            HITLResponseBody(value="something")


class TestHITLResponseHandler:
    def _make_request(self, body_dict: dict, user_id: str = "user-123") -> MagicMock:
        """Build a minimal mock aiohttp request."""
        request = MagicMock()
        request.json = AsyncMock(return_value=body_dict)
        request.session = {"user_id": user_id}
        return request

    @pytest.mark.asyncio
    async def test_hitl_endpoint_400_on_missing_field(self, mock_manager):
        """POST with missing required field returns 400."""
        request = self._make_request({"value": "test"})  # missing interaction_id
        set_default_human_manager(mock_manager)
        handler = HITLResponseHandler(request)
        response = await handler.post()
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_hitl_endpoint_404_on_unknown_id(self, mock_manager):
        """POST with unknown interaction_id returns 404."""
        mock_manager._pending_futures = {}
        mock_manager.has_pending = MagicMock(return_value=False)
        mock_manager.get_result = AsyncMock(return_value=None)
        set_default_human_manager(mock_manager)
        request = self._make_request({"interaction_id": "unknown-uuid", "value": "test"})
        handler = HITLResponseHandler(request)
        response = await handler.post()
        assert response.status == 404

    @pytest.mark.asyncio
    async def test_hitl_endpoint_200_calls_receive_response(self, mock_manager):
        """POST with valid input returns 200 and calls receive_response."""
        interaction_id = "uuid-123"
        mock_manager._pending_futures = {interaction_id: MagicMock()}
        mock_manager.receive_response = AsyncMock()
        set_default_human_manager(mock_manager)
        request = self._make_request({
            "interaction_id": interaction_id,
            "value": "user_answer",
        })
        handler = HITLResponseHandler(request)
        response = await handler.post()
        assert response.status == 200
        assert mock_manager.receive_response.called
        # Parse response body — decode bytes or StringPayload safely
        raw_body = response.body
        if isinstance(raw_body, bytes):
            raw_body = raw_body.decode()
        elif hasattr(raw_body, 'decode'):
            raw_body = raw_body.decode()
        else:
            raw_body = str(raw_body)
        body = json.loads(raw_body)
        assert body["ok"] is True
        assert body["interaction_id"] == interaction_id

    @pytest.mark.asyncio
    async def test_hitl_endpoint_503_when_no_manager(self):
        """POST returns 503 when no manager is configured."""
        set_default_human_manager(None)
        request = self._make_request({"interaction_id": "uuid-123", "value": "test"})
        handler = HITLResponseHandler(request)
        response = await handler.post()
        assert response.status == 503


# ---------------------------------------------------------------------------
# TASK-1007 Tests: setup_web_hitl bootstrap
# ---------------------------------------------------------------------------


@pytest.fixture
def aiohttp_app():
    """Mock aiohttp Application."""
    app_obj = MagicMock(spec=web.Application)
    app_obj.on_startup = []
    socket_manager = MagicMock()
    app_obj.__getitem__ = MagicMock(side_effect=lambda k: socket_manager if k == "user_socket_manager" else None)
    app_obj.get = MagicMock(side_effect=lambda k, *a: socket_manager if k == "user_socket_manager" else (a[0] if a else None))
    return app_obj


class TestSetupWebHitl:
    @pytest.mark.asyncio
    async def test_setup_web_hitl_idempotent(self, aiohttp_app):
        """Calling setup_web_hitl twice does not create two managers."""
        await setup_web_hitl(aiohttp_app)
        manager1 = get_default_human_manager()

        await setup_web_hitl(aiohttp_app)
        manager2 = get_default_human_manager()

        assert manager1 is manager2
        # Second call is a no-op: the 'web' channel is registered exactly once.
        assert "web" in manager2.channels

    @pytest.mark.asyncio
    async def test_setup_web_hitl_skips_when_no_socket_manager(self, aiohttp_app):
        """setup_web_hitl logs warning and continues if socket manager missing."""
        aiohttp_app.get = MagicMock(return_value=None)
        # Should not raise
        await setup_web_hitl(aiohttp_app)
        # Manager should still be created
        manager = get_default_human_manager()
        assert manager is not None

    @pytest.mark.asyncio
    async def test_setup_web_hitl_registers_channel(self, aiohttp_app):
        """setup_web_hitl registers WebHumanChannel under 'web'."""
        await setup_web_hitl(aiohttp_app)
        manager = get_default_human_manager()
        # Check that a channel named 'web' is registered
        assert "web" in manager.channels

    @pytest.mark.asyncio
    async def test_setup_web_hitl_awaits_startup_directly(self, aiohttp_app):
        """setup_web_hitl awaits manager.startup() itself, appending no hook.

        The bootstrap awaits ``manager.startup()`` directly so it is safe to
        call from within an existing ``on_startup`` callback (where
        ``app.on_startup`` is frozen). It must therefore NOT append a new hook.
        """
        await setup_web_hitl(aiohttp_app)
        assert len(aiohttp_app.on_startup) == 0
        assert get_default_human_manager() is not None
