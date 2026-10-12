"""Tests for the Slack knowledge-upload adapter (FEAT-647, TASK-4189)."""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.knowledge_upload.models import (
    KnowledgeUploadConfig,
    UploadOutcome,
    UploadStatus,
    UploadTargetKind,
)
from parrot.integrations.slack.knowledge_upload import SlackKnowledgeUpload, USAGE
from parrot.integrations.slack.socket_handler import SlackSocketHandler
from parrot.integrations.slack.wrapper import SlackAgentWrapper


def _make_wrapper() -> SlackAgentWrapper:
    """Build a minimal Slack wrapper without running route setup."""
    from parrot.integrations.slack.models import SlackAgentConfig

    config = SlackAgentConfig.__new__(SlackAgentConfig)
    config.name = "test-bot"
    config.chatbot_id = "test_bot"
    config.bot_token = "xoxb-test-token"
    config.signing_secret = "test-secret"
    config.app_token = None
    config.connection_mode = "webhook"
    config.enable_assistant = False
    config.allowed_channel_ids = None
    config.allowed_user_ids = None
    config.knowledge_upload = KnowledgeUploadConfig(enabled=True, slack_pending_window_s=1)
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
    wrapper.config = config
    wrapper.logger = logging.getLogger("test-slack-upload")
    wrapper._background_tasks = set()
    wrapper._message_interceptors = []
    wrapper._command_router = MagicMock()
    wrapper._safe_answer = AsyncMock()
    wrapper._dedup = MagicMock(is_duplicate=MagicMock(return_value=False))
    wrapper._assistant_handler = None
    wrapper._knowledge_upload = None
    wrapper.post_message = AsyncMock()
    wrapper._slack_api = AsyncMock(return_value={"user": {"profile": {"email": "user@example.com"}}})
    return wrapper


def _make_service(targets=None):
    """Build a service-shaped mock with deterministic upload results."""
    targets = targets or {UploadTargetKind.BOOKSTORE, UploadTargetKind.WIKI}
    service = MagicMock()
    service.available_targets.return_value = targets
    service.max_bytes.return_value = 4
    service.submit = AsyncMock(
        return_value=UploadOutcome(
            job_id="job-1",
            status=UploadStatus.ACCEPTED,
            target=UploadTargetKind.BOOKSTORE,
            filename="book.pdf",
            message="Received book.pdf.",
        )
    )
    service.shutdown = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_intercept_text_prefix():
    """A command-prefixed file is consumed and submitted to the right target."""
    wrapper = _make_wrapper()
    service = _make_service()
    adapter = SlackKnowledgeUpload(wrapper, service)
    adapter._download = AsyncMock(return_value=b"data")

    assert await adapter.intercept(
        {"channel": "C1", "user": "U1", "text": "ingest_book --force", "files": [{"name": "book.pdf"}]}
    )
    await asyncio.gather(*wrapper._background_tasks)

    request = service.submit.await_args.args[0]
    assert request.target is UploadTargetKind.BOOKSTORE
    assert request.force is True


@pytest.mark.asyncio
async def test_intercept_ignores_plain_chat():
    """Plain chat is left for the normal Slack processing path."""
    wrapper = _make_wrapper()
    service = _make_service()
    adapter = SlackKnowledgeUpload(wrapper, service)

    assert not await adapter.intercept({"channel": "C1", "user": "U1", "text": "hello"})
    service.submit.assert_not_called()


@pytest.mark.asyncio
async def test_pending_window_and_expiry():
    """A slash command arms a one-shot window that expires lazily."""
    wrapper = _make_wrapper()
    service = _make_service()
    adapter = SlackKnowledgeUpload(wrapper, service)
    adapter._download = AsyncMock(return_value=b"data")

    response = await adapter.on_command(UploadTargetKind.WIKI, {"channel_id": "C1", "user_id": "U1", "text": ""})
    assert response["response_type"] == "ephemeral"
    assert await adapter.intercept({"channel": "C1", "user": "U1", "text": "", "files": [{"name": "x.md"}]})
    await asyncio.gather(*wrapper._background_tasks)
    assert service.submit.await_args.args[0].target is UploadTargetKind.WIKI

    await adapter.on_command(UploadTargetKind.WIKI, {"channel_id": "C1", "user_id": "U1", "text": ""})
    adapter._pending[("C1", "U1")] = (0, UploadTargetKind.WIKI, {})
    assert not await adapter.intercept({"channel": "C1", "user": "U1", "files": [{"name": "x.md"}]})


@pytest.mark.asyncio
async def test_command_without_file_answers_usage():
    """A command text without an attached file receives usage guidance."""
    wrapper = _make_wrapper()
    adapter = SlackKnowledgeUpload(wrapper, _make_service())

    assert await adapter.intercept({"channel": "C1", "user": "U1", "text": "ingest_wiki"})
    wrapper.post_message.assert_awaited_once()
    assert wrapper.post_message.await_args.args[1] == USAGE


@pytest.mark.asyncio
async def test_oversize_rejected_without_download():
    """The Slack-provided size rejects an upload before opening a connection."""
    wrapper = _make_wrapper()
    adapter = SlackKnowledgeUpload(wrapper, _make_service())
    adapter._download = AsyncMock()

    await adapter._process("C1", "U1", None, UploadTargetKind.BOOKSTORE, {}, {"name": "x.pdf", "size": 5})
    adapter._download.assert_not_called()
    assert "too large" in wrapper.post_message.await_args.args[1]


@pytest.mark.asyncio
async def test_download_streamed_cap():
    """The streamed response is rejected when its accumulated bytes exceed the cap."""
    wrapper = _make_wrapper()
    adapter = SlackKnowledgeUpload(wrapper, _make_service())
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.content.iter_chunked = MagicMock(return_value=_chunks([b"123", b"45"]))
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.get.return_value = response
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    with patch("parrot.integrations.slack.knowledge_upload.ClientSession", return_value=session):
        with pytest.raises(ValueError, match="too large"):
            await adapter._download({"url_private_download": "https://slack.test/file"}, 4)


async def _chunks(chunks):
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_email_from_users_info():
    """The identity uses the email returned by users.info."""
    wrapper = _make_wrapper()
    adapter = SlackKnowledgeUpload(wrapper, _make_service())

    assert await adapter._email("U1") == "user@example.com"
    wrapper._slack_api.assert_awaited_once_with("users.info", {"user": "U1"})


def test_only_available_targets_registered():
    """Unavailable targets do not get slash-command registrations."""
    wrapper = _make_wrapper()
    adapter = SlackKnowledgeUpload(wrapper, _make_service({UploadTargetKind.BOOKSTORE}))

    adapter.register()

    assert wrapper._command_router.register.call_args.args[0] == "ingest_book"
    assert wrapper._command_router.register.call_count == 1


@pytest.mark.asyncio
async def test_parse_args_rejects_unknown_options():
    """Unsupported flags fail closed instead of silently changing intent."""
    with pytest.raises(ValueError):
        SlackKnowledgeUpload._parse_args("--unknown value")


@pytest.mark.asyncio
async def test_assistant_dm_runs_interceptors():
    """Webhook assistant DMs with files consult registered interceptors first."""
    wrapper = _make_wrapper()
    wrapper.config.enable_assistant = True
    wrapper._assistant_handler = MagicMock()
    wrapper._assistant_handler.handle_user_message = AsyncMock()
    wrapper.add_message_interceptor(lambda event: _consume(event))
    request = MagicMock()
    request.headers = {}
    request.read = AsyncMock(
        return_value=json.dumps(
            {
                "event_id": "E1",
                "event": {"type": "message", "channel_type": "im", "channel": "C1", "user": "U1", "files": [{}]},
            }
        ).encode()
    )
    with patch("parrot.integrations.slack.wrapper.verify_slack_signature_raw", return_value=True):
        response = await wrapper._handle_events(request)

    assert response.status == 200
    wrapper._assistant_handler.handle_user_message.assert_not_called()


async def _consume(event):
    return True


@pytest.mark.asyncio
async def test_socket_file_without_text_reaches_interceptor():
    """Socket Mode file messages are intercepted before empty text is discarded."""
    wrapper = _make_wrapper()
    wrapper.add_message_interceptor(lambda event: _consume(event))
    handler = SlackSocketHandler.__new__(SlackSocketHandler)
    handler.wrapper = wrapper
    handler._bot_user_id = None

    await handler._handle_event(
        {"event_id": "E2", "event": {"type": "message", "channel": "C1", "user": "U1", "text": "", "files": [{}]}}
    )
    wrapper._safe_answer.assert_not_called()
