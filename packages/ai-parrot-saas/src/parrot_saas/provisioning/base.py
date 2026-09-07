"""The port every tenant deployer implements.

One interface for both tenancy modes is the point. A shared tenant needs no
infrastructure at all and a dedicated one needs a Postgres, a Redis and a
worker container, but the control plane should not know that: it calls
``apply`` and reads a status either way. That is also what makes the two modes
testable against the same suite, and what leaves room for the AWS and GCP
deployers to be a sibling directory rather than a second code path.

Nothing here raises for an ordinary failure — see
:class:`~parrot_saas.provisioning.models.DeploymentResult` for why.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..tenancy.context import TenantContext
from .models import DeploymentResult


class TenantDeployer(ABC):
    """Provisions and tears down whatever serves one tenant.

    Attributes:
        name: Short identifier recorded on the deployment, so a row says which
            deployer produced it.
    """

    name: str = "deployer"

    @abstractmethod
    async def plan(self, tenant: TenantContext) -> DeploymentResult:
        """Describe what applying would change, without changing anything.

        Args:
            tenant: The tenant to plan for.

        Returns:
            The plan, with a resource summary when the backend reports one.
        """

    @abstractmethod
    async def apply(self, tenant: TenantContext) -> DeploymentResult:
        """Bring the tenant's infrastructure to its desired state.

        Must be idempotent: the control plane retries, and a second apply on a
        healthy tenant is a no-op that reports ``ready``.

        Args:
            tenant: The tenant to provision.

        Returns:
            The outcome.
        """

    @abstractmethod
    async def destroy(self, tenant: TenantContext) -> DeploymentResult:
        """Tear the tenant's infrastructure down.

        Args:
            tenant: The tenant to retire.

        Returns:
            The outcome.
        """

    @abstractmethod
    async def status(self, tenant: TenantContext) -> DeploymentResult:
        """Report what is currently deployed.

        Read-only, and cheap enough to poll — the control plane's status
        endpoint calls it on every request.

        Args:
            tenant: The tenant to inspect.

        Returns:
            The current state.
        """


__all__ = ("TenantDeployer",)
