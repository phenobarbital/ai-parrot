"""``llm_node`` ai-parrot bridge for LiveAvatar Phase C (FEAT-243, Module 2).

``LiveAvatarAgent`` replaces the LiveKit Agents LLM node with ai-parrot: it
extracts the last user message from ``chat_ctx``, calls ``ask_stream()`` on the
resolved ai-parrot bot and bifurcates the response:

- **speakable text** is run through the FEAT-242 :class:`SpeakableFlattener` and
  ``yield``ed as plain ``str`` so LiveKit's TTS node speaks it through the avatar;
- **structured outputs** (``tool_calls`` / ``data`` / non-default ``output_mode``
  / ``artifact_id``) are routed to the :class:`OutputBridge`, which publishes them
  to the AgentChat UI channel keyed by ``session_id``.

A short filler utterance is emitted when a turn resolves to tool calls without
producing any speech, so the avatar never goes silent (spec: no dead air during
long ``tool_calls``; Open Question Q-filler).

The heavy ``livekit-agents`` dependency (the ``liveavatar-voice`` extra) is
imported lazily: when it is absent the class still defines its logic on a plain
``object`` base so the module imports and the bifurcation is unit-testable
without a live LiveKit room.

.. note::
   **P5** — the exact ``Agent.llm_node(chat_ctx, tools, model_settings)``
   signature and the ``chat_ctx`` shape MUST be validated against the pinned
   ``livekit-agents`` version before production use. :func:`_last_user_text`
   is written defensively across the known 1.x shapes.
"""

import logging
from dataclasses import asdict, is_dataclass
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, Optional

from pydantic import BaseModel

from parrot.integrations.liveavatar.livekit_agent.models import (
    StructuredOutputMessage,
)
from parrot.integrations.liveavatar.output_bridge import OutputBridge
from parrot.integrations.liveavatar.speakable import SpeakableFlattener
from parrot.models.responses import AIMessage

try:  # pragma: no cover - success path requires the 'liveavatar-voice' extra
    from livekit.agents import Agent as _LiveKitAgent

    _HAS_LIVEKIT_AGENTS = True
except ImportError:
    _LiveKitAgent = object  # type: ignore[assignment,misc]
    _HAS_LIVEKIT_AGENTS = False

__all__ = ["LiveAvatarAgent", "DEFAULT_FILLER_TEXT"]

#: Async callable resolving an agent name to an ai-parrot bot exposing
#: ``ask_stream``. In production this is bound to ``BotManager.get_bot``.
BotResolver = Callable[[str], Awaitable[Any]]

#: Default "thinking" filler spoken when a tool turn produces no other speech.
DEFAULT_FILLER_TEXT = "Let me look into that for you."


def _json_safe(value: Any) -> Any:
    """Coerce a structured value into a JSON-serializable form for the UI bridge.

    ``AIMessage.data`` is ``Any`` and is frequently a pandas ``DataFrame`` /
    ``Series`` (or a dataclass / Pydantic model). The AgentChat broadcast path
    runs the payload through a strict JSON encoder, which raises on such
    objects, so they are normalised here before they cross the bridge contract.
    Recurses into ``dict`` / ``list`` so nested frames are handled too.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):  # pandas DataFrame / Series and other mappings
        try:
            return _json_safe(value.to_dict(orient="records"))
        except TypeError:
            return _json_safe(to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return str(value)


def _message_text(msg: Any) -> str:
    """Best-effort extraction of plain text from a livekit ChatMessage.

    Handles the ``text_content`` attribute/method, a ``content`` that is either a
    ``str`` or a list of string parts, and falls back to ``str()``.
    """
    text_content = getattr(msg, "text_content", None)
    if callable(text_content):
        try:
            text_content = text_content()
        except TypeError:  # pragma: no cover - defensive
            text_content = None
    if isinstance(text_content, str) and text_content:
        return text_content

    content = getattr(msg, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = [part for part in content if isinstance(part, str)]
        if parts:
            return " ".join(parts)
    return str(content) if content is not None else ""


def _last_user_text(chat_ctx: Any) -> str:
    """Return the text of the last ``role == "user"`` message in ``chat_ctx``.

    Defensive across livekit-agents shapes: prefers ``chat_ctx.items`` (1.x),
    falls back to ``chat_ctx.messages``. **P5**: validate against the pinned
    version.
    """
    items = getattr(chat_ctx, "items", None)
    if items is None:
        items = getattr(chat_ctx, "messages", None) or []

    last_text = ""
    for msg in items:
        if getattr(msg, "role", None) == "user":
            last_text = _message_text(msg)
    return last_text


def _is_structured(msg: AIMessage) -> bool:
    """True when an ``AIMessage`` carries non-speech structured output."""
    if getattr(msg, "tool_calls", None):
        return True
    if msg.data is not None:
        return True
    if getattr(msg, "artifact_id", None):
        return True
    output_mode = getattr(msg, "output_mode", None)
    mode_value = getattr(output_mode, "value", output_mode)
    return mode_value not in (None, "default")


def _classify(msg: AIMessage) -> str:
    """Map an ``AIMessage`` to a :class:`StructuredOutputMessage` ``type``."""
    if getattr(msg, "tool_calls", None):
        return "tool_call"
    output_mode = getattr(msg, "output_mode", None)
    mode_value = getattr(output_mode, "value", output_mode)
    if mode_value not in (None, "default"):
        return str(mode_value)
    if getattr(msg, "artifact_id", None):
        return "canvas"
    return "data"


def _structured_payload(msg: AIMessage) -> Dict[str, Any]:
    """Build the (P4-provisional) structured payload for the AgentChat UI.

    ``data`` is passed through :func:`_json_safe` so a pandas frame / dataclass /
    Pydantic model never reaches (and crashes) the broadcast JSON encoder.
    """
    return {
        "response": msg.response,
        "data": _json_safe(msg.data),
        "code": msg.code,
        "artifact_id": getattr(msg, "artifact_id", None),
        "output_mode": getattr(
            getattr(msg, "output_mode", None), "value", None
        ),
        "tool_calls": [
            getattr(tc, "name", None) or getattr(tc, "function", None)
            for tc in (getattr(msg, "tool_calls", None) or [])
        ],
    }


class LiveAvatarAgent(_LiveKitAgent):  # type: ignore[misc,valid-type]
    """LiveKit Agents ``Agent`` whose ``llm_node`` is backed by ai-parrot.

    Args:
        agent_name: Name of the ai-parrot agent that acts as the brain.
        session_id: AgentChat conversation id shared with the avatar turn; used
            both as the ``ask_stream`` session and the output-bridge channel.
        bot_resolver: Async callable ``agent_name -> bot`` (the bot must expose
            ``ask_stream``). Injected to avoid coupling to the server package.
        output_bridge: Bridge that publishes structured outputs to the UI.
        tenant_id: Optional tenant identifier (logged; avatar is opt-in per
            tenant). Not a parameter of ``ask_stream``.
        flattener_factory: Callable returning a fresh
            :class:`SpeakableFlattener` per turn. Defaults to the class itself.
        filler_text: Utterance spoken when a tool turn yields no other speech.
        instructions: Passed to the LiveKit ``Agent`` base when the extra is
            installed; ignored otherwise.
    """

    def __init__(
        self,
        *,
        agent_name: str,
        session_id: str,
        bot_resolver: BotResolver,
        output_bridge: OutputBridge,
        tenant_id: Optional[str] = None,
        flattener_factory: Callable[[], SpeakableFlattener] = SpeakableFlattener,
        filler_text: str = DEFAULT_FILLER_TEXT,
        instructions: str = "",
        **kwargs: Any,
    ) -> None:
        if _HAS_LIVEKIT_AGENTS:
            super().__init__(instructions=instructions, **kwargs)
        self._agent_name = agent_name
        self._session_id = session_id
        self._resolve_bot = bot_resolver
        self._bridge = output_bridge
        self._tenant_id = tenant_id
        self._flattener_factory = flattener_factory
        self._filler_text = filler_text
        self.logger = logging.getLogger(__name__)

    async def llm_node(
        self, chat_ctx: Any, tools: Any, model_settings: Any
    ) -> AsyncGenerator[str, None]:
        """LiveKit ``llm_node`` override: stream ai-parrot speech to the TTS node.

        Yields plain ``str`` sentences (consumed by LiveKit's TTS node). The
        ``tools`` / ``model_settings`` arguments are part of the LiveKit
        contract and are intentionally unused — tool execution lives in
        ai-parrot.
        """
        async for sentence in self._stream_response(chat_ctx):
            yield sentence

    async def _stream_response(self, chat_ctx: Any) -> AsyncGenerator[str, None]:
        """Core, livekit-independent streaming bifurcation (unit-testable)."""
        user_text = _last_user_text(chat_ctx)
        if not user_text:
            self.logger.warning(
                "llm_node called with empty user text; agent=%s session=%s",
                self._agent_name,
                self._session_id,
            )
            return

        bot = await self._resolve_bot(self._agent_name)
        flattener = self._flattener_factory()
        spoke = False

        self.logger.debug(
            "llm_node turn: agent=%s session=%s tenant=%s user_text=%r",
            self._agent_name,
            self._session_id,
            self._tenant_id,
            user_text,
        )

        try:
            async for chunk in bot.ask_stream(
                question=user_text, session_id=self._session_id
            ):
                if isinstance(chunk, str):
                    for sentence in flattener.feed(chunk):
                        spoke = True
                        yield sentence
                    continue

                # Final AIMessage sentinel — bifurcate structured vs speech.
                if _is_structured(chunk):
                    # A UI-bridge failure must not silence the avatar's speech.
                    try:
                        await self._bridge.publish(
                            StructuredOutputMessage(
                                type=_classify(chunk),
                                session_id=self._session_id,
                                payload=_structured_payload(chunk),
                                turn_id=getattr(chunk, "artifact_id", None),
                            )
                        )
                    except Exception:  # noqa: BLE001 - bridge errors are non-fatal
                        self.logger.exception(
                            "OutputBridge.publish failed; type=%s session=%s",
                            _classify(chunk),
                            self._session_id,
                        )

                if getattr(chunk, "tool_calls", None):
                    # Tool turn: avoid dead air if nothing was spoken.
                    if not spoke:
                        spoke = True
                        yield self._filler_text
                elif not spoke and chunk.response:
                    # Non-streamed block response — speak it now.
                    for sentence in flattener.feed(chunk.response):
                        spoke = True
                        yield sentence
        except Exception:
            self.logger.exception(
                "ask_stream failed; agent=%s session=%s",
                self._agent_name,
                self._session_id,
            )
            raise

        # Flush the buffered tail on NORMAL completion only. This is
        # deliberately NOT in a ``finally``: yielding while the generator is
        # being closed (barge-in / ``aclose()``) raises GeneratorExit.
        for sentence in flattener.flush():
            yield sentence
