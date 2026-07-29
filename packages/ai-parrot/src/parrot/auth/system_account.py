"""System-account principal for scheduled/background refreshes (FEAT-326, Module 5).

Scheduled recipe refreshes (FEAT-324 scheduler trigger) have no interactive
user identity, yet ``RecipeRunner.run()`` MUST receive a real
:class:`~parrot.auth.permission.PermissionContext` — a falsy ``pctx`` makes
``DatasetManager``'s PBAC/data-plane guards fail **OPEN** (documented hazard in
``parrot/tools/infographic_recipes/runner.py``).

This module provides a **config-declared system account** (the simplest
provisioning mechanism per spec §8 — no DB, no UI) plus a **fail-closed guard**
that resolves the account to a ``PermissionContext`` and refuses to run when it
cannot (never forwarding ``pctx=None``).

Provisioning (environment variables):
    ``PARROT_SYSTEM_ACCOUNT_ID``      — the system principal id (required to
                                        enable scheduled refreshes).
    ``PARROT_SYSTEM_ACCOUNT_TENANT``  — optional tenant id (defaults to the id).
    ``PARROT_SYSTEM_ACCOUNT_ROLES``   — optional comma-separated role claims.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from parrot.auth.exceptions import SystemAccountNotProvisioned
from parrot.auth.permission import PermissionContext, build_principal_context

logger = logging.getLogger(__name__)

_ENV_ID = "PARROT_SYSTEM_ACCOUNT_ID"
_ENV_TENANT = "PARROT_SYSTEM_ACCOUNT_TENANT"
_ENV_ROLES = "PARROT_SYSTEM_ACCOUNT_ROLES"


class SystemAccount(BaseModel):
    """A provisionable, non-interactive service principal.

    Attributes:
        account_id: The system principal identifier.
        tenant_id: Optional tenant/org id (defaults to ``account_id``).
        roles: Role claims for PBAC evaluation (empty by default — role-gated
            policies deny until real roles are provisioned).
    """

    model_config = ConfigDict(extra="forbid")

    account_id: str
    tenant_id: Optional[str] = None
    roles: frozenset[str] = Field(default_factory=frozenset)

    @classmethod
    def from_env(cls) -> Optional["SystemAccount"]:
        """Build the system account from environment config, or ``None``.

        Returns:
            A :class:`SystemAccount` when ``PARROT_SYSTEM_ACCOUNT_ID`` is set;
            ``None`` when the deployment has not provisioned one.
        """
        account_id = os.getenv(_ENV_ID)
        if not account_id:
            return None
        roles_raw = os.getenv(_ENV_ROLES, "")
        roles = frozenset(r.strip() for r in roles_raw.split(",") if r.strip())
        return cls(
            account_id=account_id,
            tenant_id=os.getenv(_ENV_TENANT) or None,
            roles=roles,
        )

    def to_permission_context(self, channel: str = "scheduler") -> PermissionContext:
        """Resolve this account into a :class:`PermissionContext`.

        Args:
            channel: Originating channel propagated to the context.

        Returns:
            A real ``PermissionContext`` (never falsy).
        """
        return build_principal_context(
            self.account_id,
            channel=channel,
            tenant_id=self.tenant_id,
            roles=self.roles or None,
        )


def resolve_system_account_context(
    channel: str = "scheduler",
    account: Optional[SystemAccount] = None,
) -> PermissionContext:
    """Resolve the system-account :class:`PermissionContext` or fail closed.

    Args:
        channel: Originating channel for the context.
        account: An explicit :class:`SystemAccount`; when omitted, resolved from
            environment config.

    Returns:
        A real ``PermissionContext``.

    Raises:
        SystemAccountNotProvisioned: When no system account is provisioned, or
            (defensively) when the resolved context is falsy — never returns a
            falsy context.
    """
    account = account or SystemAccount.from_env()
    if account is None:
        logger.error(
            "No system account provisioned (%s unset); refusing scheduled refresh.",
            _ENV_ID,
        )
        raise SystemAccountNotProvisioned(
            f"No system account is provisioned. Set {_ENV_ID} (and optionally "
            f"{_ENV_TENANT}/{_ENV_ROLES}) to enable scheduled refreshes."
        )
    ctx = account.to_permission_context(channel=channel)
    if not ctx:  # defensive — build_principal_context always returns truthy
        logger.error("System account %r resolved to a falsy context.", account.account_id)
        raise SystemAccountNotProvisioned(
            f"System account {account.account_id!r} resolved to a falsy "
            f"PermissionContext; refusing to run with pctx that fails open."
        )
    return ctx


async def run_scheduled_refresh(
    runner: Any,
    name: str,
    *,
    params: Optional[dict] = None,
    recipe_owner: Optional[str] = None,
    channel: str = "scheduler",
    account: Optional[SystemAccount] = None,
) -> Any:
    """Run a scheduled recipe refresh under the system-account principal.

    Fail-closed caller-side guard: resolves the system-account
    ``PermissionContext`` (raising if unresolvable) and passes it as ``pctx``.
    ``RecipeRunner`` is NEVER modified and ``pctx=None`` is NEVER forwarded.

    Args:
        runner: A ``RecipeRunner`` instance (its ``run`` coroutine is awaited).
        name: Recipe name to replay.
        params: Optional run parameters.
        recipe_owner: Optional recipe owner scope.
        channel: Originating channel for the resolved context.
        account: Optional explicit :class:`SystemAccount` (else env-resolved).

    Returns:
        Whatever ``runner.run`` returns (a ``RenderedArtifact``).

    Raises:
        SystemAccountNotProvisioned: When no resolvable system account exists.
    """
    pctx = resolve_system_account_context(channel=channel, account=account)
    logger.info(
        "Scheduled refresh of recipe %r under system account (channel=%s).",
        name, channel,
    )
    return await runner.run(
        name, params=params, pctx=pctx, recipe_owner=recipe_owner
    )


__all__ = (
    "SystemAccount",
    "SystemAccountNotProvisioned",
    "resolve_system_account_context",
    "run_scheduled_refresh",
)
