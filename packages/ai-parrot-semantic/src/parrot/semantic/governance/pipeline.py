"""Fixed-order governance pass over a parsed clone (spec §2 step 3)."""

from __future__ import annotations

import hashlib
import json
import logging

import sqlglot
from sqlglot.optimizer.qualify import qualify

from parrot.auth import PermissionContext
from parrot.security import QueryValidator
from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect

from ..errors import SemanticValidationError
from ..loader import LoadedModel
from ..models import GovernedQuery
from .guard import PositiveGuard, effective_allowed_functions
from .lineage import enforce_usage_rights, resolve_column_uses
from .masking import apply_masks
from .pbac import PbacGate, resources_from_ast
from .rls import RlsPushdown


def subject_digest(ctx: PermissionContext | None) -> str:
    """Return a stable digest of the subject fields relevant to governance."""
    if ctx is None:
        return hashlib.sha256(b"anonymous").hexdigest()
    session = ctx.session
    raw = json.dumps(
        [
            session.user_id,
            session.tenant_id,
            sorted(session.roles),
            sorted((key, repr(value)) for key, value in session.metadata.items()),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


class GovernancePipeline:
    """Apply the semantic-layer's fail-closed governance stages in a fixed order."""

    def __init__(self, *, pbac: PbacGate, rls: RlsPushdown, allowed_functions: frozenset[str]) -> None:
        """Initialize the pipeline with its authorization and row-filtering dependencies."""
        self.pbac = pbac
        self.rls = rls
        self.allowed_functions = allowed_functions
        self.logger = logging.getLogger(__name__)

    async def govern(
        self,
        sql: str,
        *,
        model: LoadedModel,
        ctx: PermissionContext | None,
        roles: frozenset[str],
        requested_limit: int | None = None,
    ) -> GovernedQuery:
        """Govern a freshly parsed SQL tree and return only fully validated SQL.

        Args:
            sql: Pre-governance SQL, which is never mutated.
            model: Loaded semantic model that supplies physical schema and policy.
            ctx: Current authorization subject.
            roles: Roles active for the request.
            requested_limit: Optional requested result limit.

        Returns:
            A fully governed query ready for execution.

        Raises:
            SemanticAccessError: From authorization, lineage, or row-level security stages.
            SemanticValidationError: If raw SQL safety or positive validation fails.
        """
        driver = model.schema.driver
        dialect = driver_to_dialect(driver) or driver
        validation = QueryValidator.validate_sql_ast(sql, dialect=dialect, read_only=True)
        if not validation.get("is_safe", False):
            raise SemanticValidationError("unsafe_sql")

        try:
            tree = sqlglot.parse_one(sql, dialect=dialect)
            tree = qualify(tree, schema=model.schema.sqlglot_schema(), dialect=dialect)
        except Exception as error:
            raise SemanticValidationError("unsafe_sql") from error

        resources = resources_from_ast(tree, driver)
        rls_applied: tuple[str, ...] = ()
        masked_columns: tuple[str, ...] = ()
        trusted_nodes: set[int] = set()
        if model.policy.governed:
            manifest = await self.pbac.authorize_manifest(ctx, model)
            await self.pbac.authorize(ctx, resources, governed=True, manifest=manifest)
            uses = resolve_column_uses(tree, model.schema)
            enforce_usage_rights(uses, model.policy, roles, trusted_nodes=set())
            tree, rls_applied, rls_trusted_nodes = self.rls.apply(tree, ctx, driver, schema=model.schema)
            tree, masked_columns, mask_trusted_nodes = apply_masks(tree, uses, model.policy, roles, dialect)
            trusted_nodes = rls_trusted_nodes | mask_trusted_nodes

        tree = PositiveGuard(
            model.schema,
            effective_allowed_functions(model.policy, self.allowed_functions),
            model.policy.limits,
        ).check_and_limit(tree, requested_limit=requested_limit, trusted_nodes=trusted_nodes)
        limit = tree.args["limit"].expression
        return GovernedQuery(
            sql=tree.sql(dialect=dialect),
            dialect=dialect,
            driver=driver,
            tables=tuple(sorted(table.removeprefix(f"{driver}:") for table in resources.tables)),
            rls_applied=rls_applied,
            masked_columns=masked_columns,
            limit=int(limit.this),
            subject_digest=subject_digest(ctx),
        )
