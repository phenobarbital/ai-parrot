"""AudioFormWSHandler — WebSocket adapter for interactive audio form sessions.

Thin I/O adapter over the pure :class:`~parrot_formdesigner.audio.engine.AudioFormSession`
state machine: it authenticates the connection, decodes JSON/binary frames into
engine events, performs every I/O request the engine returns (TTS, STT, blob
storage, re-planning, plausibility, snapshots, submission), feeds the results
back as events and encodes the wire messages (v1 shapes preserved, v2 adds
``audio_segment`` headers followed by a binary frame).

WebSocket protocol (see spec §2 for full message definitions):
- Client sends JSON messages with a "type" field.
- Binary frames are treated as audio data for STT transcription.
- Server responds with JSON messages.

Authentication: JWT token extracted from Sec-WebSocket-Protocol header or
from the first "auth" type message. Unauthenticated connections receive an
error and are closed.

Added by FEAT-224 (FormDesigner Audio Renderer); rewritten by FEAT-649.
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import logging
from types import SimpleNamespace
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from aiohttp import WSMsgType, web
from pydantic import ValidationError

from ..audio.engine import AudioFormSession
from ..audio.events import (
    AnswerAccepted,
    AnswerCleared,
    AudioReceived,
    AudioSegment,
    BlobStored,
    DeleteBlob,
    Error,
    FormComplete,
    InboundEvent,
    IOFailed,
    Outbound,
    PlanReady,
    PlausibilityDone,
    Question,
    Replan,
    RunPlausibility,
    SaveSnapshot,
    SessionEnded,
    StartSession,
    StoreBlob,
    Submit,
    SubmitDone,
    Synthesize,
    Transcribe,
    TranscriptReady,
    UnknownMessageType,
    is_io_request,
    parse_inbound,
)
from ..audio.models import (
    AudioFormManifest,
    AudioQuestion,
    AudioSessionConfig,
    AudioSessionState,
    Phase,
    VoiceMode,
)
from ..audio.narration.engine import Narrator
from ..audio.narration.lexicon import load_lexicon
from ..audio.recordings import delete_recording, store_recording
from ..audio.segments import _SYNTH_LOCK, AudioSegmentCache
from ..audio.session_store import AudioSnapshot, ResumeUnavailable, SnapshotConflict
from ..core.llm_validation import LLMValidationConfig, PlausibilityReport
from ..core.voice import resolve_voice_config
from ..core.voice_answer import unwrap_voice
from ..renderers.audio import (
    AudioFormRenderer,
    synthesize_with_fallback,
)
from ..services.auth_context import AuthContext
from ..services.plausibility import AnswerPlausibilityChecker, PlausibilityBlocked
from ..services.submission_pipeline import SubmissionPipeline, ValidationFailed

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient
    from parrot.core.ws_auth import AuthenticatedUser, TokenValidator
    from parrot.voice.tts.synthesizer import VoiceSynthesizer
    from parrot.voice.transcriber.backend import AbstractTranscriberBackend

    from ..audio.session_store import AudioSessionStore
    from ..core.schema import FormSchema
    from ..services.blob_storage import AbstractBlobStorage
    from ..services.registry import FormRegistry
    from ..services.submissions import FormSubmissionStorage
    from ..services.validators import FormValidator

logger = logging.getLogger(__name__)


# Client-facing placeholder used in lieu of a sensitive (e.g. password) value
# in transcription / confirm_request messages (FEAT-236).
_SENSITIVE_MASK = "[hidden]"

# Minimum plausible size (bytes) for a real audio recording. A complete WebM/OGG
# container with at least one frame of media is comfortably larger than this; a
# payload below it is almost always an empty/instant recording.
_MIN_AUDIO_BYTES = 256


def _sniff_audio_suffix(data: bytes) -> Optional[str]:
    """Detect the audio container from leading magic bytes.

    libav sniffs the real format from content (the temp-file suffix is only
    cosmetic for decoding), but matching the suffix to the actual container
    keeps the temp file honest and lets us reject non-audio payloads early.

    Args:
        data: The raw bytes received on the WebSocket binary frame.

    Returns:
        A file suffix (e.g. ``".webm"``) for a recognized container, or
        ``None`` if the bytes do not match any known audio container.
    """
    if len(data) < 12:
        return None
    # Matroska / WebM: EBML magic.
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return ".webm"
    # OGG (Opus/Vorbis): "OggS".
    if data[:4] == b"OggS":
        return ".ogg"
    # MP4 / M4A (AAC): "....ftyp" at offset 4.
    if data[4:8] == b"ftyp":
        return ".mp4"
    # WAV (PCM): "RIFF"...."WAVE".
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return ".wav"
    return None



_AUDIO_MIME_BY_SUFFIX = {".webm": "audio/webm", ".ogg": "audio/ogg", ".mp4": "audio/mp4", ".wav": "audio/wav"}

# Wire messages that only exist in protocol v2 — never sent to a v1 client.
_V2_ONLY_TYPES = frozenset({
    "audio_segment", "plan_updated", "section_enter", "command_ack", "question_skipped", "answer_cleared",
    "review_start", "review_item", "review_prompt", "plausibility_result", "session_resumed",
})
# Question keys added by v2.
_V2_QUESTION_KEYS = ("section_uid", "hint", "ui_cue", "answer_modes", "narration")


@dataclass
class _ConnCtx:
    """Per-connection adapter state (replaces the old per-connection audio cache)."""

    request: Any
    user: Any
    tenant: Optional[str]
    state: AudioSessionState
    engine: Optional[AudioFormSession] = None
    form: Optional["FormSchema"] = None
    revision: int = 0
    segments: Optional[AudioSegmentCache] = None
    v1_audio: dict[str, bytes] = field(default_factory=dict)  # field_uid → narration audio (inline mode)
    prefetch: bool = True
    closed: bool = False

    @property
    def inline_audio(self) -> bool:
        """True when question audio travels base64 inside ``question`` (v1, or v2 with prefetch off)."""
        return self.state.protocol_version < 2 or not self.prefetch


class _AutoSynthAdapter:
    """Presents the handler's ``auto_synthesize`` fallback as a synthesiser for ``AudioSegmentCache``.

    This puts the default path behind the same segment cache and process-wide ``_SYNTH_LOCK`` as an
    injected synthesiser (AC17).
    """

    def __init__(self, handler: "AudioFormWSHandler", state: AudioSessionState) -> None:
        self._handler = handler
        self._state = state
        cfg = state.config
        self.config = SimpleNamespace(mime_format=getattr(cfg, "tts_mime_format", None) or "audio/wav")

    async def synthesize(self, text: str, language: Optional[str] = None) -> Any:
        """Synthesize via the per-session auto backend; raise when it degrades to text-only."""
        language = None if language == "en" else language
        audio = await self._handler._auto_synthesize_cached(
            self._state, text, config=self._state.config, language=language
        )
        if not audio:
            raise RuntimeError("auto TTS unavailable")
        return SimpleNamespace(audio=audio)


class AudioFormWSHandler:
    """WebSocket adapter for interactive audio form sessions.

    One engine (:class:`AudioFormSession`) per connection; this class performs
    all I/O the engine requests:
    - JWT authentication via Sec-WebSocket-Protocol header or first message.
    - start_session: loads the FormSchema (URL tenant), builds the manifest and engine.
    - text/binary frames are decoded into engine events; STT, TTS, blob storage,
      re-planning, plausibility, autosave snapshots and submission are performed here.
    - Submission always goes through :class:`SubmissionPipeline` (sinks, events, forwarder).

    Args:
        registry: FormRegistry to look up forms by ID.
        synthesizer: VoiceSynthesizer for TTS question audio.
        transcriber: STT backend for audio answers.
        validator: FormValidator used by the lazily built submission pipeline.
        token_validator: TokenValidator for JWT authentication.
        submission_storage: Storage backend for the lazily built submission pipeline.
        pipeline: Shared SubmissionPipeline (``app["submission_pipeline"]``); built lazily when omitted.
        blob_storage: Optional blob storage for spoken-answer recordings.
        session_store: Optional AudioSessionStore for autosave/resume snapshots.
        llm_client_getter: Callable returning the LLM client used for per-form plausibility checks.
        auto_synthesize: When True and no explicit ``synthesizer`` is injected,
            the handler synthesizes TTS via the SuperTonic-first fallback helper
            (SuperTonic → Google → text-only). Defaults to False so callers that
            pass no synthesizer get a silent (text-only) session unless they
            opt in. Wired on by ``setup_form_api`` when audio is intended
            (FEAT-236 TASK-1542).

    Example::

        handler = AudioFormWSHandler(
            registry=registry,
            synthesizer=synthesizer,
            transcriber=transcriber,
            validator=FormValidator(),
            token_validator=TokenValidator(secret_key=SECRET),
        )
        # Register route: app.router.add_get(
        #   "/api/v1/{tenant}/forms/{form_uid}/audio/ws",
        #   handler.handle_websocket
        # )
    """

    def __init__(
        self,
        registry: "FormRegistry",
        synthesizer: Optional["VoiceSynthesizer"],
        transcriber: Optional["AbstractTranscriberBackend"],
        validator: "FormValidator",
        *,
        token_validator: Optional["TokenValidator"] = None,
        submission_storage: Optional["FormSubmissionStorage"] = None,
        pipeline: Optional[SubmissionPipeline] = None,
        blob_storage: Optional["AbstractBlobStorage"] = None,
        session_store: Optional["AudioSessionStore"] = None,
        llm_client_getter: Optional[Callable[[], Optional["AbstractClient"]]] = None,
        max_msg_size: int = 10 * 1024 * 1024,
        auto_synthesize: bool = False,
    ) -> None:
        """Initialize the adapter; every new collaborator is optional (degrades, never fails)."""
        self.registry = registry
        self.synthesizer = synthesizer
        self.transcriber = transcriber
        self.validator = validator
        self._token_validator = token_validator
        self._submission_storage = submission_storage
        self._pipeline = pipeline
        self._blob_storage = blob_storage
        self._session_store = session_store
        self._llm_client_getter = llm_client_getter
        self._checkers: dict[str, AnswerPlausibilityChecker] = {}  # session_id → per-form checker
        self._max_msg_size = max_msg_size
        self._auto_synthesize = auto_synthesize
        # Per-session working VoiceSynthesizer cache (session_id → synth) for the
        # auto_synthesize path, so the chosen backend is reused across a
        # session's questions instead of being rebuilt per narration (FEAT-236).
        self._session_synths: dict[str, Any] = {}
        self.logger = logging.getLogger(__name__)

    # -------------------------------------------------------------------------
    # Main entry point
    # -------------------------------------------------------------------------

    async def handle_websocket(
        self, request: web.Request
    ) -> web.WebSocketResponse:
        """Handle an incoming WebSocket connection for an audio form session.

        Args:
            request: Incoming aiohttp request. Expected path params:
                ``{form_uid}``.

        Returns:
            Completed WebSocketResponse.
        """
        # Browsers cannot set an Authorization header on a WebSocket, so the
        # JWT is smuggled in as a Sec-WebSocket-Protocol subprotocol. The
        # handshake response MUST echo back one of the client's offered
        # subprotocols, or strict clients abort the connection immediately.
        offered_protocols = [
            proto.strip()
            for proto in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
            if proto.strip()
        ]
        ws = web.WebSocketResponse(
            heartbeat=30.0,
            max_msg_size=self._max_msg_size,
            protocols=offered_protocols,
        )
        await ws.prepare(request)

        # Step 1: Authenticate
        user = await self._authenticate(ws, request)
        if user is None:
            return ws

        # Step 1.5: Tenant declaration (FEAT-421). This route is NOT
        # `_wrap_auth`-ed — navigator-auth's decorators return HTTP 401,
        # incompatible with the WS upgrade handshake — so the tenant check
        # is inline here, after JWT validation and before the form is ever
        # resolved (see spec §7 "Known Risks": audio WS cannot use the
        # requires_tenant decorator). By the time we're here, ws.prepare()
        # has already sent the HTTP 101 response, so a missing/invalid
        # tenant is reported as a WS close, never an HTTP 400.
        declared_tenant = request.match_info.get("tenant")
        if not declared_tenant:
            await self._send_error(
                ws, "TENANT_NOT_DECLARED", "This endpoint requires an explicit tenant."
            )
            await ws.close(code=1008, message=b"tenant_not_declared")
            return ws

        ctx = _ConnCtx(
            request=request,
            user=user,
            tenant=declared_tenant,
            state=AudioSessionState(
                session_id=str(uuid.uuid4()),
                form_uid=request.match_info.get("form_uid", ""),
                user_id=user.user_id,
                tenant=declared_tenant,
            ),
        )

        # Step 2: Message loop
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        await self._send_error(ws, "INVALID_JSON", "Invalid JSON message")
                        continue
                    if not isinstance(data, dict):
                        await self._send_error(ws, "INVALID_JSON", "Invalid JSON message")
                        continue
                    await self._guarded(ws, self._process_text(ws, ctx, data), "INTERNAL_ERROR")
                elif msg.type == WSMsgType.BINARY:
                    await self._guarded(ws, self._process_binary(ws, ctx, msg.data), "TRANSCRIPTION_ERROR")
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
                if ctx.closed:
                    break
        finally:
            try:
                await self._autosave(ctx, final=True)
            except Exception as exc:  # noqa: BLE001 — never mask the connection teardown
                self.logger.warning("Final snapshot save failed: %s", type(exc).__name__)
            if ctx.engine is not None and self._session_store is not None:
                # Dropped connection: the snapshot stays resumable, the active marker does not (resume re-claims it).
                try:
                    await self._session_store.release_active(ctx.state.user_id, ctx.state.session_id)
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning("Active marker release failed: %s", type(exc).__name__)
            self._checkers.pop(ctx.state.session_id, None)
            # Release any per-session synthesizer built lazily in auto mode.
            cached_synth = self._session_synths.pop(ctx.state.session_id, None)
            if cached_synth is not None:
                await self._close_synth(cached_synth)
            self.logger.debug(
                "AudioFormWSHandler: session %s closed", ctx.state.session_id
            )

        return ws

    async def _guarded(self, ws: web.WebSocketResponse, coro: Any, code: str) -> None:
        """Run ``coro``; an unexpected exception becomes an ``error`` message (no transcript/value logging)."""
        try:
            await coro
        except Exception as exc:  # noqa: BLE001 — keep the connection alive
            self.logger.exception("Error handling audio frame (%s): %s", code, type(exc).__name__)
            await self._send_error(ws, code, str(exc))

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    async def _authenticate(
        self,
        ws: web.WebSocketResponse,
        request: web.Request,
    ) -> Optional["AuthenticatedUser"]:
        """Extract and validate JWT token from the WebSocket handshake.

        Tries the Sec-WebSocket-Protocol header first (subprotocol pattern),
        then waits for an 'auth' message as a fallback.

        Args:
            ws: Prepared WebSocket response.
            request: Incoming request (used to read headers).

        Returns:
            AuthenticatedUser if valid token found, None if auth failed
            (in which case an error is sent and the connection is closed).
        """
        if self._token_validator is None:
            # No validator configured — anonymous access for testing/dev.
            self.logger.warning(
                "AudioFormWSHandler: no token_validator configured — "
                "accepting anonymous connection (not for production use)"
            )
            from parrot.core.ws_auth import AuthenticatedUser  # type: ignore[import-untyped]
            return AuthenticatedUser(user_id="anonymous", username="anonymous")

        # Try Sec-WebSocket-Protocol header (token passed as subprotocol).
        protocols = request.headers.get("Sec-WebSocket-Protocol", "")
        token: Optional[str] = None
        if protocols:
            for proto in protocols.split(","):
                proto = proto.strip()
                if proto and proto != "json":
                    token = proto
                    break

        if token:
            user = await self._token_validator.validate(token)
            if user:
                return user

        # Fallback: wait for first message of type "auth".
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=10.0)
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if data.get("type") == "auth":
                        token = data.get("token", "")
                        if token:
                            user = await self._token_validator.validate(token)
                            if user:
                                return user
                except json.JSONDecodeError:
                    pass
        except (asyncio.TimeoutError, StopAsyncIteration):
            pass

        await self._send_error(ws, "AUTH_REQUIRED", "Authentication required")
        await ws.close()
        return None

    # -------------------------------------------------------------------------
    # Frame processing
    # -------------------------------------------------------------------------

    def _decode_text(self, data: dict[str, Any], *, protocol_version: int) -> Optional["InboundEvent"]:
        """Decode a client JSON message into an engine event.

        v1 (``protocol_version < 2``) ignores unknown keys; v2 forbids them (S6). Internal ``_*`` types are never
        accepted from clients.

        Returns:
            The event, or ``None`` for an unknown message type.

        Raises:
            pydantic.ValidationError: malformed payload (surfaced as ``INVALID_MESSAGE`` by the caller).
        """
        try:
            return parse_inbound(data, protocol_version=protocol_version)  # type: ignore[return-value]
        except UnknownMessageType:
            return None

    async def _process_text(self, ws: web.WebSocketResponse, ctx: _ConnCtx, data: dict[str, Any]) -> None:
        """start_session bootstraps the engine; every other message is decoded and handled."""
        msg_type = data.get("type", "")
        if msg_type == "start_session":
            if ctx.engine is not None:
                await self._send_error(ws, "ALREADY_STARTED", "Session already started")
                return
            await self._handle_start_session(
                ws=ws, data=data, session=ctx.state, request=ctx.request, audio_cache={}, ctx=ctx
            )
            return
        try:
            event = self._decode_text(data, protocol_version=ctx.state.protocol_version)
        except ValidationError:
            await self._send_error(ws, "INVALID_MESSAGE", f"Invalid '{msg_type}' message")
            return
        if event is None:
            await self._send_error(ws, "UNKNOWN_MESSAGE_TYPE", f"Unknown message type: {msg_type}")
            return
        if ctx.engine is None:
            if event.type == "ping":
                await ws.send_json({"type": "pong"})
            else:
                await self._send_error(ws, "SESSION_NOT_STARTED", "Call start_session first")
            return
        await self._perform(ws, ctx, ctx.engine.handle(event))

    async def _process_binary(self, ws: web.WebSocketResponse, ctx: _ConnCtx, audio: bytes) -> None:
        """Validate a binary audio frame (v1 guards), then hand it to the engine as ``AudioReceived``."""
        if ctx.engine is None:
            await self._send_error(ws, "SESSION_NOT_STARTED", "Call start_session first")
            return
        if self.transcriber is None:
            await self._send_error(
                ws, "TRANSCRIBER_UNAVAILABLE", "Audio transcription not configured"
            )
            return

        # Validate the incoming payload before touching the transcriber. A
        # too-small or non-container frame is an empty/instant recording or a
        # partial MediaRecorder chunk — decoding it raises a cryptic libav EBML
        # error, so reject it here with an actionable message instead.
        suffix = _sniff_audio_suffix(audio)
        self.logger.debug(
            "Received audio frame: %d bytes, magic=%s, detected=%s",
            len(audio),
            audio[:8].hex(" ") if audio else "(empty)",
            suffix or "unknown",
        )
        if len(audio) < _MIN_AUDIO_BYTES:
            await self._send_error(
                ws,
                "EMPTY_AUDIO",
                "No audio captured. Hold the record button and speak, then "
                "release to send.",
            )
            return
        if suffix is None:
            await self._send_error(
                ws,
                "UNSUPPORTED_AUDIO",
                "Unrecognized audio format. Send a complete WebM, OGG, MP4 or "
                "WAV recording as a single binary frame.",
            )
            return
        event = AudioReceived(type="_audio", audio=audio, mime=_AUDIO_MIME_BY_SUFFIX.get(suffix))
        await self._perform(ws, ctx, ctx.engine.handle(event))

    # -------------------------------------------------------------------------
    # Session bootstrap
    # -------------------------------------------------------------------------


    async def _handle_start_session(
        self,
        *,
        ws: web.WebSocketResponse,
        data: dict[str, Any],
        session: AudioSessionState,
        request: web.Request,
        audio_cache: dict[int, str],
        ctx: Optional[_ConnCtx] = None,
    ) -> None:
        """Load the form with the URL tenant, build manifest + engine, feed ``StartSession``."""
        form_uid = data.get("form_uid") or session.form_uid
        locale = data.get("locale", "en")
        if ctx is None:
            ctx = _ConnCtx(request=request, user=None, tenant=request.match_info.get("tenant"), state=session)

        # Decode the start message first. v1 clients send ``form_id`` (or nothing): the URL ``form_uid`` is used.
        try:
            start = parse_inbound(
                {**data, "type": "start_session", "form_uid": form_uid},
                protocol_version=int(data.get("protocol_version", 1) or 1),
            )
        except ValueError:  # pydantic.ValidationError, UnknownMessageType, bad protocol_version
            await self._send_error(ws, "INVALID_MESSAGE", "Invalid 'start_session' message")
            return
        assert isinstance(start, StartSession)

        # Build the per-session config from the start_session payload (FEAT-236),
        # falling back to defaults for any omitted key.
        config = self._build_session_config(form_uid, locale, data)
        session.config = config

        # Load form — tenant-scoped by the declaration validated in
        # handle_websocket (FEAT-421). `request.match_info["tenant"]` is
        # guaranteed non-empty here: handle_websocket closes the socket
        # before the message loop (and thus before start_session can ever
        # be dispatched) when the tenant is missing.
        declared_tenant = request.match_info.get("tenant")
        form = await self.registry.get(form_uid, tenant=declared_tenant)
        if form is None:
            await self._send_error(ws, "FORM_NOT_FOUND", f"Form '{form_uid}' not found")
            return
        if form.tenant != declared_tenant:
            # Defense-in-depth: registry.get() is already tenant-scoped, so
            # this should never fire — see the equivalent
            # FormAPIHandler._assert_form_tenant (TASK-2202). Close rather
            # than serve the form; never a 403 (existence oracle).
            self.logger.warning(
                "Cross-tenant audio session blocked: form_uid=%s form.tenant=%s "
                "declared=%s",
                form_uid,
                form.tenant,
                declared_tenant,
            )
            await self._send_error(
                ws, "TENANT_MISMATCH", "Form belongs to a different tenant."
            )
            await ws.close(code=1008, message=b"tenant_mismatch")
            return

        # Build manifest (the question cap is applied by the planner, not here).
        renderer = AudioFormRenderer(synthesizer=self.synthesizer)
        questions = renderer.split_into_questions(form, locale=locale)

        def _resolve_str(v: Any) -> str:
            if isinstance(v, str):
                return v
            if isinstance(v, dict):
                return v.get(locale) or v.get("en") or next(iter(v.values()), "")
            return str(v) if v else ""

        form_title = _resolve_str(form.title)
        manifest = AudioFormManifest(
            form_uid=form_uid,
            title=form_title,
            total_questions=len(questions),
            questions=questions,
            ws_endpoint=f"/api/v1/{declared_tenant}/forms/{form_uid}/audio/ws",
            locale=locale,
        )

        session.form_uid = form_uid
        session.manifest = manifest
        session.current_index = 0
        session.tenant = declared_tenant

        deps: dict[str, Any] = {
            "form": form, "manifest": manifest, "cfg": resolve_voice_config(form, config),
            "narrator": Narrator(locale), "lexicon": load_lexicon(locale), "state": session,
            "llm_cfg": form.llm_validation,
        }
        store = self._session_store
        if start.resume_session_id:
            if store is None:
                await self._send_error(ws, "RESUME_UNAVAILABLE", "Session resume is not available")
                return
            try:
                snap = await store.load(form_uid, start.resume_session_id)
            except ResumeUnavailable:
                snap = None
            if snap is None:
                await self._send_error(ws, "RESUME_UNAVAILABLE", "Session resume is not available")
                return
            if not await store.claim_active(session.user_id, start.resume_session_id):
                await self._send_error(ws, "SESSION_ACTIVE", "Another session is already active")
                return
            engine = AudioFormSession.from_snapshot(snap, **deps)
            ctx.revision = snap.revision
        else:
            if store is not None and not await store.claim_active(session.user_id, session.session_id):
                await self._send_error(ws, "SESSION_ACTIVE", "Another session is already active")
                return
            engine = AudioFormSession(**deps)

        ctx.form = form
        ctx.engine = engine
        ctx.prefetch = start.prefetch
        segment_synth: Any = self.synthesizer
        if segment_synth is None and self._auto_synthesize:
            segment_synth = _AutoSynthAdapter(self, ctx.state)
        ctx.segments = AudioSegmentCache(segment_synth, lock=_SYNTH_LOCK)
        opening = engine.handle(start)
        if start.resume_session_id and any(
            isinstance(o, Error) and o.code in ("RESUME_STALE", "RESUME_FORBIDDEN") for o in opening
        ):
            # The marker was claimed before the engine validated user/tenant/version: give it back.
            await store.release_active(session.user_id, start.resume_session_id)
        await self._perform(ws, ctx, opening)

    def _build_session_config(
        self,
        form_uid: str,
        locale: str,
        data: dict[str, Any],
    ) -> AudioSessionConfig:
        """Build an AudioSessionConfig from the start_session payload (FEAT-236).

        Only the documented keys are read; any omitted key uses the model
        default. Invalid values fall back to defaults rather than failing the
        session.

        Args:
            form_uid: The immutable UUID of the form being started (FEAT-389).
            locale: Resolved session locale.
            data: The raw start_session message payload.

        Returns:
            A populated AudioSessionConfig.
        """
        kwargs: dict[str, Any] = {"form_uid": form_uid, "locale": locale}
        for key in (
            "tts_backend",
            "tts_voice",
            "tts_mime_format",
            "auto_advance",
            "enumerate_options",
            "stt_confirm_threshold",
        ):
            if key in data and data[key] is not None:
                kwargs[key] = data[key]
        try:
            return AudioSessionConfig(**kwargs)
        except Exception as exc:  # noqa: BLE001 — never fail the session on config
            self.logger.warning(
                "Invalid audio session config (%s); using defaults", exc
            )
            return AudioSessionConfig(form_uid=form_uid, locale=locale)

    # -------------------------------------------------------------------------
    # Outbound performance (I/O mapping)
    # -------------------------------------------------------------------------

    async def _perform(self, ws: web.WebSocketResponse, ctx: _ConnCtx, outbound: list["Outbound"]) -> None:
        """Perform outbound items in order; I/O results are fed back into the engine (iteratively)."""
        assert ctx.engine is not None
        queue = list(outbound)
        while queue and not ctx.closed:
            item = queue.pop(0)
            feedback = await self._perform_one(ws, ctx, item)
            if feedback is not None:
                queue[:0] = ctx.engine.handle(feedback)  # results run before the remaining items

    async def _perform_one(
        self, ws: web.WebSocketResponse, ctx: _ConnCtx, item: "Outbound"
    ) -> Optional["InboundEvent"]:
        """One mapping-table row; returns the event to feed back, or None for wire messages."""
        engine = ctx.engine
        assert engine is not None
        state = ctx.state
        form = ctx.form
        assert form is not None

        if not is_io_request(item):
            await self._send_wire(ws, ctx, item)
            if isinstance(item, (AnswerAccepted, AnswerCleared)):
                await self._mirror_partial(ctx, item)
            if isinstance(item, SessionEnded):
                await self._release_session(ctx)
                ctx.closed = True
                await ws.close()
            elif isinstance(item, FormComplete):
                await self._release_session(ctx)
            return None

        if isinstance(item, Synthesize):
            await self._do_synthesize(ws, ctx, item)
            return None

        if isinstance(item, Replan):
            plan, delta = await engine.planner.replan(state.answers, locale=state.locale)
            return PlanReady(type="_plan_ready", plan=list(plan), delta=delta.model_dump(mode="json"))

        if isinstance(item, Transcribe):
            return await self._do_transcribe(item, ctx)

        if isinstance(item, StoreBlob):
            if self._blob_storage is None:
                return None
            field_def = next((f for f in form.iter_fields_recursive() if f.field_id == item.field_id), None)
            if field_def is None:
                return None
            try:
                blob_ref = await store_recording(
                    self._blob_storage, audio=item.audio, mime=item.mime, form=form, field=field_def,
                    session_id=state.session_id, submission_id=state.submission_id, tenant=ctx.tenant,
                )
            except Exception as exc:  # noqa: BLE001 — recordings are best-effort evidence
                self.logger.warning("Recording storage failed for field %s: %s", item.field_id, type(exc).__name__)
                return IOFailed(type="_io_failed", request=item.type, code="BLOB_STORE_FAILED")
            return BlobStored(type="_blob_stored", field_id=item.field_id, blob_ref=blob_ref, version=item.version)

        if isinstance(item, DeleteBlob):
            if self._blob_storage is not None:
                try:
                    await delete_recording(self._blob_storage, item.blob_ref)
                except Exception as exc:  # noqa: BLE001 — best effort
                    self.logger.warning("Recording delete failed: %s", type(exc).__name__)
            return None

        if isinstance(item, SaveSnapshot):
            if engine.state.phase in (Phase.COMPLETE, Phase.ABORTED):
                return None  # the session was released: a late save would only lose its compare-and-set
            await self._save_snapshot(ws, ctx, AudioSnapshot.model_validate(item.snapshot))
            return None

        if isinstance(item, RunPlausibility):
            return await self._do_plausibility(ctx, item)

        if isinstance(item, Submit):
            return await self._do_submit(ctx, item)

        self.logger.warning("Unhandled outbound item: %s", type(item).__name__)
        return None

    async def _send_wire(self, ws: web.WebSocketResponse, ctx: _ConnCtx, msg: "Outbound") -> None:
        """Encode and send one wire message (v1-only suppressed messages are skipped)."""
        if isinstance(msg, Question) and msg.voice_mode == VoiceMode.VISUAL_FALLBACK.value and not msg.fallback_html:
            manifest_q = self._manifest_question(ctx, msg.field_id)
            if manifest_q is not None:
                fallback = await self._build_fallback_html(manifest_q, ctx.state.config)
                msg = msg.model_copy(update={"fallback_html": fallback})
        wire = self._encode(ctx, msg)
        if wire:
            await ws.send_json(wire)

    @staticmethod
    def _manifest_question(ctx: _ConnCtx, field_id: str) -> Optional[AudioQuestion]:
        """The manifest question for ``field_id`` (or None)."""
        if ctx.engine is None:
            return None
        return next((q for q in ctx.engine.manifest.questions if q.field_id == field_id), None)

    def _encode(self, ctx: _ConnCtx, msg: "Outbound") -> dict[str, Any]:
        """Wire dict for one message; v1 clients get the FEAT-236 shapes (and base64 audio on question).

        Returns an empty dict when the message must not be sent (v2-only messages for a v1 client).
        """
        wire: dict[str, Any] = msg.to_wire()  # type: ignore[union-attr]
        v2 = ctx.state.protocol_version >= 2
        mtype = wire.get("type")
        if v2:
            if mtype == "question" and ctx.inline_audio:
                self._attach_audio(ctx, wire)
            return wire
        if mtype in _V2_ONLY_TYPES:
            return {}
        if mtype == "session_started":
            wire.pop("protocol_version", None)
        elif mtype == "question":
            for key in _V2_QUESTION_KEYS:
                wire.pop(key, None)
            self._attach_audio(ctx, wire)
        elif mtype == "answer_accepted":
            q = self._manifest_question(ctx, wire.get("field_id", ""))
            wire.pop("matched", None)
            wire.pop("blob_ref", None)
            if q is not None and q.sensitive:
                wire.pop("value", None)  # v1: a sensitive value is never echoed
            elif isinstance(wire.get("value"), list):
                wire["value"] = ",".join(str(v) for v in wire["value"])
        elif mtype == "confirm_request":
            wire.pop("matched", None)
            wire.pop("alternatives", None)
        elif mtype == "form_complete":
            wire.pop("stored_in", None)
            wire.pop("plausibility_summary", None)
            answers = ctx.engine.state.answers if ctx.engine is not None else {}
            wire["answers"] = {
                fid: {"value": value, "source": answers[fid].source if fid in answers else "text"}
                for fid, value in (wire.get("answers") or {}).items()
            }
        return wire

    def _attach_audio(self, ctx: _ConnCtx, wire: dict[str, Any]) -> None:
        """Attach the base64 narration of a question (never for sensitive questions)."""
        if wire.get("sensitive"):
            return
        q = self._manifest_question(ctx, wire.get("field_id", ""))
        audio = ctx.v1_audio.get(str(q.field_uid)) if q is not None else None
        if audio:
            wire["audio"] = base64.b64encode(audio).decode()

    # -------------------------------------------------------------------------
    # I/O requests
    # -------------------------------------------------------------------------

    @staticmethod
    def _segment_kind(key: str) -> str:
        """Header ``kind`` for a narration segment key."""
        if key.startswith("review:"):
            return "review"
        if key.endswith(":hint"):
            return "hint"
        if key.endswith(":options"):
            return "options"
        if key.startswith("q:"):
            return "question"
        return "system"

    async def _synth_items(self, ctx: _ConnCtx, items: dict[str, str]) -> dict[str, bytes]:
        """Synthesize ``items`` (key → text); failures degrade to missing keys (text-only)."""
        if not items:
            return {}
        state = ctx.state
        if ctx.segments is not None and ctx.segments.synthesizer is not None and ctx.form is not None:
            cfg = ctx.engine.cfg if ctx.engine is not None else None
            return await ctx.segments.ensure(
                items,
                locale=state.locale,
                voice=getattr(cfg, "tts_voice", None),
                form_uid=str(ctx.form.form_uid),
                version=str(ctx.form.version),
            )
        out: dict[str, bytes] = {}
        if self._auto_synthesize:
            language = state.locale if state.locale != "en" else None
            for key, text in items.items():
                if key.startswith("pause:") or not text.strip():
                    continue
                audio = await self._synthesize(text, config=state.config, language=language, session=state)
                if audio:
                    out[key] = audio
        return out

    async def _do_synthesize(self, ws: web.WebSocketResponse, ctx: _ConnCtx, item: Synthesize) -> None:
        """v2: send ``audio_segment`` header + binary frame per key; v1/inline: keep bytes for ``question``."""
        engine = ctx.engine
        assert engine is not None
        if ctx.inline_audio:
            groups: dict[str, list[str]] = {}
            for key in item.keys:
                parts = key.split(":")
                if len(parts) == 3 and parts[0] == "q" and parts[2] in ("label", "hint", "options"):
                    groups.setdefault(parts[1], []).append(item.texts.get(key, ""))
            sensitive = {str(q.field_uid) for q in engine.manifest.questions if q.sensitive}
            combined = {
                f"v1:{uid}": " ".join(t for t in texts if t.strip())
                for uid, texts in groups.items()
                if uid not in sensitive
            }
            audio = await self._synth_items(ctx, combined)
            for key, data in audio.items():
                ctx.v1_audio[key[len("v1:"):]] = data
            return
        audio = await self._synth_items(ctx, {k: item.texts[k] for k in item.keys if k in item.texts})
        mime = ctx.segments.mime() if ctx.segments is not None else "audio/wav"
        if not isinstance(mime, str):
            mime = "audio/wav"
        for key in item.keys:
            data = audio.get(key)
            if not data:
                continue
            header = AudioSegment(key=key, mime=mime, kind=self._segment_kind(key), text=item.texts.get(key, ""))
            await ws.send_json(header.to_wire())
            await ws.send_bytes(data)

    async def _do_transcribe(self, item: Transcribe, ctx: _ConnCtx) -> "InboundEvent":
        """Temp file → STT; returns ``TranscriptReady`` or ``IOFailed`` (never logs transcripts)."""
        if self.transcriber is None:
            return IOFailed(
                type="_io_failed", request=item.type, code="TRANSCRIBER_UNAVAILABLE",
                detail="Audio transcription not configured",
            )
        suffix = _sniff_audio_suffix(item.audio) or ".webm"
        tmp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, prefix="audio_form_") as tmp:
                tmp.write(item.audio)
                tmp_path = Path(tmp.name)
            locale = ctx.state.locale
            try:
                result = await self.transcriber.transcribe(tmp_path, language=locale if locale != "en" else None)
            except Exception as exc:  # noqa: BLE001 — surface decode failures cleanly
                # A malformed/truncated container (e.g. a partial recording) raises deep inside libav.
                self.logger.warning(
                    "Failed to decode/transcribe audio frame (%d bytes, %s): %s", len(item.audio), suffix, exc
                )
                return IOFailed(
                    type="_io_failed", request=item.type, code="AUDIO_DECODE_ERROR",
                    detail="Could not decode the audio. Please re-record the answer.",
                )
        finally:
            if tmp_path is not None and tmp_path.exists():
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        confidence = getattr(result, "confidence", None)
        language = getattr(result, "language", None)
        seconds = getattr(result, "duration_seconds", None)
        return TranscriptReady(
            type="_transcript",
            field_id=item.field_id,
            text=str(result.text),
            language=language if isinstance(language, str) else None,
            confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
            audio_mime=item.mime or _AUDIO_MIME_BY_SUFFIX.get(suffix, "audio/webm"),
            audio_bytes_len=len(item.audio),
            duration_ms=int(seconds * 1000) if isinstance(seconds, (int, float)) else None,
        )

    def _checker_for(self, form: "FormSchema", *, session_id: str = "") -> AnswerPlausibilityChecker:
        """Per-session plausibility checker built from the form's own ``llm_validation`` config."""
        checker = self._checkers.get(session_id)
        if checker is None:
            client = self._llm_client_getter() if self._llm_client_getter is not None else None
            checker = AnswerPlausibilityChecker(client, config=form.llm_validation or LLMValidationConfig())
            self._checkers[session_id] = checker
        return checker

    async def _do_plausibility(self, ctx: _ConnCtx, item: RunPlausibility) -> "InboundEvent":
        """Run the plausibility batch; ``PlausibilityBlocked`` / failures become a ``blocked`` report."""
        engine, form = ctx.engine, ctx.form
        assert engine is not None and form is not None
        sensitive = {q.field_id for q in engine.manifest.questions if q.sensitive}
        scalars = unwrap_voice({
            fid: a.value for fid, a in ctx.state.answers.items() if a.value is not None and fid not in sensitive
        })
        checker = self._checker_for(form, session_id=ctx.state.session_id)
        try:
            report = await checker.check(form, scalars, locale=ctx.state.locale, fields=item.fields)
        except PlausibilityBlocked as exc:
            report = PlausibilityReport(status="blocked", reason=exc.reason, threshold=checker.config.threshold)
        except Exception as exc:  # noqa: BLE001 — never fail the session on the advisory check
            self.logger.warning("Plausibility check failed: %s", type(exc).__name__)
            report = PlausibilityReport(status="blocked", reason="check failed", threshold=checker.config.threshold)
        return PlausibilityDone(type="_plausibility_done", report=report)

    def _pipeline_for(self) -> SubmissionPipeline:
        """The shared pipeline, or a lazily built one (the engine hands its own plausibility report to submit)."""
        if self._pipeline is None:
            self._pipeline = SubmissionPipeline(
                validator=self.validator,
                submission_storage=self._submission_storage,
                forwarder=None,
                partial_store=None,
                plausibility=None,
            )
        return self._pipeline

    def _auth_context(self, user: Optional["AuthenticatedUser"]) -> AuthContext:
        """S11: AuthenticatedUser → AuthContext for the submission pipeline."""
        if user is None:
            return AuthContext(scheme="none")
        scheme = "bearer" if self._token_validator is not None else "none"
        return AuthContext(scheme=scheme, claims=dict(getattr(user, "raw_payload", {}) or {}))

    async def _do_submit(self, ctx: _ConnCtx, item: Submit) -> "InboundEvent":
        """Submit through the SubmissionPipeline (URL tenant, auth context); map rejections to ``SubmitDone``."""
        form = ctx.form
        assert form is not None
        state = ctx.state
        data = dict(item.data)
        # A visual-fallback REST answer arrives as the client's plain reference; the REST validator wants the
        # ``{"answer", "blob_ref"}`` shape, so wrap scalars (a dict is already in the validator's shape).
        for q in ctx.engine.manifest.questions if ctx.engine is not None else []:
            if q.field_type == "rest" and q.field_id in data and not isinstance(data[q.field_id], dict):
                data[q.field_id] = {"answer": data[q.field_id], "blob_ref": None}
        try:
            outcome = await self._pipeline_for().submit(
                form,
                data,
                tenant=ctx.tenant,
                user_id=state.user_id,
                locale=state.locale,
                context=item.context,
                extra_data=None,
                auth_context=self._auth_context(ctx.user),
                merge_session_id=state.session_id,
                plausibility=state.plausibility,
                submission_id=state.submission_id,
            )
        except ValidationFailed as exc:
            return SubmitDone(type="_submit_done", outcome={"errors": exc.errors})
        except PlausibilityBlocked as exc:
            return IOFailed(type="_io_failed", request=item.type, code="PLAUSIBILITY_UNAVAILABLE", detail=exc.reason)
        except Exception as exc:  # noqa: BLE001 — sink/lifecycle failures: surface and re-ask the last question
            self.logger.warning("Audio submission failed: %s", type(exc).__name__)
            return IOFailed(
                type="_io_failed", request=item.type, code="SUBMIT_FAILED", detail="The form could not be submitted."
            )
        return SubmitDone(type="_submit_done", outcome={
            "submission_id": outcome.submission_id,
            "stored_in": outcome.stored_in,
            "forwarded": outcome.forwarded,
        })

    # -------------------------------------------------------------------------
    # Snapshots
    # -------------------------------------------------------------------------

    async def _mirror_partial(self, ctx: _ConnCtx, item: "AnswerAccepted | AnswerCleared") -> None:
        """AC16: keep ``/partial`` in step with the audio session (scalar answers only, never sensitive ones).

        Partials are keyed like the HTTP routes: ``(form_uid, navigator-auth session id)`` → ``field_uid`` → value.
        """
        store = getattr(self._session_store, "partial_store", None)
        form, engine = ctx.form, ctx.engine
        if store is None or form is None or engine is None:
            return
        field = next((f for f in form.iter_fields_recursive() if f.field_id == item.field_id), None)
        if field is None:
            return
        http_session = None
        try:
            if "session" in ctx.request:
                http_session = ctx.request["session"].get("id")
        except Exception:  # noqa: BLE001 — no navigator session on this connection
            http_session = None
        session_id = str(http_session) if http_session else ctx.state.session_id
        uid = str(field.field_uid)
        try:
            if isinstance(item, AnswerCleared):
                await store.remove_keys(str(form.form_uid), session_id, [uid])
                return
            if any(q.sensitive and q.field_id == item.field_id for q in engine.manifest.questions):
                return
            await store.save(str(form.form_uid), session_id, {uid: item.value})
        except Exception as exc:  # noqa: BLE001 — the mirror is best effort, never fails the session
            self.logger.warning("Partial mirror failed: %s", type(exc).__name__)

    async def _save_snapshot(self, ws: web.WebSocketResponse, ctx: _ConnCtx, snap: AudioSnapshot) -> None:
        """Compare-and-set save; a lost race surfaces ``RESUME_CONFLICT`` and ends the connection."""
        store = self._session_store
        if store is None:
            return
        try:
            revision = await store.save(
                ctx.state.form_uid, ctx.state.session_id, snap, expected_revision=ctx.revision
            )
        except SnapshotConflict:
            await self._send_error(ws, "RESUME_CONFLICT", "This session was modified from another connection")
            ctx.closed = True
            await ws.close()
            return
        ctx.revision = max(ctx.revision, revision)

    async def _autosave(self, ctx: _ConnCtx, *, final: bool = False) -> None:
        """Save the engine snapshot (no-op without a store); release the session once COMPLETE / ABORTED."""
        store, engine = self._session_store, ctx.engine
        if store is None or engine is None:
            return
        phase = engine.state.phase
        if phase in (Phase.COMPLETE, Phase.ABORTED):
            await self._release_session(ctx)
            return
        if phase == Phase.IDLE or ctx.closed:
            return
        try:
            revision = await store.save(
                ctx.state.form_uid, ctx.state.session_id, engine.snapshot(), expected_revision=ctx.revision
            )
        except SnapshotConflict:
            self.logger.warning("Snapshot conflict for session %s (final=%s)", ctx.state.session_id, final)
            return
        ctx.revision = max(ctx.revision, revision)

    async def _release_session(self, ctx: _ConnCtx) -> None:
        """Delete the snapshot and active marker of a finished session (best effort)."""
        store = self._session_store
        if store is None:
            return
        try:
            await store.delete(ctx.state.form_uid, ctx.state.session_id, user_id=ctx.state.user_id)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Session release failed: %s", type(exc).__name__)

    # -------------------------------------------------------------------------
    # TTS synthesis
    # -------------------------------------------------------------------------

    async def _synthesize(
        self,
        text: str,
        *,
        config: Optional[AudioSessionConfig] = None,
        language: Optional[str] = None,
        session: Optional[AudioSessionState] = None,
    ) -> Optional[bytes]:
        """Synthesize TTS audio for ``text``, degrading gracefully (FEAT-236).

        An explicitly-injected ``self.synthesizer`` (tests/overrides) takes
        precedence. Otherwise, when ``auto_synthesize`` is enabled, the
        SuperTonic-first fallback is used, reusing a per-session synthesizer when
        a ``session`` is given. Any backend failure degrades to text-only
        (returns ``None``) — never raises.
        """
        if self.synthesizer is not None:
            try:
                result = await self.synthesizer.synthesize(text, language=language)
                return result.audio
            except Exception as exc:  # noqa: BLE001 — graceful degradation
                self.logger.warning("Injected TTS synthesizer failed: %s", exc)
                return None
        if self._auto_synthesize:
            if session is None:
                # No session to key a cache on → one-shot fallback.
                return await synthesize_with_fallback(
                    text, config=config, language=language
                )
            return await self._auto_synthesize_cached(
                session, text, config=config, language=language
            )
        return None

    async def _auto_synthesize_cached(
        self,
        session: AudioSessionState,
        text: str,
        *,
        config: Optional[AudioSessionConfig] = None,
        language: Optional[str] = None,
    ) -> Optional[bytes]:
        """SuperTonic-first synthesis reusing a per-session backend (FEAT-236).

        Mirrors :func:`synthesize_with_fallback` but keeps the first
        working ``VoiceSynthesizer`` open and cached on the handler keyed by
        ``session_id`` so subsequent questions reuse the same backend instead of
        rebuilding it. Never raises — degrades to text-only (``None``).
        """
        sid = session.session_id
        cached = self._session_synths.get(sid)
        if cached is not None:
            try:
                result = await cached.synthesize(text, language=language)
                return result.audio
            except Exception as exc:  # noqa: BLE001 — rebuild on failure
                self.logger.warning(
                    "Cached TTS backend failed (%s); rebuilding", exc
                )
                await self._close_synth(cached)
                self._session_synths.pop(sid, None)

        try:
            from parrot.voice.tts.models import TTSConfig
            from parrot.voice.tts.synthesizer import VoiceSynthesizer
        except ImportError as exc:
            self.logger.warning(
                "parrot.voice TTS stack unavailable (%s); text-only", exc
            )
            return None

        preferred = config.tts_backend if config is not None else "supertonic"
        voice = config.tts_voice if config is not None else None
        mime_format = config.tts_mime_format if config is not None else "audio/wav"
        backends = [preferred] + [b for b in ("google",) if b != preferred]
        for backend in backends:
            candidate = VoiceSynthesizer(
                TTSConfig(backend=backend, voice=voice, mime_format=mime_format)
            )
            try:
                result = await candidate.synthesize(text, language=language)
                # Keep the working backend open for reuse this session.
                self._session_synths[sid] = candidate
                return result.audio
            except Exception as exc:  # noqa: BLE001 — never raise (FEAT-231)
                self.logger.warning("TTS backend %s unavailable: %s", backend, exc)
                await self._close_synth(candidate)
        return None

    async def _close_synth(self, synth: Any) -> None:
        """Close a VoiceSynthesizer, swallowing any teardown error."""
        try:
            await synth.close()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass


    async def _build_fallback_html(
        self,
        question: AudioQuestion,
        config: Optional[AudioSessionConfig],
    ) -> str:
        """Render single-field HTML for a VISUAL_FALLBACK question (FEAT-236).

        Uses the HTML5Renderer's per-field renderer when one exists for the
        field type, otherwise returns a minimal ``<input>`` and logs.
        """
        locale = config.locale if config is not None else "en"
        try:
            from ..core.options import FieldOption
            from ..core.schema import FormField
            from ..core.types import FieldType
            from ..renderers.html5 import HTML5Renderer

            field_type = FieldType(question.field_type)
            options = None
            if question.options:
                options = [
                    FieldOption(
                        value=opt.get("value", ""),
                        label=opt.get("label") or opt.get("value", ""),
                    )
                    for opt in question.options
                ]
            field = FormField(
                field_id=question.field_id,
                field_type=field_type,
                label=question.label,
                required=question.required,
                options=options,
            )
            renderer = HTML5Renderer()
            field_renderer = renderer._registry.get(field_type)
            if field_renderer is not None:
                rendered = await field_renderer.render(field, locale=locale)
                if rendered:
                    return str(rendered)
        except Exception as exc:  # noqa: BLE001 — never fail question delivery
            self.logger.warning(
                "Visual fallback render failed for field %s: %s",
                question.field_id,
                exc,
            )
        safe_field_id = html.escape(question.field_id, quote=True)
        return f'<input type="text" name="{safe_field_id}" />'

    # -------------------------------------------------------------------------
    # Error utilities
    # -------------------------------------------------------------------------

    async def _send_error(
        self,
        ws: web.WebSocketResponse,
        code: str,
        message: str,
    ) -> None:
        """Send an error message over the WebSocket.

        Args:
            ws: Active WebSocket.
            code: Machine-readable error code.
            message: Human-readable error description.
        """
        try:
            await ws.send_json({"type": "error", "code": code, "message": message})
        except Exception:
            pass
