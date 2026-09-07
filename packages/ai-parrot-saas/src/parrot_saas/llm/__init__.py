"""Per-tenant LLM agents built from the tenant's own API keys (BYOK).

Exports are resolved lazily (PEP 562), following the convention of the parent
package: :mod:`~parrot_saas.llm.builder` reaches into ``parrot.bots`` and the
provider SDKs, which is a heavy import to pay for merely naming an exception
type or a secret name.
"""
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from .builder import (
        AgentSpec,
        build_agent,
        build_tenant_agents,
        default_cm_agent_specs,
    )
    from .credentials import (
        ANTHROPIC_API_KEY_SECRET,
        GOOGLE_API_KEY_SECRET,
        TenantCredentialMissing,
        require_secret,
    )

__all__ = (
    "ANTHROPIC_API_KEY_SECRET",
    "GOOGLE_API_KEY_SECRET",
    "AgentSpec",
    "TenantCredentialMissing",
    "build_agent",
    "build_tenant_agents",
    "default_cm_agent_specs",
    "require_secret",
)

_LAZY_EXPORTS = {
    "AgentSpec": ("parrot_saas.llm.builder", "AgentSpec"),
    "build_agent": ("parrot_saas.llm.builder", "build_agent"),
    "build_tenant_agents": ("parrot_saas.llm.builder", "build_tenant_agents"),
    "default_cm_agent_specs": (
        "parrot_saas.llm.builder",
        "default_cm_agent_specs",
    ),
    "ANTHROPIC_API_KEY_SECRET": (
        "parrot_saas.llm.credentials",
        "ANTHROPIC_API_KEY_SECRET",
    ),
    "GOOGLE_API_KEY_SECRET": (
        "parrot_saas.llm.credentials",
        "GOOGLE_API_KEY_SECRET",
    ),
    "TenantCredentialMissing": (
        "parrot_saas.llm.credentials",
        "TenantCredentialMissing",
    ),
    "require_secret": ("parrot_saas.llm.credentials", "require_secret"),
}


def __getattr__(name: str) -> Any:
    """Resolve lazily-exported names on first access (PEP 562).

    Args:
        name: Attribute being looked up on the package.

    Returns:
        The resolved object.

    Raises:
        AttributeError: If ``name`` is not a known lazy export.
    """
    try:
        module_path, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    from importlib import import_module

    return getattr(import_module(module_path), attr)


def __dir__() -> list[str]:
    """Expose lazy exports to ``dir()`` and tab-completion."""
    return sorted(__all__)
