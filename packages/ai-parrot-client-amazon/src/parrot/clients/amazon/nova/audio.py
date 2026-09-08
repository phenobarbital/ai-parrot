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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional

from ..models import translate as translate_bedrock_model
from ....models.voice import (
    LiveCompletionUsage,
    LiveToolCall,
    LiveVoiceResponse,
    VoiceStreamOptions,
    VoiceTurnMetadata,
)
from ....tools.abstract import ToolResult

if TYPE_CHECKING:
    from ....auth.permission import PermissionContext

# FEAT-536 TASK-2939: internal execution kwargs the manager's
# AbstractTool/ToolDefinition dispatch reserves for trusted, request-local
# use (permission enforcement, credential broker). A malicious or confused
# model must never be able to set these by naming them as tool arguments —
# stripped from provider-supplied args before merging trusted context in
# ``NovaAudio._build_trusted_tool_arguments``.
_RESERVED_TOOL_KWARGS: frozenset = frozenset(
    {"_permission_context", "_resolver", "_broker", "_cred_channel", "_cred_user_id"}
)

# Nova Sonic / Nova 2 Sonic synthesis voice catalog (FEAT-418, TASK-2169).
#
# Promoted from the docstring-only list at ``stream_voice()``'s ``**kwargs``
# documentation (below) into an actual validated constant. All entries are
# lowercase — Bedrock voice ids are lowercase, and ``NovaAudio._resolve_voice``
# normalizes any requested voice before comparing against this set.
#
# NOTE (spec §8 open question, unresolved): this repo has no prior
# machine-readable Nova Sonic voice catalog; the docstring's three
# English-locale voices (``matthew``, ``tiffany``, ``amy``) are the only
# ones independently verifiable from the existing codebase in this sandbox
# (no live network access to re-confirm the full multilingual catalog
# against the current AWS Bedrock Nova Sonic documentation). If the true
# catalog is larger, `_resolve_voice()`'s warn-and-fall-back behavior
# (never a hard reject) means an unlisted-but-valid voice degrades to a
# logged warning rather than breaking the call — see Completion Note.
NOVA_VOICE_CATALOG: frozenset = frozenset({"matthew", "tiffany", "amy"})


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
    # FEAT-416 (TASK-2148): completed (contentEnd-TOOL) tool calls queued
    # for execution, as (LiveToolCall, raw_input) pairs. Nova may emit
    # several toolUse/contentEnd(TOOL) pairs back-to-back in one turn
    # before the next non-tool event — this queue accumulates them so they
    # can be executed together (see NovaAudio._flush_pending_tools).
    pending_tools: List[tuple] = field(default_factory=list)


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


def _is_interruption_payload(content: str) -> bool:
    """Return whether a textOutput content payload signals barge-in.

    Nova signals interruption by sending an ``{"interrupted": true}`` object
    as the text content. Parse it rather than matching the sample's exact
    whitespace (``nova_sonic_tool_use.py:632`` uses
    ``'{ "interrupted" : true }'``, but the spacing is incidental), falling
    back to a whitespace-insensitive substring test for payloads that fail
    to parse as JSON.

    Args:
        content: The raw ``textOutput.content`` string.

    Returns:
        ``True`` when the payload signals an interruption.
    """
    if not content:
        return False
    try:
        parsed = json.loads(content)
    except ValueError:
        compact = "".join(content.split())
        return '"interrupted":true' in compact
    return bool(isinstance(parsed, dict) and parsed.get("interrupted"))


def _parse_tool_arguments(raw: Any) -> Dict[str, Any]:
    """Parse a toolUse content payload into kwargs for ``_execute_tool()``.

    Nova sends this as a JSON string. Raises ``ValueError`` for anything that
    does not decode to a JSON object, so the caller can report a tool error
    instead of crashing the turn.

    Args:
        raw: The stashed ``toolUse.content`` payload.

    Returns:
        The parsed keyword-argument dict.

    Raises:
        ValueError: When *raw* is not valid JSON, or decodes to something
            other than a JSON object.
    """
    if isinstance(raw, dict):
        return raw  # tolerate an already-parsed payload
    parsed = json.loads(raw or "{}")  # ValueError on malformed input
    if not isinstance(parsed, dict):
        raise ValueError(f"tool arguments must be a JSON object, got {type(parsed).__name__}")
    return parsed


# Candidate key spellings, most-likely first. The Pre-Alpha samples do not
# document usageEvent's schema (spec §8 Q1), so probe rather than assume.
_USAGE_INPUT_KEYS = ("inputTokens", "promptTokens", "input_tokens")
_USAGE_OUTPUT_KEYS = ("outputTokens", "completionTokens", "output_tokens")
_USAGE_TOTAL_KEYS = ("totalTokens", "total_tokens")


def _first_int(source: Dict[str, Any], keys: tuple) -> Optional[int]:
    """Return the first key present in *source* whose value is an int.

    Args:
        source: The (possibly flattened) usageEvent frame.
        keys: Candidate key spellings to probe, most-likely first.

    Returns:
        The first matching value coerced to ``int``, or ``None`` when no
        candidate key is present with a numeric value.
    """
    for key in keys:
        value = source.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


class NovaAudio:
    """Bidirectional voice-streaming mixin (Nova Sonic / Nova 2 Sonic).

    Plain mixin — defines NO ``__init__`` (MRO constraint, spec §7) and
    reads the following attributes from the composed client (set by
    :class:`~parrot.clients.nova.client.NovaClient` / inherited from
    ``BedrockConverseBase``): ``self.voice_id``, ``self._region``,
    ``self.model``, ``self.default_model``, ``self.logger``,
    ``self.tool_manager``, ``self._tool_param_names(name)`` (FEAT-536
    TASK-2939 — tool execution goes through
    ``self.tool_manager.execute_tool(..., return_tool_result=True)`` via
    :meth:`_execute_tool_full`, NOT the reducing
    ``self._execute_tool(name, input)`` route used elsewhere/by default),
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

    # FEAT-536 TASK-2941 (spec §2 "Scheduling, correlation and lifecycle"):
    # named, private, test-patchable constants for the tool coordinator's
    # bounds. NOT new public VoiceConfig/VoiceStreamOptions options — never
    # threaded through **kwargs.
    #
    # Per-call deadline measured from ADMISSION (not from when execution
    # actually starts) — "consistent with the existing remote-tool default
    # scale" (spec §2); a call still queued when its deadline elapses
    # expires without ever starting.
    _TOOL_CALL_DEADLINE_SECONDS: float = 300.0
    # Bound admitted-but-unfinished calls per stream (TASK-2940 already
    # enforces this; re-declared here as the same named constant so both
    # tasks' tests can patch one canonical name).
    _MAX_UNFINISHED_TOOLS: int = 32
    # Concurrency cap when parallel_tool_execution=True (serial mode is
    # always capped at 1, not patchable via this constant).
    _MAX_PARALLEL_TOOLS: int = 4
    # Bound cooperative task cleanup in stream_voice()'s finally block —
    # a non-cooperative tool or an already-running thread cannot be forced
    # to stop; this only bounds how long cleanup WAITS for cooperative
    # cancellation before giving up and closing the transport anyway.
    _CLEANUP_TIMEOUT_SECONDS: float = 5.0

    # PCM format constants (spec §2/§7).
    INPUT_SAMPLE_RATE_HZ: int = 16000
    OUTPUT_SAMPLE_RATE_HZ: int = 24000

    def _resolve_voice(self, requested: Optional[str]) -> str:
        """Resolve and validate the effective Nova Sonic voice (FEAT-418).

        Validates ``requested`` against :data:`NOVA_VOICE_CATALOG`
        (case-insensitively — Bedrock voice ids are lowercase). An
        out-of-catalog voice (e.g. ``"Puck"``, a Gemini voice sent here by
        ``bots/voice.py:198`` before FEAT-418) warns and falls back to
        ``self.voice_id`` rather than being passed through to Bedrock
        unvalidated. Never mutates ``self.voice_id`` — resolved locally
        per call, mirroring ``GeminiLiveClient._resolve_voice_name``.

        Args:
            requested: The per-call voice override
                (``stream_voice(voice_id=...)``), or ``None`` to use the
                constructor's default.

        Returns:
            The voice id to use for this call.
        """
        if requested is None:
            return self.voice_id
        normalized = requested.strip().lower()
        if normalized in NOVA_VOICE_CATALOG:
            return normalized
        self.logger.warning(
            "NovaAudio: voice %r is not in the known catalog; falling back to %r",
            requested,
            self.voice_id,
        )
        return self.voice_id

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
            config.aws_credentials_identity_resolver = create_default_chain(http_client=config.transport)

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

        payload_bytes = json.dumps(event).encode("utf-8")
        # --- DIAG: log every non-audio event so we can see what Nova rejects ---
        inner = event.get("event", event)
        event_type = next(
            (k for k in inner if k not in ("promptName", "contentName")),
            "unknown",
        )
        if event_type != "audioInput":
            self.logger.debug(
                "→ _send_event [%s] (%d bytes): %s",
                event_type,
                len(payload_bytes),
                payload_bytes.decode("utf-8"),
            )
        else:
            self.logger.debug(
                "→ _send_event [audioInput] (%d bytes)",
                len(payload_bytes),
            )
        # --- /DIAG ---
        await stream.input_stream.send(
            InvokeModelWithBidirectionalStreamInputChunk(value=BidirectionalInputPayloadPart(bytes_=payload_bytes))
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
            _, receiver = await asyncio.wait_for(stream.await_output(), timeout=self._OUTPUT_READY_TIMEOUT_SECONDS)
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
                raise RuntimeError(f"Nova Sonic stream returned a non-payload event: {chunk!r}")
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

    async def _end_session(
        self,
        stream: Any,
        prompt_name: str,
        content_name: str | None = None,
    ) -> None:
        """Tell Nova Sonic the prompt and session are finished.

        Sends the complete shutdown sequence that the AWS reference sample
        uses::

            contentEnd  (closes the user-audio content block)
            promptEnd   (tells the model this prompt is done)
            sessionEnd  (tears down the session)

        ``contentEnd`` is only sent when *content_name* is provided (it is
        ``None`` in error paths where the audio content block was never
        opened).  Best-effort: called from :meth:`stream_voice`'s
        ``finally``, where the stream may already be half-closed by the
        service, and where raising would mask the real error.

        Args:
            stream: The handle returned by :meth:`_open_stream`.
            prompt_name: The turn's prompt identifier.
            content_name: The user-audio content block identifier. When
                provided, a ``contentEnd`` frame is sent before
                ``promptEnd`` to close the content block cleanly.
        """
        try:
            if content_name is not None:
                await self._send_event(
                    stream,
                    {
                        "event": {
                            "contentEnd": {
                                "promptName": prompt_name,
                                "contentName": content_name,
                            }
                        }
                    },
                )
            await self._send_event(stream, {"event": {"promptEnd": {"promptName": prompt_name}}})
            await self._send_event(stream, {"event": {"sessionEnd": {}}})
        except Exception as exc:  # noqa: BLE001 — must never escape finally
            self.logger.debug("Nova Sonic session shutdown frames not delivered: %s", exc)

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

    def _build_tool_configuration(self) -> Optional[Dict[str, Any]]:
        """Build Nova Sonic's toolConfiguration from the client's tools.

        Returns:
            ``{"tools": [{"toolSpec": {...}}, ...]}``, or None when the client
            has no registered tools — in which case the caller must omit the
            ``toolConfiguration`` key from ``promptStart`` entirely rather than
            sending an empty list.
        """
        manager = getattr(self, "tool_manager", None)
        if manager is None:
            return None
        specs = []
        for tool in manager.all_tools():
            try:
                # AbstractTool instances (the @tool decorator, toolkits) expose
                # get_schema(); plain ToolDefinition entries (registered via
                # ToolManager.register_tool() without an AbstractTool wrapper)
                # do not and instead carry name/description/input_schema
                # directly — mirrors LiveToolAdapter._tool_to_declaration()'s
                # verified branching (clients/google/live.py).
                if hasattr(tool, "get_schema"):
                    schema = tool.get_schema()
                    name = schema.get("name", getattr(tool, "name", "unknown"))
                    description = schema.get("description", getattr(tool, "description", ""))
                    parameters = schema.get("parameters", {})
                elif hasattr(tool, "input_schema"):
                    name = getattr(tool, "name", "unknown")
                    description = getattr(tool, "description", "")
                    parameters = tool.input_schema
                else:
                    self.logger.warning("Skipping tool with unrecognized shape: %r", tool)
                    continue
            except Exception:  # a broken tool must not kill the turn
                self.logger.warning("Skipping tool with unreadable schema: %r", tool)
                continue
            # Nova Sonic's bidirectional streaming protocol expects
            # inputSchema.json to be a **JSON string** (double-serialized),
            # NOT a nested dict — verified against the AWS reference sample
            # (nova_sonic_tool_use.py:345-366). Passing a dict causes
            # "Unable to parse input chunk" (ValidationException).
            schema_value = json.dumps(parameters) if isinstance(parameters, dict) else parameters
            specs.append(
                {
                    "toolSpec": {
                        "name": name,
                        "description": description,
                        "inputSchema": {"json": schema_value},
                    }
                }
            )
        return {"tools": specs} if specs else None

    def _build_prompt_start(self, prompt_name: str, voice_id: str) -> Dict[str, Any]:
        """Build the promptStart event frame for a voice turn.

        Args:
            prompt_name: Per-turn prompt identifier.
            voice_id: Resolved Nova Sonic synthesis voice.

        Returns:
            The complete ``promptStart`` event frame.
        """
        prompt_start: Dict[str, Any] = {
            "promptName": prompt_name,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": self.OUTPUT_SAMPLE_RATE_HZ,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "voiceId": voice_id,
                "encoding": "base64",
                # FEAT-408 Module 2 (gap 10): the AWS sample includes
                # audioType; without it Nova may not recognise the output
                # as speech synthesis.
                "audioType": "SPEECH",
            },
        }
        tool_configuration = self._build_tool_configuration()
        if tool_configuration is not None:
            prompt_start["toolConfiguration"] = tool_configuration
            prompt_start["toolUseOutputConfiguration"] = {
                "mediaType": "application/json",
            }
        return {"event": {"promptStart": prompt_start}}

    async def _send_tool_result(self, stream: Any, prompt_name: str, tool_use_id: str, result: Any) -> None:
        """Send a tool result as the three-frame sequence Nova requires.

        ``contentStart(TOOL)`` -> ``toolResult`` -> ``contentEnd``.
        ``toolUseId`` is carried on the contentStart's
        ``toolResultInputConfiguration``; the ``toolResult`` frame itself is
        keyed by ``contentName``, not ``toolUseId``.

        Args:
            stream: The handle returned by :meth:`_open_stream`.
            prompt_name: The turn's prompt identifier.
            tool_use_id: The ``toolUseId`` from the originating ``toolUse``
                frame.
            result: The tool's return value (or error string).
        """
        content_name = str(uuid.uuid4())
        await self._send_event(
            stream,
            {
                "event": {
                    "contentStart": {
                        "promptName": prompt_name,
                        "contentName": content_name,
                        "interactive": False,
                        "type": "TOOL",
                        "role": "TOOL",
                        "toolResultInputConfiguration": {
                            "toolUseId": tool_use_id,
                            "type": "TEXT",
                            "textInputConfiguration": {"mediaType": "text/plain"},
                        },
                    }
                }
            },
        )
        if isinstance(result, str):
            content = result
        else:
            try:
                content = json.dumps(result)
            except TypeError:
                # A tool may legitimately return a non-JSON-serializable
                # object (e.g. a DataFrame); falling back to str() keeps this
                # one tool call's result-reporting from aborting the turn.
                content = str(result)
        await self._send_event(
            stream,
            {
                "event": {
                    "toolResult": {
                        "promptName": prompt_name,
                        "contentName": content_name,
                        "content": content,
                    }
                }
            },
        )
        await self._send_event(
            stream,
            {
                "event": {
                    "contentEnd": {
                        "promptName": prompt_name,
                        "contentName": content_name,
                    }
                }
            },
        )

    def _build_trusted_tool_arguments(
        self,
        tool_name: str,
        model_args: Dict[str, Any],
        *,
        session_id: Optional[str],
        user_id: Optional[str],
        turn_id: Optional[str],
    ) -> Dict[str, Any]:
        """Merge trusted request-local context into model-provided tool
        arguments (FEAT-536 TASK-2939 — spec §2 "Trusted execution context").

        Reserved internal execution kwargs (``_permission_context``,
        ``_resolver``, ``_broker``, ...) are stripped from *model_args*
        first — a provider/model must never be able to set these by naming
        them as tool arguments. ``session_id``/``user_id``/``turn_id`` are
        then injected ONLY for fields the tool's declared schema/signature
        actually accepts (via the existing
        :meth:`~parrot.clients.base.AbstractClient._tool_param_names`
        introspection — ``None`` means "accepts everything", e.g. ``**kwargs``
        tools), and are merged LAST so trusted values always win over any
        model-supplied value with the same key — the OPPOSITE precedence of
        :meth:`~parrot.clients.base.AbstractClient._execute_tool`, whose
        ``{**filtered_ctx, **parameters}`` merge lets the model override
        context (spec explicitly calls this out as unsuitable for Nova's
        trusted path).

        Args:
            tool_name: The tool being invoked (schema lookup key).
            model_args: Parsed provider/model-supplied arguments.
            session_id: Trusted session identifier, or ``None``.
            user_id: Trusted user identifier, or ``None``.
            turn_id: Trusted turn identifier, or ``None``.

        Returns:
            The merged arguments dict to pass to
            :meth:`~parrot.tools.manager.ToolManager.execute_tool`.
        """
        args = {k: v for k, v in model_args.items() if k not in _RESERVED_TOOL_KWARGS}

        trusted = {"session_id": session_id, "user_id": user_id, "turn_id": turn_id}
        trusted = {k: v for k, v in trusted.items() if v is not None}

        accepted = self._tool_param_names(tool_name)
        if accepted is not None:
            trusted = {k: v for k, v in trusted.items() if k in accepted}

        return {**args, **trusted}

    async def _execute_tool_full(
        self,
        tool_name: str,
        model_args: Dict[str, Any],
        *,
        session_id: Optional[str],
        user_id: Optional[str],
        turn_id: Optional[str],
        permission_context: Optional["PermissionContext"],
    ) -> ToolResult:
        """Execute a tool through the manager's opt-in complete-result mode
        (FEAT-536 TASK-2939, Module 2 — replaces the reducing
        :meth:`~parrot.clients.base.AbstractClient._execute_tool` route for
        Nova voice ONLY; ``NovaClient._execute_tool`` itself is NOT
        overridden, so the text/generation path is unaffected).

        Uses the SAME dispatch exactly once, with the manager's existing
        permissions, grant/confirmation checks, credential broker, lifecycle
        and result hooks (spec §2 G2) — never bypasses
        :class:`~parrot.tools.manager.ToolManager`.

        Args:
            tool_name: The tool to execute.
            model_args: Parsed provider/model-supplied arguments.
            session_id: Trusted session identifier for context injection.
            user_id: Trusted user identifier for context injection.
            turn_id: Trusted turn identifier for context injection.
            permission_context: Optional trusted ``PermissionContext`` from
                a Python caller's ``**kwargs`` (never derived from provider/
                model arguments — spec §2).

        Returns:
            The full ``ToolResult`` envelope (never the reduced payload).
        """
        merged_args = self._build_trusted_tool_arguments(
            tool_name, model_args, session_id=session_id, user_id=user_id, turn_id=turn_id
        )
        result = await self.tool_manager.execute_tool(
            tool_name,
            merged_args,
            permission_context=permission_context,
            return_tool_result=True,
        )
        if not isinstance(result, ToolResult):
            # Defensive: return_tool_result=True always yields a ToolResult
            # (TASK-2937/2938) — normalize just in case a future manager
            # change slips an unwrapped value through.
            result = ToolResult(status="success", result=result)
        return result

    def _map_tool_result_to_nova(self, result: ToolResult) -> tuple[Any, Optional[Dict[str, Any]], str]:
        """Map a complete ``ToolResult`` onto Nova's wire payload plus an
        optional visual event (FEAT-536 TASK-2939 — spec §2 "Nova
        tool-to-voice mapping" precedence table).

        A successful envelope means ``status == "success" and success is
        True``. Precedence for the provider-facing (spoken) payload:
        nonempty ``voice_text`` wins (``{"output": voice_text}``); else a
        dict ``result`` is sent as-is; else a string ``result`` becomes
        ``{"output": result}``; else ``None`` maps to ``{"output":
        "Success"}`` and any OTHER value (including falsy scalars like
        ``False``/``0``, which must survive, not be confused with missing
        data) becomes ``{"output": str(result)}``. A non-success envelope
        (or one whose ``display_data`` cannot be delivered) never emits a
        visual event; ``display_data`` itself is never serialized into the
        spoken channel.

        Args:
            result: The full envelope from :meth:`_execute_tool_full`.

        Returns:
            ``(provider_result, display_data_or_None, tool_status)`` —
            ``provider_result`` is what :meth:`_send_tool_result` sends to
            Nova; ``display_data`` is the nonempty JSON-serializable visual
            payload (or ``None``); ``tool_status`` is ``result.status``,
            recorded by the caller under ``metadata["tool_status"]``.
        """
        is_successful = result.status == "success" and result.success is True
        if not is_successful:
            message = result.error or f"Tool failed with status={result.status}"
            return {"error": message, "status": result.status}, None, result.status

        if result.voice_text:
            provider_result: Any = {"output": result.voice_text}
        elif isinstance(result.result, dict):
            provider_result = result.result
        elif isinstance(result.result, str):
            provider_result = {"output": result.result}
        elif result.result is None:
            provider_result = {"output": "Success"}
        else:
            # Preserve falsy scalars (False, 0, "") rather than treating
            # them as missing data — only `None` gets the "Success" default.
            provider_result = {"output": str(result.result)}

        display_data: Optional[Dict[str, Any]] = None
        # An empty dict stays suppressed, matching Gemini/the existing
        # handler (spec §2) — `if result.display_data` is falsy for {}.
        if result.display_data:
            try:
                json.dumps(result.display_data)
                display_data = result.display_data
            except (TypeError, ValueError):
                # Omit the visual event but let the valid spoken result
                # still reach Nova — do not fail the whole tool call over
                # a non-serializable visual payload.
                self.logger.warning(
                    "display_data for a tool result is not JSON-serializable "
                    "(status=%s); omitting the visual event.",
                    result.status,
                )

        return provider_result, display_data, result.status

    async def _send_event_locked(self, write_lock: asyncio.Lock, stream: Any, event: Dict[str, Any]) -> None:
        """Send a single wire event while holding *write_lock* (FEAT-536
        TASK-2940 — spec §2 "Serialize outbound SDK writes with a
        stream-local mechanism").

        Held only for the duration of one ``_send_event`` call — never
        across tool execution or a provider-event wait, and never
        recursively (this is the only place ``write_lock`` is acquired;
        :meth:`_execute_and_deliver_tool` acquires it once, briefly, for
        its own 3-frame tool-result sequence, and releases it before
        returning).

        Args:
            write_lock: The per-stream lock created once in
                :meth:`stream_voice` and shared by the audio sender, the
                tool-coordinator and the setup/shutdown sequences.
            stream: The handle returned by :meth:`_open_stream`.
            event: The event frame to send.
        """
        async with write_lock:
            await self._send_event(stream, event)

    async def _execute_and_deliver_tool(
        self,
        pending: LiveToolCall,
        raw_input: Optional[str],
        *,
        stream: Any,
        prompt_name: str,
        write_lock: asyncio.Lock,
        session_id: Optional[str],
        turn_id: str,
        user_id: Optional[str],
        permission_context: Optional["PermissionContext"],
        deadline_at: Optional[float] = None,
    ) -> LiveVoiceResponse:
        """Execute ONE admitted tool call end-to-end and build its streamed
        delta (FEAT-536 TASK-2940 — spec §3 Module 3; deadline enforcement
        added by TASK-2941).

        Shared by the immediate-admission coordinator in
        :meth:`stream_voice` (one call per admitted tool, run as its own
        ``asyncio.Task`` so the coordinator can await provider events and
        tool completions concurrently). Mirrors
        :meth:`_flush_pending_tools`'s inner per-tool logic (TASK-2939)
        but does NOT touch ``tool_calls_list``/``usage`` bookkeeping —
        left to the caller so admission-time (arrival) ordering into
        ``tool_calls_list`` is preserved regardless of completion order
        (spec §2: "Result delivery follows completion order with stable
        IDs. Arrival order remains available for the final snapshot.").

        Uses :meth:`_execute_tool_full` (TASK-2939) — the SAME dispatch
        exactly once — never re-executes a tool and never bypasses the
        manager. The manager's own per-instance lock (TASK-2938) already
        serializes same-instance calls; this method does not duplicate
        that.

        Args:
            pending: The admitted ``LiveToolCall`` (mutated in place with
                ``arguments``/``result``/``error``/``execution_time_ms``).
            raw_input: The stashed raw ``toolUse.content`` JSON string.
            stream: The handle returned by :meth:`_open_stream`.
            prompt_name: The turn's prompt identifier.
            write_lock: The stream-local write lock (see
                :meth:`_send_event_locked`) — held only for the 3-frame
                tool-result sequence, never across execution.
            session_id: Session identifier for the yielded response.
            turn_id: Turn identifier for the yielded response.
            user_id: User identifier for the yielded response.
            permission_context: Optional trusted ``PermissionContext``.
            deadline_at: Absolute ``time.monotonic()`` deadline (FEAT-536
                TASK-2941 — spec §2: "a 300 s per-call deadline from
                admission ... a queued call may expire before starting").
                Measured from ADMISSION by the caller (``time.monotonic()
                + self._TOOL_CALL_DEADLINE_SECONDS`` at
                ``_admit_tool()`` time), so queue wait counts against it.
                ``None`` disables the deadline (used by
                :meth:`_flush_pending_tools`'s unrelated batch path,
                which does not pass this argument).

        Returns:
            The one :class:`LiveVoiceResponse` delta for this tool call.
        """
        start = time.monotonic()
        try:
            if deadline_at is not None and start >= deadline_at:
                # Already expired while queued — never even dispatch.
                raise TimeoutError(
                    f"Tool call deadline ({self._TOOL_CALL_DEADLINE_SECONDS}s from admission) "
                    "expired before execution could start."
                )
            args = _parse_tool_arguments(raw_input)
            pending.arguments = args
            remaining = (deadline_at - start) if deadline_at is not None else None
            coro = self._execute_tool_full(
                pending.name,
                args,
                session_id=session_id,
                user_id=user_id,
                turn_id=turn_id,
                permission_context=permission_context,
            )
            if remaining is not None:
                # Deliberately NOT asyncio.wait_for(coro, timeout=...) —
                # functionally equivalent, but this explicit
                # wrap-in-a-task/asyncio.wait/cancel-and-await sequence
                # matches the pattern already used (and verified) for the
                # coordinator's OTHER timeouts in this method, keeping the
                # cancellation semantics uniform across the file.
                inner_task = asyncio.ensure_future(coro)
                done, _pending_set = await asyncio.wait({inner_task}, timeout=remaining)
                if inner_task in done:
                    tool_result = inner_task.result()
                else:
                    inner_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await inner_task
                    raise TimeoutError(
                        f"Tool call exceeded its {self._TOOL_CALL_DEADLINE_SECONDS}s deadline during execution."
                    )
            else:
                tool_result = await coro
            provider_result, display_data, tool_status = self._map_tool_result_to_nova(tool_result)
            if tool_status != "success" or tool_result.success is not True:
                pending.error = tool_result.error or f"Tool failed with status={tool_status}"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            pending.error = str(exc)
            provider_result = {"error": str(exc), "status": "error"}
            display_data = None
            tool_status = "error"
        pending.result = provider_result
        pending.execution_time_ms = (time.monotonic() - start) * 1000

        # Serialized against audio input / other tool results / shutdown —
        # held only for :meth:`_send_tool_result`'s 3-frame sequence, never
        # across execution or a provider-event wait (no lock is held above
        # this point). Reuses `_send_tool_result` verbatim rather than
        # re-implementing the contentStart/toolResult/contentEnd framing.
        async with write_lock:
            await self._send_tool_result(stream, prompt_name, pending.id, provider_result)

        response_metadata: Dict[str, Any] = {"tool_status": tool_status}
        if display_data is not None:
            response_metadata["display_data"] = display_data
        return LiveVoiceResponse(
            text="",
            tool_calls=[pending],
            is_complete=False,
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_id,
            metadata=response_metadata,
        )

    async def _flush_pending_tools(
        self,
        stream: Any,
        prompt_name: str,
        pending_tools: List[tuple],
        tool_calls_list: List[LiveToolCall],
        usage: LiveCompletionUsage,
        session_id: Optional[str],
        turn_id: str,
        user_id: Optional[str],
        parallel_tool_execution: bool,
        permission_context: Optional["PermissionContext"] = None,
    ) -> List[LiveVoiceResponse]:
        """Execute and send results for all queued tool calls (FEAT-416,
        TASK-2148 — spec §3 Module 4; result mapping updated by FEAT-536
        TASK-2939 — spec §3 Module 2).

        Executes sequentially (current, default behavior) unless
        *parallel_tool_execution* is ``True`` AND more than one tool is
        queued, in which case all queued tools run concurrently via
        ``asyncio.TaskGroup``. Either way, every tool's result is sent back
        via :meth:`_send_tool_result` (all results reach Nova before the
        model resumes — a Nova Sonic protocol requirement) and one
        :class:`LiveVoiceResponse` is returned per tool, in queued order.

        A per-tool ``try/except`` (not TaskGroup's own exception
        propagation, which would cancel sibling tasks) ensures one failing
        tool does not prevent the others from completing.

        Args:
            stream: The handle returned by :meth:`_open_stream`.
            prompt_name: The turn's prompt identifier.
            pending_tools: Queued ``(LiveToolCall, raw_input)`` pairs.
            tool_calls_list: The turn's accumulated tool-call list; executed
                calls are appended here.
            usage: The turn's usage accumulator; tool timing/count fields
                are updated in place.
            session_id: Session identifier for the yielded responses.
            turn_id: Turn identifier for the yielded responses.
            user_id: User identifier for the yielded responses.
            parallel_tool_execution: Concurrency gate (from ``VoiceConfig``,
                wired via ``**kwargs`` — TASK-2151 threads this from
                ``VoiceBot``).
            permission_context: Optional trusted ``PermissionContext``
                (FEAT-536 TASK-2939), forwarded to
                :meth:`_execute_tool_full` for every queued call.

        Returns:
            One :class:`LiveVoiceResponse` per queued tool, in order.
        """
        if not pending_tools:
            return []

        async def _run_one(
            pending: LiveToolCall, raw_input: Optional[str]
        ) -> tuple[Any, Optional[Dict[str, Any]], str]:
            start = time.monotonic()
            try:
                args = _parse_tool_arguments(raw_input)
                # Record what was actually attempted before executing, so
                # LiveToolCall.arguments reflects the real arguments even if
                # execution itself raises.
                pending.arguments = args
                tool_result = await self._execute_tool_full(
                    pending.name,
                    args,
                    session_id=session_id,
                    user_id=user_id,
                    turn_id=turn_id,
                    permission_context=permission_context,
                )
                provider_result, display_data, tool_status = self._map_tool_result_to_nova(tool_result)
                if tool_status != "success" or tool_result.success is not True:
                    pending.error = tool_result.error or f"Tool failed with status={tool_status}"
            except Exception as exc:
                pending.error = str(exc)
                provider_result = {"error": str(exc), "status": "error"}
                display_data = None
                tool_status = "error"
            # LiveToolCall.result carries the NORMALIZED provider-facing
            # result (spec §2), not the raw ToolResult envelope.
            pending.result = provider_result
            pending.execution_time_ms = (time.monotonic() - start) * 1000
            return provider_result, display_data, tool_status

        if parallel_tool_execution and len(pending_tools) > 1:
            async with asyncio.TaskGroup() as tg:
                tasks = [tg.create_task(_run_one(pending, raw_input)) for pending, raw_input in pending_tools]
            outcomes = [task.result() for task in tasks]
        else:
            outcomes = [await _run_one(pending, raw_input) for pending, raw_input in pending_tools]

        responses: List[LiveVoiceResponse] = []
        for (pending, _raw_input), (provider_result, display_data, tool_status) in zip(
            pending_tools, outcomes, strict=True
        ):
            tool_calls_list.append(pending)
            usage.tool_calls_executed += 1
            usage.tool_execution_time_ms += pending.execution_time_ms
            await self._send_tool_result(stream, prompt_name, pending.id, provider_result)
            # FEAT-536 TASK-2939: the streamed delta carries
            # metadata["tool_status"] and, when present, a nonempty
            # JSON-serializable metadata["display_data"] — one visual
            # update per successful, non-stale invocation (spec §2).
            response_metadata: Dict[str, Any] = {"tool_status": tool_status}
            if display_data is not None:
                response_metadata["display_data"] = display_data
            responses.append(
                LiveVoiceResponse(
                    text="",
                    tool_calls=[pending],
                    is_complete=False,
                    session_id=session_id,
                    turn_id=turn_id,
                    user_id=user_id,
                    metadata=response_metadata,
                )
            )
        return responses

    async def stream_voice(
        self,
        audio_iterator: AsyncIterator[bytes],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stt_only: bool = False,
        options: Optional[VoiceStreamOptions] = None,
        **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]:
        """Stream bidirectional voice interaction via Nova Sonic.

        Follows :meth:`~parrot.clients.google.live.GeminiLiveClient.stream_voice`'s
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
            stt_only: Requests speech-to-text-only behavior (FEAT-418).
                Nova Sonic has NO native STT-only mode — accepted without
                raising, logged once (not per frame), and the model
                response is still generated and still billed (resolved
                decision, spec §8; see
                :attr:`~parrot.models.voice.VoiceCapabilities.native_stt_only`
                = ``False`` on this client's descriptor). This is honest,
                not equivalent — do NOT filter the response to fake
                STT-only.
            options: Optional ``VoiceStreamOptions`` projection (FEAT-418).
                ``temperature``/``max_tokens``/``top_p``/``voice``/
                ``parallel_tool_execution`` are derived from it when not
                explicitly present in ``**kwargs`` — an explicit kwarg
                always wins over ``options``.
            **kwargs: ``voice_id`` (per-call synthesis voice override, e.g.
                ``"matthew"``, ``"tiffany"``, ``"amy"`` — falls back to the
                ``voice_id`` passed to the client's constructor; spec §8
                resolved: expose ``voice_id`` per-call too),
                ``temperature``/``max_tokens``/``top_p``/
                ``parallel_tool_execution`` (take precedence over
                ``options``, FEAT-418) plus reserved slots for future
                configuration (tool overrides, etc.).

        Yields:
            :class:`LiveVoiceResponse` objects with audio, text, tool-call,
            and usage metadata — the same shape ``VoiceChatHandler``
            already consumes from ``GeminiLiveClient``.
        """
        _require_voice_sdk()

        session_id = session_id or str(uuid.uuid4())
        turn_id = str(uuid.uuid4())

        # FEAT-418 (TASK-2170): Nova cannot suppress generation — accept
        # stt_only without raising or filtering, and say so once per
        # session (this call), not per frame.
        if stt_only:
            self.logger.info(
                "NovaAudio: stt_only requested for session %s, but Nova "
                "Sonic has no native STT-only mode — the model response "
                "is still generated and still billed (native_stt_only="
                "False; spec §8 resolved decision).",
                session_id,
            )
        # Code-review fix (FEAT-315): Nova Sonic / Nova 2 Sonic have NO
        # cross-region inference profiles (spec §6 "Verified AWS Facts") —
        # unlike the text/Converse path, the voice model ID must NEVER be
        # prefixed, even though the composed client (NovaClient) defaults
        # region_prefix="us" for the unrelated Nova 2 Lite/Premier text
        # models. region_prefix=None here bypasses self._region_prefix
        # entirely (mirrors NovaGeneration._translate_in_region_model).
        resolved_model = translate_bedrock_model(self.model or self.default_model, region_prefix=None)
        # FEAT-418 (TASK-2169/2170): explicit kwarg > options.voice >
        # constructor default (_resolve_voice(None) falls back to
        # self.voice_id). Validated against NOVA_VOICE_CATALOG with a
        # warned fallback — previously passed straight to Bedrock
        # unvalidated, so a Gemini voice like "Puck" (bots/voice.py:198)
        # produced an opaque provider error instead of a graceful fallback.
        requested_voice = (
            kwargs["voice_id"] if "voice_id" in kwargs else (options.voice if options is not None else None)
        )
        resolved_voice_id = self._resolve_voice(requested_voice)
        # FEAT-416 (TASK-2148): gate concurrent tool execution on the
        # VoiceConfig-derived flag (VoiceBot wires this in TASK-2151).
        # Default False preserves current sequential behavior exactly.
        # FEAT-418 (TASK-2170): explicit kwarg > options.parallel_tool_execution > False.
        parallel_tool_execution = kwargs.get(
            "parallel_tool_execution",
            options.parallel_tool_execution if options is not None else False,
        )
        # FEAT-536 TASK-2939: optional trusted PermissionContext from a
        # Python caller's **kwargs (spec §2 "Trusted execution context") —
        # NEVER derived from provider/model arguments. Threaded through to
        # every _flush_pending_tools() call below and on into
        # _execute_tool_full()'s ToolManager.execute_tool(..., permission_
        # context=...) call, same as VoiceBot/_execute_tool's existing
        # self._permission_context convention.
        permission_context: Optional["PermissionContext"] = kwargs.get(
            "permission_context", getattr(self, "_permission_context", None)
        )
        prompt_name = str(uuid.uuid4())
        content_name = str(uuid.uuid4())

        turn_metadata = VoiceTurnMetadata(turn_id=turn_id)
        usage = LiveCompletionUsage()
        accumulated_text = ""
        tool_calls_list: List[LiveToolCall] = []
        turn_state = _TurnState()

        self.logger.info(
            "Starting Nova Sonic voice session %s, turn %s (model=%s)",
            session_id,
            turn_id,
            resolved_model,
        )

        connection_start = time.monotonic()
        stream = await self._open_stream(resolved_model)

        # FEAT-536 TASK-2940: one stream-local write lock shared by the
        # setup sequence below, the audio sender, and the tool coordinator
        # — "serialize outbound SDK writes with a stream-local mechanism"
        # (spec §2). Never held across tool execution or a provider-event
        # wait, and never acquired recursively (see
        # :meth:`_send_event_locked`). Created here — NOT on ``self`` —
        # because ``NovaAudio`` is a shared mixin that may serve concurrent
        # sessions (same rationale as ``_TurnState``).
        write_lock = asyncio.Lock()

        # FEAT-416 (TASK-2147): thread VoiceConfig inference parameters
        # through to the Nova Sonic sessionStart event instead of hardcoding
        # them. VoiceBot wires these from VoiceConfig (TASK-2151).
        # FEAT-418 (TASK-2170): explicit kwarg > options field > hardcoded
        # default. max_tokens default changed 1024 -> 4096 (the shared
        # VoiceConfig default, spec §8 resolved decision); 8192 is
        # accepted as an explicit override.
        temperature = kwargs.get("temperature", options.temperature if options is not None else 0.7)
        max_tokens = kwargs.get("max_tokens", options.max_tokens if options is not None else 4096)
        top_p = kwargs.get("top_p", options.top_p if options is not None else 0.9)

        await self._send_event_locked(
            write_lock,
            stream,
            {
                "event": {
                    "sessionStart": {
                        "inferenceConfiguration": {
                            "maxTokens": max_tokens,
                            "topP": top_p,
                            "temperature": temperature,
                        }
                    }
                }
            },
        )
        await self._send_event_locked(write_lock, stream, self._build_prompt_start(prompt_name, resolved_voice_id))
        if system_prompt:
            # FEAT-408 Module 2 (gap 10): the AWS sample marks SYSTEM
            # content as interactive=False — it's context for the model,
            # not user-interactive content that triggers generation.
            await self._send_event_locked(
                write_lock,
                stream,
                {
                    "event": {
                        "contentStart": {
                            "promptName": prompt_name,
                            "contentName": f"{content_name}-sys",
                            "type": "TEXT",
                            "role": "SYSTEM",
                            "interactive": False,
                            "textInputConfiguration": {"mediaType": "text/plain"},
                        }
                    }
                },
            )
            await self._send_event_locked(
                write_lock,
                stream,
                {
                    "event": {
                        "textInput": {
                            "promptName": prompt_name,
                            "contentName": f"{content_name}-sys",
                            "content": system_prompt,
                        }
                    }
                },
            )
            await self._send_event_locked(
                write_lock,
                stream,
                {
                    "event": {
                        "contentEnd": {
                            "promptName": prompt_name,
                            "contentName": f"{content_name}-sys",
                        }
                    }
                },
            )

        # FEAT-408 Module 2 (gap 10): the AWS sample marks the user's
        # AUDIO contentStart as interactive=True (tells Nova this content
        # triggers model generation — required when tools are declared;
        # without it Nova waits indefinitely for "interactive content")
        # and includes audioType:"SPEECH" in the input configuration.
        await self._send_event_locked(
            write_lock,
            stream,
            {
                "event": {
                    "contentStart": {
                        "promptName": prompt_name,
                        "contentName": content_name,
                        "type": "AUDIO",
                        "role": "USER",
                        "interactive": True,
                        "audioInputConfiguration": {
                            "mediaType": "audio/lpcm",
                            "sampleRateHertz": self.INPUT_SAMPLE_RATE_HZ,
                            "sampleSizeBits": 16,
                            "channelCount": 1,
                            "encoding": "base64",
                            "audioType": "SPEECH",
                        },
                    }
                }
            },
        )

        sender_task = asyncio.create_task(
            self._audio_sender(stream, audio_iterator, prompt_name, content_name, write_lock)
        )

        # FEAT-536 TASK-2940: tool-coordinator state — local to this
        # stream_voice() call, never on ``self`` (shared-mixin rationale
        # above). Replaces the "queue and flush on next non-tool event"
        # model (FEAT-416 TASK-2148): a call is admitted (execution starts)
        # the instant its contentEnd(TOOL) is parsed, as its own
        # ``asyncio.Task`` — the coordinator loop below then races the next
        # provider event against every in-flight tool task so it "wakes"
        # on whichever completes first (spec §2: "the coordinator consumes
        # both provider events and completed tool jobs; it must wake when
        # a tool finishes even if no new provider event arrives").
        admitted_ids: set[str] = set()  # every ID ever admitted — dedup guard, IDs scoped to this stream
        running_tasks: Dict[str, "asyncio.Task[LiveVoiceResponse]"] = {}  # tool_use_id -> in-flight task
        queued_tools: List[tuple] = []  # admitted but waiting for a concurrency slot: (LiveToolCall, raw_input)
        max_concurrent_tools = self._MAX_PARALLEL_TOOLS if parallel_tool_execution else 1
        # FEAT-536 TASK-2941: completion-ORDER queue (spec §2: "result
        # delivery follows completion order with stable IDs"). Do NOT rely
        # on asyncio.wait(running_tasks.values())'s returned `done` SET for
        # ordering — when two tasks finish within the same event-loop tick
        # (a real, observed race, not merely theoretical), sets have no
        # defined iteration order, so completion order can silently be
        # lost. Each task instead pushes its own id here the instant it
        # finishes (in its `finally`, via `_start_queued_tools`'s
        # wrapper) — `asyncio.Queue.get()` is strict FIFO, so draining it
        # always reflects TRUE completion order regardless of batching.
        # A pure ORDERING side-channel — NOT raced against in
        # asyncio.wait() (that would create a second concurrent consumer
        # of the same Queue racing the coordinator's own asyncio.wait()
        # calls below, which — verified while implementing this — can
        # steal an item out from under whichever call site is genuinely
        # awaiting it right now, since asyncio.Queue wakes exactly one
        # waiter per put() and does not know which caller "should" get
        # it). The coordinator always waits on the actual
        # `running_tasks.values()` Tasks (a single call site at a time —
        # the main loop and `_drain_admitted_tools` never run
        # concurrently, both being synchronous phases of the same
        # coroutine), then consults this queue only to reconstruct TRUE
        # completion order among tasks it ALREADY knows are done.
        completed_ids_queue: "asyncio.Queue[str]" = asyncio.Queue()
        # FEAT-536 TASK-2941 (spec §2 "Barge-in must be relayed promptly
        # while tools are running ... mark their originating generation
        # stale; suppress LATE VISUAL DATA from a stale generation, but
        # return the tool result to the provider and keep an auditable
        # tool-call event"). Incremented on every barge-in (see the
        # textOutput interruption branch below); `call_generation` records
        # the generation each call was ADMITTED under, so staleness is
        # judged at harvest/drain time by comparing against whatever the
        # CURRENT generation is then — not by cancelling the call itself.
        current_generation = 0
        call_generation: Dict[str, int] = {}

        def _mark_stale_if_interrupted(response: LiveVoiceResponse) -> LiveVoiceResponse:
            """Strip a stale-generation delta's visual payload (barge-in
            happened after admission, before this call settled) while
            preserving the correlated tool-call event/result (auditable)."""
            call_ids = [tc.id for tc in response.tool_calls]
            if any(call_generation.get(cid, current_generation) != current_generation for cid in call_ids):
                if "display_data" in response.metadata:
                    del response.metadata["display_data"]
                response.metadata["stale_generation"] = True
            return response

        async def _run_and_report(
            pending: LiveToolCall, raw_input: Optional[str], deadline_at: float
        ) -> LiveVoiceResponse:
            """Run one admitted call and push its id onto
            ``completed_ids_queue`` the instant it finishes — the sole
            source of truth for completion order (see the queue's own
            comment above)."""
            try:
                result = await self._execute_and_deliver_tool(
                    pending,
                    raw_input,
                    stream=stream,
                    prompt_name=prompt_name,
                    write_lock=write_lock,
                    session_id=session_id,
                    turn_id=turn_id,
                    user_id=user_id,
                    permission_context=permission_context,
                    deadline_at=deadline_at,
                )
                return result
            finally:
                completed_ids_queue.put_nowait(pending.id)

        def _start_queued_tools() -> None:
            """Promote queued calls into running tasks up to the
            concurrency cap. Same-instance serialization beyond this
            numeric cap is the manager's own per-instance lock (TASK-2938)
            — this coordinator does not track tool-instance identity."""
            while queued_tools and len(running_tasks) < max_concurrent_tools:
                next_pending, next_raw_input, next_deadline_at = queued_tools.pop(0)
                running_tasks[next_pending.id] = asyncio.create_task(
                    _run_and_report(next_pending, next_raw_input, next_deadline_at)
                )

        async def _admit_tool(pending: LiveToolCall, raw_input: Optional[str]) -> Optional[LiveVoiceResponse]:
            """Admit a fully-parsed contentEnd(TOOL) call immediately.

            Returns a controlled overload-error :class:`LiveVoiceResponse`
            to yield when the 32-unfinished bound is exceeded; ``None`` on
            success (including a silently-ignored duplicate — spec §2: "A
            duplicate completion for an already admitted ID must not
            re-execute it").
            """
            if pending.id in admitted_ids:
                self.logger.warning(
                    "Nova Sonic session %s: duplicate contentEnd(TOOL) for "
                    "already-admitted id=%s — ignored, not re-executed.",
                    session_id,
                    pending.id,
                )
                return None
            if len(running_tasks) + len(queued_tools) >= self._MAX_UNFINISHED_TOOLS:
                pending.error = (
                    f"Rejected: {self._MAX_UNFINISHED_TOOLS} in-flight tool calls already admitted this stream."
                )
                self.logger.warning(
                    "Nova Sonic session %s: tool admission bound (%d) exceeded — rejecting id=%s.",
                    session_id,
                    self._MAX_UNFINISHED_TOOLS,
                    pending.id,
                )
                # Code-review finding: Nova is left waiting on a toolResult
                # for this toolUseId forever unless we send one — a local
                # Python delta alone is not a "correlated error result"
                # (spec §2: "Reject excess work with a correlated error
                # result"). Send the same 3-frame contentStart/toolResult/
                # contentEnd sequence _execute_and_deliver_tool() uses,
                # under the same write_lock, so Nova's own turn can
                # proceed instead of stalling on this call.
                overload_result = {"error": pending.error, "status": "overloaded"}
                pending.result = overload_result
                async with write_lock:
                    await self._send_tool_result(stream, prompt_name, pending.id, overload_result)
                return LiveVoiceResponse(
                    text="",
                    tool_calls=[pending],
                    is_complete=False,
                    session_id=session_id,
                    turn_id=turn_id,
                    user_id=user_id,
                    metadata={"tool_status": "overloaded"},
                )
            admitted_ids.add(pending.id)
            call_generation[pending.id] = current_generation
            # Arrival order preserved here — REGARDLESS of completion
            # order below (spec §2: "Arrival order remains available for
            # the final snapshot").
            tool_calls_list.append(pending)
            # Deadline measured from ADMISSION (this instant), including
            # queue wait — spec §2: "a 300 s per-call deadline from
            # admission ... a queued call may expire before starting".
            deadline_at = time.monotonic() + self._TOOL_CALL_DEADLINE_SECONDS
            queued_tools.append((pending, raw_input, deadline_at))
            _start_queued_tools()
            return None

        async def _harvest_finished_tools(done_tasks: "set[asyncio.Task]") -> List[LiveVoiceResponse]:
            """Collect finished tool tasks: update usage, free their
            running-slot, promote the next queued call, suppress stale-
            generation visuals, and return their responses IN TRUE
            COMPLETION ORDER (spec §2: "result delivery follows
            completion order with stable IDs").

            ``done_tasks`` comes from ``asyncio.wait()``, whose returned
            ``done`` set has NO defined iteration order — when two tasks
            finish within the same event-loop tick (a real, observed
            race, not merely theoretical) that order would otherwise be
            lost. Reconstructed here from ``completed_ids_queue``: drain
            every id currently queued, keep the ones that belong to
            ``done_tasks`` (in the FIFO order they were pushed — true
            completion order), and put back any others (they belong to a
            DIFFERENT, not-yet-observed completion — this is the single
            consumer of the queue; see its own comment above).
            """
            if not done_tasks:
                return []
            done_ids = {tid for tid, t in running_tasks.items() if t in done_tasks}
            ordered_ids: List[str] = []
            not_ours: List[str] = []
            while not completed_ids_queue.empty():
                qid = completed_ids_queue.get_nowait()
                (ordered_ids if qid in done_ids else not_ours).append(qid)
            for qid in not_ours:
                completed_ids_queue.put_nowait(qid)

            responses: List[LiveVoiceResponse] = []
            for tool_use_id in ordered_ids:
                task = running_tasks.pop(tool_use_id)
                response = await task  # already done — retrieves result/re-raises
                usage.tool_calls_executed += 1
                for tc in response.tool_calls:
                    usage.tool_execution_time_ms += tc.execution_time_ms
                responses.append(_mark_stale_if_interrupted(response))
            _start_queued_tools()
            return responses

        async def _drain_admitted_tools() -> AsyncIterator[LiveVoiceResponse]:
            """Settle every admitted-but-unfinished tool call before a
            final snapshot or teardown (spec §2: "On normal provider
            completion, settle admitted work and result sends before the
            final snapshot").

            Respects the SAME concurrency cap as normal admission —
            draining does not blow the cap open (a provider that sends
            ``completionEnd`` while several calls are still queued must
            not suddenly cause them all to run at once, silently
            abandoning the default's "one at a time" ordering guarantee).
            It simply keeps awaiting completions and promoting the next
            queued call — via :meth:`_harvest_finished_tools`'s own
            ``_start_queued_tools()`` call — until both ``running_tasks``
            and ``queued_tools`` are empty.
            """
            _start_queued_tools()  # fill any currently-unfilled slot
            while running_tasks or queued_tools:
                if not running_tasks:
                    # Nothing running but calls remain queued — cannot
                    # happen with cap >= 1, but never spin forever.
                    break
                done, _pending_set = await asyncio.wait(running_tasks.values(), return_when=asyncio.FIRST_COMPLETED)
                for response in await _harvest_finished_tools(done):
                    yield response

        async def _cancel_admitted_tools_for_reconnect() -> None:
            """Cancel outstanding admitted work at RECONNECT shutdown —
            distinct from :func:`_drain_admitted_tools`'s SETTLE/await
            behavior, which is spec-scoped to normal provider completion
            only.

            Spec §2: "On reconnect shutdown, cancel outstanding jobs,
            report interrupted/incomplete work locally, send correlated
            cancellation results only if the old stream remains writable
            within cleanup, and never replay them on the new stream."
            (Code-review finding: the coordinator previously called
            ``_drain_admitted_tools()`` here too, which AWAITS full
            completion — up to each call's individual 300s deadline —
            instead of cancelling, risking a hard server-side disconnect
            mid-tool-execution well past the proactive 8-minute limit
            this check exists to avoid.)

            Mirrors the EOF/disconnect cancellation path below (queued
            calls dropped, running tasks cancelled and awaited under the
            same bounded cleanup timeout, `tool_calls_list` marked
            in-place so the final snapshot reports the interruption
            locally) — but additionally attempts a best-effort correlated
            cancellation `toolResult` for each cancelled call, since
            (unlike EOF) the old stream is still nominally writable here:
            this runs BEFORE `_end_session()`/`_close_stream()`. Never
            sent on the NEW stream after reconnect.
            """
            incomplete_ids = {*running_tasks.keys(), *(p.id for p, _raw, _dl in queued_tools)}
            for tc in tool_calls_list:
                if tc.id in incomplete_ids and tc.error is None and tc.result is None:
                    tc.error = "Interrupted: connection-limit reconnect before this call completed."
            cancelled_ids = list(running_tasks.keys())
            queued_tools.clear()
            for leftover_task in running_tasks.values():
                leftover_task.cancel()
            if running_tasks:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        asyncio.gather(*running_tasks.values(), return_exceptions=True),
                        timeout=self._CLEANUP_TIMEOUT_SECONDS,
                    )
                running_tasks.clear()
            for tool_use_id in cancelled_ids:
                try:
                    async with write_lock:
                        await self._send_tool_result(
                            stream,
                            prompt_name,
                            tool_use_id,
                            {"error": "cancelled: connection reconnecting", "status": "cancelled"},
                        )
                except Exception as send_exc:  # noqa: BLE001
                    self.logger.warning(
                        "Nova Sonic session %s: failed to send cancellation result for %s "
                        "during reconnect (old stream may already be unwritable): %s",
                        session_id,
                        tool_use_id,
                        send_exc,
                    )

        # Reads exactly one event per call — wrapped in its own Task so the
        # coordinator loop below can race it against in-flight tool tasks
        # via asyncio.wait(FIRST_COMPLETED). A private sentinel (not None,
        # which is a valid audio-sender value elsewhere) marks a clean
        # StopAsyncIteration so the loop can tell "stream ended" apart from
        # "next event is falsy".
        _STREAM_END = object()
        events_iter = self._iter_events(stream)

        async def _read_next_event():
            try:
                return await events_iter.__anext__()
            except StopAsyncIteration:
                return _STREAM_END

        next_event_task: "asyncio.Task" = asyncio.create_task(_read_next_event())
        exited_via_explicit_break = False  # True for reconnect/completionEnd breaks; False for _STREAM_END

        try:
            while True:
                done, _pending_set = await asyncio.wait(
                    {next_event_task, *running_tasks.values()}, return_when=asyncio.FIRST_COMPLETED
                )

                # Deliver finished tool results FIRST and promptly, IN
                # TRUE COMPLETION ORDER — the whole point of this
                # coordinator (spec §2: "the coordinator consumes both
                # provider events and completed tool jobs"). Never blocks
                # on the next provider event.
                tool_tasks_done = done - {next_event_task}
                for tool_response in await _harvest_finished_tools(tool_tasks_done):
                    yield tool_response

                if next_event_task not in done:
                    # Only tool task(s) completed this round — go straight
                    # back to waiting; do not fabricate a provider event.
                    continue

                event = next_event_task.result()
                if event is _STREAM_END:
                    break
                # Schedule reading the NEXT provider event immediately —
                # before any per-event handling below, so a slow tool
                # handler never delays the read.
                next_event_task = asyncio.create_task(_read_next_event())
                if time.monotonic() - connection_start >= self._CONNECTION_LIMIT_SECONDS:
                    # FEAT-536 TASK-2940/2941 (hardened post-review): CANCEL
                    # every admitted-but-unfinished tool call for reconnect
                    # shutdown — never settle/await it, per spec §2's
                    # explicit distinction between normal completion
                    # (settle) and reconnect shutdown (cancel). Pending
                    # work must not keep the old stream open past the
                    # proactive 8-minute limit waiting on a call's own
                    # up-to-300s deadline.
                    #
                    # NOTE (spec §2 "Observe the existing reconnect
                    # deadline independently of event arrival"): this check
                    # still runs once per received provider event, not on
                    # an independent wall-clock timer. Nova Sonic's own
                    # server-side idle timeout fires after 55s of silence
                    # (see the idle-timeout ValidationException handling
                    # below) — well inside the ~7m45s connection limit —
                    # so a fully event-less gap long enough for this
                    # distinction to matter cannot occur in practice; an
                    # independent `asyncio.sleep()`-based timer was
                    # prototyped but reverted because it cannot be
                    # deterministically fast-forwarded by the existing
                    # `time.monotonic`-patching test strategy
                    # (test_nova.py::test_stream_voice_8_minute_reconnect,
                    # outside this task's file scope) without real-time
                    # waits — not a case this task's own scope should
                    # force a change onto.
                    await _cancel_admitted_tools_for_reconnect()

                    self.logger.info(
                        "Nova Sonic session %s approaching 8-minute connection " "limit — signalling reconnect.",
                        session_id,
                    )
                    yield LiveVoiceResponse(
                        text=accumulated_text,
                        is_complete=True,
                        tool_calls=tool_calls_list,
                        metadata={"reconnect_required": True},
                        usage=usage,
                        turn_metadata=turn_metadata,
                        session_id=session_id,
                        turn_id=turn_id,
                        user_id=user_id,
                    )
                    exited_via_explicit_break = True
                    break

                # Log every received event type for diagnostics.
                event_keys = [k for k in event if k != "promptName"]
                self.logger.debug(
                    "Nova Sonic event: %s",
                    ", ".join(event_keys) if event_keys else list(event.keys()),
                )

                content_start = event.get("contentStart")
                if content_start:
                    turn_state.role = content_start.get("role")
                    turn_state.generation_stage = _parse_generation_stage(content_start.get("additionalModelFields"))
                    continue

                text_output = event.get("textOutput")
                if text_output:
                    chunk_text = text_output.get("content", "")

                    # Barge-in / interruption — Nova signals this as an
                    # {"interrupted": true} payload inside textOutput content,
                    # not via a top-level "interruption" key or stopReason
                    # (neither appears in any AWS Nova Sonic sample).
                    if _is_interruption_payload(chunk_text):
                        turn_metadata.was_interrupted = True
                        # FEAT-536 TASK-2941 (spec §2): mark every call
                        # already admitted (running or queued) as belonging
                        # to a stale generation — their eventual visual
                        # payload will be suppressed at harvest/drain time
                        # (_mark_stale_if_interrupted), while their tool
                        # result/event still reaches Nova/the caller
                        # (auditable, never re-executed or cancelled here).
                        current_generation += 1
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

                    role = turn_state.role
                    stage = turn_state.generation_stage
                    # Missing stage must EMIT, not suppress (spec §7) — only an
                    # explicitly non-SPECULATIVE stage suppresses assistant text.
                    suppressed = role == "ASSISTANT" and stage is not None and stage != "SPECULATIVE"
                    if not suppressed:
                        if role == "ASSISTANT":
                            accumulated_text += chunk_text
                        yield LiveVoiceResponse(
                            text=chunk_text,
                            # FEAT-418 (TASK-2170): canonical lowercase
                            # role at this single emission point only —
                            # `role`/`turn_state.role` above keep Nova's
                            # raw "USER"/"ASSISTANT" for the protocol-level
                            # comparisons already in this function.
                            role=role.lower() if role else None,
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
                    audio_bytes = base64.b64decode(raw_content) if isinstance(raw_content, str) else raw_content
                    yield LiveVoiceResponse(
                        text="",
                        audio_data=audio_bytes,
                        audio_format=f"audio/pcm;rate={self.OUTPUT_SAMPLE_RATE_HZ}",
                        is_complete=False,
                        session_id=session_id,
                        turn_id=turn_id,
                        user_id=user_id,
                    )

                usage_event = event.get("usageEvent")
                if usage_event:
                    # Nova may nest the counts under a "details"/"totals"
                    # sub-object; flatten one level so both shapes work.
                    flat = {**usage_event}
                    for nested_key in ("details", "totals", "usage"):
                        nested = usage_event.get(nested_key)
                        if isinstance(nested, dict):
                            flat.update(nested)
                    if (value := _first_int(flat, _USAGE_INPUT_KEYS)) is not None:
                        usage.prompt_tokens = value
                    if (value := _first_int(flat, _USAGE_OUTPUT_KEYS)) is not None:
                        usage.completion_tokens = value
                    total = _first_int(flat, _USAGE_TOTAL_KEYS)
                    usage.total_tokens = total if total is not None else usage.prompt_tokens + usage.completion_tokens
                    # Keep the raw frame so the shape can be inspected from a
                    # real session (spec §8 Q1).
                    usage.extra["usage_event"] = usage_event
                    self.logger.debug("Nova Sonic usageEvent: %s", usage_event)
                    continue

                tool_use = event.get("toolUse")
                if tool_use:
                    # Gap 2: Nova executes the tool call on contentEnd(TOOL),
                    # not on toolUse — stash it, do NOT execute here.
                    tool_use_id = tool_use.get("toolUseId", str(uuid.uuid4()))
                    turn_state.pending_tool = LiveToolCall(
                        id=tool_use_id,
                        name=tool_use.get("toolName"),
                        arguments={},
                    )
                    turn_state.pending_tool_raw_input = tool_use.get("content")
                    continue

                content_end = event.get("contentEnd")
                if content_end and content_end.get("type") == "TOOL":
                    pending = turn_state.pending_tool
                    if pending is None:
                        # No stashed call for this contentEnd(TOOL) — ignore
                        # rather than raise (spec §2: "Reject malformed or
                        # uncorrelatable input with a controlled protocol/
                        # tool error" — there is nothing to correlate this
                        # contentEnd to, so it is dropped, not executed).
                        continue

                    # FEAT-536 TASK-2940: admit — and start executing —
                    # immediately, instead of queueing for a later "next
                    # non-tool event" flush (FEAT-416 TASK-2148's old
                    # behavior, which is exactly the progress risk this
                    # task fixes: a provider waiting for the tool result
                    # might never send that next event).
                    raw_input = turn_state.pending_tool_raw_input
                    turn_state.pending_tool = None
                    turn_state.pending_tool_raw_input = None
                    if (overload_response := await _admit_tool(pending, raw_input)) is not None:
                        yield overload_response
                    continue

                if "completionEnd" in event or event.get("stopReason") == "END_TURN":
                    # FEAT-536 TASK-2940 (spec §2): settle every admitted-
                    # but-unfinished tool call before the final snapshot —
                    # `tool_calls_list` already has every admitted call in
                    # ARRIVAL order (populated by `_admit_tool`); draining
                    # here only fills in `result`/`error` for whichever
                    # were still running, it does not reorder the list.
                    async for tool_response in _drain_admitted_tools():
                        yield tool_response
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
                    exited_via_explicit_break = True
                    break

            if not exited_via_explicit_break:
                # Stream ended without a completionEnd event (e.g. server
                # closed the connection).  Yield a completion so callers
                # are never left hanging.
                self.logger.warning(
                    "Nova Sonic session %s: stream ended without completionEnd",
                    session_id,
                )
                # FEAT-536 TASK-2941 (spec §2 "On ... EOF ..., stop
                # admission and cancel owned jobs rather than sending to a
                # closed stream"): unlike the graceful completionEnd/
                # reconnect paths (which SETTLE — await — admitted work
                # because the provider is still reachable), an
                # unexpected EOF means the stream is gone; there is
                # nowhere left to send a result, so admitted-but-
                # unfinished work is CANCELLED here rather than awaited
                # (which could otherwise hang this turn indefinitely on a
                # stalled tool with no deadline pressure yet). Queued
                # (never-started) calls are simply dropped — nothing to
                # cancel. Bounded by the SAME cleanup timeout as the
                # method's own `finally` (best-effort; a non-cooperative
                # task cannot be forced to stop).
                incomplete_ids = {*running_tasks.keys(), *(p.id for p, _raw, _dl in queued_tools)}
                for tc in tool_calls_list:
                    if tc.id in incomplete_ids and tc.error is None and tc.result is None:
                        tc.error = "Interrupted: stream ended (EOF) before this call completed."
                queued_tools.clear()
                for leftover_task in running_tasks.values():
                    leftover_task.cancel()
                if running_tasks:
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(
                            asyncio.gather(*running_tasks.values(), return_exceptions=True),
                            timeout=self._CLEANUP_TIMEOUT_SECONDS,
                        )
                    running_tasks.clear()
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

            # Nova Sonic sends a ValidationException after 55 s of no audio
            # or interactive content — this is normal idle-session expiry,
            # not a bug. Log at INFO (no traceback) instead of ERROR.
            is_idle_timeout = "Timed out waiting for audio" in str(exc) or "gaps between audio bytes" in str(exc)
            if is_idle_timeout:
                self.logger.info(
                    "Nova Sonic session %s idle timeout (55 s no audio)",
                    session_id,
                )
            else:
                self.logger.exception("Nova Sonic session %s error: %s", session_id, error_message)
            yield LiveVoiceResponse(
                text="",
                is_complete=True,
                metadata={"error": error_message},
                session_id=session_id,
                turn_id=turn_id,
                user_id=user_id,
            )
        finally:
            # FEAT-536 TASK-2940/2941: cancellation-safe coordinator
            # cleanup — release ownership of the event-reader task and any
            # tool tasks still in flight ("never leak a task, never write
            # after the transport closes"). Runs BEFORE `_end_session()`'s
            # shutdown frames so no coordinator write can race them.
            #
            # Bounded to `_CLEANUP_TIMEOUT_SECONDS` (spec §2: "Cleanup may
            # wait at most 5 s for normal cooperative task shutdown;
            # preserve cancellation propagation and close the transport in
            # finally"). A non-cooperative tool or an already-running
            # thread (opt-in complete-result mode offloads synchronous
            # ToolDefinition functions via `asyncio.to_thread`, TASK-2937)
            # cannot be forcibly stopped — `asyncio.wait_for` timing out
            # here just means cleanup stops WAITING for it; the task
            # itself is still cancelled/left running to completion on its
            # own, and the transport still closes below regardless. This
            # is a documented limitation, not a claim of rollback/success.
            next_event_task.cancel()
            for leftover_task in running_tasks.values():
                leftover_task.cancel()
            sender_task.cancel()
            cleanup_tasks = [next_event_task, sender_task, *running_tasks.values()]
            try:
                await asyncio.wait_for(
                    asyncio.gather(*cleanup_tasks, return_exceptions=True),
                    timeout=self._CLEANUP_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                self.logger.warning(
                    "Nova Sonic session %s: cooperative cleanup did not finish within %.0fs — "
                    "closing the transport anyway; a non-cooperative task cannot be forced to stop.",
                    session_id,
                    self._CLEANUP_TIMEOUT_SECONDS,
                )
            # Tell Nova the prompt/session are over before the transport
            # closes — best-effort, must never mask the turn's own error.
            # content_name closes the user-audio content block that was
            # intentionally left open during the turn (VAD-driven
            # end-of-speech, matching the AWS reference sample).
            await self._end_session(stream, prompt_name, content_name)
            # One stream_voice() call == one turn, so the stream opened above
            # must be released here or every turn leaks its connection.
            await self._close_stream(stream)

    async def _audio_sender(
        self,
        stream: Any,
        audio_iterator: AsyncIterator[bytes],
        prompt_name: str,
        content_name: str,
        write_lock: Optional[asyncio.Lock] = None,
    ) -> None:
        """Forward PCM audio chunks from *audio_iterator* as ``audioInput``
        event frames.  A ``None`` sentinel marks end-of-turn and exits the
        sender — it does **not** send ``contentEnd``.

        Why no ``contentEnd`` here:  the AWS reference samples
        (``nova_sonic_simple.py``) keep the user-audio content block open
        for the full session and rely on Nova's server-side VAD to detect
        end-of-speech from the trailing silence injected by
        ``VoiceSession.end_turn()``.  Sending ``contentEnd`` mid-session
        takes Nova out of "listening" mode; without a follow-up
        ``promptEnd`` the model never starts generating — a deadlock that
        surfaces as a 55-second idle timeout.

        ``contentEnd`` → ``promptEnd`` → ``sessionEnd`` are sent as a
        single shutdown sequence by :meth:`_end_session`, called from
        :meth:`stream_voice`'s ``finally`` block after the model has
        finished responding (or the turn timed out / errored).

        Args:
            write_lock: The stream-local write lock (FEAT-536 TASK-2940 —
                spec §2 "Serialize outbound SDK writes with a stream-local
                mechanism"), shared with the tool coordinator so
                ``audioInput`` frames never interleave mid-frame with a
                tool-result send. Optional/defaults to a fresh, private
                lock when called standalone (e.g. directly from a test) —
                :meth:`stream_voice` always passes its own shared lock.
        """
        write_lock = write_lock if write_lock is not None else asyncio.Lock()
        chunks_sent = 0
        try:
            async for chunk in audio_iterator:
                if chunk is None:
                    self.logger.info(
                        "Audio sender: end-of-turn after %d chunks " "(no contentEnd — VAD handles end-of-speech)",
                        chunks_sent,
                    )
                    break
                # Code-review fix: audioInputConfiguration declares
                # "encoding": "base64" (see stream_voice()'s contentStart
                # event above), so raw PCM bytes must be base64-text-encoded
                # before being embedded in the JSON event frame — sending
                # raw bytes verbatim would both violate the declared wire
                # format and fail JSON serialization outright.
                await self._send_event_locked(
                    write_lock,
                    stream,
                    {
                        "event": {
                            "audioInput": {
                                "promptName": prompt_name,
                                "contentName": content_name,
                                "content": base64.b64encode(chunk).decode("ascii"),
                            }
                        }
                    },
                )
                chunks_sent += 1
                if chunks_sent % 50 == 0:
                    self.logger.debug("Audio sender: %d chunks sent so far", chunks_sent)
        except asyncio.CancelledError:
            self.logger.debug("Audio sender: cancelled (chunks_sent=%d)", chunks_sent)
            raise
        except Exception as exc:
            self.logger.error(
                "Nova Sonic audio sender error after %d chunks: %s",
                chunks_sent,
                exc,
            )
