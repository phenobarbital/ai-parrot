"""Amazon Nova 2 Sonic experimental bidirectional voice client (FEAT-302).

Implements :class:`NovaSonicClient`, an :class:`~parrot.clients.base.AbstractClient`
subclass providing bidirectional speech-to-speech via Amazon Nova Sonic's
``InvokeModelWithBidirectionalStream`` API — using the **Pre-Alpha**
``aws_sdk_bedrock_runtime`` SDK (Python >= 3.12 only; boto3/aioboto3 do not
support this operation).

Follows the sender/receiver task architecture pioneered by
:class:`~parrot.clients.live.GeminiLiveClient.stream_voice` (HTTP/2
bidirectional stream instead of a WebSocket), yielding the same
:class:`~parrot.clients.live.LiveVoiceResponse` shape so downstream
consumers (``VoiceChatHandler``) work unchanged.

.. warning::
    **EXPERIMENTAL.** ``aws_sdk_bedrock_runtime==0.7.0`` is Pre-Alpha and its
    API may change before GA — this module isolates every raw SDK call
    behind three thin wrappers (:meth:`NovaSonicClient._open_stream`,
    :meth:`NovaSonicClient._send_event`, :meth:`NovaSonicClient._iter_events`,
    mirroring :class:`~parrot.clients.bedrock.BedrockConverseClient`'s
    ``_sdk_create``/``_sdk_stream`` pattern) so only those need updating if
    the SDK's shape changes.

See ``sdd/specs/bedrock-client-llm.spec.md`` (Module 7) for the full design.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from .base import AbstractClient
from .live import LiveCompletionUsage, LiveToolCall, LiveVoiceResponse, VoiceTurnMetadata
from ..conf import AWS_REGION_NAME, BEDROCK_AWS_REGION
from ..models.bedrock_models import translate as translate_bedrock_model
from ..models.responses import AIMessage


class NovaSonicClient(AbstractClient):
    """Experimental Amazon Nova 2 Sonic bidirectional speech-to-speech client.

    Handles PCM 16kHz mono audio input and PCM 24kHz mono audio output over
    an ``aws_sdk_bedrock_runtime`` bidirectional stream. Text-only
    ``ask()``/``ask_stream()`` calls delegate to an internally-managed
    :class:`~parrot.clients.bedrock.BedrockConverseClient` (lazily
    constructed) rather than reimplementing text completion here.

    Connections are limited to ~8 minutes by the Nova Sonic service;
    :meth:`stream_voice` proactively yields a ``reconnect_required`` signal
    frame and closes the stream shortly before the limit so callers can
    open a new session and replay recent context.
    """

    client_type: str = "nova-sonic"
    client_name: str = "nova-sonic"
    _default_model: str = "amazon.nova-2-sonic-v1:0"

    # Nova Sonic's hard limit is ~8 minutes; reconnect with a safety margin
    # so a turn in progress is not cut off mid-stream.
    _CONNECTION_LIMIT_SECONDS: float = 8 * 60 - 15

    # PCM format constants (spec §2/§7).
    INPUT_SAMPLE_RATE_HZ: int = 16000
    OUTPUT_SAMPLE_RATE_HZ: int = 24000

    def __init__(
        self,
        region: Optional[str] = None,
        profile: Optional[str] = None,
        region_prefix: Optional[str] = None,
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
        text_fallback_model: Optional[str] = None,
        voice_id: str = "matthew",
        **kwargs
    ):
        """Initialise a Nova Sonic client.

        Args:
            region: AWS region for the Bedrock Runtime endpoint. Resolution
                order: explicit kwarg → ``BEDROCK_AWS_REGION`` →
                ``AWS_REGION_NAME`` → ``"us-east-1"``.
            profile: Optional named AWS profile, forwarded to the internal
                text-fallback :class:`~parrot.clients.bedrock.BedrockConverseClient`.
            region_prefix: Cross-region inference-profile prefix applied by
                :func:`~parrot.models.bedrock_models.translate`.
            guardrail_id: Bedrock guardrail identifier, used by
                :meth:`_apply_pii_guardrail` (transcription PII filtering)
                and forwarded to the internal text-fallback client.
            guardrail_version: Bedrock guardrail version. See
                ``guardrail_id``.
            text_fallback_model: Model ID used by the internal text-fallback
                :class:`~parrot.clients.bedrock.BedrockConverseClient`
                (``ask()``/``ask_stream()``). Defaults to
                ``BedrockConverseClient._default_model``.
            voice_id: Nova Sonic synthesis voice (e.g. ``"matthew"``,
                ``"tiffany"``, ``"amy"``).
            **kwargs: Forwarded to
                :class:`~parrot.clients.base.AbstractClient`.

        Raises:
            ImportError: When ``aws_sdk_bedrock_runtime`` (Pre-Alpha,
                Python >= 3.12 only) is not installed. Raised eagerly at
                construction time (rather than deferred to first use) so
                misconfiguration surfaces immediately with an actionable
                install hint.
        """
        try:
            import aws_sdk_bedrock_runtime  # noqa: F401 — presence check only
        except ImportError as exc:
            raise ImportError(
                "NovaSonicClient requires the Pre-Alpha 'aws_sdk_bedrock_runtime' "
                "package (==0.7.0, Python >= 3.12 only). This client is "
                "EXPERIMENTAL. Install with: "
                "pip install 'aws_sdk_bedrock_runtime==0.7.0'"
            ) from exc

        self._region = region or BEDROCK_AWS_REGION or AWS_REGION_NAME or "us-east-1"
        self._profile = profile
        self._region_prefix = region_prefix
        self._guardrail_id = guardrail_id
        self._guardrail_version = guardrail_version
        self._text_fallback_model = text_fallback_model
        self.voice_id = voice_id
        self._text_client: Any = None  # lazy BedrockConverseClient delegate
        super().__init__(**kwargs)

    # ------------------------------------------------------------------
    # Session & client management
    # ------------------------------------------------------------------

    async def get_client(self) -> Any:
        """Build the Nova Sonic bidirectional-stream SDK client.

        Returns:
            A ``BedrockAgentRuntimeClient`` (or equivalent) scoped to
            ``self._region``.
        """
        from aws_sdk_bedrock_runtime import BedrockAgentRuntimeClient
        return BedrockAgentRuntimeClient(region=self._region)

    def _translate_model(self, model: Optional[str]) -> str:
        """Resolve a public/Bedrock model ID via ``bedrock_models.translate()``."""
        raw = model or self.model or self.default_model
        return translate_bedrock_model(raw, self._region_prefix)

    def _get_text_client(self):
        """Lazily construct the internal text-fallback client.

        Returns:
            A cached :class:`~parrot.clients.bedrock.BedrockConverseClient`
            instance sharing this client's region/profile/guardrail config.
        """
        if self._text_client is None:
            from .bedrock import BedrockConverseClient
            self._text_client = BedrockConverseClient(
                model=self._text_fallback_model,
                region=self._region,
                profile=self._profile,
                region_prefix=self._region_prefix,
                guardrail_id=self._guardrail_id,
                guardrail_version=self._guardrail_version,
            )
        return self._text_client

    # ------------------------------------------------------------------
    # Thin SDK wrappers — isolate the Pre-Alpha bidirectional-stream API
    # (pattern: BedrockConverseClient._sdk_create/_sdk_stream)
    # ------------------------------------------------------------------

    async def _open_stream(self, model_id: str) -> Any:
        """Open the Nova Sonic bidirectional stream for *model_id*.

        Returns:
            The SDK's bidirectional stream handle, expected to expose an
            ``input_stream.send(event: dict)`` coroutine for sending event
            frames and an ``output_stream`` async iterator of response event
            frames (see :meth:`_send_event` / :meth:`_iter_events`).
        """
        from aws_sdk_bedrock_runtime.models import (
            InvokeModelWithBidirectionalStreamOperationInput,
        )
        client = await self._ensure_client()
        return await client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=model_id)
        )

    async def _send_event(self, stream: Any, event: Dict[str, Any]) -> None:
        """Send a single JSON event frame to the bidirectional stream."""
        await stream.input_stream.send(event)

    def _iter_events(self, stream: Any) -> AsyncIterator[Dict[str, Any]]:
        """Return the async iterator of output event frames from *stream*."""
        return stream.output_stream

    # ------------------------------------------------------------------
    # Guardrails (delegates to the text-fallback client, TASK-1746)
    # ------------------------------------------------------------------

    async def _apply_pii_guardrail(self, text: str) -> str:
        """Filter PII from a transcription via the configured guardrail.

        Delegates to
        :meth:`~parrot.clients.bedrock.BedrockConverseClient.apply_guardrail_text`
        (returns *text* unmodified when no guardrail is configured).
        """
        return await self._get_text_client().apply_guardrail_text(text, source="INPUT")

    # ------------------------------------------------------------------
    # Voice streaming
    # ------------------------------------------------------------------

    async def stream_voice(
        self,
        audio_iterator: AsyncIterator[bytes],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs
    ) -> AsyncIterator[LiveVoiceResponse]:
        """Stream bidirectional voice interaction via Nova Sonic.

        Follows :meth:`~parrot.clients.live.GeminiLiveClient.stream_voice`'s
        sender/receiver task pattern: a background sender task reads PCM
        16kHz chunks from *audio_iterator* and forwards them as
        ``audioInput`` event frames, while this coroutine iterates the
        stream's output events and yields :class:`LiveVoiceResponse`
        objects (PCM 24kHz audio and/or text).

        Args:
            audio_iterator: Async iterator yielding PCM 16-bit, 16kHz mono
                audio chunks. A ``None`` sentinel marks end-of-turn (mirrors
                ``GeminiLiveClient``'s multi-turn convention).
            system_prompt: Optional system instructions for the session.
            session_id: Session identifier for tracking.
            user_id: User identifier.
            **kwargs: Reserved for future configuration (tool overrides,
                etc.).

        Yields:
            :class:`LiveVoiceResponse` objects with audio, text, tool-call,
            and usage metadata — the same shape ``VoiceChatHandler``
            already consumes from ``GeminiLiveClient``.
        """
        session_id = session_id or str(uuid.uuid4())
        turn_id = str(uuid.uuid4())
        resolved_model = self._translate_model(None)
        prompt_name = str(uuid.uuid4())
        content_name = str(uuid.uuid4())

        turn_metadata = VoiceTurnMetadata(turn_id=turn_id)
        usage = LiveCompletionUsage()
        accumulated_text = ""
        tool_calls_list: List[LiveToolCall] = []

        self.logger.info(
            "Starting Nova Sonic voice session %s, turn %s (model=%s)",
            session_id, turn_id, resolved_model,
        )

        connection_start = time.monotonic()
        stream = await self._open_stream(resolved_model)

        await self._send_event(stream, {"event": {"sessionStart": {
            "inferenceConfiguration": {"maxTokens": 1024, "topP": 0.9, "temperature": 0.7}
        }}})
        await self._send_event(stream, {"event": {"promptStart": {
            "promptName": prompt_name,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": self.OUTPUT_SAMPLE_RATE_HZ,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "voiceId": self.voice_id,
                "encoding": "base64",
            },
        }}})
        if system_prompt:
            await self._send_event(stream, {"event": {"contentStart": {
                "promptName": prompt_name, "contentName": f"{content_name}-sys",
                "type": "TEXT", "role": "SYSTEM",
            }}})
            await self._send_event(stream, {"event": {"textInput": {
                "promptName": prompt_name, "contentName": f"{content_name}-sys",
                "content": system_prompt,
            }}})
            await self._send_event(stream, {"event": {"contentEnd": {
                "promptName": prompt_name, "contentName": f"{content_name}-sys",
            }}})

        await self._send_event(stream, {"event": {"contentStart": {
            "promptName": prompt_name, "contentName": content_name,
            "type": "AUDIO", "role": "USER",
            "audioInputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": self.INPUT_SAMPLE_RATE_HZ,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "encoding": "base64",
            },
        }}})

        sender_task = asyncio.create_task(
            self._audio_sender(stream, audio_iterator, prompt_name, content_name)
        )

        try:
            async for event in self._iter_events(stream):
                if time.monotonic() - connection_start >= self._CONNECTION_LIMIT_SECONDS:
                    self.logger.info(
                        "Nova Sonic session %s approaching 8-minute connection "
                        "limit — signalling reconnect.", session_id,
                    )
                    yield LiveVoiceResponse(
                        text=accumulated_text,
                        is_complete=True,
                        metadata={"reconnect_required": True},
                        usage=usage,
                        turn_metadata=turn_metadata,
                        session_id=session_id,
                        turn_id=turn_id,
                        user_id=user_id,
                    )
                    break

                # Barge-in / interruption.
                if "interruption" in event or event.get("stopReason") == "INTERRUPTED":
                    turn_metadata.was_interrupted = True
                    yield LiveVoiceResponse(
                        text=accumulated_text,
                        is_complete=True,
                        is_interrupted=True,
                        usage=usage,
                        turn_metadata=turn_metadata,
                        session_id=session_id,
                        turn_id=turn_id,
                        user_id=user_id,
                    )
                    accumulated_text = ""
                    continue

                text_output = event.get("textOutput")
                if text_output:
                    chunk_text = text_output.get("content", "")
                    accumulated_text += chunk_text
                    yield LiveVoiceResponse(
                        text=chunk_text,
                        is_complete=False,
                        session_id=session_id,
                        turn_id=turn_id,
                        user_id=user_id,
                    )

                audio_output = event.get("audioOutput")
                if audio_output:
                    yield LiveVoiceResponse(
                        text="",
                        audio_data=audio_output.get("content"),
                        audio_format=f"audio/pcm;rate={self.OUTPUT_SAMPLE_RATE_HZ}",
                        is_complete=False,
                        session_id=session_id,
                        turn_id=turn_id,
                        user_id=user_id,
                    )

                tool_use = event.get("toolUse")
                if tool_use:
                    tool_name = tool_use.get("toolName")
                    tool_input = tool_use.get("content", {})
                    tool_use_id = tool_use.get("toolUseId", str(uuid.uuid4()))

                    tc = LiveToolCall(id=tool_use_id, name=tool_name, arguments=tool_input)
                    start = time.monotonic()
                    try:
                        result = await self._execute_tool(tool_name, tool_input)
                        tc.result = result
                    except Exception as exc:
                        tc.error = str(exc)
                        result = str(exc)
                    tc.execution_time_ms = (time.monotonic() - start) * 1000
                    tool_calls_list.append(tc)
                    usage.tool_calls_executed += 1
                    usage.tool_execution_time_ms += tc.execution_time_ms

                    await self._send_event(stream, {"event": {"toolResult": {
                        "promptName": prompt_name,
                        "toolUseId": tool_use_id,
                        "content": str(result),
                    }}})

                    yield LiveVoiceResponse(
                        text="",
                        tool_calls=[tc],
                        is_complete=False,
                        session_id=session_id,
                        turn_id=turn_id,
                        user_id=user_id,
                    )

                if "completionEnd" in event or event.get("stopReason") == "END_TURN":
                    turn_metadata.ended_at = None
                    yield LiveVoiceResponse(
                        text="",
                        is_complete=True,
                        tool_calls=tool_calls_list,
                        usage=usage,
                        turn_metadata=turn_metadata,
                        session_id=session_id,
                        turn_id=turn_id,
                        user_id=user_id,
                    )
                    break
        except asyncio.CancelledError:
            self.logger.info("Nova Sonic session %s cancelled", session_id)
            raise
        except Exception as exc:
            self.logger.error("Nova Sonic session %s error: %s", session_id, exc)
            yield LiveVoiceResponse(
                text="",
                is_complete=True,
                metadata={"error": str(exc)},
                session_id=session_id,
                turn_id=turn_id,
                user_id=user_id,
            )
        finally:
            sender_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender_task

    async def _audio_sender(
        self,
        stream: Any,
        audio_iterator: AsyncIterator[bytes],
        prompt_name: str,
        content_name: str,
    ) -> None:
        """Forward PCM audio chunks from *audio_iterator* as ``audioInput``
        event frames. A ``None`` sentinel marks end-of-turn (mirrors
        ``GeminiLiveClient._audio_sender``'s multi-turn convention) and
        triggers a ``contentEnd`` frame without closing the sender task.
        """
        chunks_sent = 0
        try:
            async for chunk in audio_iterator:
                if chunk is None:
                    if chunks_sent > 0:
                        await self._send_event(stream, {"event": {"contentEnd": {
                            "promptName": prompt_name, "contentName": content_name,
                        }}})
                    continue
                await self._send_event(stream, {"event": {"audioInput": {
                    "promptName": prompt_name,
                    "contentName": content_name,
                    "content": chunk,
                }}})
                chunks_sent += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.error("Nova Sonic audio sender error: %s", exc)

    # ------------------------------------------------------------------
    # Text-only fallback (delegates to BedrockConverseClient)
    # ------------------------------------------------------------------

    async def ask(self, prompt: str, **kwargs) -> AIMessage:
        """Text-only fallback — delegates to an internal
        :class:`~parrot.clients.bedrock.BedrockConverseClient`.

        NovaSonicClient's primary interface is :meth:`stream_voice`; this
        method exists so text-only interactions (and the
        ``AbstractClient.ask`` contract) still work without requiring
        callers to manage a separate client instance.
        """
        return await self._get_text_client().ask(prompt, **kwargs)

    async def ask_stream(self, prompt: str, **kwargs) -> AsyncIterator[Union[str, AIMessage]]:
        """Text-only streaming fallback — delegates to the internal
        :class:`~parrot.clients.bedrock.BedrockConverseClient`."""
        async for chunk in self._get_text_client().ask_stream(prompt, **kwargs):
            yield chunk

    async def invoke(self, prompt: str, **kwargs):
        """Text-only lightweight fallback — delegates to the internal
        :class:`~parrot.clients.bedrock.BedrockConverseClient`."""
        return await self._get_text_client().invoke(prompt, **kwargs)

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]):
        """Not supported: NovaSonicClient has no suspend/resume concept for
        voice sessions (mirrors ``GeminiLiveClient.resume``'s precedent).

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "NovaSonicClient does not support suspend/resume for voice sessions."
        )
