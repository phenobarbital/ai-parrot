from __future__ import annotations
from typing import List, Dict, Any, Optional, Union, AsyncIterator, TYPE_CHECKING, Sequence
import os
import json
import uuid
from enum import Enum
from pathlib import Path
from dataclasses import is_dataclass
from pydantic import BaseModel, TypeAdapter

from ..memory.render import HistoryMessage
# FEAT-524: ids are no longer ask() parameters; response metadata reads them
# from the per-call ContextVars BaseBot binds (FEAT-228).
from parrot.observability.context import current_session_id, current_user_id
from .base import AbstractClient

if TYPE_CHECKING:
    from xai_sdk import AsyncClient


def _xai_chat_helpers():
    """Lazy-import the xai_sdk.chat role/tool builders."""
    try:
        from xai_sdk.chat import user, system, assistant, tool_result
    except ImportError as exc:
        raise ImportError(
            "GrokClient requires the 'xai-sdk' package (>=1.12). "
            "Install with: pip install ai-parrot[grok]"
        ) from exc
    return user, system, assistant, tool_result

from ..models import (
    MessageResponse,
    CompletionUsage,
    AIMessage,
    StructuredOutputConfig,
    ToolCall
)
from ..models.responses import InvokeResult
from ..exceptions import InvokeError
from ..tools.manager import ToolFormat

class GrokModel(str, Enum):
    """Grok model versions (xAI API, July 2026)."""
    GROK_4_3 = "grok-4.3"
    GROK_4_20 = "grok-4.20"
    GROK_4_20_NON_REASONING = "grok-4.20-non-reasoning"
    GROK_4_20_REASONING = "grok-4.20-reasoning"
    GROK_4_20_MULTI_AGENT = "grok-4.20-multi-agent"
    GROK_BUILD_0_1 = "grok-build-0.1"
    GROK_CODE_FAST_1 = "grok-code-fast-1"
    GROK_IMAGINE_IMAGE = "grok-imagine-image"
    GROK_IMAGINE_IMAGE_QUALITY = "grok-imagine-image-quality"
    GROK_IMAGINE_VIDEO = "grok-imagine-video"

class GrokClient(AbstractClient):
    """
    Client for interacting with xAI's Grok models.
    """
    client_type: str = "xai"
    client_name: str = "grok"
    _default_model: str = GrokModel.GROK_4_3.value
    _lightweight_model: str = GrokModel.GROK_4_20_NON_REASONING.value
    # Grok models are reasoning-heavy and xAI allows large completions;
    # preserves the budget ask()/ask_stream() hardcoded before FEAT-481.
    _default_max_tokens: int = 16000

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: int = 3600,
        **kwargs
    ):
        """
        Initialize Grok client.

        Args:
            api_key: xAI API key (defaults to XAI_API_KEY env var)
            timeout: Request timeout in seconds
            **kwargs: Additional arguments for AbstractClient
        """
        super().__init__(**kwargs)
        self.api_key = api_key or os.getenv("XAI_API_KEY")
        if not self.api_key:
            try:
                from navconfig import config
                self.api_key = config.get("XAI_API_KEY")
            except ImportError:
                pass

        if not self.api_key:
            raise ValueError("XAI_API_KEY not found in environment or config")

        self.timeout = timeout

    async def get_client(self) -> "AsyncClient":
        """Construct and return a fresh xAI AsyncClient for the current loop."""
        try:
            from xai_sdk import AsyncClient
        except ImportError as exc:
            raise ImportError(
                "GrokClient requires the 'xai-sdk' package (>=1.12). "
                "Install with: pip install ai-parrot[grok]"
            ) from exc
        return AsyncClient(api_key=self.api_key, timeout=self.timeout)

    async def close(self) -> None:
        """Close all per-loop SDK clients."""
        await super().close()

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> Any:
        pass

    def _prepare_structured_output_format(self, structured_output: type) -> dict:
        """Prepare response format for structured output using full JSON schema."""
        if not structured_output:
            return {}

        if isinstance(structured_output, BaseModel):
            structured_output = structured_output.__class__
        if is_dataclass(structured_output) and not isinstance(structured_output, type):
            structured_output = structured_output.__class__

        schema = None
        name = "structured_output"

        if isinstance(structured_output, type) and hasattr(structured_output, 'model_json_schema'):
            schema = structured_output.model_json_schema()
            name = structured_output.__name__.lower()
        elif is_dataclass(structured_output):
            schema = TypeAdapter(structured_output).json_schema()
            name = structured_output.__name__.lower()

        if schema:
            return {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": name,
                        "schema": schema,
                        "strict": True
                    }
                }
            }

        return {"response_format": {"type": "json_object"}}

    def _get_response_format_for_sdk(self, structured_output) -> Any:
        """Return a response_format value accepted by the xai_sdk chat.create().

        The SDK accepts a Pydantic BaseModel subclass directly, or the
        string ``"json_object"`` for unstructured JSON. Raw dicts are not
        supported by the gRPC transport.
        """
        if not structured_output:
            return None

        output_type = structured_output
        if isinstance(output_type, StructuredOutputConfig):
            output_type = output_type.output_type
        if isinstance(output_type, BaseModel):
            output_type = output_type.__class__
        if is_dataclass(output_type) and not isinstance(output_type, type):
            output_type = output_type.__class__

        # Pydantic models can be passed directly — the SDK generates the JSON schema
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            return output_type

        # Fallback: request JSON and parse manually afterward
        return "json_object"

    def _prepare_tools_for_grok(self) -> list:
        """Prepare tools using xai_sdk.chat.tool() for gRPC transport."""
        try:
            from xai_sdk.chat import tool as make_tool
        except ImportError:
            return []

        schemas = self.tool_manager.get_tool_schemas(provider_format=ToolFormat.OPENAI)
        prepared_tools = []
        for schema in schemas:
            s = schema.copy()
            s.pop('_tool_instance', None)
            prepared_tools.append(
                make_tool(
                    name=s.get("name", ""),
                    description=s.get("description", ""),
                    parameters=s.get("parameters", {}),
                )
            )
        return prepared_tools

    async def ask(
        self,
        prompt: str,
        model: str = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        history: Optional[Sequence[HistoryMessage]] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
    ) -> MessageResponse:
        """
        Send a prompt to Grok and return the response.
        """
        max_tokens = self._resolve_max_tokens(max_tokens)
        client = await self.get_client()
        model = model or self.model or self.default_model
        turn_id = str(uuid.uuid4())

        # 1. Prepare Structured Output
        response_format = None
        output_config = None
        if structured_output:
            output_config = self._get_structured_config(structured_output)
            if output_config and output_config.output_type:
                response_format = self._get_response_format_for_sdk(output_config)
            elif isinstance(structured_output, (type, BaseModel)) or is_dataclass(structured_output):
                response_format = self._get_response_format_for_sdk(structured_output)

        # 2. Prepare Tools
        _use_tools = use_tools if use_tools is not None else self.enable_tools
        prepared_tools = []
        if _use_tools:
            if tools:
                prepared_tools = tools
            else:
                prepared_tools = self._prepare_tools_for_grok()

        # FEAT-176: lifecycle event — BeforeClientCallEvent
        import time as _lc_time_grok2
        _lc_tc_grok2 = self._emit_before_call(
            client_name="grok",
            model=model,
            temperature=temperature if temperature is not None else self.temperature,
            system_prompt=system_prompt,
            has_tools=bool(_use_tools),
            parent_trace=None,
        )
        _lc_t0_grok2 = _lc_time_grok2.perf_counter()

        # 3. Initialize Chat
        chat_kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        if response_format is not None:
            chat_kwargs["response_format"] = response_format

        if prepared_tools:
            chat_kwargs['tools'] = prepared_tools
            chat_kwargs['tool_choice'] = "auto"

        chat = client.chat.create(**chat_kwargs)

        user_fn, system_fn, assistant_fn, tool_result_fn = _xai_chat_helpers()

        # 4. Add Context (System, History, User)
        if system_prompt:
            chat.append(system_fn(system_prompt))

        # FEAT-524: history arrives already rendered by the bot; grok's own
        # loader/writer pair is gone.
        for message in history or ():
            if message.role == "assistant":
                chat.append(assistant_fn(message.content))
            else:
                chat.append(user_fn(message.content))

        chat.append(user_fn(prompt))

        # 5. Execution Loop (Tools)
        final_response = None
        all_tool_calls = []
        max_turns = 10
        current_turn = 0

        # FEAT-397: per-round token usage accumulation across the tool loop.
        # Each chat.sample() call IS a round — current_turn is already the
        # 1-indexed round number, no separate pre-loop "initial call" here.
        _lc_accumulated_usage_grok2: "Optional[CompletionUsage]" = None

        while current_turn < max_turns:
            current_turn += 1

            try:
                _lc_round_t0_grok2 = _lc_time_grok2.perf_counter()
                response = await chat.sample()
                chat.append(response)
                _lc_round_duration_grok2 = (_lc_time_grok2.perf_counter() - _lc_round_t0_grok2) * 1000

                # FEAT-397: build this round's usage and accumulate. Rounds
                # where the provider reported no usage are skipped (accumulator
                # untouched); the round event still fires with usage=None.
                # Grok's usage may be a JSON-safe dict OR an xai_sdk protobuf
                # object — from_grok() handles both; its extra_usage dict
                # (getattr-extracted for the protobuf branch) doubles as the
                # JSON-safe raw_usage payload, per this task's implementation note.
                if hasattr(response, "usage") and response.usage:
                    _lc_round_usage_grok2 = CompletionUsage.from_grok(response.usage)
                    _lc_round_raw_usage_grok2 = _lc_round_usage_grok2.extra_usage
                    _lc_accumulated_usage_grok2 = (
                        _lc_round_usage_grok2
                        if _lc_accumulated_usage_grok2 is None
                        else _lc_accumulated_usage_grok2 + _lc_round_usage_grok2
                    )
                else:
                    _lc_round_usage_grok2 = None
                    _lc_round_raw_usage_grok2 = None

                tool_calls = response.tool_calls or []

                if not tool_calls:
                    final_response = response
                    break

                _lc_round_tool_names_grok2 = []
                for tc in tool_calls:
                    fn = tc.function
                    tool_name = fn.name
                    tool_args_str = fn.arguments
                    tool_id = tc.id

                    try:
                        tool_args = json.loads(tool_args_str)
                    except json.JSONDecodeError:
                        tool_args = {}

                    tool_exec_result = await self._execute_tool(tool_name, tool_args)

                    tool_call_rec = ToolCall(
                        id=tool_id,
                        name=tool_name,
                        arguments=tool_args,
                        result=tool_exec_result
                    )
                    all_tool_calls.append(tool_call_rec)
                    _lc_round_tool_names_grok2.append(tool_name)

                    chat.append(tool_result_fn(str(tool_exec_result), tool_call_id=tool_id))

                # FEAT-397: emit ClientRoundEvent for this round's tool execution.
                self._emit_round_event(
                    _lc_tc_grok2,
                    client_name="grok",
                    model=model,
                    round_number=current_turn,
                    usage=_lc_round_usage_grok2,
                    raw_usage=_lc_round_raw_usage_grok2,
                    tool_calls=_lc_round_tool_names_grok2,
                    duration_ms=_lc_round_duration_grok2,
                )

                continue

            except Exception as e:
                self.logger.error(f"Error in GrokClient loop: {e}")
                raise

        # 6. Parse Final Response
        if not final_response:
            final_response = response

        from ..models.responses import AIMessageFactory

        text_content = final_response.content if hasattr(final_response, 'content') else str(final_response)

        structured_payload = None
        if output_config:
            try:
                # Known-truncated output must not reach a custom parser either.
                self._raise_if_truncated(self._extract_finish_reason(final_response))
                if output_config.custom_parser:
                    structured_payload = output_config.custom_parser(text_content)
                else:
                    structured_payload = await self._parse_structured_output(
                        text_content,
                        output_config,
                        finish_reason=self._extract_finish_reason(final_response),
                    )
            except InvokeError:
                raise
            except Exception:
                pass

        ai_message = AIMessageFactory.create_message(
            response=final_response,
            input_text=prompt,
            model=model,
            user_id=current_user_id.get(),
            session_id=current_session_id.get(),
            turn_id=turn_id,
            usage=CompletionUsage.from_grok(final_response.usage) if hasattr(final_response, 'usage') else None,
            text_response=text_content
        )

        # FEAT-397: replace the last-round-only usage with the accumulated
        # multi-round total. For single-round calls (no tool use), the
        # accumulated total equals the last (only) round's usage, so this
        # is a no-op for existing single-round behavior.
        if _lc_accumulated_usage_grok2 is not None:
            if current_turn > 1:
                _lc_accumulated_usage_grok2.extra_usage["rounds"] = current_turn
            ai_message.usage = _lc_accumulated_usage_grok2

        ai_message.tool_calls = all_tool_calls
        if structured_payload:
            ai_message.structured_output = structured_payload
            ai_message.is_structured = True
            ai_message.output = structured_payload

        # FEAT-524: no memory write — AbstractBot.save_conversation_turn is
        # the single writer.

        # FEAT-176: lifecycle event — AfterClientCallEvent
        _lc_grok2_usage = getattr(ai_message, 'usage', None)
        await self._emit_after_call(
            _lc_tc_grok2, client_name="grok", model=model,
            duration_ms=(_lc_time_grok2.perf_counter() - _lc_t0_grok2) * 1000,
            input_tokens=getattr(_lc_grok2_usage, 'prompt_tokens', None) if _lc_grok2_usage else None,
            output_tokens=getattr(_lc_grok2_usage, 'completion_tokens', None) if _lc_grok2_usage else None,
            finish_reason=None,
        )
        return ai_message

    async def ask_stream(
        self,
        prompt: str,
        model: str = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        history: Optional[Sequence[HistoryMessage]] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        deep_research: bool = False,
        agent_config: Optional[Dict[str, Any]] = None,
        lazy_loading: bool = False,
    ) -> AsyncIterator[Union[str, AIMessage]]:
        """Stream response from Grok.

        Yields successive string chunks followed by a final
        :class:`~parrot.models.responses.AIMessage` with metadata.
        """
        max_tokens = self._resolve_max_tokens(max_tokens)
        turn_id = str(uuid.uuid4())
        client = await self.get_client()
        model = model or self.model or self.default_model

        # FEAT-176: lifecycle event — BeforeClientCallEvent for stream
        import time as _lc_time_groks
        from parrot.core.events.lifecycle.events import ClientStreamChunkEvent as _GrokStreamChunkEvent
        _lc_tc_groks = self._emit_before_call(
            client_name="grok",
            model=model,
            temperature=temperature if temperature is not None else self.temperature,
            system_prompt=system_prompt,
            has_tools=False,
            parent_trace=None,
        )
        _lc_t0_groks = _lc_time_groks.perf_counter()
        _lc_has_chunk_subs_grok2 = self.events.has_subscribers(_GrokStreamChunkEvent)
        _lc_chunk_idx_grok2 = 0

        chat_kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if structured_output:
            config = self._get_structured_config(structured_output)
            if config and config.output_type:
                rf = self._get_response_format_for_sdk(config)
                if rf is not None:
                    chat_kwargs["response_format"] = rf
            elif isinstance(structured_output, (type, BaseModel)) or is_dataclass(structured_output):
                rf = self._get_response_format_for_sdk(structured_output)
                if rf is not None:
                    chat_kwargs["response_format"] = rf

        chat = client.chat.create(**chat_kwargs)

        user_fn, system_fn, assistant_fn, _ = _xai_chat_helpers()

        if system_prompt:
            chat.append(system_fn(system_prompt))

        # FEAT-524: history arrives already rendered by the bot; grok's own
        # loader/writer pair is gone.
        for message in history or ():
            if message.role == "assistant":
                chat.append(assistant_fn(message.content))
            else:
                chat.append(user_fn(message.content))

        chat.append(user_fn(prompt))

        full_response = []
        final_sdk_response = None

        async for response, chunk in chat.stream():
            content = chunk.content
            final_sdk_response = response

            if content:
                full_response.append(content)
                # FEAT-176: per-chunk event
                if _lc_has_chunk_subs_grok2:
                    await self.events.emit(_GrokStreamChunkEvent(
                        trace_context=_lc_tc_groks, client_name="grok",
                        model=model, chunk_index=_lc_chunk_idx_grok2,
                        chunk_size_bytes=len(content.encode("utf-8")),
                        source_type="client", source_name="grok",
                    ))
                    _lc_chunk_idx_grok2 += 1
                yield content

        # Build and yield final AIMessage
        final_text = final_sdk_response.content if final_sdk_response else "".join(full_response)
        usage = (
            CompletionUsage.from_grok(final_sdk_response.usage)
            if final_sdk_response and hasattr(final_sdk_response, 'usage')
            else CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        )
        ai_message = AIMessage(
            input=prompt,
            output=final_text,
            response=final_text,
            model=model or self.model or self.default_model,
            provider="grok",
            usage=usage,
            user_id=current_user_id.get(),
            session_id=current_session_id.get(),
            turn_id=turn_id,
        )
        # FEAT-176: lifecycle event — AfterClientCallEvent
        await self._emit_after_call(
            _lc_tc_groks, client_name="grok", model=model,
            duration_ms=(_lc_time_groks.perf_counter() - _lc_t0_groks) * 1000,
            input_tokens=getattr(usage, 'prompt_tokens', None),
            output_tokens=getattr(usage, 'completion_tokens', None),
            finish_reason=None,
        )
        yield ai_message

        # FEAT-524: no memory write — the bot persists the round.

    async def resume(
        self,
        session_id: str,
        user_input: str,
        state: Dict[str, Any]
    ) -> AIMessage:
        """Resume a suspended Grok execution after a HandoffTool / HITL pause.

        Replays the suspended message history into a fresh xAI ``chat`` object,
        injects ``user_input`` as the resumption signal (as a ``tool_result``
        when a ``tool_call_id`` is present in ``state``, otherwise as a normal
        ``user`` turn) and continues the tool-call loop until a final response
        is produced.
        """
        from ..models.responses import AIMessageFactory

        client = await self.get_client()
        messages: List[Dict[str, Any]] = state.get("messages", [])
        tool_call_id = state.get("tool_call_id")
        model = state.get("agent_name") or state.get("model") or self.model or self._default_model
        turn_id = str(uuid.uuid4())

        chat_kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "temperature": 0.1,
        }
        prepared_tools = self._prepare_tools_for_grok() if self.enable_tools else []
        if prepared_tools:
            chat_kwargs["tools"] = prepared_tools
            chat_kwargs["tool_choice"] = "auto"

        chat = client.chat.create(**chat_kwargs)

        user_fn, system_fn, assistant_fn, tool_result_fn = _xai_chat_helpers()

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content") or ""
            if role == "system":
                chat.append(system_fn(content))
            elif role == "user":
                chat.append(user_fn(content))
            elif role == "assistant":
                chat.append(assistant_fn(content))
            elif role == "tool":
                chat.append(
                    tool_result_fn(
                        content,
                        tool_call_id=msg.get("tool_call_id") or msg.get("name"),
                    )
                )

        if tool_call_id:
            chat.append(tool_result_fn(user_input, tool_call_id=tool_call_id))
        else:
            chat.append(user_fn(user_input))

        all_tool_calls: List[ToolCall] = []
        max_turns = 10
        current_turn = 0
        final_response = None

        while current_turn < max_turns:
            current_turn += 1
            response = await chat.sample()
            chat.append(response)

            tool_calls = response.tool_calls or []

            if not tool_calls:
                final_response = response
                break

            for tc in tool_calls:
                fn = tc.function
                tool_name = fn.name
                try:
                    tool_args = json.loads(fn.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                try:
                    tool_exec_result = await self._execute_tool(tool_name, tool_args)
                    rec = ToolCall(
                        id=tc.id,
                        name=tool_name,
                        arguments=tool_args,
                        result=tool_exec_result,
                    )
                    all_tool_calls.append(rec)
                    chat.append(tool_result_fn(str(tool_exec_result), tool_call_id=tc.id))
                except Exception as exc:
                    from parrot.core.exceptions import HumanInteractionInterrupt

                    if isinstance(exc, HumanInteractionInterrupt):
                        exc.session_id = session_id
                        exc.messages = messages.copy()
                        exc.tool_call_id = tc.id
                        exc.agent_name = model
                        raise

                    err_rec = ToolCall(
                        id=tc.id,
                        name=tool_name,
                        arguments=tool_args,
                        error=str(exc),
                    )
                    all_tool_calls.append(err_rec)
                    chat.append(tool_result_fn(f"Error: {exc}", tool_call_id=tc.id))

        if final_response is None:
            final_response = response

        text_content = (
            final_response.content if hasattr(final_response, "content") else str(final_response)
        )
        ai_message = AIMessageFactory.create_message(
            response=final_response,
            input_text="[Resumed Conversation]",
            model=model,
            user_id=state.get("user_id", "unknown"),
            session_id=session_id,
            usage=CompletionUsage.from_grok(final_response.usage)
            if hasattr(final_response, "usage")
            else None,
            text_response=text_content,
        )
        ai_message.tool_calls = all_tool_calls
        return ai_message

    async def batch_ask(self, requests: List[Any]) -> List[Any]:
        """Batch processing not yet implemented for Grok."""
        raise NotImplementedError("Batch processing not supported for Grok yet")

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
        """Lightweight stateless invocation for GrokClient.

        Uses the xai_sdk stateful chat API with ``response_format`` for
        structured output. A single ``chat.sample()`` or ``chat.parse()``
        call is made — no retry, no history, no prompt builder.
        """
        try:
            resolved_prompt = self._resolve_invoke_system_prompt(system_prompt)
            config = self._build_invoke_structured_config(output_type, structured_output)
            resolved_model = self._resolve_invoke_model(model)
            max_tokens = self._resolve_max_tokens(max_tokens, resolved_model, for_invoke=True)

            client = await self.get_client()

            user_fn, system_fn, _, _ = _xai_chat_helpers()

            chat_kwargs: Dict[str, Any] = {
                "model": resolved_model,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            # Pydantic models without custom_parser → SDK-native parse()
            use_sdk_parse = False
            if config and config.output_type:
                if (
                    not config.custom_parser
                    and isinstance(config.output_type, type)
                    and issubclass(config.output_type, BaseModel)
                ):
                    use_sdk_parse = True
                else:
                    chat_kwargs["response_format"] = "json_object"

            if use_tools:
                tool_defs = self._prepare_tools_for_grok()
                if tool_defs:
                    chat_kwargs["tools"] = tool_defs

            chat = client.chat.create(**chat_kwargs)
            chat.append(system_fn(resolved_prompt))
            chat.append(user_fn(prompt))

            output: Any
            if use_sdk_parse and config:
                response, parsed = await chat.parse(config.output_type)
                # The SDK may have parsed a truncated payload (or raised a
                # generic error on it): attribute the failure to truncation.
                self._raise_if_truncated(self._extract_finish_reason(response), model=resolved_model)
                output = parsed
            else:
                response = await chat.sample()
                raw_text = response.content or ""
                output = raw_text
                if config:
                    # Known-truncated output must not reach a custom parser either.
                    self._raise_if_truncated(self._extract_finish_reason(response), model=resolved_model)
                    if config.custom_parser:
                        output = config.custom_parser(raw_text)
                    else:
                        output = await self._parse_structured_output(
                            raw_text,
                            config,
                            finish_reason=self._extract_finish_reason(response),
                            model=resolved_model,
                        )

            usage = CompletionUsage.from_grok(response.usage) if hasattr(response, 'usage') else CompletionUsage()
            return self._build_invoke_result(
                output, output_type, resolved_model, usage, response
            )
        except InvokeError:
            raise
        except Exception as exc:
            raise self._handle_invoke_error(exc)
