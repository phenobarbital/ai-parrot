"""Per-component LLM defaults (FEAT-796).

Resolves ``<COMPONENT>_LLM`` -> ``DEFAULT_LLM`` -> builtin (all ``provider:model``) and
``<COMPONENT>_<PROVIDER>_API_KEY`` -> legacy vars -> ``None``. Key values are never logged.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal, Optional, Sequence

from navconfig import config
from pydantic import BaseModel

from parrot import conf

logger = logging.getLogger(__name__)


class ComponentLLM(BaseModel):
    """Resolved provider/model for a component plus where it came from."""

    provider: str
    model: str
    source: Literal["component", "global", "builtin", "agent"]


def _split(value: str, *, var: str, default_provider: str) -> tuple[str, str]:
    """Split ``provider:model`` (bare ``model`` inherits ``default_provider``).

    Raises:
        ValueError: Naming ``var`` when the value is empty, has an empty side,
            or the provider is not a ``SUPPORTED_CLIENTS`` key.
    """
    from parrot.clients.factory import SUPPORTED_CLIENTS  # noqa: PLC0415 — conf import cycle

    value = value.strip()
    provider, separator, model = value.partition(":")
    if not separator:
        provider, model = default_provider, provider
    provider = provider.strip().lower()
    model = model.strip()
    if not provider or not model:
        raise ValueError(f"{var}: provider and model must both be set")
    if provider not in SUPPORTED_CLIENTS:
        raise ValueError(f"{var}: unsupported provider '{provider}'")
    return provider, model


def resolve_component_llm(component: str, *, builtin: str) -> ComponentLLM:
    """Resolve ``<COMPONENT>_LLM`` -> ``DEFAULT_LLM`` -> ``builtin``."""
    builtin_provider, builtin_model = builtin.split(":", 1)
    var = f"{component.upper()}_LLM"
    value = config.get(var)
    if value:
        provider, model = _split(value, var=var, default_provider=builtin_provider)
        return ComponentLLM(provider=provider, model=model, source="component")
    global_value = getattr(conf, "DEFAULT_LLM", None)
    if global_value:
        provider, model = _split(global_value, var="DEFAULT_LLM", default_provider=builtin_provider)
        return ComponentLLM(provider=provider, model=model, source="global")
    return ComponentLLM(provider=builtin_provider, model=builtin_model, source="builtin")


def provider_key_token(provider: str) -> str:
    """``google``/``gemini-live``/``google-compat`` -> ``GOOGLE``; else upper snake case."""
    from parrot.bots.flows.crew.credentials import GOOGLE_PROVIDER_KEYS  # noqa: PLC0415

    if provider.lower() in GOOGLE_PROVIDER_KEYS:
        return "GOOGLE"
    return provider.upper().replace("-", "_")


def resolve_component_api_key(components: Sequence[str], provider: str, *, legacy: Sequence[str] = ()) -> Optional[str]:
    """First set ``<C>_<TOKEN>_API_KEY`` for C in ``components``, then ``legacy`` vars, else None."""
    token = provider_key_token(provider)
    for name in [f"{component.upper()}_{token}_API_KEY" for component in components] + list(legacy):
        value = config.get(name)
        if value:
            return value
    return None


#: Every component with a ``<COMPONENT>_<PROVIDER>_API_KEY`` default (FEAT-882 rev 0.2).
COMPONENTS: tuple[str, ...] = (
    "AGENT",
    "CREW",
    "FLOW",
    "EXPERT_JUDGMENT",
    "EXPERT_BALANCED",
    "EXPERT_TEMPLATED",
)

#: Legacy component-default variables (Google only).
_LEGACY_COMPONENT_KEYS: tuple[str, ...] = ("CREW_AI_KEY",)

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def agent_env_token(name: str) -> str:
    """Return an environment-variable token derived from an agent name.

    Args:
        name: The agent's name.

    Returns:
        Upper-case ``name`` with non-alphanumeric runs replaced by ``_``.
    """
    return _NON_ALNUM.sub("_", name or "").strip("_").upper()


def resolve_agent_llm(name: str, *, default_provider: str) -> Optional[ComponentLLM]:
    """Resolve an agent-specific model declaration.

    Args:
        name: The agent name used to derive the environment-variable token.
        default_provider: Provider used for a bare model declaration.

    Returns:
        The resolved agent model, or ``None`` when it is unset.

    Raises:
        ValueError: If the configured model declaration is invalid.
    """
    token = agent_env_token(name)
    if not token:
        return None
    var = f"{token}_MODEL"
    value = config.get(var)
    if not value:
        return None
    provider, model = _split(value, var=var, default_provider=default_provider)
    return ComponentLLM(provider=provider, model=model, source="agent")


def resolve_agent_api_key(name: str, provider: str) -> Optional[str]:
    """Return an agent-specific provider API key, if configured.

    Args:
        name: The agent name used to derive the environment-variable token.
        provider: Provider name used to derive the credential key token.

    Returns:
        The configured key or ``None``. The key is never logged.
    """
    token = agent_env_token(name)
    if not token:
        return None
    return resolve_component_api_key((token,), provider)


def is_component_default_key(api_key: Optional[str], provider: str) -> bool:
    """Report whether a key is configured as a component default.

    Args:
        api_key: Candidate API key value.
        provider: Provider whose component-default keys are checked.

    Returns:
        ``True`` when the candidate equals a configured component-default key.
    """
    if not api_key:
        return False
    token = provider_key_token(provider)
    names = [f"{component}_{token}_API_KEY" for component in COMPONENTS]
    if token == "GOOGLE":
        names.extend(_LEGACY_COMPONENT_KEYS)
    return any(config.get(name) == api_key for name in names)


def _raw_llm_provider(llm: Any, default_provider: Optional[str]) -> Optional[str]:
    """Determine the provider declared by a raw LLM setting.

    Args:
        llm: Raw LLM declaration from an agent.
        default_provider: Provider to use when ``llm`` is absent.

    Returns:
        The lower-case provider, or ``None`` when it cannot safely be inferred.
    """
    if llm is None:
        return default_provider.lower() if default_provider else None
    if isinstance(llm, str):
        provider = llm.split(":", 1)[0].strip()
        return provider.lower() if provider else None
    if isinstance(llm, type):
        provider = getattr(llm, "client_name", None)
        return provider.lower() if isinstance(provider, str) and provider else None
    return None


def apply_component_api_key(agent: Any, component: str) -> bool:
    """Inject a component API key into an unconfigured agent.

    Args:
        agent: Agent exposing raw LLM and LLM keyword attributes.
        component: Component whose configured default key is injected.

    Returns:
        ``True`` if a key was injected into a rebound kwargs dictionary.
    """
    from parrot.bots.flows.crew.credentials import has_explicit_google_credential  # noqa: PLC0415

    if getattr(agent, "is_configured", False):
        return False
    if not hasattr(agent, "_llm_raw") or not hasattr(agent, "_llm_kwargs"):
        return False
    provider = _raw_llm_provider(agent._llm_raw, getattr(agent, "_default_llm", "google"))
    if not provider:
        return False
    llm_kwargs = agent._llm_kwargs or {}
    if has_explicit_google_credential(llm_kwargs):
        return False
    api_key = resolve_component_api_key((component,), provider)
    if not api_key:
        return False
    agent._llm_kwargs = {**llm_kwargs, "api_key": api_key}
    logger.debug("Injected %s default API key into agent %r", component.upper(), getattr(agent, "name", None))
    return True
