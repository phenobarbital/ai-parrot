from typing import List, Dict, Any, Optional, Union, AsyncIterator
import os
import asyncio
import logging
import json
import uuid
from enum import Enum
from pathlib import Path
from dataclasses import is_dataclass
from pydantic import BaseModel, TypeAdapter

from xai_sdk import AsyncClient
from xai_sdk.chat import user, system, assistant

from .base import AbstractClient
from ..models import (
    MessageResponse,
    CompletionUsage,
    AIMessage,
    StructuredOutputConfig,
    ToolCall,
    OutputFormat
)
from ..models.responses import InvokeResult
from ..exceptions import InvokeError
from ..tools.abstract import AbstractTool
from ..memory import ConversationTurn
from ..tools.manager import ToolFormat

class GrokModel(str, Enum):
    """Grok model versions."""
    GROK_4_FAST_REASONING = "grok-4-fast-reasoning"
    GROK_4 = "grok-4"
    GROK_4_1_FAST_NON_REASONING = "grok-4-1-fast-non-reasoning"
    GROK_4_1_FAST_REASONING = "grok-4-1-fast-reasoning"
    GROK_3_MINI = "gro-3-mini"
    GROK_CODE_FAST_1 = "grok-code-fast-1"
    GROK_2_IMAGE = "grok-2-image-1212"
    GROK_2_VISION = "grok-2-vision-1212"

class GrokClient(AbstractClient):
    """
    Client for interacting with xAI's Grok models.
    """
    client_type: str = "xai"
    client_name: str = "grok"
    _default_model: str = GrokModel.GROK_4.value
    _lightweight_model: str = "grok-4-1-fast-non-reasoning"

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
            # Try to get from config if available
            try:
                from navconfig import config
                self.api_key = config.get("XAI_API_KEY")
            except ImportError:
                pass
                
        if not self.api_key:
            raise ValueError("XAI_API_KEY not found in environment or config")
            
        self.timeout = timeout
        # NOTE: no self.client = None — base class owns the per-loop cache as a property.

    async def get_client(self) -> AsyncClient:
        """Construct and return a fresh xAI AsyncClient for the current loop.

        The per-loop cache in AbstractClient calls this on a cache miss.
        Do NOT cache here — the base class ``_ensure_client()`` handles that.

        Returns:
            A freshly constructed ``AsyncClient`` instance.
        """
        return AsyncClient(api_key=self.api_key, timeout=self.timeout)

    async def close(self) -> None:
        """Close all per-loop SDK clients.

        Delegates to the base class which safely handles dead / foreign loops.
        """
        await super().close()
        # NOTE: no self.client = None — base close() already cleared the per-loop cache.

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> Any:
        pass

    def _prepare_structured_output_format(self, structured_output: type) -> dict:
        """Prepare response format for structured output using full JSON schema."""
        if not structured_output:
            return {}

        # Normalize instance → class
        if isinstance(structured_output, BaseModel):
            structured_output = structured_output.__class__
        if is_dataclass(structured_output) and not isinstance(structured_output, type):
            structured_output = structured_output.__class__

        schema = None
        name = "structured_output"

        # Pydantic models
        if isinstance(structured_output, type) and hasattr(structured_output, 'model_json_schema'):
            schema = structured_output.model_json_schema()
            name = structured_output.__name__.lower()
        # Dataclasses
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

        # Fallback
        return {"response_format": {"type": "json_object"}}

    def _prepare_tools_for_grok(self) -> List[Dict[str, Any]]:
        """Prepare tools using OpenAI format which is compatible with xAI."""
        # Use ToolManager to get OpenAI formatted schemas
        schemas = self.tool_manager.get_tool_schemas(provider_format=ToolFormat.OPENAI)
        prepared_tools = []
        for schema in schemas:
            # Clean internal keys
            s = schema.copy()
            s.pop('_tool_instance', None)
            
            # Wrap in OpenAI Tool format (xAI SDK specific: no 'type' field)
            prepared_tools.append({
                "function": {
                    "name": s.get("name"),
                    "description": s.get("description"),
                    "parameters": json.dumps(s.get("parameters", {}))
                }
            })
        return prepared_tools

    async def ask(
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = 16000,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
    ) -> MessageResponse:
        """
        Send a prompt to Grok and return the response.
        """
        client = await self.get_client()
        model = model or self.model or self.default_model
        turn_id = str(uuid.uuid4())
        
        # 1. Prepare Structured Output
        response_format = None
        output_config = None
        if structured_output:
            output_config = self._get_structured_config(structured_output)
            if output_config and output_config.output_type:
                 fmt = self._prepare_structured_output_format(output_config.output_type)
                 if fmt:
                     response_format = fmt.get("response_format")
            elif isinstance(structured_output, (type, BaseModel)) or is_dataclass(structured_output):
                 fmt = self._prepare_structured_output_format(structured_output)
                 if fmt:
                     response_format = fmt.get("response_format")

        # 2. Prepare Tools
        _use_tools = use_tools if use_tools is not None else self.enable_tools
        prepared_tools = []
        if _use_tools:
             if tools:
                 # TODO: Normalize manual tools if needed, assuming OpenAI format for now
                 prepared_tools = tools
             else:
                 prepared_tools = self._prepare_tools_for_grok()

        # 3. Initialize Chat
        chat_kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        if response_format:
            chat_kwargs["response_format"] = response_format
            
        if prepared_tools:
             chat_kwargs['tools'] = prepared_tools
             chat_kwargs['tool_choice'] = "auto"

        # Note: xAI SDK stateful 'chat' object might be tricky for tool loops + structured output
        # if we need to modify 'messages' manually. 
        # Using chat.create() creates a new conversation container.
        chat = client.chat.create(**chat_kwargs)

        # 4. Add Context (System, History, User)
        if system_prompt:
            chat.append(system(system_prompt))
            
        if self.conversation_memory and user_id and session_id:
            history = await self.get_conversation(user_id, session_id)
            if history:
                for turn in history.turns:
                     chat.append(user(turn.input))
                     if turn.output:
                         chat.append(assistant(turn.output))

        chat.append(user(prompt))

        # 5. Execution Loop (Tools)
        final_response = None
        all_tool_calls = []
        
        # Limit loops to prevent infinite recursion
        max_turns = 10
        current_turn = 0
        
        while current_turn < max_turns:
            current_turn += 1
            
            try:
                # Execute request
                response = await chat.sample()
                
                # Check for tools
                # xAI SDK response object structure for tool calls needs verification.
                # Assuming standard OpenAI-like or SDK specific attribute.
                # Looking at xai_sdk/chat.py source or behavior would be ideal.
                # Based on `GrokClient` previous implementation attempt and standard patterns:
                # response.tool_calls might exist if using `tool_choice`.
                
                # If the SDK handles tool execution automatically, we might not need this loop?
                # Usually client SDKs don't auto-execute.
                
                tool_calls = getattr(response, 'tool_calls', [])
                if not tool_calls and hasattr(response, 'message'):
                     # Check nested message object if present
                     tool_calls = getattr(response.message, 'tool_calls', [])
                
                # If no tool calls, we are done
                if not tool_calls:
                    final_response = response
                    break
                    
                # Handle Tool Calls
                # response should be added to chat? 
                # The SDK might auto-append the assistants reply to its internal history 
                # if we use `chat.sample()`? 
                # Wait, `chat` is a stateful object. `chat.sample()` returns a response 
                # AND likely updates internal state? 
                # Let's assume `chat` object maintains state. 
                # If we need to add the tool result, we likely check `chat` methods.
                # `chat.append` takes a message.
                # We need to append the tool result.
                
                # For each tool call:
                for tc in tool_calls:
                    fn = tc.function
                    tool_name = fn.name
                    tool_args_str = fn.arguments
                    tool_id = tc.id
                    
                    try:
                        tool_args = json.loads(tool_args_str)
                    except json.JSONDecodeError:
                         # Try cleaning or fallback
                        tool_args = {}
                        
                    # Execute
                    tool_exec_result = await self._execute_tool(tool_name, tool_args)
                    
                    # Create ToolCall record for AIMessage
                    tool_call_rec = ToolCall(
                        id=tool_id,
                        name=tool_name,
                        arguments=tool_args,
                        result=tool_exec_result
                    )
                    all_tool_calls.append(tool_call_rec)
                    
                    # Append result to chat. xAI's API rejects ``name`` on
                    # any role other than ``user`` — use the SDK's
                    # ``tool_result(content, tool_call_id=...)`` signature.
                    from xai_sdk.chat import tool_result as ToolResultMsg
                    chat.append(ToolResultMsg(str(tool_exec_result), tool_call_id=tool_id))
                
                # Loop continues to next sample()
                continue
                
            except Exception as e:
                self.logger.error(f"Error in GrokClient loop: {e}")
                # If failure, break and return what we have or re-raise
                raise
        
        # 6. Parse Final Response
        if not final_response:
             # Should not happen unless max_turns hit without final response
             # Just return last response
             final_response = response

        # Local import to avoid circular dependency
        from ..models.responses import AIMessageFactory

        # Parse structured output if native handling didn't yield an object 
        # (xAI SDK might return object if response_format was used? or just JSON string)
        # Assuming JSON string for safely.
        text_content = final_response.content if hasattr(final_response, 'content') else str(final_response)
        
        structured_payload = None
        if output_config:
            try:
                # If response_format was used, text_content should be JSON
                if output_config.custom_parser:
                    structured_payload = output_config.custom_parser(text_content)
                else:
                    structured_payload = await self._parse_structured_output(text_content, output_config)
            except Exception:
                # If parsing failed, keep as text
                pass

        ai_message = AIMessageFactory.create_message(
            response=final_response,
            input_text=prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            usage=CompletionUsage.from_grok(final_response.usage) if hasattr(final_response, 'usage') else None,
            text_response=text_content
        )
        
        ai_message.tool_calls = all_tool_calls
        if structured_payload:
            ai_message.structured_output = structured_payload
            ai_message.is_structured = True
            ai_message.output = structured_payload # Swap if structured is primary

        if user_id and session_id:
             turn = ConversationTurn(
                turn_id=turn_id,
                user_id=user_id,
                user_message=prompt,
                assistant_response=ai_message.to_text,
                tools_used=[t.name for t in ai_message.tool_calls] if ai_message.tool_calls else [],
                metadata=ai_message.usage.dict() if ai_message.usage else None
            )
             await self.conversation_memory.add_turn(
                user_id, 
                session_id, 
                turn
            )

        return ai_message

    async def ask_stream(
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = 16000,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncIterator[str]:
        """
        Stream response from Grok.
        """
        turn_id = str(uuid.uuid4())
        client = await self.get_client()
        model = model or self.model or self.default_model

        chat_kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True 
        }

        if structured_output:
            config = self._get_structured_config(structured_output)
            if config:
                if output_config and output_config.output_type:
                     fmt = self._prepare_structured_output_format(output_config.output_type)
                     if fmt:
                         chat_kwargs["response_format"] = fmt.get("response_format")
                elif isinstance(structured_output, (type, BaseModel)) or is_dataclass(structured_output):
                     fmt = self._prepare_structured_output_format(structured_output)
                     if fmt:
                         chat_kwargs["response_format"] = fmt.get("response_format")

        chat = client.chat.create(**chat_kwargs)

        if system_prompt:
            chat.append(system(system_prompt))

        if self.conversation_memory and user_id and session_id:
            history = await self.get_conversation(user_id, session_id)
            if history:
                for turn in history.turns:
                    chat.append(user(turn.input))
                    if turn.output:
                        chat.append(assistant(turn.output))

        chat.append(user(prompt))
        
        full_response = []
        
        async for token in chat.stream():
            content = token 
            if hasattr(token, 'choices'):
                 delta = token.choices[0].delta
                 if hasattr(delta, 'content'):
                     content = delta.content
            elif hasattr(token, 'content'):
                 content = token.content
            
            if content:
                full_response.append(content)
                yield content

        if user_id and session_id:
            turn = ConversationTurn(
                turn_id=turn_id,
                user_id=user_id,
                user_message=prompt,
                assistant_response="".join(full_response)
            )
            await self.conversation_memory.add_turn(
                user_id,
                session_id,
                turn
            )

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

        Args:
            session_id: Session identifier (propagated to the AIMessage and to
                any ``HumanInteractionInterrupt`` raised inside the loop).
            user_input: User reply to inject into the conversation as the
                resumption value.
            state: Suspended state — expects keys ``messages`` (list of
                OpenAI-style dicts with ``role`` / ``content`` / ``tool_calls``),
                ``tool_call_id`` (optional) and ``agent_name`` / ``model``
                (optional, used to pick the model).

        Returns:
            :class:`AIMessage` with the final assistant response and the list
            of tool calls that ran during resumption.
        """
        from xai_sdk.chat import tool_result as ToolResultMsg
        from ..models.responses import AIMessageFactory

        client = await self.get_client()
        messages: List[Dict[str, Any]] = state.get("messages", [])
        tool_call_id = state.get("tool_call_id")
        model = state.get("agent_name") or state.get("model") or self.model or self._default_model
        turn_id = str(uuid.uuid4())

        # Re-create a stateful chat from the suspended history.
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

        # Replay history into the new chat object.
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content") or ""
            if role == "system":
                chat.append(system(content))
            elif role == "user":
                chat.append(user(content))
            elif role == "assistant":
                chat.append(assistant(content))
            elif role == "tool":
                chat.append(
                    ToolResultMsg(
                        content,
                        tool_call_id=msg.get("tool_call_id") or msg.get("name"),
                    )
                )

        # Inject the resumption value: as a tool_result if we paused inside a
        # tool call, otherwise as a regular user turn.
        if tool_call_id:
            chat.append(ToolResultMsg(user_input, tool_call_id=tool_call_id))
        else:
            chat.append(user(user_input))

        # Continue the tool-call loop just like ``ask()`` does.
        all_tool_calls: List[ToolCall] = []
        max_turns = 10
        current_turn = 0
        final_response = None

        while current_turn < max_turns:
            current_turn += 1
            response = await chat.sample()

            tool_calls = getattr(response, "tool_calls", []) or []
            if not tool_calls and hasattr(response, "message"):
                tool_calls = getattr(response.message, "tool_calls", []) or []

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
                    chat.append(ToolResultMsg(str(tool_exec_result), tool_call_id=tc.id))
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
                    chat.append(ToolResultMsg(f"Error: {exc}", tool_call_id=tc.id))

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
        max_tokens: int = 4096,
        temperature: float = 0.0,
        use_tools: bool = False,
        tools: Optional[list] = None,
    ) -> InvokeResult:
        """Lightweight stateless invocation for GrokClient.

        Uses native ``json_schema`` response_format with ``strict: True`` for
        structured output (same approach as OpenAI).  A single SDK call is made
        — no retry, no history, no prompt builder.

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

            await self._ensure_client()

            messages = [
                {"role": "system", "content": resolved_prompt},
                {"role": "user", "content": prompt},
            ]

            kwargs: Dict[str, Any] = {
                "model": resolved_model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages,
            }

            # Native JSON schema structured output
            if config:
                schema = config.get_schema()
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": config.output_type.__name__,
                        "schema": schema,
                        "strict": True,
                    },
                }

            # Tools
            if use_tools:
                tool_defs = self._prepare_tools_for_grok()
                if tool_defs:
                    kwargs["tools"] = tool_defs

            response = await self.client.chat.completions.create(**kwargs)
            raw_text = response.choices[0].message.content or ""

            # Parse output
            output: Any = raw_text
            if config:
                if config.custom_parser:
                    output = config.custom_parser(raw_text)
                else:
                    output = await self._parse_structured_output(raw_text, config)

            usage = CompletionUsage.from_grok(response.usage) if hasattr(response, 'usage') else CompletionUsage()
            return self._build_invoke_result(
                output, output_type, resolved_model, usage, response
            )
        except InvokeError:
            raise
        except Exception as exc:
            raise self._handle_invoke_error(exc)
