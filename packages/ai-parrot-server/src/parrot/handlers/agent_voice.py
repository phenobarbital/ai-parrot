"""HTTP handler for voice agent interaction (FEAT-231).

``AgentVoiceTalk`` is a thin REST subclass of :class:`AgentTalk` that adds a
voice I/O adapter around the **unchanged** text dispatch:

    audio note  ──STT──▶  query: str  ──bot.ask()──▶  AIMessage
                                                          │
    audio + content  ◀──TTS──  AIMessage.response  ◀──────┘

It inherits agent resolution, PBAC, HITL, auth envelopes, session handling and
output negotiation from :class:`AgentTalk`, mirroring the existing
``InfographicTalk(AgentTalk)`` precedent, and overrides only the two voice
seams:

1. **Inbound (STT).** ``handle_upload`` is overridden: after the inherited
   multipart parse, an audio attachment (if present) is transcribed via a
   lazily-imported :class:`VoiceTranscriber` and the transcript is injected as
   ``data['query']`` so the inherited ``post()`` text path runs unchanged.
2. **Outbound (TTS).** ``post`` is overridden to wrap ``super().post()``: when
   the request carried voice input, ``AIMessage.response`` (str only) is
   synthesized via a lazily-imported :class:`VoiceSynthesizer` and
   ``audio_base64`` + ``audio_format`` are attached to the inherited JSON
   envelope. ``output`` / ``data`` / ``media`` stay in ``content`` and never
   pass through the synthesizer.

The voice stack (``parrot.voice.*``, shipped by ``ai-parrot-integrations``) is
imported **lazily inside the voice code path** so server boot never hard-requires
the satellite distribution. TTS failures degrade gracefully to text-only.

Added by FEAT-231 (AgentTalk Voice Support).
"""
from __future__ import annotations

import base64
import contextlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from aiohttp import web
from navconfig.logging import logging
from navigator_auth.decorators import is_authenticated, user_session
from datamodel.parsers.json import json_encoder  # noqa  pylint: disable=E0611

from .agent import AgentTalk

# Audio container extensions the voice transcriber understands (mirrors
# VoiceTranscriber.SUPPORTED_FORMATS in ai-parrot-integrations).
_AUDIO_EXTS = {".ogg", ".mp3", ".wav", ".m4a", ".webm", ".mp4", ".flac"}

# Default output audio container (spec U5 — web-player friendly).
_DEFAULT_AUDIO_FORMAT = "audio/wav"


@is_authenticated()
@user_session()
class AgentVoiceTalk(AgentTalk):
    """Voice-capable REST handler: audio → STT → text agent → TTS → audio.

    Endpoint: ``POST /api/v1/agents/voice/{agent_id}``

    Inherits everything from :class:`AgentTalk` (agent resolution, PBAC, HITL,
    auth envelopes, session and output negotiation) and overrides only the two
    voice seams (``handle_upload`` inbound, ``post`` outbound). The text path
    (``AgentTalk.post``) is reused unchanged.
    """

    _logger_name: str = "Parrot.AgentVoiceTalk"

    def post_init(self, *args, **kwargs) -> None:
        """Initialise the logger and per-request voice state."""
        self.logger = logging.getLogger(self._logger_name)
        # True once an inbound audio attachment has been transcribed; gates the
        # outbound TTS so a plain text request behaves like the inherited path.
        self._did_transcribe: bool = False
        # TTS backend + container, optionally overridden per request body.
        self._tts_backend: str = "google"
        self._tts_format: str = _DEFAULT_AUDIO_FORMAT
        # STT backend, optionally overridden per request body.
        self._stt_backend: Optional[str] = None
        # ── Avatar mode flag (FEAT-242 Phase A — TASK-007) ─────────────────
        # Set to True when the request body carries ``"avatar": true``.
        # When True the turn triggers avatar speech via the active LITE/FULL
        # session speaker; gated by the per-tenant opt-in hook from TASK-008.
        # Absent or False → unchanged text/voice behaviour (no avatar session).
        self._avatar_mode: bool = False
        # Tenant ID for opt-in gating; extracted from the request body.
        # Not threaded through the existing chat path (spec §6 Anti-Hallucination);
        # TASK-008 wires this explicitly.
        self._avatar_tenant_id: Optional[str] = None

    # ── Inbound seam (STT) ─────────────────────────────────────────────

    async def handle_upload(self, *args, **kwargs) -> Tuple[Dict[str, Any], dict]:
        """Override the inherited multipart parse to transcribe voice input.

        Calls the inherited ``handle_upload`` to parse the multipart body, then
        — if an audio attachment is present and no explicit ``query`` was sent
        — transcribes it and injects the transcript as ``data['query']`` so the
        inherited ``post()`` text dispatch runs unchanged. The consumed audio
        attachment is removed from the attachment map and its tempfile is always
        unlinked.

        Returns:
            ``(attachments, data)`` with ``data['query']`` populated from the
            transcript when an audio note was supplied.
        """
        attachments, data = await super().handle_upload(*args, **kwargs)

        # Pick up optional per-request backend selectors before consuming data.
        self._read_voice_options(data)

        audio_info, field = self._find_audio_attachment(attachments)
        if audio_info is not None:
            if not data.get("query"):
                # Voice-in: transcribe and inject the transcript as the query.
                # _transcribe_attachment unlinks the audio tempfile itself.
                transcript = await self._transcribe_attachment(audio_info)
                data["query"] = transcript
                self._did_transcribe = True
            else:
                # An explicit text 'query' wins; discard the audio note and
                # clean up its tempfile so it is not left on disk or ingested
                # as a RAG document by the inherited _handle_attachments path.
                self.logger.info(
                    "AgentVoiceTalk: explicit 'query' present; "
                    "ignoring audio attachment."
                )
                self._unlink_attachment(audio_info)
            # Remove the consumed/ignored audio entry from the attachment map.
            attachments[field].remove(audio_info)
            if not attachments[field]:
                del attachments[field]

        return attachments, data

    def _read_voice_options(self, data: dict) -> None:
        """Read optional per-request voice backend selectors from the body.

        Args:
            data: The parsed form fields. ``stt_backend``, ``tts_backend`` and
                ``audio_format`` are consumed (popped) when present.
        """
        stt = data.pop("stt_backend", None)
        if isinstance(stt, str) and stt:
            self._stt_backend = stt
        tts = data.pop("tts_backend", None)
        if isinstance(tts, str) and tts:
            self._tts_backend = tts
        fmt = data.pop("audio_format", None)
        if isinstance(fmt, str) and fmt:
            self._tts_format = fmt
        # ── Avatar mode flag (FEAT-242 Phase A — TASK-007) ─────────────────
        # ``avatar=true`` in the request body opts the turn into avatar mode.
        # The opt-in hook from TASK-008 gates the actual orchestration.
        avatar_flag = data.pop("avatar", None)
        if avatar_flag is True or (isinstance(avatar_flag, str) and avatar_flag.lower() == "true"):
            self._avatar_mode = True
        tenant_id = data.pop("tenant_id", None)
        if isinstance(tenant_id, str) and tenant_id:
            self._avatar_tenant_id = tenant_id

    def _find_audio_attachment(
        self, attachments: Dict[str, Any]
    ) -> Tuple[Optional[dict], Optional[str]]:
        """Locate the first audio attachment among the uploaded files.

        Args:
            attachments: ``handle_upload`` output — a mapping of form field
                name to a list of ``{'file_path', 'file_name', 'mime_type'}``
                dicts.

        Returns:
            ``(file_info, field_name)`` for the first audio attachment, or
            ``(None, None)`` if none is present.
        """
        for field, files in (attachments or {}).items():
            for file_info in files:
                if self._is_audio(file_info):
                    return file_info, field
        return None, None

    @staticmethod
    def _is_audio(file_info: dict) -> bool:
        """Return True if the uploaded file looks like a transcribable audio note."""
        mime = (file_info.get("mime_type") or "").lower()
        if mime.startswith("audio/") or mime == "video/webm":
            return True
        name = file_info.get("file_name") or ""
        return Path(name).suffix.lower() in _AUDIO_EXTS

    async def _transcribe_attachment(self, file_info: dict) -> str:
        """Transcribe an audio attachment to text via the voice stack.

        Lazily imports :class:`VoiceTranscriber` (so server boot never requires
        ``ai-parrot-integrations``), transcribes the persisted audio tempfile,
        and always unlinks the tempfile afterwards.

        Args:
            file_info: An attachment dict from ``handle_upload`` with a
                ``file_path`` (Path) to the persisted audio tempfile.

        Returns:
            The transcribed text.

        Raises:
            web.HTTPServiceUnavailable: If the voice stack is not installed.
            web.HTTPBadRequest: If transcription fails (e.g. duration guard).
        """
        try:
            from parrot.voice.transcriber.transcriber import VoiceTranscriber
            from parrot.voice.transcriber.models import (
                TranscriberBackend,
                VoiceTranscriberConfig,
            )
        except ImportError as exc:
            self.logger.warning("Voice transcriber stack unavailable: %s", exc)
            raise web.HTTPServiceUnavailable(
                text=json.dumps(
                    {
                        "error": "Voice transcription is unavailable; install "
                        "ai-parrot-integrations[voice].",
                    }
                ),
                content_type="application/json",
            ) from exc

        config_kwargs: Dict[str, Any] = {}
        if self._stt_backend:
            try:
                config_kwargs["backend"] = TranscriberBackend(self._stt_backend)
            except ValueError:
                self.logger.warning(
                    "Unknown STT backend '%s'; using default.", self._stt_backend
                )
        transcriber = VoiceTranscriber(VoiceTranscriberConfig(**config_kwargs))

        audio_path: Path = file_info["file_path"]
        try:
            result = await transcriber.transcribe_file(audio_path)
            self.logger.info(
                "AgentVoiceTalk: transcribed %s (%d chars)",
                getattr(audio_path, "name", audio_path),
                len(result.text),
            )
            return result.text
        except ImportError as exc:
            # Selected STT backend's extra is not installed — clean 503, never
            # a 500. Mirrors the top-level guard above.
            self.logger.warning("AgentVoiceTalk: STT backend unavailable: %s", exc)
            raise web.HTTPServiceUnavailable(
                text=json.dumps(
                    {
                        "error": "The selected speech-to-text backend is not "
                        "installed; install ai-parrot-integrations[voice].",
                    }
                ),
                content_type="application/json",
            ) from exc
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            self.logger.warning("AgentVoiceTalk: transcription failed: %s", exc)
            raise web.HTTPBadRequest(
                text=json.dumps({"error": f"Could not transcribe audio: {exc}"}),
                content_type="application/json",
            ) from exc
        finally:
            with contextlib.suppress(Exception):
                await transcriber.close()
            self._unlink_attachment(file_info)

    def _unlink_attachment(self, file_info: dict) -> None:
        """Best-effort removal of an uploaded attachment's tempfile.

        Args:
            file_info: An attachment dict with a ``file_path`` (Path).
        """
        path = file_info.get("file_path")
        if isinstance(path, Path) and path.exists():
            with contextlib.suppress(Exception):
                path.unlink()
                self.logger.debug(
                    "AgentVoiceTalk: cleaned up audio tempfile %s", path
                )

    # ── Outbound seam (TTS) ────────────────────────────────────────────

    async def post(self) -> web.Response:
        """Run the inherited text dispatch, then attach synthesized audio.

        Delegates the entire request to ``AgentTalk.post`` (which calls our
        overridden ``handle_upload`` for STT injection), then — only when the
        request carried voice input — synthesizes ``AIMessage.response`` and
        attaches ``audio_base64`` + ``audio_format`` to the JSON envelope.

        When ``_avatar_mode`` is True the opt-in hook from TASK-008 is
        consulted; if avatar mode is enabled for the tenant, the avatar
        session is expected to have been pre-started via the
        ``/api/v1/agents/avatar/{agent_id}/start`` endpoint.  The reply is
        spoken through that session by the inherited ``AgentTalk.post`` path
        (``_speak_text_to_avatar`` for the non-stream reply, or
        ``_handle_stream_response`` per-sentence when streaming).

        Returns:
            The inherited response, augmented with audio when applicable.
        """
        # ── Avatar mode gate (FEAT-242 TASK-007 / TASK-008) ───────────────
        # If the request carries avatar=true, check the opt-in gate and attach
        # avatar metadata to the response.  The actual PCM push happens via the
        # /api/v1/agents/avatar/{agent_id}/start endpoint, not here — keeping
        # this path non-blocking.
        if self._avatar_mode:
            try:
                from parrot.integrations.liveavatar.optin import is_avatar_enabled
                if not is_avatar_enabled(
                    tenant_id=self._avatar_tenant_id,
                    agent_name=self.request.match_info.get("agent_id", ""),
                ):
                    self.logger.info(
                        "AgentVoiceTalk: avatar mode requested but tenant opt-in "
                        "is off; falling through to text/voice path."
                    )
                    self._avatar_mode = False
            except ImportError:
                self._avatar_mode = False

        response = await super().post()
        if not self._did_transcribe:
            # Plain text request to the voice endpoint → behave like AgentTalk.
            return response
        return await self._augment_with_audio(response)

    async def _augment_with_audio(self, response: web.Response) -> web.Response:
        """Attach base64 TTS audio to a successful JSON response envelope.

        Synthesizes **only** the ``response`` field of the inherited JSON
        envelope (which is ``AIMessage.response`` — the speakable text);
        ``output`` / ``data`` / ``media`` are left untouched. On any synthesizer
        failure the original (text-only) response is returned unchanged.

        Args:
            response: The web.Response produced by the inherited ``post()``.

        Returns:
            A new JSON response with ``audio_base64`` + ``audio_format`` added,
            or the original response when augmentation is not possible.
        """
        if response.content_type != "application/json" or response.status != 200:
            return response

        body = response.body
        if not body:
            return response
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            return response
        if not isinstance(payload, dict):
            return response

        # The inherited JSON envelope carries AIMessage.response under "response".
        text = payload.get("response")
        if not isinstance(text, str) or not text.strip():
            return response

        try:
            audio_b64, audio_format = await self._synthesize(text)
        except (ValueError, RuntimeError, ImportError) as exc:
            self.logger.warning(
                "AgentVoiceTalk: TTS unavailable, returning text-only (%s)", exc
            )
            return response

        payload["audio_base64"] = audio_b64
        payload["audio_format"] = audio_format
        return web.json_response(
            payload, dumps=json_encoder, content_type="application/json"
        )

    async def _synthesize(self, text: str) -> Tuple[str, str]:
        """Synthesize speech for ``text`` and return base64 audio + format.

        Lazily imports :class:`VoiceSynthesizer` (so server boot never requires
        ``ai-parrot-integrations``) and synthesizes the agent's reply.

        Args:
            text: The speakable reply text (``AIMessage.response``).

        Returns:
            ``(audio_base64, audio_format)`` where ``audio_base64`` is the
            base64-encoded ``SynthesisResult.audio`` and ``audio_format`` is the
            truthful ``SynthesisResult.mime_format``.

        Raises:
            ImportError: If the voice TTS stack is not installed.
            ValueError / RuntimeError: If synthesis fails.
        """
        from parrot.voice.tts.synthesizer import VoiceSynthesizer
        from parrot.voice.tts.models import TTSConfig

        synthesizer = VoiceSynthesizer(
            TTSConfig(backend=self._tts_backend, mime_format=self._tts_format)
        )
        try:
            result = await synthesizer.synthesize(text)
        finally:
            with contextlib.suppress(Exception):
                await synthesizer.close()

        audio_b64 = base64.b64encode(result.audio).decode("ascii")
        return audio_b64, result.mime_format


@is_authenticated()
@user_session()
class AgentTranscribeOnly(AgentVoiceTalk):
    """Transcribe-only endpoint for Mode B internal STT (FEAT-249 TASK-1608).

    Exposes ``POST /api/v1/agents/transcribe/{agent_id}`` — accepts a multipart
    audio upload, runs STT via :class:`VoiceTranscriber` (backend selectable via
    ``stt_backend`` form field), and returns ``{"text": "<transcript>"}`` without
    invoking the agent.

    This allows the FULL-mode frontend to obtain a transcript from ai-parrot's
    internal STT (FasterWhisper or OpenAI Whisper) instead of relying on the
    LiveAvatar data-channel ``user.transcription`` events.  LiveAvatar STT remains
    the *documented default*; internal STT is opt-in via this endpoint.

    Backend selection mirrors :meth:`AgentVoiceTalk._read_voice_options`:
        ``stt_backend=faster_whisper`` (local, default) or ``stt_backend=openai``
        (cloud).  Unknown values are logged and fall back to the configured default.

    Returns:
        JSON ``{"text": "<transcript>"}`` on success.
        HTTP 503 when the voice stack (``ai-parrot-integrations[voice]``) is absent.
        HTTP 400 when transcription fails (e.g. bad audio, duration guard).
    """

    _logger_name: str = "Parrot.AgentTranscribeOnly"

    async def post(self) -> web.Response:
        """Handle POST: parse multipart, transcribe audio, return transcript."""
        data, attachments = await self.handle_upload()
        self._read_voice_options(data)

        audio_info, _ = self._find_audio_attachment(attachments)
        if audio_info is None:
            raise web.HTTPBadRequest(
                text=json.dumps({"error": "No audio attachment found in the request."}),
                content_type="application/json",
            )

        try:
            text = await self._transcribe_attachment(audio_info)
        finally:
            # _transcribe_attachment always unlinks the tempfile; no double-unlink needed.
            pass

        return web.Response(
            text=json.dumps({"text": text}),
            content_type="application/json",
        )
