"""FEAT-710 TASK-4552 — AgentTalk tenant + per-turn metadata."""

from __future__ import annotations

import asyncio
from pathlib import Path
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
    assert source.count("tenant=tenant,") == 3


def test_save_turn_metadata_both_paths() -> None:
    """Both persisted AgentTalk turn paths include the telemetry metadata."""
    source = _AGENT_SRC.read_text(encoding="utf-8")

    assert source.count("chat_storage.save_turn(") == 2
    stream_save, sync_save = source.split("chat_storage.save_turn(")[1:]

    for save_call, message_name in ((stream_save, "ai_message"), (sync_save, "response")):
        assert "metadata={" in save_call
        assert f'"usage": {message_name}.usage.model_dump() if {message_name}.usage is not None else None,' in save_call
        assert f'"cost_usd": {message_name}.usage.estimated_cost if {message_name}.usage is not None else None,' in save_call
        assert '"tenant": tenant,' in save_call
        assert '"agent": agent_name,' in save_call


@pytest.mark.asyncio
async def test_stream_save_turn_receives_resolved_tenant_metadata(monkeypatch) -> None:
    """The streaming persistence task retains the explicitly supplied tenant."""
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
        """Recording asynchronous chat storage."""

        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def save_turn(self, **kwargs) -> None:
            self.calls.append(kwargs)

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
        memory=None,
        llm=None,
        agent_name="agent-1",
        tenant="acme",
    )
    await asyncio.sleep(0)

    assert bot.calls[0]["tenant"] == "acme"
    assert storage.calls[0]["metadata"] == {
        "usage": message.usage.model_dump(),
        "cost_usd": 0.42,
        "tenant": "acme",
        "agent": "agent-1",
    }
