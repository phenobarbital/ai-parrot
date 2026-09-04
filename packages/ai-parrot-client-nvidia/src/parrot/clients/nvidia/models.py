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

       **Several members are withdrawn upstream.** A live probe on 2026-09-02
       sent a real ``POST /v1/chat/completions`` for every member then defined:

       ===============================  ======================================
       Member                           Live status (2026-09-02)
       ===============================  ======================================
       ``MINIMAX_M3``                   200 OK
       ``GPT_OSS_120B``                 200 OK
       ``KIMI_K2_6``                    404 — gated per account
       ``DEEPSEEK_V4_PRO``              410 Gone — EOL
       ``DEEPSEEK_V4_FLASH``            410 Gone — EOL
       ``LLAMA_3_3_70B_INSTRUCT``       410 Gone — EOL 2026-08-26
       ``NEMOTRON_3_NANO_30B``          410 Gone — EOL
       ``GLM_5_2``                      410 Gone — EOL 2026-08-21
       ``STEPFUN_STEP_3_7_FLASH``       410 Gone — EOL
       ===============================  ======================================

       The dead members are deliberately kept rather than deleted, because
       removing a member breaks any caller that imports it by name. They are
       documented here so nobody picks one expecting it to work, and the
       replacements now live in :data:`FREE_TIER_MODELS` below.

    The revision before this one claimed verification against
    ``GET /v1/models`` on 2026-08-05. That is why the drift went unnoticed:
    presence in the catalog listing is NOT proof a slug still serves traffic —
    ``GLM_5_2`` and ``LLAMA_3_3_70B_INSTRUCT`` both vanished from the catalog
    *and* began returning 410, while ``KIMI_K2_6`` is listed but returns 404
    per account. Only a real completion request is evidence.

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

    # -- Free preview endpoints (see FREE_TIER_MODELS below) ----------------

    #: Reasoning model: emits ``reasoning_content`` beside ``content``.
    #: Surfaced on ``AIMessage.reasoning``. Because the thinking is drawn from
    #: the same token budget as the answer, this model needs a large
    #: ``max_tokens`` and a generous timeout — both are the NvidiaClient
    #: defaults (65536 / 300s). Optionally cap the thinking with
    #: ``reasoning_budget``.
    NEMOTRON_3_NANO_OMNI_30B_REASONING = (
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
    )

    #: Reasoning-capable; confirmed emitting ``reasoning_content``.
    NEMOTRON_3_5_LIGHTNING_30B = "nvidia/nemotron-3.5-lightning-30b-a3b"

    #: Moonshot's successor to the account-gated ``kimi-k2.6``.
    #: Reasoning-capable; confirmed emitting ``reasoning_content``.
    KIMI_K3 = "moonshotai/kimi-k3"

    #: Successor to the withdrawn ``deepseek-ai/deepseek-v4-flash``.
    #: Its thinking flags use DIFFERENT ``chat_template_kwargs`` keys than the
    #: ``enable_thinking``/``clear_thinking`` pair ``NvidiaClient`` injects —
    #: this model documents ``{"thinking": True, "reasoning_effort": "high"}``.
    #: Pass those through ``extra_body`` explicitly rather than relying on the
    #: ``enable_thinking=True`` shortcut.
    DEEPSEEK_V4_FLASH_0731 = "deepseek-ai/deepseek-v4-flash-0731"

    GEMMA_4_31B_IT = "google/gemma-4-31b-it"

    # Z-AI — WITHDRAWN upstream (410 Gone, EOL 2026-08-21). Kept only so
    # existing imports keep resolving; see the warning in the class docstring.
    GLM_5_2 = "z-ai/glm-5.2"

    # Stepfun-ai — WITHDRAWN upstream (410 Gone).
    STEPFUN_STEP_3_7_FLASH = "stepfun-ai/step-3.7-flash"


#: Models NVIDIA publishes as **free preview endpoints**
#: (https://build.nvidia.com/models?filters=nimType%3Anim_type_preview).
#:
#: These are the models the ``free_tier`` throttle in
#: :class:`~parrot.clients.nvidia.NvidiaClient` is designed for: NVIDIA caps
#: free endpoints at 40 requests per minute, which is what the client's
#: :class:`~parrot.clients.nvidia.SlidingWindowRateLimiter` enforces. A model
#: outside this set is served from a paid or otherwise-provisioned endpoint,
#: where ``free_tier=False`` removes the cap.
#:
#: Membership here is NVIDIA's published classification, not something derived
#: from the API: a free endpoint answers ``200`` when it has capacity and
#: ``503 ResourceExhausted`` ("Worker local total request limit reached") when
#: it does not — so a 503 means *busy*, never *absent*, and cannot be used to
#: infer the list. Treat saturation as the normal operating condition of a free
#: endpoint and retry rather than falling back to another model.
FREE_TIER_MODELS: frozenset[str] = frozenset(
    {
        NvidiaModel.KIMI_K3.value,
        NvidiaModel.NEMOTRON_3_5_LIGHTNING_30B.value,
        NvidiaModel.DEEPSEEK_V4_FLASH_0731.value,
        NvidiaModel.LAGUNA_XS_2_1.value,
        NvidiaModel.NEMOTRON_3_NANO_OMNI_30B_REASONING.value,
        NvidiaModel.GEMMA_4_31B_IT.value,
        NvidiaModel.MISTRAL_NEMOTRON.value,
    }
)


