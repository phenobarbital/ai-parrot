"""Reusable dev-agent dispatcher builder + pool env parsing (FEAT-323).

Extracts the ``DevAgentSpec -> (dispatcher, profile)`` mapping that used to
live inline in ``examples/dev_loop/server.py`` (the ``DEV_LOOP_DEVELOPMENT_
AGENT`` if/elif block) into a reusable, testable function so a
``DevAgentPool`` (TASK-1860) can materialize N dispatchers instead of just
one. Also provides the ``DEV_LOOP_DEV_AGENTS`` / ``DEV_LOOP_DEV_ISOLATION`` /
``DEV_LOOP_DEV_POOL_MAX`` env-var parsers.

See ``sdd/specs/dev-loop-multiple-dev-agents.spec.md`` §3 "Module 3" for the
authoritative design. The per-backend model defaults and env-var names here
are copied verbatim from ``examples/dev_loop/server.py`` (lines ~454-585) so
the single-agent path keeps byte-identical observable behaviour.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional, Tuple

from pydantic import BaseModel, ValidationError

# NOTE: imported via the *package* (``parrot.flows.dev_loop``), not the
# ``.dispatcher`` / ``.models`` submodules directly. Importing a submodule
# of this package unconditionally triggers a full execution of
# ``parrot/flows/dev_loop/__init__.py`` first (Python always initializes
# parent packages before submodules), so there is no eager-import cost
# saved by bypassing the package re-exports here. Going through the
# package instead keeps this module's class identities aligned with every
# other consumer (e.g. ``examples/dev_loop/server.py``) that imports the
# same names the same way — submodule-only reloads (as exercised by
# ``test_lazy_import.py``'s aggressive ``sys.modules`` surgery) would
# otherwise leave this module holding a *different* class object than a
# consumer that imported via the package, breaking ``isinstance`` checks.
from parrot.flows.dev_loop import (
    ClaudeCodeDispatcher,
    ClaudeCodeDispatchProfile,
    CodexCodeDispatcher,
    CodexCodeDispatchProfile,
    DevAgentPoolConfig,
    DevAgentSpec,
    DevLoopCodeDispatcher,
    GeminiCodeDispatcher,
    GeminiCodeDispatchProfile,
    GrokCodeDispatcher,
    GrokCodeDispatchProfile,
    LLMCodeDispatcher,
    LLMCodeDispatchProfile,
    MoonshotCodeDispatcher,
    MoonshotCodeDispatchProfile,
    ZaiCodeDispatcher,
    ZaiCodeDispatchProfile,
)

logger = logging.getLogger(__name__)

# Signature compatible with ``conf.config.get(key, fallback=...)``.
ConfigGetter = Callable[..., Any]


def _default_config_getter(key: str, fallback: Any = None) -> Any:
    """Fallback ``config_getter`` used when the caller supplies none.

    Lazily imports ``parrot.conf`` so this module stays importable (and
    unit-testable) without pulling in the full settings stack unless a
    caller actually relies on the default.

    Args:
        key: Env/config key.
        fallback: Value to return when unset.

    Returns:
        The resolved config value, or ``fallback``.
    """
    from parrot import conf

    return conf.config.get(key, fallback=fallback)


def _get_bool(getter: ConfigGetter, key: str, fallback: bool) -> bool:
    """Resolve a boolean config value tolerant of str/bool getters.

    Args:
        getter: A ``(key, fallback) -> Any`` callable.
        key: Env/config key.
        fallback: Default boolean when unset.

    Returns:
        The resolved boolean.
    """
    value = getter(key, fallback)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_dispatcher(
    spec: DevAgentSpec,
    *,
    redis_url: str,
    max_concurrent: int,
    stream_ttl_seconds: int,
    config_getter: ConfigGetter = _default_config_getter,
) -> Tuple[DevLoopCodeDispatcher, BaseModel]:
    """Materialize a ``DevAgentSpec`` into a dispatcher + dispatch profile.

    Mirrors the ``DEV_LOOP_DEVELOPMENT_AGENT`` if/elif block in
    ``examples/dev_loop/server.py`` (lines ~454-585), parametrized by
    ``spec`` instead of a single global env var. ``spec.model`` (when
    non-empty) always wins over the backend's env-var/hardcoded default.

    Args:
        spec: The dev-agent spec (backend + optional model override).
        redis_url: Redis URL passed to every dispatcher constructor.
        max_concurrent: Concurrency cap for this dispatcher's semaphore.
        stream_ttl_seconds: Redis stream TTL passed to every dispatcher.
        config_getter: ``(key, fallback) -> Any`` callable used to resolve
            per-backend model/behaviour env vars. Defaults to
            ``conf.config.get``; tests inject a fake for isolation.

    Returns:
        A ``(dispatcher, profile)`` tuple.

    Raises:
        ValueError: If ``spec.agent`` is not one of the known backends
            (should not happen given ``DevAgentSpec``'s ``Literal`` type,
            but guards against future drift).
    """
    common = {
        "redis_url": redis_url,
        "max_concurrent": max_concurrent,
        "stream_ttl_seconds": stream_ttl_seconds,
    }

    if spec.agent == "claude-code":
        dispatcher: DevLoopCodeDispatcher = ClaudeCodeDispatcher(**common)
        profile: BaseModel = ClaudeCodeDispatchProfile(
            model=spec.model or "claude-sonnet-4-6"
        )
        return dispatcher, profile

    if spec.agent == "codex":
        dispatcher = CodexCodeDispatcher(**common)
        profile = CodexCodeDispatchProfile(
            model=spec.model or config_getter("DEV_LOOP_CODEX_MODEL", "gpt-5.5")
        )
        return dispatcher, profile

    if spec.agent == "gemini":
        dispatcher = GeminiCodeDispatcher(**common)
        profile = GeminiCodeDispatchProfile(
            model=spec.model or config_getter("DEV_LOOP_GEMINI_MODEL", "auto")
        )
        return dispatcher, profile

    if spec.agent == "nvidia":
        dispatcher = LLMCodeDispatcher(**common)
        nvidia_model = spec.model or config_getter(
            "DEV_LOOP_NVIDIA_CODE_MODEL", "moonshotai/kimi-k2-instruct-0905"
        )
        profile = LLMCodeDispatchProfile(
            llm=f"nvidia:{nvidia_model}",
            enable_thinking=_get_bool(
                config_getter, "DEV_LOOP_NVIDIA_ENABLE_THINKING", False
            ),
            clear_thinking=_get_bool(
                config_getter, "DEV_LOOP_NVIDIA_CLEAR_THINKING", False
            ),
        )
        return dispatcher, profile

    if spec.agent == "grok":
        dispatcher = GrokCodeDispatcher(**common)
        profile = GrokCodeDispatchProfile(
            model=spec.model or config_getter("DEV_LOOP_GROK_MODEL", "grok-build-0.1")
        )
        return dispatcher, profile

    if spec.agent == "zai":
        dispatcher = ZaiCodeDispatcher(**common)
        profile = ZaiCodeDispatchProfile(
            model=spec.model or config_getter("DEV_LOOP_ZAI_MODEL", "glm-5.2"),
            enable_thinking=_get_bool(
                config_getter, "DEV_LOOP_ZAI_ENABLE_THINKING", True
            ),
            reasoning_effort=config_getter("DEV_LOOP_ZAI_REASONING_EFFORT", "max"),
        )
        return dispatcher, profile

    if spec.agent == "moonshot":
        dispatcher = MoonshotCodeDispatcher(**common)
        profile = MoonshotCodeDispatchProfile(
            model=spec.model or config_getter("DEV_LOOP_MOONSHOT_MODEL", "kimi-k3"),
            reasoning_effort=config_getter(
                "DEV_LOOP_MOONSHOT_REASONING_EFFORT", "max"
            ),
        )
        return dispatcher, profile

    raise ValueError(f"Unknown DevAgentBackend: {spec.agent!r}")


def parse_pool_env(config_getter: ConfigGetter) -> Optional[DevAgentPoolConfig]:
    """Parse ``DEV_LOOP_DEV_AGENTS`` / ``DEV_LOOP_DEV_ISOLATION`` into a config.

    Args:
        config_getter: ``(key, fallback) -> Any`` callable.

    Returns:
        A :class:`DevAgentPoolConfig`, or ``None`` when the env var is
        absent/empty, its JSON is malformed, or it fails Pydantic
        validation (e.g. unknown backend, empty agents list) — this is a
        degradation signal, never an exception.
    """
    raw = config_getter("DEV_LOOP_DEV_AGENTS", None)
    if not raw:
        return None

    try:
        agents_data = json.loads(raw)
        agents = [DevAgentSpec(**entry) for entry in agents_data]
        isolation = config_getter("DEV_LOOP_DEV_ISOLATION", None)
        kwargs: dict[str, Any] = {"agents": agents}
        if isolation:
            kwargs["isolation_mode"] = isolation
        return DevAgentPoolConfig(**kwargs)
    except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as exc:
        logger.warning(
            "DEV_LOOP_DEV_AGENTS is malformed (%s); ignoring pool config.", exc
        )
        return None


def resolve_pool_max(config_getter: ConfigGetter, *, default: int = 4) -> int:
    """Resolve the ``DEV_LOOP_DEV_POOL_MAX`` cap on total pool concurrency.

    Args:
        config_getter: ``(key, fallback) -> Any`` callable.
        default: Fallback cap when unset/unparsable.

    Returns:
        The resolved cap, always ``>= 1``.
    """
    raw = config_getter("DEV_LOOP_DEV_POOL_MAX", default)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        logger.warning(
            "DEV_LOOP_DEV_POOL_MAX=%r is not a valid int; using default %d.",
            raw,
            default,
        )
        return default
