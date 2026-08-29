"""Tenant provisioning: one port, two planes.

``SharedDeployer`` prepares a tenant on the shared plane; ``PulumiDeployer``
builds it a stack of its own. Both implement :class:`TenantDeployer`, so the
control plane calls the same four methods either way.
"""
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from .base import TenantDeployer
    from .models import (
        Deployment,
        DeploymentMode,
        DeploymentResult,
        DeploymentStatus,
    )
    from .pulumi_deployer import PulumiDeployer
    from .repository import DeploymentRepository
    from .shared import SharedDeployer

__all__ = (
    "Deployment",
    "DeploymentMode",
    "DeploymentRepository",
    "DeploymentResult",
    "DeploymentStatus",
    "PulumiDeployer",
    "SharedDeployer",
    "TenantDeployer",
)

_LAZY_EXPORTS = {
    "TenantDeployer": ("parrot_saas.provisioning.base", "TenantDeployer"),
    "Deployment": ("parrot_saas.provisioning.models", "Deployment"),
    "DeploymentMode": ("parrot_saas.provisioning.models", "DeploymentMode"),
    "DeploymentResult": ("parrot_saas.provisioning.models", "DeploymentResult"),
    "DeploymentStatus": ("parrot_saas.provisioning.models", "DeploymentStatus"),
    "DeploymentRepository": (
        "parrot_saas.provisioning.repository",
        "DeploymentRepository",
    ),
    "SharedDeployer": ("parrot_saas.provisioning.shared", "SharedDeployer"),
    "PulumiDeployer": (
        "parrot_saas.provisioning.pulumi_deployer",
        "PulumiDeployer",
    ),
}


def __getattr__(name: str) -> Any:
    """Resolve lazily-exported names on first access (PEP 562)."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(target[0]), target[1])
