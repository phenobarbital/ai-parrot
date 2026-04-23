"""Nvidia NIM data models for AI-Parrot.

Provides model enums for Nvidia's NIM-hosted OpenAI-compatible API gateway
(https://integrate.api.nvidia.com/v1). No Pydantic wrappers are needed —
Nvidia's response shape matches the OpenAI Chat Completion shape and is
already covered by existing AIMessage / CompletionUsage models.
"""
from enum import Enum


class NvidiaModel(str, Enum):
    """Nvidia NIM-hosted model identifiers.

    String-valued enum so members interchange with raw model strings
    in OpenAI SDK calls (e.g. ``model=NvidiaModel.KIMI_K2_THINKING.value``
    or simply ``model=NvidiaModel.KIMI_K2_THINKING`` since the class
    inherits from ``str``).

    All slugs have been verified against the Nvidia NIM model catalog.
    """

    # Moonshot AI
    KIMI_K2_THINKING = "moonshotai/kimi-k2-thinking"
    KIMI_K2_INSTRUCT_0905 = "moonshotai/kimi-k2-instruct-0905"
    KIMI_K2_5 = "moonshotai/kimi-k2.5"

    # Minimax
    MINIMAX_M2_5 = "minimaxai/minimax-m2.5"
    MINIMAX_M2_7 = "minimaxai/minimax-m2.7"

    # Mistral
    MAMBA_CODESTRAL_7B = "mistralai/mamba-codestral-7b-v0.1"

    # DeepSeek
    DEEPSEEK_V3_1_TERMINUS = "deepseek-ai/deepseek-v3.1-terminus"

    # Qwen
    QWEN3_5_397B = "qwen/qwen3.5-397b-a17b"

    # Z-AI (reasoning-capable; emits reasoning_content in streaming deltas)
    GLM_5_1 = "z-ai/glm-5.1"
