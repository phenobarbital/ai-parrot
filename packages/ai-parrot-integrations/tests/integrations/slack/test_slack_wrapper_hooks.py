"""Unit tests for FEAT-555 M9 — wrapper hooks and ingress hardening (TASK-3205)."""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.slack.socket_handler import SlackSocketHandler  # verified: slack/socket_handler.py:20
from parrot.integrations.slack.wrapper import SlackAgentWrapper  # verified: slack/__init__.py:20


def _make_wrapper(allowed_user_ids=None, allowed_channel_ids=None) -> SlackAgentWrapper:
    """Minimal wrapper without running __init__ (pattern: test_slack_wrapper_jira.py:14-60)."""
    from parrot.integrations.slack.models import SlackAgentConfig

    config = SlackAgentConfig.__new__(SlackAgentConfig)
    config.name = "test-bot"
    config.chatbot_id = "test_bot"
    config.bot_token = "xoxb-test-token"
    config.signing_secret = "test-secret"
    config.app_token = None
    config.connection_mode = "webhook"
    config.enable_assistant = False
    config.allowed_channel_ids = allowed_channel_ids
    config.allowed_user_ids = allowed_user_ids
    config.webhook_path = None
    config.suggested_prompts = None
    config.max_concurrent_requests = 5
    config.jira_client_id = None
    config.jira_client_secret = None
    config.jira_redirect_uri = None
    config.welcome_message = None
    config.commands = {}
    config.kind = "slack"

    wrapper = SlackAgentWrapper.__new__(SlackAgentWrapper)
    wrapper.agent = MagicMock()
    wrapper.config = config
    wrapper.app = MagicMock()
    wrapper.logger = logging.getLogger("test")
    wrapper.conversations = {}
    wrapper._concurrency_semaphore = asyncio.Semaphore(5)
    wrapper._background_tasks = set()
    wrapper._assistant_handler = None
    wrapper._interactive_handler = MagicMock()
    wrapper._interactive_handler.handle = AsyncMock(return_value=None)
    wrapper._dedup = MagicMock()
    wrapper._dedup.is_duplicate = MagicMock(return_value=False)
    wrapper._message_interceptors = []
    wrapper._command_router = MagicMock()
    wrapper._command_router.dispatch = AsyncMock(return_value=None)
    wrapper.events_route = "/api/slack/test_bot/events"
    wrapper.commands_route = "/api/slack/test_bot/commands"
    wrapper.interactive_route = "/api/slack/test_bot/interactive"
    wrapper._safe_answer = AsyncMock()
    return wrapper


def _make_socket_handler(wrapper: SlackAgentWrapper) -> SlackSocketHandler:
    handler = SlackSocketHandler.__new__(SlackSocketHandler)
    handler.wrapper = wrapper
    handler._bot_user_id = None
    handler._running = False
    handler._connection_task = None
    return handler


def _request(body: dict, headers: dict | None = None) -> MagicMock:
    request = MagicMock()
    request.headers = headers or {}
    request.read = AsyncMock(return_value=json.dumps(body).encode("utf-8"))
    return request


@pytest.mark.asyncio
async def test_interceptor_consumes_event_webhook_path():
    """An interceptor returning True prevents _safe_answer in _handle_events."""
    wrapper = _make_wrapper()

    async def _consume(event):
        return True

    wrapper.add_message_interceptor(_consume)

    body = {
        "event_id": "Ev1",
        "type": "event_callback",
        "event": {"type": "message", "channel": "C1", "user": "U1", "text": "1: an answer", "ts": "1.1"},
    }
    request = _request(body)

    with patch("parrot.integrations.slack.wrapper.verify_slack_signature_raw", return_value=True):
        resp = await wrapper._handle_events(request)

    assert resp.status == 200
    wrapper._safe_answer.assert_not_called()


@pytest.mark.asyncio
async def test_interceptor_consumes_event_socket_path():
    """The same interceptor consumes the event in SlackSocketHandler._handle_event."""
    wrapper = _make_wrapper()

    async def _consume(event):
        return True

    wrapper.add_message_interceptor(_consume)
    handler = _make_socket_handler(wrapper)

    payload = {
        "event_id": "Ev2",
        "event": {"type": "message", "channel": "C1", "user": "U1", "text": "1: an answer", "ts": "1.1"},
    }
    await handler._handle_event(payload)

    wrapper._safe_answer.assert_not_called()


@pytest.mark.asyncio
async def test_post_message_returns_ts():
    """post_message returns the ts from chat.postMessage."""
    wrapper = _make_wrapper()
    wrapper._slack_api = AsyncMock(return_value={"ok": True, "ts": "1.2"})

    result = await wrapper.post_message("C1", "hello")

    assert result == "1.2"
    wrapper._slack_api.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_message_false_on_failure():
    wrapper = _make_wrapper()
    wrapper._slack_api = AsyncMock(return_value=None)

    assert await wrapper.update_message("C1", "1.2", "new text") is False


@pytest.mark.asyncio
async def test_open_dm_returns_channel_id():
    wrapper = _make_wrapper()
    wrapper._slack_api = AsyncMock(return_value={"ok": True, "channel": {"id": "D1"}})

    assert await wrapper.open_dm("U1") == "D1"


@pytest.mark.asyncio
async def test_post_message_becomes_thin_wrapper_around_it():
    """_post_message keeps existing callers working (return value discarded)."""
    wrapper = _make_wrapper()
    wrapper.post_message = AsyncMock(return_value="1.3")

    result = await wrapper._post_message("C1", "hi")

    assert result is None
    wrapper.post_message.assert_awaited_once_with("C1", "hi", blocks=None, thread_ts=None)


@pytest.mark.asyncio
async def test_interactive_route_rejects_bad_signature():
    """_handle_interactive returns 401 when the signature does not verify."""
    wrapper = _make_wrapper()
    request = MagicMock()
    request.headers = {}
    request.read = AsyncMock(return_value=b"payload=%7B%7D")

    with patch("parrot.integrations.slack.wrapper.verify_slack_signature_raw", return_value=False):
        resp = await wrapper._handle_interactive(request)

    assert resp.status == 401
    wrapper._interactive_handler.handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_interactive_route_authorized_delegates_to_handler():
    wrapper = _make_wrapper()
    import urllib.parse

    inner = {"type": "block_actions", "channel": {"id": "C1"}, "user": {"id": "U1"}}
    body = urllib.parse.urlencode({"payload": json.dumps(inner)}).encode("utf-8")
    request = MagicMock()
    request.headers = {}
    request.read = AsyncMock(return_value=body)

    with patch("parrot.integrations.slack.wrapper.verify_slack_signature_raw", return_value=True):
        resp = await wrapper._handle_interactive(request)

    assert resp.status == 200
    wrapper._interactive_handler.handle.assert_awaited_once_with(inner)


@pytest.mark.asyncio
async def test_socket_mode_enforces_user_whitelist():
    """Socket Mode drops events, slash commands and interactive payloads from a non-whitelisted user."""
    wrapper = _make_wrapper(allowed_user_ids=["U_OK"])
    handler = _make_socket_handler(wrapper)
    handler._send_response = AsyncMock()

    # events_api
    await handler._handle_event(
        {"event_id": "E1", "event": {"type": "message", "channel": "C1", "user": "U_BAD", "text": "hi", "ts": "1.1"}}
    )
    wrapper._safe_answer.assert_not_called()

    # slash command
    await handler._handle_slash_command(
        {"channel_id": "C1", "user_id": "U_BAD", "team_id": "T1", "text": "hi", "response_url": "http://x"}
    )
    wrapper._command_router.dispatch.assert_not_called()
    wrapper._safe_answer.assert_not_called()

    # interactive
    await handler._handle_interactive({"type": "block_actions", "channel": {"id": "C1"}, "user": {"id": "U_BAD"}})
    wrapper._interactive_handler.handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_view_submission_enforces_user_whitelist_webhook_and_socket():
    """A view_submission payload carries no channel — both paths must still check allowed_user_ids (code review fix).

    Before this fix, ``if channel and not self._is_authorized(channel, user)``
    short-circuited to ``False`` whenever ``channel`` was falsy (every
    ``view_submission``), so NO authorization check ran at all for modal
    submissions in either the webhook or Socket Mode path.
    """
    wrapper = _make_wrapper(allowed_user_ids=["U_OK"])
    import urllib.parse

    inner = {"type": "view_submission", "user": {"id": "U_BAD"}, "view": {"private_metadata": "{}"}}
    body = urllib.parse.urlencode({"payload": json.dumps(inner)}).encode("utf-8")
    request = MagicMock()
    request.headers = {}
    request.read = AsyncMock(return_value=body)

    with patch("parrot.integrations.slack.wrapper.verify_slack_signature_raw", return_value=True):
        resp = await wrapper._handle_interactive(request)
    assert resp.status == 200
    wrapper._interactive_handler.handle.assert_not_awaited()

    handler = _make_socket_handler(wrapper)
    await handler._handle_interactive(inner)
    wrapper._interactive_handler.handle.assert_not_awaited()

    # A whitelisted user's view_submission still reaches the handler.
    inner_ok = {"type": "view_submission", "user": {"id": "U_OK"}, "view": {"private_metadata": "{}"}}
    await handler._handle_interactive(inner_ok)
    wrapper._interactive_handler.handle.assert_awaited_once_with(inner_ok)
