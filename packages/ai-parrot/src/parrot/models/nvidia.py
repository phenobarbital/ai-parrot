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
    in OpenAI SDK calls (e.g. ``model=NvidiaModel.KIMI_K2_6.value``
    or simply ``model=NvidiaModel.KIMI_K2_6`` since the class
    inherits from ``str``).

    Slugs use NIM's ``vendor/model`` form, where the vendor segment may itself
    contain a dash (``z-ai/glm-5.2``).

    All slugs were re-verified against the live ``GET /v1/models`` catalog on
    2026-08-05, and all but ``KIMI_K2_6`` additionally confirmed to return HTTP
    200 from ``POST /v1/chat/completions``. ``KIMI_K2_6`` is present in the
    catalog but is gated per account: keys without the entitlement get
    ``404 Not Found`` ("Not found for account") rather than a slug error.

    Every member of the previous revision of this enum had reached
    end-of-life and been withdrawn from the catalog — requests returned
    ``410 Gone`` or ``404``. The mapping applied was:

    - ``moonshotai/kimi-k2-thinking`` → ``moonshotai/kimi-k2.6``
    - ``moonshotai/kimi-k2-instruct-0905`` → ``moonshotai/kimi-k2.6``
    - ``moonshotai/kimi-k2.5`` → ``moonshotai/kimi-k2.6``
    - ``minimaxai/minimax-m2.5`` → ``minimaxai/minimax-m3``
    - ``minimaxai/minimax-m2.7`` → ``minimaxai/minimax-m3``
    - ``mistralai/mamba-codestral-7b-v0.1`` → ``mistralai/mistral-nemotron``
      (and ``poolside/laguna-xs-2.1`` for the code-generation role)
    - ``deepseek-ai/deepseek-v3.1-terminus`` → ``deepseek-ai/deepseek-v4-pro``
    - ``qwen/qwen3.5-397b-a17b`` → dropped; the catalog carries no Qwen model
    - ``z-ai/glm-5.1`` → ``z-ai/glm-5.2``

    The three Moonshot members and the two Minimax members collapsed to a
    single successor each. They are deliberately **not** kept as aliases: in a
    ``str``-valued Enum, two members sharing one value silently become
    aliases of the first, which would make ``NvidiaModel.KIMI_K2_THINKING``
    resolve to a non-thinking model.
    """

    # Moonshot AI — gated per account (404 without the entitlement)
    KIMI_K2_6 = "moonshotai/kimi-k2.6"

    # Minimax
    MINIMAX_M3 = "minimaxai/minimax-m3"

    # DeepSeek
    DEEPSEEK_V4_PRO = "deepseek-ai/deepseek-v4-pro"
    DEEPSEEK_V4_FLASH = "deepseek-ai/deepseek-v4-flash"

    # Mistral
    MISTRAL_NEMOTRON = "mistralai/mistral-nemotron"

    # Code generation
    LAGUNA_XS_2_1 = "poolside/laguna-xs-2.1"
    LLAMA_3_3_70B_INSTRUCT = "meta/llama-3.3-70b-instruct"

    # OpenAI open-weights
    GPT_OSS_120B = "openai/gpt-oss-120b"

    # Nvidia first-party
    NEMOTRON_3_NANO_30B = "nvidia/nemotron-3-nano-30b-a3b"

    # Z-AI (reasoning-capable; emits reasoning_content in streaming deltas)
    GLM_5_2 = "z-ai/glm-5.2"

    # Stepfun-ai:
    STEPFUN_STEP_3_7_FLASH = "stepfun-ai/step-3.7-flash"


