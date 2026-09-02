"""Native AWS Bedrock Converse API client for AI-Parrot (FEAT-302, FEAT-315).

Implements :class:`BedrockConverseBase`, the model-family-agnostic Converse
API engine (session/client management, message/tool conversion, the
tool-use loop, streaming, guardrails, structured output, and credential
resolution), and :class:`BedrockConverseClient`, a thin
:class:`BedrockConverseBase` subclass that keeps the historical Claude/
Llama/Mistral-oriented public surface byte-compatible.

``BedrockConverseBase`` talks to the AWS Bedrock Runtime *Converse* API
directly via ``aioboto3`` — as opposed to
:class:`~parrot.clients.claude.AnthropicClient`'s ``backend="bedrock"``,
which routes through the Anthropic SDK's ``AsyncAnthropicBedrock`` transport
(FEAT-232) and is therefore limited to Claude models.

This module implements Spec Module 4 ("BedrockConverseClient — Core"):
session/client management, the Converse API tool-use loop, streaming,
``resume()``, and a lightweight ``invoke()``. Module 5 ("Advanced
Features", TASK-1746) adds extended thinking, prompt caching, schema-based
structured output, guardrails (``apply_guardrail_text()``), and the
``_invoke_native()`` fallback for models without ARN-versioned IDs.
Factory registration is Module 6 (TASK-1747).

FEAT-315 (TASK-1806) extracted the engine into ``BedrockConverseBase`` so
that :class:`~parrot.clients.nova.NovaClient` can inherit it directly
instead of delegating to a second internal client object, and fixed the
``aws_id`` credential-resolution bug described below.

See ``sdd/specs/bedrock-client-llm.spec.md`` and
``sdd/specs/novaclient-amazon-aws.spec.md`` for the full design.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from .base import AbstractClient
from ..conf import (
    AWS_CREDENTIALS,
    AWS_REGION_NAME,
    BEDROCK_AWS_REGION,
    AWS_NOVA_API_KEY,
)
from ..exceptions import InvokeError
from ..models.basic import CompletionUsage, ToolCall
from ..models.bedrock_models import translate as translate_bedrock_model
from ..models.responses import AIMessage, AIMessageFactory, InvokeResult
from ..models.outputs import StructuredOutputConfig
from ..tools.manager import ToolFormat

# Model families that REJECT sampling parameters (2026 generation). Bedrock
# answers a request carrying ``temperature``/``topP``/``topK`` for one of these
# with ``ValidationException: The model returned the following errors:
# `temperature` is deprecated for this model``. Matched as substrings because
# the resolved id carries a region prefix and may carry a ``-vN:0`` suffix
# (e.g. ``us.anthropic.claude-opus-5``). Older families (Opus/Sonnet 4.6 and
# down, Amazon Nova, third-party vendors) still accept sampling params.
NO_SAMPLING_MODEL_FAMILIES: tuple[str, ...] = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
)


def rejects_sampling_params(model_id: str) -> bool:
    """Return True when *model_id* rejects sampling parameters.

    Args:
        model_id: A Bedrock model ID, already translated (it may carry a
            region prefix, a version suffix, or be a full ARN).

    Returns:
        ``True`` when ``temperature``/``topP``/``topK`` must be omitted from
        the request for this model.
    """
    return any(family in (model_id or "") for family in NO_SAMPLING_MODEL_FAMILIES)


def _requires_adaptive_thinking(model_id: str) -> bool:
    """Return True when *model_id* requires the ``"adaptive"`` thinking shape.

    FEAT-482 Module 3: the same 2026-generation model families that reject
    legacy sampling parameters (see :func:`rejects_sampling_params`) also
    reject the legacy extended-thinking shape —
    ``additionalModelRequestFields.thinking = {"type": "enabled",
    "budget_tokens": N}`` — returning ``ValidationException`` / HTTP 400.
    They require ``{"type": "adaptive"}`` instead (confirmed against AWS's
    Bedrock Converse API documentation for Claude adaptive thinking,
    2026-08-31). Amazon Nova and older Anthropic families are unaffected
    and keep the ``budget_tokens`` shape byte-identically.

    Args:
        model_id: A Bedrock model ID, already translated (it may carry a
            region prefix, a version suffix, or be a full ARN).

    Returns:
        ``True`` when the ``"adaptive"`` thinking shape must be used
        instead of ``budget_tokens`` for this model.
    """
    return rejects_sampling_params(model_id)


class _StaticBedrockTokenProvider:
    """Serves a fixed Bedrock API key as a botocore auth token.

    Registered as a session's ``token_provider`` component so
    ``signature_version="bearer"`` resolves to the operator's configured
    key instead of falling through to SigV4 credentials. Deliberately
    minimal — botocore only requires ``load_token()``, and aiobotocore
    awaits ``get_frozen_token()``, so the latter is a coroutine here
    (botocore's own providers are sync; aiobotocore wraps them).

    Args:
        token: The Bedrock API key (bearer token, ``"ABSK..."``).
    """

    def __init__(self, token: str) -> None:
        from botocore.tokens import FrozenAuthToken

        self._frozen = FrozenAuthToken(token)

    def load_token(self) -> _StaticBedrockTokenProvider:
        """Return self — this provider is its own (already-loaded) token."""
        return self

    async def get_frozen_token(self) -> Any:
        """Return the immutable token botocore's ``BearerAuth`` signs with."""
        return self._frozen


class BedrockConverseBase(AbstractClient):
    """Model-family-agnostic engine for AWS Bedrock's native Converse API.

    Carries everything that does NOT vary by model family: credential/
    region resolution, ``aioboto3`` session/client management, message and
    tool-schema conversion, the Converse tool-use loop, streaming,
    ``resume()``, ``invoke()``, guardrails, and structured output.

    Concrete subclasses (e.g. :class:`BedrockConverseClient`,
    :class:`~parrot.clients.nova.NovaClient`) set the family-specific class
    attributes (``client_type``, ``client_name``, ``_default_model``,
    ``_fallback_model``, ...) and inherit the rest verbatim — no
    delegation object, no reimplementation (spec ``novaclient-amazon-aws``
    §2/§3 Module 1).
    """

    def __init__(
        self,
        aws_id: Optional[str] = None,
        region: Optional[str] = None,
        profile: Optional[str] = None,
        region_prefix: Optional[str] = None,
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
        max_retries: int = 4,
        read_timeout: int = 120,
        aws_access_key: Optional[str] = None,
        aws_secret_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        aws_bearer_token: Optional[str] = None,
        **kwargs,
    ):
        """Initialise a Bedrock Converse API client.

        Args:
            aws_id: Optional ``AWS_CREDENTIALS`` profile name (spec
                ``novaclient-amazon-aws`` §1/§2.2). Resolution: kwarg →
                named profile in ``parrot.conf::AWS_CREDENTIALS`` (falls
                back to the ``'default'`` profile when the named profile is
                missing). No ``aws_id`` means no profile lookup at all — see
                ``aws_access_key``/``aws_bearer_token`` for what happens next.
            region: AWS region for the Bedrock Runtime endpoint. Resolution
                order: explicit kwarg → ``AWS_CREDENTIALS`` profile
                ``region_name`` → ``BEDROCK_AWS_REGION`` →
                ``AWS_REGION_NAME`` → ``"us-east-1"``.
            profile: Optional named AWS profile, passed to
                ``aioboto3.Session``.
            region_prefix: Cross-region inference-profile prefix (e.g.
                ``"us"``, ``"eu"``, ``"apac"``) applied by
                :func:`~parrot.models.bedrock_models.translate`.
            guardrail_id: Bedrock guardrail identifier. Stored for use by
                Module 5 (TASK-1746, Advanced Features); not yet applied to
                requests in this Core implementation.
            guardrail_version: Bedrock guardrail version. See
                ``guardrail_id``.
            max_retries: Max retry attempts for the underlying botocore
                client (adaptive retry mode).
            read_timeout: Socket read timeout (seconds) for the botocore
                client.
            aws_access_key: AWS access key ID. Resolution: kwarg → the
                ``aws_id`` profile's ``aws_key``/``aws_access_key_id``. No
                generic conf-wide fallback (removed — it silently picked up
                whatever AWS account was configured for unrelated services,
                e.g. S3, which may lack Bedrock permissions entirely).
            aws_secret_key: AWS secret access key. Same resolution order.
            aws_session_token: Optional STS session token. Same resolution
                order.
            aws_bearer_token: Bedrock API key (bearer token, ``"ABSK..."``
                prefix) — an alternative to the access/secret keypair.
                Resolution: kwarg → the ``aws_id`` profile's
                ``aws_bearer_token`` → ``AWS_NOVA_API_KEY`` (conf). Only
                consulted when no static access key resolves above (a
                caller providing both is assumed to want the access/secret
                keypair). When resolved, :meth:`get_client` exports it as
                ``AWS_BEARER_TOKEN_BEDROCK`` for botocore's own bearer-auth
                support (``botocore>=1.36``) to pick up — leave every
                resolution step ``None`` to instead rely on
                ``AWS_BEARER_TOKEN_BEDROCK`` already set in the process
                environment (the SDK's own default).
            **kwargs: Forwarded to
                :class:`~parrot.clients.base.AbstractClient`.
        """
        self._aws_id = aws_id
        # FEAT-315 (TASK-1806) fix: the previous implementation read
        # ``access_key``/``secret_key``/``session_token``/``region`` from
        # ``AWS_CREDENTIALS`` profiles — those keys are the BUG, not the
        # schema (real keys are ``aws_key``/``aws_secret``/``region_name``,
        # per ``interfaces/aws.py:52-64``) — and left the credential
        # attributes unbound entirely when the named profile was missing.
        # This canonical resolver always binds the four attributes, in the
        # priority order from spec §1 Goals: explicit kwargs → ``aws_id``
        # profile (fallback to 'default') → SDK chain (attributes may end
        # up ``None``, but are never unbound).
        #
        # Code-review fix (post-FEAT-315): the conf-wide ``AWS_ACCESS_KEY``/
        # ``AWS_SECRET_KEY``/``AWS_SESSION_TOKEN`` fallback was removed —
        # it made every no-``aws_id`` client silently authenticate as
        # whatever IAM identity happens to be configured for unrelated
        # services, which may (as observed) be denied Bedrock access
        # entirely. Static keys now require an explicit kwarg or a named
        # ``aws_id`` profile; failing both, we try a Bedrock API key
        # (bearer token) instead of a static keypair, and only fall through
        # to the plain SDK credential chain (env vars, shared credentials
        # file, SSO, ...) if that is unset too.
        credentials: Dict[str, Any] = {}
        if self._aws_id:
            credentials = AWS_CREDENTIALS.get(self._aws_id) or {}
            if not credentials:
                credentials = AWS_CREDENTIALS.get("default", {})
        self._aws_access_key = aws_access_key or credentials.get("aws_key") or credentials.get("aws_access_key_id")
        self._aws_secret_key = (
            aws_secret_key or credentials.get("aws_secret") or credentials.get("aws_secret_access_key")
        )
        self._aws_session_token = aws_session_token or credentials.get("aws_session_token")
        self._aws_bearer_token = None
        if not self._aws_access_key:
            self._aws_bearer_token = aws_bearer_token or credentials.get("aws_bearer_token") or AWS_NOVA_API_KEY
        self._region = region or credentials.get("region_name") or BEDROCK_AWS_REGION or AWS_REGION_NAME or "us-east-1"
        self._profile = profile
        self._region_prefix = region_prefix
        self._guardrail_id = guardrail_id
        self._guardrail_version = guardrail_version
        self._max_retries = max_retries
        self._read_timeout = read_timeout
        # Code-review fix (FEAT-302): AbstractClient.__init__ unconditionally
        # does ``self._fallback_model = kwargs.get('fallback_model', None)``,
        # which shadows this class's ``_fallback_model`` class attribute with
        # an instance attribute of ``None`` unless a caller explicitly passes
        # ``fallback_model=``. Without this, ``_should_use_fallback()`` (and
        # therefore the capacity-error retry path in ``ask()``) silently
        # never fires for a normally-constructed client. Pre-existing
        # base-class behavior (identically affects AnthropicClient) — worked
        # around here rather than in base.py to stay within this feature's
        # scope; callers can still override via an explicit ``fallback_model=``
        # kwarg, which ``setdefault`` will not clobber.
        kwargs.setdefault("fallback_model", self._fallback_model)
        super().__init__(**kwargs)

    # ------------------------------------------------------------------
    # Session & client management
    # ------------------------------------------------------------------

    async def get_client(self) -> Any:
        """Create and return an aioboto3 Bedrock Runtime client.

        ``aioboto3`` is imported lazily here so that importing this module
        does not require the optional ``bedrock-native`` extra (TASK-1747)
        to be installed until the client is actually used. The returned
        client is cached per event loop by
        :meth:`~parrot.clients.base.AbstractClient._ensure_client`.

        Returns:
            An ``aiobotocore`` Bedrock Runtime client instance.
        """
        import aioboto3
        from botocore.config import Config as BotoConfig

        session = aioboto3.Session(profile_name=self._profile) if self._profile else aioboto3.Session()

        client_kwargs: Dict[str, Any] = {
            "region_name": self._region,
            "config": BotoConfig(
                retries={"max_attempts": self._max_retries, "mode": "adaptive"},
                read_timeout=self._read_timeout,
            ),
        }
        if self._aws_access_key and self._aws_secret_key:
            client_kwargs["aws_access_key_id"] = self._aws_access_key
            client_kwargs["aws_secret_access_key"] = self._aws_secret_key
            if self._aws_session_token:
                client_kwargs["aws_session_token"] = self._aws_session_token
        elif self._aws_bearer_token:
            # A configured Bedrock API key is AUTHORITATIVE: bind the token
            # to this session explicitly and pin the auth scheme to
            # ``bearer``, rather than exporting AWS_BEARER_TOKEN_BEDROCK and
            # hoping botocore prefers it.
            #
            # The env-var hand-off (the previous approach) silently lost
            # whenever SigV4 credentials were resolvable — and navconfig
            # itself exports AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY from
            # env/.env into os.environ, so botocore's credential chain
            # found them first and signed as that IAM identity. Every call
            # then failed with AccessDeniedException naming an identity the
            # operator never intended to use for Bedrock, while the
            # configured API key sat unused. It is also unsupported below
            # botocore 1.36 (this project pins 1.35.x), where reading
            # AWS_BEARER_TOKEN_* does not exist at all.
            #
            # ``signature_version="bearer"`` selects botocore's BearerAuth
            # (auth.AUTH_TYPE_MAPS), which takes its token from the
            # session's ``token_provider`` component — supported on both
            # 1.35.x and later.
            # ``_session`` is boto3/aioboto3's only handle on the underlying
            # botocore session — there is no public accessor.
            session._session.register_component("token_provider", _StaticBedrockTokenProvider(self._aws_bearer_token))
            client_kwargs["config"] = client_kwargs["config"].merge(BotoConfig(signature_version="bearer"))
            self.logger.debug(
                "Bedrock auth: using the configured API key (bearer); "
                "ambient SigV4 credentials, if any, are bypassed."
            )
        # else: no static keys or bearer token resolved from parrot config —
        # fall through to botocore's own default credential chain (env vars,
        # AWS_BEARER_TOKEN_BEDROCK if already exported, shared credentials
        # file, SSO, instance role, ...).

        client_ctx = session.client("bedrock-runtime", **client_kwargs)
        return await client_ctx.__aenter__()

    def _translate_model(self, model: Optional[str]) -> str:
        """Resolve a public/Bedrock model ID via ``bedrock_models.translate()``.

        Args:
            model: A public model ID, alias, or already Bedrock-shaped ID.

        Returns:
            The Bedrock model ID to send as ``modelId``.
        """
        raw = model or self.model or self.default_model
        return translate_bedrock_model(raw, self._region_prefix)

    def _is_capacity_error(self, error: Exception) -> bool:
        """Detect Bedrock throttling/capacity errors.

        Recognises both a real ``botocore.exceptions.ClientError`` (via its
        ``response["Error"]["Code"]`` shape) and the dynamically generated
        ``client.exceptions.ThrottlingException`` class (matched by class
        name, since it is not import-stable across botocore versions).
        """
        error_code = None
        response = getattr(error, "response", None)
        if isinstance(response, dict):
            error_code = response.get("Error", {}).get("Code")
        capacity_codes = (
            "ThrottlingException",
            "ServiceUnavailableException",
            "ModelNotReadyException",
            "ModelTimeoutException",
        )
        if error_code in capacity_codes or type(error).__name__ in capacity_codes:
            return True
        return super()._is_capacity_error(error)

    # ------------------------------------------------------------------
    # Thin SDK wrappers (pattern: AnthropicClient._sdk_create/_sdk_stream)
    # ------------------------------------------------------------------

    async def _sdk_create(self, payload: dict) -> Dict[str, Any]:
        """Dispatch a non-streaming ``converse()`` call."""
        return await self.client.converse(**payload)

    async def _sdk_stream(self, payload: dict) -> AsyncIterator[Dict[str, Any]]:
        """Dispatch a streaming ``converse_stream()`` call.

        Returns:
            The ``stream`` async iterator of Converse stream events
            (``contentBlockStart`` / ``contentBlockDelta`` /
            ``contentBlockStop`` / ``messageStop`` / ``metadata``).
        """
        response = await self.client.converse_stream(**payload)
        return response["stream"]

    # ------------------------------------------------------------------
    # Message / tool schema adaptation
    # ------------------------------------------------------------------

    def _prepare_messages(self, prompt: str, files: Optional[List[Union[str, Path]]] = None) -> List[Dict[str, Any]]:
        """Build the initial Bedrock Converse user message.

        Overrides :meth:`AbstractClient._prepare_messages` (which produces
        Anthropic-shaped ``{"type": "text", "text": ...}`` blocks) to emit
        Bedrock Converse's ``{"text": ...}`` block shape directly. Keeps the
        same ``(prompt, files)`` signature so it remains a drop-in override
        for :meth:`AbstractClient._prepare_conversation_context`, which calls
        it internally.

        Note:
            File/image attachments are not yet supported for Bedrock
            Converse in this client — a warning is logged and files are
            skipped (no Bedrock-specific encoding implemented yet).
        """
        if files:
            self.logger.warning(
                "BedrockConverseClient: file/image attachments are not yet " "supported (%d file(s) ignored).",
                len(files),
            )
        return [{"role": "user", "content": [{"text": prompt}]}]

    @staticmethod
    def _to_bedrock_content_block(block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert a single ai-parrot (Anthropic-shaped) content block to
        Bedrock Converse shape.

        Returns:
            The converted block, the block unchanged if it is already
            Bedrock-shaped (e.g. re-appended assistant turns), or ``None``
            for block types Bedrock Converse does not support yet (e.g. raw
            file-path attachments) — callers must filter out ``None``.
        """
        block_type = block.get("type")
        if block_type == "text":
            return {"text": block.get("text", "")}
        if block_type == "tool_use":
            return {
                "toolUse": {
                    "toolUseId": block.get("id"),
                    "name": block.get("name"),
                    "input": block.get("input", {}),
                }
            }
        if block_type == "tool_result":
            result_block: Dict[str, Any] = {
                "toolUseId": block.get("tool_use_id"),
                "content": [{"text": str(block.get("content", ""))}],
            }
            if block.get("is_error"):
                result_block["status"] = "error"
            return {"toolResult": result_block}
        if block_type == "file":
            # Not yet supported — dropped (see _prepare_messages note).
            return None
        # Already Bedrock-shaped (e.g. text/toolUse/toolResult/reasoningContent
        # blocks re-appended verbatim from a previous converse() response).
        if any(key in block for key in ("text", "toolUse", "toolResult", "reasoningContent")):
            return block
        return None

    def _to_bedrock_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert a list of ai-parrot conversation messages into Bedrock
        Converse ``messages`` shape (``role`` + list of Converse content
        blocks).

        Args:
            messages: Messages as produced by
                :meth:`AbstractClient._prepare_conversation_context`
                (Anthropic-shaped content blocks, mixed with any already
                Bedrock-shaped blocks re-appended by the tool-use loop).

        Returns:
            Messages with content blocks in Bedrock Converse shape.
            Messages with no convertible content blocks are dropped.
        """
        converted: List[Dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if isinstance(content, str):
                blocks = [{"text": content}]
            else:
                blocks = [
                    converted_block
                    for block in (content or [])
                    if (converted_block := self._to_bedrock_content_block(block)) is not None
                ]
            if blocks:
                converted.append({"role": role, "content": blocks})
        return converted

    def _inference_config(
        self,
        model_id: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Build the Converse ``inferenceConfig`` block for *model_id*.

        ``temperature`` is omitted for the 2026-generation models that reject
        sampling parameters (see :func:`rejects_sampling_params`) — sending it
        fails the whole call with a ``ValidationException`` instead of being
        ignored.

        Args:
            model_id: The already-translated Bedrock model ID.
            max_tokens: Per-call output cap; falls back to ``self.max_tokens``
                then 4096.
            temperature: Per-call sampling temperature; falls back to
                ``self.temperature``.

        Returns:
            The ``inferenceConfig`` dict for the Converse payload.
        """
        config: Dict[str, Any] = {
            "maxTokens": max_tokens if max_tokens is not None else (self.max_tokens or 4096),
        }
        if not rejects_sampling_params(model_id):
            config["temperature"] = temperature if temperature is not None else self.temperature
        return config

    def _prepare_tools(self, filter_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Convert registered tools to Bedrock Converse ``toolSpec`` format.

        Overrides :meth:`AbstractClient._prepare_tools`, which only
        recognises a fixed set of ``client_type`` values (openai / google /
        groq / vertex, else Anthropic) and does not know about
        ``bedrock-converse``. Uses
        :class:`~parrot.tools.manager.ToolSchemaAdapter` with
        :attr:`~parrot.tools.manager.ToolFormat.BEDROCK` (TASK-1743)
        instead.

        Args:
            filter_names: If given, only tools whose name is in this list
                are included (used by lazy-loading tool search).

        Returns:
            A list of ``{"toolSpec": {...}}`` envelopes suitable for
            ``toolConfig.tools`` in a Converse API request.
        """
        manager_tools = self.tool_manager.get_tool_schemas(provider_format=ToolFormat.BEDROCK)

        tool_specs: List[Dict[str, Any]] = []
        processed: set = set()
        for schema in manager_tools:
            clean_schema = schema.copy()
            clean_schema.pop("_tool_instance", None)
            tool_name = clean_schema.get("toolSpec", {}).get("name")

            if filter_names is not None and tool_name not in filter_names:
                continue
            if tool_name and tool_name not in processed:
                tool_specs.append(clean_schema)
                processed.add(tool_name)

        self.logger.debug("Prepared %d Bedrock tool specs", len(tool_specs))
        return tool_specs

    def _parse_json_schema_output(self, text: str) -> Any:
        """Parse a raw-JSON-Schema structured-output response (Module 5).

        Used for the ``output_schema`` param (a plain JSON Schema dict, as
        opposed to ``structured_output``/``output_type`` which target a
        Pydantic/dataclass type via
        :class:`~parrot.models.outputs.StructuredOutputConfig`). Falls back
        to markdown-code-block extraction, then to the raw text, if direct
        JSON parsing fails.

        Args:
            text: The assistant's response text, expected to contain a JSON
                document per the schema instruction injected into the
                system prompt.

        Returns:
            The parsed JSON value (usually a ``dict``), or the original
            text unchanged if it could not be parsed as JSON.
        """
        try:
            return self._json.loads(text)
        except Exception:
            pass
        try:
            candidate = self._extract_json_from_response(text)
            return self._json.loads(candidate)
        except Exception:
            return text

    # ------------------------------------------------------------------
    # Guardrails (Module 5)
    # ------------------------------------------------------------------

    async def apply_guardrail_text(self, text: str, source: str = "OUTPUT") -> str:
        """Apply the configured Bedrock guardrail to standalone text.

        Calls Bedrock's ``apply_guardrail()`` API directly (not via
        ``converse()``) — useful for filtering text that did not originate
        from a Converse call (e.g. transcriptions, as used by
        :class:`~parrot.clients.nova.audio.NovaAudio` via
        :meth:`~parrot.clients.nova.audio.NovaAudio._apply_pii_guardrail`,
        TASK-1748/FEAT-315).

        Args:
            text: The text to filter.
            source: Guardrail content source — ``"INPUT"`` or ``"OUTPUT"``
                (default).

        Returns:
            The guardrail-processed text, or the original *text* unchanged
            if no guardrail is configured on this client (``guardrail_id``/
            ``guardrail_version`` were not passed to ``__init__``).
        """
        if not self._guardrail_id or not self._guardrail_version:
            return text

        await self._ensure_client()
        response = await self.client.apply_guardrail(
            guardrailIdentifier=self._guardrail_id,
            guardrailVersion=self._guardrail_version,
            source=source,
            content=[{"text": {"text": text}}],
        )
        output_blocks = response.get("outputs", [])
        processed_text = "".join(block.get("text", "") for block in output_blocks if "text" in block)
        return processed_text or text

    # ------------------------------------------------------------------
    # invoke_model fallback for non-ARN-versioned model IDs (Module 5)
    # ------------------------------------------------------------------

    async def _invoke_native(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fallback to ``invoke_model()`` for models without ARN-versioned IDs.

        Some Bedrock-hosted models (e.g. Opus 4.8, Fable 5) are not yet
        available via the Converse envelope and must be called through
        ``invoke_model()`` using the Anthropic-native request/response
        payload format directly (``anthropic_version`` +
        ``messages``/``content`` blocks with ``"type"`` keys — the same
        shape :class:`~parrot.clients.claude.AnthropicClient` sends).

        Args:
            messages: Anthropic-native messages (``{"role", "content":
                [{"type": "text", "text": ...}]}``).
            model: Bedrock model ID (already translated). Falls back to
                ``self.model`` translated via :meth:`_translate_model`.
            max_tokens: Maximum completion tokens.
            temperature: Sampling temperature.
            system_prompt: Optional system prompt string.

        Returns:
            The decoded Anthropic-native response body (``dict``) — NOT the
            Converse envelope shape.
        """
        await self._ensure_client()
        resolved_model = model or self._translate_model(self.model)
        max_tokens = self._resolve_max_tokens(max_tokens, resolved_model)

        body: Dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": messages,
        }
        # Same rejection as the Converse path — the 2026-generation models
        # answer a request carrying ``temperature`` with a 400.
        if not rejects_sampling_params(resolved_model):
            body["temperature"] = temperature
        if system_prompt:
            body["system"] = system_prompt

        response = await self.client.invoke_model(
            modelId=resolved_model,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        response_body = await response["body"].read()
        return json.loads(response_body)

    # ------------------------------------------------------------------
    # Public API: ask / ask_stream / resume / invoke
    # ------------------------------------------------------------------

    async def ask(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
        deep_research: bool = False,
        background: bool = False,
        lazy_loading: bool = False,
        thinking_budget: Optional[int] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        prompt_cache: bool = False,
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
    ) -> AIMessage:
        """Ask Bedrock a question via the Converse API, with tool-use loop.

        Args:
            deep_research: Not yet supported for Bedrock — logged and
                ignored.
            background: Not yet supported for Bedrock — logged and ignored.
            lazy_loading: Not yet supported for Bedrock — falls back to
                eager tool preparation.
            thinking_budget: When set, enables extended thinking via
                ``additionalModelRequestFields.thinking`` (Module 5). Only
                supported by specific models (Claude Sonnet 4 family, etc.);
                the resulting ``reasoningContent`` blocks (text + opaque
                ``signature``) are preserved verbatim across tool-use
                rounds and are available on the returned ``AIMessage`` via
                ``raw_response`` (no dedicated field — see spec §6).
                FEAT-482 Module 3: on 2026-generation Anthropic models
                that reject ``budget_tokens`` (Opus 5, Fable 5, Opus
                4.8/4.7, Sonnet 5, Mythos 5 — see
                :func:`_requires_adaptive_thinking`), the value is used
                only as an on/off switch and the request instead carries
                ``{"type": "adaptive"}``. Amazon Nova and older Anthropic
                models keep the ``budget_tokens`` shape byte-identically.
            output_schema: Optional raw JSON Schema dict. When provided, a
                schema-in-system-prompt instruction is injected (Module 5)
                and the final response text is parsed as JSON into
                ``AIMessage.structured_output`` (``is_structured=True``).
                Distinct from ``structured_output`` (which targets a
                Pydantic/dataclass type via
                :class:`~parrot.models.outputs.StructuredOutputConfig`) —
                use this when you only have a raw JSON Schema, not a type.
            prompt_cache: When ``True``, marks the system prompt as a cache
                point (Module 5) via ``system=[{"text": ...},
                {"cachePoint": {"type": "default"}}]`` and
                ``additionalModelRequestFields.promptCaching``. Cache hit/miss
                metrics arrive via ``cacheReadInputTokens`` /
                ``cacheWriteInputTokens`` in ``CompletionUsage.extra_usage``
                (already surfaced by ``CompletionUsage.from_bedrock()``,
                TASK-1742). For multi-round tool-use calls, these two
                counters are the **sum across all rounds** (FEAT-404, U1) —
                not the last round's values — because
                ``CompletionUsage.__add__`` shallow-merges ``extra_usage``
                right-hand-wins and would otherwise silently drop earlier
                rounds' cache accounting.
            guardrail_id: Per-call guardrail identifier override. Falls back
                to the identifier passed to ``__init__``.
            guardrail_version: Per-call guardrail version override. Falls
                back to the version passed to ``__init__``.
        """
        await self._ensure_client()

        _use_tools = use_tools if use_tools is not None else self.enable_tools
        resolved_model = self._translate_model(model)
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        if deep_research or background:
            self.logger.warning(
                "BedrockConverseClient.ask(): deep_research/background are " "not yet supported; ignoring."
            )
        if lazy_loading:
            self.logger.warning(
                "BedrockConverseClient.ask(): lazy_loading is not yet "
                "supported; falling back to eager tool preparation."
            )

        messages, conversation_history, resolved_system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )
        bedrock_messages = self._to_bedrock_messages(messages)

        _lc_tc = self._emit_before_call(
            client_name=self.client_name,
            model=resolved_model,
            temperature=temperature if temperature is not None else self.temperature,
            system_prompt=self._resolve_system_prompt(resolved_system_prompt),
            has_tools=bool(_use_tools),
            parent_trace=None,
        )
        _lc_t0 = time.perf_counter()

        output_config = self._get_structured_config(structured_output)
        if output_config:
            schema_instruction = output_config.format_schema_instruction()
            resolved_system_prompt = (
                f"{resolved_system_prompt}\n\n{schema_instruction}" if resolved_system_prompt else schema_instruction
            )
        elif output_schema:
            # Module 5: schema-in-system-prompt structured output from a raw
            # JSON Schema dict (no Pydantic/dataclass type available).
            schema_instruction = "Respond with valid JSON matching this schema: " f"{json.dumps(output_schema)}"
            resolved_system_prompt = (
                f"{resolved_system_prompt}\n\n{schema_instruction}" if resolved_system_prompt else schema_instruction
            )

        payload: Dict[str, Any] = {
            "modelId": resolved_model,
            "messages": bedrock_messages,
            "inferenceConfig": self._inference_config(resolved_model, max_tokens, temperature),
        }
        if resolved_system_prompt:
            if prompt_cache:
                payload["system"] = [
                    {"text": resolved_system_prompt},
                    {"cachePoint": {"type": "default"}},
                ]
            else:
                payload["system"] = [{"text": resolved_system_prompt}]

        additional_fields: Dict[str, Any] = {}
        if thinking_budget:
            if _requires_adaptive_thinking(resolved_model):
                # FEAT-482 Module 3: modern Anthropic models (Opus 5, Fable
                # 5, Opus 4.8/4.7, Sonnet 5) 400 on the legacy
                # ``budget_tokens`` shape and require ``{"type":
                # "adaptive"}`` instead. Effort is deliberately left at
                # Bedrock's own default rather than threading a new
                # ``effort`` parameter through this call — the caller's
                # ``thinking_budget`` value has no adaptive-shape
                # equivalent to carry.
                additional_fields["thinking"] = {"type": "adaptive"}
            else:
                additional_fields["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": thinking_budget,
                }
        if prompt_cache:
            additional_fields["promptCaching"] = {"cachePoint": {"type": "default"}}
        if additional_fields:
            payload["additionalModelRequestFields"] = additional_fields

        resolved_guardrail_id = guardrail_id or self._guardrail_id
        resolved_guardrail_version = guardrail_version or self._guardrail_version
        if resolved_guardrail_id and resolved_guardrail_version:
            payload["guardrailConfig"] = {
                "guardrailIdentifier": resolved_guardrail_id,
                "guardrailVersion": resolved_guardrail_version,
            }

        if _use_tools and tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)

        if _use_tools:
            tool_specs = self._prepare_tools()
            if tool_specs:
                payload["toolConfig"] = {"tools": tool_specs}

        all_tool_calls: List[ToolCall] = []
        used_fallback = False
        result: Dict[str, Any] = {}
        content_blocks: List[Dict[str, Any]] = []

        # FEAT-404: per-round token usage accumulation across the tool loop
        # (mirrors the FEAT-397 idiom in AnthropicClient.ask()).
        _lc_round_number = 0
        _lc_accumulated_usage: Optional[CompletionUsage] = None

        while True:
            # FEAT-404: time this round's SDK call (including a fallback
            # retry, if any) for the round event's duration_ms.
            _lc_round_t0 = time.perf_counter()
            try:
                result = await self._sdk_create(payload)
            except Exception as e:
                if self._should_use_fallback(payload["modelId"], e):
                    self.logger.warning(
                        "Bedrock model %s capacity error: %s. Retrying with fallback: %s",
                        payload["modelId"],
                        e,
                        self._fallback_model,
                    )
                    payload["modelId"] = self._translate_model(self._fallback_model)
                    used_fallback = True
                    result = await self._sdk_create(payload)
                else:
                    raise
            _lc_round_number += 1
            _lc_round_duration_ms = (time.perf_counter() - _lc_round_t0) * 1000

            # FEAT-404: build this round's usage and accumulate. Rounds
            # where the provider reported no usage are skipped (accumulator
            # untouched); the round event still fires with usage=None.
            _lc_round_raw_usage = result.get("usage") or None
            if _lc_round_raw_usage:
                _lc_round_usage = CompletionUsage.from_bedrock(_lc_round_raw_usage)
                if _lc_accumulated_usage is None:
                    _lc_accumulated_usage = _lc_round_usage
                else:
                    # __add__ shallow-merges extra_usage right-hand-wins, so
                    # capture the pre-add cache counters before they are
                    # overwritten by this round's values (spec §2, U1).
                    _lc_prev_cache_read = _lc_accumulated_usage.extra_usage.get("cacheReadInputTokens", 0) or 0
                    _lc_prev_cache_write = _lc_accumulated_usage.extra_usage.get("cacheWriteInputTokens", 0) or 0
                    _lc_accumulated_usage = _lc_accumulated_usage + _lc_round_usage
                    # Re-sum the two cache counters explicitly so multi-round
                    # totals honour the ask() docstring (spec §2, U1) instead
                    # of reporting only the last round's cache accounting.
                    _lc_accumulated_usage.extra_usage["cacheReadInputTokens"] = _lc_prev_cache_read + (
                        _lc_round_usage.extra_usage.get("cacheReadInputTokens", 0) or 0
                    )
                    _lc_accumulated_usage.extra_usage["cacheWriteInputTokens"] = _lc_prev_cache_write + (
                        _lc_round_usage.extra_usage.get("cacheWriteInputTokens", 0) or 0
                    )
            else:
                _lc_round_usage = None

            message = result.get("output", {}).get("message", {})
            content_blocks = message.get("content", [])

            if result.get("stopReason") == "tool_use":
                tool_result_blocks = []
                _lc_round_tool_names: List[str] = []

                for block in content_blocks:
                    if "toolUse" not in block:
                        continue
                    tool_use = block["toolUse"]
                    tool_name = tool_use.get("name")
                    tool_input = tool_use.get("input", {})
                    tool_id = tool_use.get("toolUseId")

                    tc = ToolCall(id=tool_id, name=tool_name, arguments=tool_input)

                    try:
                        start_time = time.time()
                        tool_result = await self._execute_tool(tool_name, tool_input)
                        tc.result = tool_result
                        tc.execution_time = time.time() - start_time
                        tool_result_blocks.append(
                            {
                                "toolResult": {
                                    "toolUseId": tool_id,
                                    "content": [{"text": str(tool_result)}],
                                }
                            }
                        )
                    except Exception as e:
                        from parrot.core.exceptions import HumanInteractionInterrupt

                        if isinstance(e, HumanInteractionInterrupt):
                            e.session_id = session_id
                            e.messages = bedrock_messages + [{"role": "assistant", "content": content_blocks}]
                            e.tool_call_id = tool_id
                            e.agent_name = resolved_model
                            raise

                        tc.error = str(e)
                        tool_result_blocks.append(
                            {
                                "toolResult": {
                                    "toolUseId": tool_id,
                                    "content": [{"text": str(e)}],
                                    "status": "error",
                                }
                            }
                        )

                    all_tool_calls.append(tc)
                    _lc_round_tool_names.append(tool_name)

                # FEAT-404: emit ClientRoundEvent after tool execution for
                # this round (mirrors AnthropicClient.ask(), claude.py:640-650).
                self._emit_round_event(
                    _lc_tc,
                    client_name=self.client_name,
                    model=resolved_model,
                    round_number=_lc_round_number,
                    usage=_lc_round_usage,
                    raw_usage=_lc_round_raw_usage,
                    tool_calls=_lc_round_tool_names,
                    duration_ms=_lc_round_duration_ms,
                )

                # Preserve the assistant turn verbatim (reasoningContent
                # blocks, with their signature, travel through unmodified —
                # see spec §7 "ReasoningContent signature corruption").
                bedrock_messages.append({"role": "assistant", "content": content_blocks})
                bedrock_messages.append({"role": "user", "content": tool_result_blocks})
                payload["messages"] = bedrock_messages
            else:
                bedrock_messages.append({"role": "assistant", "content": content_blocks})
                break

        final_output = None
        assistant_response_text = "".join(block.get("text", "") for block in content_blocks if "text" in block)
        if output_config:
            try:
                if output_config.custom_parser:
                    final_output = await output_config.custom_parser(assistant_response_text)
                else:
                    final_output = await self._parse_structured_output(assistant_response_text, output_config)
            except Exception:
                final_output = assistant_response_text
        elif output_schema:
            final_output = self._parse_json_schema_output(assistant_response_text)

        tools_used = [tc.name for tc in all_tool_calls]
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_history,
            bedrock_messages,
            resolved_system_prompt,
            turn_id,
            original_prompt,
            assistant_response_text,
            tools_used,
        )

        ai_message = AIMessageFactory.from_bedrock(
            response=result,
            input_text=original_prompt,
            model=payload["modelId"] if used_fallback else resolved_model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output,
            tool_calls=all_tool_calls,
        )

        if used_fallback:
            ai_message.metadata["used_fallback_model"] = True
            ai_message.metadata["original_model"] = resolved_model
            ai_message.metadata["fallback_model"] = self._fallback_model

        # FEAT-404: replace the last-round-only usage with the accumulated
        # multi-round total. For single-round calls (no tool use), the
        # accumulated total equals the last (only) round's usage, so this
        # is a strict no-op for existing single-round behavior.
        if _lc_accumulated_usage is not None:
            if _lc_round_number > 1:
                _lc_accumulated_usage.extra_usage["rounds"] = _lc_round_number
            ai_message.usage = _lc_accumulated_usage

        _lc_usage = ai_message.usage
        await self._emit_after_call(
            _lc_tc,
            client_name=self.client_name,
            model=resolved_model,
            duration_ms=(time.perf_counter() - _lc_t0) * 1000,
            input_tokens=getattr(_lc_usage, "input_tokens", None) if _lc_usage else None,
            output_tokens=getattr(_lc_usage, "output_tokens", None) if _lc_usage else None,
            finish_reason=ai_message.stop_reason,
        )
        return ai_message

    async def ask_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: bool = True,
        deep_research: bool = False,
        agent_config: Optional[Dict[str, Any]] = None,
        lazy_loading: bool = False,
        thinking_budget: Optional[int] = None,
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[Union[str, AIMessage]]:
        """Stream a Bedrock Converse response with tool-use support.

        Yields successive ``str`` chunks (mapped from ``contentBlockDelta``
        events), then a single final :class:`AIMessage` sentinel — the same
        streaming convention followed by every other client
        (:meth:`AnthropicClient.ask_stream`, etc.).

        When the model requests a tool during streaming, the tool is executed
        between streaming rounds: text from the current round is yielded as
        it arrives, then the tool executes (a brief pause the caller sees as
        a gap between chunks), and a new streaming round begins with the
        tool result injected into the conversation. This mirrors the
        ``while True`` tool loop in :meth:`ask` and the existing streaming
        tool support in the Google client.

        Args:
            use_tools: Whether to include tool definitions and run the
                streaming tool-call loop.  Defaults to ``True``.
            thinking_budget: See :meth:`ask` — enables extended thinking via
                ``additionalModelRequestFields.thinking`` (Module 5),
                including the FEAT-482 Module 3 adaptive-shape selection
                for 2026-generation Anthropic models.
            guardrail_id: Per-call guardrail identifier override. Falls back
                to the identifier passed to ``__init__``.
            guardrail_version: Per-call guardrail version override. Falls
                back to the version passed to ``__init__``.
        """
        await self._ensure_client()

        resolved_model = self._translate_model(model)
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        if deep_research:
            self.logger.warning("BedrockConverseClient.ask_stream(): deep_research is not " "yet supported; ignoring.")
        if lazy_loading:
            self.logger.warning(
                "BedrockConverseClient.ask_stream(): lazy_loading is not "
                "yet supported; falling back to eager tool preparation."
            )

        messages, conversation_history, resolved_system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )
        bedrock_messages = self._to_bedrock_messages(messages)

        payload: Dict[str, Any] = {
            "modelId": resolved_model,
            "messages": bedrock_messages,
            "inferenceConfig": self._inference_config(resolved_model, max_tokens, temperature),
        }
        if resolved_system_prompt:
            payload["system"] = [{"text": resolved_system_prompt}]

        if thinking_budget:
            if _requires_adaptive_thinking(resolved_model):
                # FEAT-482 Module 3: see the identical branch in ask().
                payload["additionalModelRequestFields"] = {"thinking": {"type": "adaptive"}}
            else:
                payload["additionalModelRequestFields"] = {
                    "thinking": {"type": "enabled", "budget_tokens": thinking_budget}
                }

        resolved_guardrail_id = guardrail_id or self._guardrail_id
        resolved_guardrail_version = guardrail_version or self._guardrail_version
        if resolved_guardrail_id and resolved_guardrail_version:
            payload["guardrailConfig"] = {
                "guardrailIdentifier": resolved_guardrail_id,
                "guardrailVersion": resolved_guardrail_version,
            }

        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)

        if use_tools and self.enable_tools:
            tool_specs = self._prepare_tools()
            if tool_specs:
                payload["toolConfig"] = {"tools": tool_specs}

        # ── Streaming tool-call loop ──────────────────────────────────
        # Mirrors the while-True loop in ask() (line ~870). Each round
        # streams text chunks to the caller; when the model stops with
        # stopReason="tool_use", tools are executed between rounds and
        # the conversation continues.
        all_tool_calls: List[ToolCall] = []
        accumulated_text = ""
        stop_reason: Optional[str] = None
        usage_dict: Dict[str, Any] = {}
        _max_tool_rounds = 25  # safety cap, same depth as ask()

        for _round in range(_max_tool_rounds):
            # ── Stream one round ──────────────────────────────────────
            round_text = ""
            round_content_blocks: List[Dict[str, Any]] = []
            # Collect tool-use blocks from stream events.
            _current_tool_block: Optional[Dict[str, str]] = None
            _tool_use_blocks: List[Dict[str, Any]] = []

            stream = await self._sdk_stream(payload)
            async for event in stream:
                # --- Text chunks: yield immediately ---
                delta = event.get("contentBlockDelta", {}).get("delta", {})
                text_chunk = delta.get("text")
                if text_chunk:
                    round_text += text_chunk
                    accumulated_text += text_chunk
                    yield text_chunk

                # --- Tool-use block collection ---
                if "contentBlockStart" in event:
                    start_body = event["contentBlockStart"].get("start", {})
                    if "toolUse" in start_body:
                        _current_tool_block = {
                            "toolUseId": start_body["toolUse"].get("toolUseId", ""),
                            "name": start_body["toolUse"].get("name", ""),
                            "input_json": "",
                        }
                # Accumulate streamed tool-input JSON fragments.
                tool_use_delta = delta.get("toolUse")
                if tool_use_delta and _current_tool_block is not None:
                    _current_tool_block["input_json"] += tool_use_delta.get("input", "")
                if "contentBlockStop" in event and _current_tool_block is not None:
                    _tool_use_blocks.append(_current_tool_block)
                    _current_tool_block = None

                if "messageStop" in event:
                    stop_reason = event["messageStop"].get("stopReason")
                if "metadata" in event:
                    usage_dict = event["metadata"].get("usage", {})

            # ── Build the assistant content blocks for this round ─────
            if round_text:
                round_content_blocks.append({"text": round_text})
            for tb in _tool_use_blocks:
                try:
                    tool_input = json.loads(tb["input_json"]) if tb["input_json"] else {}
                except (json.JSONDecodeError, TypeError):
                    tool_input = {}
                round_content_blocks.append({
                    "toolUse": {
                        "toolUseId": tb["toolUseId"],
                        "name": tb["name"],
                        "input": tool_input,
                    }
                })

            bedrock_messages.append({"role": "assistant", "content": round_content_blocks})

            # ── Tool-use round: execute tools, loop ───────────────────
            if stop_reason == "tool_use" and _tool_use_blocks:
                tool_result_blocks: List[Dict[str, Any]] = []
                for tb in _tool_use_blocks:
                    try:
                        tool_input = json.loads(tb["input_json"]) if tb["input_json"] else {}
                    except (json.JSONDecodeError, TypeError):
                        tool_input = {}
                    tc = ToolCall(
                        id=tb["toolUseId"],
                        name=tb["name"],
                        arguments=tool_input,
                    )
                    try:
                        start_time = time.time()
                        tool_result = await self._execute_tool(tb["name"], tool_input)
                        tc.result = tool_result
                        tc.execution_time = time.time() - start_time
                        tool_result_blocks.append({
                            "toolResult": {
                                "toolUseId": tb["toolUseId"],
                                "content": [{"text": str(tool_result)}],
                            }
                        })
                    except Exception as e:
                        from parrot.core.exceptions import HumanInteractionInterrupt

                        if isinstance(e, HumanInteractionInterrupt):
                            e.session_id = session_id
                            e.messages = bedrock_messages
                            e.tool_call_id = tb["toolUseId"]
                            e.agent_name = resolved_model
                            raise
                        tc.error = str(e)
                        tool_result_blocks.append({
                            "toolResult": {
                                "toolUseId": tb["toolUseId"],
                                "content": [{"text": str(e)}],
                                "status": "error",
                            }
                        })
                    all_tool_calls.append(tc)

                bedrock_messages.append({"role": "user", "content": tool_result_blocks})
                payload["messages"] = bedrock_messages
                # Reset for next round — stop_reason will be overwritten.
                stop_reason = None
            else:
                # No tool call (or tools disabled) — done.
                break

        tools_used = [tc.name for tc in all_tool_calls]
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_history,
            bedrock_messages,
            resolved_system_prompt,
            turn_id,
            original_prompt,
            accumulated_text,
            tools_used,
        )

        synthetic_response = {
            "output": {"message": {"role": "assistant", "content": [{"text": accumulated_text}]}},
            "stopReason": stop_reason,
            "usage": usage_dict,
        }
        yield AIMessageFactory.from_bedrock(
            response=synthetic_response,
            input_text=original_prompt,
            model=resolved_model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            tool_calls=all_tool_calls,
        )

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage:
        """Resume a suspended Bedrock tool-use execution.

        Args:
            session_id: The session ID.
            user_input: The user's input, injected as the ``toolResult``
                content for the pending ``toolUseId``.
            state: The suspended state — ``messages`` (Bedrock-shaped, as
                captured by :meth:`ask`'s ``HumanInteractionInterrupt``
                path), ``tool_call_id``, and optional ``agent_name`` (model
                override).

        Returns:
            The :class:`AIMessage` produced once the resumed tool-use loop
            reaches a non-``tool_use`` stop reason.

        Note:
            FEAT-404 (U2/U4): unlike the five reference clients (Anthropic,
            OpenAI, Gemini, Groq, Grok), whose ``resume()`` carries no
            lifecycle instrumentation, Bedrock/Nova's ``resume()``
            deliberately DOES emit a full call-level lifecycle span
            (``BeforeClientCallEvent``/``AfterClientCallEvent``) plus
            per-round ``ClientRoundEvent``s and accumulated multi-round
            usage — the same four-part idiom as :meth:`ask`. This asymmetry
            is intentional (completeness over parity); do not remove it in
            a future consistency sweep.
        """
        await self._ensure_client()

        # Code-review fix (FEAT-302): copy rather than alias state["messages"]
        # — this method appends to bedrock_messages below (and again inside
        # the tool loop), so binding by reference would mutate the caller's
        # stored state in place. A retried resume() call against the same
        # saved state would otherwise accumulate stray entries from the
        # first attempt. Same pattern pre-exists in AnthropicClient.resume().
        bedrock_messages: List[Dict[str, Any]] = list(state["messages"])
        tool_call_id = state["tool_call_id"]
        resolved_model = self._translate_model(state.get("agent_name", self.model or self.default_model))

        bedrock_messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": tool_call_id,
                            "content": [{"text": user_input}],
                        }
                    }
                ],
            }
        )

        all_tool_calls: List[ToolCall] = []
        turn_id = str(uuid.uuid4())

        payload: Dict[str, Any] = {
            "modelId": resolved_model,
            "messages": bedrock_messages,
            "inferenceConfig": self._inference_config(resolved_model),
        }
        tool_specs = self._prepare_tools()
        if tool_specs:
            payload["toolConfig"] = {"tools": tool_specs}

        # FEAT-404 (U2/U4): establish the call-level lifecycle span that
        # resume() previously lacked entirely (mirrors ask()'s 659-667).
        _lc_tc = self._emit_before_call(
            client_name=self.client_name,
            model=resolved_model,
            temperature=self.temperature,
            system_prompt=None,
            has_tools=bool(tool_specs),
            parent_trace=None,
        )
        _lc_t0 = time.perf_counter()

        result: Dict[str, Any] = {}
        content_blocks: List[Dict[str, Any]] = []

        # FEAT-404: per-round token usage accumulation across the tool loop
        # (same idiom as ask() — see TASK-2094). resume() has no fallback
        # branch, unlike ask().
        _lc_round_number = 0
        _lc_accumulated_usage: Optional[CompletionUsage] = None

        while True:
            # FEAT-404: time this round's SDK call for the round event's
            # duration_ms.
            _lc_round_t0 = time.perf_counter()
            result = await self._sdk_create(payload)
            _lc_round_number += 1
            _lc_round_duration_ms = (time.perf_counter() - _lc_round_t0) * 1000

            # FEAT-404: build this round's usage and accumulate. Rounds
            # where the provider reported no usage are skipped (accumulator
            # untouched); the round event still fires with usage=None.
            _lc_round_raw_usage = result.get("usage") or None
            if _lc_round_raw_usage:
                _lc_round_usage = CompletionUsage.from_bedrock(_lc_round_raw_usage)
                if _lc_accumulated_usage is None:
                    _lc_accumulated_usage = _lc_round_usage
                else:
                    # __add__ shallow-merges extra_usage right-hand-wins, so
                    # capture the pre-add cache counters before they are
                    # overwritten by this round's values (spec §2, U1).
                    _lc_prev_cache_read = _lc_accumulated_usage.extra_usage.get("cacheReadInputTokens", 0) or 0
                    _lc_prev_cache_write = _lc_accumulated_usage.extra_usage.get("cacheWriteInputTokens", 0) or 0
                    _lc_accumulated_usage = _lc_accumulated_usage + _lc_round_usage
                    # Re-sum the two cache counters explicitly so multi-round
                    # totals honour the ask() docstring semantics (spec §2,
                    # U1) instead of reporting only the last round's cache
                    # accounting.
                    _lc_accumulated_usage.extra_usage["cacheReadInputTokens"] = _lc_prev_cache_read + (
                        _lc_round_usage.extra_usage.get("cacheReadInputTokens", 0) or 0
                    )
                    _lc_accumulated_usage.extra_usage["cacheWriteInputTokens"] = _lc_prev_cache_write + (
                        _lc_round_usage.extra_usage.get("cacheWriteInputTokens", 0) or 0
                    )
            else:
                _lc_round_usage = None

            message = result.get("output", {}).get("message", {})
            content_blocks = message.get("content", [])

            if result.get("stopReason") == "tool_use":
                tool_result_blocks = []
                _lc_round_tool_names: List[str] = []

                for block in content_blocks:
                    if "toolUse" not in block:
                        continue
                    tool_use = block["toolUse"]
                    tool_name = tool_use.get("name")
                    tool_input = tool_use.get("input", {})
                    tool_id = tool_use.get("toolUseId")

                    tc = ToolCall(id=tool_id, name=tool_name, arguments=tool_input)

                    try:
                        start_time = time.time()
                        tool_result = await self._execute_tool(tool_name, tool_input)
                        tc.result = tool_result
                        tc.execution_time = time.time() - start_time
                        tool_result_blocks.append(
                            {
                                "toolResult": {
                                    "toolUseId": tool_id,
                                    "content": [{"text": str(tool_result)}],
                                }
                            }
                        )
                    except Exception as e:
                        from parrot.core.exceptions import HumanInteractionInterrupt

                        if isinstance(e, HumanInteractionInterrupt):
                            e.session_id = session_id
                            e.messages = bedrock_messages + [{"role": "assistant", "content": content_blocks}]
                            e.tool_call_id = tool_id
                            e.agent_name = resolved_model
                            raise

                        tc.error = str(e)
                        tool_result_blocks.append(
                            {
                                "toolResult": {
                                    "toolUseId": tool_id,
                                    "content": [{"text": str(e)}],
                                    "status": "error",
                                }
                            }
                        )

                    all_tool_calls.append(tc)
                    _lc_round_tool_names.append(tool_name)

                # FEAT-404: emit ClientRoundEvent after tool execution for
                # this round (mirrors ask(), TASK-2094).
                self._emit_round_event(
                    _lc_tc,
                    client_name=self.client_name,
                    model=resolved_model,
                    round_number=_lc_round_number,
                    usage=_lc_round_usage,
                    raw_usage=_lc_round_raw_usage,
                    tool_calls=_lc_round_tool_names,
                    duration_ms=_lc_round_duration_ms,
                )

                bedrock_messages.append({"role": "assistant", "content": content_blocks})
                bedrock_messages.append({"role": "user", "content": tool_result_blocks})
                payload["messages"] = bedrock_messages
            else:
                bedrock_messages.append({"role": "assistant", "content": content_blocks})
                break

        ai_message = AIMessageFactory.from_bedrock(
            response=result,
            input_text="[Resumed Conversation]",
            model=resolved_model,
            session_id=session_id,
            turn_id=turn_id,
            tool_calls=all_tool_calls,
        )

        # FEAT-404: replace the last-round-only usage with the accumulated
        # multi-round total. For single-round resumes (no further tool
        # use), the accumulated total equals the last (only) round's usage.
        if _lc_accumulated_usage is not None:
            if _lc_round_number > 1:
                _lc_accumulated_usage.extra_usage["rounds"] = _lc_round_number
            ai_message.usage = _lc_accumulated_usage

        _lc_usage = ai_message.usage
        await self._emit_after_call(
            _lc_tc,
            client_name=self.client_name,
            model=resolved_model,
            duration_ms=(time.perf_counter() - _lc_t0) * 1000,
            input_tokens=getattr(_lc_usage, "input_tokens", None) if _lc_usage else None,
            output_tokens=getattr(_lc_usage, "output_tokens", None) if _lc_usage else None,
            finish_reason=ai_message.stop_reason,
        )
        return ai_message

    async def invoke(
        self,
        prompt: str,
        *,
        output_type: Optional[type] = None,
        structured_output: Optional[StructuredOutputConfig] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        use_tools: bool = False,
        tools: Optional[list] = None,
    ) -> InvokeResult:
        """Lightweight stateless invocation for BedrockConverseClient.

        A single ``converse()`` call — no retry, no conversation history, no
        prompt builder. Uses schema-in-system-prompt for structured output
        (Bedrock-native ``outputConfig.textFormat`` support is added in
        Module 5 / TASK-1746).

        Args:
            prompt: User prompt.
            output_type: Pydantic model or dataclass to parse the response
                into.
            structured_output: Full :class:`StructuredOutputConfig`; takes
                precedence over ``output_type``.
            model: Model override. Defaults to ``_lightweight_model``.
            system_prompt: System prompt override.
            max_tokens: Maximum completion tokens.
            temperature: Sampling temperature.
            use_tools: Whether to inject registered tools.
            tools: Additional tool definitions (unused — registered tools
                are always sourced from the tool manager; kept for
                interface parity with other clients).

        Returns:
            :class:`InvokeResult` with parsed output.

        Raises:
            InvokeError: On provider errors.
        """
        try:
            await self._ensure_client()

            resolved_prompt = self._resolve_invoke_system_prompt(system_prompt)
            config = self._build_invoke_structured_config(output_type, structured_output)
            resolved_model = self._translate_model(self._resolve_invoke_model(model))
            max_tokens = self._resolve_max_tokens(max_tokens, resolved_model)

            if config:
                resolved_prompt += "\n\n" + config.format_schema_instruction()

            payload: Dict[str, Any] = {
                "modelId": resolved_model,
                "messages": [{"role": "user", "content": [{"text": prompt}]}],
                "system": [{"text": resolved_prompt}],
                "inferenceConfig": self._inference_config(resolved_model, max_tokens, temperature),
            }

            if use_tools:
                tool_defs = self._prepare_tools()
                if tool_defs:
                    payload["toolConfig"] = {"tools": tool_defs}

            result = await self._sdk_create(payload)

            raw_text = "".join(
                block.get("text", "")
                for block in result.get("output", {}).get("message", {}).get("content", [])
                if "text" in block
            )

            output: Any = raw_text
            if config:
                if config.custom_parser:
                    output = config.custom_parser(raw_text)
                else:
                    output = await self._parse_structured_output(raw_text, config)

            usage = CompletionUsage.from_bedrock(result.get("usage", {}))

            return self._build_invoke_result(output, output_type, resolved_model, usage, result)
        except InvokeError:
            raise
        except Exception as exc:
            raise self._handle_invoke_error(exc)


class BedrockConverseClient(BedrockConverseBase):
    """Client for AWS Bedrock's native Converse API — non-Nova families.

    Thin :class:`BedrockConverseBase` subclass carrying only the
    family-specific defaults (Claude/Llama/Mistral/... on Bedrock). All
    behavior (``ask``/``ask_stream``/``resume``/``invoke``, credential
    resolution, guardrails, structured output) is inherited unchanged from
    :class:`BedrockConverseBase` — this class's public surface is
    byte-compatible with the pre-FEAT-315 monolithic implementation.
    """

    client_type: str = "bedrock-converse"
    client_name: str = "bedrock-converse"
    _default_model: str = "claude-sonnet-4-5"
    _fallback_model: str = "claude-haiku-4-5"
    _lightweight_model: str = "claude-haiku-4-5-20251001"
    # FEAT-181: minimum token count for provider-side prompt caching
    # (Bedrock Anthropic models share Anthropic's 1024-token threshold).
    _min_cache_tokens: int = 1024

    # This client fronts several model families at once, and Bedrock REJECTS an
    # over-cap max_tokens ("The maximum tokens you requested exceeds the model
    # limit of N") rather than clamping. The class default is therefore the
    # smallest cap measured across the families in routine use, and the table
    # below lifts the individual models that accept more.
    _default_max_tokens: int = 16384

    # Measured 2026-09-03 in us-east-1 by walking max_tokens up per model until
    # Converse rejected the request. Keyed by fragment, so one entry matches
    # both the public name and the geo-prefixed Bedrock id
    # (claude-opus-5 / us.anthropic.claude-opus-5).
    _model_max_tokens: Dict[str, int] = {
        "claude-opus-5": 65536,
        "claude-sonnet-5": 65536,
        "gpt-oss-120b": 65536,
        "claude-haiku-4-5": 32768,
        "deepseek.r1": 32768,
        "qwen3-coder-30b": 65536,
        "qwen3-32b": 16384,
    }
