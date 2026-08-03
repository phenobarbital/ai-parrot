"""NovaAudio — bidirectional voice streaming mixin for NovaClient (FEAT-315).

Ports the bidirectional speech-to-speech implementation from the deleted
FEAT-302 voice-only client module (removed in FEAT-315 — see
``docs/migration/feat-315-novaclient.md``) into a plain capability mixin,
composed into
:class:`~parrot.clients.nova.client.NovaClient` alongside
``BedrockConverseBase`` (spec ``novaclient-amazon-aws`` §2/§3 Module 3),
mirroring how :class:`~parrot.clients.google.generation.GoogleGeneration`
is composed into :class:`~parrot.clients.google.client.GoogleGenAIClient`.

.. warning::
    **EXPERIMENTAL.** ``aws_sdk_bedrock_runtime==0.7.0`` is Pre-Alpha and its
    API may change before GA — every raw SDK call is isolated behind four
    thin wrappers (:meth:`NovaAudio._open_stream`,
    :meth:`NovaAudio._send_event`, :meth:`NovaAudio._iter_events`,
    :meth:`NovaAudio._close_stream`, mirroring
    :class:`~parrot.clients.bedrock.BedrockConverseBase`'s
    ``_sdk_create``/``_sdk_stream`` pattern) so only those need updating if
    the SDK's shape changes. The Pre-Alpha SDK is imported lazily — only at
    first :meth:`stream_voice` call, via :func:`_require_voice_sdk` — so
    text/generation-only usage of ``NovaClient`` never requires it.

    The wrappers were verified against the real package on
    ``aws_sdk_bedrock_runtime==0.7.0`` / Python 3.13. The SDK renames its
    client class across minor releases (``BedrockRuntimeClient`` in 0.3.0
    and 0.7.0, ``AsyncBedrockRuntimeClient`` in 0.8.0), so
    :func:`_resolve_voice_client_class` looks the name up tolerantly rather
    than importing a fixed symbol.

.. note::
    **Voice auth cannot use a Bedrock API key.** The text path
    (``BedrockConverseBase``) accepts a bearer token via
    ``aws_bearer_token``/``AWS_NOVA_API_KEY``, exported as
    ``AWS_BEARER_TOKEN_BEDROCK`` for botocore. This Pre-Alpha SDK is
    smithy-based, not botocore-based, and its ``Config`` exposes only
    ``aws_access_key_id``/``aws_secret_access_key``/``aws_session_token``
    (or a credentials resolver) — there is no bearer-auth scheme. A
    bearer-token-only configuration therefore cannot open a voice stream;
    :meth:`_open_stream` warns and falls through to the SDK's default
    credential chain.

See ``sdd/specs/novaclient-amazon-aws.spec.md`` (§3 Module 3) for the full
design.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import time
import uuid
from dataclasses import dataclass
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


# Client-class names seen across Pre-Alpha releases, newest-known name last.
# 0.3.0 / 0.7.0 export ``BedrockRuntimeClient``; 0.8.0 renamed it to
# ``AsyncBedrockRuntimeClient``. NOTE: ``BedrockAgentRuntimeClient`` is NOT in
# this list on purpose — that class belongs to the unrelated
# *bedrock-agent-runtime* service and exists in no version of this package.
_VOICE_CLIENT_CLASS_NAMES: tuple[str, ...] = (
    "BedrockRuntimeClient",
    "AsyncBedrockRuntimeClient",
)


def _resolve_voice_client_class() -> type:
    """Return the bidirectional-stream client class of the installed SDK.

    The Pre-Alpha package renames this class between minor releases and does
    NOT re-export it from the package root, so it is resolved by name from
    ``aws_sdk_bedrock_runtime.client`` instead of imported as a fixed symbol.

    Returns:
        The SDK's Bedrock Runtime client class.

    Raises:
        ImportError: When no known client class name is present, listing what
            the installed package actually exposes so the caller can add the
            new name to :data:`_VOICE_CLIENT_CLASS_NAMES`.
    """
    from aws_sdk_bedrock_runtime import client as sdk_client

    for name in _VOICE_CLIENT_CLASS_NAMES:
        if (cls := getattr(sdk_client, name, None)) is not None:
            return cls

    available = sorted(n for n in dir(sdk_client) if n.endswith("Client"))
    raise ImportError(
        "No known Bedrock Runtime client class found in "
        f"aws_sdk_bedrock_runtime.client (tried "
        f"{', '.join(_VOICE_CLIENT_CLASS_NAMES)}). The installed package "
        f"exposes: {', '.join(available) or '<none>'}. The Pre-Alpha SDK "
        "likely renamed it again — add the new name to "
        "_VOICE_CLIENT_CLASS_NAMES."
    )


@dataclass
class _TurnState:
    """Receive-side state carried across frames within one Nova Sonic turn.

    Nova reports the speaker and generation stage on ``contentStart``, not on
    the ``textOutput`` frames they govern, so this must persist between
    frames. Kept as a local inside :meth:`NovaAudio.stream_voice` — never on
    ``self``, since ``NovaAudio`` is a shared mixin that may serve concurrent
    sessions.
    """
    role: Optional[str] = None
    generation_stage: Optional[str] = None
    pending_tool: Optional[LiveToolCall] = None
    pending_tool_raw_input: Optional[str] = None


def _parse_generation_stage(additional_model_fields: Any) -> Optional[str]:
    """Extract ``generationStage`` from a contentStart's additionalModelFields.

    Nova sends this as a JSON *string*. Returns None when absent or malformed
    — callers treat None as "no stage reported" and emit the text (spec §7:
    a missing stage must never suppress assistant text).

    Args:
        additional_model_fields: The raw ``additionalModelFields`` value from
            a ``contentStart`` frame (expected to be a JSON string).

    Returns:
        The parsed ``generationStage`` value, or ``None`` when absent or the
        value does not parse as a JSON object.
    """
    if not additional_model_fields:
        return None
    try:
        if isinstance(additional_model_fields, str):
            additional_model_fields = json.loads(additional_model_fields)
        return additional_model_fields.get("generationStage")
    except (ValueError, AttributeError):
        return None


class NovaAudio:
    """Bidirectional voice-streaming mixin (Nova Sonic / Nova 2 Sonic).

    Plain mixin — defines NO ``__init__`` (MRO constraint, spec §7) and
    reads the following attributes from the composed client (set by
    :class:`~parrot.clients.nova.client.NovaClient` / inherited from
    ``BedrockConverseBase``): ``self.voice_id``, ``self._region``,
    ``self.model``, ``self.default_model``, ``self.logger``,
    ``self._execute_tool(name, input)``,
    ``self.apply_guardrail_text(text, source)``, plus the credentials
    ``BedrockConverseBase`` resolved — ``self._aws_access_key``,
    ``self._aws_secret_key``, ``self._aws_session_token`` and
    ``self._aws_bearer_token`` (all read defensively via ``getattr``, since
    a mixin cannot assume its host ran that resolution). Deliberately does NOT
    read ``self._region_prefix`` for model resolution — Nova Sonic has no
    cross-region inference profiles (see :meth:`stream_voice`).
    """

    # Nova Sonic's hard limit is ~8 minutes; reconnect with a safety margin
    # so a turn in progress is not cut off mid-stream.
    _CONNECTION_LIMIT_SECONDS: float = 8 * 60 - 15

    # Bound the wait for the stream's initial response. The Pre-Alpha SDK runs
    # the request in a background task and, when that task raises (bad
    # credentials, no model access, wrong region), the output future is never
    # resolved and ``await_output()`` would block forever — a silent hung turn.
    _OUTPUT_READY_TIMEOUT_SECONDS: float = 30.0

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

        Credentials are read from the attributes
        :class:`~parrot.clients.bedrock.BedrockConverseBase` already
        resolved (``_aws_access_key``/``_aws_secret_key``/
        ``_aws_session_token``) rather than re-resolved here, so voice and
        text authenticate as the same identity. When no static keys
        resolved, the credential kwargs are omitted entirely and the SDK's
        own default chain applies. A bearer-token-only configuration is
        warned about — this SDK has no bearer-auth scheme (see the module
        note).

        Returns:
            A ``smithy_core.aio.eventstream.DuplexEventStream``: send input
            events through ``stream.input_stream.send(chunk)`` (see
            :meth:`_send_event`) and obtain the output receiver via
            ``await stream.await_output()`` (see :meth:`_iter_events`).
            Note ``stream.output_stream`` is ``None`` until ``await_output()``
            has been awaited.
        """
        from aws_sdk_bedrock_runtime.config import Config
        from aws_sdk_bedrock_runtime.models import (
            InvokeModelWithBidirectionalStreamOperationInput,
        )
        from smithy_aws_core.identity.chain import create_default_chain

        client_cls = _resolve_voice_client_class()

        config_kwargs: Dict[str, Any] = {"region": self._region}
        access_key = getattr(self, "_aws_access_key", None)
        secret_key = getattr(self, "_aws_secret_key", None)
        if access_key and secret_key:
            config_kwargs["aws_access_key_id"] = access_key
            config_kwargs["aws_secret_access_key"] = secret_key
            if session_token := getattr(self, "_aws_session_token", None):
                config_kwargs["aws_session_token"] = session_token
        elif getattr(self, "_aws_bearer_token", None):
            self.logger.warning(
                "A Bedrock API key (bearer token) is configured, but the "
                "Pre-Alpha voice SDK has no bearer-auth scheme — it cannot "
                "authenticate a Nova Sonic stream. Falling back to the SDK's "
                "environment/IMDS credential chain; pass aws_access_key/"
                "aws_secret_key (or a named aws_id profile) for voice."
            )

        config = Config(**config_kwargs)

        # Setting the static key fields is NOT sufficient: the SDK leaves
        # ``aws_credentials_identity_resolver`` at None by default, and SigV4
        # signing then fails outright with
        # "Attempted to use SigV4 auth, but aws_credentials_identity_resolver
        # was not set on the config." There is no implicit default chain, so
        # install the standard one explicitly — Static (reads the key fields
        # set above) -> Environment -> IMDS — which covers both the explicit
        # credentials case and ambient credentials.
        if config.aws_credentials_identity_resolver is None:
            config.aws_credentials_identity_resolver = create_default_chain(
                http_client=config.transport
            )

        client = client_cls(config=config)
        return await client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=model_id)
        )

    async def _send_event(self, stream: Any, event: Dict[str, Any]) -> None:
        """Send a single JSON event frame to the bidirectional stream.

        The wire format is a length-delimited event-stream chunk carrying the
        JSON frame as an opaque byte payload — the SDK does NOT accept a bare
        dict, so *event* is serialized and wrapped here.

        Args:
            stream: The handle returned by :meth:`_open_stream`.
            event: A Nova Sonic event frame, e.g.
                ``{"event": {"audioInput": {...}}}``.
        """
        from aws_sdk_bedrock_runtime.models import (
            BidirectionalInputPayloadPart,
            InvokeModelWithBidirectionalStreamInputChunk,
        )

        await stream.input_stream.send(
            InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(
                    bytes_=json.dumps(event).encode("utf-8")
                )
            )
        )

    async def _iter_events(self, stream: Any) -> AsyncIterator[Dict[str, Any]]:
        """Yield Nova Sonic output frames as plain, unwrapped dicts.

        Normalizes the SDK's transport shape so :meth:`stream_voice` stays
        SDK-agnostic and can keep doing ``event.get("textOutput")``:

        1. ``await stream.await_output()`` — the receiver does not exist
           until this is awaited (``stream.output_stream`` is ``None``
           before it), which is why this is an async generator rather than
           a plain accessor.
        2. Each received chunk carries its JSON payload as opaque bytes at
           ``chunk.value.bytes_`` — decoded here.
        3. Nova nests every frame under an ``"event"`` envelope
           (``{"event": {"textOutput": {...}}}``) — unwrapped one level here.

        Args:
            stream: The handle returned by :meth:`_open_stream`.

        Yields:
            The inner frame dict, e.g. ``{"textOutput": {"content": "hi"}}``.

        Raises:
            RuntimeError: When the initial response does not arrive within
                :data:`_OUTPUT_READY_TIMEOUT_SECONDS`, or when a chunk carries
                no payload. The output union also contains the service's
                modelled exceptions (validation, throttling, model-timeout,
                service-unavailable, ...), which surface here and are reported
                to ``stream_voice()``'s handler rather than silently skipped.
        """
        try:
            _, receiver = await asyncio.wait_for(
                stream.await_output(), timeout=self._OUTPUT_READY_TIMEOUT_SECONDS
            )
        except TimeoutError as exc:
            raise RuntimeError(
                "Nova Sonic did not return an initial response within "
                f"{self._OUTPUT_READY_TIMEOUT_SECONDS:.0f}s. The Pre-Alpha SDK "
                "swallows request-pipeline failures instead of failing the "
                "stream, so this usually means the request never authenticated "
                "or was rejected: check AWS credentials, Bedrock access to the "
                f"model in region {self._region!r}, and that the account is "
                "enabled for Nova Sonic."
            ) from exc
        async for chunk in receiver:
            payload = getattr(getattr(chunk, "value", None), "bytes_", None)
            if payload is None:
                raise RuntimeError(
                    f"Nova Sonic stream returned a non-payload event: {chunk!r}"
                )
            frame = json.loads(payload)
            # Tolerate an already-unwrapped frame so a caller (or test double)
            # may hand over either shape.
            yield frame.get("event", frame)

    async def _close_stream(self, stream: Any) -> None:
        """Close the bidirectional stream, releasing its connection.

        Called from :meth:`stream_voice`'s ``finally`` block. One
        ``stream_voice()`` call is one turn, so without this every turn
        would leak a connection. Errors are swallowed: the stream may
        already be half-closed by the service when a turn ends.
        """
        with contextlib.suppress(Exception):
            await stream.close()

    # ------------------------------------------------------------------
    # Guardrails (calls the inherited BedrockConverseBase method directly —
    # no _get_text_client delegate, per FEAT-315)
    # ------------------------------------------------------------------

    async def _apply_pii_guardrail(self, text: str) -> str:
        """Filter PII from a transcription via the configured guardrail.

        Calls :meth:`~parrot.clients.bedrock.BedrockConverseBase.apply_guardrail_text`
        directly (returns *text* unmodified when no guardrail is
        configured) — the ``_get_text_client()`` delegate pattern from the
        deleted legacy voice-only client module no longer exists.
        """
        return await self.apply_guardrail_text(text, source="INPUT")

    # ------------------------------------------------------------------
    # Voice streaming
    # ------------------------------------------------------------------

    def _build_prompt_start(self, prompt_name: str, voice_id: str) -> Dict[str, Any]:
        """Build the promptStart event frame for a voice turn.

        Args:
            prompt_name: Per-turn prompt identifier.
            voice_id: Resolved Nova Sonic synthesis voice.

        Returns:
            The complete ``promptStart`` event frame.
        """
        return {"event": {"promptStart": {
            "promptName": prompt_name,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": self.OUTPUT_SAMPLE_RATE_HZ,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "voiceId": voice_id,
                "encoding": "base64",
                "audioType": "SPEECH",
            },
            "toolUseOutputConfiguration": {"mediaType": "application/json"},
        }}}

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
        # Code-review fix (FEAT-315): Nova Sonic / Nova 2 Sonic have NO
        # cross-region inference profiles (spec §6 "Verified AWS Facts") —
        # unlike the text/Converse path, the voice model ID must NEVER be
        # prefixed, even though the composed client (NovaClient) defaults
        # region_prefix="us" for the unrelated Nova 2 Lite/Premier text
        # models. region_prefix=None here bypasses self._region_prefix
        # entirely (mirrors NovaGeneration._translate_in_region_model).
        resolved_model = translate_bedrock_model(
            self.model or self.default_model, region_prefix=None
        )
        resolved_voice_id = kwargs.get("voice_id") or self.voice_id
        prompt_name = str(uuid.uuid4())
        content_name = str(uuid.uuid4())

        turn_metadata = VoiceTurnMetadata(turn_id=turn_id)
        usage = LiveCompletionUsage()
        accumulated_text = ""
        tool_calls_list: List[LiveToolCall] = []
        turn_state = _TurnState()

        self.logger.info(
            "Starting Nova Sonic voice session %s, turn %s (model=%s)",
            session_id, turn_id, resolved_model,
        )

        connection_start = time.monotonic()
        stream = await self._open_stream(resolved_model)

        await self._send_event(stream, {"event": {"sessionStart": {
            "inferenceConfiguration": {"maxTokens": 1024, "topP": 0.9, "temperature": 0.7}
        }}})
        await self._send_event(
            stream, self._build_prompt_start(prompt_name, resolved_voice_id)
        )
        if system_prompt:
            await self._send_event(stream, {"event": {"contentStart": {
                "promptName": prompt_name, "contentName": f"{content_name}-sys",
                "type": "TEXT", "role": "SYSTEM",
                "interactive": False,
                "textInputConfiguration": {"mediaType": "text/plain"},
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
            "interactive": True,
            "audioInputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": self.INPUT_SAMPLE_RATE_HZ,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "encoding": "base64",
                "audioType": "SPEECH",
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

                content_start = event.get("contentStart")
                if content_start:
                    turn_state.role = content_start.get("role")
                    turn_state.generation_stage = _parse_generation_stage(
                        content_start.get("additionalModelFields")
                    )
                    continue

                text_output = event.get("textOutput")
                if text_output:
                    chunk_text = text_output.get("content", "")
                    role = turn_state.role
                    stage = turn_state.generation_stage
                    # Missing stage must EMIT, not suppress (spec §7) — only an
                    # explicitly non-SPECULATIVE stage suppresses assistant text.
                    suppressed = (
                        role == "ASSISTANT"
                        and stage is not None
                        and stage != "SPECULATIVE"
                    )
                    if not suppressed:
                        if role == "ASSISTANT":
                            accumulated_text += chunk_text
                        yield LiveVoiceResponse(
                            text=chunk_text,
                            role=role,
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
            # The SDK's modelled service errors (AccessDeniedException,
            # ValidationException, ...) frequently carry an EMPTY str(), so a
            # bare str(exc) yields "Nova Sonic session <id> error: " and a
            # metadata payload of {"error": ""} — undiagnosable, and falsy
            # enough that consumers testing truthiness miss the failure
            # entirely. Always include the exception type.
            error_message = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            self.logger.exception(
                "Nova Sonic session %s error: %s", session_id, error_message
            )
            yield LiveVoiceResponse(
                text="",
                is_complete=True,
                metadata={"error": error_message},
                session_id=session_id,
                turn_id=turn_id,
                user_id=user_id,
            )
        finally:
            sender_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender_task
            # One stream_voice() call == one turn, so the stream opened above
            # must be released here or every turn leaks its connection.
            await self._close_stream(stream)

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
