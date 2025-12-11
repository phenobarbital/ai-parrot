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
from ..tools.abstract import AbstractTool
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
        self.client: Optional[AsyncClient] = None

    async def get_client(self) -> AsyncClient:
        """Return the xAI AsyncClient instance."""
        if not self.client:
            self.client = AsyncClient(
                api_key=self.api_key,
                timeout=self.timeout
            )
        return self.client

    async def close(self):
        """Close the client connection."""
        await super().close()
        self.client = None

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
        return self.tool_manager.get_tool_schemas(provider_format=ToolFormat.OPENAI)

    async def ask(
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = 4096,
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
                    
                    # Append result to chat
                    # xAI SDK likely has a `tool` message type
                    from xai_sdk.chat import tool_result as ToolResultMsg
                    msg = ToolResultMsg(str(tool_exec_result))
                    # xAI SDK proto does not have tool_call_id, assuming name or order maps it.
                    # Using name field for tool_call_id as best guess for OpenAI compatibility
                    msg.name = tool_id
                    chat.append(msg)
                
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
             await self.conversation_memory.add_turn(
                user_id, 
                session_id, 
                prompt, 
                ai_message.to_text,
                metadata=ai_message.usage.dict() if ai_message.usage else None
            )

        return ai_message

    async def ask_stream(
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = 4096,
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
            await self.conversation_memory.add_turn(
                user_id,
                session_id,
                prompt,
                "".join(full_response)
            )

    async def batch_ask(self, requests: List[Any]) -> List[Any]:
        """Batch processing not yet implemented for Grok."""
        raise NotImplementedError("Batch processing not supported for Grok yet")
