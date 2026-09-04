"""OpenRouter data models for AI-Parrot.

Provides model enums, provider routing preferences, and usage tracking
models for the OpenRouter API integration.
"""
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class OpenRouterModel(str, Enum):
    """Common OpenRouter model identifiers.

    These are convenience constants for frequently used models.
    Any valid OpenRouter model string can be used directly.
    """
    DEEPSEEK_R1 = "deepseek/deepseek-r1"
    DEEPSEEK_V3 = "deepseek/deepseek-chat"
    LLAMA_3_3_70B = "meta-llama/llama-3.3-70b-instruct"
    MISTRAL_LARGE = "mistralai/mistral-large-latest"
    QWEN_2_5_72B = "qwen/qwen-2.5-72b-instruct"
    GEMMA_2_27B = "google/gemma-2-27b-it"


class ProviderPreferences(BaseModel):
    """OpenRouter provider routing preferences.

    Controls how OpenRouter selects upstream providers for model inference.
    Serialized and sent as the 'provider' key in extra_body.

    Attributes:
        allow_fallbacks: Allow OpenRouter to fall back to alternative providers.
        require_parameters: Only use providers that support all requested parameters.
        data_collection: Data collection preference: 'deny' or 'allow'.
        order: Ordered list of preferred providers, e.g. ['DeepInfra', 'Together'].
        ignore: List of providers to exclude from routing.
        quantizations: Allowed quantization levels, e.g. ['bf16', 'fp8'].
    """
    allow_fallbacks: bool = Field(
        default=True,
        description="Allow OpenRouter to fall back to alternative providers"
    )
    require_parameters: bool = Field(
        default=False,
        description="Only use providers that support all requested parameters"
    )
    data_collection: Optional[str] = Field(
        default=None,
        description="Data collection preference: 'deny' or 'allow'"
    )
    order: Optional[List[str]] = Field(
        default=None,
        description="Ordered list of preferred providers, e.g. ['DeepInfra', 'Together']"
    )
    ignore: Optional[List[str]] = Field(
        default=None,
        description="List of providers to exclude"
    )
    quantizations: Optional[List[str]] = Field(
        default=None,
        description="Allowed quantization levels, e.g. ['bf16', 'fp8']"
    )


class OpenRouterUsage(BaseModel):
    """Cost and usage information from OpenRouter generation responses.

    Populated from OpenRouter's generation stats endpoint
    (GET /api/v1/generation?id={generation_id}).

    Attributes:
        generation_id: Unique identifier for the generation.
        model: Model used for the generation.
        total_cost: Total cost in USD for the generation.
        prompt_tokens: Number of prompt tokens used.
        completion_tokens: Number of completion tokens generated.
        native_tokens_prompt: Native token count for prompt (provider-specific).
        native_tokens_completion: Native token count for completion (provider-specific).
        provider_name: Name of the upstream provider that served the request.
    """
    generation_id: Optional[str] = None
    model: Optional[str] = None
    total_cost: Optional[float] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    native_tokens_prompt: Optional[int] = None
    native_tokens_completion: Optional[int] = None
    provider_name: Optional[str] = None
