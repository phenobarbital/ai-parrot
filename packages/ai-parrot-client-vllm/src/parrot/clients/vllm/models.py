"""Pydantic models for vLLM client integration.

This module provides configuration and request/response models
for the vLLMClient, supporting vLLM-specific features like guided
decoding, LoRA adapters, and batch processing.
"""

from typing import Dict, Optional, Any, List, Type
from pydantic import BaseModel, Field, model_validator


class VLLMConfig(BaseModel):
    """Configuration for vLLM client.

    Attributes:
        base_url: vLLM server base URL (default: http://localhost:8000/v1)
        api_key: Optional API key for authentication
        timeout: Request timeout in seconds
    """

    base_url: str = Field(
        default="http://localhost:8000/v1",
        description="vLLM server base URL"
    )
    api_key: Optional[str] = Field(
        default=None,
        description="Optional API key for authentication"
    )
    timeout: int = Field(
        default=120,
        ge=1,
        description="Request timeout in seconds"
    )


class VLLMSamplingParams(BaseModel):
    """Extended sampling parameters for vLLM.

    These parameters extend the standard OpenAI-compatible sampling
    with vLLM-specific options for fine-grained control.

    Attributes:
        top_k: Top-k sampling (-1 to disable)
        min_p: Minimum probability threshold (0.0 to 1.0)
        repetition_penalty: Penalty for repeated tokens (>1.0 to discourage)
        length_penalty: Length penalty for beam search
        presence_penalty: Penalty for new tokens based on presence
        frequency_penalty: Penalty for new tokens based on frequency
    """

    top_k: int = Field(
        default=-1,
        description="Top-k sampling (-1 to disable)"
    )
    min_p: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum probability threshold"
    )
    repetition_penalty: float = Field(
        default=1.0,
        ge=0.0,
        description="Repetition penalty (>1.0 to discourage repetition)"
    )
    length_penalty: float = Field(
        default=1.0,
        description="Length penalty for beam search"
    )
    presence_penalty: float = Field(
        default=0.0,
        ge=-2.0,
        le=2.0,
        description="Presence penalty for new tokens"
    )
    frequency_penalty: float = Field(
        default=0.0,
        ge=-2.0,
        le=2.0,
        description="Frequency penalty for new tokens"
    )

    def to_extra_body(self) -> Dict[str, Any]:
        """Convert to vLLM extra_body format.

        Only includes non-default values to minimize request payload.

        Returns:
            Dict with vLLM-specific sampling parameters
        """
        params = {}
        if self.top_k != -1:
            params["top_k"] = self.top_k
        if self.min_p > 0.0:
            params["min_p"] = self.min_p
        if self.repetition_penalty != 1.0:
            params["repetition_penalty"] = self.repetition_penalty
        if self.length_penalty != 1.0:
            params["length_penalty"] = self.length_penalty
        return params


class VLLMLoRARequest(BaseModel):
    """LoRA adapter configuration for vLLM requests.

    vLLM supports dynamically loading and switching between LoRA adapters
    at request time, enabling fine-tuned behavior without reloading models.

    Attributes:
        lora_name: Name of the LoRA adapter to use
        lora_int_id: Optional integer ID for the LoRA adapter
        lora_local_path: Optional local path to LoRA adapter weights
    """

    lora_name: str = Field(
        ...,
        description="Name of the LoRA adapter to use"
    )
    lora_int_id: Optional[int] = Field(
        default=None,
        description="Optional integer ID for the LoRA adapter"
    )
    lora_local_path: Optional[str] = Field(
        default=None,
        description="Optional local path to LoRA adapter weights"
    )

    def to_extra_body(self) -> Dict[str, Any]:
        """Convert to vLLM lora_request format.

        Returns:
            Dict with LoRA request configuration
        """
        request = {"lora_name": self.lora_name}
        if self.lora_int_id is not None:
            request["lora_int_id"] = self.lora_int_id
        if self.lora_local_path is not None:
            request["lora_local_path"] = self.lora_local_path
        return {"lora_request": request}


class VLLMGuidedParams(BaseModel):
    """Guided decoding parameters for constrained generation.

    vLLM supports constraining output to specific patterns using
    JSON schemas, regular expressions, or predefined choices.
    Only one constraint type can be active at a time.

    Attributes:
        guided_json: JSON schema for constrained output
        guided_regex: Regular expression pattern to match
        guided_choice: List of valid output choices
        guided_grammar: BNF grammar for constrained output
    """

    guided_json: Optional[Dict[str, Any]] = Field(
        default=None,
        description="JSON schema for constrained output"
    )
    guided_regex: Optional[str] = Field(
        default=None,
        description="Regular expression pattern to match"
    )
    guided_choice: Optional[List[str]] = Field(
        default=None,
        description="List of valid output choices"
    )
    guided_grammar: Optional[str] = Field(
        default=None,
        description="BNF grammar for constrained output"
    )

    @model_validator(mode='after')
    def check_mutually_exclusive(self) -> 'VLLMGuidedParams':
        """Ensure only one guided constraint is specified."""
        constraints = [
            self.guided_json is not None,
            self.guided_regex is not None,
            self.guided_choice is not None,
            self.guided_grammar is not None,
        ]
        if sum(constraints) > 1:
            raise ValueError(
                "Only one guided constraint can be specified at a time: "
                "guided_json, guided_regex, guided_choice, or guided_grammar"
            )
        return self

    def to_extra_body(self) -> Dict[str, Any]:
        """Convert to vLLM extra_body format.

        Returns:
            Dict with the active guided constraint
        """
        if self.guided_json is not None:
            return {"guided_json": self.guided_json}
        if self.guided_regex is not None:
            return {"guided_regex": self.guided_regex}
        if self.guided_choice is not None:
            return {"guided_choice": self.guided_choice}
        if self.guided_grammar is not None:
            return {"guided_grammar": self.guided_grammar}
        return {}


class VLLMBatchRequest(BaseModel):
    """Batch request model for vLLM batch processing.

    Represents a single request within a batch, containing
    the prompt and optional parameters for generation.

    Attributes:
        prompt: The input prompt or messages
        model: Model identifier (optional, uses default if not specified)
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        guided_json: Optional JSON schema constraint
        guided_regex: Optional regex constraint
        guided_choice: Optional choice constraint
        lora_adapter: Optional LoRA adapter name
        sampling_params: Optional extended sampling parameters
    """

    prompt: str = Field(
        ...,
        description="The input prompt for generation"
    )
    model: Optional[str] = Field(
        default=None,
        description="Model identifier"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature"
    )
    max_tokens: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum tokens to generate"
    )
    guided_json: Optional[Dict[str, Any]] = Field(
        default=None,
        description="JSON schema for constrained output"
    )
    guided_regex: Optional[str] = Field(
        default=None,
        description="Regex pattern for constrained output"
    )
    guided_choice: Optional[List[str]] = Field(
        default=None,
        description="List of valid choices"
    )
    lora_adapter: Optional[str] = Field(
        default=None,
        description="LoRA adapter name"
    )
    sampling_params: Optional[VLLMSamplingParams] = Field(
        default=None,
        description="Extended sampling parameters"
    )


class VLLMBatchResponse(BaseModel):
    """Batch response model for vLLM batch processing.

    Contains the results of a batch processing operation,
    including individual responses and aggregate statistics.

    Attributes:
        responses: List of generated text responses
        errors: List of errors for failed requests (indexed by position)
        total_requests: Total number of requests in the batch
        successful: Number of successful completions
        failed: Number of failed requests
        total_tokens: Total tokens used across all requests
    """

    responses: List[Optional[str]] = Field(
        default_factory=list,
        description="List of generated responses (None for failed requests)"
    )
    errors: Dict[int, str] = Field(
        default_factory=dict,
        description="Map of request index to error message"
    )
    total_requests: int = Field(
        default=0,
        description="Total number of requests in batch"
    )
    successful: int = Field(
        default=0,
        description="Number of successful completions"
    )
    failed: int = Field(
        default=0,
        description="Number of failed requests"
    )
    total_tokens: int = Field(
        default=0,
        description="Total tokens used across all requests"
    )


class VLLMServerInfo(BaseModel):
    """vLLM server information model.

    Contains metadata about the running vLLM server instance.

    Attributes:
        version: vLLM version string
        model_id: Currently loaded model identifier
        gpu_memory_utilization: GPU memory utilization (0.0 to 1.0)
        max_model_len: Maximum model context length
        tensor_parallel_size: Number of GPUs for tensor parallelism
    """

    version: Optional[str] = Field(
        default=None,
        description="vLLM version string"
    )
    model_id: Optional[str] = Field(
        default=None,
        description="Currently loaded model identifier"
    )
    gpu_memory_utilization: Optional[float] = Field(
        default=None,
        description="GPU memory utilization"
    )
    max_model_len: Optional[int] = Field(
        default=None,
        description="Maximum model context length"
    )
    tensor_parallel_size: Optional[int] = Field(
        default=None,
        description="Number of GPUs for tensor parallelism"
    )


def pydantic_to_guided_json(model: Type[BaseModel]) -> Dict[str, Any]:
    """Convert a Pydantic model class to vLLM guided_json schema.

    This helper enables structured output by converting Pydantic models
    to JSON schemas that vLLM can use for constrained generation.

    Args:
        model: A Pydantic BaseModel class (not an instance)

    Returns:
        JSON schema dict compatible with vLLM's guided_json parameter

    Example:
        >>> from pydantic import BaseModel
        >>> class Person(BaseModel):
        ...     name: str
        ...     age: int
        >>> schema = pydantic_to_guided_json(Person)
        >>> # Use with vLLMClient:
        >>> # await client.ask("Extract person info", guided_json=schema)
    """
    return model.model_json_schema()
