from typing import Dict, Optional, Any
from enum import Enum
from pydantic import BaseModel, Field


class OutputFormat(Enum):
    """Supported output formats for structured responses."""
    JSON = "json"
    XML = "xml"
    CSV = "csv"
    YAML = "yaml"
    CODE = "code"
    CUSTOM = "custom"
    TEXT = "text"


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
