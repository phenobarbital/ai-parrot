"""OpenAI-compatible streaming chat-completions endpoint (FEAT-247).

Exposes an OpenAI-compatible surface so LiveAvatar FULL Mode can call
ai-parrot directly as its **Custom LLM**, removing the frontend from the
LLM<->avatar relay loop (FEAT-248 built the FULL mode session lifecycle;
this module adds the missing wire protocol on top of it):

    POST /v1/chat/completions/{session_id}
        OpenAI-compatible chat-completions endpoint.  ``session_id`` is baked
        into the URL path (minted by ``/full/start``, see
        ``handlers/avatar_fullmode.py`` + TASK-1875) and ``agent`` is passed
        as a query parameter.  Authenticated via a static ``Authorization:
        Bearer <token>`` shared secret (server-to-server call from
        LiveAvatar's infra, not a browser session).

        ``stream=true`` (LiveAvatar's mode) emits OpenAI
        ``chat.completion.chunk`` SSE deltas backed by
        :meth:`AbstractBot.ask_stream`, flattened through
        :class:`SpeakableFlattener` so markdown never leaks into the TTS
        pipeline, and terminates with ``data: [DONE]``.  ``stream=false``
        returns a single JSON completion.

        Structured output on the final ``AIMessage`` (data/code/tool_calls)
        is published via the existing FEAT-249 Mode-B bifurcation path
        (``AgentTalk._maybe_publish_bifurcated_output``) so it still reaches
        the AgentChat WS side channel — reused here rather than
        reimplemented, see :func:`_publish_bifurcated_output`.

    GET /v1/models
        Minimal OpenAI-compatible model listing: one "model" per registered
        agent name.

Lazy/defensive: this module has no optional-extra dependency of its own (no
liveavatar import at module scope), so it is always importable; TASK-1876
wires ``register_openai_compat_routes`` into ``manager.py`` under the
standard defensive ``ImportError`` guard used by the other optional route
groups.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from aiohttp import web
from navigator.views import BaseView
from pydantic import BaseModel, ConfigDict, Field

from parrot.bots.base import AbstractBot
from parrot.models.responses import AIMessage

from .avatar_fullmode import FULLMODE_SESSIONS_KEY

_logger = logging.getLogger("Parrot.OpenAICompatView")

# Env var holding the shared secret LiveAvatar must present as
# ``Authorization: Bearer <token>`` on every call to this endpoint.
OPENAI_COMPAT_BEARER_TOKEN_ENV = "OPENAI_COMPAT_BEARER_TOKEN"

# Short spoken filler used when a turn produced ONLY structured output (e.g.
# a chart) and nothing was ever fed to the SpeakableFlattener — otherwise the
# avatar would sit there mute (spec §7 Known Risks).
_STRUCTURED_ONLY_FILLER = "Here's what I found."


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    """A single OpenAI-style chat message."""

    role: str = Field(..., description="'system' | 'user' | 'assistant'")
    content: str = Field(default="", description="Message text content")


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat-completions request (subset we honour).

    Unrecognised fields (``temperature``, ``top_p``, ``max_tokens``, etc.)
    are tolerated but ignored — ``model`` is informational only since the
    agent is resolved from the URL's per-session route, not from this body.
    """

    model_config = ConfigDict(extra="ignore")

    model: str = Field(default="", description="Informational; agent resolved from URL")
    messages: List[ChatMessage] = Field(default_factory=list)
    stream: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_bearer_token(request: web.Request) -> bool:
    """Validate ``Authorization: Bearer <token>`` against the configured secret.

    Fails closed: if ``OPENAI_COMPAT_BEARER_TOKEN`` is not configured, every
    request is rejected (there is no shared secret to authenticate against).

    Args:
        request: The incoming aiohttp request.

    Returns:
        ``True`` if the bearer token matches the configured secret.
    """
    expected = os.environ.get(OPENAI_COMPAT_BEARER_TOKEN_ENV)
    if not expected:
        _logger.warning(
            "%s is not configured — rejecting OpenAI-compat request.",
            OPENAI_COMPAT_BEARER_TOKEN_ENV,
        )
        return False
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False
    token = auth_header[len("Bearer "):]
    return token == expected


def _extract_last_user_message(messages: List[ChatMessage]) -> Optional[str]:
    """Return the content of the last ``role="user"`` message, if any.

    Args:
        messages: Parsed OpenAI-style message list from the request body.

    Returns:
        The last user message's content, or ``None`` if no user message
        is present.
    """
    for msg in reversed(messages):
        if msg.role == "user":
            return msg.content
    return None


def _sse_chunk(
    completion_id: str,
    created: int,
    model: str,
    *,
    content: Optional[str] = None,
    finish_reason: Optional[str] = None,
) -> bytes:
    """Build one OpenAI ``chat.completion.chunk`` SSE frame.

    Args:
        completion_id: Stable ``chatcmpl-...`` id for this completion.
        created: Unix timestamp (seconds) the completion started at.
        model: Model id to report (the resolved agent name).
        content: Delta text content, or ``None`` for an empty delta (e.g.
            the terminal ``finish_reason="stop"`` chunk).
        finish_reason: ``"stop"`` on the terminal chunk, ``None`` otherwise.

    Returns:
        UTF-8 encoded ``b"data: {...}\\n\\n"`` frame ready to write on the
        stream response.
    """
    delta: Dict[str, Any] = {"content": content} if content is not None else {}
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {"index": 0, "delta": delta, "finish_reason": finish_reason}
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n".encode("utf-8")


_DONE_FRAME = b"data: [DONE]\n\n"


async def _publish_bifurcated_output(
    request: web.Request,
    logger: logging.Logger,
    ai_message: Any,
    session_id: str,
    turn_id: Optional[str],
) -> None:
    """Publish structured output via the existing FEAT-249 Mode-B path.

    Reuses ``AgentTalk._maybe_publish_bifurcated_output`` (handlers/agent.py)
    rather than reimplementing the bifurcation logic: the method is invoked
    as an unbound call against a minimal shim exposing only ``.request`` and
    ``.logger`` — the two attributes it reads. This mirrors the pattern
    already established in
    ``tests/handlers/test_fullmode_bifurcation.py::_FakeAgentTalk``.

    Best-effort: any error (including the import itself) is logged and
    swallowed so it never breaks the spoken stream.

    Args:
        request: The originating aiohttp request (carries ``app`` context).
        logger: Logger to use for the shim (and for reporting failures here).
        ai_message: The final ``AIMessage`` from the turn.
        session_id: The conversation/session id (Redis channel key).
        turn_id: Optional turn identifier for deduplication.
    """
    try:
        from parrot.handlers.agent import AgentTalk

        class _BifurcationShim:
            pass

        shim = _BifurcationShim()
        shim.request = request  # type: ignore[attr-defined]
        shim.logger = logger  # type: ignore[attr-defined]

        await AgentTalk._maybe_publish_bifurcated_output(
            shim, ai_message=ai_message, session_id=session_id, turn_id=turn_id,
        )
    except Exception:  # noqa: BLE001 - best-effort, never breaks the reply
        logger.warning(
            "OpenAICompat: bifurcated output publish failed for session %s",
            session_id, exc_info=True,
        )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class OpenAIChatCompletions(BaseView):
    """``POST /v1/chat/completions/{session_id}`` — OpenAI-compatible endpoint.

    Bridges LiveAvatar FULL Mode's Custom LLM calls to
    :meth:`AbstractBot.ask_stream`, reusing the FEAT-249 Mode-B bifurcation
    pattern for structured outputs and :class:`SpeakableFlattener` so
    markdown never reaches LiveAvatar's TTS.
    """

    async def post(self) -> Union[web.StreamResponse, web.Response]:
        """Handle a chat-completions request (streaming or non-streaming)."""
        request = self.request

        if not _check_bearer_token(request):
            raise web.HTTPUnauthorized(reason="Missing or invalid bearer token")

        session_id = request.match_info.get("session_id", "")
        fullmode_store: Dict[str, Any] = request.app.get(FULLMODE_SESSIONS_KEY) or {}
        if not session_id or session_id not in fullmode_store:
            raise web.HTTPNotFound(
                reason=f"Unknown FULL mode session_id '{session_id}'"
            )

        agent_name = request.rel_url.query.get("agent", "")
        if not agent_name:
            raise web.HTTPBadRequest(reason="'agent' query parameter is required")

        try:
            body: Dict[str, Any] = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise web.HTTPBadRequest(reason="Invalid JSON body") from exc

        try:
            chat_request = ChatCompletionRequest(**body)
        except Exception as exc:  # noqa: BLE001
            raise web.HTTPBadRequest(
                reason=f"Invalid chat-completions request: {exc}"
            ) from exc

        question = _extract_last_user_message(chat_request.messages)
        if question is None:
            raise web.HTTPBadRequest(reason="No user message found in 'messages'")

        manager = request.app.get("bot_manager")
        if manager is None:
            raise web.HTTPServiceUnavailable(reason="Bot manager is not configured")

        bot: AbstractBot = await manager.get_bot(agent_name, session_id=session_id)

        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())

        if chat_request.stream:
            return await self._stream_response(
                bot=bot,
                question=question,
                session_id=session_id,
                agent_name=agent_name,
                completion_id=completion_id,
                created=created,
            )
        return await self._non_stream_response(
            bot=bot,
            question=question,
            session_id=session_id,
            agent_name=agent_name,
            completion_id=completion_id,
            created=created,
        )

    async def _stream_response(
        self,
        *,
        bot: AbstractBot,
        question: str,
        session_id: str,
        agent_name: str,
        completion_id: str,
        created: int,
    ) -> web.StreamResponse:
        """Stream the completion as OpenAI ``chat.completion.chunk`` SSE frames."""
        # Local import: SpeakableFlattener ships from the optional
        # ai-parrot-integrations[liveavatar] extra. The session was already
        # validated against FULLMODE_SESSIONS_KEY above, so this import can
        # only fail if the extra was uninstalled after the session started —
        # treated as a hard 503 rather than silently degrading speech.
        from parrot.integrations.liveavatar.speakable import SpeakableFlattener

        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await resp.prepare(self.request)

        flattener = SpeakableFlattener()
        ai_message: Optional[AIMessage] = None
        emitted_any = False

        async def _write_sentences(sentences: List[str]) -> None:
            nonlocal emitted_any
            for sentence in sentences:
                await resp.write(
                    _sse_chunk(completion_id, created, agent_name, content=sentence)
                )
                await resp.drain()
                emitted_any = True

        try:
            async_stream: AsyncIterator[Union[str, AIMessage]] = bot.ask_stream(
                question, session_id=session_id,
            )
            async for chunk in async_stream:
                if isinstance(chunk, AIMessage):
                    ai_message = chunk
                else:
                    await _write_sentences(flattener.feed(chunk))

            await _write_sentences(flattener.flush())

            # Acceptance: "the final AIMessage's speakable response is also
            # spoken" — feed any trailing response text not already covered
            # by the streamed chunks (e.g. a spoken caption for a chart).
            if ai_message is not None and getattr(ai_message, "response", None):
                await _write_sentences(flattener.feed(ai_message.response))
                await _write_sentences(flattener.flush())

            # Known risk (spec §7): a turn that is ONLY structured output
            # (e.g. a chart) produces no speech — emit a short filler so the
            # avatar isn't mute.
            if not emitted_any and ai_message is not None:
                has_structured = bool(
                    getattr(ai_message, "is_structured", False)
                    or getattr(ai_message, "data", None) is not None
                    or getattr(ai_message, "code", None) is not None
                    or getattr(ai_message, "tool_calls", None)
                )
                if has_structured:
                    await _write_sentences([_STRUCTURED_ONLY_FILLER])

            if ai_message is not None and session_id:
                await _publish_bifurcated_output(
                    self.request,
                    self.logger,
                    ai_message,
                    session_id,
                    str(getattr(ai_message, "turn_id", "") or "") or None,
                )

            await resp.write(
                _sse_chunk(completion_id, created, agent_name, finish_reason="stop")
            )
            await resp.write(_DONE_FRAME)
        except asyncio.CancelledError:
            self.logger.info(
                "OpenAICompat: stream cancelled by client for session %s", session_id,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "OpenAICompat: stream error for session %s: %s", session_id, exc,
            )
            try:
                await resp.write(
                    _sse_chunk(completion_id, created, agent_name, finish_reason="stop")
                )
                await resp.write(_DONE_FRAME)
            except Exception:  # noqa: BLE001
                pass
        finally:
            await resp.write_eof()
        return resp

    async def _non_stream_response(
        self,
        *,
        bot: AbstractBot,
        question: str,
        session_id: str,
        agent_name: str,
        completion_id: str,
        created: int,
    ) -> web.Response:
        """Run the turn to completion and return a single JSON completion."""
        content_parts: List[str] = []
        ai_message: Optional[AIMessage] = None

        async_stream: AsyncIterator[Union[str, AIMessage]] = bot.ask_stream(
            question, session_id=session_id,
        )
        async for chunk in async_stream:
            if isinstance(chunk, AIMessage):
                ai_message = chunk
            else:
                content_parts.append(chunk)

        content = "".join(content_parts)
        if not content and ai_message is not None:
            content = ai_message.response or ""

        if ai_message is not None and session_id:
            await _publish_bifurcated_output(
                self.request,
                self.logger,
                ai_message,
                session_id,
                str(getattr(ai_message, "turn_id", "") or "") or None,
            )

        completion = {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": agent_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        }
        return web.json_response(completion)


class OpenAIModels(BaseView):
    """``GET /v1/models`` — minimal OpenAI-compatible model listing.

    Reports one "model" per agent registered on the ``BotManager``.
    """

    async def get(self) -> web.Response:
        """List available agents as OpenAI-style model entries."""
        manager = self.request.app.get("bot_manager")
        agent_names: List[str] = []
        if manager is not None:
            agent_names = list(getattr(manager, "_bots", {}).keys())

        return web.json_response({
            "object": "list",
            "data": [
                {"id": name, "object": "model", "owned_by": "ai-parrot"}
                for name in agent_names
            ],
        })


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_openai_compat_routes(router: Any) -> bool:
    """Register the OpenAI-compat chat-completions and models routes.

    Unlike ``register_fullmode_routes``, this module has no optional-extra
    import of its own at module scope, so it has no guard to run here;
    TASK-1876 wires this function into ``manager.py`` under the standard
    defensive ``ImportError`` pattern used for the other optional route
    groups (the guard covers the caller failing to import this module at
    all, e.g. if a future dependency of this file becomes optional).

    Args:
        router: The aiohttp ``UrlDispatcher`` to register routes on.

    Returns:
        ``True`` — routes are always registered when this function runs.
    """
    router.add_view("/v1/chat/completions/{session_id}", OpenAIChatCompletions)
    router.add_view("/v1/models", OpenAIModels)
    _logger.info("OpenAI-compat routes registered.")
    return True
