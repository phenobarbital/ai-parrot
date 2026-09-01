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
# (FEAT-405 Module 5; widened by FEAT-486 with "mantle" - purely
# additive, the "codex" default and "nova" choice are unchanged).
# Deliberately NOT the full ``DevAgentBackend`` set —
# only backends with a registered "<backend>-adversarial" review
# dispatcher qualify.
_ADVERSARIAL_BACKEND_CHOICES: Tuple[str, ...] = ("codex", "nova", "mantle")


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
        ``"codex"``, ``"nova"`` or ``"mantle"`` (FEAT-486 — the
        read-only ``gpt-5.6-sol`` counter-reviewer over bedrock-mantle).

    Raises:
        ValueError: If the configured value is not one of those three
            — names the valid options.
    """
    getter = config_getter or (lambda key, fallback="": conf.config.get(key, fallback=fallback))
    value = str(getter("DEV_LOOP_ADVERSARIAL_BACKEND", ADVERSARIAL_BACKEND) or ADVERSARIAL_BACKEND)
    if value not in _ADVERSARIAL_BACKEND_CHOICES:
        raise ValueError(
            f"Invalid DEV_LOOP_ADVERSARIAL_BACKEND={value!r}; must be one "
            f"of {_ADVERSARIAL_BACKEND_CHOICES} (codex, nova, mantle)."
        )
    return value


# Non-judge review dispatchers registered in ``CodeReviewDispatcherFactory``
# that can serve as the *primary* reviewer of a bug-mode run.
PRIMARY_REVIEW_BACKENDS: Tuple[str, ...] = ("claude-code", "codex", "gemini", "google_coding")


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
            # FEAT-486 additions (append-only — every id above is
            # unchanged): the console's second default dev-pool seat,
            # and the counter-reviewer model reachable over bedrock-mantle.
            "qwen.qwen3-coder-480b-a35b-v1:0",
            "gpt-5.6-sol",
        ),
        requires="AWS credentials with Bedrock model access (+ Bedrock API key for bedrock-mantle)",
        roles=("development", "adversarial"),
        notes="Dev seat routes MiniMax/Kimi/GLM/Qwen3-coder via "
        "bedrock-mantle; the adversarial seat is a read-only, "
        "no-tools call — Converse on Nova 2 Lite via "
        "DEV_LOOP_ADVERSARIAL_BACKEND='nova', or Chat Completions "
        "on bedrock-mantle (gpt-5.6-sol, FEAT-486) via "
        "DEV_LOOP_ADVERSARIAL_BACKEND='mantle'. The us.anthropic.* "
        "ids remain selectable but require the per-account "
        "Anthropic use-case form on Bedrock.",
    ),
)

_BY_ID: Dict[str, BackendInfo] = {b.id: b for b in BACKENDS}

ConfigGetter = Callable[..., Any]


def get_backend(backend_id: str) -> Optional[BackendInfo]:
    """Return the :class:`BackendInfo` for ``backend_id``, or ``None``."""
    return _BY_ID.get(backend_id)


def backends_for_role(role: str) -> List[BackendInfo]:
    """Return every backend that may fill ``role``.

    Args:
        role: One of ``development``, ``judge``, ``primary_review``,
            ``adversarial``, ``planner``.

    Returns:
        The matching backends, in catalog order.
    """
    return [b for b in BACKENDS if role in b.roles]


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
    return {
        "backends": [_backend_payload(b, config_getter) for b in BACKENDS],
        "roles": {
            "development": [b.id for b in backends_for_role("development")],
            "judge": [b.id for b in backends_for_role("judge")],
            "primary_review": [b.id for b in backends_for_role("primary_review")],
            "adversarial": [resolved_adversarial_backend],
        },
        "adversarial_backend": resolved_adversarial_backend,
        "adversarial_model": conf.DEV_LOOP_ADVERSARIAL_MODEL,
        "default_judge_panel": default_judge_panel_payload(config_getter),
    }


__all__ = [
    "ADVERSARIAL_BACKEND",
    "BACKENDS",
    "BackendInfo",
    "JUDGE_BACKENDS",
    "PRIMARY_REVIEW_BACKENDS",
    "backends_for_role",
    "catalog_payload",
    "default_judge_panel_payload",
    "effective_default_model",
    "get_backend",
    "resolve_adversarial_backend",
]
