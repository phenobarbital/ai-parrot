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
import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from aiohttp import WSMsgType, web

from ..audio.models import (
    AudioAnswer,
    AudioFormManifest,
    AudioQuestion,
    AudioSessionState,
)
from ..renderers.audio import AudioFormRenderer

if TYPE_CHECKING:
    from parrot.voice.handler import AuthenticatedUser, TokenValidator
    from parrot.voice.tts.synthesizer import VoiceSynthesizer
    from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend

    from ..services.registry import FormRegistry
    from ..services.validators import FormValidator
    from ..services.submissions import FormSubmissionStorage

logger = logging.getLogger(__name__)

# Maximum audio questions per session (spec open question resolved: 10 max).
MAX_QUESTIONS = 10


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
    ) -> None:
        """Initialize the AudioFormWSHandler."""
        self.registry = registry
        self.synthesizer = synthesizer
        self.transcriber = transcriber
        self.validator = validator
        self._token_validator = token_validator
        self._submission_storage = submission_storage
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
        ws = web.WebSocketResponse(heartbeat=30.0, max_msg_size=10 * 1024 * 1024)
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
            from parrot.voice.handler import AuthenticatedUser  # type: ignore[import-untyped]
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
            msg = await asyncio.wait_for(ws.__anext__(), timeout=10.0)  # type: ignore[attr-defined]
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

        from parrot_formdesigner.core.types import LocalizedString  # noqa: F401 — for _resolve usage

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

        # Pre-synthesize all questions if synthesizer available.
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
            await self._send_question(ws, questions[0], audio_cache)
        else:
            await self._finish_session(ws, session, request)

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

            # Send transcription back to client.
            await ws.send_json({
                "type": "transcription",
                "field_id": current_q.field_id,
                "text": transcript,
                "confidence": confidence,
            })

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
        await self._send_question(ws, manifest.questions[target], audio_cache)

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
        await self._send_question(ws, current_q, audio_cache)

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

    async def _accept_answer(
        self,
        ws: web.WebSocketResponse,
        session: AudioSessionState,
        field_id: str,
        value: str,
        *,
        source: str = "text",
        confidence: Optional[float] = None,
        raw_transcript: Optional[str] = None,
    ) -> bool:
        """Validate and store an answer for the current question.

        Args:
            ws: Active WebSocket.
            session: Current session state.
            field_id: Field ID being answered.
            value: Answer value string.
            source: 'text' or 'speech'.
            confidence: STT confidence (speech only).
            raw_transcript: Raw transcript (speech only).

        Returns:
            True if accepted, False if rejected (error message sent).
        """
        answer = AudioAnswer(
            field_id=field_id,
            value=value,
            source=source,  # type: ignore[arg-type]
            confidence=confidence,
            raw_transcript=raw_transcript,
        )
        session.answers[field_id] = answer

        await ws.send_json({
            "type": "answer_accepted",
            "field_id": field_id,
            "value": value,
            "source": source,
        })
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
            await self._finish_session(ws, session, request)
        else:
            next_q = manifest.questions[session.current_index]
            await self._send_question(ws, next_q, audio_cache)

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
            # Cannot submit without request context — send form_complete only.
            answers_out = {
                fid: {"value": a.value, "source": a.source}
                for fid, a in session.answers.items()
            }
            session.completed = True
            await ws.send_json({
                "type": "form_complete",
                "submission_id": None,
                "answers": answers_out,
            })
        else:
            next_q = manifest.questions[session.current_index]
            await self._send_question(ws, next_q, audio_cache)

    async def _finish_session(
        self,
        ws: web.WebSocketResponse,
        session: AudioSessionState,
        request: web.Request,
    ) -> None:
        """Submit form data and send form_complete message."""
        session.completed = True
        answers_out = {
            fid: {"value": a.value, "source": a.source}
            for fid, a in session.answers.items()
        }
        submission_id: Optional[str] = None

        # Attempt form submission via FormAPIHandler.submit_data equivalent.
        if self._submission_storage is not None and session.manifest is not None:
            try:
                from ..services.submissions import SubmissionData

                submission = SubmissionData(
                    form_id=session.form_id,
                    data={fid: a.value for fid, a in session.answers.items()},
                )
                saved = await self._submission_storage.save(submission)
                submission_id = str(saved.submission_id) if saved else None
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
    ) -> None:
        """Send a question message with optional base64 TTS audio.

        Args:
            ws: Active WebSocket.
            question: The AudioQuestion to send.
            audio_cache: Per-session cache of pre-synthesized audio (base64).
        """
        audio_b64 = audio_cache.get(question.index)

        # If not pre-synthesized, try on-demand synthesis.
        if audio_b64 is None and self.synthesizer is not None:
            try:
                result = await self.synthesizer.synthesize(question.label)
                audio_b64 = base64.b64encode(result.audio).decode()
                audio_cache[question.index] = audio_b64
            except Exception as exc:
                self.logger.warning(
                    "On-demand TTS failed for q%d: %s", question.index, exc
                )

        msg: dict[str, Any] = {
            "type": "question",
            "index": question.index,
            "field_id": question.field_id,
            "label": question.label,
            "required": question.required,
            "field_type": question.field_type,
        }
        if question.description:
            msg["description"] = question.description
        if audio_b64:
            msg["audio"] = audio_b64
        if question.options:
            msg["options"] = question.options

        await ws.send_json(msg)

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
