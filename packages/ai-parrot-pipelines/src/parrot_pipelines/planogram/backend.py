"""LLM backend (provider + model) resolution for planogram pipelines (FEAT-574)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, Tuple, Union

from pydantic import BaseModel

from parrot.clients.factory import LLMFactory  # verified: parrot/clients/factory.py:163
from parrot.conf import DEFAULT_LLM_MODEL  # verified: parrot/conf.py:443


class _Unset(Enum):
    """Sentinel type for 'argument omitted' (distinct from None and from "google")."""

    UNSET = "unset"


UNSET = _Unset.UNSET

#: The single documented package default — today's effective handler behaviour.
DEFAULT_LLM_BACKEND: str = f"google:{DEFAULT_LLM_MODEL}"

BackendOrigin = Literal["llm_instance", "llm_string", "constructor", "config", "package_default"]


class ResolvedBackend(BaseModel):
    """Provider/model a pipeline run resolved to, and where the decision came from."""

    provider: str
    model: Optional[str] = None  # None ⇒ provider default
    origin: BackendOrigin

    def as_string(self) -> str:
        """Return ``"provider:model"``, or just ``"provider"`` when no model is pinned."""
        return f"{self.provider}:{self.model}" if self.model else self.provider


def _parse(backend: str) -> Tuple[str, Optional[str]]:
    """Parse ``"provider:model"``; raise ValueError on an empty provider or a non-string.

    Args:
        backend: Backend string (``"provider"`` or ``"provider:model"``).

    Returns:
        ``(provider lower-cased, model or None)``.

    Raises:
        ValueError: ``backend`` is not a string, is blank, or has an empty provider.
    """
    if not isinstance(backend, str) or not backend.strip():
        raise ValueError(f"Invalid llm backend: {backend!r}")
    provider, model = LLMFactory.parse_llm_string(backend.strip())
    provider = provider.strip().lower()
    if not provider:
        raise ValueError(f"Invalid llm backend: {backend!r}")
    return provider, (model or None)


def resolve_backend(
    llm: Any,
    llm_provider: Union[str, _Unset],
    llm_model: Union[str, None, _Unset],
    config_backend: Optional[str],
) -> ResolvedBackend:
    """Resolve the backend by the FEAT-574 precedence.

    Order: explicit ``llm`` (instance or "provider:model" string) → explicit
    ``llm_provider`` / ``llm_model`` overrides applied to the configured backend →
    ``config_backend`` → ``DEFAULT_LLM_BACKEND``. A provider switch without a model
    never inherits the other provider's model id.

    Args:
        llm: A client instance, a ``"provider[:model]"`` string, or ``None``.
        llm_provider: Explicit provider, or ``UNSET`` when omitted.
        llm_model: Explicit model, ``None`` or ``UNSET`` (both mean "not given").
        config_backend: ``PlanogramConfig.llm_backend`` (may be ``None``).

    Returns:
        The resolved backend with its origin.

    Raises:
        ValueError: For an unparseable backend string.
    """
    # Row 1 — an injected client instance wins over everything.
    if llm is not None and not isinstance(llm, str):
        return ResolvedBackend(
            provider=str(llm.client_name).lower(),
            model=getattr(llm, "model", None),
            origin="llm_instance",
        )
    # Row 2 — an explicit "provider[:model]" string.
    if isinstance(llm, str):
        provider, model = _parse(llm)
        return ResolvedBackend(provider=provider, model=model, origin="llm_string")

    if config_backend is not None:
        base_provider, base_model = _parse(config_backend)
        base_origin: BackendOrigin = "config"
    else:
        base_provider, base_model = _parse(DEFAULT_LLM_BACKEND)
        base_origin = "package_default"

    provider_given = llm_provider is not UNSET
    model_given = llm_model is not UNSET and llm_model is not None

    # Row 3 — nothing explicit: the configured (or package default) backend.
    if not provider_given and not model_given:
        return ResolvedBackend(provider=base_provider, model=base_model, origin=base_origin)

    if provider_given:
        provider = str(llm_provider).strip().lower()
        if not provider:
            raise ValueError(f"Invalid llm_provider: {llm_provider!r}")
        if model_given:
            # Row 6 — explicit provider and model.
            return ResolvedBackend(provider=provider, model=str(llm_model), origin="constructor")
        if provider == base_provider:
            # Row 4 — same provider: keep the base model.
            return ResolvedBackend(provider=provider, model=base_model, origin="constructor")
        # Row 5 — provider switch: never inherit the other provider's model id.
        return ResolvedBackend(provider=provider, model=None, origin="constructor")

    # Row 7 — explicit model only: applied to the base provider.
    return ResolvedBackend(provider=base_provider, model=str(llm_model), origin="constructor")
