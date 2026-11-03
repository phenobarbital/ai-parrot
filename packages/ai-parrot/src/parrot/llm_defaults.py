"""Per-component LLM defaults (FEAT-796).

Resolves ``<COMPONENT>_LLM`` -> ``DEFAULT_LLM`` -> builtin (all ``provider:model``) and
``<COMPONENT>_<PROVIDER>_API_KEY`` -> legacy vars -> ``None``. Key values are never logged.
"""

from __future__ import annotations

from typing import Literal, Optional, Sequence

from navconfig import config
from pydantic import BaseModel

from parrot import conf


class ComponentLLM(BaseModel):
    """Resolved provider/model for a component plus where it came from."""

    provider: str
    model: str
    source: Literal["component", "global", "builtin"]


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
