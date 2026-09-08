"""
VoiceChatHandler - WebSocket Handler with Authentication

Enhanced WebSocket handler for voice chat with:
- JWT authentication via Sec-WebSocket-Protocol (pre-connection)
- JWT authentication via message type (post-connection)
- Configurable route setup via setup_routes()
- Heartbeat/ping mechanism

This handler ONLY handles WebSocket transport.
It does NOT know about Google/Gemini - all voice logic
is encapsulated in VoiceBot/GeminiLiveClient.
"""

from __future__ import annotations
import asyncio
import base64
import binascii
import contextlib
import json
import re
import uuid
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    TYPE_CHECKING,
    Union,
)
from aiohttp import web, WSMsgType
from navconfig.logging import logging

if TYPE_CHECKING:
    # Type-check-only import — VoiceProvider itself has no optional runtime
    # dependencies, but this keeps the module-scope import list minimal and
    # matches the lazy-import style used for NovaClient/GeminiLiveClient
    # in resolve_voice_client_class() below.
    # FEAT-416 (TASK-2152): import the unified VoiceProvider from core —
    # parrot.voice.models.VoiceProvider is now just a re-export of this.
    from parrot.models.voice import VoiceProvider

# Type hints for optional imports
try:
    from parrot.bots.voice import VoiceBot, create_voice_bot
    from parrot.models.voice import VoiceConfig

    # FEAT-416 (TASK-2152): VoiceSession (TASK-2149) replaces the inlined
    # turn lifecycle previously in _run_voice_session().
    from parrot.voice.session import VoiceSession
except ImportError:
    VoiceBot = Any
    VoiceConfig = Any
    VoiceSession = Any
    create_voice_bot = None


# Filters internal "thinking" text that sometimes leaks into the model's
# output (e.g. "**Clarifying...**", "**Show Product Image**"). Shared by
# _send_voice_response() and _HandlerVoiceSession.build_frames() so both
# frame-construction paths filter identically (FEAT-418, TASK-2174).
_THOUGHT_FILTER_PATTERN = re.compile(r"^\s*(?:(\*\*|##)?\s*[A-Z][a-z]+ing\b|(\*\*|##)\s*Show\s+[A-Z])")

# ── FEAT-537: moderated broadcast control socket ────────────────────────────

#: Participant control/input route.  Credentials never appear in the path —
#: only the agent and broadcast ids, which are not secrets (a share link
#: carries the broadcast id and nothing else, spec §2).
def _public_broadcast_message(exc: BaseException) -> str:
    """Return the only failure text that may cross the client boundary.

    ``BroadcastError.message`` is explicitly operator-facing
    (``broadcast/errors.py``: "Never returned to a client verbatim — the client
    sees ``reason`` and ``status``"), and it embeds internals such as version
    numbers and epoch values.  The HTTP surface already emits only
    ``reason.value``; this keeps the WebSocket surface identical rather than
    letting the same failure be more revealing over one transport than the
    other.

    Args:
        exc: The exception being reported.

    Returns:
        The sanitized reason code, or a generic string when the exception
        carries no public reason at all.
    """
    reason = getattr(exc, "reason", None)
    value = getattr(reason, "value", None)
    return value if isinstance(value, str) and value else "request rejected"


BROADCAST_WS_ROUTE: str = "/ws/voice/broadcast/{agent_id}/{broadcast_id}"

#: Close codes for the broadcast socket.
WS_CLOSE_UNAUTHENTICATED: int = 4401
WS_CLOSE_FORBIDDEN: int = 4403

#: How long a socket may stay unattached before it is closed.
BROADCAST_ATTACH_TIMEOUT_S: float = 10.0

#: Largest accepted base64 audio payload per message.
BROADCAST_MAX_AUDIO_B64_BYTES: int = 64 * 1024

#: Per-socket message rate ceiling.
BROADCAST_MAX_MSGS_PER_SECOND: int = 50


# =============================================================================
# Authentication
# =============================================================================
# AuthenticatedUser and TokenValidator are shared WebSocket auth infrastructure
# and now live in the dependency-light parrot.core.ws_auth module, so any WS
# service can authenticate without pulling in the VoiceBot / Gemini Live stack.
# Re-exported here for backward compatibility.
from parrot.core.ws_auth import AuthenticatedUser, TokenValidator  # noqa: E402,F401

# =============================================================================
# Provider Resolution (FEAT-302, TASK-1749)
# =============================================================================
# VoiceChatHandler is transport-only (WebSocket) — voice-provider client
# construction has historically been hardcoded to GeminiLiveClient inside
# VoiceBot._resolve_llm_config() (parrot.bots.voice, core ai-parrot). This
# helper is additive: it lets callers resolve the AbstractClient subclass
# for a given VoiceProvider without requiring changes to VoiceBot's
# existing (GeminiLiveClient-only) resolution path. Full end-to-end
# provider-aware VoiceBot wiring is out of scope here — see spec Module 8.


def resolve_voice_client_class(provider: "VoiceProvider"):
    """Resolve the ``AbstractClient`` subclass for a given ``VoiceProvider``.

    Recognizes ``VoiceProvider.NOVA`` and returns
    :class:`~parrot.clients.amazon.nova.NovaClient` (lazily imported — the
    Pre-Alpha ``aws_sdk_bedrock_runtime`` extra is optional and is only
    required at first ``stream_voice()`` call, not at import time). Every
    other currently-declared provider resolves to
    :class:`~parrot.clients.google.live.GeminiLiveClient`, the only fully-wired
    voice client at this time (``OPENAI_REALTIME`` / ``WHISPER_TTS`` are
    declared in the enum but not yet backed by dedicated client classes).

    Args:
        provider: The ``VoiceProvider`` enum member to resolve.

    Returns:
        The ``AbstractClient`` subclass to instantiate for *provider*.

    Raises:
        ImportError: When ``NOVA`` is requested and
            ``aws_sdk_bedrock_runtime`` (Pre-Alpha, Python >= 3.12 only) is
            not installed and ``stream_voice()`` is called — importing
            :class:`NovaClient` itself never requires it.
    """
    # FEAT-416 (TASK-2152): import the unified VoiceProvider from core.
    from parrot.models.voice import VoiceProvider as _VoiceProvider

    if provider == _VoiceProvider.NOVA:
        from parrot.clients.amazon.nova import NovaClient

        return NovaClient

    from parrot.clients.google.live import GeminiLiveClient

    return GeminiLiveClient


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class BotConfig:
    """Configuration for VoiceBot creation."""

    name: str = "Voice Assistant"
    voice_name: str = "Puck"
    language: str = "en-US"
    system_prompt: Optional[str] = None
    tools: Optional[List[Any]] = None
    voice_config: Optional[VoiceConfig] = None

    # Additional client configuration — Gemini / VertexAI
    api_key: Optional[str] = None
    vertexai: bool = False
    project: Optional[str] = None
    location: Optional[str] = None
    credentials_file: Optional[str] = None

    # Nova / Bedrock (FEAT-315 — required for VoiceBot to forward AWS
    # credentials to NovaClient; without these the SDK falls back to its
    # default credential chain which may resolve to the wrong identity).
    aws_access_key: Optional[str] = None
    aws_secret_key: Optional[str] = None
    aws_id: Optional[str] = None
    region: Optional[str] = None
    region_prefix: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        result = {}
        for key, value in asdict(self).items():
            if value is not None:
                result[key] = value
        return result

    def merge_with(self, overrides: Dict[str, Any]) -> "BotConfig":
        """Create new BotConfig with overrides applied."""
        current = asdict(self)
        current.update(overrides)
        return BotConfig(**{k: v for k, v in current.items() if k in BotConfig.__dataclass_fields__})

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotConfig":
        """Create BotConfig from dictionary."""
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)


# =============================================================================
# Connection State
# =============================================================================


@dataclass
class WebSocketConnection:
    """Represents an active WebSocket connection with auth state."""

    ws: web.WebSocketResponse
    session_id: str
    created_at: datetime = field(default_factory=datetime.now)

    # Authentication state
    authenticated: bool = False
    user: Optional[AuthenticatedUser] = None

    # Legacy user_id support (will use user.user_id if authenticated)
    _user_id: Optional[str] = None

    @property
    def user_id(self) -> Optional[str]:
        """Get user ID from authenticated user or legacy field."""
        if self.user:
            return self.user.user_id
        return self._user_id

    @user_id.setter
    def user_id(self, value: Optional[str]):
        self._user_id = value

    # Bot associated with this connection
    bot: Optional[VoiceBot] = None

    # Streaming mode configuration
    # "streaming" = real-time bidirectional (default)
    # "buffered" = collect complete audio, process, return complete response
    streaming_mode: str = "streaming"

    # Recording state
    is_recording: bool = False
    recording_start_time: Optional[datetime] = None
    session_active: bool = False
    stop_audio_sending: bool = False
    gemini_responding: bool = False

    # Audio buffer for non-streaming mode
    audio_buffer: bytes = b""

    # Audio queue for streaming mode
    audio_queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    # Voice session task
    voice_task: Optional[asyncio.Task] = None

    # FEAT-416 (TASK-2152): the VoiceSession managing this connection's
    # turn lifecycle (start_turn/push_audio/end_turn/close/reconnection).
    # Created in _handle_start_session(), consumed by
    # _handle_start_recording()/_handle_audio_data()/_handle_stop_recording().
    voice_session: Optional["VoiceSession"] = None

    # Shutdown event
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)

    # Configuration
    config: Optional[BotConfig] = None

    # STT-only mode (FEAT-257): when True, Gemini transcribes input but does not
    # generate a model response.  response_chunk / model audio frames are suppressed.
    stt_only: bool = False

    # Ping tracking
    last_ping: Optional[datetime] = None
    ping_count: int = 0

    # Avatar session (FEAT-245): optional LiveAvatar LITE mouth driven by Gemini audio.
    # Type is Optional[Any] to avoid importing the liveavatar stack at module level
    # (lazy import so /ws/voice works without the ai-parrot-integrations[liveavatar] extra).
    avatar_session: Optional[Any] = None

    # FEAT-536 TASK-2942: per-connection tool-call dedup bookkeeping for
    # the direct _send_voice_response() streaming path (_handle_send_text)
    # — equivalent to _HandlerVoiceSession's own turn_no-keyed bookkeeping,
    # since that path has no session object to carry it on. Keyed by
    # response.turn_id (that path's only available turn-boundary marker)
    # so IDs may legitimately be reused in a later turn; naturally reset
    # on session close since a new WebSocketConnection is created per
    # connection.
    _tool_dedup_turn_id: Optional[str] = None
    _sent_tool_call_ids: set = field(default_factory=set)


# =============================================================================
# VoiceSession relay adapter (FEAT-416 TASK-2152; re-based on the
# build_frames() hook, FEAT-418 TASK-2174)
# =============================================================================
# VoiceSession's own _relay() (parrot.voice.session, TASK-2149) used to
# build a generic, minimal frame vocabulary the handler's real,
# ALREADY-SHIPPED WebSocket protocol (response_chunk/transcription/
# response_complete/ready_to_speak/display_data/session_warning, STT-only
# gating, "thought" text filtering, the LiveAvatar audio tee) couldn't
# reproduce without dropping information. TASK-2152 worked around that by
# overriding BOTH `_relay()` (delegating to `_send_voice_response()`) AND
# duplicating `_run_turn()`'s entire reconnection loop, purely so the turn
# could be driven through `VoiceBot.ask_stream()` (conversation-memory
# persistence, dynamic system-prompt building, `stt_only` — all
# VoiceBot-level features `VoiceSession.client.stream_voice()` alone
# cannot provide) instead of `self.client.stream_voice()` directly.
#
# FEAT-418 (TASK-2174) removes both workarounds:
#   1. `build_frames()` (TASK-2171's relay extension hook) now reproduces
#      the handler's real frame protocol directly, so `_run_turn()` no
#      longer needs re-implementing to reach a custom `_relay()` — this
#      class overrides `build_frames()` (sync) instead. The LiveAvatar
#      audio tee is async, so it stays in a (now cooperative, calling
#      `super()._relay()`) `_relay()` override — `build_frames()` cannot
#      `await` it.
#   2. `client` is now `_AskStreamVoiceClient` (below), a tiny adapter
#      presenting `VoiceBot.ask_stream()` as `VoiceCapable.stream_voice()`
#      so the now-INHERITED `_run_turn()` (TASK-2150's reconnection loop,
#      unmodified) drives turns through the bot — preserving conversation
#      memory and dynamic system-prompt building without needing its own
#      copy of the reconnection loop. `stt_only` threads through
#      `VoiceSession.__init__`'s `stt_only` parameter (TASK-2172), which
#      `to_stream_options()` projects into `options.stt_only`.
#
# Net result: `_HandlerVoiceSession` no longer defines `_run_turn` at
# all — `voice/session.py`'s loop is the only reconnection loop in the
# codebase, satisfied literally, not just in spirit.
class _AskStreamVoiceClient:
    """Adapts ``VoiceBot.ask_stream()`` to the ``VoiceCapable.stream_voice()``
    shape (FEAT-418, TASK-2174).

    ``VoiceSession``'s inherited ``_run_turn()`` calls
    ``self.client.stream_voice(...)``. Passing the raw provider client
    (``bot._llm``) there would bypass ``VoiceBot`` entirely — losing
    conversation-memory persistence and dynamic system-prompt building
    (KB/vector/user context), both of which ``VoiceChatHandler`` relies on
    today (it explicitly configures ``conversation_memory`` on the bot
    before starting a session — see ``_handle_start_session()`` — *because*
    ``ask_stream()`` is what persists turns). This adapter is the glue that
    lets the turn still flow through the bot while ``VoiceSession`` itself
    stays a thin, provider-agnostic lifecycle manager.
    """

    def __init__(self, bot: "VoiceBot", user_id: Optional[str] = None):
        self._bot = bot
        self._user_id = user_id

    def set_user_id(self, user_id: Optional[str]) -> None:
        """Re-bind the principal every subsequent turn runs as (FEAT-537).

        A broadcast keeps one bot and one conversation while the speaking floor
        moves between participants, so the identity the bot resolves tool
        permissions and context from must be settable per turn.  Without this
        the whole broadcast would run as whoever happened to start it, silently
        lending that user's privileges to every later speaker (spec §2).

        Args:
            user_id: The current speaker's authenticated user id, or ``None``.
        """
        self._user_id = user_id

    @property
    def voice_capabilities(self):
        """Delegates to the underlying raw client's descriptor — required
        by ``VoiceSession.__init__``'s capability preflight (TASK-2172)."""
        return self._bot._llm.voice_capabilities

    async def stream_voice(
        self,
        audio_iterator,
        system_prompt=None,
        session_id=None,
        user_id=None,
        options=None,
        **kwargs,
    ):
        """Delegates to ``VoiceBot.ask_stream()``.

        ``VoiceBot`` builds its own dynamic ``system_prompt`` internally
        (KB/vector/conversation context) — the ``system_prompt`` argument
        here (``VoiceSession.system_prompt``, a static value) is
        intentionally NOT forwarded, matching the pre-TASK-2174 behavior
        where the duplicated ``_run_turn()`` called ``bot.ask_stream()``
        the same way. ``stt_only`` is read off ``options`` (projected by
        ``VoiceSession`` from its own ``stt_only`` constructor parameter,
        TASK-2172) since ``ask_stream()`` takes it as a dedicated
        parameter, not part of an options object.
        """
        stt_only = options.stt_only if options is not None else False
        async for response in self._bot.ask_stream(
            audio_input=audio_iterator,
            session_id=session_id,
            user_id=user_id or self._user_id,
            stt_only=stt_only,
        ):
            yield response


@dataclass
class _BroadcastSocketState:
    """Per-socket state for one broadcast participant (FEAT-537).

    Deliberately separate from :class:`WebSocketConnection`: a broadcast socket
    owns no bot, no conversation and no avatar session — those belong to the
    broadcast — so reusing the single-user connection's fields would invite
    exactly the connection-owns-the-producer coupling spec §2 removes.

    Attributes:
        socket_id: Unique id of this socket; also the microphone-binding key.
        agent_id: Agent from the route.
        broadcast_id: Broadcast from the route.
        ws: The WebSocket response.
        connection: A minimal ``WebSocketConnection`` kept in
            ``handler.connections`` so shutdown cleanup still sees this socket.
        principal: The scoped principal resolved from the authenticated user.
        lease_id: The admitted lease this socket speaks for, once attached.
        attached: Whether the mandatory ``attach`` handshake completed.
        bound: Whether this socket currently holds the microphone binding.
        rejected_frames: Count of unauthorized/stale input frames dropped.
        speaker_input: The local or relayed sink this socket feeds, once it has
            started recording.
    """

    socket_id: str
    agent_id: str
    broadcast_id: str
    ws: Any
    connection: Any
    principal: Any = None
    lease_id: Optional[str] = None
    attached: bool = False
    bound: bool = False
    rejected_frames: int = 0
    speaker_input: Any = None
    _message_times: List[float] = field(default_factory=list)

    def allow_message(self) -> bool:
        """Sliding-window rate limit for this socket.

        Returns:
            ``False`` when the socket exceeded
            :data:`BROADCAST_MAX_MSGS_PER_SECOND` in the last second.
        """
        now = time.monotonic()
        self._message_times = [t for t in self._message_times if now - t < 1.0]
        if len(self._message_times) >= BROADCAST_MAX_MSGS_PER_SECOND:
            return False
        self._message_times.append(now)
        return True

    async def push(self, frame: Dict[str, Any]) -> None:
        """Send one server-initiated frame to this participant.

        Failures are swallowed: a control notification is advisory and the
        durable state remains authoritative (spec §2).

        Args:
            frame: The frame to send.
        """
        if self.ws.closed:
            return
        with contextlib.suppress(Exception):
            await self.ws.send_json(frame)


@dataclass
class ToolCallDedupState:
    """Per-turn ``tool_call`` de-duplication bookkeeping.

    A streamed delta and the final completion snapshot carry the SAME
    :class:`LiveToolCall` objects (FEAT-536 TASK-2940/2941 arrival-order
    accumulation), so without this every already-relayed id would be emitted
    again on ``is_complete``.  Keyed by ``turn_no`` so ids may legitimately be
    reused in a LATER turn.

    Extracted from ``_HandlerVoiceSession`` (FEAT-537 TASK-2959) so the
    broadcast relay shares one implementation with the single-user path
    instead of growing a near-copy that can drift.

    Attributes:
        turn_no: The turn the current ``sent_ids`` belong to.
        sent_ids: Tool-call ids already emitted this turn.
    """

    turn_no: Optional[int] = None
    sent_ids: set = field(default_factory=set)

    def reset_if_new_turn(self, turn_no: int) -> None:
        """Clear the id set when the turn number changes.

        Args:
            turn_no: The turn being relayed.
        """
        if turn_no != self.turn_no:
            self.turn_no = turn_no
            self.sent_ids = set()


def build_voice_frames(
    resp: Any,
    turn_no: int,
    *,
    stt_only: bool,
    dedup_state: ToolCallDedupState,
) -> list:
    """Translate one ``LiveVoiceResponse`` into VoiceChatHandler wire frames.

    This is the single, pure implementation of the handler's rich frame
    protocol (FEAT-418 TASK-2174): ``response_chunk`` / ``transcription`` /
    ``display_data`` / ``tool_call`` / ``response_complete`` / ``ready_to_speak``,
    plus the ``go_away`` → ``session_warning`` mapping, with STT-only gating and
    "thought" text filtering.

    Both :class:`_HandlerVoiceSession` (single user) and the broadcast relay
    call it, so the two paths cannot drift apart in what a browser receives.
    The broadcast relay strips ``audio_base64`` from the result afterwards —
    its PCM goes to the shared room, not down each participant's socket.

    Must stay **sync**: the base ``VoiceSession._relay()`` calls
    ``build_frames()`` without awaiting.

    Args:
        resp: The provider response to translate.
        turn_no: Current turn number.
        stt_only: Whether the session is transcription-only.
        dedup_state: Mutable per-turn tool-call dedup bookkeeping.

    Returns:
        JSON-serializable frame dicts, in send order.
    """
    dedup_state.reset_if_new_turn(turn_no)

    frames: list = []

    if not stt_only:
        is_thought = bool(resp.text and _THOUGHT_FILTER_PATTERN.match(resp.text))
        text_to_send = "" if is_thought else resp.text
        if (resp.audio_data or text_to_send) and not resp.is_complete:
            frames.append(
                {
                    "type": "response_chunk",
                    "text": text_to_send or "",
                    "audio_base64": base64.b64encode(resp.audio_data).decode() if resp.audio_data else "",
                    "audio_format": "audio/pcm;rate=24000" if resp.audio_data else "",
                    "is_interrupted": resp.is_interrupted,
                }
            )

    # User transcription is always forwarded (both modes) — canonical
    # role replaces the removed metadata["user_transcription"] key.
    if resp.role == "user" and resp.text:
        frames.append(
            {
                "type": "transcription",
                "text": resp.text,
                "is_user": True,
            }
        )

    # Everything below this point is model-response output — skip in
    # STT-only mode (matches _send_voice_response()'s early return).
    if not stt_only:
        # Forward the assistant's spoken text as the display bubble.
        # canonical role="assistant" replaces the removed
        # metadata["assistant_transcription"] key; turn_metadata's own
        # output_transcription remains as a fallback for a frame that
        # carries no text of its own (e.g. an audio-only chunk).
        assistant_text = resp.text if resp.role == "assistant" else None
        if not assistant_text and resp.turn_metadata:
            assistant_text = resp.turn_metadata.output_transcription
        if assistant_text:
            frames.append(
                {
                    "type": "transcription",
                    "text": assistant_text,
                    "is_user": False,
                }
            )

        if resp.metadata.get("display_data"):
            frames.append(
                {
                    "type": "display_data",
                    "data": resp.metadata["display_data"],
                }
            )

        for tc in resp.tool_calls:
            if tc.id in dedup_state.sent_ids:
                continue
            dedup_state.sent_ids.add(tc.id)
            frames.append(
                {
                    "type": "tool_call",
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "result": tc.result,
                    "execution_time_ms": tc.execution_time_ms,
                }
            )

        if resp.is_complete:
            final_text = resp.text
            if final_text and _THOUGHT_FILTER_PATTERN.match(final_text):
                final_text = ""
            response_complete_frame = {
                "type": "response_complete",
                "text": final_text or "",
                "is_interrupted": resp.is_interrupted,
            }
            # FEAT-418 (TASK-2178): surface per-turn token/latency
            # counters on the streaming path — mirrors the shape
            # _send_complete_voice_response() already sends on the
            # non-streaming path (input_tokens/output_tokens/
            # total_tokens), plus the timing fields LiveCompletionUsage
            # already computes (response_time_ms/first_token_time_ms),
            # so the dual-provider example can render a live counter
            # per provider without fabricating data client-side.
            if resp.usage:
                response_complete_frame["usage"] = {
                    "input_tokens": resp.usage.prompt_tokens,
                    "output_tokens": resp.usage.completion_tokens,
                    "total_tokens": resp.usage.total_tokens,
                    "response_time_ms": resp.usage.response_time_ms,
                    "first_token_time_ms": resp.usage.first_token_time_ms,
                }
            frames.append(response_complete_frame)
            frames.append(
                {
                    "type": "ready_to_speak",
                    "message": "Ready for new question",
                }
            )

    # Gemini's GoAway signal is distinct from reconnect_required and,
    # by itself, is not understood by VoiceSession's (inherited,
    # unmodified) reconnection loop. Mutating resp.metadata here is
    # safe: build_frames() runs (via _relay()) BEFORE _run_turn()
    # checks resp.metadata.get("reconnect_required") (spec §7 relay-
    # before-reconnect ordering). As of TASK-2168, Gemini's own
    # producer already sets reconnect_required alongside go_away — this
    # mutation is now a defensive no-op for Gemini and a safety net for
    # any future provider that emits go_away without it.
    if resp.metadata.get("go_away"):
        frames.append(
            {
                "type": "session_warning",
                "message": "Session reconnecting...",
            }
        )
        resp.metadata["reconnect_required"] = True

    return frames


class _HandlerVoiceSession(VoiceSession):
    """VoiceSession that relays through VoiceChatHandler's existing,
    richer WebSocket frame protocol instead of VoiceSession's own."""

    def __init__(self, *args, handler: "VoiceChatHandler", connection: "WebSocketConnection", **kwargs):
        super().__init__(*args, **kwargs)
        self._handler = handler
        self._connection = connection
        # FEAT-536 TASK-2942 (spec §2 "Event delivery and completion
        # snapshots"): per-turn dedup bookkeeping — the streamed delta and
        # the final Python completion snapshot both carry the SAME
        # LiveToolCall objects (arrival-order accumulation, TASK-2940/
        # 2941), so build_frames() would otherwise emit a duplicate
        # tool_call wire frame for every already-relayed id. Keyed by
        # turn_no (not a single running set) so IDs may legitimately be
        # reused in a LATER turn — reset happens naturally at a turn
        # boundary in build_frames() below; "session close" reset is
        # satisfied by this being a fresh instance per session (a new
        # _HandlerVoiceSession is constructed per voice session, never
        # reused across sessions).
        self._dedup_state = ToolCallDedupState()
        self._tool_dedup_turn_no: Optional[int] = None
        self._sent_tool_call_ids: set = set()

    async def _send(self, payload: dict) -> None:
        # Code-review fix: route through the handler's own _send_message()
        # (blanket try/except + logged failure) instead of the inherited
        # VoiceSession._send(), which only suppresses ConnectionResetError
        # — keeps error/reconnect frames on the exact same safety net as
        # every other frame this handler sends.
        await self._handler._send_message(self._connection.ws, payload)

    def build_frames(self, resp, turn_no: int) -> list:
        """Reproduce VoiceChatHandler's real WebSocket frame protocol.

        Thin wrapper over the module-level :func:`build_voice_frames` (the
        pure implementation, extracted by FEAT-537 TASK-2959 so the broadcast
        relay shares it). Dedup state stays on the instance because a fresh
        ``_HandlerVoiceSession`` is constructed per voice session and must
        never carry ids across sessions.

        Args:
            resp: The provider response to translate.
            turn_no: The current turn number.

        Returns:
            A list of JSON-serializable frame dicts, in send order.
        """
        frames = build_voice_frames(
            resp,
            turn_no,
            stt_only=self._connection.stt_only,
            dedup_state=self._dedup_state,
        )
        # Kept in sync for backwards compatibility: these two attributes were
        # public-ish instance state before the extraction and are read by
        # existing tests and by _send_voice_response()'s own dedup path.
        self._tool_dedup_turn_no = self._dedup_state.turn_no
        self._sent_tool_call_ids = self._dedup_state.sent_ids
        return frames

    async def _relay(self, resp, turn_no: int) -> None:
        """Send build_frames()'s output, then run the LiveAvatar audio tee.

        The tee is async (awaits connection.avatar_session.speak()/
        interrupt()/finish_turn()) so it cannot live in the sync
        build_frames() — kept here, cooperating with the base class via
        super()._relay() rather than re-implementing frame sending.
        """
        await super()._relay(resp, turn_no)

        # ── Avatar audio tee (FEAT-245) ───────────────────────────────
        # Best-effort: exceptions are caught and logged; the browser audio
        # path MUST NOT be interrupted by an avatar hiccup (dual audio).
        # Skipped in STT-only mode, matching _send_voice_response()'s
        # early return (the avatar tee is unreachable there too).
        connection = self._connection
        if connection.stt_only or connection.avatar_session is None:
            return
        try:
            if resp.is_interrupted:
                await connection.avatar_session.interrupt()
            else:
                if resp.audio_data:
                    await connection.avatar_session.speak(resp.audio_data)
                if resp.is_complete:
                    await connection.avatar_session.finish_turn()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("VoiceChatHandler: avatar tee error (voice stream unaffected): %s", exc)


# =============================================================================
# Main Handler
# =============================================================================


class VoiceChatHandler:
    """
    WebSocket handler for voice chat with authentication support.

    Features:
    - Pre-connection auth via Sec-WebSocket-Protocol header
    - Post-connection auth via 'auth' message type
    - Configurable route setup
    - Heartbeat/ping mechanism

    Authentication Methods:

    1. Sec-WebSocket-Protocol (recommended for browsers):
       ```javascript
       // Frontend
       const ws = new WebSocket(url, ["jwt", token]);
       ```

    2. Query parameter:
       ```javascript
       const ws = new WebSocket(`${url}?token=${token}`);
       ```

    3. Post-connection message:
       ```javascript
       ws.send(JSON.stringify({type: "auth", token: "..."}));
       ```

    Usage:
        handler = VoiceChatHandler(
            bot_factory=lambda: create_voice_bot(name="Assistant"),
            require_auth=True,
        )

        # Option 1: Setup routes
        handler.setup_routes(app, prefix="/api/v1")

        # Option 2: Direct route
        app.router.add_get('/ws/voice', handler.handle_websocket)
    """

    def __init__(
        self,
        bot_factory: Optional[Callable[[], VoiceBot]] = None,
        default_config: Optional[Union[BotConfig, Dict[str, Any]]] = None,
        *,
        # Authentication options
        require_auth: bool = False,
        token_validator: Optional[TokenValidator] = None,
        secret_key: Optional[str] = None,
        auth_timeout: float = 30.0,
        # Route options
        ws_route: str = "/ws/voice",
        health_route: str = "/health",
        # FEAT-537 — moderated multi-browser broadcast
        broadcast_service: Optional[Any] = None,
        nova_bot_factory: Optional[Callable[[], "VoiceBot"]] = None,
    ):
        """
        Initialize handler.

        Args:
            bot_factory: Factory for creating VoiceBot instances
            default_config: Default bot configuration
            require_auth: Require authentication before session start
            token_validator: Custom token validator
            secret_key: JWT secret key (if not using navigator_auth)
            auth_timeout: Timeout for post-connection auth (seconds)
            ws_route: WebSocket route path
            health_route: Health check route path
            broadcast_service: FEAT-537 broadcast facade (``BroadcastService``,
                TASK-2961).  Typed loosely on purpose: the handler must not
                hard-import the broadcast package, which pulls in the optional
                LiveKit/Redis stack.  ``None`` disables broadcast mode entirely
                and leaves every existing code path untouched.
            nova_bot_factory: Factory used **only** for broadcasts.  A
                broadcast fixes the provider to Nova for its lifetime (spec
                §2), so it must not reuse ``bot_factory``, which the shared
                example rebinds when the user switches provider in the UI.
        """
        self.bot_factory = bot_factory or self._default_bot_factory

        if isinstance(default_config, BotConfig):
            self.default_config = default_config
        elif isinstance(default_config, dict):
            self.default_config = BotConfig.from_dict(default_config)
        else:
            self.default_config = BotConfig()

        self._current_config: Optional[BotConfig] = None
        self.connections: Dict[str, WebSocketConnection] = {}

        # Authentication
        self.require_auth = require_auth
        self.token_validator = token_validator or TokenValidator(
            secret_key=secret_key,
            allow_anonymous=not require_auth,
        )
        self.auth_timeout = auth_timeout

        # Routes
        self.ws_route = ws_route
        self.health_route = health_route

        # FEAT-537 — broadcast mode (inactive unless a service is injected).
        self.broadcast_service = broadcast_service
        self.nova_bot_factory = nova_bot_factory
        self.ws_broadcast_route = BROADCAST_WS_ROUTE

        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @property
    def broadcast_enabled(self) -> bool:
        """Whether a broadcast service was injected (FEAT-537)."""
        return self.broadcast_service is not None

    def _default_bot_factory(self) -> VoiceBot:
        """Default factory for bots."""
        config = self._current_config or self.default_config
        if create_voice_bot is None:
            raise ImportError("VoiceBot not available")
        return create_voice_bot(**config.as_dict())

    @staticmethod
    def resolve_provider_client(provider: "VoiceProvider"):
        """Resolve the ``AbstractClient`` subclass for *provider* (FEAT-302).

        Thin wrapper around the module-level
        :func:`resolve_voice_client_class` — recognizes
        ``VoiceProvider.NOVA`` and returns
        :class:`~parrot.clients.amazon.nova.NovaClient`.
        """
        return resolve_voice_client_class(provider)

    # =========================================================================
    # Route Setup
    # =========================================================================

    def setup_routes(
        self,
        app: web.Application,
        prefix: str = "",
        *,
        include_health: bool = True,
        include_static: bool = True,
        static_dir: Optional[str] = None,
    ) -> None:
        """
        Register routes on an aiohttp application.

        Args:
            app: aiohttp Application
            prefix: URL prefix for all routes (e.g., "/api/v1")
            include_health: Include health check endpoint
            include_static: Include static file serving
            static_dir: Directory for static files
        """
        # Normalize prefix
        prefix = prefix.rstrip("/")

        # WebSocket route
        ws_path = f"{prefix}{self.ws_route}"
        app.router.add_get(ws_path, self.handle_websocket)
        self.logger.info("WebSocket route registered: %s", ws_path)

        # FEAT-537: the moderated broadcast control/input socket. Mounted ONLY
        # when a broadcast service was injected, so an ordinary voice
        # deployment exposes exactly the routes it did before.
        if self.broadcast_enabled:
            broadcast_ws_path = f"{prefix}{self.ws_broadcast_route}"
            app.router.add_get(broadcast_ws_path, self.handle_broadcast_websocket)
            self.logger.info(
                "Broadcast WebSocket route registered: %s", broadcast_ws_path
            )

        # Health check
        if include_health:
            health_path = f"{prefix}{self.health_route}"
            app.router.add_get(health_path, self._handle_health)
            self.logger.info("Health route registered: %s", health_path)

        # Static files
        if include_static and static_dir:
            from pathlib import Path

            static_path = Path(static_dir)
            if static_path.exists():
                app.router.add_static(f"{prefix}/static", static_path)
                self.logger.info("Static route registered: %s/static", prefix)

        # Store reference in app
        app["voice_handler"] = self

        # Cleanup on shutdown
        app.on_cleanup.append(self._cleanup_all_connections)

        self.logger.info(
            f"VoiceChatHandler mounted at {prefix or '/'} " f"(auth={'required' if self.require_auth else 'optional'})"
        )

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response(
            {
                "status": "ok",
                "active_connections": len(self.connections),
                "authenticated_connections": sum(1 for c in self.connections.values() if c.authenticated),
                "timestamp": datetime.now().isoformat(),
            }
        )

    async def _cleanup_all_connections(self, app: web.Application) -> None:
        """Cleanup all connections on app shutdown."""
        for connection in list(self.connections.values()):
            await self._cleanup_connection(connection)

    # =========================================================================
    # Authentication
    # =========================================================================

    async def _authenticate_from_protocol(
        self, request: web.Request
    ) -> tuple[Optional[str], Optional[AuthenticatedUser]]:
        """
        Extract and validate JWT from Sec-WebSocket-Protocol header.

        The browser sends: new WebSocket(url, ["jwt", token])
        Header received: Sec-WebSocket-Protocol: jwt, <token>

        Returns:
            Tuple of (selected_protocol, authenticated_user)
        """
        protocol_header = request.headers.get("Sec-WebSocket-Protocol")
        if not protocol_header:
            return None, None

        parts = [p.strip() for p in protocol_header.split(",")]

        # Check if using JWT protocol
        if "jwt" not in parts:
            return None, None

        # Find token (the part that isn't 'jwt')
        parts_copy = parts.copy()
        parts_copy.remove("jwt")

        if not parts_copy:
            return None, None

        token = parts_copy[0]
        user = await self.token_validator.validate(token)

        if user:
            return "jwt", user
        return None, None

    async def _authenticate_from_query(self, request: web.Request) -> Optional[AuthenticatedUser]:
        """Extract and validate JWT from query parameter."""
        token = request.query.get("token")
        if token:
            return await self.token_validator.validate(token)
        return None

    # =========================================================================
    # WebSocket Handler
    # =========================================================================

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """
        Main WebSocket handler.

        Protocol:

        Client -> Server:
        - {"type": "auth", "token": "<jwt>"}
        - {"type": "start_session", "config": {...}}
        - {"type": "audio_data", "data": "<base64>"}
        - {"type": "start_recording"}
        - {"type": "stop_recording"}
        - {"type": "send_text", "text": "..."}
        - {"type": "end_session"}
        - {"type": "ping"}

        Server -> Client:
        - {"type": "connected", "session_id": "...", "authenticated": bool}
        - {"type": "auth_success", "user": {...}}
        - {"type": "auth_error", "message": "..."}
        - {"type": "session_started", "session_id": "..."}
        - {"type": "voice_response", ...}
        - {"type": "pong", "timestamp": "...", "ping_count": N}
        - {"type": "error", "message": "..."}
        """
        # Try pre-connection authentication
        selected_protocol, pre_auth_user = await self._authenticate_from_protocol(request)

        # Also try query param auth
        if not pre_auth_user:
            pre_auth_user = await self._authenticate_from_query(request)

        # Prepare WebSocket response
        ws = web.WebSocketResponse(
            heartbeat=30.0,
            max_msg_size=10 * 1024 * 1024,  # 10MB for audio
            protocols=[selected_protocol] if selected_protocol else None,
        )
        await ws.prepare(request)

        session_id = str(uuid.uuid4())

        connection = WebSocketConnection(
            ws=ws,
            session_id=session_id,
            authenticated=pre_auth_user is not None,
            user=pre_auth_user,
            _user_id=request.query.get("user_id"),
        )
        self.connections[session_id] = connection

        self.logger.info(f"New WebSocket connection: {session_id} " f"(authenticated={connection.authenticated})")

        try:
            # Send connection confirmation
            await self._send_message(
                ws,
                {
                    "type": "connected",
                    "session_id": session_id,
                    "authenticated": connection.authenticated,
                    "require_auth": self.require_auth and not connection.authenticated,
                },
            )

            # If pre-authenticated, send success
            if connection.authenticated and connection.user:
                await self._send_message(
                    ws,
                    {
                        "type": "auth_success",
                        "user": {
                            "user_id": connection.user.user_id,
                            "username": connection.user.username,
                        },
                    },
                )

            # Process messages
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_message(connection, data)
                    except json.JSONDecodeError:
                        await self._send_error(ws, "Invalid JSON")
                    except Exception as e:
                        self.logger.error("Error handling message: %s", e)
                        await self._send_error(ws, str(e))

                elif msg.type == WSMsgType.BINARY:
                    # Direct binary audio
                    if not connection.is_recording:
                        connection.stop_audio_sending = False
                        connection.gemini_responding = False
                        connection.recording_start_time = datetime.now()
                        connection.audio_buffer = b""  # Reset buffer
                        # FEAT-416 (TASK-2152 code-review fix): mirrors
                        # _handle_audio_data()'s implicit-start-of-turn
                        # handling — this binary path bypasses that
                        # method entirely, so it needs its own start_turn()
                        # for the same auto-start-on-first-chunk case.
                        if connection.streaming_mode == "streaming" and connection.voice_session is not None:
                            await connection.voice_session.start_turn()
                    connection.is_recording = True

                    if connection.session_active and not connection.stop_audio_sending:
                        if connection.streaming_mode == "streaming":
                            # FEAT-416 (TASK-2152 code-review fix): this
                            # path previously queued into
                            # connection.audio_queue, which nothing has
                            # drained since the VoiceSession refactor —
                            # audio sent as raw binary WS frames (rather
                            # than base64-in-JSON via _handle_audio_data())
                            # was being silently dropped. Route through
                            # the same VoiceSession the JSON path uses.
                            if connection.voice_session is not None:
                                await connection.voice_session.push_audio(msg.data)
                        else:
                            # Buffered mode: accumulate audio
                            connection.audio_buffer += msg.data

                elif msg.type == WSMsgType.ERROR:
                    self.logger.error("WebSocket error: %s", ws.exception())

        except asyncio.CancelledError:
            self.logger.info("Connection cancelled: %s", session_id)

        finally:
            await self._cleanup_connection(connection)
            self.connections.pop(session_id, None)
            self.logger.info("Connection closed: %s", session_id)

        return ws

    # =========================================================================
    # FEAT-537 — Broadcast control / input socket
    # =========================================================================

    async def handle_broadcast_websocket(
        self, request: web.Request
    ) -> web.WebSocketResponse:
        """Participant control and microphone socket for one broadcast.

        Route: ``/ws/voice/broadcast/{agent_id}/{broadcast_id}``.

        Every admitted participant opens one of these to *receive* state.  Only
        the participant currently holding the floor may also *send* microphone
        audio, and every such message is re-validated against the live floor
        state before it reaches a provider.  Authentication alone, socket
        possession, being the moderator, or holding a LiveKit viewer token are
        each insufficient (spec §2).

        Client → Server:
            - ``{"type": "attach", "lease_id": "..."}`` — required first message
            - ``{"type": "ping"}`` — control heartbeat, every 5 s
            - ``{"type": "start_session"}`` — attach to the *existing* broadcast
              voice session; never creates a bot
            - ``{"type": "start_recording", "floor_epoch": N}``
            - ``{"type": "audio_data"|"audio_chunk", "data": "<b64>", "floor_epoch": N}``
            - ``{"type": "stop_recording", "floor_epoch": N}``
            - ``{"type": "finish_speaking"}`` — hand the floor back
            - ``{"type": "end_session"}`` — release only this speaking binding

        Server → Client:
            - ``{"type": "attached", "lease_id": ..., "role": ...}``
            - ``{"type": "broadcast_state", "state": {...}}``
            - ``{"type": "floor_state", "granted": bool, "floor_epoch": N}``
            - ``{"type": "floor_revoked", "floor_epoch": N}``
            - ``{"type": "error", "code": "...", "message": "..."}``
            - plus the shared voice frames fanned out by the relay

        Args:
            request: The aiohttp request.

        Returns:
            The prepared WebSocket response.
        """
        service = self.broadcast_service
        if service is None:  # pragma: no cover — route is not mounted then
            raise web.HTTPNotFound()

        agent_id = request.match_info.get("agent_id", "")
        broadcast_id = request.match_info.get("broadcast_id", "")

        # Same authentication as the legacy route. The query-token form is
        # accepted only for parity with /ws/voice; browsers should prefer the
        # Sec-WebSocket-Protocol form, which keeps the token out of URLs and
        # access logs (spec §2: "Keep credentials out of URL query strings").
        selected_protocol, user = await self._authenticate_from_protocol(request)
        if not user:
            user = await self._authenticate_from_query(request)

        ws = web.WebSocketResponse(
            heartbeat=30.0,
            max_msg_size=10 * 1024 * 1024,
            protocols=[selected_protocol] if selected_protocol else None,
        )
        await ws.prepare(request)

        if self.require_auth and user is None:
            await ws.close(
                code=WS_CLOSE_UNAUTHENTICATED, message=b"authentication required"
            )
            return ws

        socket_id = str(uuid.uuid4())
        connection = WebSocketConnection(
            ws=ws,
            session_id=socket_id,
            authenticated=user is not None,
            user=user,
        )
        self.connections[socket_id] = connection

        state = _BroadcastSocketState(
            socket_id=socket_id,
            agent_id=agent_id,
            broadcast_id=broadcast_id,
            ws=ws,
            connection=connection,
        )
        try:
            state.principal = await service.resolve_principal(user, agent_id)
        except Exception as exc:  # noqa: BLE001 — no scope, no socket
            self.logger.warning(
                "broadcast socket %s: principal resolution failed: %s", socket_id, exc
            )
            await ws.close(code=WS_CLOSE_FORBIDDEN, message=b"not authorized")
            self.connections.pop(socket_id, None)
            return ws

        try:
            await self._run_broadcast_socket(service, state)
        except asyncio.CancelledError:
            self.logger.info("broadcast socket %s cancelled", socket_id)
        finally:
            await self._teardown_broadcast_socket(service, state)
            self.connections.pop(socket_id, None)
        return ws

    async def _run_broadcast_socket(
        self, service: Any, state: "_BroadcastSocketState"
    ) -> None:
        """Attach the socket to a lease, then serve its message loop."""
        if not await self._attach_broadcast_socket(service, state):
            return

        async for msg in state.ws:
            if msg.type != WSMsgType.TEXT:
                if msg.type == WSMsgType.ERROR:
                    self.logger.error(
                        "broadcast socket %s error: %s",
                        state.socket_id,
                        state.ws.exception(),
                    )
                # Raw binary audio is deliberately NOT accepted here: it cannot
                # carry a floor_epoch, so it could not be fenced.
                continue
            try:
                message = json.loads(msg.data)
            except json.JSONDecodeError:
                await self._send_broadcast_error(state.ws, "invalid_json", "Invalid JSON")
                continue
            if not state.allow_message():
                await self._send_broadcast_error(
                    state.ws, "rate_limited", "too many messages"
                )
                continue
            try:
                await self._handle_broadcast_message(service, state, message)
            except Exception as exc:  # noqa: BLE001 — one bad message, not the socket
                await self._report_broadcast_error(state, exc)

    async def _attach_broadcast_socket(
        self, service: Any, state: "_BroadcastSocketState"
    ) -> bool:
        """Consume the mandatory ``attach`` message and verify lease ownership.

        Returns:
            ``True`` when the socket is attached and may proceed.
        """
        try:
            msg = await asyncio.wait_for(
                state.ws.receive(), timeout=BROADCAST_ATTACH_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            await state.ws.close(code=WS_CLOSE_FORBIDDEN, message=b"attach timeout")
            return False
        if msg.type != WSMsgType.TEXT:
            await state.ws.close(code=WS_CLOSE_FORBIDDEN, message=b"attach required")
            return False
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            await state.ws.close(code=WS_CLOSE_FORBIDDEN, message=b"attach required")
            return False
        if payload.get("type") != "attach" or not payload.get("lease_id"):
            await state.ws.close(code=WS_CLOSE_FORBIDDEN, message=b"attach required")
            return False

        lease_id = str(payload["lease_id"])
        tenant_id = state.principal.tenant_id
        lease = await service.get_lease(tenant_id, state.broadcast_id, lease_id)
        # A lease id is not a bearer token: it must belong to the authenticated
        # principal. Otherwise anyone who saw a lease id in a log could attach
        # as that participant.
        if lease is None or lease.principal.user_id != state.principal.user_id:
            self.logger.warning(
                "broadcast socket %s: lease %s not owned by %s",
                state.socket_id,
                lease_id,
                state.principal.user_id,
            )
            await state.ws.close(code=WS_CLOSE_FORBIDDEN, message=b"lease not owned")
            return False

        state.lease_id = lease_id
        state.attached = True
        await service.attach_control(
            tenant_id, state.broadcast_id, lease_id, state.push
        )
        await service.heartbeat(tenant_id, state.broadcast_id, lease_id)

        descriptor = await service.get_descriptor(tenant_id, state.broadcast_id)
        await self._send_message(
            state.ws,
            {
                "type": "attached",
                "lease_id": lease_id,
                "broadcast_id": state.broadcast_id,
                "is_moderator": bool(
                    descriptor and descriptor.moderator_lease_id == lease_id
                ),
            },
        )
        await self._push_broadcast_state(service, state)
        return True

    async def _push_broadcast_state(
        self, service: Any, state: "_BroadcastSocketState"
    ) -> None:
        """Send the public projection plus this socket's own floor permission."""
        tenant_id = state.principal.tenant_id
        public = await service.public_state(tenant_id, state.broadcast_id)
        await self._send_message(
            state.ws, {"type": "broadcast_state", "state": public}
        )
        descriptor = await service.get_descriptor(tenant_id, state.broadcast_id)
        if descriptor is None:
            return
        granted = (
            descriptor.speaker_lease_id == state.lease_id
            and descriptor.floor_state.value == "granted"
        )
        # Sent explicitly so the browser gates its microphone on the SERVER's
        # answer, never on a generic ready_to_speak frame (spec §2).
        await self._send_message(
            state.ws,
            {
                "type": "floor_state",
                "granted": granted,
                "floor_epoch": descriptor.floor_epoch,
            },
        )

    async def _handle_broadcast_message(
        self, service: Any, state: "_BroadcastSocketState", message: Dict[str, Any]
    ) -> None:
        """Dispatch one message from an attached broadcast socket."""
        tenant_id = state.principal.tenant_id
        msg_type = message.get("type", "")

        if msg_type == "ping":
            await service.heartbeat(tenant_id, state.broadcast_id, state.lease_id)
            await self._send_message(
                state.ws,
                {"type": "pong", "timestamp": datetime.now().isoformat()},
            )
            return

        if msg_type == "get_state":
            await self._push_broadcast_state(service, state)
            return

        if msg_type == "start_session":
            # Attaches to the EXISTING broadcast voice session. A participant
            # socket never creates a bot or a conversation.
            session = service.voice_session(tenant_id, state.broadcast_id)
            await self._send_message(
                state.ws,
                {
                    "type": "session_started",
                    "broadcast_id": state.broadcast_id,
                    "producer_local": session is not None,
                },
            )
            return

        if msg_type in ("start_recording", "audio_data", "audio_chunk", "stop_recording"):
            await self._handle_broadcast_audio(service, state, msg_type, message)
            return

        if msg_type == "finish_speaking":
            await service.release_floor(
                tenant_id, state.broadcast_id, state.lease_id
            )
            await self._push_broadcast_state(service, state)
            return

        if msg_type == "end_session":
            # Releases only THIS participant's speaking binding. Stopping the
            # broadcast for everyone is the moderator's explicit HTTP stop.
            await self._release_speaking(service, state)
            await self._send_message(state.ws, {"type": "session_ended"})
            return

        self.logger.warning(
            "broadcast socket %s: unknown message type %r", state.socket_id, msg_type
        )

    async def _handle_broadcast_audio(
        self,
        service: Any,
        state: "_BroadcastSocketState",
        msg_type: str,
        message: Dict[str, Any],
    ) -> None:
        """Validate floor authority, then feed the broadcast's voice session.

        Every rejection is counted and dropped locally; a rejected frame is
        never forwarded to a provider and never fanned out to other browsers.
        """
        from parrot.integrations.liveavatar.broadcast.errors import BroadcastError
        from parrot.integrations.liveavatar.broadcast.floor import (
            validate_audio_authority,
        )

        tenant_id = state.principal.tenant_id
        floor_epoch = message.get("floor_epoch")
        descriptor = await service.get_descriptor(tenant_id, state.broadcast_id)
        lease = await service.get_lease(tenant_id, state.broadcast_id, state.lease_id)
        if descriptor is None:
            await self._send_broadcast_error(
                state.ws, "not_found", "broadcast is gone"
            )
            return

        try:
            validate_audio_authority(
                descriptor,
                lease,
                floor_epoch=floor_epoch if isinstance(floor_epoch, int) else None,
                socket_id=state.socket_id,
            )
        except BroadcastError as exc:
            state.rejected_frames += 1
            await self._send_broadcast_error(
                state.ws,
                exc.reason.value if exc.reason else "forbidden",
                _public_broadcast_message(exc),
            )
            return

        if msg_type == "start_recording":
            try:
                await service.bind_speaker_socket(
                    tenant_id,
                    state.broadcast_id,
                    state.lease_id,
                    state.socket_id,
                    descriptor.floor_epoch,
                )
            except BroadcastError as exc:
                state.rejected_frames += 1
                await self._send_broadcast_error(
                    state.ws,
                    exc.reason.value if exc.reason else "forbidden",
                    _public_broadcast_message(exc),
                )
                return
            state.bound = True
            # Release any previous input first. Replacing it in place leaked an
            # aiohttp ClientSession per remote turn and, worse, let two inputs
            # call start_turn() concurrently — two provider streams for one
            # speaker.
            if state.speaker_input is not None:
                with contextlib.suppress(Exception):
                    await state.speaker_input.aclose()
                state.speaker_input = None
            try:
                state.speaker_input = await service.attach_speaker_input(
                    tenant_id,
                    state.broadcast_id,
                    state.lease_id,
                    state.principal,
                    descriptor.floor_epoch,
                )
                await state.speaker_input.start_turn()
            except BroadcastError as exc:
                state.rejected_frames += 1
                await self._send_broadcast_error(
                    state.ws,
                    exc.reason.value if exc.reason else "forbidden",
                    _public_broadcast_message(exc),
                )
                return
            await self._send_message(
                state.ws,
                {"type": "recording_started", "floor_epoch": descriptor.floor_epoch},
            )
            return

        if msg_type == "stop_recording":
            if state.speaker_input is not None:
                await state.speaker_input.end_turn()
            await self._send_message(state.ws, {"type": "recording_stopped"})
            return

        raw = message.get("data", "")
        if not isinstance(raw, str) or not raw:
            state.rejected_frames += 1
            return
        if len(raw) > BROADCAST_MAX_AUDIO_B64_BYTES:
            state.rejected_frames += 1
            await self._send_broadcast_error(
                state.ws, "payload_too_large", "audio payload exceeds the limit"
            )
            return
        try:
            pcm = base64.b64decode(raw)
        except (ValueError, binascii.Error):
            state.rejected_frames += 1
            await self._send_broadcast_error(
                state.ws, "invalid_audio", "audio payload is not valid base64"
            )
            return
        # Cheap, caller-independent validation happens above; only the actual
        # hand-off to the producer needs an established recording turn.
        if state.speaker_input is None:
            state.rejected_frames += 1
            await self._send_broadcast_error(
                state.ws, "floor_not_granted", "send start_recording first"
            )
            return
        await state.speaker_input.push_audio(pcm)

    async def _release_speaking(
        self, service: Any, state: "_BroadcastSocketState"
    ) -> None:
        """Unbind this socket and, if it held the floor, hand it back."""
        if not state.attached or state.lease_id is None:
            return
        tenant_id = state.principal.tenant_id
        if state.speaker_input is not None:
            with contextlib.suppress(Exception):
                await state.speaker_input.aclose()
            state.speaker_input = None
        with contextlib.suppress(Exception):
            await service.unbind_speaker_socket(
                tenant_id, state.broadcast_id, state.lease_id, state.socket_id
            )
        state.bound = False
        descriptor = await self._safe_descriptor(service, state)
        if descriptor is not None and descriptor.speaker_lease_id == state.lease_id:
            with contextlib.suppress(Exception):
                await service.release_floor(
                    tenant_id, state.broadcast_id, state.lease_id
                )

    async def _safe_descriptor(
        self, service: Any, state: "_BroadcastSocketState"
    ) -> Any:
        """Fetch the descriptor without letting a store blip break teardown."""
        try:
            return await service.get_descriptor(
                state.principal.tenant_id, state.broadcast_id
            )
        except Exception:  # noqa: BLE001
            return None

    async def _teardown_broadcast_socket(
        self, service: Any, state: "_BroadcastSocketState"
    ) -> None:
        """Release the socket's bindings and deregister it.  Never raises."""
        if not state.attached or state.lease_id is None:
            return
        await self._release_speaking(service, state)
        with contextlib.suppress(Exception):
            await service.detach_control(
                state.principal.tenant_id, state.broadcast_id, state.lease_id
            )
        self.logger.info(
            "broadcast socket %s closed (lease=%s, rejected_frames=%d)",
            state.socket_id,
            state.lease_id,
            state.rejected_frames,
        )

    async def _send_broadcast_error(
        self, ws: web.WebSocketResponse, code: str, message: str
    ) -> None:
        """Send a coded error frame.

        Broadcast clients branch on ``code`` (``floor_not_granted``,
        ``stale_floor_epoch``, ``speaker_connection_exists``, …); the legacy
        ``_send_error`` sends only a human message.
        """
        await self._send_message(
            ws, {"type": "error", "code": code, "message": message}
        )

    async def _report_broadcast_error(
        self, state: "_BroadcastSocketState", exc: BaseException
    ) -> None:
        """Translate an exception into a coded error frame."""
        reason = getattr(exc, "reason", None)
        code = getattr(reason, "value", None) or "internal_error"
        if code == "internal_error":
            # The detail stays server-side: an unhandled exception's text can
            # embed connection strings or internal hosts (aiohttp/redis errors
            # routinely do), and the peer is only a lease holder.
            self.logger.exception(
                "broadcast socket %s: unhandled error", state.socket_id
            )
        await self._send_broadcast_error(
            state.ws, code, _public_broadcast_message(exc)
        )

    # =========================================================================
    # Message Handlers
    # =========================================================================

    async def _handle_message(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None:
        """Route message to appropriate handler."""
        msg_type = message.get("type", "")

        # Auth can always be handled
        if msg_type == "auth":
            await self._handle_auth(connection, message)
            return

        # Ping can always be handled
        if msg_type == "ping":
            await self._handle_ping(connection, message)
            return

        # Check authentication for other message types
        if self.require_auth and not connection.authenticated:
            await self._send_message(
                connection.ws,
                {"type": "auth_required", "message": "Authentication required. Send {type: 'auth', token: '...'}"},
            )
            return

        handlers = {
            "start_session": self._handle_start_session,
            "end_session": self._handle_end_session,
            "reset_session": self._handle_reset_session,
            "start_recording": self._handle_start_recording,
            "stop_recording": self._handle_stop_recording,
            "audio_data": self._handle_audio_data,
            "audio_chunk": self._handle_audio_data,
            "send_text": self._handle_send_text,
            "text_message": self._handle_send_text,
            "voice_complete": self._handle_voice_complete,  # Non-streaming voice
            "voice_buffer": self._handle_voice_complete,  # Alias
        }

        if handler := handlers.get(msg_type):
            await handler(connection, message)
        else:
            self.logger.warning("Unknown message type: %s", msg_type)

    async def _handle_auth(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None:
        """
        Handle authentication message.

        Expected message format:
        {
            "type": "auth",
            "token": "<jwt_token>"
        }

        Or with authorization header format:
        {
            "type": "auth",
            "authorization": "Bearer <jwt_token>"
        }
        """
        # Extract token from message
        token = message.get("token")

        if not token:
            # Try authorization header format
            auth_header = message.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token:
            await self._send_message(
                connection.ws,
                {
                    "type": "auth_error",
                    "message": "Token not provided",
                },
            )
            return

        # Validate token
        user = await self.token_validator.validate(token)

        if user:
            connection.authenticated = True
            connection.user = user

            await self._send_message(
                connection.ws,
                {
                    "type": "auth_success",
                    "message": "Authentication successful",
                    "user": {
                        "user_id": user.user_id,
                        "username": user.username,
                    },
                },
            )

            self.logger.info(f"Session {connection.session_id} authenticated as {user.username}")
        else:
            await self._send_message(
                connection.ws,
                {
                    "type": "auth_error",
                    "message": "Invalid or expired token",
                },
            )

            self.logger.warning(f"Session {connection.session_id} authentication failed")

    async def _handle_ping(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None:
        """
        Handle ping message for connection keepalive.

        Request:
        {
            "type": "ping",
            "timestamp": "2025-01-14T12:00:00Z"  // optional client timestamp
        }

        Response:
        {
            "type": "pong",
            "timestamp": "2025-01-14T12:00:01Z",
            "client_timestamp": "2025-01-14T12:00:00Z",  // echoed if provided
            "ping_count": 42,
            "session_id": "...",
            "authenticated": true,
            "session_active": false
        }
        """
        connection.last_ping = datetime.now()
        connection.ping_count += 1

        response = {
            "type": "pong",
            "timestamp": datetime.now().isoformat(),
            "ping_count": connection.ping_count,
            "session_id": connection.session_id,
            "authenticated": connection.authenticated,
            "session_active": connection.session_active,
        }

        # Echo client timestamp if provided
        if client_ts := message.get("timestamp"):
            response["client_timestamp"] = client_ts

        await self._send_message(connection.ws, response)

    async def _handle_start_session(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None:
        """
        Start voice session.

        Message format:
        {
            "type": "start_session",
            "config": {
                "voice_name": "Puck",
                "language": "en-US",
                "system_prompt": "...",
                ...
            },
            "streaming_mode": "streaming"  // or "buffered"
        }

        Streaming modes:
        - "streaming" (default): Real-time bidirectional audio streaming.
          Audio chunks are sent immediately to the model and responses
          stream back in real-time. Best for conversational voice.

        - "buffered": Collect complete audio, process once, return complete
          response. Useful when client prefers to record complete audio
          first (e.g., mobile apps with push-to-talk).
        """
        # Merge default config with client-provided config
        client_config = message.get("config", {})
        config = self.default_config.merge_with(client_config)
        connection.config = config

        # Set streaming mode
        streaming_mode = message.get("streaming_mode", "streaming")
        if streaming_mode not in ("streaming", "buffered"):
            streaming_mode = "streaming"
        connection.streaming_mode = streaming_mode

        # STT-only mode (FEAT-257): parse from start_session payload.
        # Default False → full-duplex (existing behavior unchanged).
        stt_only_raw = message.get("stt_only", False)
        connection.stt_only = bool(stt_only_raw)
        if connection.stt_only:
            self.logger.info(
                "VoiceChatHandler: STT-only mode enabled for session %s",
                connection.session_id,
            )

        # Clear audio buffer for buffered mode
        connection.audio_buffer = b""

        # Store config for factory
        self._current_config = config
        connection.bot = self.bot_factory()

        # The bot factory builds the VoiceBot but does NOT run the async
        # configure() flow, so conversation_memory is never set up — which
        # means ask_stream() silently skips loading/saving turns and every
        # turn starts with no memory of the previous one (Gemini Live Mode
        # had no conversational continuity).  Configure memory here, best-
        # effort: Redis for cross-turn persistence within the session, with
        # the built-in in-memory fallback if Redis is unavailable.  Keyed by
        # connection.session_id, so turns accumulate across the session and
        # survive a GoAway reconnect.
        try:
            if getattr(connection.bot, "conversation_memory", None) is None:
                if not getattr(connection.bot, "memory_type", None) or connection.bot.memory_type == "memory":
                    connection.bot.memory_type = "redis"
                connection.bot.configure_conversation_memory()
        except Exception:  # noqa: BLE001 - memory is best-effort, never block voice
            self.logger.warning(
                "VoiceChatHandler: could not configure conversation memory "
                "for session %s; continuing without cross-turn memory.",
                connection.session_id,
                exc_info=True,
            )

        # Start voice task only for streaming mode
        connection.shutdown_event.clear()
        connection.session_active = True
        connection.stop_audio_sending = False

        if streaming_mode == "streaming":
            connection.voice_task = asyncio.create_task(self._run_voice_session(connection))

        # ── Avatar wiring (FEAT-245) ──────────────────────────────────────
        # Lazy-import the liveavatar stack so /ws/voice works without the
        # optional ai-parrot-integrations[liveavatar] extra.  All avatar
        # exceptions are caught and surfaced as avatar.active=false in the
        # session_started reply (graceful degradation — voice still starts).
        avatar_block: dict = {}
        avatar_requested = bool(message.get("avatar", False))
        if avatar_requested:
            try:
                from parrot.integrations.liveavatar import VoiceAvatarSession
                from parrot.integrations.liveavatar.optin import is_avatar_enabled

                tenant_id: Optional[str] = message.get("tenant_id") or None
                avatar_id_override: Optional[str] = message.get("avatar_id") or None
                agent_id: str = config.name if config and config.name else "voice-assistant"

                if not is_avatar_enabled(tenant_id=tenant_id, agent_name=agent_id):
                    avatar_block = {
                        "active": False,
                        "reason": "avatar mode is not enabled for this tenant",
                    }
                    self.logger.info(
                        "VoiceChatHandler: avatar opt-in denied for tenant=%s agent=%s",
                        tenant_id,
                        agent_id,
                    )
                else:
                    session: "VoiceAvatarSession" = await VoiceAvatarSession.start(
                        agent_id=agent_id,
                        session_id=connection.session_id,
                        tenant_id=tenant_id,
                        avatar_id=avatar_id_override,
                    )
                    connection.avatar_session = session
                    avatar_block = {
                        "active": True,
                        **session.viewer_credentials,
                        "audio": "dual",
                    }
                    self.logger.info(
                        "VoiceChatHandler: avatar session started for session=%s",
                        connection.session_id,
                    )
            except ImportError as exc:
                avatar_block = {"active": False, "reason": "liveavatar stack not installed"}
                self.logger.warning("VoiceChatHandler: liveavatar import failed — voice-only: %s", exc)
            except Exception as exc:  # noqa: BLE001
                avatar_block = {"active": False, "reason": str(exc)[:120]}
                self.logger.warning("VoiceChatHandler: avatar start failed — voice-only: %s", exc)

        session_started_msg: dict = {
            "type": "session_started",
            "session_id": connection.session_id,
            "user_id": connection.user_id,
            "streaming_mode": streaming_mode,
            "stt_only": connection.stt_only,
            "config": {
                "voice_name": config.voice_name,
                "language": config.language,
                "input_format": "audio/pcm;rate=16000",
                "output_format": "audio/pcm;rate=24000",
            },
        }
        if avatar_block:
            session_started_msg["avatar"] = avatar_block

        await self._send_message(connection.ws, session_started_msg)

        await self._send_message(connection.ws, {"type": "ready_to_speak", "message": "Ready for your question"})

        self.logger.info(
            "Voice session started: %s (mode=%s)",
            connection.session_id,
            streaming_mode,
        )

    async def _handle_end_session(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None:
        """End voice session."""
        connection.shutdown_event.set()
        connection.session_active = False
        connection.stop_audio_sending = True

        if connection.voice_task:
            connection.voice_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await connection.voice_task

        if connection.bot:
            await connection.bot.close()
            connection.bot = None

        # Tear down avatar session — mirrors _cleanup_connection so that an
        # explicit end_session from the client does not orphan the LiveAvatar WS.
        if connection.avatar_session is not None:
            with contextlib.suppress(Exception):
                await connection.avatar_session.aclose()
            connection.avatar_session = None

        await self._send_message(
            connection.ws,
            {
                "type": "session_ended",
                "session_id": connection.session_id,
            },
        )

        self.logger.info("Voice session ended: %s", connection.session_id)

    async def _handle_reset_session(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None:
        """Reset session - end current and start new."""
        await self._handle_end_session(connection, message)

        # Clear audio queue
        while not connection.audio_queue.empty():
            try:
                connection.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Start new session with same config
        await self._handle_start_session(
            connection, {"config": connection.config.as_dict() if connection.config else {}}
        )

        self.logger.info("Voice session reset: %s", connection.session_id)

    async def _handle_start_recording(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None:
        """Start audio recording."""
        connection.stop_audio_sending = False
        connection.gemini_responding = False
        connection.is_recording = True
        connection.recording_start_time = datetime.now()

        # FEAT-536 TASK-2942 (spec §2 "Demo interruption controls"): this
        # existing start_recording path is also the explicit Interrupt/
        # speak-again action — it replaces whatever voice turn (and its
        # avatar output) was in progress. Interrupt an active avatar
        # BEFORE start_turn() below so queued avatar audio from the turn
        # being replaced does not outlive it. Best-effort/isolated: an
        # avatar failure must never prevent the user from starting a new
        # turn or block ordinary WebSocket voice delivery.
        if connection.avatar_session is not None:
            try:
                await connection.avatar_session.interrupt()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "VoiceChatHandler: avatar interrupt on start_recording failed " "(voice recording unaffected): %s",
                    exc,
                )

        # FEAT-416 (TASK-2152): in streaming mode, each recording is one
        # VoiceSession turn — start_turn() creates the (fresh, per-turn)
        # audio queue that _handle_audio_data()/_handle_stop_recording()
        # below feed. VoiceSession itself also emits a "turn_started"
        # frame (additive — existing clients should ignore unknown frame
        # types; this is new functionality this refactor enables, not a
        # change to any existing frame).
        if connection.streaming_mode == "streaming" and connection.voice_session is not None:
            await connection.voice_session.start_turn()

        await self._send_message(
            connection.ws,
            {
                "type": "recording_started",
            },
        )

    async def _handle_stop_recording(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None:
        """
        Stop audio recording.

        In streaming mode: signals end of audio stream.
        In buffered mode: triggers processing of accumulated audio via ask_voice.
        """
        connection.is_recording = False
        connection.stop_audio_sending = True

        MIN_DURATION_MS = 500
        duration_ms = 0

        if connection.recording_start_time:
            duration_ms = (datetime.now() - connection.recording_start_time).total_seconds() * 1000
            connection.recording_start_time = None

            if duration_ms < MIN_DURATION_MS:
                self.logger.info(f"Recording too short ({duration_ms:.0f}ms), ignoring")
                # FEAT-416 (TASK-2152): previously drained
                # connection.audio_queue directly; audio now lives in
                # VoiceSession's own per-turn queue (created by
                # start_turn() in _handle_start_recording()), so abandon
                # that turn outright via VoiceSession's own cancellation
                # (cheaper than end_turn()'s ~460ms paced-silence
                # sequence, which is pointless for a clip too short to
                # process anyway).
                if connection.streaming_mode == "streaming" and connection.voice_session is not None:
                    await connection.voice_session._cancel_turn()
                connection.audio_buffer = b""

                await self._send_message(
                    connection.ws, {"type": "recording_stopped", "message": "Recording too short. Please hold longer."}
                )
                return

        await self._send_message(
            connection.ws,
            {
                "type": "recording_stopped",
                "message": "Processing...",
                "duration_ms": duration_ms,
            },
        )

        # FEAT-416 (TASK-2152): signal end-of-turn through VoiceSession —
        # this injects the 20ms-paced silence VAD needs before the
        # end-of-turn sentinel (TASK-2149), which the previous inlined
        # audio_from_queue() generator did not do.
        if connection.streaming_mode == "streaming" and connection.voice_session is not None:
            await connection.voice_session.end_turn()

        # In buffered mode, process the accumulated audio now
        if connection.streaming_mode == "buffered" and connection.audio_buffer:
            await self._handle_voice_binary_complete(connection, connection.audio_buffer)
            connection.audio_buffer = b""

    async def _handle_audio_data(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None:
        """
        Receive audio chunk (base64).

        In streaming mode: queues audio for immediate processing.
        In buffered mode: accumulates audio for later processing.
        """
        if not connection.is_recording:
            connection.stop_audio_sending = False
            connection.gemini_responding = False
            connection.recording_start_time = datetime.now()
            connection.audio_buffer = b""
            # FEAT-416 (TASK-2152): some clients send audio_data without a
            # preceding explicit start_recording — auto-start the
            # VoiceSession turn here too (matching the implicit
            # is_recording=True above), otherwise push_audio() below would
            # silently drop this audio (VoiceSession._queue is None until
            # start_turn() runs, TASK-2149).
            if connection.streaming_mode == "streaming" and connection.voice_session is not None:
                await connection.voice_session.start_turn()

        connection.is_recording = True

        if not connection.session_active or connection.stop_audio_sending:
            return

        if audio_b64 := message.get("data", ""):
            audio_bytes = base64.b64decode(audio_b64)

            if connection.streaming_mode == "streaming":
                if connection.voice_session is not None:
                    await connection.voice_session.push_audio(audio_bytes)
            else:
                # Buffered mode
                connection.audio_buffer += audio_bytes

    async def _handle_send_text(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None:
        """
        Send text to bot and receive voice response (text-to-speech).

        Uses VoiceBot.ask() which converts text to speech.

        Message format:
        {
            "type": "send_text",
            "text": "Hello, how are you?",
            "streaming": true  // optional, default true
        }
        """
        text = message.get("text", "")
        if not text or not connection.bot:
            return

        streaming = message.get("streaming", True)

        try:
            if streaming:
                # Streaming mode - send chunks as they arrive
                async for response in connection.bot.ask(
                    question=text,
                    session_id=connection.session_id,
                    user_id=connection.user_id,
                ):
                    await self._send_voice_response(connection, response)
            else:
                # Non-streaming mode - accumulate and send complete response
                full_text = ""
                full_audio = b""
                tool_calls = []

                async for response in connection.bot.ask(
                    question=text,
                    session_id=connection.session_id,
                    user_id=connection.user_id,
                ):
                    if response.text:
                        full_text += response.text
                    if response.audio_data:
                        full_audio += response.audio_data
                    if response.tool_calls:
                        tool_calls.extend(response.tool_calls)

                # Send complete response
                await self._send_complete_voice_response(
                    connection,
                    text=full_text,
                    audio_data=full_audio,
                    tool_calls=tool_calls,
                )

        except Exception as e:
            self.logger.error("Error processing text: %s", e)
            await self._send_error(connection.ws, str(e))

    async def _handle_voice_complete(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None:
        """
        Handle complete audio buffer for non-streaming voice processing.

        Uses VoiceBot.ask_voice() which processes complete audio and returns
        complete response (no streaming).

        This is useful when:
        - Client wants to send complete audio at once
        - Client prefers complete response over streaming
        - Lower latency is less important than simplicity

        Message format:
        {
            "type": "voice_complete",
            "audio_base64": "<complete audio buffer in base64>",
            "audio_format": "audio/pcm;rate=16000"  // optional
        }

        Response:
        {
            "type": "voice_response",
            "text": "transcribed and response text",
            "audio_base64": "<complete response audio>",
            "audio_format": "audio/pcm;rate=24000",
            "tool_calls": [...],
            "usage": {...}
        }
        """
        if not connection.bot:
            await self._send_error(connection.ws, "Session not started")
            return

        audio_b64 = message.get("audio_base64", "") or message.get("data", "")
        if not audio_b64:
            await self._send_error(connection.ws, "No audio data provided")
            return

        try:
            # Decode audio
            audio_bytes = base64.b64decode(audio_b64)

            self.logger.info(
                f"Processing complete audio: {len(audio_bytes)} bytes " f"for session {connection.session_id}"
            )

            # Notify client we're processing
            await self._send_message(
                connection.ws,
                {
                    "type": "processing",
                    "message": "Processing audio...",
                    "audio_size": len(audio_bytes),
                },
            )

            # Use non-streaming ask_voice
            response = await connection.bot.ask_voice(
                audio_input=audio_bytes,
                session_id=connection.session_id,
                user_id=connection.user_id,
            )

            # Send complete response
            await self._send_complete_voice_response(
                connection,
                text=response.text,
                audio_data=response.audio_data,
                tool_calls=response.tool_calls,
                usage=response.usage,
                metadata=response.metadata,
            )

        except Exception as e:
            self.logger.error("Error processing voice: %s", e)
            await self._send_error(connection.ws, str(e))

    async def _handle_voice_binary_complete(self, connection: WebSocketConnection, audio_bytes: bytes) -> None:
        """
        Handle complete binary audio for non-streaming processing.

        Called when connection is in non-streaming mode and receives
        complete binary audio data.
        """
        if not connection.bot:
            return

        try:
            self.logger.info(f"Processing binary audio: {len(audio_bytes)} bytes")

            await self._send_message(
                connection.ws,
                {
                    "type": "processing",
                    "message": "Processing audio...",
                },
            )

            response = await connection.bot.ask_voice(
                audio_input=audio_bytes,
                session_id=connection.session_id,
                user_id=connection.user_id,
            )

            await self._send_complete_voice_response(
                connection,
                text=response.text,
                audio_data=response.audio_data,
                tool_calls=response.tool_calls,
                usage=response.usage,
                metadata=response.metadata,
            )

        except Exception as e:
            self.logger.error("Error processing binary voice: %s", e)
            await self._send_error(connection.ws, str(e))

    async def _send_complete_voice_response(
        self,
        connection: WebSocketConnection,
        text: str = "",
        audio_data: Optional[bytes] = None,
        tool_calls: Optional[List[Any]] = None,
        usage: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send complete voice response (non-streaming).

        Used by ask_voice and non-streaming text-to-speech.

        Note (FEAT-418, TASK-2174): this used to forward a
        ``metadata["user_transcription"]`` key as a ``transcription``
        frame. That key is removed from the producer (TASK-2167) and,
        unlike the streaming path (``_send_voice_response()``, migrated to
        canonical ``role``), ``VoiceBot.ask_voice()``'s aggregation
        (``bots/voice.py``, out of this task's file scope) merges all
        chunks' ``metadata``/``text`` into one flat response without
        preserving per-chunk ``role`` — so there is no role-based
        replacement available here without changing ``ask_voice()``
        itself. The dead branch is removed rather than left silently
        never firing.
        """
        # Send tool calls
        for tc in tool_calls or []:
            await self._send_message(
                connection.ws,
                {
                    "type": "tool_call",
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "result": tc.result,
                    "execution_time_ms": getattr(tc, "execution_time_ms", None),
                },
            )

        # Send complete response
        response_msg = {
            "type": "voice_response",
            "text": text,
            "audio_base64": base64.b64encode(audio_data).decode() if audio_data else "",
            "audio_format": "audio/pcm;rate=24000",
            "is_complete": True,
        }

        if usage:
            response_msg["usage"] = {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
                "total_tokens": getattr(usage, "total_tokens", 0),
                "audio_duration_ms": getattr(usage, "audio_duration_ms", 0),
            }

        await self._send_message(connection.ws, response_msg)

        # Signal ready for next input
        await self._send_message(connection.ws, {"type": "ready_to_speak", "message": "Ready for new question"})

    # =========================================================================
    # Voice Session
    # =========================================================================

    async def _run_voice_session(self, connection: WebSocketConnection) -> None:
        """Own the connection's :class:`VoiceSession` for its lifetime.

        FEAT-416 (TASK-2152): the actual turn lifecycle (audio queue,
        turn task, silence-paced end-of-turn, reconnection) is now owned
        by ``connection.voice_session`` (a :class:`_HandlerVoiceSession`),
        driven by ``_handle_start_recording()``/``_handle_audio_data()``/
        ``_handle_stop_recording()``. This method just constructs the
        session and keeps this task alive until shutdown, then tears it
        down — mirroring the task's own Implementation Notes pattern.
        """
        if not connection.bot:
            return

        bot = connection.bot

        # VoiceSession requires a VoiceCapable client. Reuse VoiceBot's own
        # lazy-construction (matches ask_stream()/ask()'s
        # `if self._llm is None: ...` pattern) rather than duplicating
        # VoiceBot's private _resolve_llm_config()/_create_llm_client()
        # call sequence differently — accesses the same "private" attrs
        # the rest of this handler already does (e.g.
        # connection.bot.conversation_memory above).
        if bot._llm is None:
            config = bot._resolve_llm_config()
            bot._llm = bot._create_llm_client(config)

        # FEAT-418 (TASK-2174): wrap the raw client so the now-INHERITED
        # VoiceSession._run_turn() (no more duplicated reconnection loop)
        # drives turns through VoiceBot.ask_stream() — preserving
        # conversation-memory persistence and dynamic system-prompt
        # building, which the raw client's stream_voice() alone cannot
        # provide. See _AskStreamVoiceClient's docstring above.
        client = _AskStreamVoiceClient(bot, user_id=connection.user_id)

        async def send_fn(payload: dict) -> None:
            if not connection.ws.closed:
                await connection.ws.send_json(payload)

        connection.voice_session = _HandlerVoiceSession(
            client=client,
            send_fn=send_fn,
            system_prompt=bot.system_prompt,
            voice_config=bot.voice_config,
            session_id=connection.session_id,
            stt_only=connection.stt_only,
            handler=self,
            connection=connection,
        )

        try:
            while not connection.shutdown_event.is_set():
                await asyncio.sleep(0.1)
        finally:
            if connection.voice_session is not None:
                await connection.voice_session.close()

    async def _send_voice_response(self, connection: WebSocketConnection, response: Any) -> None:
        """Send voice response to client.

        In STT-only mode (connection.stt_only=True) only ``transcription``
        frames (is_user=True) are forwarded; ``response_chunk`` and model
        audio frames are suppressed (double-brain guard).

        FEAT-536 TASK-2942: ``tool_call`` frames are deduped per turn
        (keyed by ``response.turn_id`` — this path's only available
        turn-boundary marker, tracked on ``connection`` — see its own
        field comment) — equivalent to ``_HandlerVoiceSession.build_frames()``'s
        ``turn_no``-keyed bookkeeping for the streaming relay path.
        """
        turn_id = getattr(response, "turn_id", None)
        if turn_id != connection._tool_dedup_turn_id:
            connection._tool_dedup_turn_id = turn_id
            connection._sent_tool_call_ids = set()

        # STT-only: skip all model response frames — only transcription is allowed.
        if not connection.stt_only:
            # Send response_chunk for audio OR text (not just audio)
            # FILTER: Skip internal thought processes that leak into output
            # (see _THOUGHT_FILTER_PATTERN's docstring for the two patterns).
            is_thought = bool(response.text and _THOUGHT_FILTER_PATTERN.match(response.text))

            # Determine strict text to send (suppress if thought)
            text_to_send = response.text
            if is_thought:
                text_to_send = ""

            if (response.audio_data or text_to_send) and not response.is_complete:
                await self._send_message(
                    connection.ws,
                    {
                        "type": "response_chunk",
                        "text": text_to_send or "",
                        "audio_base64": base64.b64encode(response.audio_data).decode() if response.audio_data else "",
                        "audio_format": "audio/pcm;rate=24000" if response.audio_data else "",
                        "is_interrupted": response.is_interrupted,
                    },
                )

        # User transcription is always forwarded (both modes). FEAT-418:
        # canonical role="user" replaces the removed
        # metadata["user_transcription"] key.
        if response.role == "user" and response.text:
            await self._send_message(
                connection.ws,
                {
                    "type": "transcription",
                    "text": response.text,
                    "is_user": True,
                },
            )

        # Everything below this point is model-response output — skip in STT-only.
        if connection.stt_only:
            return

        # Forward the assistant's spoken text as the display bubble.
        # FEAT-418: canonical role="assistant" replaces the removed
        # metadata["assistant_transcription"] key; turn_metadata's own
        # output_transcription remains as a fallback for a frame that
        # carries no text of its own (e.g. an audio-only chunk). In audio
        # mode Gemini's model_turn TEXT modality is generated separately
        # from the audio — it diverges from what's actually spoken (and
        # leaks "thinking" headers), so the transcription is the source of
        # truth for the bubble. The front shows this and ignores the
        # response_chunk text (audio only).
        assistant_text = response.text if response.role == "assistant" else None
        if not assistant_text and response.turn_metadata:
            assistant_text = response.turn_metadata.output_transcription
        if assistant_text:
            await self._send_message(
                connection.ws,
                {
                    "type": "transcription",
                    "text": assistant_text,
                    "is_user": False,
                },
            )

        if response.metadata.get("display_data"):
            await self._send_message(connection.ws, {"type": "display_data", "data": response.metadata["display_data"]})

        for tc in response.tool_calls:
            if tc.id in connection._sent_tool_call_ids:
                continue
            connection._sent_tool_call_ids.add(tc.id)
            await self._send_message(
                connection.ws,
                {
                    "type": "tool_call",
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "result": tc.result,
                    "execution_time_ms": tc.execution_time_ms,
                },
            )

        if response.is_complete:
            # Re-check filter for the final text payload
            final_text = response.text
            if final_text and _THOUGHT_FILTER_PATTERN.match(final_text):
                final_text = ""

            await self._send_message(
                connection.ws,
                {
                    "type": "response_complete",
                    "text": final_text or "",
                    "is_interrupted": response.is_interrupted,
                },
            )

            await self._send_message(connection.ws, {"type": "ready_to_speak", "message": "Ready for new question"})

        # ── Avatar audio tee (FEAT-245) ───────────────────────────────────
        # Best-effort: exceptions are caught and logged; the browser audio
        # path MUST NOT be interrupted by an avatar hiccup (dual audio).
        if connection.avatar_session is not None:
            try:
                if response.is_interrupted:
                    await connection.avatar_session.interrupt()
                else:
                    if response.audio_data:
                        await connection.avatar_session.speak(response.audio_data)
                    if response.is_complete:
                        await connection.avatar_session.finish_turn()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("VoiceChatHandler: avatar tee error (voice stream unaffected): %s", exc)

    # =========================================================================
    # Utilities
    # =========================================================================

    async def _send_message(self, ws: web.WebSocketResponse, message: Dict[str, Any]) -> None:
        """Send JSON message to client."""
        try:
            await ws.send_json(message)
        except Exception as e:
            self.logger.error("Error sending message: %s", e)

    async def _send_error(self, ws: web.WebSocketResponse, error_message: str) -> None:
        """Send error message to client."""
        await self._send_message(
            ws,
            {
                "type": "error",
                "message": error_message,
                "timestamp": datetime.now().isoformat(),
            },
        )

    async def _cleanup_connection(self, connection: WebSocketConnection) -> None:
        """Clean up connection resources."""
        connection.shutdown_event.set()

        if connection.voice_task:
            connection.voice_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await connection.voice_task

        if connection.bot:
            await connection.bot.close()

        # Clear audio queue
        while not connection.audio_queue.empty():
            try:
                connection.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Clear audio buffer
        connection.audio_buffer = b""

        # Tear down avatar session (FEAT-245) — idempotent, never raises
        if connection.avatar_session is not None:
            try:
                await connection.avatar_session.aclose()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("VoiceChatHandler: avatar session cleanup error: %s", exc)
            finally:
                connection.avatar_session = None

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Send message to all active connections."""
        for connection in self.connections.values():
            await self._send_message(connection.ws, message)

    @property
    def active_connections(self) -> int:
        """Number of active connections."""
        return len(self.connections)


# =============================================================================
# Factory Function
# =============================================================================


def create_voice_server(
    bot_factory: Optional[Callable[[], VoiceBot]] = None,
    bot_config: Optional[Union[BotConfig, Dict[str, Any]]] = None,
    *,
    require_auth: bool = False,
    secret_key: Optional[str] = None,
    static_dir: Optional[str] = None,
    **kwargs,
) -> web.Application:
    """
    Create complete voice server application.

    Args:
        bot_factory: Custom bot factory
        bot_config: Default bot configuration
        require_auth: Require JWT authentication
        secret_key: JWT secret key
        static_dir: Static files directory
        **kwargs: Additional handler arguments

    Returns:
        Configured aiohttp Application
    """
    handler = VoiceChatHandler(
        bot_factory=bot_factory, default_config=bot_config, require_auth=require_auth, secret_key=secret_key, **kwargs
    )

    app = web.Application()

    # Setup routes
    handler.setup_routes(
        app,
        include_static=static_dir is not None,
        static_dir=static_dir,
    )

    # Serve index if static dir exists
    if static_dir:
        from pathlib import Path

        frontend_dir = Path(static_dir)
        if (frontend_dir / "chat.html").exists():

            async def index(request):
                return web.FileResponse(frontend_dir / "chat.html")

            app.router.add_get("/", index)

    # CORS middleware
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)

        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-User-Id"
        return response

    app.middlewares.append(cors_middleware)

    return app


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Voice Chat WebSocket Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind")
    parser.add_argument("--voice", default="Puck", help="Default voice name")
    parser.add_argument("--require-auth", action="store_true", help="Require authentication")
    parser.add_argument("--secret-key", help="JWT secret key")
    args = parser.parse_args()

    app = create_voice_server(
        bot_config=BotConfig(
            voice_name=args.voice,
            system_prompt="You are a helpful voice assistant.",
        ),
        require_auth=args.require_auth,
        secret_key=args.secret_key,
    )

    print(f"Starting voice server on {args.host}:{args.port}")
    print(f"Authentication: {'required' if args.require_auth else 'optional'}")
    web.run_app(app, host=args.host, port=args.port)
