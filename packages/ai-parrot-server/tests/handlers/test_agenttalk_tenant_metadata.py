"""FEAT-710 TASK-4552 — AgentTalk tenant + per-turn metadata."""

from __future__ import annotations

import asyncio
from pathlib import Path
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_AGENT_SRC = Path(__file__).resolve().parents[2] / "src" / "parrot" / "handlers" / "agent.py"


def test_client_tenant_ignored_and_resolved_tenant_passed() -> None:
    """AgentTalk drops client tenant values and forwards the resolved value."""
    source = _AGENT_SRC.read_text(encoding="utf-8")

    assert "from .scope import resolve_request_tenant" in source
    assert 'if data.pop("tenant", None) is not None:' in source
    assert "Ignoring client-supplied 'tenant' for agent %s (FEAT-707)" in source
    assert "tenant = await resolve_request_tenant(app, self.request)" in source
    assert source.count("tenant=tenant,") == 4  # ask, ask_stream, stream handler, _format_response


def test_handler_builds_no_turn_metadata_and_never_saves() -> None:
    """The persisted-turn metadata moved into the bot's TurnPresentation (FEAT-886)."""
    source = _AGENT_SRC.read_text(encoding="utf-8")
    assert "save_turn" not in source
    assert "turn_id=client_message_id," in source


@pytest.mark.asyncio
async def test_stream_handler_forwards_tenant_and_turn_id_and_persists_nothing(monkeypatch) -> None:
    """FEAT-886: the handler hands tenant + client turn id to the bot; the bot owns persistence."""
    agent_module = pytest.importorskip("parrot.handlers.agent")
    from parrot.models.basic import CompletionUsage
    from parrot.models.responses import AIMessage

    class _StreamResponse:
        """Minimal chunked response used by the stream handler."""

        def __init__(self, **kwargs) -> None:
            self.status = kwargs["status"]

        async def prepare(self, request) -> None:
            return None

        async def write(self, data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        async def write_eof(self) -> None:
            return None

    class _ChatStorage:
        """Any attribute access means the handler touched storage: the test then fails."""

        def __getattr__(self, name):
            raise AssertionError(f"AgentTalk must not use ChatStorage.{name}")

    class _Bot:
        """Streaming bot that records arguments and yields one final message."""

        def __init__(self, message: AIMessage) -> None:
            self.calls: list[dict] = []
            self.message = message

        async def ask_stream(self, **kwargs):
            self.calls.append(kwargs)
            yield self.message

    monkeypatch.setattr(agent_module.web, "StreamResponse", _StreamResponse)
    storage = _ChatStorage()
    message = AIMessage(
        input="hello",
        output="world",
        response="world",
        model="test-model",
        provider="test-provider",
        usage=CompletionUsage(prompt_tokens=3, completion_tokens=5, estimated_cost=0.42),
    )
    bot = _Bot(message)
    handler = SimpleNamespace(
        request=SimpleNamespace(app={"chat_storage": storage}),
        logger=MagicMock(),
        _maybe_start_avatar_speaker=AsyncMock(return_value=None),
    )
    cls = agent_module.AgentTalk
    handler._cancel_suggestions_task = cls._cancel_suggestions_task
    for name in ("_write_auth_required_trailer", "_turn_auth_requirement", "_retry_safe"):
        setattr(handler, name, types.MethodType(getattr(cls, name), handler))

    await agent_module.AgentTalk._handle_stream_response(
        handler,
        bot=bot,
        query="hello",
        session_id="session-1",
        user_id="user-1",
        search_type="similarity",
        return_sources=True,
        use_vector_context=True,
        use_conversation_history=True,
        output_mode=agent_module.OutputMode.DEFAULT,
        format_kwargs={},
        llm=None,
        agent_name="agent-1",
        tenant="acme",
        client_message_id="client-msg-1",
    )
    await asyncio.sleep(0)

    assert bot.calls[0]["tenant"] == "acme"
    assert bot.calls[0]["turn_id"] == "client-msg-1"
