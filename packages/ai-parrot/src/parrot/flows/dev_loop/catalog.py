"""LLM client + model catalog for the dev-loop demo server (FEAT-378 UI).

The dev-loop flow materialises every agent — development workers, QA
judges, the adversarial reviewer — through
:func:`parrot.flows.dev_loop.agent_builder.build_dispatcher`, which knows
exactly seven backends (the ``DevAgentBackend`` Literal). Nothing in the
library, however, publishes *which* of those backends is usable in
*which* role, nor which models they accept: the console UI needs both to
render its ``<select>`` pickers.

This module is that missing catalog. It is deliberately **data**, not
logic:

* ``BACKENDS`` mirrors ``agent_builder.build_dispatcher``'s if/elif chain
  one entry per branch — same ids, same env var, same fallback model.
* ``ROLES`` records which backends each role can actually accept, read
  off the code that consumes them (see :data:`JUDGE_BACKENDS`).
* :func:`catalog_payload` resolves the *effective* defaults through
  ``conf.config.get`` so the UI shows what this deployment will really
  use, not what the source file hardcodes.

Model lists are a curated starting point, never a whitelist: every
picker in the UI also accepts a free-text model id, and an empty model
always means "use the backend default".

FEAT-388: this module is the package home of the catalog, promoted from
``examples/dev_loop/llm_catalog.py`` (Module 1). That file is now a thin
re-export shim so the demo server (``import llm_catalog``) keeps working
unchanged; the CLI (``parrot devloop``) imports this module directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from parrot import conf

# Backends that ``JudgePanelReviewDispatcher._build_judge`` can map to a
# review dispatcher. Every other backend raises ValueError there — see
# ``code_review.py`` ("supported: claude-code, codex, gemini").
JUDGE_BACKENDS: Tuple[str, ...] = ("claude-code", "codex", "gemini", "google_coding")

# The adversarial seat's static, no-behaviour-change default (FEAT-405
# [R3]): unset config resolves here. ``CodexAdversarialReviewDispatcher``
# was originally the sole reviewer built on the read-only
# ``sdd-secondopinion`` subagent profile (``ClaudeCodeDispatchProfile.
# subagent`` does not admit it); FEAT-405 adds a second option —
# ``NovaAdversarialReviewDispatcher``, read-only by construction (no tools
# passed at all, rather than a sandboxed CLI profile). The module-level
# constant is kept (or existing importers of the bare string break); use
# :func:`resolve_adversarial_backend` to get the deployment's actual
# choice.
ADVERSARIAL_BACKEND: str = "codex"

# Valid values for the config-resolved adversarial backend selector
# (FEAT-405 Module 5). Deliberately NOT the full ``DevAgentBackend`` set —
# only backends with a registered "<backend>-adversarial" review
# dispatcher qualify.
_ADVERSARIAL_BACKEND_CHOICES: Tuple[str, ...] = ("codex", "nova")


def resolve_adversarial_backend(config_getter: Optional[ConfigGetter] = None) -> str:
    """Return the deployment's configured adversarial backend.

    Resolves ``DEV_LOOP_ADVERSARIAL_BACKEND`` through config, defaulting to
    :data:`ADVERSARIAL_BACKEND` (``"codex"``) when unset — [R3]: an
    operator who configures nothing sees byte-identical behaviour to
    pre-FEAT-405.

    Args:
        config_getter: ``(key, fallback) -> Any``; defaults to
            ``conf.config.get``.

    Returns:
        ``"codex"`` or ``"nova"``.

    Raises:
        ValueError: If the configured value is neither ``"codex"`` nor
            ``"nova"`` — names the valid options.
    """
    getter = config_getter or (lambda key, fallback="": conf.config.get(key, fallback=fallback))
    value = str(getter("DEV_LOOP_ADVERSARIAL_BACKEND", ADVERSARIAL_BACKEND) or ADVERSARIAL_BACKEND)
    if value not in _ADVERSARIAL_BACKEND_CHOICES:
        raise ValueError(
            f"Invalid DEV_LOOP_ADVERSARIAL_BACKEND={value!r}; must be one "
            f"of {_ADVERSARIAL_BACKEND_CHOICES} (codex, nova)."
        )
    return value


# Non-judge review dispatchers registered in ``CodeReviewDispatcherFactory``
# that can serve as the *primary* reviewer of a bug-mode run.
PRIMARY_REVIEW_BACKENDS: Tuple[str, ...] = ("claude-code", "codex", "gemini", "google_coding")

# FEAT-482: the complementary research-partner seat's static,
# no-behaviour-change default — the backend used once the seat is
# EXPLICITLY enabled without further qualification. Unlike
# ``ADVERSARIAL_BACKEND`` (mandatory, always resolves to a real backend),
# the research-partner seat is opt-in: unset ``DEV_FLOW_RESEARCH_PARTNER``
# resolves to the empty-string "disabled" sentinel, not to this constant —
# see :func:`resolve_research_partner_backend`.
RESEARCH_PARTNER_BACKEND: str = "gpt"

# Valid values for the config-resolved research-partner backend selector
# (FEAT-482 Module 1). Both reach Bedrock on the SAME ``AWS_NOVA_API_KEY``
# credential — "gpt" via bedrock-mantle (``BedrockMantleClient``), "nova"
# via Converse (``NovaClient``) — through one shared ``BedrockResearchPartner``
# implementation.
_RESEARCH_PARTNER_CHOICES: Tuple[str, ...] = ("gpt", "nova")

# The empty string is the "research-partner seat disabled" sentinel for
# ``DEV_FLOW_RESEARCH_PARTNER`` — distinct from ``_RESEARCH_PARTNER_CHOICES``,
# which enumerates only the enabled values.
_RESEARCH_PARTNER_DISABLED: str = ""

# Anthropic model-id prefixes rejected for the research-partner seat (FEAT-482
# §8 Q12): they correlate training priors with the primary Claude seat,
# defeating the seat's decorrelation purpose, AND
# ``BedrockConverseBase``'s pre-Module-3 ``thinking_budget`` shape returns
# HTTP 400 against modern Anthropic models on Bedrock (Opus 5, Fable 5,
# Opus 4.8/4.7, Sonnet 5).
_ANTHROPIC_PARTNER_MODEL_PREFIXES: Tuple[str, ...] = (
    "us.anthropic.",
    "global.anthropic.",
    "claude-",
)


def _reject_anthropic_partner_model(model: str) -> None:
    """Hard-reject an Anthropic model configured for the research-partner seat.

    Args:
        model: The resolved partner model id (e.g. from
            ``DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL`` /
            ``DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL``).

    Raises:
        ValueError: If ``model`` matches an Anthropic model-id prefix.
            Names BOTH the decorrelation reason and the Bedrock 400.
    """
    if any(model.startswith(prefix) for prefix in _ANTHROPIC_PARTNER_MODEL_PREFIXES):
        raise ValueError(
            f"Anthropic model {model!r} may not be configured as the "
            "research-partner seat: (1) it correlates training priors "
            "with the primary Claude seat, defeating the seat's "
            "decorrelation purpose, and (2) BedrockConverseBase's "
            "thinking shape returns HTTP 400 against modern Anthropic "
            "models on Bedrock (see the adaptive-thinking support in "
            "clients/bedrock.py)."
        )


def resolve_research_partner_backend(config_getter: Optional[ConfigGetter] = None) -> str:
    """Return the deployment's configured research-partner backend.

    Resolves ``DEV_FLOW_RESEARCH_PARTNER`` through config. Unset (empty
    string) means the seat is disabled — an operator who configures
    nothing sees byte-identical behaviour to pre-FEAT-482.

    Args:
        config_getter: ``(key, fallback) -> Any``; defaults to
            ``conf.config.get``.

    Returns:
        ``""`` (disabled), ``"gpt"``, or ``"nova"``.

    Raises:
        ValueError: If the configured value is neither ``"gpt"`` nor
            ``"nova"`` — names the valid options. Also raised (naming
            both the decorrelation reason and the Bedrock 400) if the
            resolved backend's model is an Anthropic model id.
    """
    getter = config_getter or (lambda key, fallback="": conf.config.get(key, fallback=fallback))
    value = str(getter("DEV_FLOW_RESEARCH_PARTNER", _RESEARCH_PARTNER_DISABLED) or _RESEARCH_PARTNER_DISABLED)
    if not value:
        return _RESEARCH_PARTNER_DISABLED
    if value not in _RESEARCH_PARTNER_CHOICES:
        raise ValueError(
            f"Invalid DEV_FLOW_RESEARCH_PARTNER={value!r}; must be one "
            f"of {_RESEARCH_PARTNER_CHOICES} (gpt, nova), or unset to "
            "disable the research-partner seat."
        )
    if value == "gpt":
        model_key = "DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL"
        default_model = conf.DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL
    else:
        model_key = "DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL"
        default_model = conf.DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL
    model = str(getter(model_key, default_model) or default_model)
    _reject_anthropic_partner_model(model)
    return value


@dataclass(frozen=True)
class BackendInfo:
    """One dev-loop LLM backend, as the console needs to render it.

    Attributes:
        id: The ``DevAgentBackend`` literal value.
        label: Human-readable name for the picker.
        transport: ``"cli"`` when the dispatcher shells out to a coding
            CLI, ``"api"`` when it drives an ``AbstractClient``.
        model_env: The config key ``build_dispatcher`` reads for this
            backend's model, or ``None`` when the default is hardcoded.
        default_model: The fallback used when neither the spec nor the
            env supplies a model.
        models: Curated model ids offered in the picker. Never a
            whitelist — the UI also accepts free text.
        requires: What an operator must provision for this backend to
            work (CLI on ``$PATH``, API key, …).
        roles: Roles this backend may fill.
        notes: Extra behaviour worth surfacing in the UI hint line.
    """

    id: str
    label: str
    transport: str
    model_env: Optional[str]
    default_model: str
    models: Tuple[str, ...]
    requires: str
    roles: Tuple[str, ...]
    notes: str = ""


#: One entry per ``build_dispatcher`` branch (agent_builder.py:136-201).
BACKENDS: Tuple[BackendInfo, ...] = (
    BackendInfo(
        id="claude-code",
        label="Claude Code",
        transport="cli",
        model_env=None,  # hardcoded fallback in build_dispatcher
        default_model="claude-sonnet-4-6",
        models=(
            "claude-opus-5",
            "claude-sonnet-5",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
        ),
        requires="`claude` CLI on $PATH, authenticated",
        roles=("development", "judge", "primary_review", "planner"),
        notes="Write-enabled reviewer; also drives planner/synthesis/QA.",
    ),
    BackendInfo(
        id="codex",
        label="Codex",
        transport="cli",
        model_env="DEV_LOOP_CODEX_MODEL",
        default_model="gpt-5.5",
        models=("gpt-5.5", "gpt-5.5-codex"),
        requires="`codex` CLI on $PATH (or OPENAI_API_KEY)",
        roles=("development", "judge", "primary_review", "adversarial"),
        notes="Only backend with a read-only `sdd-secondopinion` profile — " "it holds the mandatory adversarial seat.",
    ),
    BackendInfo(
        id="gemini",
        label="Gemini",
        transport="cli",
        model_env="DEV_LOOP_GEMINI_MODEL",
        default_model="auto",
        models=("auto",),
        requires="`gemini` CLI on $PATH, authenticated",
        roles=("development", "judge", "primary_review"),
        notes="`auto` lets the CLI pick the model.",
    ),
    BackendInfo(
        id="google_coding",
        label="Google Coding (agy)",
        transport="cli",
        model_env="DEV_LOOP_GOOGLE_CODING_MODEL",
        default_model="auto",
        models=("auto", "gemini-3.6-flash", "gemini-3.0-pro"),
        requires="`agy` CLI on $PATH, authenticated",
        roles=("development", "judge", "primary_review"),
        notes="Headless Google Antigravity CLI console dispatcher.",
    ),
    BackendInfo(
        id="nvidia",
        label="Nvidia NIM",
        transport="api",
        model_env="DEV_LOOP_NVIDIA_CODE_MODEL",
        default_model="minimaxai/minimax-m3",
        models=(
            "minimaxai/minimax-m3",
            "z-ai/glm-5.2",
            "poolside/laguna-xs-2.1",
            "meta/llama-3.3-70b-instruct",
        ),
        requires="NVIDIA_API_KEY",
        roles=("development",),
        notes="Set DEV_LOOP_NVIDIA_ENABLE_THINKING=true for GLM reasoning mode.",
    ),
    BackendInfo(
        id="grok",
        label="Grok",
        transport="api",
        model_env="DEV_LOOP_GROK_MODEL",
        default_model="grok-build-0.1",
        models=("grok-build-0.1",),
        requires="xAI credentials",
        roles=("development",),
    ),
    BackendInfo(
        id="zai",
        label="Z.ai (GLM)",
        transport="api",
        model_env="DEV_LOOP_ZAI_MODEL",
        default_model="glm-5.2",
        models=("glm-5.2", "glm-5.1"),
        requires="Z.ai credentials",
        roles=("development",),
        notes="Thinking mode on by default (DEV_LOOP_ZAI_ENABLE_THINKING).",
    ),
    BackendInfo(
        id="moonshot",
        label="Moonshot (Kimi)",
        transport="api",
        model_env="DEV_LOOP_MOONSHOT_MODEL",
        default_model="kimi-k3",
        models=("kimi-k3", "kimi-k2"),
        requires="Moonshot credentials",
        roles=("development",),
    ),
    BackendInfo(
        id="nova",
        label="Nova (AWS Bedrock)",
        transport="api",
        model_env="DEV_LOOP_NOVA_CODE_MODEL",
        default_model="minimax.minimax-m2.5",
        models=(
            "minimax.minimax-m2.5",
            "moonshotai.kimi-k2.5",
            "zai.glm-5",
            "us.amazon.nova-2-lite-v1:0",
            "us.amazon.nova-pro-v1:0",
            "us.anthropic.claude-opus-5",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            "global.anthropic.claude-fable-5",
        ),
        requires="AWS credentials with Bedrock model access (+ Bedrock API key for bedrock-mantle)",
        roles=("development", "adversarial", "research_partner"),
        notes="Dev seat routes MiniMax/Kimi/GLM via bedrock-mantle; the "
        "adversarial seat is a read-only, no-tools Converse call on "
        "Nova 2 Lite — select via DEV_LOOP_ADVERSARIAL_BACKEND. The "
        "us.anthropic.* ids remain selectable but require the "
        "per-account Anthropic use-case form on Bedrock. The "
        "research-partner seat (FEAT-482) selects this backend via "
        "DEV_FLOW_RESEARCH_PARTNER=nova.",
    ),
)

_BY_ID: Dict[str, BackendInfo] = {b.id: b for b in BACKENDS}

# FEAT-482: the complementary research-partner seat's catalog. Deliberately
# NOT folded into ``BACKENDS`` — that tuple's documented contract is "one
# entry per ``build_dispatcher`` branch" (coding dev-loop backends only,
# see the module-level comment above :131), and every existing test asserts
# every ``BACKENDS`` entry is development-capable
# (``test_backends_for_role_development_includes_all_backends``). "nova" is
# already a ``build_dispatcher`` branch, so its existing ``BACKENDS`` entry
# above just gained the extra ``"research_partner"`` role. "gpt" (bedrock-
# mantle ``gpt-5.6-sol``) has no coding dev_loop counterpart at all, so it
# lives here instead.
RESEARCH_PARTNER_BACKENDS: Tuple[BackendInfo, ...] = (
    BackendInfo(
        id="gpt",
        label="GPT (Bedrock Mantle)",
        transport="api",
        model_env="DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL",
        default_model="gpt-5.6-sol",
        models=("gpt-5.6-sol",),
        requires="AWS credentials with a Bedrock API key (bedrock-mantle); "
        "reuses AWS_NOVA_API_KEY — no separate OPENAI_API_KEY",
        roles=("research_partner",),
        notes="FEAT-482: the default complementary research-partner "
        "backend — OpenAI-compatible bedrock-mantle transport via "
        "BedrockMantleClient, decorrelated from the primary Claude "
        "seat. Select via DEV_FLOW_RESEARCH_PARTNER=gpt (default "
        "once the seat is enabled).",
    ),
    _BY_ID["nova"],
)

# FEAT-482 code-review follow-up: extend the lookup dict with the
# research-partner-only entries ("gpt"; "nova" is already present and is
# the SAME object, not a duplicate) so get_backend()/backends_for_role()/
# catalog_payload() can actually surface the seat, per Module 1's own
# intent ("Add a BackendInfo entry ... so the catalog surfaces the seat").
# BACKENDS itself is intentionally left untouched (see the comment above)
# — this only widens the id->BackendInfo lookup, not the "one entry per
# build_dispatcher branch" tuple.
_BY_ID.update({b.id: b for b in RESEARCH_PARTNER_BACKENDS})

ConfigGetter = Callable[..., Any]


def get_backend(backend_id: str) -> Optional[BackendInfo]:
    """Return the :class:`BackendInfo` for ``backend_id``, or ``None``.

    Looks across both ``BACKENDS`` (coding dev-loop backends) and
    ``RESEARCH_PARTNER_BACKENDS`` (FEAT-482) — e.g. ``get_backend("gpt")``
    resolves even though ``"gpt"`` is not itself a ``build_dispatcher``
    branch.
    """
    return _BY_ID.get(backend_id)


def backends_for_role(role: str) -> List[BackendInfo]:
    """Return every backend that may fill ``role``.

    Args:
        role: One of ``development``, ``judge``, ``primary_review``,
            ``adversarial``, ``planner``, ``research_partner``.

    Returns:
        The matching backends, in catalog order. Searches across both
        ``BACKENDS`` and ``RESEARCH_PARTNER_BACKENDS`` (FEAT-482) — "nova"
        appears in both but is the same object, so it is never duplicated
        in the result.
    """
    return [b for b in _BY_ID.values() if role in b.roles]


def effective_default_model(backend: BackendInfo, config_getter: Optional[ConfigGetter] = None) -> str:
    """Resolve the model this deployment will actually use for ``backend``.

    Mirrors ``build_dispatcher``: the env var wins over the hardcoded
    fallback, and an explicit ``DevAgentSpec.model`` (not visible here)
    would win over both.

    Args:
        backend: The catalog entry to resolve.
        config_getter: ``(key, fallback) -> Any``; defaults to
            ``conf.config.get``.

    Returns:
        The effective default model id.
    """
    getter = config_getter or conf.config.get
    if backend.model_env is None:
        return backend.default_model
    return str(getter(backend.model_env, fallback=backend.default_model) or backend.default_model)


def _backend_payload(backend: BackendInfo, config_getter: Optional[ConfigGetter]) -> Dict[str, Any]:
    """Serialise one backend for the ``/api/config`` response."""
    resolved = effective_default_model(backend, config_getter)
    models = list(backend.models)
    if resolved not in models:
        # A deployment that overrode the model via env must still see it
        # preselected in the picker.
        models.insert(0, resolved)
    return {
        "id": backend.id,
        "label": backend.label,
        "transport": backend.transport,
        "model_env": backend.model_env,
        "default_model": resolved,
        "models": models,
        "requires": backend.requires,
        "roles": list(backend.roles),
        "notes": backend.notes,
    }


def default_judge_panel_payload(config_getter: Optional[ConfigGetter] = None) -> List[Dict[str, str]]:
    """Return the default judge panel as ``[{agent, model}, ...]``.

    Resolves through the library's own ``DEV_LOOP_JUDGE_PANEL`` /
    ``default_judge_panel()`` chain so the console shows the panel the
    flow would really assemble, then falls back to the catalog's own
    3-judge default if the library symbols are unavailable (e.g. running
    the console against a build predating FEAT-378).

    Args:
        config_getter: ``(key, fallback) -> Any``; defaults to
            ``conf.config.get``.

    Returns:
        A list of ``{"agent": ..., "model": ...}`` dicts.
    """
    try:
        from parrot.flows.dev_loop.code_review import _judges_from_conf

        getter = config_getter or (lambda key, fallback="": conf.config.get(key, fallback=fallback))
        return [{"agent": j.agent, "model": j.model} for j in _judges_from_conf(getter)]
    except Exception:  # noqa: BLE001 - catalog must never break the console
        return [
            {"agent": "claude-code", "model": ""},
            {"agent": "codex", "model": ""},
            {"agent": "gemini", "model": ""},
        ]


def catalog_payload(config_getter: Optional[ConfigGetter] = None) -> Dict[str, Any]:
    """Build the full ``/api/config`` payload consumed by the console UI.

    Args:
        config_getter: ``(key, fallback) -> Any``; defaults to
            ``conf.config.get``.

    Returns:
        A JSON-serialisable dict with the backend catalog, the role →
        backend mapping, and the resolved review/judge defaults.
    """
    resolved_adversarial_backend = resolve_adversarial_backend(config_getter)
    # FEAT-482: resolved separately from the "roles" membership list below —
    # unlike "adversarial" (mandatory, always exactly one active backend),
    # the research-partner seat is opt-in, so "" (disabled) is a valid,
    # common resolution here.
    resolved_research_partner_backend = resolve_research_partner_backend(config_getter)
    return {
        # FEAT-482 code-review follow-up: iterate _BY_ID (BACKENDS +
        # RESEARCH_PARTNER_BACKENDS, deduplicated) rather than BACKENDS
        # alone, so "gpt" — which has no build_dispatcher branch — is still
        # visible to any console/CLI surface rendering a backend picker.
        "backends": [_backend_payload(b, config_getter) for b in _BY_ID.values()],
        "roles": {
            "development": [b.id for b in backends_for_role("development")],
            "judge": [b.id for b in backends_for_role("judge")],
            "primary_review": [b.id for b in backends_for_role("primary_review")],
            "adversarial": [resolved_adversarial_backend],
            "research_partner": [b.id for b in backends_for_role("research_partner")],
        },
        "adversarial_backend": resolved_adversarial_backend,
        "adversarial_model": conf.DEV_LOOP_ADVERSARIAL_MODEL,
        "research_partner_backend": resolved_research_partner_backend,
        "default_judge_panel": default_judge_panel_payload(config_getter),
    }


__all__ = [
    "ADVERSARIAL_BACKEND",
    "BACKENDS",
    "BackendInfo",
    "JUDGE_BACKENDS",
    "PRIMARY_REVIEW_BACKENDS",
    "RESEARCH_PARTNER_BACKEND",
    "RESEARCH_PARTNER_BACKENDS",
    "backends_for_role",
    "catalog_payload",
    "default_judge_panel_payload",
    "effective_default_model",
    "get_backend",
    "resolve_adversarial_backend",
    "resolve_research_partner_backend",
]
