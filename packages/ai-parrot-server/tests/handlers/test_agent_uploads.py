"""Regression coverage for AgentTalk upload persistence and responses."""
from __future__ import annotations

import logging
from inspect import unwrap
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.handlers.agent import AgentTalk


def _make_handler() -> AgentTalk:
    """Build an AgentTalk instance without navigator's application setup."""
    handler = AgentTalk.__new__(AgentTalk)
    handler.logger = MagicMock(spec=logging.Logger)
    handler.json_response = lambda content, status=200: SimpleNamespace(content=content, status=status)
    return handler


class _FakeAgent:
    """Minimal agent that binds a supplied bot for one request."""

    def __init__(self, bot: Any) -> None:
        self.name = "upload-agent"
        self.tool_manager = MagicMock()
        self.enable_tools = False
        self._bot = bot

    @asynccontextmanager
    async def session(self, **_: Any):
        """Yield the request-scoped bot."""
        yield self._bot


def _make_post_handler(*, attachments: dict[str, Any], data: dict[str, Any], agent: _FakeAgent) -> AgentTalk:
    """Build the narrow POST surface needed to exercise the upload branch."""
    handler = _make_handler()
    handler._request = SimpleNamespace(app={}, match_info={"agent_id": "upload-agent"})
    handler.query_parameters = lambda _: {}
    handler.handle_upload = AsyncMock(return_value=(attachments, data))
    handler._check_pbac_agent_access = AsyncMock(return_value=None)
    handler._get_user_session = AsyncMock(return_value=("user-1", "session-1"))
    handler._resolve_bot = AsyncMock(return_value=(agent, True))
    handler._get_output_format = lambda *_: "json"
    handler._speak_text_to_avatar = AsyncMock()
    handler._format_response = MagicMock(return_value=SimpleNamespace(status=200))
    return handler


class TestUploadPersistence:
    """Uploads persist before AgentTalk branches on a chat query."""

    @pytest.mark.asyncio
    async def test_upload_with_query_persists_file(self) -> None:
        """Spec AC2: a file-plus-prompt request persists the file."""
        bot = SimpleNamespace(
            handle_files=AsyncMock(return_value={"files": [{"file_id": "file-1"}], "dataframes": [], "errors": []}),
            ask=AsyncMock(return_value=SimpleNamespace(response="done")),
        )
        handler = _make_post_handler(
            attachments={"report.docx": b"document"}, data={"query": "attach this"}, agent=_FakeAgent(bot)
        )

        response = await unwrap(AgentTalk.post)(handler)

        assert response.status == 200
        bot.handle_files.assert_awaited_once_with({"report.docx": b"document"})
        bot.ask.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upload_only_reports_stored_files(self) -> None:
        """Upload responses expose files, dataframes, errors, and agent."""
        handler = _make_handler()

        response = await handler._handle_attachments(
            SimpleNamespace(name="upload-agent"),
            {"files": [{"file_id": "file-1"}], "dataframes": ["sheet"], "errors": []},
        )

        assert response.status == 200
        assert response.content == {
            "files": [{"file_id": "file-1"}],
            "dataframes": ["sheet"],
            "errors": [],
            "agent": "upload-agent",
        }
        assert "added_files" not in response.content

    @pytest.mark.asyncio
    async def test_nothing_stored_is_not_success(self) -> None:
        """Spec AC3: an upload that stores nothing returns a client error."""
        handler = _make_handler()

        response = await handler._handle_attachments(
            SimpleNamespace(name="upload-agent"),
            {"files": [], "dataframes": [], "errors": [{"filename": "bad.docx", "error": "invalid"}]},
        )

        assert response.status == 400
        assert response.content["errors"] == [{"filename": "bad.docx", "error": "invalid"}]

    @pytest.mark.asyncio
    async def test_persistence_failure_does_not_break_chat(self) -> None:
        """A handle_files failure is logged while the prompt still runs."""
        bot = SimpleNamespace(
            handle_files=AsyncMock(side_effect=RuntimeError("storage unavailable")),
            ask=AsyncMock(return_value=SimpleNamespace(response="answer")),
        )
        handler = _make_post_handler(
            attachments={"report.docx": b"document"}, data={"query": "summarize"}, agent=_FakeAgent(bot)
        )

        response = await unwrap(AgentTalk.post)(handler)

        assert response.status == 200
        bot.ask.assert_awaited_once()
        handler.logger.error.assert_called_once()
