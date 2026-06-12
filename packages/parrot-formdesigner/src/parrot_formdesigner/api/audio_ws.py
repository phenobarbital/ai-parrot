"""AudioFormWSHandler — WebSocket handler for interactive audio form sessions.

Manages a stateful audio Q&A session over WebSocket: one question at a time,
text or audio answers, TTS delivery, STT transcription, validation, and
final form submission.

WebSocket protocol (see spec §2 for full message definitions):
- Client sends JSON messages with a "type" field.
- Binary frames are treated as audio data for STT transcription.
- Server responds with JSON messages.

Authentication: JWT token extracted from Sec-WebSocket-Protocol header or
from the first "auth" type message. Unauthenticated connections receive an
error and are closed.

Added by FEAT-224 (FormDesigner Audio Renderer).
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional

from aiohttp import WSMsgType, web

from ..audio.models import (
    AudioAnswer,
    AudioFormManifest,
    AudioQuestion,
    AudioSessionConfig,
    AudioSessionState,
    VoiceMode,
)
from ..renderers.audio import (
    AudioFormRenderer,
    synthesize_with_fallback,
)

if TYPE_CHECKING:
    from parrot.core.ws_auth import AuthenticatedUser, TokenValidator
    from parrot.voice.tts.synthesizer import VoiceSynthesizer
    from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend

    from ..services.registry import FormRegistry
    from ..services.validators import FormValidator
    from ..services.submissions import FormSubmissionStorage

logger = logging.getLogger(__name__)

# Maximum audio questions per session (spec open question resolved: 10 max).
MAX_QUESTIONS = 10

# Client-facing placeholder used in lieu of a sensitive (e.g. password) value
# in transcription / confirm_request messages (FEAT-236).
_SENSITIVE_MASK = "[hidden]"


class AudioFormWSHandler:
    """WebSocket handler for interactive audio form sessions.

    Manages one stateful audio session per WebSocket connection:
    - JWT authentication via Sec-WebSocket-Protocol header or first message.
    - start_session: loads FormSchema, builds AudioFormManifest, sends Q1.
    - answer_text: validates text answer, stores it, advances to next question.
    - answer_audio: binary frame → temp file → STT transcription → validate.
    - skip_question, go_back, repeat_question, end_session navigation.
    - After last answer: submits form data, sends form_complete.

    Args:
        registry: FormRegistry to look up forms by ID.
        synthesizer: VoiceSynthesizer for TTS question audio.
        transcriber: FasterWhisperBackend for STT transcription.
        validator: FormValidator for answer validation.
        token_validator: TokenValidator for JWT authentication.
        submission_storage: Optional storage backend for form submissions.
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
        #   "/api/v1/forms/{form_id}/audio/ws",
        #   handler.handle_websocket
        # )
    """

    def __init__(
        self,
        registry: "FormRegistry",
        synthesizer: Optional["VoiceSynthesizer"],
        transcriber: Optional["FasterWhisperBackend"],
        validator: "FormValidator",
        *,
        token_validator: Optional["TokenValidator"] = None,
        submission_storage: Optional["FormSubmissionStorage"] = None,
        max_msg_size: int = 10 * 1024 * 1024,
        auto_synthesize: bool = False,
    ) -> None:
        """Initialize the AudioFormWSHandler."""
        self.registry = registry
        self.synthesizer = synthesizer
        self.transcriber = transcriber
        self.validator = validator
        self._token_validator = token_validator
        self._submission_storage = submission_storage
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
                ``{form_id}``.

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

        form_id = request.match_info.get("form_id", "")
        session = AudioSessionState(
            session_id=str(uuid.uuid4()),
            form_id=form_id,
            user_id=user.user_id,
        )

        # Per-session TTS audio cache: question index → base64 audio str
        _audio_cache: dict[int, str] = {}

        # Step 2: Message loop
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        await self._send_error(ws, "INVALID_JSON", "Invalid JSON message")
                        continue

                    msg_type = data.get("type", "")
                    try:
                        await self._dispatch_text(
                            ws, msg_type, data, session, request, _audio_cache
                        )
                    except Exception as exc:
                        self.logger.exception(
                            "Error handling message type=%s: %s", msg_type, exc
                        )
                        await self._send_error(ws, "INTERNAL_ERROR", str(exc))

                elif msg.type == WSMsgType.BINARY:
                    try:
                        await self._handle_answer_audio(
                            ws, msg.data, session, _audio_cache
                        )
                    except Exception as exc:
                        self.logger.exception(
                            "Error handling binary audio frame: %s", exc
                        )
                        await self._send_error(ws, "TRANSCRIPTION_ERROR", str(exc))

                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break

        finally:
            # Release any per-session synthesizer built lazily in auto mode.
            cached_synth = self._session_synths.pop(session.session_id, None)
            if cached_synth is not None:
                await self._close_synth(cached_synth)
            self.logger.debug(
                "AudioFormWSHandler: session %s closed", session.session_id
            )

        return ws

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
    # Text message dispatcher
    # -------------------------------------------------------------------------

    async def _dispatch_text(
        self,
        ws: web.WebSocketResponse,
        msg_type: str,
        data: dict[str, Any],
        session: AudioSessionState,
        request: web.Request,
        audio_cache: dict[int, str],
    ) -> None:
        """Dispatch a text JSON message to the appropriate handler method.

        Args:
            ws: Active WebSocket.
            msg_type: The "type" field of the incoming message.
            data: Full parsed message dict.
            session: Current session state.
            request: Original HTTP request (for tenant resolution).
            audio_cache: Per-session TTS audio cache.
        """
        handlers: dict[str, Any] = {
            "start_session": self._handle_start_session,
            "answer_text": self._handle_answer_text,
            "answer_selection": self._handle_answer_selection,
            "answer_payload": self._handle_answer_payload,
            "confirm_answer": self._handle_confirm_answer,
            "skip_question": self._handle_skip_question,
            "go_back": self._handle_go_back,
            "repeat_question": self._handle_repeat_question,
            "end_session": self._handle_end_session,
            "ping": self._handle_ping,
        }
        handler = handlers.get(msg_type)
        if handler is None:
            await self._send_error(
                ws, "UNKNOWN_MESSAGE_TYPE", f"Unknown message type: {msg_type}"
            )
            return

        # Pass common args; individual handlers accept **kwargs for flexibility.
        await handler(
            ws=ws,
            data=data,
            session=session,
            request=request,
            audio_cache=audio_cache,
        )

    # -------------------------------------------------------------------------
    # Message handlers
    # -------------------------------------------------------------------------

    def _build_session_config(
        self,
        form_id: str,
        locale: str,
        data: dict[str, Any],
    ) -> AudioSessionConfig:
        """Build an AudioSessionConfig from the start_session payload (FEAT-236).

        Only the documented keys are read; any omitted key uses the model
        default. Invalid values fall back to defaults rather than failing the
        session.

        Args:
            form_id: The form being started.
            locale: Resolved session locale.
            data: The raw start_session message payload.

        Returns:
            A populated AudioSessionConfig.
        """
        kwargs: dict[str, Any] = {"form_id": form_id, "locale": locale}
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
            return AudioSessionConfig(form_id=form_id, locale=locale)

    async def _handle_start_session(
        self,
        *,
        ws: web.WebSocketResponse,
        data: dict[str, Any],
        session: AudioSessionState,
        request: web.Request,
        audio_cache: dict[int, str],
    ) -> None:
        """Handle start_session message: load form, build manifest, send Q1."""
        form_id = data.get("form_id") or session.form_id
        locale = data.get("locale", "en")

        # Build the per-session config from the start_session payload (FEAT-236),
        # falling back to defaults for any omitted key.
        config = self._build_session_config(form_id, locale, data)
        session.config = config

        # Load form
        form = await self.registry.get(form_id, tenant=None)
        if form is None:
            await self._send_error(ws, "FORM_NOT_FOUND", f"Form '{form_id}' not found")
            return

        # Build manifest
        renderer = AudioFormRenderer(synthesizer=self.synthesizer)
        questions = renderer.split_into_questions(form, locale=locale)

        if len(questions) > MAX_QUESTIONS:
            questions = questions[:MAX_QUESTIONS]
            self.logger.warning(
                "Form %s has >%d questions; truncating to %d",
                form_id, MAX_QUESTIONS, MAX_QUESTIONS,
            )


        def _resolve_str(v: Any) -> str:
            if isinstance(v, str):
                return v
            if isinstance(v, dict):
                return v.get(locale) or v.get("en") or next(iter(v.values()), "")
            return str(v) if v else ""

        form_title = _resolve_str(form.title)
        manifest = AudioFormManifest(
            form_id=form_id,
            title=form_title,
            total_questions=len(questions),
            questions=questions,
            ws_endpoint=f"/api/v1/forms/{form_id}/audio/ws",
            locale=locale,
        )

        session.form_id = form_id
        session.manifest = manifest
        session.current_index = 0

        # Pre-synthesize all questions only when an explicit synthesizer is
        # injected. In auto_synthesize mode questions are synthesized on demand
        # in _send_question (one at a time) to avoid bulk backend calls.
        if self.synthesizer is not None:
            await self._presynthize_to_cache(questions, audio_cache, locale=locale)

        await ws.send_json({
            "type": "session_started",
            "session_id": session.session_id,
            "total_questions": len(questions),
            "title": form_title,
        })

        # Deliver first question.
        if questions:
            await self._send_question(
                ws, questions[0], audio_cache, config=config, session=session
            )
        else:
            await self._finish_session(ws, session)

    async def _handle_answer_text(
        self,
        *,
        ws: web.WebSocketResponse,
        data: dict[str, Any],
        session: AudioSessionState,
        request: web.Request,
        audio_cache: dict[int, str],
    ) -> None:
        """Handle answer_text: validate, store, advance."""
        field_id = data.get("field_id", "")
        value = str(data.get("value", ""))

        accepted = await self._accept_answer(
            ws, session, field_id, value, source="text"
        )
        if accepted:
            await self._advance_session(ws, session, request, audio_cache)

    async def _handle_answer_selection(
        self,
        *,
        ws: web.WebSocketResponse,
        data: dict[str, Any],
        session: AudioSessionState,
        request: web.Request,
        audio_cache: dict[int, str],
    ) -> None:
        """Handle answer_selection for a PROMPT_SELECT question (FEAT-236).

        Accepts ``{field_id, value}`` (single) or ``{field_id, values: [...]}``
        (multi). The ``field_id`` must match the current question. Validates each
        value against the question's ``options`` and stores an
        ``AudioAnswer(source="selection")``. Multi values are stored as a
        comma-joined string.
        """
        field_id = data.get("field_id", "")
        question = await self._current_question(ws, session, field_id)
        if question is None:
            return  # error already sent by _current_question

        allowed = {opt.get("value") for opt in (question.options or [])}

        if "values" in data:
            raw_values = data.get("values") or []
            values = [str(v) for v in raw_values]
            if question.required and not values:
                await self._reject_answer(
                    ws, field_id, "Select at least one option"
                )
                return
            if allowed and any(v not in allowed for v in values):
                await self._reject_answer(
                    ws, field_id, "One or more selected values are not valid options"
                )
                return
            value = ",".join(values)
        else:
            value = str(data.get("value", ""))
            if allowed and value not in allowed:
                await self._reject_answer(
                    ws, field_id, f"'{value}' is not a valid option"
                )
                return

        accepted = await self._accept_answer(
            ws, session, field_id, value, source="selection"
        )
        if accepted:
            await self._advance_session(ws, session, request, audio_cache)

    async def _handle_answer_payload(
        self,
        *,
        ws: web.WebSocketResponse,
        data: dict[str, Any],
        session: AudioSessionState,
        request: web.Request,
        audio_cache: dict[int, str],
    ) -> None:
        """Handle answer_payload for a VISUAL_FALLBACK question (FEAT-236).

        Accepts ``{field_id, value}`` collected after the client completes the
        inline single-field visual render. The ``field_id`` must match the
        current question. Stores ``source="text"`` and advances. A required REST
        field can be completed this way.
        """
        field_id = data.get("field_id", "")
        if await self._current_question(ws, session, field_id) is None:
            return  # error already sent by _current_question
        value = str(data.get("value", ""))

        accepted = await self._accept_answer(
            ws, session, field_id, value, source="text"
        )
        if accepted:
            await self._advance_session(ws, session, request, audio_cache)

    async def _handle_confirm_answer(
        self,
        *,
        ws: web.WebSocketResponse,
        data: dict[str, Any],
        session: AudioSessionState,
        request: web.Request,
        audio_cache: dict[int, str],
    ) -> None:
        """Handle confirm_answer for a low-confidence transcript (FEAT-236).

        ``{field_id, confirmed: bool}`` — on ``true`` the pending transcript is
        stored and the session advances; on ``false`` the pending transcript is
        discarded and the SAME question is re-sent (no advance).
        """
        pending = session.pending
        if pending is None:
            await self._send_error(
                ws, "NO_PENDING_ANSWER", "No answer is awaiting confirmation"
            )
            return

        client_field_id = data.get("field_id", "")
        if client_field_id and client_field_id != pending.field_id:
            await self._send_error(
                ws,
                "FIELD_MISMATCH",
                f"confirm_answer for '{client_field_id}' but the pending "
                f"answer is for '{pending.field_id}'",
            )
            return

        confirmed = bool(data.get("confirmed", False))
        session.pending = None

        if confirmed:
            accepted = await self._accept_answer(
                ws, session, pending.field_id, pending.value,
                source="speech", confidence=pending.confidence,
                raw_transcript=pending.raw_transcript,
            )
            if accepted:
                await self._advance_session(ws, session, request, audio_cache)
        else:
            # Re-send the current (same) question; nothing is stored.
            if session.manifest is not None and session.current_index < len(
                session.manifest.questions
            ):
                current_q = session.manifest.questions[session.current_index]
                await self._send_question(
                    ws, current_q, audio_cache,
                    config=session.config, session=session,
                )

    async def _handle_answer_audio(
        self,
        ws: web.WebSocketResponse,
        audio_bytes: bytes,
        session: AudioSessionState,
        audio_cache: dict[int, str],
    ) -> None:
        """Handle binary audio frame: write to temp file, transcribe, validate."""
        if session.manifest is None:
            await self._send_error(ws, "SESSION_NOT_STARTED", "Call start_session first")
            return

        manifest = session.manifest
        if session.current_index >= len(manifest.questions):
            await self._send_error(ws, "SESSION_COMPLETE", "All questions answered")
            return

        current_q = manifest.questions[session.current_index]

        if self.transcriber is None:
            await self._send_error(
                ws, "TRANSCRIBER_UNAVAILABLE", "Audio transcription not configured"
            )
            return

        # Write audio bytes to a temp file for transcription.
        tmp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".ogg", delete=False, prefix="audio_form_"
            ) as tmp:
                tmp.write(audio_bytes)
                tmp_path = Path(tmp.name)

            result = await self.transcriber.transcribe(
                tmp_path,
                language=manifest.locale if manifest.locale != "en" else None,
            )

            transcript = result.text
            confidence = result.confidence

            # Never echo a sensitive (e.g. password) value back to the client;
            # the real transcript is still stored server-side (FEAT-236).
            display_text = _SENSITIVE_MASK if current_q.sensitive else transcript

            # Send transcription back to client.
            await ws.send_json({
                "type": "transcription",
                "field_id": current_q.field_id,
                "text": display_text,
                "confidence": confidence,
            })

            # Low-confidence read-back gate (FEAT-236): when the STT confidence
            # is below the configured threshold, hold the transcript as PENDING
            # and ask the client to confirm before storing. Do NOT advance.
            threshold = (
                session.config.stt_confirm_threshold
                if session.config is not None
                else 0.6
            )
            if confidence is None:
                self.logger.debug(
                    "STT returned no confidence for field %s; auto-advancing",
                    current_q.field_id,
                )
            if confidence is not None and confidence < threshold:
                session.pending = AudioAnswer(
                    field_id=current_q.field_id,
                    value=transcript,
                    source="speech",
                    confidence=confidence,
                    raw_transcript=transcript,
                )
                await ws.send_json({
                    "type": "confirm_request",
                    "field_id": current_q.field_id,
                    "transcript": display_text,
                    "confidence": confidence,
                })
                return

            # Validate and store the answer.
            accepted = await self._accept_answer(
                ws, session, current_q.field_id, transcript,
                source="speech", confidence=confidence,
                raw_transcript=transcript,
            )
            if accepted:
                # Need to advance — but we can't pass request/audio_cache here
                # easily since this is called from the binary handler.
                # Use a minimal advance that doesn't need request.
                await self._advance_session_no_request(ws, session, audio_cache)

        finally:
            if tmp_path and tmp_path.exists():
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    async def _handle_skip_question(
        self,
        *,
        ws: web.WebSocketResponse,
        data: dict[str, Any],
        session: AudioSessionState,
        request: web.Request,
        audio_cache: dict[int, str],
    ) -> None:
        """Handle skip_question: advance past optional, reject for required."""
        if session.manifest is None:
            await self._send_error(ws, "SESSION_NOT_STARTED", "Call start_session first")
            return

        manifest = session.manifest
        if session.current_index >= len(manifest.questions):
            return

        current_q = manifest.questions[session.current_index]
        if current_q.required:
            await ws.send_json({
                "type": "answer_rejected",
                "field_id": current_q.field_id,
                "error": "This field is required and cannot be skipped",
            })
            return

        session.current_index += 1
        await self._advance_session(ws, session, request, audio_cache)

    async def _handle_go_back(
        self,
        *,
        ws: web.WebSocketResponse,
        data: dict[str, Any],
        session: AudioSessionState,
        request: web.Request,
        audio_cache: dict[int, str],
    ) -> None:
        """Handle go_back: navigate to a previous question."""
        if session.manifest is None:
            await self._send_error(ws, "SESSION_NOT_STARTED", "Call start_session first")
            return

        to_index = data.get("to_index")
        if to_index is not None:
            target = int(to_index)
        else:
            target = max(0, session.current_index - 1)

        manifest = session.manifest
        if target < 0 or target >= len(manifest.questions):
            await self._send_error(
                ws, "INVALID_INDEX", f"Index {target} out of range"
            )
            return

        session.current_index = target
        await self._send_question(
            ws, manifest.questions[target], audio_cache,
            config=session.config, session=session,
        )

    async def _handle_repeat_question(
        self,
        *,
        ws: web.WebSocketResponse,
        data: dict[str, Any],
        session: AudioSessionState,
        request: web.Request,
        audio_cache: dict[int, str],
    ) -> None:
        """Handle repeat_question: re-send TTS audio for current question."""
        if session.manifest is None:
            await self._send_error(ws, "SESSION_NOT_STARTED", "Call start_session first")
            return

        manifest = session.manifest
        if session.current_index >= len(manifest.questions):
            return

        current_q = manifest.questions[session.current_index]
        await self._send_question(
            ws, current_q, audio_cache, config=session.config, session=session
        )

    async def _handle_end_session(
        self,
        *,
        ws: web.WebSocketResponse,
        data: dict[str, Any],
        session: AudioSessionState,
        request: web.Request,
        audio_cache: dict[int, str],
    ) -> None:
        """Handle end_session: abort the session."""
        await ws.send_json({"type": "session_ended", "session_id": session.session_id})
        await ws.close()

    async def _handle_ping(
        self,
        *,
        ws: web.WebSocketResponse,
        data: dict[str, Any],
        session: AudioSessionState,
        request: web.Request,
        audio_cache: dict[int, str],
    ) -> None:
        """Handle ping keep-alive."""
        await ws.send_json({"type": "pong"})

    # -------------------------------------------------------------------------
    # Answer validation helpers
    # -------------------------------------------------------------------------

    def _question_for_field(
        self,
        session: AudioSessionState,
        field_id: str,
    ) -> Optional[AudioQuestion]:
        """Return the manifest question for ``field_id`` (or None)."""
        if session.manifest is None:
            return None
        for q in session.manifest.questions:
            if q.field_id == field_id:
                return q
        return None

    async def _current_question(
        self,
        ws: web.WebSocketResponse,
        session: AudioSessionState,
        field_id: str,
    ) -> Optional[AudioQuestion]:
        """Return the current question iff ``field_id`` matches it.

        Enforces in-order answering for the FEAT-236 hybrid handlers: sends an
        error and returns None when the session has not started, is complete, or
        the client answered a field that is not the current question.
        """
        if session.manifest is None:
            await self._send_error(
                ws, "SESSION_NOT_STARTED", "Call start_session first"
            )
            return None
        if session.current_index >= len(session.manifest.questions):
            await self._send_error(ws, "SESSION_COMPLETE", "All questions answered")
            return None
        current = session.manifest.questions[session.current_index]
        if field_id != current.field_id:
            await self._send_error(
                ws,
                "WRONG_FIELD",
                f"Expected an answer for '{current.field_id}', got '{field_id}'",
            )
            return None
        return current

    async def _reject_answer(
        self,
        ws: web.WebSocketResponse,
        field_id: str,
        reason: str,
    ) -> None:
        """Send an answer_rejected message for ``field_id``."""
        await ws.send_json({
            "type": "answer_rejected",
            "field_id": field_id,
            "reason": reason,
        })

    async def _accept_answer(
        self,
        ws: web.WebSocketResponse,
        session: AudioSessionState,
        field_id: str,
        value: str,
        *,
        source: Literal["text", "speech", "selection"] = "text",
        confidence: Optional[float] = None,
        raw_transcript: Optional[str] = None,
    ) -> bool:
        """Validate and store an answer for the current question.

        Args:
            ws: Active WebSocket.
            session: Current session state.
            field_id: Field ID being answered.
            value: Answer value string.
            source: 'text', 'speech' or 'selection'.
            confidence: STT confidence (speech only).
            raw_transcript: Raw transcript (speech only).

        Returns:
            True if accepted, False if rejected (error message sent).
        """
        answer = AudioAnswer(
            field_id=field_id,
            value=value,
            source=source,
            confidence=confidence,
            raw_transcript=raw_transcript,
        )

        # Look up the answered question (for required + sensitive handling).
        question = self._question_for_field(session, field_id)

        # Validate the answer if a form registry and manifest are available.
        if self.validator is not None and session.manifest is not None:
            if question is not None and question.required and not value.strip():
                await ws.send_json({
                    "type": "answer_rejected",
                    "field_id": field_id,
                    "reason": "This field is required",
                })
                return False

        session.answers[field_id] = answer

        # Never echo a sensitive (e.g. password) value back to the client.
        ack: dict[str, Any] = {
            "type": "answer_accepted",
            "field_id": field_id,
            "source": source,
        }
        if question is None or not question.sensitive:
            ack["value"] = value
        await ws.send_json(ack)
        return True

    # -------------------------------------------------------------------------
    # Session advancement
    # -------------------------------------------------------------------------

    async def _advance_session(
        self,
        ws: web.WebSocketResponse,
        session: AudioSessionState,
        request: web.Request,
        audio_cache: dict[int, str],
    ) -> None:
        """Advance to the next question or finish the session."""
        if session.manifest is None:
            return

        manifest = session.manifest
        session.current_index += 1

        if session.current_index >= len(manifest.questions):
            await self._finish_session(ws, session)
        else:
            next_q = manifest.questions[session.current_index]
            await self._send_question(
                ws, next_q, audio_cache, config=session.config, session=session
            )

    async def _advance_session_no_request(
        self,
        ws: web.WebSocketResponse,
        session: AudioSessionState,
        audio_cache: dict[int, str],
    ) -> None:
        """Advance session (called from binary handler without request)."""
        if session.manifest is None:
            return

        manifest = session.manifest
        session.current_index += 1

        if session.current_index >= len(manifest.questions):
            await self._finish_session(ws, session)
        else:
            next_q = manifest.questions[session.current_index]
            await self._send_question(
                ws, next_q, audio_cache, config=session.config, session=session
            )

    async def _finish_session(
        self,
        ws: web.WebSocketResponse,
        session: AudioSessionState,
    ) -> None:
        """Submit form data and send form_complete message."""
        session.completed = True
        answers_out = {
            fid: {"value": a.value, "source": a.source}
            for fid, a in session.answers.items()
        }
        submission_id: Optional[str] = None

        # Attempt form submission using FormSubmission model and store().
        if self._submission_storage is not None and session.manifest is not None:
            try:
                from ..services.submissions import FormSubmission

                submission = FormSubmission(
                    form_id=session.form_id,
                    form_version="1",
                    data={fid: a.value for fid, a in session.answers.items()},
                    is_valid=True,
                    user_id=session.user_id,
                )
                submission_id = await self._submission_storage.store(submission)
            except Exception as exc:
                self.logger.warning(
                    "Form submission failed for session %s: %s",
                    session.session_id,
                    exc,
                )

        await ws.send_json({
            "type": "form_complete",
            "submission_id": submission_id,
            "answers": answers_out,
        })

    # -------------------------------------------------------------------------
    # Question delivery
    # -------------------------------------------------------------------------

    async def _send_question(
        self,
        ws: web.WebSocketResponse,
        question: AudioQuestion,
        audio_cache: dict[int, str],
        *,
        config: Optional[AudioSessionConfig] = None,
        session: Optional[AudioSessionState] = None,
    ) -> None:
        """Send a question message with VoiceMode metadata and optional audio.

        Carries ``voice_mode``/``render_mode``/``sensitive`` always, ``options``
        for selection questions, and ``fallback_html`` for VISUAL_FALLBACK
        questions. Sensitive questions (e.g. password) are delivered without TTS
        audio. PROMPT_SELECT questions optionally enumerate their option labels
        in the narration (FEAT-236).

        Args:
            ws: Active WebSocket.
            question: The AudioQuestion to send.
            audio_cache: Per-session cache of pre-synthesized audio (base64).
            config: The session config (locale, enumerate_options, backend).
            session: The session, used to key the per-session synthesizer cache
                in auto_synthesize mode.
        """
        # Sensitive questions are never narrated — mute TTS read-back entirely.
        audio_b64: Optional[str] = None
        if not question.sensitive:
            audio_b64 = audio_cache.get(question.index)
            if audio_b64 is None:
                tts_text = self._narration_text(question, config)
                language = (
                    config.locale
                    if config is not None and config.locale != "en"
                    else None
                )
                audio_bytes = await self._synthesize(
                    tts_text, config=config, language=language, session=session
                )
                if audio_bytes:
                    audio_b64 = base64.b64encode(audio_bytes).decode()
                    audio_cache[question.index] = audio_b64

        # Single-field visual fallback HTML for VISUAL_FALLBACK questions.
        fallback_html = question.fallback_html
        if question.voice_mode == VoiceMode.VISUAL_FALLBACK and not fallback_html:
            fallback_html = await self._build_fallback_html(question, config)

        msg: dict[str, Any] = {
            "type": "question",
            "index": question.index,
            "field_id": question.field_id,
            "label": question.label,
            "required": question.required,
            "field_type": question.field_type,
            "voice_mode": question.voice_mode.value,
            "render_mode": question.render_mode,
            "sensitive": question.sensitive,
        }
        if question.description:
            msg["description"] = question.description
        if audio_b64:
            msg["audio"] = audio_b64
        if question.options:
            msg["options"] = question.options
        if fallback_html:
            msg["fallback_html"] = fallback_html

        await ws.send_json(msg)

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

    def _narration_text(
        self,
        question: AudioQuestion,
        config: Optional[AudioSessionConfig],
    ) -> str:
        """Build the TTS narration text for a question.

        For PROMPT_SELECT questions with ``enumerate_options`` enabled, appends
        the option labels so the user hears the choices.
        """
        text = question.label
        enumerate_options = (
            config.enumerate_options if config is not None else True
        )
        if (
            question.voice_mode == VoiceMode.PROMPT_SELECT
            and enumerate_options
            and question.options
        ):
            labels = [
                str(opt.get("label") or opt.get("value") or "")
                for opt in question.options
            ]
            labels = [label for label in labels if label]
            if labels:
                text = f"{text} Options: {', '.join(labels)}."
        return text

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
    # TTS pre-synthesis
    # -------------------------------------------------------------------------

    async def _presynthize_to_cache(
        self,
        questions: list[AudioQuestion],
        audio_cache: dict[int, str],
        *,
        locale: str = "en",
    ) -> None:
        """Pre-synthesize TTS audio for all questions into the cache.

        Args:
            questions: List of AudioQuestion to synthesize.
            audio_cache: Dict to populate with base64 audio strings.
            locale: BCP 47 language tag for TTS.
        """
        if self.synthesizer is None:
            return

        for q in questions:
            # Sensitive questions are never narrated (FEAT-236) — skip entirely.
            if q.sensitive:
                continue
            try:
                result = await self.synthesizer.synthesize(
                    q.label,
                    language=locale if locale != "en" else None,
                )
                audio_cache[q.index] = base64.b64encode(result.audio).decode()
            except Exception as exc:
                self.logger.warning(
                    "Pre-synthesis failed for q%d (%s): %s",
                    q.index, q.field_id, exc
                )

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
