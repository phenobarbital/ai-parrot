"""Two-phase PBAC gate over DataPlanePolicyGuard — never reaches its fail-open branch."""

from __future__ import annotations

import importlib.util
import logging

from sqlglot import exp

from parrot.auth import DataPlanePolicyGuard, PermissionContext
from parrot.auth.exceptions import AuthorizationRequired
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

from ..errors import SemanticAccessError
from ..loader import LoadedModel


# DataPlanePolicyGuard fails open on an ImportError of this module, not of the ``navigator_auth`` root,
# so probing the root would report PBAC as enforceable while the guard silently allows everything.
_EVALUATOR_MODULE = "navigator_auth.abac.policies.environment"


def _evaluator_importable() -> bool:
    """Return whether the navigator-auth module the core guard imports at call time resolves."""
    try:
        return importlib.util.find_spec(_EVALUATOR_MODULE) is not None
    except (ImportError, ValueError):  # missing parent package, or a namespace package without a spec
        return False


class PbacGate:
    """Fail-closed adapter around the core data-plane policy guard."""

    def __init__(self, guard: DataPlanePolicyGuard | None) -> None:
        """Probe evaluator availability at construction (navigator-auth importable, guard not None)."""
        self.guard = guard
        self.available = guard is not None and _evaluator_importable()
        self.logger = logging.getLogger(__name__)

    async def authorize_manifest(self, ctx: PermissionContext | None, model: LoadedModel) -> PhysicalResources:
        """Authorize the model's driver and schema-map tables before compilation."""
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
        """Deny missing governance prerequisites, manifest escapes, and guard denials."""
        if not governed:
            return
        if ctx is None:
            raise SemanticAccessError("no_subject")
        if not self.available or self.guard is None:
            raise SemanticAccessError("pbac_unavailable")
        if manifest is not None and resources.tables - manifest.tables:
            raise SemanticAccessError("outside_manifest")
        try:
            await self.guard.authorize_source(ctx, resources)
        except AuthorizationRequired as error:
            raise SemanticAccessError("pbac_denied") from error


def resources_from_ast(tree: exp.Expression, driver: str) -> PhysicalResources:
    """Build physical resources from qualified AST tables, excluding CTE references."""
    cte_names = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    tables = {
        f"{driver}:{'.'.join(part for part in (table.db, table.name) if part)}"
        for table in tree.find_all(exp.Table)
        if table.name and not (not table.db and not table.catalog and table.name in cte_names)
    }
    return PhysicalResources(driver=driver, tables=tables)
