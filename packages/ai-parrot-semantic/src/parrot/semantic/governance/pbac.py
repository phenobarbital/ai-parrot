"""Two-phase PBAC gate over DataPlanePolicyGuard — never reaches its fail-open branch."""

from __future__ import annotations

import importlib.util
import logging

from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

from parrot.auth import DataPlanePolicyGuard, PermissionContext
from parrot.auth.exceptions import AuthorizationRequired
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

from ..errors import SemanticAccessError
from ..loader import LoadedModel

_PBAC_MODULES = (
    "navigator_auth.abac.policies.environment",
    "navigator_auth.abac.policies.evaluator",
)


class PbacGate:
    """Fail-closed adapter around the core data-plane policy guard."""

    def __init__(self, guard: DataPlanePolicyGuard | None) -> None:
        """Probe the exact PBAC modules and require a configured evaluator.

        Args:
            guard: Core policy guard configured by the host application.
        """
        self.guard = guard
        self.logger = logging.getLogger(__name__)
        try:
            modules_available = all(importlib.util.find_spec(module) is not None for module in _PBAC_MODULES)
        except (ImportError, ModuleNotFoundError, ValueError):
            modules_available = False
        self.available = bool(
            modules_available and guard is not None and getattr(guard, "_evaluator", None) is not None
        )

    async def authorize_manifest(self, ctx: PermissionContext | None, model: LoadedModel) -> PhysicalResources:
        """Authorize a model's complete declared resource manifest.

        Args:
            ctx: Trusted request permission context.
            model: Fully loaded semantic model.

        Returns:
            The authorized manifest for the post-compilation subset check.

        Raises:
            SemanticAccessError: If authorization cannot be completed.
        """
        manifest = PhysicalResources(
            driver=model.schema.driver,
            tables={f"{model.schema.driver}:{table}" for table in model.schema.tables},
        )
        await self.authorize(ctx, manifest, governed=model.policy.governed)
        return manifest

    async def authorize(
        self,
        ctx: PermissionContext | None,
        resources: PhysicalResources,
        *,
        governed: bool,
        manifest: PhysicalResources | None = None,
    ) -> None:
        """Authorize resources while closing every core fail-open path.

        Args:
            ctx: Trusted request permission context.
            resources: Physical resources used by the qualified query.
            governed: Whether the model opted into governance.
            manifest: Previously authorized pre-compilation manifest.

        Raises:
            SemanticAccessError: On absent identity, unavailable PBAC, manifest
                mismatch, or policy denial.
        """
        if not governed:
            return
        if ctx is None:
            raise SemanticAccessError("no_subject", "A governed query requires a permission context")
        if not self.available or self.guard is None:
            raise SemanticAccessError("pbac_unavailable", "The PBAC evaluator is unavailable")
        if manifest is not None and (
            resources.driver != manifest.driver or not resources.tables.issubset(manifest.tables)
        ):
            raise SemanticAccessError("outside_manifest", "The query uses resources outside the authorized manifest")
        try:
            await self.guard.authorize_source(ctx, resources)
        except AuthorizationRequired as exc:
            self.logger.warning("Semantic PBAC denied access to a governed resource")
            raise SemanticAccessError("pbac_denied", "PBAC denied the governed query") from exc


def resources_from_ast(tree: exp.Expression, driver: str) -> PhysicalResources:
    """Resolve physical tables from a qualified AST, excluding CTE aliases.

    Args:
        tree: Qualified sqlglot expression.
        driver: Canonical physical driver name.

    Returns:
        Physical resources addressed by real table sources in the AST.
    """
    tables: set[str] = set()
    for scope in traverse_scope(tree):
        for _, source in scope.selected_sources.values():
            if not isinstance(source, exp.Table) or not source.name:
                continue
            qualified_name = ".".join(part for part in (source.catalog, source.db, source.name) if part)
            tables.add(f"{driver}:{qualified_name}")
    return PhysicalResources(driver=driver, tables=tables)
