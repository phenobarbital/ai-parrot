"""Unit + integration tests for the OpenAI-compatible chat-completions endpoint
(FEAT-247, TASK-1874 + TASK-1876).

Following the project convention for handler tests (see
``test_knowledge_handler.py``), the views are exercised via ``__new__`` +
manually-injected ``.logger``/``._request`` — bypassing navigator's
``BaseView`` init (which needs a live app/auth) — and
``web.StreamResponse`` is monkeypatched to a chunk-capturing fake so the SSE
stream can be inspected without a real HTTP connection.

``TestOpenAICompatIntegration`` (TASK-1876) is the exception: it stands up a
real aiohttp test server via ``aiohttp_client`` and drives it with the actual
``openai`` Python SDK to verify wire-format conformance end-to-end. Skipped
automatically when the optional ``openai`` dev dependency is not installed.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.handlers.openai_compat import (
    OPENAI_COMPAT_BEARER_TOKEN_ENV,
    OpenAIChatCompletions,
    OpenAIModels,
)
from parrot.models.responses import AIMessage

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeStreamResponse:
    """Captures chunks written to a streamed response (mirrors test_knowledge_handler.py)."""

    instances: list = []

    def __init__(self, *args, **kwargs):
        self.chunks: list[bytes] = []
        self.eof = False
        _FakeStreamResponse.instances.append(self)

    async def prepare(self, request):
        self.prepared = True

    async def write(self, data: bytes):
        self.chunks.append(data)

    async def drain(self):
        pass

    async def write_eof(self):
        self.eof = True


def _make_handler(
    view_cls,
    *,
    headers=None,
    match_info=None,
    query=None,
    json_body=None,
    app=None,
):
    """Construct a view with a mocked request (bypasses BaseView.__init__)."""
    handler = view_cls.__new__(view_cls)
    handler.logger = logging.getLogger("test.openai_compat")

    request = MagicMock()
    request.app = app if app is not None else {}
    request.headers = headers or {}
    request.match_info = match_info or {}
    fake_url = MagicMock()
    fake_url.query = query or {}
    request.rel_url = fake_url
    request.json = AsyncMock(return_value=json_body or {})
    # ``request`` is a read-only property on aiohttp's View — set the backing
    # attribute it returns (``self._request``).
    handler._request = request
    return handler, request


def _fake_bot(name: str = "test_agent"):
    bot = MagicMock()
    bot.name = name

    async def _stream(question, session_id=None, **kw):
        yield "Hello "
        yield "world."

    bot.ask_stream = _stream
    return bot


@pytest.fixture(autouse=True)
def _bearer_token(monkeypatch):
    monkeypatch.setenv(OPENAI_COMPAT_BEARER_TOKEN_ENV, "test-secret-token")


# ---------------------------------------------------------------------------
# TestOpenAIChatCompletions
# ---------------------------------------------------------------------------


class TestOpenAIChatCompletions:
    async def test_streams_deltas(self, monkeypatch):
        """stream=true -> SSE chat.completion.chunk deltas ending [DONE]."""
        bot_manager = MagicMock()
        bot_manager.get_bot = AsyncMock(return_value=_fake_bot())
        handler, _ = _make_handler(
            OpenAIChatCompletions,
            headers={"Authorization": "Bearer test-secret-token"},
            match_info={"session_id": "sess-1"},
            query={"agent": "test_agent"},
            json_body={
                "model": "test_agent",
                "messages": [{"role": "user", "content": "Who is Pikachu?"}],
                "stream": True,
            },
            app={
                "bot_manager": bot_manager,
                "avatar_fullmode_sessions": {"sess-1": {}},
            },
        )
        _FakeStreamResponse.instances.clear()
        monkeypatch.setattr(
            "parrot.handlers.openai_compat.web.StreamResponse", _FakeStreamResponse
        )

        resp = await handler.post()

        stream = _FakeStreamResponse.instances[-1]
        assert resp is stream
        assert stream.eof is True
        raw = b"".join(stream.chunks).decode()
        assert "chat.completion.chunk" in raw
        assert "Hello world." in raw
        assert '"finish_reason": "stop"' in raw
        assert raw.strip().endswith("data: [DONE]")

    async def test_non_stream_json(self):
        """stream=false -> single JSON completion response."""
        bot_manager = MagicMock()
        bot_manager.get_bot = AsyncMock(return_value=_fake_bot())
        handler, _ = _make_handler(
            OpenAIChatCompletions,
            headers={"Authorization": "Bearer test-secret-token"},
            match_info={"session_id": "sess-1"},
            query={"agent": "test_agent"},
            json_body={
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
            },
            app={
                "bot_manager": bot_manager,
                "avatar_fullmode_sessions": {"sess-1": {}},
            },
        )

        resp = await handler.post()
        body = json.loads(resp.body)

        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["content"] == "Hello world."
        assert body["choices"][0]["finish_reason"] == "stop"

    async def test_auth_required(self):
        """Missing bearer token -> 401."""
        handler, _ = _make_handler(
            OpenAIChatCompletions,
            headers={},
            match_info={"session_id": "sess-1"},
        )

        with pytest.raises(web.HTTPUnauthorized):
            await handler.post()

    async def test_invalid_bearer_token_rejected(self):
        """Wrong bearer token -> 401."""
        handler, _ = _make_handler(
            OpenAIChatCompletions,
            headers={"Authorization": "Bearer wrong-token"},
            match_info={"session_id": "sess-1"},
        )

        with pytest.raises(web.HTTPUnauthorized):
            await handler.post()

    async def test_unknown_session_404(self):
        """session_id not in FULLMODE_SESSIONS_KEY -> 404."""
        handler, _ = _make_handler(
            OpenAIChatCompletions,
            headers={"Authorization": "Bearer test-secret-token"},
            match_info={"session_id": "ghost"},
            app={"avatar_fullmode_sessions": {}},
        )

        with pytest.raises(web.HTTPNotFound):
            await handler.post()

    async def test_resolves_agent_and_session(self):
        """agent from query param + session_id from URL passed to ask_stream."""
        captured = {}

        bot = MagicMock()
        bot.name = "test_agent"

        async def _stream(question, session_id=None, **kw):
            captured["question"] = question
            captured["session_id"] = session_id
            yield "ok."

        bot.ask_stream = _stream

        bot_manager = MagicMock()
        bot_manager.get_bot = AsyncMock(return_value=bot)

        handler, _ = _make_handler(
            OpenAIChatCompletions,
            headers={"Authorization": "Bearer test-secret-token"},
            match_info={"session_id": "sess-42"},
            query={"agent": "test_agent"},
            json_body={
                "messages": [{"role": "user", "content": "What's Pikachu?"}],
                "stream": False,
            },
            app={
                "bot_manager": bot_manager,
                "avatar_fullmode_sessions": {"sess-42": {}},
            },
        )

        await handler.post()

        bot_manager.get_bot.assert_awaited_once_with("test_agent", session_id="sess-42")
        assert captured["question"] == "What's Pikachu?"
        assert captured["session_id"] == "sess-42"

    async def test_agent_session_mismatch_forbidden(self):
        """agent query param must match the agent this session was started for."""
        bot_manager = MagicMock()
        bot_manager.get_bot = AsyncMock(return_value=_fake_bot())

        handler, _ = _make_handler(
            OpenAIChatCompletions,
            headers={"Authorization": "Bearer test-secret-token"},
            match_info={"session_id": "sess-1"},
            query={"agent": "some_other_agent"},
            json_body={
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
            },
            app={
                "bot_manager": bot_manager,
                "avatar_fullmode_sessions": {
                    "sess-1": {"agent_id": "pokemon_analyst"}
                },
            },
        )

        with pytest.raises(web.HTTPForbidden):
            await handler.post()

        bot_manager.get_bot.assert_not_awaited()

    async def test_agent_session_match_allowed(self):
        """Matching agent + session_id proceeds normally."""
        bot_manager = MagicMock()
        bot_manager.get_bot = AsyncMock(return_value=_fake_bot())

        handler, _ = _make_handler(
            OpenAIChatCompletions,
            headers={"Authorization": "Bearer test-secret-token"},
            match_info={"session_id": "sess-1"},
            query={"agent": "pokemon_analyst"},
            json_body={
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
            },
            app={
                "bot_manager": bot_manager,
                "avatar_fullmode_sessions": {
                    "sess-1": {"agent_id": "pokemon_analyst"}
                },
            },
        )

        resp = await handler.post()
        assert json.loads(resp.body)["object"] == "chat.completion"

    async def test_unknown_agent_returns_404(self):
        """get_bot() returning None (unregistered agent) -> 404, not a crash."""
        bot_manager = MagicMock()
        bot_manager.get_bot = AsyncMock(return_value=None)

        handler, _ = _make_handler(
            OpenAIChatCompletions,
            headers={"Authorization": "Bearer test-secret-token"},
            match_info={"session_id": "sess-1"},
            query={"agent": "no_such_agent"},
            json_body={
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
            },
            app={
                "bot_manager": bot_manager,
                "avatar_fullmode_sessions": {"sess-1": {}},
            },
        )

        with pytest.raises(web.HTTPNotFound):
            await handler.post()

    async def test_non_stream_ask_stream_error_returns_500(self):
        """bot.ask_stream raising mid-turn -> clean 500, not an unhandled exception."""
        bot = MagicMock()
        bot.name = "test_agent"

        async def _stream(question, session_id=None, **kw):
            raise RuntimeError("provider unavailable")
            yield  # pragma: no cover - unreachable, makes this an async generator

        bot.ask_stream = _stream

        bot_manager = MagicMock()
        bot_manager.get_bot = AsyncMock(return_value=bot)

        handler, _ = _make_handler(
            OpenAIChatCompletions,
            headers={"Authorization": "Bearer test-secret-token"},
            match_info={"session_id": "sess-1"},
            query={"agent": "test_agent"},
            json_body={
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
            },
            app={
                "bot_manager": bot_manager,
                "avatar_fullmode_sessions": {"sess-1": {}},
            },
        )

        with pytest.raises(web.HTTPInternalServerError):
            await handler.post()

    async def test_no_double_speak_when_response_mirrors_streamed_chunks(self, monkeypatch):
        """Regression: a final AIMessage.response equal to the already-streamed
        text must NOT be spoken a second time (code-review finding)."""
        ai_message = MagicMock(spec=AIMessage)
        ai_message.is_structured = False
        ai_message.data = None
        ai_message.code = None
        ai_message.tool_calls = []
        # Mirrors real ask_stream implementations (e.g. clients/grok.py,
        # AbstractBot.ask_stream's fallback envelope): `.response` holds the
        # SAME text already yielded chunk-by-chunk, not additional content.
        ai_message.response = "Hello world."
        ai_message.turn_id = None

        bot = MagicMock()
        bot.name = "test_agent"

        async def _stream(question, session_id=None, **kw):
            yield "Hello "
            yield "world."
            yield ai_message

        bot.ask_stream = _stream

        bot_manager = MagicMock()
        bot_manager.get_bot = AsyncMock(return_value=bot)

        monkeypatch.setattr(
            "parrot.handlers.agent.AgentTalk._maybe_publish_bifurcated_output",
            AsyncMock(),
        )

        handler, _ = _make_handler(
            OpenAIChatCompletions,
            headers={"Authorization": "Bearer test-secret-token"},
            match_info={"session_id": "sess-1"},
            query={"agent": "test_agent"},
            json_body={
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
            app={
                "bot_manager": bot_manager,
                "avatar_fullmode_sessions": {"sess-1": {}},
            },
        )
        _FakeStreamResponse.instances.clear()
        monkeypatch.setattr(
            "parrot.handlers.openai_compat.web.StreamResponse", _FakeStreamResponse
        )

        await handler.post()

        stream = _FakeStreamResponse.instances[-1]
        raw = b"".join(stream.chunks).decode()
        # "Hello world." must appear as spoken content exactly once, not twice.
        assert raw.count("Hello world.") == 1

    async def test_structured_output_published_without_crashing_stream(self, monkeypatch):
        """Final AIMessage w/ structured data triggers bifurcation, never crashes stream."""
        ai_message = MagicMock(spec=AIMessage)
        ai_message.is_structured = True
        ai_message.data = {"hp": 35}
        ai_message.code = None
        ai_message.tool_calls = []
        ai_message.response = ""
        ai_message.turn_id = "turn-abc"

        bot = MagicMock()
        bot.name = "pokemon_analyst"

        async def _stream(question, session_id=None, **kw):
            yield "Pikachu is "
            yield "an Electric type."
            yield ai_message

        bot.ask_stream = _stream

        bot_manager = MagicMock()
        bot_manager.get_bot = AsyncMock(return_value=bot)

        published = []

        async def _fake_publish(self, *, ai_message, session_id, turn_id=None):
            published.append((session_id, turn_id, ai_message))

        monkeypatch.setattr(
            "parrot.handlers.agent.AgentTalk._maybe_publish_bifurcated_output",
            _fake_publish,
        )

        handler, _ = _make_handler(
            OpenAIChatCompletions,
            headers={"Authorization": "Bearer test-secret-token"},
            match_info={"session_id": "sess-1"},
            query={"agent": "pokemon_analyst"},
            json_body={
                "messages": [{"role": "user", "content": "Who is Pikachu?"}],
                "stream": True,
            },
            app={
                "bot_manager": bot_manager,
                "avatar_fullmode_sessions": {"sess-1": {}},
            },
        )
        _FakeStreamResponse.instances.clear()
        monkeypatch.setattr(
            "parrot.handlers.openai_compat.web.StreamResponse", _FakeStreamResponse
        )

        await handler.post()

        assert len(published) == 1
        assert published[0][0] == "sess-1"
        assert published[0][1] == "turn-abc"
        stream = _FakeStreamResponse.instances[-1]
        assert stream.eof is True
        raw = b"".join(stream.chunks).decode()
        assert raw.strip().endswith("data: [DONE]")

    async def test_structured_only_turn_gets_spoken_filler(self, monkeypatch):
        """A turn with ONLY structured output (no text chunks) still speaks something."""
        ai_message = MagicMock(spec=AIMessage)
        ai_message.is_structured = True
        ai_message.data = {"hp": 35}
        ai_message.code = None
        ai_message.tool_calls = []
        ai_message.response = ""
        ai_message.turn_id = None

        bot = MagicMock()
        bot.name = "pokemon_analyst"

        async def _stream(question, session_id=None, **kw):
            yield ai_message

        bot.ask_stream = _stream

        bot_manager = MagicMock()
        bot_manager.get_bot = AsyncMock(return_value=bot)

        monkeypatch.setattr(
            "parrot.handlers.agent.AgentTalk._maybe_publish_bifurcated_output",
            AsyncMock(),
        )

        handler, _ = _make_handler(
            OpenAIChatCompletions,
            headers={"Authorization": "Bearer test-secret-token"},
            match_info={"session_id": "sess-1"},
            query={"agent": "pokemon_analyst"},
            json_body={
                "messages": [{"role": "user", "content": "Show me a chart"}],
                "stream": True,
            },
            app={
                "bot_manager": bot_manager,
                "avatar_fullmode_sessions": {"sess-1": {}},
            },
        )
        _FakeStreamResponse.instances.clear()
        monkeypatch.setattr(
            "parrot.handlers.openai_compat.web.StreamResponse", _FakeStreamResponse
        )

        await handler.post()

        stream = _FakeStreamResponse.instances[-1]
        raw = b"".join(stream.chunks).decode()
        # A non-empty spoken delta was emitted despite no plain-text chunks.
        assert '"content":' in raw.replace(" ", "")


# ---------------------------------------------------------------------------
# TestOpenAIModels
# ---------------------------------------------------------------------------


class TestOpenAIModels:
    async def test_models_endpoint(self):
        """GET /v1/models returns available agent names."""
        bot_manager = MagicMock()
        bot_manager.get_bots.return_value = {
            "pokemon_analyst": MagicMock(),
            "weather_bot": MagicMock(),
        }

        handler, _ = _make_handler(
            OpenAIModels,
            headers={"Authorization": "Bearer test-secret-token"},
            app={"bot_manager": bot_manager},
        )

        resp = await handler.get()
        body = json.loads(resp.body)

        ids = {m["id"] for m in body["data"]}
        assert ids == {"pokemon_analyst", "weather_bot"}
        assert body["object"] == "list"

    async def test_models_endpoint_no_manager(self):
        """GET /v1/models with no bot_manager configured returns an empty list."""
        handler, _ = _make_handler(
            OpenAIModels,
            headers={"Authorization": "Bearer test-secret-token"},
            app={},
        )

        resp = await handler.get()
        body = json.loads(resp.body)

        assert body["data"] == []

    async def test_models_endpoint_requires_auth(self):
        """GET /v1/models without a bearer token -> 401 (agent registry is not public)."""
        handler, _ = _make_handler(OpenAIModels, headers={}, app={})

        with pytest.raises(web.HTTPUnauthorized):
            await handler.get()


# ---------------------------------------------------------------------------
# TestOpenAICompatIntegration (TASK-1876)
# ---------------------------------------------------------------------------

openai = pytest.importorskip("openai")


class TestOpenAICompatIntegration:
    """The ``openai`` Python SDK, pointed at our per-session URL, streams a
    completion end-to-end (contract-conformance integration test).

    LiveAvatar's Custom LLM integration POSTs directly to the minted
    per-session URL (``/v1/chat/completions/{session_id}``), which is not a
    fixed suffix the ``openai`` SDK's high-level ``chat.completions.create()``
    can target (it always appends ``/chat/completions`` to ``base_url``).
    The SDK's low-level ``client.post(path, ..., stream_cls=...)`` escape
    hatch is used instead so the *actual* SSE decoder from the SDK parses our
    response — this is what makes it a wire-format conformance check rather
    than a reimplementation of our own SSE parsing.
    """

    async def test_openai_sdk_streams_completion(self, aiohttp_client, monkeypatch):
        from openai import AsyncOpenAI, AsyncStream
        from openai.types.chat import ChatCompletionChunk

        from parrot.handlers.openai_compat import register_openai_compat_routes

        monkeypatch.setenv(OPENAI_COMPAT_BEARER_TOKEN_ENV, "test-secret-token")

        app = web.Application()
        register_openai_compat_routes(app.router)

        bot = MagicMock()
        bot.name = "pokemon_analyst"

        async def _stream(question, session_id=None, **kw):
            yield "Pikachu is "
            yield "an Electric type."

        bot.ask_stream = _stream

        bot_manager = MagicMock()
        bot_manager.get_bot = AsyncMock(return_value=bot)

        app["bot_manager"] = bot_manager
        app["avatar_fullmode_sessions"] = {"sess-int-1": {}}

        test_client = await aiohttp_client(app)
        base_url = str(test_client.make_url("/"))

        sdk_client = AsyncOpenAI(api_key="unused", base_url=base_url)

        stream = await sdk_client.post(
            "/v1/chat/completions/sess-int-1?agent=pokemon_analyst",
            body={
                "model": "pokemon_analyst",
                "messages": [{"role": "user", "content": "Who is Pikachu?"}],
                "stream": True,
            },
            cast_to=ChatCompletionChunk,
            stream=True,
            stream_cls=AsyncStream[ChatCompletionChunk],
            options={"headers": {"Authorization": "Bearer test-secret-token"}},
        )

        collected = ""
        saw_stop = False
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is not None and delta.content:
                collected += delta.content
            if chunk.choices and chunk.choices[0].finish_reason == "stop":
                saw_stop = True

        assert "Pikachu is an Electric type." in collected
        assert saw_stop
