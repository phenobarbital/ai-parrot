from typing import Dict, List, Optional, Any, TypedDict, Callable
from enum import Enum
from datetime import datetime
from dataclasses import dataclass
from typing_extensions import Literal
from pydantic import BaseModel, Field


class OutputFormat(Enum):
    """Supported output formats for structured responses."""
    JSON = "json"
    CSV = "csv"
    YAML = "yaml"
    XML = "xml"
    CODE = "code"
    CUSTOM = "custom"
    TEXT = "text"


@dataclass
class StructuredOutputConfig:
    """Configuration for structured output parsing."""
    output_type: type
    format: OutputFormat = OutputFormat.JSON
    custom_parser: Optional[Callable[[str], Any]] = None



class ToolCall(BaseModel):
    """Unified tool call representation."""
    id: str
    name: str
    arguments: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time: Optional[float] = None


class CompletionUsage(BaseModel):
    """Unified completion usage tracking across different LLM providers."""

    # Core usage metrics (common across all providers)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # Timing information (optional, provider-specific)
    completion_time: Optional[float] = None
    prompt_time: Optional[float] = None
    queue_time: Optional[float] = None
    total_time: Optional[float] = None

    # Cost information (optional)
    estimated_cost: Optional[float] = None

    # Provider-specific additional fields
    extra_usage: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_openai(cls, usage: Any) -> "CompletionUsage":
        """Create from OpenAI usage object."""
        return cls(
            prompt_tokens=getattr(usage, 'prompt_tokens', 0),
            completion_tokens=getattr(usage, 'completion_tokens', 0),
            total_tokens=getattr(usage, 'total_tokens', 0)
        )

    @classmethod
    def from_groq(cls, usage: Any) -> "CompletionUsage":
        """Create from Groq usage object."""
        return cls(
            prompt_tokens=getattr(usage, 'prompt_tokens', 0),
            completion_tokens=getattr(usage, 'completion_tokens', 0),
            total_tokens=getattr(usage, 'total_tokens', 0),
            completion_time=getattr(usage, 'completion_time', None),
            prompt_time=getattr(usage, 'prompt_time', None),
            queue_time=getattr(usage, 'queue_time', None),
            total_time=getattr(usage, 'total_time', None)
        )

    @classmethod
    def from_claude(cls, usage: Dict[str, Any]) -> "CompletionUsage":
        """Create from Claude usage dict."""
        return cls(
            prompt_tokens=usage.get('input_tokens', 0),
            completion_tokens=usage.get('output_tokens', 0),
            total_tokens=usage.get('input_tokens', 0) + usage.get('output_tokens', 0),
            extra_usage=usage
        )

    @classmethod
    def from_gemini(cls, usage: Dict[str, Any]) -> "CompletionUsage":
        """Create from Gemini/Vertex AI usage dict."""
        # Handle both Gemini API format and Vertex AI format
        prompt_tokens = usage.get('prompt_token_count', 0) or usage.get('prompt_tokens', 0)
        completion_tokens = usage.get(
            'candidates_token_count', 0
        ) or usage.get('completion_tokens', 0)
        total_tokens = usage.get('total_token_count', 0) or usage.get('total_tokens', 0)

        return cls(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            extra_usage=usage
        )


class AIMessage(BaseModel):
    """Unified AI message response that can handle various output types."""

    # Core response data
    input: str = Field(
        description="The original input/prompt sent to the LLM"
    )
    output: Any = Field(
        description="The response output - can be text, structured data, dataframe, etc."
    )

    # Metadata
    model: str = Field(
        description="The model used for generation"
    )
    provider: str = Field(
        description="The LLM provider (openai, groq, claude, etc.)"
    )

    # Usage and performance
    usage: CompletionUsage = Field(
        description="Token usage and timing information"
    )

    # Additional response metadata
    stop_reason: Optional[str] = Field(
        default=None, description="Why the generation stopped"
    )
    finish_reason: Optional[str] = Field(
        default=None, description="Finish reason from provider"
    )

    # Tool usage
    tool_calls: List[ToolCall] = Field(
        default_factory=list,
        description="Tools called during generation"
    )

    # Conversation context
    user_id: Optional[str] = Field(
        default=None, description="User ID for conversation tracking"
    )
    session_id: Optional[str] = Field(
        default=None, description="Session ID for conversation tracking"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.now, description="When the response was created"
    )

    # Raw response for debugging
    raw_response: Optional[Dict[str, Any]] = Field(
        default=None, description="Original response from provider"
    )

    # Conversation turn info
    turn_id: Optional[str] = Field(
        default=None,
        description="Unique ID for this conversation turn"
    )

    class Config:
        """Pydantic configuration for AIMessage."""
        # Allow arbitrary types for output field (pandas DataFrames, etc.)
        arbitrary_types_allowed = True

    @property
    def text(self) -> str:
        """Get text representation of output."""
        if isinstance(self.output, str):
            return self.output
        elif isinstance(self.output, dict) and 'content' in self.output:
            # Handle MessageResponse-style format
            content = self.output['content']
            if isinstance(content, list) and content:
                return content[0].get('text', str(self.output))
            return str(content)
        elif hasattr(self.output, 'to_string'):
            # Handle pandas DataFrames
            return self.output.to_string()
        else:
            return str(self.output)

    @property
    def is_structured(self) -> bool:
        """Check if output is structured data."""
        return not isinstance(self.output, str)

    @property
    def has_tools(self) -> bool:
        """Check if tools were used."""
        return len(self.tool_calls) > 0

    def add_tool_call(self, tool_call: ToolCall) -> None:
        """Add a tool call to the response."""
        self.tool_calls.append(tool_call)  # pylint: disable=E1101 # noqa


class StreamChunk(BaseModel):
    """Represents a chunk in a streaming response."""
    content: str
    is_complete: bool = False
    chunk_id: Optional[str] = None
    turn_id: Optional[str] = None


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

# Factory functions to create AIMessage from different providers
class AIMessageFactory:
    """Factory to create AIMessage from different provider responses."""

    @staticmethod
    def from_openai(
        response: Any,
        input_text: str,
        model: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        structured_output: Any = None
    ) -> AIMessage:
        """Create AIMessage from OpenAI response."""
        message = response.choices[0].message

        # Handle tool calls
        tool_calls = []
        if hasattr(message, 'tool_calls') and message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=tc.function.arguments if isinstance(tc.function.arguments, dict)
                                else eval(tc.function.arguments)
                    )
                )

        return AIMessage(
            input=input_text,
            output=structured_output if structured_output else message.content,
            model=model,
            provider="openai",
            usage=CompletionUsage.from_openai(response.usage),
            stop_reason=response.choices[0].finish_reason,
            finish_reason=response.choices[0].finish_reason,
            tool_calls=tool_calls,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            raw_response=response.dict() if hasattr(response, 'dict') else response.__dict__
        )

    @staticmethod
    def from_groq(
        response: Any,
        input_text: str,
        model: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        structured_output: Any = None
    ) -> AIMessage:
        """Create AIMessage from Groq response."""
        message = response.choices[0].message

        # Handle tool calls
        tool_calls = []
        if hasattr(message, 'tool_calls') and message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=tc.function.arguments if isinstance(tc.function.arguments, dict)
                                else eval(tc.function.arguments)
                    )
                )

        return AIMessage(
            input=input_text,
            output=structured_output if structured_output else message.content,
            model=model,
            provider="groq",
            usage=CompletionUsage.from_groq(response.usage),
            stop_reason=response.choices[0].finish_reason,
            finish_reason=response.choices[0].finish_reason,
            tool_calls=tool_calls,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            raw_response=response.dict() if hasattr(response, 'dict') else response.__dict__
        )

    @staticmethod
    def from_claude(
        response: Dict[str, Any],
        input_text: str,
        model: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        structured_output: Any = None,
        tool_calls: List[ToolCall] = None
    ) -> AIMessage:
        """Create AIMessage from Claude response."""
        # Extract text content
        content = ""
        for content_block in response.get("content", []):
            if content_block.get("type") == "text":
                content += content_block.get("text", "")

        return AIMessage(
            input=input_text,
            output=structured_output if structured_output else content,
            model=model,
            provider="claude",
            usage=CompletionUsage.from_claude(response.get("usage", {})),
            stop_reason=response.get("stop_reason"),
            finish_reason=response.get("stop_reason"),
            tool_calls=tool_calls or [],
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            raw_response=response
        )

    @staticmethod
    def from_gemini(
        response: Any,
        input_text: str,
        model: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        structured_output: Any = None,
        tool_calls: List[ToolCall] = None
    ) -> AIMessage:
        """Create AIMessage from Gemini/Vertex AI response."""
        # Handle both direct text responses and response objects
        if hasattr(response, 'text'):
            content = response.text
        else:
            content = str(response)

        # Extract usage information
        usage_dict = {}
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            # Vertex AI format
            usage_dict = {
                'prompt_token_count': response.usage_metadata.prompt_token_count,
                'candidates_token_count': response.usage_metadata.candidates_token_count,
                'total_token_count': response.usage_metadata.total_token_count
            }
        elif hasattr(response, 'usage'):
            # Standard Gemini API format
            usage_dict = response.usage.__dict__ if hasattr(response.usage, '__dict__') else {}

        return AIMessage(
            input=input_text,
            output=structured_output if structured_output else content,
            model=model,
            provider="gemini",  # Will be overridden to "vertex_ai" in VertexAIClient
            usage=CompletionUsage.from_gemini(usage_dict),
            stop_reason="completed",
            finish_reason="completed",
            tool_calls=tool_calls or [],
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            raw_response=response.__dict__ if hasattr(response, '__dict__') else str(response)
        )
