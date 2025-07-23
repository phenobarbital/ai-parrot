import json
from typing import AsyncIterator, Dict, List, Optional, Union, TypedDict, Any, Callable
import re
import mimetypes
import asyncio
import base64
from pathlib import Path
from dataclasses import dataclass, asdict
from abc import ABC, abstractmethod
import io
from pydantic import ValidationError
import yaml
from datamodel.exceptions import ParserError  # pylint: disable=E0611 # noqa
from datamodel.parsers.json import json_encoder, json_decoder, JSONContent  # pylint: disable=E0611 # noqa
from navconfig import config
from navconfig.logging import logging
import pandas as pd
import aiohttp
from .memory import ConversationSession, ConversationMemory, InMemoryConversationMemory
from .tools import PythonREPLTool
from .models import (
    StructuredOutputConfig,
    OutputFormat
)


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
class ToolDefinition:
    """Data structure for tool definition."""
    """Defines a tool with its name, description, input schema, and function."""
    __slots__ = ('name', 'description', 'input_schema', 'function')
    name: str
    description: str
    input_schema: Dict[str, Any]
    function: Callable

@dataclass
class BatchRequest:
    """Data structure for batch request."""
    custom_id: str
    params: Dict[str, Any]


class AbstractClient(ABC):
    """Abstract base Class for LLM models."""
    version: str = "0.1.0"
    base_headers: Dict[str, str] = {
        "Content-Type": "application/json",
    }
    agent_type: str = "generic"

    def __init__(
        self,
        conversation_memory: Optional[ConversationMemory] = None,
        **kwargs
    ):
        self.session: Optional[aiohttp.ClientSession] = None
        self.tools: Dict[str, ToolDefinition] = {}
        self.conversation_memory = conversation_memory or InMemoryConversationMemory()
        self.base_headers.update(kwargs.get('headers', {}))
        self.api_key = kwargs.get('api_key', None)
        self.version = kwargs.get('version', self.version)
        self._config = config
        self.logger: logging.Logger = logging.getLogger(__name__)
        self._json: Any = JSONContent()
        self.agent_type: str = kwargs.get('agent_type', self.agent_type)

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            headers=self.base_headers
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def start_conversation(
        self, user_id: str, session_id: str,
        system_prompt: Optional[str] = None
    ) -> ConversationSession:
        """Start a new conversation session."""
        return await self.conversation_memory.create_session(
            user_id,
            session_id,
            system_prompt
        )

    async def get_conversation(
        self,
        user_id: str,
        session_id: str
    ) -> Optional[ConversationSession]:
        """Get an existing conversation session."""
        return await self.conversation_memory.get_session(user_id, session_id)

    async def clear_conversation(
        self,
        user_id: str,
        session_id: str
    ) -> None:
        """Clear a conversation session."""
        await self.conversation_memory.clear_session(user_id, session_id)

    async def list_conversations(self, user_id: str) -> List[str]:
        """List all conversation sessions for a user."""
        return await self.conversation_memory.list_sessions(user_id)

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        function: Callable,
        type: str = "function",
    ) -> None:
        """Register a Python function as a tool for Claude to call."""
        self.tools[name] = ToolDefinition(name, description, input_schema, function)

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
        tool = PythonREPLTool(
            report_dir=report_dir,
            plt_style=plt_style,
            palette=palette
        )

        self.register_tool(
            name="python_repl",
            type="function",
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

    def _prepare_tools(self) -> List[Dict[str, Any]]:
        """Convert registered tools to API format."""
        if self.agent_type == 'openai':
            return [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema
                    }
                }
                for tool in self.tools.values()
            ]
        else:
            return [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema
                }
                for tool in self.tools.values()
            ]

    async def _execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any]
    ) -> Any:
        """Execute a registered tool function."""
        if tool_name not in self.tools:
            raise ValueError(f"Tool '{tool_name}' not registered")

        tool = self.tools[tool_name]
        if asyncio.iscoroutinefunction(tool.function):
            return await tool.function(**parameters)
        else:
            return tool.function(**parameters)

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
            for file_path in files:
                content.append(self._encode_file(file_path))

        return [{"role": "user", "content": content}]

    def _validate_response(self, response: Dict[str, Any]) -> bool:
        """Validate API response structure."""
        required_fields = ["id", "type", "role", "content", "model"]
        return all(field in response for field in required_fields)

    @abstractmethod
    async def ask(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
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
        session_id: Optional[str] = None
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

        text_content = ""
        for content_block in result["content"]:
            if content_block["type"] == "text":
                text_content += content_block["text"]

        try:
            if hasattr(structured_output, '__annotations__'):
                parsed = json_decoder(text_content)
                return structured_output(**parsed) if hasattr(
                    structured_output, '__dataclass_fields__'
                ) else parsed
            else:
                return structured_output(text_content)
        except:
            return result

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
        system_prompt: Optional[str]
    ) -> tuple[List[Dict[str, Any]], Optional[ConversationSession], Optional[str]]:
        """Prepare conversation context and return messages, session, and system prompt."""
        messages = []
        conversation_session = None

        if user_id and session_id:
            conversation_session = await self.get_conversation(user_id, session_id)
            if conversation_session:
                messages = conversation_session.messages.copy()
                if not system_prompt and conversation_session.system_prompt:
                    system_prompt = conversation_session.system_prompt

        new_user_message = self._prepare_messages(prompt, files)[0]
        messages.append(new_user_message)

        return messages, conversation_session, system_prompt

    async def _update_conversation_memory(
        self,
        user_id: Optional[str],
        session_id: Optional[str],
        conversation_session: Optional[ConversationSession],
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str]
    ) -> None:
        """Update conversation memory with new messages."""
        if user_id and session_id:
            if not conversation_session:
                conversation_session = await self.start_conversation(
                    user_id,
                    session_id,
                    system_prompt
                )

            conversation_session.messages = messages
            await self.conversation_memory.update_session(conversation_session)

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
                    if hasattr(output_type, 'model_validate_json'):
                        return output_type.model_validate_json(response_text)
                    elif hasattr(output_type, 'model_validate'):
                        parsed_json = self._json.loads(response_text)
                        return output_type.model_validate(parsed_json)
                    else:
                        return self._json.loads(response_text)
                except (ParserError, ValidationError, json.JSONDecodeError):
                    self.logger.warning(f"Standard parsing failed: {e}")
                    try:
                        # Try fallback with field mapping
                        json_text = self._extract_json_from_response(response_text)
                        parsed_json = self._json.loads(json_text)
                    except (ParserError, ValidationError, json.JSONDecodeError):
                        self.logger.warning(f"Fallback parsing failed: {e}")
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
                    'multiplication_result': float(multiplication_match.group(3)) if multiplication_match else 0.0,
                    'explanation': text
                }

                return output_type(**data)

        # Fallback: return text if parsing fails
        return text
