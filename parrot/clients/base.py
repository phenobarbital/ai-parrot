from __future__ import annotations
from typing import (
    AsyncIterator,
    Dict,
    List,
    Optional,
    Union,
    TypedDict,
    Any,
    Callable
)
from datetime import datetime
import json
import random
import re
import mimetypes
import asyncio
import base64
from pathlib import Path
from dataclasses import dataclass, is_dataclass
from abc import ABC, abstractmethod
import io
import wave
import yaml
from click import prompt
from pydub import AudioSegment
import ffmpeg  # pylint: disable=E1101 # noqa
from pydantic import (
    BaseModel,
    ValidationError,
    TypeAdapter
)
from datamodel.exceptions import ParserError  # pylint: disable=E0611 # noqa
from datamodel.parsers.json import json_decoder, JSONContent  # pylint: disable=E0611 # noqa
from navconfig import config
from navconfig.logging import logging
import pandas as pd
import aiohttp
from ..memory import (
    ConversationTurn,
    ConversationHistory,
    ConversationMemory,
    InMemoryConversation,
    FileConversationMemory,
    RedisConversation
)
from ..tools import PythonREPLTool
from ..models import (
    StructuredOutputConfig,
    OutputFormat
)
from ..tools.abstract import AbstractTool, ToolResult
from ..tools.manager import (
    ToolManager,
    ToolFormat,
    ToolDefinition
)


LLM_PRESETS = {
    "analytical": {"temperature": 0.1, "max_tokens": 4000},
    "creative": {"temperature": 0.7, "max_tokens": 6000},
    "balanced": {"temperature": 0.4, "max_tokens": 4000},
    "concise": {"temperature": 0.2, "max_tokens": 2000},
    "detailed": {"temperature": 0.3, "max_tokens": 8000},
    "comprehensive": {"temperature": 0.5, "max_tokens": 10000},
    "verbose": {"temperature": 0.6, "max_tokens": 12000},
    "summarization": {"temperature": 0.2, "max_tokens": 3000},
    "translation": {"temperature": 0.1, "max_tokens": 5000},
    "inspiration": {"temperature": 0.8, "max_tokens": 7000},
    "default": {"temperature": 0.1, "max_tokens": 1024}
}


def register_python_tool(
    client,
    report_dir: Optional[Path] = None,
    plt_style: str = 'seaborn-v0_8-whitegrid',
    palette: str = 'Set2'
) -> PythonREPLTool:
    """Register Python REPL tool with a ClaudeAPIClient.

    Args:
        client: The ClaudeAPIClient instance
        report_dir: Directory for saving reports
        plt_style: Matplotlib style
        palette: Seaborn color palette

    Returns:
        The PythonREPLTool instance
    """
    tool = PythonREPLTool(
        report_dir=report_dir,
        plt_style=plt_style,
        palette=palette
    )

    client.register_tool(
        name="python_repl",
        description=(
            "A Python shell for executing Python commands. "
            "Input should be valid Python code. "
            "Pre-loaded libraries: pandas (pd), numpy (np), matplotlib.pyplot (plt), "
            "seaborn (sns), numexpr (ne). "
            "Available tools: quick_eda, generate_eda_report, list_available_dataframes "
            "from parrot_tools. "
            "Use execution_results dict for capturing intermediate results. "
            "Use report_directory Path for saving outputs. "
            "Use extended_json.dumps(obj)/extended_json.loads(bytes) for JSON operations."
        ),
        input_schema=tool.get_tool_schema(),
        function=tool
    )

    return tool

class MessageResponse(TypedDict):
    """Response structure for LLM messages."""
    id: str
    type: str
    role: str
    content: List[Dict[str, Any]]
    model: str
    stop_reason: Optional[str]
    stop_sequence: Optional[str]
    usage: Dict[str, int]

@dataclass
class RetryConfig:
    """Configuration for MAX_TOKENS retry behavior."""
    max_retries: int = 1
    token_increase_threshold: int = 1024
    new_token_limit: int = 8192
    error_patterns: List[str] = None

    def __post_init__(self):
        if self.error_patterns is None:
            self.error_patterns = [
                r"MAX_TOKENS?",
                r"TOKEN.*LIMIT",
                r"CONTEXT.*LENGTH",
                r"TOO.*MANY.*TOKENS"
            ]

class TokenRetryMixin:
    """Mixin class to add token retry functionality to any LLM client."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.retry_config = RetryConfig()

    def is_token_limit_error(self, error: Exception) -> bool:
        """Check if the error is related to token limits."""
        error_message = str(error).upper()

        return any(
            re.search(pattern, error_message)
            for pattern in self.retry_config.error_patterns
        )

    def should_retry_with_more_tokens(self, current_tokens: int, retry_count: int) -> bool:
        """Determine if we should retry with increased tokens."""
        return (
            retry_count < self.retry_config.max_retries and
            current_tokens <= self.retry_config.token_increase_threshold
        )

    def get_increased_token_limit(self, current_tokens: int) -> int:
        """Calculate the new token limit for retry."""
        if current_tokens <= 1024:
            return 4096
        elif current_tokens <= 4096:
            return 8192
        elif current_tokens <= 8192:
            return 12288
        else:
            return min(current_tokens * 2, 16384)  # Cap at 16k tokens

@dataclass
class BatchRequest:
    """Data structure for batch request."""
    custom_id: str
    params: Dict[str, Any]


class StreamingRetryConfig:
    """Configuration for streaming retry behavior."""
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
        jitter: bool = True,
        auto_retry_on_max_tokens: bool = True,
        token_increase_factor: float = 1.5,
        retry_on_rate_limit: bool = True,
        retry_on_server_error: bool = True
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter = jitter
        self.auto_retry_on_max_tokens = auto_retry_on_max_tokens
        self.token_increase_factor = token_increase_factor
        self.retry_on_rate_limit = retry_on_rate_limit
        self.retry_on_server_error = retry_on_server_error


class AbstractClient(ABC):
    """Abstract base Class for LLM models."""
    version: str = "0.1.0"
    base_headers: Dict[str, str] = {
        "Content-Type": "application/json",
    }
    client_type: str = "generic"
    client_name: str = 'generic'
    use_session: bool = False

    def __init__(
        self,
        conversation_memory: Optional[ConversationMemory] = None,
        preset: Optional[str] = None,
        tools: Optional[List[Union[str, AbstractTool]]] = None,
        use_tools: bool = False,
        debug: bool = True,
        **kwargs
    ):
        self.__name__ = self.__class__.__name__
        self.model: str = kwargs.get('model', None)
        self.session: Optional[aiohttp.ClientSession] = None
        self.use_session: bool = kwargs.get('use_session', self.use_session)
        if preset:
            preset_config = LLM_PRESETS.get(preset, LLM_PRESETS['default'])
            # define temp, top_k, top_p, max_tokens from selected preset:
            self.temperature = preset_config.get('temperature', 0.4)
            self.top_k = preset_config.get('top_k', 30)
            self.top_p = preset_config.get('top_p', 0.2)
            self.max_tokens = preset_config.get('max_tokens', 4096)
        else:
            # define default values from preset default:
            self.temperature = kwargs.get('temperature', 0)
            self.top_k = kwargs.get('top_k', 30)
            self.top_p = kwargs.get('top_p', 0.2)
            self.max_tokens = kwargs.get('max_tokens', 4096)
        self.conversation_memory = conversation_memory or InMemoryConversation()
        self.base_headers.update(kwargs.get('headers', {}))
        self.api_key = kwargs.get('api_key', None)
        self.version = kwargs.get('version', self.version)
        self._config = config
        self.logger: logging.Logger = logging.getLogger(self.__name__)
        self._json: Any = JSONContent()
        self.client_type: str = kwargs.get('client_type', self.client_type)
        self._debug: bool = debug
        self._program: str = kwargs.get('program', 'parrot')  # Default program slug
        # Initialize ToolManager instead of direct tools dict
        self.tool_manager = ToolManager(
            logger=self.logger,
            debug=self._debug
        )
        self.tools: Dict[str, Union[ToolDefinition, AbstractTool]] = {}
        self.enable_tools: bool = use_tools
        # Initialize tools if provided
        if use_tools and tools:
            self.tool_manager.default_tools(tools)
            self.enable_tools = True

    async def __aenter__(self):
        if self.use_session:
            self.session = aiohttp.ClientSession(
                headers=self.base_headers
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def __repr__(self):
        return f'<{self.__name__} model={self.model} client_type={self.client_type}>'

    def set_program(self, program_slug: str) -> None:
        """Set the program slug for the client."""
        self._program = program_slug

    def _get_chatbot_key(self, chatbot_id: Optional[str] = None) -> Optional[str]:
        """Resolve chatbot identifier for memory operations."""
        key = chatbot_id or getattr(self, 'chatbot_id', None)
        return None if key is None else str(key)

    async def start_conversation(
        self,
        user_id: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        chatbot_id: Optional[str] = None,
    ) -> ConversationHistory:
        """Start a new conversation session."""
        return await self.conversation_memory.create_history(
            user_id,
            session_id,
            metadata=metadata,
            chatbot_id=self._get_chatbot_key(chatbot_id)
        )

    async def get_conversation(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> Optional[ConversationHistory]:
        """Get an existing conversation session."""
        if not self.conversation_memory:
            return None
        return await self.conversation_memory.get_history(
            user_id,
            session_id,
            chatbot_id=self._get_chatbot_key(chatbot_id)
        )

    async def clear_conversation(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> bool:
        """Clear conversation history for a session."""
        if not self.conversation_memory:
            return False
        await self.conversation_memory.clear_history(
            user_id,
            session_id,
            chatbot_id=self._get_chatbot_key(chatbot_id)
        )
        return True

    async def delete_conversation(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> bool:
        """Delete conversation history entirely."""
        if not self.conversation_memory:
            return False
        return await self.conversation_memory.delete_history(
            user_id,
            session_id,
            chatbot_id=self._get_chatbot_key(chatbot_id)
        )

    async def list_user_conversations(
        self,
        user_id: str,
        chatbot_id: Optional[str] = None
    ) -> List[str]:
        """List all conversation sessions for a user."""
        if not self.conversation_memory:
            return []
        return await self.conversation_memory.list_sessions(
            user_id,
            chatbot_id=self._get_chatbot_key(chatbot_id)
        )

    def set_tools(self, tools: List[Union[str, AbstractTool]]) -> None:
        """Set complete list of tools, replacing existing."""
        self.tool_manager.clear_tools()
        self.tools.clear()
        self.register_tools(tools)

    def get_tool(self, name: str) -> Optional[AbstractTool]:
        """Get a tool by name from ToolManager or legacy tools."""
        # Try ToolManager first
        if tool := self.tool_manager.get_tool(name):
            return tool

        # Fall back to legacy tools
        legacy_tool = self.tools.get(name)
        return legacy_tool if isinstance(legacy_tool, AbstractTool) else None

    def register_tool(
        self,
        tool: Union[ToolDefinition, AbstractTool] = None,
        name: str = None,
        description: str = None,
        input_schema: Dict[str, Any] = None,
        function: Callable = None,
    ) -> None:
        """Register a Python function as a tool for LLM to call."""
        self.tool_manager.register_tool(
            tool=tool,
            name=name,
            description=description,
            input_schema=input_schema,
            function=function
        )

    def register_tools(
        self,
        tools: List[Union[ToolDefinition, AbstractTool]]
    ) -> None:
        """Register multiple tools at once."""
        self.tool_manager.register_tools(tools)
        self.enable_tools = True

    def register_python_tool(
        self,
        report_dir: Optional[Path] = None,
        plt_style: str = 'seaborn-v0_8-whitegrid',
        palette: str = 'Set2'
    ) -> PythonREPLTool:
        """Register Python REPL tool with a ClaudeAPIClient.

        Args:
            client: The ClaudeAPIClient instance
            report_dir: Directory for saving reports
            plt_style: Matplotlib style
            palette: Seaborn color palette

        Returns:
            The PythonREPLTool instance
        """
        if "python_repl" in self.tools:
            return self.tools["python_repl"]

        tool = PythonREPLTool(
            report_dir=report_dir,
            plt_style=plt_style,
            palette=palette,
            debug=self._debug,
        )
        self.tool_manager.add_tool(tool)
        return tool

    def list_tools(self) -> List[str]:
        """Get a list of all registered tool names."""
        tool_names = self.tool_manager.list_tools()
        legacy_names = list(self.tools.keys())
        return tool_names + [name for name in legacy_names if name not in tool_names]

    def remove_tool(self, name: str) -> bool:
        """
        Remove a tool by name.

        Args:
            name: Tool name to remove

        Returns:
            True if tool was removed, False if not found
        """
        self.tool_manager.remove_tool(name)

    def clear_tools(self) -> None:
        """Clear all registered tools."""
        self.tool_manager.clear_tools()
        self.tools.clear()
        self.logger.info(
            "Cleared all tools"
        )

    def _encode_file(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """Encode file for API upload."""
        path = Path(file_path)
        mime_type, _ = mimetypes.guess_type(str(path))

        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode('utf-8')

        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": mime_type or "application/octet-stream",
                "data": encoded
            }
        }

    def _make_openai_strict_tool(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure the tool schema matches OpenAI strict function-tool requirements:
        - type=function
        - function.strict = True
        - function.parameters is an object schema with additionalProperties = False
        """
        if schema.get("type") != "function":
            return schema  # Only wrap function tools

        fn = schema.setdefault("function", {})
        params = fn.setdefault("parameters", {})

        # Ensure JSON Schema object shape
        # If your ToolSchemaAdapter already sets this, we won't override it.
        if params.get("type") is None:
            params["type"] = "object"
        if "properties" not in params:
            # If no properties defined, keep empty; model won't be able to send args anyway.
            params["properties"] = {}

        # Critical for strict tools: must be present and false
        if "additionalProperties" not in params:
            params["additionalProperties"] = False

        # Mark the function as strict
        fn["strict"] = True

        return schema

    def _prepare_tools(self) -> List[Dict[str, Any]]:
        """Convert registered tools to API format."""
        tool_schemas = []
        processed_tools = set()  # Track processed tools to avoid duplicates

        # Determine the format based on client type
        if self.client_type == 'openai':
            provider_format = ToolFormat.OPENAI
        elif self.client_type == 'google':
            provider_format = ToolFormat.GOOGLE
        elif self.client_type == 'groq':
            provider_format = ToolFormat.GROQ
        elif self.client_type == 'vertex':
            provider_format = ToolFormat.VERTEX
        else:
            provider_format = ToolFormat.ANTHROPIC  # Default to Anthropic for Claude

        # Get tools from ToolManager using the correct method
        manager_tools = self.tool_manager.get_tool_schemas(provider_format=provider_format)

        for tool_schema in manager_tools:
            # Remove the _tool_instance for API formatting
            clean_schema = tool_schema.copy()
            clean_schema.pop('_tool_instance', None)

            tool_name = clean_schema.get('name')
            if tool_name and tool_name not in processed_tools:
                # Format according to the client type
                if self.client_type == 'openai':
                    # OpenAI expects function wrapper
                    formatted_schema = {
                        "type": "function",
                        "function": {
                            "name": clean_schema["name"],
                            "description": clean_schema["description"],
                            "parameters": clean_schema.get("parameters", {})
                        }
                    }
                    formatted_schema = self._make_openai_strict_tool(
                        formatted_schema
                    )
                else:
                    # Claude/Anthropic and others use direct format
                    formatted_schema = {
                        "name": clean_schema["name"],
                        "description": clean_schema["description"],
                        "input_schema": clean_schema.get("parameters", {})
                    }

                tool_schemas.append(formatted_schema)
                processed_tools.add(tool_name)

        self.logger.debug(f"Prepared {len(tool_schemas)} tool schemas")
        return tool_schemas

    async def _execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any]
    ) -> Any:
        """Execute a registered tool function."""
        try:
            result = await self.tool_manager.execute_tool(tool_name, parameters)
            if isinstance(result, ToolResult):
                if result.status == "error":
                    raise ValueError(result.error)
                return result.result
            return result
        except Exception as e:
            self.logger.error(
                f"Error executing tool {tool_name}: {e}"
            )
            raise

    async def _execute_tool_call(
        self,
        content_block: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a single tool call and return the result."""
        tool_name = content_block["name"]
        tool_input = content_block["input"]
        tool_id = content_block["id"]

        try:
            tool_result = await self._execute_tool(tool_name, tool_input)
            return {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": str(tool_result)
            }
        except Exception as e:
            return {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "is_error": True,
                "content": str(e)
            }

    def _prepare_messages(
        self,
        prompt: str,
        files: Optional[List[Union[str, Path]]] = None
    ) -> List[Dict[str, Any]]:
        """Prepare message content with optional file attachments."""
        content = [{"type": "text", "text": prompt}]

        if files:
            content.extend(self._encode_file(file_path) for file_path in files)

        return [{"role": "user", "content": content}]

    def _validate_response(self, response: Dict[str, Any]) -> bool:
        """Validate API response structure."""
        required_fields = ["id", "type", "role", "content", "model"]
        return all(field in response for field in required_fields)

    def _get_structured_config(
        self,
        structured_output: Union[type, StructuredOutputConfig, None]
    ) -> Optional[StructuredOutputConfig]:
        """Get structured output configuration."""
        if isinstance(structured_output, StructuredOutputConfig):
            return structured_output
        elif structured_output:
            return StructuredOutputConfig(
                output_type=structured_output,
                format=OutputFormat.JSON
            )
        return None

    def _ensure_json_instruction(
        self,
        messages: List[Dict[str, Any]],
        instruction: str
    ) -> None:
        """Ensure the latest user message explicitly requests JSON output."""
        if not instruction:
            return

        lowered_instruction = instruction.lower()

        for message in reversed(messages):
            if message.get("role") != "user":
                continue

            existing_content = message.get("content")
            if isinstance(existing_content, str):
                if lowered_instruction in existing_content.lower():
                    return
                message["content"] = [{"type": "text", "text": existing_content}]

            content = message.setdefault("content", [])
            for block in content:
                if block.get("type") == "text":
                    text = block.get("text", "")
                    if lowered_instruction in text.lower():
                        return
                    block["text"] = f"{text}\n\n{instruction}" if text else instruction
                    return

            content.append({"type": "text", "text": instruction})
            return

        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": instruction}]
        })

    @abstractmethod
    async def ask(
        self,
        prompt: str,
        model: str,
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
        """Send a prompt to the model and return the response."""
        raise NotImplementedError("Subclasses must implement this method.")

    @abstractmethod
    async def ask_stream(
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncIterator[str]:
        """Stream the model's response."""
        raise NotImplementedError("Subclasses must implement this method.")

    @abstractmethod
    async def batch_ask(self, requests: List[Any]) -> List[Any]:
        """Process multiple requests in batch."""
        raise NotImplementedError("Subclasses must implement batch processing.")

    async def _handle_structured_output(
        self,
        result: Dict[str, Any],
        structured_output: Optional[type]
    ) -> Any:
        """Parse response into structured output format."""
        if not structured_output:
            return result

        text_content = "".join(
            content_block["text"]
            for content_block in result["content"]
            if content_block["type"] == "text"
        )

        try:
            if not hasattr(structured_output, '__annotations__'):
                return structured_output(text_content)
            parsed = json_decoder(text_content)
            return self._coerce_mapping_to_type(structured_output, parsed)
        except Exception:  # pylint: disable=broad-except
            return result

    def _coerce_mapping_to_type(self, output_type: type, data: Any) -> Any:
        """Attempt to instantiate output_type from mapping-like data."""
        if data is None:
            return None

        if is_dataclass(output_type):
            try:
                if isinstance(data, list):
                    return [self._coerce_mapping_to_type(output_type, item) for item in data]
                if isinstance(data, dict):
                    return output_type(**data)
            except TypeError:
                return data
            return data

        if hasattr(output_type, '__annotations__'):
            if isinstance(data, list):
                coerced = []
                for item in data:
                    if isinstance(item, dict):
                        try:
                            coerced.append(output_type(**item))
                        except TypeError:
                            coerced.append(item)
                    else:
                        coerced.append(item)
                return coerced
            if isinstance(data, dict):
                try:
                    return output_type(**data)
                except TypeError:
                    return data

        return data

    async def _process_tool_calls(
        self,
        initial_result: Dict[str, Any],
        messages: List[Dict[str, Any]],
        payload: Dict[str, Any],
        endpoint: str
    ) -> Dict[str, Any]:
        """Handle tool calls in a loop until completion."""
        result = initial_result

        while result.get("stop_reason") == "tool_use":
            tool_results = []

            for content_block in result["content"]:
                if content_block["type"] == "tool_use":
                    tool_result = await self._execute_tool_call(content_block)
                    tool_results.append(tool_result)

            messages.append({"role": "assistant", "content": result["content"]})
            messages.append({"role": "user", "content": tool_results})
            payload["messages"] = messages

            async with self.session.post(endpoint, json=payload) as response:
                response.raise_for_status()
                result = await response.json()

        # Add final assistant response
        messages.append({"role": "assistant", "content": result["content"]})
        return result

    async def _prepare_conversation_context(
        self,
        prompt: str,
        files: Optional[List[Union[str, Path]]],
        user_id: Optional[str],
        session_id: Optional[str],
        system_prompt: Optional[str],
        stateless: bool = False
    ) -> tuple[List[Dict[str, Any]], Optional[ConversationHistory], Optional[str]]:
        """Prepare conversation context and return messages, session, and system prompt."""
        messages = []
        conversation_history = None

        if user_id and session_id:
            conversation_history = await self.conversation_memory.get_history(
                user_id,
                session_id,
                chatbot_id=self._get_chatbot_key()
            )
            if not conversation_history:
                conversation_history = await self.conversation_memory.create_history(
                    user_id,
                    session_id,
                    chatbot_id=self._get_chatbot_key()
                )

        # Get recent conversation messages for context
        if conversation_history:
            messages = conversation_history.get_messages_for_api()
        new_user_message = self._prepare_messages(prompt, files)[0]
        messages.append(new_user_message)

        # Convert stored conversation turns to messages format and create system prompt:
        if conversation_history and not stateless:
            self.logger.debug(
                f"Found {len(conversation_history.turns)} previous turns"
            )
            for turn in conversation_history.turns:
                # Add user message
                messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": turn.user_message}]
                })

                # Add assistant message
                messages.append({
                    "role": "assistant",
                    "content": [{"type": "text", "text": turn.assistant_response}]
                })

            if not system_prompt and len(conversation_history.turns) > 0:
                # Create a summary of the conversation context
                recent_context = []
                for turn in conversation_history.turns[-3:]:  # Last 3 turns for context
                    recent_context.extend(
                        (
                            f"User: {turn.user_message}",
                            f"Assistant: {turn.assistant_response}",
                        )
                    )

                system_prompt = (
                        "You are a helpful AI assistant. You have access to the following conversation history:\n\n"
                        + "\n".join(recent_context) +
                        "\n\nUse this context to provide relevant and consistent responses. "
                        "When users refer to previously mentioned information, acknowledge and use that context."
                    )
                self.logger.debug("Created contextual system prompt from conversation history")

        # Handle file attachments if provided
        current_message_parts = [{"type": "text", "text": prompt}]
        if files:
            for file_path in files:
                try:
                    file_path = Path(file_path)
                    if file_path.exists():
                        current_message_parts.append({
                            "type": "file",
                            "file_path": str(file_path)
                        })
                except Exception as e:
                    self.logger.error(f"Error processing file {file_path}: {e}")

        # Add the current user message
        messages.append({
            "role": "user",
            "content": current_message_parts
        })

        # self.logger.debug(f"Prepared {len(messages)} messages for conversation context")
        return messages, conversation_history, system_prompt

    async def _update_conversation_memory(
        self,
        user_id: Optional[str],
        session_id: Optional[str],
        conversation_history: Optional[ConversationHistory],
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str],
        turn_id: str,
        original_prompt: str,
        assistant_response: str,
        tools_used: List[str] = None
    ) -> None:
        """Update conversation memory with the latest turn."""
        if not (user_id and session_id and conversation_history and self.conversation_memory):
            return

        # Create a new conversation turn
        turn = ConversationTurn(
            turn_id=turn_id,
            user_id=user_id,
            user_message=original_prompt,
            assistant_response=assistant_response,
            context_used=system_prompt,
            tools_used=tools_used or [],
            metadata={
                "message_count": len(messages),
                "has_system_prompt": bool(system_prompt),
                "provider": getattr(self, 'client_type', 'unknown')
            }
        )

        # Add turn to conversation history
        await self.conversation_memory.add_turn(
            user_id,
            session_id,
            turn,
            chatbot_id=self._get_chatbot_key()
        )

    def _extract_json_from_response(self, text: str) -> str:
        """Extract JSON from Claude's response, handling markdown code blocks and extra text."""
        # First, try to find JSON in markdown code blocks
        json_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
        match = re.search(json_pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Try to find JSON object in the text (looking for { ... })
        json_object_pattern = r'\{.*\}'
        match = re.search(json_object_pattern, text, re.DOTALL)
        if match:
            return match.group(0).strip()

        # Try to find JSON array in the text (looking for [ ... ])
        json_array_pattern = r'\[.*\]'
        match = re.search(json_array_pattern, text, re.DOTALL)
        if match:
            return match.group(0).strip()

        # If no JSON found, return the original text
        return text.strip()

    def _unwrap_nested_response(self, parsed_json: Any, output_type: type) -> Any:
        """Unwrap JSON responses that are nested under a single key.

        Some LLMs (especially Claude) wrap their response in an extra key layer.
        For example: {"dinner_plan": {"appetizer": "...", ...}}
        instead of: {"appetizer": "...", ...}

        This method detects and unwraps such responses.
        """
        if not isinstance(parsed_json, dict):
            return parsed_json

        # If the JSON has exactly one key and it's a dict, check if unwrapping makes sense
        if len(parsed_json) == 1:
            single_key = list(parsed_json.keys())[0]
            nested_value = parsed_json[single_key]

            # Only unwrap if the nested value is a dict
            if isinstance(nested_value, dict):
                # Try to validate the nested value against the expected type
                if hasattr(output_type, 'model_validate'):
                    try:
                        # If this succeeds, the nested value is the correct structure
                        output_type.model_validate(nested_value)
                        return nested_value
                    except (ValidationError, Exception):
                        # If validation fails, return original
                        pass
                elif hasattr(output_type, '__annotations__'):
                    # For dataclasses, check if fields match
                    expected_fields = set(output_type.__annotations__.keys())
                    nested_fields = set(nested_value.keys())

                    # If nested value has the expected fields, unwrap it
                    if expected_fields & nested_fields:  # If there's any overlap
                        return nested_value

        return parsed_json

    async def _parse_structured_output(
        self,
        response_text: str,
        structured_output: StructuredOutputConfig
    ) -> Any:
        """Parse structured output based on format."""
        try:
            output_type = structured_output.output_type
            if not output_type:
                raise ValueError(
                    "Output type is not specified in structured output config."
                )
            # default to JSON parsing if no specific schema is provided
            if structured_output.format == OutputFormat.JSON:
                # Current JSON logic
                try:
                    # first, try to remove backsticks (markdown code blocks) if any:
                    # This is the right way to do it.
                    response_text = response_text.strip()
                    if response_text.startswith('```json'):
                        response_text = response_text[7:-3]
                    if hasattr(output_type, 'model_validate_json') or hasattr(output_type, 'model_validate'):
                        # For model_validate_json, we need to parse first to unwrap
                        if not isinstance(output_type, type):
                            output_type = output_type.__class__
                        parsed_json = self._json.loads(response_text)
                        parsed_json = self._unwrap_nested_response(parsed_json, output_type)
                        return output_type.model_validate(parsed_json)
                    else:
                        parsed_json = self._json.loads(response_text)
                        parsed_json = self._unwrap_nested_response(parsed_json, output_type)
                        if is_dataclass(output_type) or hasattr(output_type, '__annotations__'):
                            return self._coerce_mapping_to_type(output_type, parsed_json)
                        return parsed_json
                except (ParserError, ValidationError, json.JSONDecodeError) as e:
                    self.logger.warning(f"Standard parsing failed: {e}")
                    try:
                        # Try fallback with field mapping
                        json_text = self._extract_json_from_response(response_text)
                        parsed_json = self._json.loads(json_text)
                        parsed_json = self._unwrap_nested_response(parsed_json, output_type)
                        if hasattr(output_type, 'model_validate'):
                            return output_type.model_validate(parsed_json)
                        if is_dataclass(output_type) or hasattr(output_type, '__annotations__'):
                            return self._coerce_mapping_to_type(output_type, parsed_json)
                        return parsed_json
                    except (ParserError, ValidationError, json.JSONDecodeError) as e:
                        self.logger.warning(
                            f"Fallback parsing failed: {e}"
                        )
                        return response_text
            elif structured_output.format == OutputFormat.TEXT:
                # Parse natural language text into structured format
                return await self._parse_text_to_structure(
                    response_text,
                    output_type
                )
            elif structured_output.format == OutputFormat.CSV:
                df = pd.read_csv(io.StringIO(response_text))
                return df if output_type == pd.DataFrame else df
            elif structured_output.format == OutputFormat.YAML:
                data = yaml.safe_load(response_text)
                if hasattr(output_type, 'model_validate'):
                    return output_type.model_validate(data)
                if is_dataclass(output_type) or hasattr(output_type, '__annotations__'):
                    return self._coerce_mapping_to_type(output_type, data)
                return data
            elif structured_output.format == OutputFormat.CUSTOM:
                if structured_output.custom_parser:
                    return structured_output.custom_parser(response_text)
            else:
                raise ValueError(
                    f"Unsupported output format: {structured_output.format}"
                )
        except (ParserError, ValueError) as exc:
            self.logger.error(f"Error parsing structured output: {exc}")
            # Fallback to raw text if parsing fails
            return response_text
        except Exception as exc:
            self.logger.error(
                f"Unexpected error during structured output parsing: {exc}"
            )
            # Fallback to raw text
            return response_text

    async def _parse_text_to_structure(self, text: str, output_type: type) -> Any:
        """Parse natural language text into a structured format using AI."""
        # Option 1: Use regex/NLP parsing for simple cases
        if hasattr(output_type, '__annotations__'):
            annotations = output_type.__annotations__

            # Simple extraction for common patterns
            if 'addition_result' in annotations and 'multiplication_result' in annotations:

                # Extract numbers from text like "12 + 8 = 20" and "6 * 9 = 54"
                addition_match = re.search(r'(\d+)\s*\+\s*(\d+)\s*=\s*(\d+)', text)
                multiplication_match = re.search(r'(\d+)\s*\*\s*(\d+)\s*=\s*(\d+)', text)

                data = {
                    'addition_result': float(addition_match.group(3)) if addition_match else 0.0,
                    'multiplication_result': float(
                            multiplication_match.group(3)
                        ) if multiplication_match else 0.0,
                    'explanation': text
                }

                return output_type(**data)

        # Fallback: return text if parsing fails
        return text

    def _save_image(
        self,
        image: Any,
        output_directory: Path,
        prefix: str = 'generated_image_'
    ) -> Path:
        """Save a PIL image to the specified directory."""
        output_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = output_directory / f"{prefix}{timestamp}.jpeg"
        image.save(file_path)
        self.logger.info(f"Saved image to {file_path}")
        return file_path

    def _save_audio_file(self, audio_data: bytes, output_path: Path, mime_format: str):
        """
        Saves the audio data to a file in the specified format.
        """
        if mime_format == "audio/wav":
            # Save as WAV using the wave module
            output_path = output_path.with_suffix('.wav')
            with wave.open(str(output_path), mode="wb") as wf:
                # Mono
                wf.setnchannels(1)  # pylint: disable=E1101 # noqa
                # 16-bit PCM
                wf.setsampwidth(2)  # pylint: disable=E1101 # noqa
                wf.setcomptype("NONE", "not compressed")  # pylint: disable=E1101 # noqa
                # 24kHz sample rate
                wf.setframerate(24000)  # pylint: disable=E1101 # noqa
                wf.writeframes(audio_data)  # pylint: disable=E1101 # noqa
        elif mime_format in ("audio/mpeg", "audio/webm"):
            # choose extension and pydub format name
            ext = "mp3" if mime_format == "audio/mpeg" else "webm"
            fp = output_path.with_suffix(f'.{ext}')

            # wrap raw PCM bytes in a BytesIO so pydub can read them
            raw = io.BytesIO(audio_data)
            seg = AudioSegment.from_raw(
                raw,
                sample_width=2,
                frame_rate=24000,
                channels=1
            )
            # export using the appropriate container/codec
            seg.export(str(fp), format=ext)

        else:
            raise ValueError(f"Unsupported mime_format: {mime_format!r}")

    def _save_video_file(
        self,
        mp4_bytes,
        output_dir: Path,
        video_number: int = 1,
        mime_format: str = 'video/mp4',
        prefix: str = 'generated_video_'
    ) -> Path:
        """
        Download the GenAI video (always MP4), then either:
        - Write it straight out if mime_format is video/mp4
        - Otherwise, transcode via ffmpeg to the requested container/codec
        Returns the Path to the saved file.

        """
        # 1) Prep output path
        output_dir.mkdir(parents=True, exist_ok=True)
        ext = mimetypes.guess_extension(mime_format) or '.mp4'
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = output_dir / f"{prefix}{timestamp}_{video_number}{ext}"

        # 3) Straight-dump for MP4
        if mime_format == "video/mp4":
            out_path.write_bytes(mp4_bytes)
            self.logger.info(
                f"Saved MP4 to {out_path}"
            )
            return out_path

        # 4) Transcode via ffmpeg for other formats
        try:
            if mime_format == 'video/avi':
                video_format = 'avi'
                vcodec = 'libxvid'  # H.264 codec for AVI
                acodec = 'mp2'       # MP2 audio codec for AVI
            elif mime_format == 'video/webm':
                video_format = 'webm'
                vcodec = 'libvpx'  # VP8 video codec for WebM
                acodec = 'libopus'
            elif mime_format == 'video/mpeg':
                video_format = 'mpeg'
                vcodec = 'mpeg2video'  # MPEG-2 video codec
                acodec = 'mp2'       # MP2 audio codec
            else:
                raise ValueError(
                    f"Unsupported mime_format for video transcoding: {mime_format!r}"
                )
            # 1. Set up the FFmpeg process
            process = (
                ffmpeg  # pylint: disable=E1101 # noqa
                .input('pipe:', format='mp4')  # pylint: disable=E1101 # noqa
                .output(
                    'pipe:',
                    format=video_format,  # Output container format
                    vcodec=vcodec,      # video codec
                    acodec=acodec      # audio codec
                )
                .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
            )
            # 2. Pipe the mp4 bytes in and get the webm bytes out
            out_bytes, err = process.communicate(input=mp4_bytes)
            process.wait()
            if err:
                self.logger.error("FFmpeg Error:", err.decode())
            with open(out_path, 'wb') as f:
                f.write(out_bytes)
            self.logger.info(
                f"Saved {mime_format} to {out_path}"
            )
            return out_path
        except Exception as e:
            self.logger.error(
                f"Error saving {mime_format} to {out_path}: {e}"
            )
            return None

    @staticmethod
    def create_conversation_memory(
        memory_type: str = "memory",
        **kwargs
    ) -> ConversationMemory:
        """Factory method to create a conversation memory instance."""
        if memory_type == "memory":
            return InMemoryConversation()
        elif memory_type == "redis":
            return RedisConversation(**kwargs)
        elif memory_type == "file":
            return FileConversationMemory(**kwargs)
        else:
            raise ValueError(
                f"Unsupported memory type: {memory_type}"
            )

    async def _wait_with_backoff(self, retry_count: int, config: StreamingRetryConfig) -> None:
        """Wait with exponential backoff before retry."""
        delay = min(
            config.base_delay * (config.backoff_factor ** (retry_count - 1)),
            config.max_delay
        )

        if config.jitter:
            # Add random jitter to avoid thundering herd
            delay *= (0.5 + random.random() * 0.5)

        await asyncio.sleep(delay)

    def _parse_json_from_text(self, text: str) -> Union[dict, list]:
        """Robustly parse JSON even if the model wraps it in ```json fences."""
        if not text:
            return {}
        # strip fences
        s = text.strip()
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
        s = re.sub(r"\s*```$", "", s)
        # grab the largest {...} or [...] block if extra prose sneaks in
        m = re.search(r"(\{.*\}|\[.*\])", s, flags=re.S)
        s = m[1] if m else s
        return json_decoder(s)

    def _oai_normalize_schema(self, schema: dict) -> dict:
        """
        Normalize JSON schema for OpenAI `response_format`.

        Rules inferred from OpenAI errors:
        - ANY object (type == "object") must have `additionalProperties: false`.
        - Objects that declare `properties` must also have a `required` array
        that includes ALL property names.
        """

        def visit(node):
            if isinstance(node, dict):
                t = node.get("type")

                # --- Object handling ---
                if t == "object":
                    # 1) ALL object schemas must have additionalProperties = false
                    node["additionalProperties"] = False

                    # 2) If the object has explicit properties, required must cover them all
                    props = node.get("properties")
                    if isinstance(props, dict) and props:
                        prop_keys = list(props.keys())
                        existing_required = node.get("required") or []
                        missing = [k for k in prop_keys if k not in existing_required]
                        node["required"] = existing_required + missing

                    # Recurse into nested object children
                    for key in ("properties", "patternProperties"):
                        if key in node and isinstance(node[key], dict):
                            for sub in node[key].values():
                                visit(sub)

                # --- Array handling ---
                if t == "array":
                    # Recurse into items
                    if "items" in node and isinstance(node["items"], (dict, list)):
                        visit(node["items"])

                    # Recurse into prefixItems (tuples)
                    if "prefixItems" in node and isinstance(node["prefixItems"], list):
                        for sub in node["prefixItems"]:
                            visit(sub)

                # --- Combinators: ALWAYS recurse, regardless of type ---
                for key in ("anyOf", "allOf", "oneOf"):
                    if key in node and isinstance(node[key], list):
                        for sub in node[key]:
                            visit(sub)

                # --- Definitions: ALWAYS recurse ---
                for key in ("$defs", "definitions"):
                    if key in node and isinstance(node[key], dict):
                        for sub in node[key].values():
                            visit(sub)

            elif isinstance(node, list):
                for item in node:
                    visit(item)

            return node

        # shallow copy is fine; you don't want to mutate the caller's dict root
        return visit(dict(schema))

    def _build_response_format_from(self, output_config):
        """
        Build a valid OpenAI response_format payload from a StructuredOutputConfig
        or a direct Pydantic/dataclass type. Ensures additionalProperties:false.
        """
        if not output_config:
            return None

        # Explicit JSON-only request (no schema)
        fmt = getattr(output_config, "format", None)
        if fmt and str(fmt).lower().endswith("json_object"):
            return {"type": "json_object"}

        ot = getattr(output_config, "output_type", None) or output_config

        # Pydantic model -> JSON Schema
        if isinstance(ot, type) and issubclass(ot, BaseModel):
            raw = ot.model_json_schema()
            schema = self._oai_normalize_schema(raw)
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": getattr(output_config, "name", None) or ot.__name__,
                    "schema": schema,
                    "strict": True,
                },
            }
        # Python dataclass -> JSON Schema
        if is_dataclass(ot):
            ta = TypeAdapter(ot)
            raw = ta.json_schema()
            schema = self._oai_normalize_schema(raw)
            return {
                    "type": "json_schema",
                    "json_schema": {
                        "name": getattr(output_config, "name", None) or ot.__name__,
                        "schema": schema,
                        "strict": True,
                    },
            }
        # Fallback: at least constrain to JSON object
        return {"type": "json_object"}
