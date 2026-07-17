"""NovaAudio — bidirectional voice streaming mixin for NovaClient (FEAT-315).

Ports the bidirectional speech-to-speech implementation from
``parrot.clients.nova_sonic.NovaSonicClient`` (FEAT-302) into a plain
capability mixin, composed into
:class:`~parrot.clients.nova.client.NovaClient` alongside
``BedrockConverseBase`` (spec ``novaclient-amazon-aws`` §2/§3 Module 3),
mirroring how :class:`~parrot.clients.google.generation.GoogleGeneration`
is composed into :class:`~parrot.clients.google.client.GoogleGenAIClient`.

.. warning::
    **EXPERIMENTAL.** ``aws_sdk_bedrock_runtime==0.7.0`` is Pre-Alpha and its
    API may change before GA — every raw SDK call is isolated behind three
    thin wrappers (:meth:`NovaAudio._open_stream`,
    :meth:`NovaAudio._send_event`, :meth:`NovaAudio._iter_events`, mirroring
    :class:`~parrot.clients.bedrock.BedrockConverseBase`'s
    ``_sdk_create``/``_sdk_stream`` pattern) so only those need updating if
    the SDK's shape changes. The Pre-Alpha SDK is imported lazily — only at
    first :meth:`stream_voice` call, via :func:`_require_voice_sdk` — so
    text/generation-only usage of ``NovaClient`` never requires it.

See ``sdd/specs/novaclient-amazon-aws.spec.md`` (§3 Module 3) for the full
design.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from ..live import LiveCompletionUsage, LiveToolCall, LiveVoiceResponse, VoiceTurnMetadata
from ...models.bedrock_models import translate as translate_bedrock_model


def _require_voice_sdk() -> None:
    """Raise an actionable ``ImportError`` if the Pre-Alpha voice SDK is missing.

    Called at the top of :meth:`NovaAudio.stream_voice` (NOT at import time,
    NOT in any ``__init__``) so that text/generation-only usage of
    ``NovaClient`` never requires the experimental
    ``aws_sdk_bedrock_runtime`` package or Python >= 3.12.

    Raises:
        ImportError: When ``aws_sdk_bedrock_runtime`` is not installed.
    """
    try:
        import aws_sdk_bedrock_runtime  # noqa: F401 — presence check only
    except ImportError as exc:
        raise ImportError(
            "NovaClient.stream_voice() requires the Pre-Alpha "
            "'aws_sdk_bedrock_runtime' package (==0.7.0, Python >= 3.12 "
            "only). This voice path is EXPERIMENTAL. Install with: "
            "pip install 'aws_sdk_bedrock_runtime==0.7.0'"
        ) from exc


class NovaAudio:
    """Bidirectional voice-streaming mixin (Nova Sonic / Nova 2 Sonic).

    Plain mixin — defines NO ``__init__`` (MRO constraint, spec §7) and
    reads the following attributes from the composed client (set by
    :class:`~parrot.clients.nova.client.NovaClient` / inherited from
    ``BedrockConverseBase``): ``self.voice_id``, ``self._region``,
    ``self._region_prefix``, ``self.model``, ``self.default_model``,
    ``self.logger``, ``self._execute_tool(name, input)``,
    ``self.apply_guardrail_text(text, source)``.
    """

    # Nova Sonic's hard limit is ~8 minutes; reconnect with a safety margin
    # so a turn in progress is not cut off mid-stream.
    _CONNECTION_LIMIT_SECONDS: float = 8 * 60 - 15

    # PCM format constants (spec §2/§7).
    INPUT_SAMPLE_RATE_HZ: int = 16000
    OUTPUT_SAMPLE_RATE_HZ: int = 24000

    # ------------------------------------------------------------------
    # Thin SDK wrappers — isolate the Pre-Alpha bidirectional-stream API
    # (pattern: BedrockConverseBase._sdk_create/_sdk_stream)
    # ------------------------------------------------------------------

    async def _open_stream(self, model_id: str) -> Any:
        """Open the Nova Sonic bidirectional stream for *model_id*.

        Builds its own ``aws_sdk_bedrock_runtime`` client directly — this
        is NOT ``self._ensure_client()``/``self.get_client()`` (those are
        the ``aioboto3`` Bedrock Runtime client used by the inherited
        text engine and are cached per event loop by
        :class:`~parrot.clients.bedrock.BedrockConverseBase`).

        Returns:
            The SDK's bidirectional stream handle, exposing an
            ``input_stream.send(event: dict)`` coroutine for sending event
            frames and an ``output_stream`` async iterator of response
            event frames (see :meth:`_send_event` / :meth:`_iter_events`).
        """
        from aws_sdk_bedrock_runtime import BedrockAgentRuntimeClient
        from aws_sdk_bedrock_runtime.models import (
            InvokeModelWithBidirectionalStreamOperationInput,
        )
        client = BedrockAgentRuntimeClient(region=self._region)
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
    # Guardrails (calls the inherited BedrockConverseBase method directly —
    # no _get_text_client delegate, per FEAT-315)
    # ------------------------------------------------------------------

    async def _apply_pii_guardrail(self, text: str) -> str:
        """Filter PII from a transcription via the configured guardrail.

        Calls :meth:`~parrot.clients.bedrock.BedrockConverseBase.apply_guardrail_text`
        directly (returns *text* unmodified when no guardrail is
        configured) — the ``_get_text_client()`` delegate pattern from
        ``nova_sonic.py`` no longer exists.
        """
        return await self.apply_guardrail_text(text, source="INPUT")

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
            **kwargs: ``voice_id`` (per-call synthesis voice override, e.g.
                ``"matthew"``, ``"tiffany"``, ``"amy"`` — falls back to the
                ``voice_id`` passed to the client's constructor; spec §8
                resolved: expose ``voice_id`` per-call too) plus reserved
                slots for future configuration (tool overrides, etc.).

        Yields:
            :class:`LiveVoiceResponse` objects with audio, text, tool-call,
            and usage metadata — the same shape ``VoiceChatHandler``
            already consumes from ``GeminiLiveClient``.
        """
        _require_voice_sdk()

        session_id = session_id or str(uuid.uuid4())
        turn_id = str(uuid.uuid4())
        resolved_model = translate_bedrock_model(
            self.model or self.default_model, self._region_prefix
        )
        resolved_voice_id = kwargs.get("voice_id") or self.voice_id
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
                "voiceId": resolved_voice_id,
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
                    # Code-review fix: audioOutputConfiguration declares
                    # "encoding": "base64" (see stream_voice()'s promptStart
                    # event above), so "content" arrives as a base64 *text*
                    # string, not raw bytes — decode it before handing off
                    # as LiveVoiceResponse.audio_data (typed Optional[bytes]).
                    raw_content = audio_output.get("content")
                    audio_bytes = (
                        base64.b64decode(raw_content)
                        if isinstance(raw_content, str) else raw_content
                    )
                    yield LiveVoiceResponse(
                        text="",
                        audio_data=audio_bytes,
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
                # Code-review fix: audioInputConfiguration declares
                # "encoding": "base64" (see stream_voice()'s contentStart
                # event above), so raw PCM bytes must be base64-text-encoded
                # before being embedded in the JSON event frame — sending
                # raw bytes verbatim would both violate the declared wire
                # format and fail JSON serialization outright.
                await self._send_event(stream, {"event": {"audioInput": {
                    "promptName": prompt_name,
                    "contentName": content_name,
                    "content": base64.b64encode(chunk).decode("ascii"),
                }}})
                chunks_sent += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.error("Nova Sonic audio sender error: %s", exc)
