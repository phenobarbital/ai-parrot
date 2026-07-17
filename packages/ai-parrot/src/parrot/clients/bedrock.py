"""Native AWS Bedrock Converse API client for AI-Parrot (FEAT-302).

Implements :class:`BedrockConverseClient`, an async-first
:class:`~parrot.clients.base.AbstractClient` subclass that talks to the AWS
Bedrock Runtime *Converse* API directly via ``aioboto3`` — as opposed to
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

See ``sdd/specs/bedrock-client-llm.spec.md`` for the full design.
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
    AWS_ACCESS_KEY,
    AWS_SECRET_KEY,
    AWS_SESSION_TOKEN,
    AWS_REGION_NAME,
    BEDROCK_AWS_REGION,
)
from ..exceptions import InvokeError
from ..models.basic import CompletionUsage, ToolCall
from ..models.bedrock_models import translate as translate_bedrock_model
from ..models.responses import AIMessage, AIMessageFactory, InvokeResult
from ..models.outputs import StructuredOutputConfig
from ..tools.manager import ToolFormat


class BedrockConverseClient(AbstractClient):
    """Client for AWS Bedrock's native Converse API.

    Uses ``aioboto3`` to call ``bedrock-runtime`` directly, supporting any
    Bedrock-hosted model family (Claude, Nova, Llama, Mistral, ...) — not
    just Claude, which is all :class:`~parrot.clients.claude.AnthropicClient`
    (``backend="bedrock"``) exposes.
    """

    client_type: str = "bedrock-converse"
    client_name: str = "bedrock-converse"
    _default_model: str = "claude-sonnet-4-5"
    _fallback_model: str = "claude-haiku-4-5"
    _lightweight_model: str = "claude-haiku-4-5-20251001"
    # FEAT-181: minimum token count for provider-side prompt caching
    # (Bedrock Anthropic models share Anthropic's 1024-token threshold).
    _min_cache_tokens: int = 1024

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
        **kwargs
    ):
        """Initialise a Bedrock Converse API client.

        Args:
            aws_id: Optional AWS account ID. Resolution: kwarg → ``AWS_ID`` → SDK credential chain.
            region: AWS region for the Bedrock Runtime endpoint. Resolution
                order: explicit kwarg → ``BEDROCK_AWS_REGION`` →
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
            aws_access_key: AWS access key ID. Resolution: kwarg →
                ``AWS_ACCESS_KEY`` → SDK credential chain.
            aws_secret_key: AWS secret access key. Same resolution order.
            aws_session_token: Optional STS session token. Same resolution
                order.
            **kwargs: Forwarded to
                :class:`~parrot.clients.base.AbstractClient`.
        """
        self._aws_id = aws_id
        if self._aws_id:
            if credentials := AWS_CREDENTIALS.get(self._aws_id):
                self._aws_access_key = credentials.get("access_key")
                self._aws_secret_key = credentials.get("secret_key")
                self._aws_session_token = credentials.get("session_token")
                self._region = credentials.get("region") or region or BEDROCK_AWS_REGION or AWS_REGION_NAME or "us-east-1"
        else:
            self._aws_access_key = aws_access_key or AWS_ACCESS_KEY
            self._aws_secret_key = aws_secret_key or AWS_SECRET_KEY
            self._aws_session_token = aws_session_token or AWS_SESSION_TOKEN
            self._region = region or BEDROCK_AWS_REGION or AWS_REGION_NAME or "us-east-1"
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
        kwargs.setdefault('fallback_model', self._fallback_model)
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

        session = (
            aioboto3.Session(profile_name=self._profile)
            if self._profile else aioboto3.Session()
        )

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

    def _prepare_messages(
        self,
        prompt: str,
        files: Optional[List[Union[str, Path]]] = None
    ) -> List[Dict[str, Any]]:
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
                "BedrockConverseClient: file/image attachments are not yet "
                "supported (%d file(s) ignored).", len(files),
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
            return {"toolUse": {
                "toolUseId": block.get("id"),
                "name": block.get("name"),
                "input": block.get("input", {}),
            }}
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
            clean_schema.pop('_tool_instance', None)
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
        :class:`~parrot.integrations.bedrock.nova_sonic.NovaSonicClient`,
        TASK-1748).

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
        processed_text = "".join(
            block.get("text", "") for block in output_blocks if "text" in block
        )
        return processed_text or text

    # ------------------------------------------------------------------
    # invoke_model fallback for non-ARN-versioned model IDs (Module 5)
    # ------------------------------------------------------------------

    async def _invoke_native(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        max_tokens: int = 4096,
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

        body: Dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
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
                TASK-1742).
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
                "BedrockConverseClient.ask(): deep_research/background are "
                "not yet supported; ignoring."
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
                f"{resolved_system_prompt}\n\n{schema_instruction}"
                if resolved_system_prompt else schema_instruction
            )
        elif output_schema:
            # Module 5: schema-in-system-prompt structured output from a raw
            # JSON Schema dict (no Pydantic/dataclass type available).
            schema_instruction = (
                "Respond with valid JSON matching this schema: "
                f"{json.dumps(output_schema)}"
            )
            resolved_system_prompt = (
                f"{resolved_system_prompt}\n\n{schema_instruction}"
                if resolved_system_prompt else schema_instruction
            )

        payload: Dict[str, Any] = {
            "modelId": resolved_model,
            "messages": bedrock_messages,
            "inferenceConfig": {
                "maxTokens": max_tokens if max_tokens is not None else (self.max_tokens or 4096),
                "temperature": temperature if temperature is not None else self.temperature,
            },
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

        while True:
            try:
                result = await self._sdk_create(payload)
            except Exception as e:
                if self._should_use_fallback(payload["modelId"], e):
                    self.logger.warning(
                        "Bedrock model %s capacity error: %s. Retrying with fallback: %s",
                        payload["modelId"], e, self._fallback_model,
                    )
                    payload["modelId"] = self._translate_model(self._fallback_model)
                    used_fallback = True
                    result = await self._sdk_create(payload)
                else:
                    raise

            message = result.get("output", {}).get("message", {})
            content_blocks = message.get("content", [])

            if result.get("stopReason") == "tool_use":
                tool_result_blocks = []

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
                        tool_result_blocks.append({
                            "toolResult": {
                                "toolUseId": tool_id,
                                "content": [{"text": str(tool_result)}],
                            }
                        })
                    except Exception as e:
                        from parrot.core.exceptions import HumanInteractionInterrupt
                        if isinstance(e, HumanInteractionInterrupt):
                            e.session_id = session_id
                            e.messages = bedrock_messages + [
                                {"role": "assistant", "content": content_blocks}
                            ]
                            e.tool_call_id = tool_id
                            e.agent_name = resolved_model
                            raise

                        tc.error = str(e)
                        tool_result_blocks.append({
                            "toolResult": {
                                "toolUseId": tool_id,
                                "content": [{"text": str(e)}],
                                "status": "error",
                            }
                        })

                    all_tool_calls.append(tc)

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
        assistant_response_text = "".join(
            block.get("text", "") for block in content_blocks if "text" in block
        )
        if output_config:
            try:
                if output_config.custom_parser:
                    final_output = await output_config.custom_parser(assistant_response_text)
                else:
                    final_output = await self._parse_structured_output(
                        assistant_response_text, output_config
                    )
            except Exception:
                final_output = assistant_response_text
        elif output_schema:
            final_output = self._parse_json_schema_output(assistant_response_text)

        tools_used = [tc.name for tc in all_tool_calls]
        await self._update_conversation_memory(
            user_id, session_id, conversation_history, bedrock_messages,
            resolved_system_prompt, turn_id, original_prompt,
            assistant_response_text, tools_used,
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
            ai_message.metadata['used_fallback_model'] = True
            ai_message.metadata['original_model'] = resolved_model
            ai_message.metadata['fallback_model'] = self._fallback_model

        _lc_usage = ai_message.usage
        await self._emit_after_call(
            _lc_tc,
            client_name=self.client_name,
            model=resolved_model,
            duration_ms=(time.perf_counter() - _lc_t0) * 1000,
            input_tokens=getattr(_lc_usage, 'input_tokens', None) if _lc_usage else None,
            output_tokens=getattr(_lc_usage, 'output_tokens', None) if _lc_usage else None,
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
        deep_research: bool = False,
        agent_config: Optional[Dict[str, Any]] = None,
        lazy_loading: bool = False,
        thinking_budget: Optional[int] = None,
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
    ) -> AsyncIterator[Union[str, AIMessage]]:
        """Stream a Bedrock Converse response.

        Yields successive ``str`` chunks (mapped from ``contentBlockDelta``
        events), then a single final :class:`AIMessage` sentinel — the same
        streaming convention followed by every other client
        (:meth:`AnthropicClient.ask_stream`, etc.).

        Args:
            thinking_budget: See :meth:`ask` — enables extended thinking via
                ``additionalModelRequestFields.thinking`` (Module 5).
            guardrail_id: Per-call guardrail identifier override. Falls back
                to the identifier passed to ``__init__``.
            guardrail_version: Per-call guardrail version override. Falls
                back to the version passed to ``__init__``.

        Note:
            Tool-use is not resumed mid-stream in this Core implementation —
            if the model requests a tool during streaming, the tool-use
            content block is still yielded as text-less, and the final
            ``AIMessage`` carries ``stop_reason="tool_use"`` with no
            tool_calls populated. Full streaming tool-use loops are deferred
            to a future iteration; ``ask()`` should be used when tool-use is
            required.
        """
        await self._ensure_client()

        resolved_model = self._translate_model(model)
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        if deep_research:
            self.logger.warning(
                "BedrockConverseClient.ask_stream(): deep_research is not "
                "yet supported; ignoring."
            )
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
            "inferenceConfig": {
                "maxTokens": max_tokens if max_tokens is not None else (self.max_tokens or 4096),
                "temperature": temperature if temperature is not None else self.temperature,
            },
        }
        if resolved_system_prompt:
            payload["system"] = [{"text": resolved_system_prompt}]

        if thinking_budget:
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

        if self.enable_tools:
            tool_specs = self._prepare_tools()
            if tool_specs:
                payload["toolConfig"] = {"tools": tool_specs}

        accumulated_text = ""
        stop_reason: Optional[str] = None
        usage_dict: Dict[str, Any] = {}

        stream = await self._sdk_stream(payload)
        async for event in stream:
            delta = event.get("contentBlockDelta", {}).get("delta", {})
            text_chunk = delta.get("text")
            if text_chunk:
                accumulated_text += text_chunk
                yield text_chunk
            if "messageStop" in event:
                stop_reason = event["messageStop"].get("stopReason")
            if "metadata" in event:
                usage_dict = event["metadata"].get("usage", {})

        bedrock_messages.append(
            {"role": "assistant", "content": [{"text": accumulated_text}]}
        )
        await self._update_conversation_memory(
            user_id, session_id, conversation_history, bedrock_messages,
            resolved_system_prompt, turn_id, original_prompt,
            accumulated_text, [],
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
        )

    async def resume(
        self,
        session_id: str,
        user_input: str,
        state: Dict[str, Any]
    ) -> AIMessage:
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
        resolved_model = self._translate_model(
            state.get("agent_name", self.model or self.default_model)
        )

        bedrock_messages.append({
            "role": "user",
            "content": [{
                "toolResult": {
                    "toolUseId": tool_call_id,
                    "content": [{"text": user_input}],
                }
            }]
        })

        all_tool_calls: List[ToolCall] = []
        turn_id = str(uuid.uuid4())

        payload: Dict[str, Any] = {
            "modelId": resolved_model,
            "messages": bedrock_messages,
            "inferenceConfig": {
                "maxTokens": self.max_tokens or 4096,
                "temperature": self.temperature,
            },
        }
        tool_specs = self._prepare_tools()
        if tool_specs:
            payload["toolConfig"] = {"tools": tool_specs}

        result: Dict[str, Any] = {}
        content_blocks: List[Dict[str, Any]] = []

        while True:
            result = await self._sdk_create(payload)
            message = result.get("output", {}).get("message", {})
            content_blocks = message.get("content", [])

            if result.get("stopReason") == "tool_use":
                tool_result_blocks = []

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
                        tool_result_blocks.append({
                            "toolResult": {
                                "toolUseId": tool_id,
                                "content": [{"text": str(tool_result)}],
                            }
                        })
                    except Exception as e:
                        from parrot.core.exceptions import HumanInteractionInterrupt
                        if isinstance(e, HumanInteractionInterrupt):
                            e.session_id = session_id
                            e.messages = bedrock_messages + [
                                {"role": "assistant", "content": content_blocks}
                            ]
                            e.tool_call_id = tool_id
                            e.agent_name = resolved_model
                            raise

                        tc.error = str(e)
                        tool_result_blocks.append({
                            "toolResult": {
                                "toolUseId": tool_id,
                                "content": [{"text": str(e)}],
                                "status": "error",
                            }
                        })

                    all_tool_calls.append(tc)

                bedrock_messages.append({"role": "assistant", "content": content_blocks})
                bedrock_messages.append({"role": "user", "content": tool_result_blocks})
                payload["messages"] = bedrock_messages
            else:
                bedrock_messages.append({"role": "assistant", "content": content_blocks})
                break

        return AIMessageFactory.from_bedrock(
            response=result,
            input_text="[Resumed Conversation]",
            model=resolved_model,
            session_id=session_id,
            turn_id=turn_id,
            tool_calls=all_tool_calls,
        )

    async def invoke(
        self,
        prompt: str,
        *,
        output_type: Optional[type] = None,
        structured_output: Optional[StructuredOutputConfig] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
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

            if config:
                resolved_prompt += "\n\n" + config.format_schema_instruction()

            payload: Dict[str, Any] = {
                "modelId": resolved_model,
                "messages": [{"role": "user", "content": [{"text": prompt}]}],
                "system": [{"text": resolved_prompt}],
                "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
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
