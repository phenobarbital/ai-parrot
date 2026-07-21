from typing import Dict, Optional, Any, List
from enum import Enum
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
)


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


class ToolConfig(BaseModel):
    """Tool configuration for session-scoped ToolManager setup."""
    tools: List[Dict[str, Any]] = Field(default_factory=list)
    mcp_servers: List[Dict[str, Any]] = Field(default_factory=list)
    toolkits: List[str] = Field(default_factory=list)


class ModelConfig(BaseModel):
    """Model configuration for session-scoped LLM setup."""
    provider: str
    model: str
    temperature: float = 0.1
    max_tokens: int = 8192


class CompletionUsage(BaseModel):
    """Unified completion usage tracking across different LLM providers.

    Speaks both token vocabularies. The canonical fields keep the OpenAI naming
    (``prompt_tokens`` / ``completion_tokens``), but the model also accepts and
    emits the OTel-GenAI / Anthropic naming (``input_tokens`` / ``output_tokens``)
    so it interoperates with any framework regardless of which dialect it uses:

    - **Construction** accepts either name (``CompletionUsage(input_tokens=17)``
      or ``CompletionUsage(prompt_tokens=17)``) via field ``validation_alias``.
    - **Read access** exposes both (``usage.input_tokens`` and
      ``usage.prompt_tokens``).
    - **Serialization** (``model_dump`` / ``model_dump_json``) includes both
      vocabularies via computed fields.
    """

    # populate_by_name keeps the Python attribute names usable as kwargs even
    # though validation_alias is declared on the fields below.
    model_config = ConfigDict(populate_by_name=True)

    # Core usage metrics (common across all providers). validation_alias lets the
    # OTel/Anthropic ``input_tokens`` / ``output_tokens`` names populate them too.
    prompt_tokens: int = Field(
        0, validation_alias=AliasChoices("prompt_tokens", "input_tokens")
    )
    completion_tokens: int = Field(
        0, validation_alias=AliasChoices("completion_tokens", "output_tokens")
    )
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

    # GenAI SemConv aliases. The canonical fields use the OpenAI naming
    # (prompt/completion); these computed fields expose the OTel GenAI naming
    # (input/output) for read access AND serialization, so callers and the
    # observability layer can read ``usage.input_tokens`` / ``usage.output_tokens``
    # and any consumer dumping the model sees both vocabularies — matching
    # ``gen_ai.usage.input_tokens`` / ``gen_ai.usage.output_tokens``.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def input_tokens(self) -> int:
        """Alias for :attr:`prompt_tokens` (OTel GenAI ``input_tokens``)."""
        return self.prompt_tokens

    @computed_field  # type: ignore[prop-decorator]
    @property
    def output_tokens(self) -> int:
        """Alias for :attr:`completion_tokens` (OTel GenAI ``output_tokens``)."""
        return self.completion_tokens

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
    def from_bedrock(cls, usage: Dict[str, Any]) -> "CompletionUsage":
        """Create from AWS Bedrock Converse API usage dict.

        Bedrock Converse returns camelCase usage fields (``inputTokens`` /
        ``outputTokens``), plus optional prompt-cache token counts
        (``cacheReadInputTokens`` / ``cacheWriteInputTokens``) which are
        preserved in ``extra_usage`` for observability.
        """
        input_tokens = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)
        return cls(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            extra_usage={
                "cacheReadInputTokens": usage.get("cacheReadInputTokens", 0),
                "cacheWriteInputTokens": usage.get("cacheWriteInputTokens", 0),
            }
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

    @classmethod
    def from_claude_agent(
        cls,
        result_usage: Optional[Dict[str, Any]] = None,
        *,
        total_cost_usd: Optional[float] = None,
        num_turns: Optional[int] = None,
        model_usage: Optional[Dict[str, Any]] = None,
    ) -> "CompletionUsage":
        """Create from a ``claude_agent_sdk.types.ResultMessage`` payload.

        The agent SDK exposes usage at two levels: a per-turn ``usage`` dict on
        each ``AssistantMessage`` (mirroring the Anthropic Messages API
        ``input_tokens`` / ``output_tokens`` shape) and an aggregate
        ``ResultMessage.usage`` plus ``ResultMessage.total_cost_usd`` and
        ``ResultMessage.num_turns``. We prefer the aggregate ``result_usage``
        when present, falling back to zeros if the message stream produced no
        ``ResultMessage``.

        Args:
            result_usage: ``ResultMessage.usage`` dict — may include
                ``input_tokens``, ``output_tokens``, plus cache-related fields.
            total_cost_usd: ``ResultMessage.total_cost_usd`` — populates
                ``estimated_cost``.
            num_turns: ``ResultMessage.num_turns`` — stored under
                ``extra_usage["num_turns"]``.
            model_usage: ``ResultMessage.model_usage`` — stored under
                ``extra_usage["model_usage"]``.
        """
        result_usage = result_usage or {}
        prompt_tokens = int(
            result_usage.get("input_tokens")
            or result_usage.get("prompt_tokens")
            or 0
        )
        completion_tokens = int(
            result_usage.get("output_tokens")
            or result_usage.get("completion_tokens")
            or 0
        )
        total_tokens = int(
            result_usage.get("total_tokens", prompt_tokens + completion_tokens)
        )

        extra: Dict[str, Any] = {}
        if result_usage:
            extra["raw_usage"] = dict(result_usage)
        if num_turns is not None:
            extra["num_turns"] = num_turns
        if model_usage:
            extra["model_usage"] = model_usage

        return cls(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost=total_cost_usd,
            extra_usage=extra,
        )

    @classmethod
    def from_grok(cls, usage: Any) -> "CompletionUsage":
        """Create from Grok usage object (dict or xai_sdk protobuf)."""
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        if isinstance(usage, dict):
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)
            total_tokens = usage.get('total_tokens', 0)
            extra = usage
        else:
            prompt_tokens = getattr(usage, 'prompt_tokens', 0)
            completion_tokens = getattr(usage, 'completion_tokens', 0)
            total_tokens = getattr(usage, 'total_tokens', 0)
            extra = {
                "reasoning_tokens": getattr(usage, 'reasoning_tokens', 0),
                "cached_prompt_text_tokens": getattr(usage, 'cached_prompt_text_tokens', 0),
                "prompt_image_tokens": getattr(usage, 'prompt_image_tokens', 0),
            }

        return cls(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            extra_usage=extra,
        )
