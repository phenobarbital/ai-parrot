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

    .. warning::

       **Most of this enum is stale.** A live probe on 2026-09-02 sent a real
       ``POST /v1/chat/completions`` for every member. Only two answered:

       ===============================  ======================================
       Member                           Live status (2026-09-02)
       ===============================  ======================================
       ``MINIMAX_M3``                   200 OK
       ``GPT_OSS_120B``                 200 OK
       ``NEMOTRON_3_NANO_OMNI_30B_``    200 OK (added 2026-09-02)
       ``  REASONING``
       ``KIMI_K2_6``                    404 — gated per account
       ``DEEPSEEK_V4_PRO``              410 Gone — EOL
       ``DEEPSEEK_V4_FLASH``            410 Gone — EOL
       ``LLAMA_3_3_70B_INSTRUCT``       410 Gone — EOL 2026-08-26
       ``NEMOTRON_3_NANO_30B``          410 Gone — EOL
       ``GLM_5_2``                      410 Gone — EOL 2026-08-21
       ``STEPFUN_STEP_3_7_FLASH``       410 Gone — EOL
       ``MISTRAL_NEMOTRON``             500 / unverified
       ``LAGUNA_XS_2_1``                503 — endpoint saturated, unverified
       ===============================  ======================================

       The dead members are deliberately kept rather than deleted, because
       removing a member breaks any caller that imports it by name; they are
       documented here so nobody picks one expecting it to work. The catalog
       lists dated successors for the DeepSeek pair
       (``deepseek-v4-pro-0813``, ``deepseek-v4-flash-0731``) and renamed
       ``nemotron-nano-3-30b-a3b`` for ``NEMOTRON_3_NANO_30B``, but none were
       confirmed with a successful request, so none are added here on
       speculation. Re-probe before relying on any member other than the three
       marked 200 OK.

    The previous revision claimed verification against ``GET /v1/models`` on
    2026-08-05. That is why the drift went unnoticed: presence in the catalog
    listing is NOT proof a slug still serves traffic — ``GLM_5_2`` and
    ``LLAMA_3_3_70B_INSTRUCT`` both vanished from the catalog *and* began
    returning 410, while ``KIMI_K2_6`` is listed but returns 404 per account.
    Only a real completion request is evidence.

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

    #: Reasoning model: emits ``reasoning_content`` beside ``content``.
    #: Surfaced on ``AIMessage.reasoning``. Because the thinking is drawn from
    #: the same token budget as the answer, this model needs a large
    #: ``max_tokens`` and a generous timeout — both are the NvidiaClient
    #: defaults (65536 / 300s). Optionally cap the thinking with
    #: ``reasoning_budget``.
    NEMOTRON_3_NANO_OMNI_30B_REASONING = (
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
    )

    # Z-AI (reasoning-capable; emits reasoning_content in streaming deltas)
    GLM_5_2 = "z-ai/glm-5.2"

    # Stepfun-ai:
    STEPFUN_STEP_3_7_FLASH = "stepfun-ai/step-3.7-flash"


