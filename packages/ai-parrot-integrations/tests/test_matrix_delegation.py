"""Tests for HybridDelegator and DelegationRequest (TASK-1300 — FEAT-195)."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.integrations.matrix.crew.delegation import (
    DelegationRequest,
    HybridDelegator,
)
from parrot.integrations.matrix.events import ParrotEventType, ResultEventContent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_delegator() -> tuple[HybridDelegator, AsyncMock, AsyncMock]:
    """Return (delegator, mock_appservice, mock_registry)."""
    appservice = AsyncMock()
    appservice.send_as_agent.return_value = "$visible_event"
    appservice.send_formatted_as_agent.return_value = "$formatted_event"
    appservice.send_reply_as_agent.return_value = "$reply_event"
    appservice._registered_agents = {"analyst": "@analyst:server"}

    registry = AsyncMock()
    target_card = MagicMock(
        agent_name="db_agent",
        display_name="DB Agent",
        mxid="@db_agent:server",
    )
    registry.get.return_value = target_card

    delegator = HybridDelegator(appservice=appservice, registry=registry)
    return delegator, appservice, registry


def _make_request(**overrides) -> DelegationRequest:
    kwargs = dict(
        requester_name="analyst",
        target_agent="db_agent",
        task_description="Query revenue data for Q4",
        room_id="!room:server",
    )
    kwargs.update(overrides)
    return DelegationRequest(**kwargs)


# ---------------------------------------------------------------------------
# Tests for DelegationRequest
# ---------------------------------------------------------------------------


class TestDelegationRequest:
    """Tests for the DelegationRequest Pydantic model."""

    def test_creation(self):
        """DelegationRequest created with required fields."""
        req = _make_request()
        assert req.requester_name == "analyst"
        assert req.target_agent == "db_agent"
        assert req.task_description == "Query revenue data for Q4"
        assert req.room_id == "!room:server"
        assert req.context is None

    def test_creation_with_context(self):
        """DelegationRequest accepts optional context."""
        req = _make_request(context="ctx-123")
        assert req.context == "ctx-123"

    def test_required_fields_enforced(self):
        """Missing required fields raise ValidationError."""
        with pytest.raises(Exception):
            DelegationRequest(requester_name="a", target_agent="b")  # type: ignore[call-arg]

    def test_serialization(self):
        """DelegationRequest serializes correctly via model_dump."""
        req = _make_request(context="ctx")
        data = req.model_dump()
        assert data["requester_name"] == "analyst"
        assert data["context"] == "ctx"


# ---------------------------------------------------------------------------
# Tests for HybridDelegator
# ---------------------------------------------------------------------------


class TestHybridDelegator:
    """Tests for HybridDelegator.delegate() and on_custom_event()."""

    @pytest.mark.asyncio
    async def test_delegate_posts_visible_message(self):
        """Visible 'Asking @peer...' message is posted as the requester.

        After FIX-11, when the target agent is known, the delegation message is
        sent via send_formatted_as_agent (plain text body + HTML formatted_body).
        Falls back to send_as_agent when the target card cannot be resolved.
        """
        delegator, appservice, _ = _make_delegator()

        # Immediately resolve the result so delegate() doesn't hang
        async def resolve_result():
            await asyncio.sleep(0.01)
            content = ResultEventContent(task_id="PLACEHOLDER", content="Result text")
            for task_id, future in list(delegator._pending.items()):
                content = ResultEventContent(task_id=task_id, content="Result text")
                if not future.done():
                    future.set_result(content)

        asyncio.ensure_future(resolve_result())

        await delegator.delegate(_make_request(), timeout=1.0)

        # Visible message must have been sent — either as formatted or plain text
        total_calls = (
            appservice.send_as_agent.call_count
            + appservice.send_formatted_as_agent.call_count
        )
        assert total_calls == 1, (
            f"Expected exactly one send call, got send_as_agent="
            f"{appservice.send_as_agent.call_count}, "
            f"send_formatted_as_agent={appservice.send_formatted_as_agent.call_count}"
        )
        # Check the message text regardless of which method was used
        if appservice.send_formatted_as_agent.call_count:
            call_args = appservice.send_formatted_as_agent.call_args
            body = call_args[0][2] if call_args[0] else str(call_args)
        else:
            call_args = appservice.send_as_agent.call_args
            body = call_args[0][2] if call_args[0] else str(call_args)
        assert "Asking" in body or "Asking" in str(call_args)

    @pytest.mark.asyncio
    async def test_delegate_sends_custom_event(self):
        """m.parrot.task custom event is sent via _send_custom_event."""
        delegator, appservice, _ = _make_delegator()

        # Patch _send_custom_event to avoid mautrix dependency
        delegator._send_custom_event = AsyncMock()

        # Resolve pending future quickly
        async def resolve():
            await asyncio.sleep(0.01)
            for task_id, future in list(delegator._pending.items()):
                result = ResultEventContent(task_id=task_id, content="Done")
                if not future.done():
                    future.set_result(result)

        asyncio.ensure_future(resolve())
        await delegator.delegate(_make_request(), timeout=1.0)

        delegator._send_custom_event.assert_called_once()
        call_args = delegator._send_custom_event.call_args
        assert call_args[1]["event_type"] == ParrotEventType.TASK or \
               ParrotEventType.TASK in call_args[0]

    @pytest.mark.asyncio
    async def test_delegate_timeout_returns_none(self):
        """Timeout waiting for result returns None and does not raise."""
        delegator, appservice, _ = _make_delegator()
        delegator._send_custom_event = AsyncMock()

        result = await delegator.delegate(_make_request(), timeout=0.01)

        assert result is None

    @pytest.mark.asyncio
    async def test_result_posted_as_reply(self):
        """Result is posted as reply-to the visible request message."""
        delegator, appservice, _ = _make_delegator()
        delegator._send_custom_event = AsyncMock()

        async def resolve():
            await asyncio.sleep(0.01)
            for task_id, future in list(delegator._pending.items()):
                result = ResultEventContent(task_id=task_id, content="Revenue: $1M")
                if not future.done():
                    future.set_result(result)

        asyncio.ensure_future(resolve())
        result_text = await delegator.delegate(_make_request(), timeout=1.0)

        assert result_text == "Revenue: $1M"
        appservice.send_reply_as_agent.assert_called_once()
        reply_call = appservice.send_reply_as_agent.call_args
        assert "Revenue: $1M" in reply_call[0]

    @pytest.mark.asyncio
    async def test_on_custom_event_resolves_future(self):
        """Incoming m.parrot.result resolves the pending future."""
        delegator, _, _ = _make_delegator()

        # Set up a pending future
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        task_id = "task-abc-123"
        delegator._pending[task_id] = future

        await delegator.on_custom_event(
            ParrotEventType.RESULT,
            {"task_id": task_id, "content": "Result text", "success": True},
        )

        assert future.done()
        result = future.result()
        assert result.task_id == task_id
        assert result.content == "Result text"

    @pytest.mark.asyncio
    async def test_on_custom_event_ignores_non_result_type(self):
        """Non-result event type does not resolve any futures."""
        delegator, _, _ = _make_delegator()

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        delegator._pending["task-xyz"] = future

        await delegator.on_custom_event(
            ParrotEventType.TASK,
            {"task_id": "task-xyz", "content": "Some task"},
        )

        assert not future.done()

    @pytest.mark.asyncio
    async def test_on_custom_event_ignores_unknown_task_id(self):
        """m.parrot.result for unknown task_id is silently ignored."""
        delegator, _, _ = _make_delegator()

        # Should not raise
        await delegator.on_custom_event(
            ParrotEventType.RESULT,
            {"task_id": "unknown-id", "content": "Result", "success": True},
        )

    @pytest.mark.asyncio
    async def test_unknown_target_agent_uses_fallback_pill(self):
        """When registry.get returns None, falls back to @agent_name format."""
        delegator, appservice, registry = _make_delegator()
        registry.get.return_value = None
        delegator._send_custom_event = AsyncMock()

        await delegator.delegate(_make_request(), timeout=0.01)

        # Should still post visible message (no crash)
        appservice.send_as_agent.assert_called_once()
        call_args = appservice.send_as_agent.call_args
        body = call_args[0][2]
        assert "db_agent" in body or "Asking" in body


# ---------------------------------------------------------------------------
# Tests for MatrixAppService custom event routing
# ---------------------------------------------------------------------------


class TestAppServiceCustomEventRouting:
    """Tests for MatrixAppService._handle_event() routing m.parrot.* events."""

    @pytest.mark.asyncio
    async def test_custom_event_callback_called_for_result(self):
        """_handle_event calls _custom_event_callback for m.parrot.result events."""
        from parrot.integrations.matrix.appservice import MatrixAppService
        from parrot.integrations.matrix.models import MatrixAppServiceConfig

        config = MatrixAppServiceConfig(
            as_token="tok",
            hs_token="hs",
            homeserver="http://localhost:8008",
            server_name="server",
            bot_localpart="bot",
        )

        # We skip full mautrix setup — just test the callback routing logic
        # by mocking HAS_MAUTRIX and the internal call
        with patch(
            "parrot.integrations.matrix.appservice.HAS_MAUTRIX", True
        ), patch(
            "parrot.integrations.matrix.appservice.MautrixAppService"
        ):
            svc = MatrixAppService.__new__(MatrixAppService)
            svc._config = config
            svc._appservice = None
            svc._registered_agents = {}
            svc._agent_rooms = {}
            svc._event_callback = None
            svc._custom_event_callback = None
            svc.logger = MagicMock()

            custom_callback = AsyncMock()
            svc.set_custom_event_callback(custom_callback)

            # Create a mock event for m.parrot.result
            mock_event = MagicMock()
            mock_event.type = MagicMock()
            mock_event.type.__str__ = lambda s: ParrotEventType.RESULT

            content_mock = MagicMock()
            content_mock.__iter__ = lambda s: iter(
                [("task_id", "t1"), ("content", "res")]
            )
            mock_event.content = content_mock

            await svc._handle_event(mock_event)

            custom_callback.assert_called_once()

    def test_set_custom_event_callback_stores_callable(self):
        """set_custom_event_callback stores the callback."""
        from parrot.integrations.matrix.appservice import MatrixAppService
        from parrot.integrations.matrix.models import MatrixAppServiceConfig

        config = MatrixAppServiceConfig(
            as_token="tok",
            hs_token="hs",
            homeserver="http://localhost:8008",
            server_name="server",
            bot_localpart="bot",
        )

        with patch("parrot.integrations.matrix.appservice.HAS_MAUTRIX", True), \
             patch("parrot.integrations.matrix.appservice.MautrixAppService"):
            svc = MatrixAppService.__new__(MatrixAppService)
            svc._config = config
            svc._appservice = None
            svc._registered_agents = {}
            svc._agent_rooms = {}
            svc._event_callback = None
            svc._custom_event_callback = None
            svc.logger = MagicMock()

            cb = AsyncMock()
            svc.set_custom_event_callback(cb)
            assert svc._custom_event_callback is cb
