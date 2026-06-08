from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import is_dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from datamodel.exceptions import ParserError  # pylint: disable=E0611 # noqa
from datamodel.parsers.json import json_decoder  # pylint: disable=E0611 # noqa
from navconfig import config

from ..models import AIMessage, CompletionUsage, OutputFormat, StructuredOutputConfig, ToolCall
from ..models.responses import InvokeResult
from ..models.zai import THINKING_CAPABLE_ZAI_MODELS, ZaiModel
from ..exceptions import InvokeError
from .base import AbstractClient


class ZaiClient(AbstractClient):
    """Client for Z.ai chat completions using the official ``zai-sdk`` package."""

    client_type: str = "zai"
    client_name: str = "zai"
    model: str = ZaiModel.GLM_5_1.value
    _default_model: str = ZaiModel.GLM_5_1.value
    _lightweight_model: str = ZaiModel.GLM_4_5_FLASH_FREE.value
    _min_cache_tokens: int = 0  # Z.ai does not support explicit prompt caching yet

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.z.ai/api/paas/v4/",
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        self.api_key = api_key or config.get("ZAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ZAI_API_KEY is required. Pass api_key= or set the ZAI_API_KEY environment variable."
            )
        self.base_url = base_url or config.get("ZAI_BASE_URL") or "https://api.z.ai/api/paas/v4/"
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        super().__init__(**kwargs)

    async def get_client(self) -> Any:
        """Create the official Z.ai SDK client for the current event loop."""
        from zai import ZaiClient as OfficialZaiClient

        kwargs: Dict[str, Any] = {
            "api_key": self.api_key,
            "base_url": self.base_url,
        }
        if self.timeout is not None:
            kwargs["timeout"] = self.timeout
        if self.max_retries is not None:
            kwargs["max_retries"] = self.max_retries
        return OfficialZaiClient(**kwargs)

    def _model_value(self, model: Union[str, ZaiModel, None]) -> str:
        if isinstance(model, ZaiModel):
            return model.value
        return model or self.model or self._default_model

    def _normalize_content(self, content: Any) -> Any:
        if not isinstance(content, list):
            return content

        text_parts: List[str] = []
        normalized: List[Dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                normalized.append(part)
                continue
            if part.get("type") == "text":
                text = part.get("text", "")
                if text:
                    text_parts.append(text)
                continue
            normalized.append(part)

        if normalized:
            return [
                *({"type": "text", "text": text} for text in text_parts),
                *normalized,
            ]
        return "\n".join(text_parts)

    def _normalize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for message in messages:
            msg = dict(message)
            if "content" in msg:
                msg["content"] = self._normalize_content(msg["content"])
            normalized.append(msg)
        return normalized

    async def _build_messages(
        self,
        prompt: str,
        files: Optional[List[Union[str, Path]]],
        user_id: Optional[str],
        session_id: Optional[str],
        system_prompt: Optional[Union[str, list]],
    ) -> tuple[List[Dict[str, Any]], Any, Optional[str]]:
        resolved_system_prompt = self._resolve_system_prompt(system_prompt)
        messages, conversation_history, _ = await self._prepare_conversation_context(
            prompt,
            files,
            user_id,
            session_id,
            resolved_system_prompt,
        )
        if resolved_system_prompt:
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": resolved_system_prompt,
                },
            )
        return self._normalize_messages(messages), conversation_history, resolved_system_prompt

    def _prepare_zai_tools(self) -> List[Dict[str, Any]]:
        tools: List[Dict[str, Any]] = []
        for tool in self.tool_manager.all_tools():
            tool_name = tool.name if hasattr(tool, "name") else tool.__class__.__name__
            if hasattr(tool, "input_schema") and tool.input_schema:
                parameters = tool.input_schema
            elif hasattr(tool, "get_schema"):
                schema = tool.get_schema()
                parameters = schema.get("parameters", schema)
            else:
                parameters = {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                }

            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": getattr(tool, "description", "") or "",
                        "parameters": parameters,
                    },
                }
            )
        return tools

    def _prepare_structured_output_format(self, output_type: Optional[type]) -> Dict[str, Any]:
        if output_type is None:
            return {"response_format": {"type": "json_object"}}

        if hasattr(output_type, "model_json_schema"):
            schema = output_type.model_json_schema()
        elif hasattr(output_type, "schema"):
            schema = output_type.schema()
        elif is_dataclass(output_type):
            schema = StructuredOutputConfig(output_type=output_type).get_schema()
        else:
            return {"response_format": {"type": "json_object"}}

        name = getattr(output_type, "__name__", "structured_output")
        return {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": name.lower(),
                    "schema": self._oai_normalize_schema(schema, force_required_all=False),
                },
            }
        }

    def _thinking_payload(
        self,
        model: str,
        thinking: Optional[Union[bool, str, Dict[str, Any]]],
        deep_thinking: bool,
    ) -> Optional[Dict[str, Any]]:
        if thinking is None and not deep_thinking:
            return None
        if model not in THINKING_CAPABLE_ZAI_MODELS:
            self.logger.warning(
                "Z.ai thinking requested for model %s, which is not in the known thinking-capable set.",
                model,
            )
        if isinstance(thinking, dict):
            return thinking
        if isinstance(thinking, str):
            return {"type": thinking}
        enabled = bool(thinking) or deep_thinking
        return {"type": "enabled" if enabled else "disabled"}

    def _usage_from_response(self, response: Any) -> CompletionUsage:
        usage = getattr(response, "usage", None)
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        completion_details = getattr(usage, "completion_tokens_details", None)
        extra_usage: Dict[str, Any] = {}
        cached_tokens = getattr(prompt_details, "cached_tokens", None)
        reasoning_tokens = getattr(completion_details, "reasoning_tokens", None)
        if cached_tokens is not None:
            extra_usage["cached_tokens"] = cached_tokens
        if reasoning_tokens is not None:
            extra_usage["reasoning_tokens"] = reasoning_tokens
        return CompletionUsage(
            prompt_tokens=getattr(usage, "prompt_tokens", 0),
            completion_tokens=getattr(usage, "completion_tokens", 0),
            total_tokens=getattr(usage, "total_tokens", 0),
            extra_usage=extra_usage,
        )

    def _response_to_dict(self, response: Any) -> Dict[str, Any]:
        if hasattr(response, "model_dump"):
            return response.model_dump()
        if hasattr(response, "dict"):
            return response.dict()
        if isinstance(response, dict):
            return response
        return getattr(response, "__dict__", {})

    def _message_to_dict(self, message: Any) -> Dict[str, Any]:
        if hasattr(message, "model_dump"):
            return message.model_dump()
        if hasattr(message, "dict"):
            return message.dict()
        if isinstance(message, dict):
            return message
        return getattr(message, "__dict__", {})

    def _create_ai_message(
        self,
        *,
        response: Any,
        input_text: str,
        model: str,
        user_id: Optional[str],
        session_id: Optional[str],
        turn_id: str,
        structured_output: Any = None,
        tool_calls: Optional[List[ToolCall]] = None,
        response_time: Optional[float] = None,
    ) -> AIMessage:
        choice = response.choices[0]
        message = choice.message
        content = getattr(message, "content", None) or ""
        reasoning_content = getattr(message, "reasoning_content", None)
        usage = self._usage_from_response(response)
        metadata: Dict[str, Any] = {}
        if reasoning_content:
            metadata["reasoning_content"] = reasoning_content
        if usage.extra_usage.get("cached_tokens") is not None:
            metadata["cached_tokens"] = usage.extra_usage["cached_tokens"]

        return AIMessage(
            input=input_text,
            output=structured_output if structured_output is not None else content,
            response=content,
            is_structured=structured_output is not None,
            structured_output=structured_output,
            model=model,
            provider="zai",
            usage=usage,
            stop_reason=getattr(choice, "finish_reason", None),
            finish_reason=getattr(choice, "finish_reason", None),
            tool_calls=tool_calls or [],
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            response_time=response_time,
            raw_response=self._response_to_dict(response),
            metadata=metadata,
        )

    async def _create_completion(self, **request_args: Any) -> Any:
        client = await self._ensure_client()
        return await asyncio.to_thread(client.chat.completions.create, **request_args)

    def _parse_tool_arguments(self, raw_arguments: Any) -> Dict[str, Any]:
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if not raw_arguments:
            return {}
        try:
            return json.loads(raw_arguments)
        except json.JSONDecodeError:
            try:
                return json_decoder(raw_arguments)
            except ParserError:
                return {}

    async def _run_tool_loop(
        self,
        *,
        messages: List[Dict[str, Any]],
        response: Any,
        request_args: Dict[str, Any],
        max_turns: int = 10,
    ) -> tuple[Any, List[ToolCall]]:
        all_tool_calls: List[ToolCall] = []
        result = response.choices[0].message
        turns = 0
        while getattr(result, "tool_calls", None) and turns < max_turns:
            turns += 1
            messages.append(self._message_to_dict(result))
            for provider_tool_call in result.tool_calls:
                function = provider_tool_call.function
                tool_name = function.name
                tool_args = self._parse_tool_arguments(function.arguments)
                tool_call = ToolCall(
                    id=provider_tool_call.id,
                    name=tool_name,
                    arguments=tool_args,
                )
                try:
                    started = time.perf_counter()
                    tool_result = await self._execute_tool(tool_name, tool_args)
                    tool_call.execution_time = time.perf_counter() - started
                    tool_call.result = tool_result
                    content = json.dumps(tool_result, default=str)
                except Exception as exc:
                    tool_call.error = str(exc)
                    content = f"Error: {exc}"

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": provider_tool_call.id,
                        "name": tool_name,
                        "content": content,
                    }
                )
                all_tool_calls.append(tool_call)

            follow_up_args = dict(request_args)
            follow_up_args["messages"] = messages
            response = await self._create_completion(**follow_up_args)
            result = response.choices[0].message
        return response, all_tool_calls

    async def ask(
        self,
        prompt: str,
        model: Union[str, ZaiModel, None] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.9,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[Union[str, list]] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
        thinking: Optional[Union[bool, str, Dict[str, Any]]] = None,
        deep_thinking: bool = False,
        **_: Any,
    ) -> AIMessage:
        """Send a non-streaming chat request to Z.ai.

        Args:
            prompt: The user input text.
            model: Z.ai model identifier; defaults to :attr:`_default_model`.
            max_tokens: Maximum completion tokens.
            temperature: Sampling temperature.
            top_p: Top-p nucleus sampling parameter.
            files: Optional file paths to include in the request.
            system_prompt: Optional system prompt string or list of
                CacheableSegments.
            structured_output: Pydantic model or :class:`StructuredOutputConfig`
                for JSON-schema-constrained responses.
            user_id: Optional user identifier for conversation memory.
            session_id: Optional session identifier for conversation memory.
            tools: Additional tool definitions to register for this call.
            use_tools: Override the instance-level ``enable_tools`` flag.
            thinking: Enable chain-of-thought for thinking-capable models.
            deep_thinking: Shorthand to enable thinking on capable models.

        Returns:
            :class:`AIMessage` with the final response and usage metadata.

        Raises:
            Exception: Propagates provider errors after emitting a
                ``ClientCallFailedEvent``.
        """
        resolved_model = self._model_value(model)
        turn_id = str(uuid.uuid4())
        started = time.perf_counter()
        messages, conversation_history, resolved_system_prompt = await self._build_messages(
            prompt,
            files,
            user_id,
            session_id,
            system_prompt,
        )

        _use_tools = use_tools if use_tools is not None else self.enable_tools
        if tools:
            for tool in tools:
                self.register_tool(tool)

        output_config = self._get_structured_config(structured_output)
        request_args: Dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": False,
        }

        if thinking_payload := self._thinking_payload(resolved_model, thinking, deep_thinking):
            request_args["thinking"] = thinking_payload

        if _use_tools:
            request_args["tools"] = self._prepare_zai_tools()
            request_args["tool_choice"] = "auto"
        elif output_config:
            self._ensure_json_instruction(
                messages,
                "Please respond with a valid JSON object that matches the requested schema.",
            )
            request_args.update(
                self._prepare_structured_output_format(output_config.output_type)
                if output_config.format == OutputFormat.JSON
                else {}
            )

        # FEAT-176/228: emit before-call lifecycle event
        lc_tc = self._emit_before_call(
            client_name="zai",
            model=resolved_model,
            temperature=temperature,
            system_prompt=resolved_system_prompt,
            has_tools=bool(_use_tools),
        )
        try:
            response = await self._create_completion(**request_args)
            all_tool_calls: List[ToolCall] = []
            if _use_tools:
                response, all_tool_calls = await self._run_tool_loop(
                    messages=messages,
                    response=response,
                    request_args=request_args,
                )

            content = getattr(response.choices[0].message, "content", None) or ""
            parsed_output = None
            if output_config:
                parsed_output = await self._parse_structured_output(content, output_config)

            response_time = time.perf_counter() - started
            ai_message = self._create_ai_message(
                response=response,
                input_text=prompt,
                model=resolved_model,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                structured_output=parsed_output,
                tool_calls=all_tool_calls,
                response_time=response_time,
            )
        except Exception as exc:
            await self._emit_failed_call(
                lc_tc,
                client_name="zai",
                model=resolved_model,
                duration_ms=(time.perf_counter() - started) * 1000,
                exc=exc,
            )
            raise

        await self._emit_after_call(
            lc_tc,
            client_name="zai",
            model=resolved_model,
            duration_ms=response_time * 1000,
            input_tokens=ai_message.usage.prompt_tokens,
            output_tokens=ai_message.usage.completion_tokens,
            finish_reason=ai_message.stop_reason,
        )
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_history,
            messages,
            resolved_system_prompt,
            turn_id,
            prompt,
            ai_message.response or "",
            tools_used=[tool_call.name for tool_call in all_tool_calls],
        )
        return ai_message

    def _next_stream_item(self, iterator: Any) -> tuple[bool, Any]:
        try:
            return True, next(iterator)
        except StopIteration:
            return False, None

    def _accumulate_stream_tool_calls(
        self,
        accumulator: Dict[int, Dict[str, Any]],
        tool_call_deltas: Optional[List[Any]],
    ) -> None:
        if not tool_call_deltas:
            return
        for delta in tool_call_deltas:
            index = getattr(delta, "index", 0)
            current = accumulator.setdefault(
                index,
                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
            )
            if getattr(delta, "id", None):
                current["id"] = delta.id
            if getattr(delta, "type", None):
                current["type"] = delta.type
            function = getattr(delta, "function", None)
            if function is None:
                continue
            if getattr(function, "name", None):
                current["function"]["name"] += function.name
            if getattr(function, "arguments", None):
                current["function"]["arguments"] += function.arguments

    async def _stream_completion(self, **request_args: Any) -> AsyncIterator[Any]:
        """Collect all chunks from the synchronous Z.ai stream in a single thread.

        The ``zai-sdk`` exposes only a synchronous streaming client.  A single
        :func:`asyncio.to_thread` call collects *all* chunks so the event loop
        is blocked only once rather than once per token.

        Args:
            **request_args: Keyword arguments forwarded verbatim to
                ``client.chat.completions.create(stream=True, ...)``.

        Yields:
            Raw chunk objects from the Z.ai streaming response.
        """
        client = await self._ensure_client()

        def _collect_all_chunks() -> list:
            return list(client.chat.completions.create(**request_args))

        chunks = await asyncio.to_thread(_collect_all_chunks)
        for chunk in chunks:
            yield chunk

    async def ask_stream(
        self,
        prompt: str,
        model: Union[str, ZaiModel, None] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.9,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[Union[str, list]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
        thinking: Optional[Union[bool, str, Dict[str, Any]]] = None,
        deep_thinking: bool = False,
        stream_reasoning: bool = False,
        **_: Any,
    ) -> AsyncIterator[Union[str, AIMessage]]:
        """Stream a Z.ai response, yielding text chunks followed by an
        :class:`AIMessage` sentinel.

        Args:
            prompt: The user input text.
            model: Z.ai model identifier; defaults to :attr:`_default_model`.
            max_tokens: Maximum completion tokens.
            temperature: Sampling temperature.
            top_p: Top-p nucleus sampling parameter.
            files: Optional file paths to include in the request.
            system_prompt: Optional system prompt string or list of
                CacheableSegments.
            user_id: Optional user identifier for conversation memory.
            session_id: Optional session identifier for conversation memory.
            tools: Additional tool definitions to register for this call.
            use_tools: Override the instance-level ``enable_tools`` flag.
            thinking: Enable chain-of-thought for thinking-capable models.
            deep_thinking: Shorthand to enable thinking on capable models.
            stream_reasoning: When ``True``, yield reasoning-content chunks as
                they arrive in addition to the final content.

        Yields:
            ``str`` chunks of the response as they arrive, followed by a
            single :class:`AIMessage` sentinel carrying full metadata.

        Raises:
            Exception: Propagates provider errors after emitting a
                ``ClientCallFailedEvent``.
        """
        resolved_model = self._model_value(model)
        turn_id = str(uuid.uuid4())
        started = time.perf_counter()
        messages, conversation_history, resolved_system_prompt = await self._build_messages(
            prompt,
            files,
            user_id,
            session_id,
            system_prompt,
        )

        _use_tools = use_tools if use_tools is not None else self.enable_tools
        if tools:
            for tool in tools:
                self.register_tool(tool)

        request_args: Dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": True,
        }
        if thinking_payload := self._thinking_payload(resolved_model, thinking, deep_thinking):
            request_args["thinking"] = thinking_payload
        if _use_tools:
            request_args["tools"] = self._prepare_zai_tools()
            request_args["tool_choice"] = "auto"
            request_args["tool_stream"] = True

        # FEAT-176/228: emit before-call lifecycle event
        lc_tc = self._emit_before_call(
            client_name="zai",
            model=resolved_model,
            temperature=temperature,
            system_prompt=resolved_system_prompt,
            has_tools=bool(_use_tools),
        )

        content_parts: List[str] = []
        reasoning_parts: List[str] = []
        usage = CompletionUsage()
        finish_reason: Optional[str] = None
        last_raw_chunk: Dict[str, Any] = {}
        tool_call_accumulator: Dict[int, Dict[str, Any]] = {}

        try:
            async for chunk in self._stream_completion(**request_args):
                last_raw_chunk = self._response_to_dict(chunk)
                if getattr(chunk, "usage", None):
                    usage = self._usage_from_response(chunk)
                if not getattr(chunk, "choices", None):
                    continue
                choice = chunk.choices[0]
                finish_reason = getattr(choice, "finish_reason", None) or finish_reason
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    reasoning_parts.append(reasoning)
                    if stream_reasoning:
                        yield reasoning
                content = getattr(delta, "content", None)
                if content:
                    content_parts.append(content)
                    yield content
                self._accumulate_stream_tool_calls(
                    tool_call_accumulator,
                    getattr(delta, "tool_calls", None),
                )

            all_tool_calls: List[ToolCall] = []
            if tool_call_accumulator:
                assistant_tool_calls = [tool_call_accumulator[index] for index in sorted(tool_call_accumulator)]
                messages.append(
                    {
                        "role": "assistant",
                        "content": "".join(content_parts),
                        "tool_calls": assistant_tool_calls,
                    }
                )
                for provider_tool_call in assistant_tool_calls:
                    function = provider_tool_call["function"]
                    tool_name = function["name"]
                    tool_args = self._parse_tool_arguments(function["arguments"])
                    tool_call = ToolCall(
                        id=provider_tool_call.get("id") or str(uuid.uuid4()),
                        name=tool_name,
                        arguments=tool_args,
                    )
                    try:
                        tool_started = time.perf_counter()
                        tool_result = await self._execute_tool(tool_name, tool_args)
                        tool_call.execution_time = time.perf_counter() - tool_started
                        tool_call.result = tool_result
                        tool_content = json.dumps(tool_result, default=str)
                    except Exception as exc:
                        tool_call.error = str(exc)
                        tool_content = f"Error: {exc}"
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": tool_content,
                        }
                    )
                    all_tool_calls.append(tool_call)

                follow_up_args = dict(request_args)
                follow_up_args["messages"] = messages
                follow_up_args.pop("tool_stream", None)
                async for chunk in self._stream_completion(**follow_up_args):
                    last_raw_chunk = self._response_to_dict(chunk)
                    if getattr(chunk, "usage", None):
                        usage = self._usage_from_response(chunk)
                    if not getattr(chunk, "choices", None):
                        continue
                    choice = chunk.choices[0]
                    finish_reason = getattr(choice, "finish_reason", None) or finish_reason
                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        continue
                    content = getattr(delta, "content", None)
                    if content:
                        content_parts.append(content)
                        yield content

            content_text = "".join(content_parts)
            if not content_text:
                yield ""

            metadata: Dict[str, Any] = {}
            reasoning_text = "".join(reasoning_parts)
            if reasoning_text:
                metadata["reasoning_content"] = reasoning_text
            if usage.extra_usage.get("cached_tokens") is not None:
                metadata["cached_tokens"] = usage.extra_usage["cached_tokens"]

            response_time = time.perf_counter() - started
            ai_message = AIMessage(
                input=prompt,
                output=content_text,
                response=content_text,
                model=resolved_model,
                provider="zai",
                usage=usage,
                stop_reason=finish_reason,
                finish_reason=finish_reason,
                tool_calls=all_tool_calls,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                response_time=response_time,
                raw_response=last_raw_chunk,
                metadata=metadata,
            )
        except Exception as exc:
            await self._emit_failed_call(
                lc_tc,
                client_name="zai",
                model=resolved_model,
                duration_ms=(time.perf_counter() - started) * 1000,
                exc=exc,
            )
            raise

        await self._emit_after_call(
            lc_tc,
            client_name="zai",
            model=resolved_model,
            duration_ms=response_time * 1000,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            finish_reason=finish_reason,
        )
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_history,
            messages,
            resolved_system_prompt,
            turn_id,
            prompt,
            content_text,
            tools_used=[tool_call.name for tool_call in all_tool_calls],
        )
        yield ai_message

    async def resume(
        self,
        session_id: str,
        user_input: str,
        state: Dict[str, Any],
    ) -> AIMessage:
        """Resume a suspended ZaiClient execution after a HandoffTool / HITL pause.

        Injects *user_input* into the suspended message history (as a ``tool``
        role message when ``state["tool_call_id"]`` is present, otherwise as a
        ``user`` message) and continues the tool-call loop until a final
        response is produced.

        Args:
            session_id: Session identifier propagated to any
                :class:`~parrot.core.exceptions.HumanInteractionInterrupt`
                raised inside the loop.
            user_input: User reply to inject as the resumption value.
            state: Suspended execution state.  Expected keys:

                - ``messages`` (``list``): OpenAI-style message dicts.
                - ``tool_call_id`` (``str``, optional): ID of the paused tool
                  call.  When present *user_input* is injected as a ``tool``
                  result; otherwise it is injected as a ``user`` turn.
                - ``model`` / ``agent_name`` (``str``, optional): Model
                  override.
                - ``user_id`` (``str``, optional): Propagated to the returned
                  :class:`AIMessage`.

        Returns:
            :class:`AIMessage` with the final assistant response and all tool
            calls executed during resumption.

        Raises:
            :class:`~parrot.core.exceptions.HumanInteractionInterrupt`:
                Re-raised with updated session context when a tool triggers
                another human-interaction pause.
        """
        messages: List[Dict[str, Any]] = list(state.get("messages", []))
        tool_call_id: Optional[str] = state.get("tool_call_id")
        resolved_model = self._model_value(
            state.get("model") or state.get("agent_name")
        )
        turn_id = str(uuid.uuid4())

        # Inject the resumption value as a tool result or a new user turn.
        if tool_call_id:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": "handoff_tool",
                    "content": user_input,
                }
            )
        else:
            messages.append({"role": "user", "content": user_input})

        request_args: Dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.1,
            "stream": False,
        }
        if self.enable_tools:
            request_args["tools"] = self._prepare_zai_tools()
            request_args["tool_choice"] = "auto"

        response = await self._create_completion(**request_args)
        all_tool_calls: List[ToolCall] = []
        result = response.choices[0].message
        max_turns = 10
        turns = 0

        while getattr(result, "tool_calls", None) and turns < max_turns:
            turns += 1
            messages.append(self._message_to_dict(result))
            for provider_tc in result.tool_calls:
                fn = provider_tc.function
                tool_name = fn.name
                tool_args = self._parse_tool_arguments(fn.arguments)
                tc = ToolCall(
                    id=provider_tc.id,
                    name=tool_name,
                    arguments=tool_args,
                )
                try:
                    started = time.perf_counter()
                    tool_result = await self._execute_tool(tool_name, tool_args)
                    tc.execution_time = time.perf_counter() - started
                    tc.result = tool_result
                    content = json.dumps(tool_result, default=str)
                except Exception as exc:
                    from parrot.core.exceptions import HumanInteractionInterrupt

                    if isinstance(exc, HumanInteractionInterrupt):
                        exc.session_id = session_id
                        exc.messages = messages.copy()
                        exc.tool_call_id = provider_tc.id
                        exc.agent_name = resolved_model
                        raise
                    tc.error = str(exc)
                    content = f"Error: {exc}"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": provider_tc.id,
                        "name": tool_name,
                        "content": content,
                    }
                )
                all_tool_calls.append(tc)

            follow_up = dict(request_args)
            follow_up["messages"] = messages
            response = await self._create_completion(**follow_up)
            result = response.choices[0].message

        return self._create_ai_message(
            response=response,
            input_text="[Resumed Conversation]",
            model=resolved_model,
            user_id=state.get("user_id"),
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
        """Lightweight stateless invocation for ZaiClient.

        Makes a single ``chat.completions.create`` call without conversation
        history, retries, or the full prompt-builder overhead.  Uses Z.ai's
        native ``json_schema`` response format for structured output.

        Args:
            prompt: User prompt.
            output_type: Pydantic model or dataclass to parse the response
                into.  Mutually exclusive with *structured_output* (the latter
                wins).
            structured_output: Full :class:`StructuredOutputConfig`.  Takes
                precedence over *output_type*.
            model: Model override.  Falls back to :attr:`_lightweight_model`,
                then :attr:`model`.
            system_prompt: System prompt override.  Falls back to the default
                :attr:`BASIC_SYSTEM_PROMPT` template.
            max_tokens: Maximum completion tokens (default ``4096``).
            temperature: Sampling temperature (default ``0.0`` for
                deterministic structured extraction).
            use_tools: If ``True``, inject registered tools into the request.
            tools: Additional tool definitions to register for this call.

        Returns:
            :class:`InvokeResult` with ``output``, ``model``, ``usage``, and
            ``raw_response``.

        Raises:
            :class:`~parrot.exceptions.InvokeError`: On any provider error.
        """
        try:
            resolved_system = self._resolve_invoke_system_prompt(system_prompt)
            config = self._build_invoke_structured_config(output_type, structured_output)
            resolved_model = self._resolve_invoke_model(model)

            if tools:
                for tool_def in tools:
                    self.register_tool(tool_def)

            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": resolved_system},
                {"role": "user", "content": prompt},
            ]

            kwargs: Dict[str, Any] = {
                "model": resolved_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            }

            if config:
                kwargs.update(
                    self._prepare_structured_output_format(config.output_type)
                    if config.format == OutputFormat.JSON
                    else {}
                )

            if use_tools:
                tool_defs = self._prepare_zai_tools()
                if tool_defs:
                    kwargs["tools"] = tool_defs
                    kwargs["tool_choice"] = "auto"

            response = await self._create_completion(**kwargs)
            raw_text = getattr(response.choices[0].message, "content", None) or ""

            output: Any = raw_text
            if config:
                if config.custom_parser:
                    output = config.custom_parser(raw_text)
                else:
                    output = await self._parse_structured_output(raw_text, config)

            usage = self._usage_from_response(response)
            return self._build_invoke_result(output, output_type, resolved_model, usage, response)

        except InvokeError:
            raise
        except Exception as exc:
            raise self._handle_invoke_error(exc) from exc

    async def embed(self, *args: Any, **kwargs: Any) -> Any:
        """Embeddings are not implemented by this chat client yet."""
        raise NotImplementedError("ZaiClient embed() is not implemented.")
