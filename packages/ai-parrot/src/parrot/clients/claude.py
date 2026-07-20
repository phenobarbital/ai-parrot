from __future__ import annotations
import asyncio
from typing import AsyncIterator, Dict, List, Literal, Optional, Union, Any, TYPE_CHECKING
from typing import List as TypingList
import base64
import io
import time
from enum import Enum
import uuid
import logging
from pathlib import Path
import mimetypes
from pydantic import BaseModel, Field
from navconfig import config
# from datamodel.exceptions import ParserError  # pylint: disable=E0611 # noqa
from datamodel.parsers.json import json_decoder  # pylint: disable=E0611 # noqa
from .base import AbstractClient, BatchRequest, StreamingRetryConfig
# FEAT-176: lifecycle events
from parrot.core.events.lifecycle.events import (
    ClientStreamChunkEvent,
    PromptCacheAppliedEvent,
    PromptCacheSkippedEvent,
)
# FEAT-232: AWS / Bedrock conf constants
from ..conf import (
    AWS_ACCESS_KEY,
    AWS_SECRET_KEY,
    AWS_REGION_NAME,
    AWS_SESSION_TOKEN,
    ANTHROPIC_AWS_WORKSPACE_ID,
    BEDROCK_AWS_REGION,
)

if TYPE_CHECKING:
    # Type-check-only imports — keep IDE/mypy support without forcing the
    # SDKs to be installed at runtime when this client is unused.
    from anthropic import AsyncAnthropic, AsyncAnthropicBedrock, AsyncAnthropicAWS
    from parrot.clients.anthropic_backends import AnthropicBackendProtocol
    from PIL import Image
from ..models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    OutputFormat,
    StructuredOutputConfig,
    CompletionUsage,
    ObjectDetectionResult
)
from ..models.responses import InvokeResult
from ..exceptions import InvokeError
from ..models.claude import ClaudeModel
from ..models.outputs import (
    SentimentAnalysis,
    ProductReview
)

logging.getLogger("anthropic").setLevel(logging.WARNING)
# Silence the underlying HTTP stack used by the Anthropic SDK; its DEBUG
# traces (connect_tcp/start_tls) are pure noise for callers of this client.
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# FEAT-232: backend selector type alias.
AnthropicBackend = Literal["direct", "bedrock", "aws"]


class AnthropicClient(AbstractClient):
    """Client for interacting with the Anthropic API using the official SDK."""
    version: str = "2023-06-01"
    client_type: str = "anthropic"
    client_name: str = "claude"
    use_session: bool = False
    _default_model: str = 'claude-sonnet-4-5'
    _fallback_model: str = 'claude-sonnet-4.5'
    _lightweight_model: str = "claude-haiku-4-5-20251001"
    # FEAT-181: Anthropic caches system prefixes ≥ 1024 tokens.
    _min_cache_tokens: int = 1024

    def __init__(
        self,
        api_key: str = None,
        base_url: str = "https://api.anthropic.com",
        backend: AnthropicBackend = "direct",
        aws_access_key: Optional[str] = None,
        aws_secret_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        aws_region: Optional[str] = None,
        workspace_id: Optional[str] = None,
        aws_profile: Optional[str] = None,
        region_prefix: Optional[str] = None,
        **kwargs
    ):
        """Initialise an Anthropic client.

        Args:
            api_key: Anthropic API key (direct backend only).  Defaults to the
                ``ANTHROPIC_API_KEY`` navconfig / env value.
            base_url: Base URL for the direct Anthropic API.
            backend: Transport backend — ``"direct"`` (default), ``"bedrock"``,
                or ``"aws"``.
            aws_access_key: AWS access key ID.  Resolved: kwarg → conf/env → None
                (SDK chain).
            aws_secret_key: AWS secret access key.  Same resolution order.
            aws_session_token: Optional STS session token.  Same resolution order.
            aws_region: AWS region (e.g. ``"us-east-1"``).  For the ``bedrock``
                backend, prefers the Bedrock-specific ``BEDROCK_AWS_REGION`` env
                var over the general ``AWS_REGION_NAME`` to avoid region
                pollution from other services.
            workspace_id: Claude-on-AWS workspace ID (``aws`` backend only;
                **mandatory** for that backend — the SDK raises at construction
                without it).  Env/conf constant: ``ANTHROPIC_AWS_WORKSPACE_ID``.
            aws_profile: Optional AWS named profile.  Passed through to the SDK
                as-is; ``None`` → omitted.
            region_prefix: Cross-region inference-profile prefix for the
                ``bedrock`` backend (e.g. ``"us"``, ``"eu"``, ``"apac"``).
                When provided, model IDs are translated to
                ``"<prefix>.anthropic.<id>-vN:0"`` form.  ``None`` → no prefix.
            **kwargs: Forwarded to :class:`~parrot.clients.base.AbstractClient`.
        """
        self.api_key = api_key or config.get('ANTHROPIC_API_KEY')
        self.base_url = base_url
        self.backend: AnthropicBackend = backend
        self._backend_name: str = backend

        # ── FEAT-232: credential resolution — kwarg → parrot.conf/env → None ─
        # parrot.conf constants already back-fall to env vars via navconfig,
        # so we only need one fallback level here.
        _access_key = aws_access_key or AWS_ACCESS_KEY
        _secret_key = aws_secret_key or AWS_SECRET_KEY
        _session_token = aws_session_token or AWS_SESSION_TOKEN
        # FIX-4: for Bedrock, prefer the Bedrock-specific region env var so that
        # a general AWS_REGION_NAME set for other services (e.g. DynamoDB in
        # eu-west-1) does not silently override the intended Bedrock region.
        # Resolution order: explicit kwarg → BEDROCK_AWS_REGION → None (boto3 chain).
        _bedrock_region = aws_region or BEDROCK_AWS_REGION
        # For the aws-workspace backend keep using the general AWS_REGION_NAME fallback.
        _region = aws_region or AWS_REGION_NAME
        _workspace_id = workspace_id or ANTHROPIC_AWS_WORKSPACE_ID

        # ── Instantiate the matching backend strategy ─────────────────────────
        from .anthropic_backends import DirectBackend, BedrockBackend, AWSWorkspaceBackend
        if backend == "bedrock":
            self._backend: "AnthropicBackendProtocol" = BedrockBackend(
                aws_region=_bedrock_region,
                aws_access_key=_access_key,
                aws_secret_key=_secret_key,
                aws_session_token=_session_token,
                region_prefix=region_prefix,
            )
        elif backend == "aws":
            self._backend = AWSWorkspaceBackend(
                aws_region=_region,
                workspace_id=_workspace_id,
                aws_access_key=_access_key,
                aws_secret_key=_secret_key,
                aws_session_token=_session_token,
                aws_profile=aws_profile,
            )
        else:
            self._backend = DirectBackend(api_key=self.api_key)

        # NOTE: no self.client = None — base class owns the per-loop cache as a property.
        # FIX-3: x-api-key is only meaningful for the direct backend; Bedrock/AWS
        # backends authenticate via SigV4 / SDK chain — sending "None" as a header
        # value would be both incorrect and potentially confusing.
        self.base_headers = {
            "Content-Type": "application/json",
            "anthropic-version": self.version,
        }
        if self._backend_name == "direct" and self.api_key:
            self.base_headers["x-api-key"] = self.api_key
        super().__init__(**kwargs)

    # FEAT-232 observability: map the active backend to the ``client_name`` carried
    # on lifecycle events, which ``resolve_gen_ai_system`` turns into the OTel
    # ``gen_ai.provider.name`` / ``gen_ai.system`` value (see
    # observability/attributes.py::PROVIDER_TO_GEN_AI_SYSTEM). Bedrock-served
    # Claude is a distinct provider in OpenLIT (``aws.bedrock``); the direct and
    # aws-workspace backends are both the Anthropic API (``anthropic``).
    _BACKEND_TELEMETRY_NAME: dict[str, str] = {
        "direct": "anthropic",
        "bedrock": "anthropic-bedrock",
        "aws": "anthropic",
    }

    @property
    def _telemetry_client_name(self) -> str:
        """Return the ``client_name`` for telemetry events given the active backend."""
        return self._BACKEND_TELEMETRY_NAME.get(self._backend_name, "anthropic")

    async def get_client(self) -> "Union[AsyncAnthropic, AsyncAnthropicBedrock, AsyncAnthropicAWS]":
        """Build and return the appropriate SDK client for the active backend.

        Delegates to the backend strategy object's ``build_client()`` method.
        On ``backend="direct"`` this is byte-for-byte equivalent to the
        pre-FEAT-232 behaviour (``AsyncAnthropic(api_key=…, max_retries=2)``).

        Returns:
            An ``AsyncAnthropic``, ``AsyncAnthropicBedrock``, or
            ``AsyncAnthropicAWS`` instance depending on ``self.backend``.

        Raises:
            ImportError: When the required SDK extra is not installed.
            ValueError: When mandatory fields for the ``"aws"`` backend are
                missing (``aws_region`` / ``workspace_id``).
        """
        return await self._backend.build_client()

    def _resolve_model(self, model) -> str:
        """Resolve and translate a model argument for the active backend.

        Applies the same ``model.value if isinstance(model, ClaudeModel)``
        normalisation that all call sites used inline, then feeds the result
        through ``self._backend.translate_model()`` so Bedrock IDs are applied
        uniformly at every model-resolution site.

        Args:
            model: A model identifier — a :class:`~parrot.models.claude.ClaudeModel`
                enum member, a plain string, or ``None``.  ``None`` / falsy
                values fall back to ``self.model`` then ``self.default_model``.

        Returns:
            A resolved, backend-translated model ID string.
        """
        raw = (model.value if isinstance(model, ClaudeModel) else model) or (
            self.model or self.default_model
        )
        return self._backend.translate_model(raw)

    def _is_capacity_error(self, error: Exception) -> bool:
        """Detect Anthropic capacity errors using SDK exception types."""
        from anthropic import RateLimitError, APIStatusError
        if isinstance(error, RateLimitError):
            return True
        if isinstance(error, APIStatusError) and error.status_code in (429, 503, 529):
            return True
        return super()._is_capacity_error(error)

    # ── Model-capability guards ─────────────────────────────────────────────
    # Adaptive-thinking-only models removed the legacy sampling parameters
    # (``temperature`` / ``top_p`` / ``top_k``); sending any returns a 400.
    # Fable 5 additionally rejects an explicit ``thinking={"type":"disabled"}``
    # — the param must be omitted entirely. Mirrors the guard pattern in
    # ``GoogleGenAIClient._requires_thinking``.
    _ADAPTIVE_ONLY_PREFIXES: tuple = (
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
    )

    @staticmethod
    def _model_str(model) -> str:
        """Normalise a model identifier (str / ``ClaudeModel`` / None) to a str."""
        if isinstance(model, ClaudeModel):
            return model.value
        return model or ""

    @classmethod
    def _rejects_sampling_params(cls, model) -> bool:
        """Whether the model 400s on ``temperature`` / ``top_p`` / ``top_k``.

        True for adaptive-thinking-only models (Fable 5, Opus 4.7, Opus 4.8),
        which removed the sampling parameters.
        """
        m = cls._model_str(model)
        return any(m.startswith(p) for p in cls._ADAPTIVE_ONLY_PREFIXES)

    @classmethod
    def _rejects_explicit_thinking_disabled(cls, model) -> bool:
        """Whether an explicit ``thinking={"type": "disabled"}`` returns a 400.

        Only Fable 5 rejects it (Opus 4.7/4.8 still accept ``disabled``); for
        Fable 5 the ``thinking`` param must be omitted entirely instead.
        """
        return cls._model_str(model).startswith("claude-fable-5")

    def _sanitize_payload_for_model(self, payload: dict) -> dict:
        """Drop request params the target model rejects with a 400.

        - Adaptive-only models (Fable 5, Opus 4.7/4.8): remove
          ``temperature`` / ``top_p`` / ``top_k``.
        - Fable 5: drop an explicit ``thinking={"type": "disabled"}`` (must be
          omitted, not sent).

        Applied just before every ``messages.create`` / ``messages.stream``
        call so all payload-building paths are covered uniformly. Mutates and
        returns ``payload``.
        """
        model = payload.get("model", "")
        if self._rejects_sampling_params(model):
            for param in ("temperature", "top_p", "top_k"):
                if payload.pop(param, None) is not None:
                    self.logger.debug(
                        "AnthropicClient: dropped '%s' — %s is adaptive-only "
                        "and rejects sampling params.", param, model,
                    )
        thinking = payload.get("thinking")
        if (
            isinstance(thinking, dict)
            and thinking.get("type") == "disabled"
            and self._rejects_explicit_thinking_disabled(model)
        ):
            payload.pop("thinking", None)
            self.logger.debug(
                "AnthropicClient: dropped thinking={type:disabled} — %s "
                "requires the 'thinking' param omitted.", model,
            )
        return payload

    async def _sdk_create(self, payload: dict):
        """Sanitize then dispatch a non-streaming ``messages.create`` call."""
        return await self.client.messages.create(
            **self._sanitize_payload_for_model(payload)
        )

    def _sdk_stream(self, payload: dict):
        """Sanitize then return a streaming ``messages.stream`` context manager."""
        return self.client.messages.stream(
            **self._sanitize_payload_for_model(payload)
        )

    # ── FEAT-181: Prompt Caching ───────────────────────────────────────────

    def _segments_to_anthropic_blocks(self, segments: list) -> list:
        """Convert CacheableSegments to Anthropic system content blocks.

        Anthropic requires the ``system`` field to be a list of content blocks
        when using ``cache_control``. This method translates segments into
        that format, respecting the 4-block hard limit.

        Args:
            segments: List of
                :class:`~parrot.bots.prompts.segments.CacheableSegment` objects.

        Returns:
            List of ``{"type": "text", "text": ...}`` dicts, with
            ``"cache_control": {"type": "ephemeral"}`` on cacheable blocks
            up to the 4-block limit.
        """
        MAX_CACHE_BLOCKS = 4
        blocks = []
        cacheable_count = 0
        for seg in segments:
            block: dict = {"type": "text", "text": seg.text}
            if seg.cacheable and cacheable_count < MAX_CACHE_BLOCKS:
                block["cache_control"] = {"type": "ephemeral"}
                cacheable_count += 1
            elif seg.cacheable and cacheable_count >= MAX_CACHE_BLOCKS:
                self.logger.debug(
                    "AnthropicClient: max 4 cache_control blocks reached; "
                    "segment dropped from cache: %.40s...", seg.text
                )
            blocks.append(block)
        return blocks

    def _apply_cache_hints(
        self,
        payload: dict,
        segments: list,
        trace_context=None,
    ) -> dict:
        """Apply Anthropic cache_control blocks to the payload system prompt.

        FEAT-181 — overrides AbstractClient no-op.

        Args:
            payload: The request payload dict.
            segments: List of
                :class:`~parrot.bots.prompts.segments.CacheableSegment` objects.
            trace_context: Optional W3C trace context for event correlation.
                When ``None``, a new root trace is created for the event.

        Returns:
            The payload with ``system`` replaced by a list of content blocks
            when segments are present; unchanged otherwise.
        """
        import hashlib as _hashlib
        from parrot.core.events.lifecycle import TraceContext as _TC
        tc = trace_context if trace_context is not None else _TC.new_root()
        if not segments:
            self.events.emit_nowait(PromptCacheSkippedEvent(
                trace_context=tc,
                client_name=self._telemetry_client_name,
                model=payload.get("model", ""),
                reason="no_segments",
                source_type="client",
                source_name="anthropic",
            ))
            return payload
        blocks = self._segments_to_anthropic_blocks(segments)
        payload["system"] = blocks
        # Emit cache-applied event (fire-and-forget)
        cacheable_segs = [s for s in segments if s.cacheable]
        seg_hashes = tuple(
            _hashlib.sha256(s.text.encode()).hexdigest() for s in cacheable_segs
        )
        est_tokens = sum(len(s.text) // 4 for s in cacheable_segs)
        self.events.emit_nowait(PromptCacheAppliedEvent(
            trace_context=tc,
            client_name=self._telemetry_client_name,
            model=payload.get("model", ""),
            blocks_marked=sum(
                1 for b in blocks if isinstance(b, dict) and "cache_control" in b
            ),
            est_tokens=est_tokens,
            segment_hashes=seg_hashes,
            source_type="client",
            source_name="anthropic",
        ))
        return payload

    async def ask(
        self,
        prompt: str,
        model: Union[Enum, str] = None,
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
        context_1m: bool = False,
    ) -> AIMessage:
        """Ask Claude a question with optional conversation memory.

        Args:
            use_tools: If None, uses instance default. If True/False, overrides for this call.
            deep_research: If True, use enhanced system prompt for thorough research
            background: If True, execute research in background mode (not yet supported)
            lazy_loading: If True, enable dynamic tool searching
        """
        await self._ensure_client()

        # If use_tools is None, use the instance default
        _use_tools = use_tools if use_tools is not None else self.enable_tools

        # For deep research, automatically enable tools
        if deep_research:
            _use_tools = True
            self.logger.info("Deep research mode enabled: activating enhanced research prompt and tools")

        model = self._resolve_model(model)
        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        messages, conversation_history, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        # FEAT-176: lifecycle event — BeforeClientCallEvent
        import time as _lc_time
        _lc_tc = self._emit_before_call(
            client_name=self._telemetry_client_name,
            model=model,
            temperature=temperature if temperature is not None else self.temperature,
            system_prompt=self._resolve_system_prompt(system_prompt),
            has_tools=bool(_use_tools),
            parent_trace=None,
        )
        _lc_t0 = _lc_time.perf_counter()

        # Enhance system prompt for deep research mode
        if deep_research:
            research_prompt = self._get_deep_research_system_prompt()
            # FEAT-181: guard against List[CacheableSegment] + string concatenation
            _sp = self._resolve_system_prompt(system_prompt) if isinstance(system_prompt, list) else system_prompt
            system_prompt = f"{_sp}\n\n{research_prompt}" if _sp else research_prompt

        # Lazy loading system prompt
        if lazy_loading:
            search_prompt = "You have access to a library of tools. Use the 'search_tools' function to find relevant tools."
            # FEAT-181: guard against List[CacheableSegment] + string concatenation
            _sp = self._resolve_system_prompt(system_prompt) if isinstance(system_prompt, list) else system_prompt
            system_prompt = f"{_sp}\n\n{search_prompt}" if _sp else search_prompt

        output_config = self._get_structured_config(
            structured_output
        )

        if structured_output:
            schema_instruction = output_config.format_schema_instruction()
            # FEAT-181: guard against List[CacheableSegment] + string concatenation
            _sp = self._resolve_system_prompt(system_prompt) if isinstance(system_prompt, list) else system_prompt
            system_prompt = f"{_sp}\n\n{schema_instruction}" if _sp else schema_instruction

        # Anthropic SDK requires max_tokens to be a non-None int;
        # _calculate_nonstreaming_timeout() does `int * max_tokens`.
        _max_tokens = max_tokens if max_tokens is not None else (self.max_tokens or 16000)
        payload = {
            "model": model,
            "max_tokens": _max_tokens,
            "temperature": temperature or self.temperature,
            "messages": messages
        }

        if system_prompt:
            if isinstance(system_prompt, list):
                # FEAT-181: List of CacheableSegments — translate to cache blocks.
                payload = self._apply_cache_hints(payload, system_prompt)
            else:
                payload["system"] = system_prompt

        if context_1m:
            payload["betas"] = ["context-1m-2025-08-07"]

        if _use_tools and (tools and isinstance(tools, list)):
            for tool in tools:
                self.register_tool(tool)

        # LAZY LOADING LOGIC
        active_tool_names = set()
        
        if _use_tools:
            if lazy_loading:
                 prepared = self._prepare_lazy_tools()
                 if prepared:
                     payload["tools"] = prepared
                     active_tool_names.add("search_tools")
            else:
                 payload["tools"] = self._prepare_tools()

        # Track tool calls for the response
        all_tool_calls = []
        used_fallback = False

        # Handle tool calls in a loop
        while True:
            # Use the Anthropic SDK to create messages
            try:
                response = await self._sdk_create(payload)
            except Exception as e:
                if self._should_use_fallback(payload["model"], e):
                    self.logger.warning(
                        "Model %s capacity error: %s. Retrying with fallback: %s",
                        payload["model"], e, self._fallback_model
                    )
                    payload["model"] = self._backend.translate_model(self._fallback_model)
                    used_fallback = True
                    response = await self._sdk_create(payload)
                else:
                    raise
            # Convert Message object to dict for compatibility
            result = response.model_dump()

            # Check if Claude wants to use a tool
            if result.get("stop_reason") == "tool_use":
                tool_results = []
                found_new_tools = False

                for content_block in result["content"]:
                    if content_block["type"] == "tool_use":
                        tool_name = content_block["name"]
                        tool_input = content_block["input"]
                        tool_id = content_block["id"]

                        # Create ToolCall object and execute
                        tc = ToolCall(
                            id=tool_id,
                            name=tool_name,
                            arguments=tool_input
                        )

                        try:
                            start_time = time.time()
                            tool_result = await self._execute_tool(tool_name, tool_input)
                            execution_time = time.time() - start_time

                            # Lazy Loading Check
                            if lazy_loading and tool_name == "search_tools":
                                 new_tools = self._check_new_tools(tool_name, str(tool_result))
                                 if new_tools:
                                     for nt in new_tools:
                                         if nt not in active_tool_names:
                                             active_tool_names.add(nt)
                                             found_new_tools = True

                            tc.result = tool_result
                            tc.execution_time = execution_time

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": str(tool_result)
                            })
                        except Exception as e:
                            from parrot.core.exceptions import HumanInteractionInterrupt
                            if isinstance(e, HumanInteractionInterrupt):
                                e.session_id = session_id
                                # We MUST append the assistant's tool-use message so it is in the history when resuming
                                e.messages = messages + [{"role": "assistant", "content": result["content"]}]
                                e.tool_call_id = tool_id
                                e.agent_name = model
                                raise

                            tc.error = str(e)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "is_error": True,
                                "content": str(e)
                            })

                        all_tool_calls.append(tc)

                # Update available tools if new ones found
                if lazy_loading and found_new_tools:
                     payload["tools"] = self._prepare_tools(filter_names=list(active_tool_names))

                # Add tool results and continue conversation
                messages.append({"role": "assistant", "content": result["content"]})
                messages.append({"role": "user", "content": tool_results})
                payload["messages"] = messages
            else:
                # No more tool calls, assistant response final
                messages.append({"role": "assistant", "content": result["content"]})
                break

        # Handle structured output
        final_output = None
        if structured_output:
            # Extract text content from Claude's response
            text_content = "".join(
                content_block["text"]
                for content_block in result["content"]
                if content_block["type"] == "text"
            )
            try:
                if output_config.custom_parser:
                    final_output = await output_config.custom_parser(
                        text_content
                    )
                final_output = await self._parse_structured_output(
                    text_content,
                    output_config
                )
            except Exception:
                final_output = text_content

        # Extract assistant response text for conversation memory
        assistant_response_text = "".join(
            content_block.get("text", "")
            for content_block in result.get("content", [])
            if content_block.get("type") == "text"
        )

        # Update conversation memory with unified system
        tools_used = [tc.name for tc in all_tool_calls]
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_history,
            messages,
            system_prompt,
            turn_id,
            original_prompt,
            assistant_response_text,
            tools_used
        )

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_claude(
            response=result,
            input_text=original_prompt,
            model=payload["model"] if used_fallback else model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output,
            tool_calls=all_tool_calls
        )

        # Add fallback metadata if fallback was used
        if used_fallback:
            if not hasattr(ai_message, 'metadata') or ai_message.metadata is None:
                ai_message.metadata = {}
            ai_message.metadata['used_fallback_model'] = True
            ai_message.metadata['original_model'] = model
            ai_message.metadata['fallback_model'] = self._fallback_model

        # FEAT-176: lifecycle event — AfterClientCallEvent
        _lc_usage = getattr(ai_message, 'usage', None)
        await self._emit_after_call(
            _lc_tc,
            client_name=self._telemetry_client_name,
            model=model,
            duration_ms=(_lc_time.perf_counter() - _lc_t0) * 1000,
            input_tokens=getattr(_lc_usage, 'input_tokens', None) if _lc_usage else None,
            output_tokens=getattr(_lc_usage, 'output_tokens', None) if _lc_usage else None,
            finish_reason=getattr(ai_message, 'stop_reason', None),
        )
        return ai_message

    async def resume(
        self,
        session_id: str,
        user_input: str,
        state: Dict[str, Any]
    ) -> AIMessage:
        """Resume a suspended model execution.
        
        Args:
            session_id: The session ID
            user_input: The user's input to inject as tool result
            state: The suspended state containing messages and tool_call_id
            
        Returns:
            AIMessage: The response from the LLM
        """
        await self._ensure_client()

        messages = state["messages"]
        tool_call_id = state["tool_call_id"]
        # Preserve agent_name semantics; translate result through backend.
        model = self._backend.translate_model(
            state.get("agent_name", self.model or self.default_model)
        )

        # Inject user input as tool result
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": user_input
            }]
        })

        # Track tools used in this continuation
        all_tool_calls = []
        turn_id = str(uuid.uuid4())
        
        payload = {
            "model": model,
            "max_tokens": self.max_tokens or 4096,
            "temperature": self.temperature,
            "messages": messages,
            "tools": self._prepare_tools()
        }

        # Handle tool calls in a loop
        while True:
            response = await self._sdk_create(payload)
            result = response.model_dump()

            if result.get("stop_reason") == "tool_use":
                tool_results = []

                for content_block in result["content"]:
                    if content_block["type"] == "tool_use":
                        tool_name = content_block["name"]
                        tool_input = content_block["input"]
                        tool_id = content_block["id"]

                        tc = ToolCall(id=tool_id, name=tool_name, arguments=tool_input)

                        try:
                            start_time = time.time()
                            tool_result = await self._execute_tool(tool_name, tool_input)
                            tc.result = tool_result
                            tc.execution_time = time.time() - start_time

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": str(tool_result)
                            })
                        except Exception as e:
                            from parrot.core.exceptions import HumanInteractionInterrupt
                            if isinstance(e, HumanInteractionInterrupt):
                                e.session_id = session_id
                                e.messages = messages + [{"role": "assistant", "content": result["content"]}]
                                e.tool_call_id = tool_id
                                e.agent_name = model
                                raise

                            tc.error = str(e)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "is_error": True,
                                "content": str(e)
                            })

                        all_tool_calls.append(tc)

                messages.append({"role": "assistant", "content": result["content"]})
                messages.append({"role": "user", "content": tool_results})
                payload["messages"] = messages
            else:
                messages.append({"role": "assistant", "content": result["content"]})
                break

        return AIMessageFactory.from_claude(
            response=result,
            input_text="[Resumed Conversation]",
            model=model,
            user_id="unknown",
            session_id=session_id,
            turn_id=turn_id,
            tool_calls=all_tool_calls
        )

    async def ask_stream(
        self,
        prompt: str,
        model: Union[ClaudeModel, str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        retry_config: Optional[StreamingRetryConfig] = None,
        on_max_tokens: Optional[str] = "retry",  # "retry", "notify", "ignore"
        tools: Optional[List[Dict[str, Any]]] = None,
        deep_research: bool = False,
        agent_config: Optional[Dict[str, Any]] = None,
        lazy_loading: bool = False,
        context_1m: bool = False,
    ) -> AsyncIterator[Union[str, AIMessage]]:
        """Stream Claude's response using AsyncIterator with optional conversation memory.

        Yields successive string chunks of the response followed by a single
        final :class:`~parrot.models.responses.AIMessage` with full metadata
        (usage, stop_reason, model, turn_id).

        Args:
            deep_research: If True, use enhanced system prompt for thorough research
            agent_config: Optional configuration (not used, for interface compatibility)
        """
        await self._ensure_client()

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        # Default retry configuration
        if retry_config is None:
            retry_config = StreamingRetryConfig()

        messages, conversation_history, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        # Enhance system prompt for deep research mode
        if deep_research:
            research_prompt = self._get_deep_research_system_prompt()
            # FEAT-181: guard against List[CacheableSegment] + string concatenation
            _sp = self._resolve_system_prompt(system_prompt) if isinstance(system_prompt, list) else system_prompt
            system_prompt = f"{_sp}\n\n{research_prompt}" if _sp else research_prompt
            self.logger.info("Deep research mode enabled for streaming")

        # FIX-5: resolve model BEFORE computing _lc_model_s so that lifecycle
        # events log the actual Bedrock ID sent to the API, not the public alias.
        model = self._resolve_model(model)

        # FEAT-176: lifecycle event — BeforeClientCallEvent for stream
        import time as _lc_time_s
        _lc_model_s = model  # already resolved via _resolve_model above
        _lc_tc_s = self._emit_before_call(
            client_name=self._telemetry_client_name,
            model=_lc_model_s or "",
            temperature=temperature if temperature is not None else self.temperature,
            system_prompt=self._resolve_system_prompt(system_prompt),
            has_tools=False,
            parent_trace=None,
        )
        _lc_t0_s = _lc_time_s.perf_counter()
        _lc_has_chunk_subs = self.events.has_subscribers(ClientStreamChunkEvent)
        _lc_chunk_idx = 0

        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)

        # Ensure max_tokens is never None (SDK multiplies it for timeout calc)
        current_max_tokens = max_tokens if max_tokens is not None else (self.max_tokens or 16000)
        retry_count = 0
        assistant_content = ""
        final_message = None
        while retry_count <= retry_config.max_retries:
            try:
                payload = {
                    "model": model,
                    "max_tokens": current_max_tokens,
                    "temperature": temperature or self.temperature,
                    "messages": messages
                }

                if system_prompt:
                    if isinstance(system_prompt, list):
                        # FEAT-181: List of CacheableSegments — translate to cache blocks.
                        payload = self._apply_cache_hints(payload, system_prompt)
                    else:
                        payload["system"] = system_prompt

                if context_1m:
                    payload["betas"] = ["context-1m-2025-08-07"]

                payload["tools"] = self._prepare_tools()

                assistant_content = ""
                max_tokens_reached = False
                stop_reason = None

                try:
                    # Use the Anthropic SDK's streaming API
                    async with self._sdk_stream(payload) as stream:
                        async for text in stream.text_stream:
                            assistant_content += text
                            # FEAT-176: per-chunk event (short-circuited when no subscribers)
                            if _lc_has_chunk_subs:
                                await self.events.emit(ClientStreamChunkEvent(
                                    trace_context=_lc_tc_s,
                                    client_name=self._telemetry_client_name,
                                    model=_lc_model_s or "",
                                    chunk_index=_lc_chunk_idx,
                                    chunk_size_bytes=len(text.encode("utf-8")),
                                    source_type="client",
                                    source_name="anthropic",
                                ))
                                _lc_chunk_idx += 1
                            yield text

                        # Get the final message to check stop reason
                        final_message = await stream.get_final_message()
                        stop_reason = final_message.stop_reason
                        if stop_reason == 'max_tokens':
                            max_tokens_reached = True

                except Exception as e:
                    # Handle rate limits and server errors
                    error_str = str(e).lower()
                    if '429' in error_str or 'rate limit' in error_str:
                        if retry_config.retry_on_rate_limit and retry_count < retry_config.max_retries:
                            yield f"\n\n⚠️ **Rate limited (attempt {retry_count + 1}). Retrying...**\n\n"
                            retry_count += 1
                            await self._wait_with_backoff(retry_count, retry_config)
                            continue
                        else:
                            yield "\n\n❌ **Rate limit exceeded. Max retries reached.**\n"
                            break
                    elif '5' in error_str[:3]:  # 5xx errors
                        if retry_config.retry_on_server_error and retry_count < retry_config.max_retries:
                            yield f"\n\n⚠️ **Server error (attempt {retry_count + 1}). Retrying...**\n\n"
                            retry_count += 1
                            await self._wait_with_backoff(retry_count, retry_config)
                            continue
                        else:
                            yield "\n\n❌ **Server error. Max retries reached.**\n"
                            break
                    else:
                        raise
                # Check if we reached max tokens
                if max_tokens_reached:
                    if on_max_tokens == "notify":
                        yield f"\n\n⚠️ **Response truncated due to token limit ({current_max_tokens} tokens). The response may be incomplete.**\n"
                    elif on_max_tokens == "retry" and retry_config.auto_retry_on_max_tokens:
                        if retry_count < retry_config.max_retries:
                            # Increase token limit for retry
                            new_max_tokens = int(current_max_tokens * retry_config.token_increase_factor)

                            # Notify user about retry
                            yield f"\n\n🔄 **Response reached token limit ({current_max_tokens}). Retrying with increased limit ({new_max_tokens})...**\n\n"

                            current_max_tokens = new_max_tokens
                            retry_count += 1

                            # Wait before retry
                            await self._wait_with_backoff(retry_count, retry_config)
                            continue
                        else:
                            # Max retries reached
                            yield "\n\n❌ **Maximum retries reached. Response may be incomplete due to token limits.**\n"
                    elif on_max_tokens == "ignore":
                        continue  # Just ignore and yield what we have
                # If we get here, streaming completed successfully
                break
            except Exception as e:
                if retry_count < retry_config.max_retries:
                    error_msg = f"\n\n⚠️ **Streaming error (attempt {retry_count + 1}): {str(e)}. Retrying...**\n\n"
                    yield error_msg

                    retry_count += 1
                    await self._wait_with_backoff(retry_count, retry_config)
                    continue
                else:
                    # Max retries reached, yield error and break
                    yield f"\n\n❌ **Streaming failed after {retry_config.max_retries} retries: {str(e)}**\n"
                    break

        # Yield final AIMessage with full metadata
        if final_message is not None:
            ai_message = AIMessageFactory.from_claude(
                response=final_message.model_dump(),
                input_text=original_prompt,
                model=model,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
            )
        else:
            ai_message = AIMessage(
                input=original_prompt,
                output=assistant_content,
                response=assistant_content,
                model=model,
                provider="claude",
                usage=CompletionUsage(
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                ),
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
            )
        # Update conversation memory BEFORE yielding the final AIMessage so the
        # memory write executes even if the consumer stops iterating after receiving
        # the sentinel (generators are not fully drained once the caller exits the
        # async-for loop).
        if assistant_content:
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_history,
                messages + [{
                    "role": "assistant",
                    "content": [{"type": "text", "text": assistant_content}]
                }],
                system_prompt,
                turn_id,
                original_prompt,
                assistant_content,
                []  # No tools used in streaming
            )

        # FEAT-176: lifecycle event — AfterClientCallEvent for stream
        _lc_stream_usage = getattr(ai_message, 'usage', None)
        await self._emit_after_call(
            _lc_tc_s,
            client_name=self._telemetry_client_name,
            model=_lc_model_s or "",
            duration_ms=(_lc_time_s.perf_counter() - _lc_t0_s) * 1000,
            input_tokens=getattr(_lc_stream_usage, 'input_tokens', None) if _lc_stream_usage else None,
            output_tokens=getattr(_lc_stream_usage, 'output_tokens', None) if _lc_stream_usage else None,
            finish_reason=getattr(ai_message, 'stop_reason', None),
        )
        yield ai_message

    async def batch_ask(self, requests: List[BatchRequest], context_1m: bool = False) -> List[AIMessage]:
        """Process multiple requests in batch."""
        await self._ensure_client()

        # Prepare batch payload in correct format
        batch_payload = {
            "requests": [
                {
                    "custom_id": req.custom_id,
                    "params": self._sanitize_payload_for_model({
                        **req.params,
                        **({"betas": ["context-1m-2025-08-07"]} if context_1m else {})
                    })
                }
                for req in requests
            ]
        }

        # Create batch using SDK
        batch = await self.client.messages.batches.create(**batch_payload)
        batch_id = batch.id

        # Poll for completion
        while True:
            batch_status = await self.client.messages.batches.retrieve(batch_id)

            if batch_status.processing_status == "ended":
                break
            elif batch_status.processing_status in ["failed", "canceled"]:
                raise RuntimeError(f"Batch processing failed: {batch_status}")

            await asyncio.sleep(5)  # Wait 5 seconds before polling again

        # Retrieve results
        results_url = batch_status.results_url
        if results_url:
            # Note: SDK may not have direct results download, so we use session for this
            if not self.session:
                import aiohttp
                async with aiohttp.ClientSession() as temp_session:
                    async with temp_session.get(results_url) as response:
                        response.raise_for_status()
                        results_text = await response.text()
            else:
                async with self.session.get(results_url) as response:
                    response.raise_for_status()
                    results_text = await response.text()

            # Parse JSONL format and convert to AIMessage
            results = []
            for line in results_text.strip().split('\n'):
                if line:
                    batch_result = json_decoder(line)
                    # Extract the response from batch format
                    if 'response' in batch_result and 'body' in batch_result['response']:
                        claude_response = batch_result['response']['body']

                        # Create AIMessage from batch result
                        ai_message = AIMessageFactory.from_claude(
                            response=claude_response,
                            input_text="Batch request",
                            model=claude_response.get('model', 'unknown'),
                            turn_id=str(uuid.uuid4())
                        )
                        results.append(ai_message)
                    else:
                        # Fallback for unexpected format
                        results.append(batch_result)

            return results
        else:
            raise RuntimeError("No results URL provided in batch status")

    def _encode_image_for_claude(
        self,
        image: Union[Path, bytes, "Image.Image"]
    ) -> Dict[str, Any]:
        """Encode image for Claude's vision API."""
        try:
            from PIL import Image
        except ImportError as exc:
            raise ImportError(
                "Image methods on AnthropicClient require Pillow. "
                "Install with: pip install Pillow"
            ) from exc

        if isinstance(image, Path):
            if not image.exists():
                raise FileNotFoundError(f"Image file not found: {image}")

            # Get mime type
            mime_type, _ = mimetypes.guess_type(str(image))
            if not mime_type or not mime_type.startswith('image/'):
                mime_type = "image/jpeg"  # Default fallback

            # Read and encode the file
            with open(image, "rb") as f:
                encoded_data = base64.b64encode(f.read()).decode('utf-8')

        elif isinstance(image, bytes):
            # Handle raw bytes
            mime_type = "image/jpeg"  # Default, could be improved with image format detection
            encoded_data = base64.b64encode(image).decode('utf-8')

        elif isinstance(image, Image.Image):
            # Handle PIL Image object
            buffer = io.BytesIO()
            # Save as JPEG by default (could be made configurable)
            image_format = "JPEG"
            if image.mode in ("RGBA", "LA", "P"):
                # Convert to RGB for JPEG compatibility
                image = image.convert("RGB")

            image.save(buffer, format=image_format)
            encoded_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
            mime_type = f"image/{image_format.lower()}"

        else:
            raise ValueError("Image must be a Path, bytes, or PIL.Image object.")

        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime_type,
                "data": encoded_data
            }
        }

    async def ask_to_image(
        self,
        prompt: str,
        image: Union[Path, bytes, Image.Image],
        reference_images: Optional[List[Union[Path, bytes, Image.Image]]] = None,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        count_objects: bool = False,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        context_1m: bool = False,
    ) -> AIMessage:
        """
        Ask Claude a question about an image with optional conversation memory.

        Args:
            prompt (str): The question or prompt about the image.
            image (Union[Path, bytes, Image.Image]): The primary image to analyze.
            reference_images (Optional[List[Union[Path, bytes, Image.Image]]]):
                Optional reference images.
            model (Union[ClaudeModel, str]): The Claude model to use.
            max_tokens (int): Maximum tokens for the response.
            temperature (float): Sampling temperature.
            structured_output (Union[type, StructuredOutputConfig]):
                Optional structured output format.
            count_objects (bool):
                Whether to count objects in the image (enables default JSON output).
            user_id (Optional[str]): User identifier for conversation memory.
            session_id (Optional[str]): Session identifier for conversation memory.

        Returns:
            AIMessage: The response from Claude about the image.
        """
        await self._ensure_client()

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        # Get conversation history if available
        conversation_history = None
        messages = []

        # Get conversation context (but don't include files since we handle images separately)
        if user_id and session_id and self.conversation_memory:
            chatbot_key = self._get_chatbot_key()
            # Get or create conversation history
            conversation_history = await self.conversation_memory.get_history(
                user_id,
                session_id,
                chatbot_id=chatbot_key
            )
            if not conversation_history:
                conversation_history = await self.conversation_memory.create_history(
                    user_id,
                    session_id,
                    chatbot_id=chatbot_key
                )

            # Get previous conversation messages for context
            # Convert turns to API message format
            messages = conversation_history.get_messages_for_api()

        output_config = self._get_structured_config(
            structured_output
        )

        # Prepare the content for the current message
        content = []

        # Add the primary image first
        primary_image_content = self._encode_image_for_claude(image)
        content.append(primary_image_content)

        # Add reference images if provided
        if reference_images:
            for ref_image in reference_images:
                ref_image_content = self._encode_image_for_claude(ref_image)
                content.append(ref_image_content)

        # Add the text prompt last
        content.append({
            "type": "text",
            "text": prompt
        })

        # Create the new user message with image content
        new_message = {
            "role": "user",
            "content": content
        }

        # Replace the last message (which was just text) with our multimodal message
        if messages and messages[-1]["role"] == "user":
            messages[-1] = new_message
        else:
            messages.append(new_message)

        # Prepare the payload
        payload = {
            "model": self._resolve_model(model),
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature or self.temperature,
            "messages": messages
        }

        if context_1m:
            payload["betas"] = ["context-1m-2025-08-07"]

        # Add system prompt for structured output
        if structured_output:
            structured_system_prompt = "You are a precise assistant that responds only with valid JSON when requested. When asked for structured output, respond with ONLY the JSON object, no additional text, explanations, or markdown formatting."
            if system_prompt:
                if isinstance(system_prompt, list):
                    # FEAT-181: Segments + structured output — append structured hint as non-cacheable block.
                    extra_block = {"type": "text", "text": structured_system_prompt}
                    blocks = self._segments_to_anthropic_blocks(system_prompt)
                    blocks.append(extra_block)
                    payload["system"] = blocks
                else:
                    payload["system"] = f"{system_prompt}\n\n{structured_system_prompt}"
            else:
                payload["system"] = structured_system_prompt
        elif system_prompt:
            if isinstance(system_prompt, list):
                # FEAT-181: List of CacheableSegments — translate to cache blocks.
                payload = self._apply_cache_hints(payload, system_prompt)
            else:
                payload["system"] = system_prompt

        if count_objects and not structured_output:
            # Import ObjectDetectionResult from models
            try:
                structured_output = ObjectDetectionResult
            except ImportError:
                # Fallback - define a simple structure if import fails
                class SimpleObjectDetection(BaseModel):
                    """Simple object detection result structure."""
                    analysis: str = Field(description="Detailed analysis of the image")
                    total_count: int = Field(description="Total number of objects detected")
                    objects: TypingList[str] = Field(
                        default_factory=list,
                        description="List of detected objects"
                    )

                structured_output = SimpleObjectDetection
            output_config = StructuredOutputConfig(
                output_type=structured_output,
                format=OutputFormat.JSON
            )

        # Note: Claude's vision models typically don't support tool calling
        # So we skip tool preparation for vision requests
        # Track tool calls (will likely be empty for vision requests)
        all_tool_calls = []

        # Make the API request using SDK
        response = await self._sdk_create(payload)
        result = response.model_dump()

        # Handle structured output
        final_output = None
        text_content = ""

        # Extract text content from Claude's response
        for content_block in result.get("content", []):
            if content_block.get("type") == "text":
                text_content += content_block.get("text", "")

        if structured_output:
            try:
                final_output = await self._parse_structured_output(
                    text_content,
                    output_config
                )
            except Exception:
                final_output = text_content
        else:
            final_output = text_content

        # Add assistant response to messages for conversation memory
        assistant_message = {"role": "assistant", "content": result["content"]}
        messages.append(assistant_message)

        # Update conversation memory
        tools_used = [tc.name for tc in all_tool_calls]
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_history,
            messages + [{"role": "assistant", "content": result["content"]}],
            system_prompt,
            turn_id,
            f"[Image Analysis]: {original_prompt}",  # Include image context in the stored prompt
            text_content,
            tools_used
        )



        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_claude(
            response=result,
            input_text=f"[Image Analysis]: {original_prompt}",
            model=model.value if isinstance(model, ClaudeModel) else model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output,
            tool_calls=all_tool_calls
        )

        # Ensure text field is properly set for property access
        if not structured_output:
            ai_message.response = final_output

        return ai_message

    async def summarize_text(
        self,
        text: str,
        max_length: int = 500,
        min_length: int = 100,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,
        temperature: Optional[float] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        context_1m: bool = False,
    ) -> AIMessage:
        """
        Generates a summary for a given text in a stateless manner.

        Args:
            text (str): The text content to summarize.
            max_length (int): The maximum desired character length for the summary.
            min_length (int): The minimum desired character length for the summary.
            model (Union[ClaudeModel, str]): The model to use.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        await self._ensure_client()

        self.logger.info(
            f"Generating summary for text: '{text[:50]}...'"
        )

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())

        # Define the specific system prompt for summarization
        system_prompt = f"""Your job is to produce a final summary from the following text and identify the main theme.
- The summary should be concise and to the point.
- The summary should be no longer than {max_length} characters and no less than {min_length} characters.
- The summary should be in a single paragraph.
- Focus on the key information and main points.
- Write in clear, accessible language."""

        # Prepare the message for Claude
        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": text}]
        }]

        payload = {
            "model": self._resolve_model(model),
            "max_tokens": self.max_tokens,
            "temperature": temperature or self.temperature,
            "messages": messages,
            "system": system_prompt
        }

        if context_1m:
            payload["betas"] = ["context-1m-2025-08-07"]

        # Make a stateless call to Claude using SDK
        response = await self._sdk_create(payload)
        result = response.model_dump()

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_claude(
            response=result,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None,
            tool_calls=[]
        )

        return ai_message


    async def translate_text(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,
        temperature: Optional[float] = 0.2,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        context_1m: bool = False,
    ) -> AIMessage:
        """
        Translates a given text from a source language to a target language.

        Args:
            text (str): The text content to translate.
            target_lang (str): The target language name or ISO code (e.g., 'Spanish', 'es', 'French', 'fr').
            source_lang (Optional[str]): The source language name or ISO code.
                If None, Claude will attempt to detect it.
            model (Union[ClaudeModel, str]): The model to use. Defaults to SONNET_4.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        await self._ensure_client()

        self.logger.info(
            f"Translating text to '{target_lang}': '{text[:50]}...'"
        )

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())

        # Construct the system prompt for translation
        if source_lang:
            system_prompt = f"""You are a professional translator. Translate the following text from {source_lang} to {target_lang}.
Requirements:
- Provide only the translated text, without any additional comments or explanations
- Maintain the original meaning and tone
- Use natural, fluent language in the target language
- Preserve formatting if present (like line breaks, bullet points, etc.)
- If there are proper nouns or technical terms, keep them appropriate for the target language context"""  # noqa
        else:
            system_prompt = f"""You are a professional translator. First, detect the source language of the following text, then translate it to {target_lang}.
Requirements:
- Provide only the translated text, without any additional comments or explanations
- Maintain the original meaning and tone
- Use natural, fluent language in the target language
- Preserve formatting if present (like line breaks, bullet points, etc.)
- If there are proper nouns or technical terms, keep them appropriate for the target language context"""  # noqa

        # Prepare the message for Claude
        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": text}]
        }]

        payload = {
            "model": self._resolve_model(model),
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "messages": messages,
            "system": system_prompt
        }

        if context_1m:
            payload["betas"] = ["context-1m-2025-08-07"]

        # Make a stateless call to Claude using SDK
        response = await self._sdk_create(payload)
        result = response.model_dump()

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_claude(
            response=result,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None,
            tool_calls=[]
        )

        return ai_message


    # Additional helper methods you might want to add

    async def extract_key_points(
        self,
        text: str,
        num_points: int = 5,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,
        temperature: Optional[float] = 0.3,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        context_1m: bool = False,
    ) -> AIMessage:
        """
        Extract key points from a given text.

        Args:
            text (str): The text content to analyze.
            num_points (int): The number of key points to extract.
            model (Union[ClaudeModel, str]): The model to use.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        await self._ensure_client()

        turn_id = str(uuid.uuid4())

        system_prompt = f"""Extract the {num_points} most important key points from the following text.
Requirements:
- Present each point as a clear, concise bullet point
- Focus on the main ideas and significant information
- Each point should be self-contained and meaningful
- Order points by importance (most important first)
- Use bullet points (•) to format the list"""

        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": text}]
        }]

        payload = {
            "model": self._resolve_model(model),
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "messages": messages,
            "system": system_prompt
        }

        if context_1m:
            payload["betas"] = ["context-1m-2025-08-07"]

        response = await self._sdk_create(payload)
        result = response.model_dump()

        return AIMessageFactory.from_claude(
            response=result,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None,
            tool_calls=[]
        )


    async def analyze_sentiment(
        self,
        text: str,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,
        temperature: Optional[float] = 0.1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        use_structured: bool = False,
        context_1m: bool = False,
    ) -> AIMessage:
        """
        Analyze the sentiment of a given text.

        Args:
            text (str): The text content to analyze.
            model (Union[ClaudeModel, str]): The model to use.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        await self._ensure_client()

        turn_id = str(uuid.uuid4())
        if use_structured:
            system_prompt = """You are a sentiment analysis expert.
Analyze the sentiment of the given text and respond with valid JSON matching this exact schema:
{
  "sentiment": "positive" | "negative" | "neutral" | "mixed",
  "confidence_level": 0.0-1.0,
  "emotional_indicators": ["word1", "phrase2", ...],
  "reason": "explanation of analysis"
}
Respond only with valid JSON, no additional text."""
        else:
            system_prompt = """
Analyze the sentiment of the following text and provide a structured response.
Your response should include:
1. Overall sentiment (Positive, Negative, Neutral, or Mixed)
2. Confidence level (High, Medium, Low)
3. Key emotional indicators found in the text
4. Brief explanation of your analysis
Format your response clearly with these sections.
            """

        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": text}]
        }]

        payload = {
            "model": self._resolve_model(model),
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "messages": messages,
            "system": system_prompt
        }

        if context_1m:
            payload["betas"] = ["context-1m-2025-08-07"]

        response = await self._sdk_create(payload)
        structured_output = SentimentAnalysis if use_structured else None
        return AIMessageFactory.from_claude(
            response=response,
            input_text=f"Review: {text[:100]}...", # Changed from 'text' to f"Review: {text[:100]}..."
            model=model,
            user_id=user_id, # Kept user_id
            session_id=session_id, # Kept session_id
            turn_id=turn_id, # Kept turn_id
            structured_output=structured_output, # Kept structured_output
            tool_calls=[]
        )

    def _get_deep_research_system_prompt(self) -> str:
        """Generate a specialized system prompt for deep research mode.

        This prompt encourages thorough, methodical research with iterative refinement.
        """
        return """You are in DEEP RESEARCH mode. Your task is to conduct thorough, comprehensive research on the given topic.

Follow this methodology:
1. **Initial Analysis**: Break down the research question into key components
2. **Systematic Investigation**: Use available tools to gather information from multiple sources
3. **Critical Evaluation**: Assess the credibility and relevance of each source
4. **Synthesis**: Combine findings into a coherent, well-structured response
5. **Verification**: Cross-reference facts and verify claims when possible

Research Guidelines:
- Be comprehensive: explore multiple angles and perspectives
- Be critical: evaluate source quality and potential biases
- Be thorough: don't stop at surface-level information
- Be structured: organize findings logically
- Be accurate: cite sources and acknowledge uncertainty when appropriate

If tools are available, use them strategically to:
- Search for current information
- Verify facts across multiple sources
- Gather diverse perspectives
- Access specialized knowledge bases

Provide your final answer with:
- Clear, well-organized structure
- Supporting evidence for key claims
- Acknowledgment of limitations or gaps in available information
- Relevant citations or references when applicable"""

    async def analyze_product_review(
        self,
        review_text: str,
        product_id: str,
        product_name: str,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,
        temperature: Optional[float] = 0.1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Analyze a product review and extract structured information.

        Args:
            review_text (str): The product review text to analyze.
            product_id (str): Unique identifier for the product.
            product_name (str): Name of the product being reviewed.
            model (Union[ClaudeModel, str]): The model to use.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        await self._ensure_client()

        turn_id = str(uuid.uuid4())

        system_prompt = f"""You are a product review analysis expert. Analyze the given product review and respond with valid JSON matching this exact schema:

    {{
    "product_id": "{product_id}",
    "product_name": "{product_name}",
    "review_text": "original review text",
    "rating": 0.0-5.0,
    "sentiment": "positive" | "negative" | "neutral",
    "key_features": ["feature1", "feature2", ...]
    }}

    Extract the rating based on the review content (estimate if not explicitly stated), determine sentiment, and identify key product features mentioned. Respond only with valid JSON, no additional text."""

        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": f"Product ID: {product_id}\nProduct Name: {product_name}\nReview: {review_text}"}]
        }]

        payload = {
            "model": self._resolve_model(model),
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "messages": messages,
            "system": system_prompt
        }

        response = await self._sdk_create(payload)
        result = response.model_dump()

        return AIMessageFactory.from_claude(
            response=result,
            input_text=review_text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=ProductReview,
            tool_calls=[]
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
        """Lightweight stateless invocation for AnthropicClient.

        Uses schema-in-system-prompt for structured output (Claude does not
        support native ``response_format`` JSON schema).  A single
        ``messages.create()`` call is made — no retry, no history, no
        prompt builder.

        Args:
            prompt: User prompt.
            output_type: Pydantic model or dataclass to parse the response into.
            structured_output: Full :class:`StructuredOutputConfig`; takes
                precedence over ``output_type``.
            model: Model override. Defaults to ``_lightweight_model``.
            system_prompt: System prompt override.
            max_tokens: Maximum completion tokens.
            temperature: Sampling temperature.
            use_tools: Whether to inject registered tools.
            tools: Additional tool definitions.

        Returns:
            :class:`InvokeResult` with parsed output.

        Raises:
            :class:`InvokeError`: On provider errors.
        """
        try:
            resolved_prompt = self._resolve_invoke_system_prompt(system_prompt)
            config = self._build_invoke_structured_config(output_type, structured_output)
            resolved_model = self._resolve_invoke_model(model)

            # Claude: inject schema instruction into system prompt
            if config:
                resolved_prompt += "\n\n" + config.format_schema_instruction()

            messages = [{"role": "user", "content": prompt}]

            kwargs: Dict[str, Any] = {
                "model": resolved_model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": resolved_prompt,
                "messages": messages,
            }

            # Prepare tools if requested
            if use_tools:
                tool_defs = self._prepare_tools()
                if tool_defs:
                    kwargs["tools"] = tool_defs

            if not self.client:
                raise RuntimeError(
                    "AnthropicClient not initialised. Use async context manager."
                )

            response = await self.client.messages.create(**kwargs)

            # Extract text from response content blocks
            raw_text = ""
            for block in response.content:
                if hasattr(block, 'text'):
                    raw_text += block.text

            # Parse structured output
            output: Any = raw_text
            if config:
                if config.custom_parser:
                    output = config.custom_parser(raw_text)
                else:
                    output = await self._parse_structured_output(raw_text, config)

            usage_dict = {}
            if hasattr(response, 'usage') and response.usage:
                usage_dict = response.usage.__dict__
            usage = CompletionUsage.from_claude(usage_dict)

            return self._build_invoke_result(
                output, output_type, resolved_model, usage, response
            )
        except InvokeError:
            raise
        except Exception as exc:
            raise self._handle_invoke_error(exc)


# Backward compatibility alias
ClaudeClient = AnthropicClient
