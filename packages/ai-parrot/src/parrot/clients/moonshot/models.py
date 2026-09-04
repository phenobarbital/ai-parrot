"""Moonshot (Kimi) data models for AI-Parrot.

Provides model enums and capability constants for Moonshot's
OpenAI-compatible API (https://api.moonshot.ai/v1). No Pydantic wrappers
are needed — Moonshot's response shape matches the OpenAI Chat Completion
shape and is already covered by existing AIMessage / CompletionUsage models.
"""
from enum import Enum


class MoonshotModel(str, Enum):
    """Moonshot (Kimi) model identifiers.

    String-valued enum so members interchange with raw model strings
    in OpenAI SDK calls (e.g. ``model=MoonshotModel.KIMI_K3.value``
    or simply ``model=MoonshotModel.KIMI_K3`` since the class inherits
    from ``str``).

    All slugs have been verified against the Moonshot API model catalog.
    """

    KIMI_K3 = "kimi-k3"
    KIMI_K2_7_CODE = "kimi-k2.7-code"
    KIMI_K2_7_CODE_HIGHSPEED = "kimi-k2.7-code-highspeed"
    KIMI_K2_6 = "kimi-k2.6"
    MOONSHOT_V1_128K = "moonshot-v1-128k"
    MOONSHOT_V1_8K_VISION = "moonshot-v1-8k-vision-preview"
    MOONSHOT_V1_128K_VISION = "moonshot-v1-128k-vision-preview"


# Models with fixed sampling parameters — passing temperature, top_p, n,
# presence_penalty, or frequency_penalty returns invalid_request_error.
K_SERIES_MODELS: frozenset[str] = frozenset({
    MoonshotModel.KIMI_K3.value,
    MoonshotModel.KIMI_K2_7_CODE.value,
    MoonshotModel.KIMI_K2_7_CODE_HIGHSPEED.value,
    MoonshotModel.KIMI_K2_6.value,
})

# Models where thinking mode is always on — no parameter needed to enable it.
ALWAYS_THINKING_MODELS: frozenset[str] = frozenset({
    MoonshotModel.KIMI_K2_7_CODE.value,
    MoonshotModel.KIMI_K2_7_CODE_HIGHSPEED.value,
})

# Models that support the reasoning_effort parameter.
REASONING_EFFORT_MODELS: frozenset[str] = frozenset({
    MoonshotModel.KIMI_K3.value,
})

# Models that support the thinking dict parameter.
THINKING_DICT_MODELS: frozenset[str] = frozenset({
    MoonshotModel.KIMI_K2_6.value,
})

# Vision-capable models.
VISION_MODELS: frozenset[str] = frozenset({
    MoonshotModel.KIMI_K3.value,
    MoonshotModel.KIMI_K2_7_CODE.value,
    MoonshotModel.KIMI_K2_7_CODE_HIGHSPEED.value,
    MoonshotModel.KIMI_K2_6.value,
    MoonshotModel.MOONSHOT_V1_8K_VISION.value,
    MoonshotModel.MOONSHOT_V1_128K_VISION.value,
})
