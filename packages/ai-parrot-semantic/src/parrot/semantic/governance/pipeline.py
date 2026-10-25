"""Fixed-order request-local governance with exact provenance."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.qualify import qualify

from parrot.auth import PermissionContext
from parrot.security.query_validator import QueryValidator
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

from ..errors import SemanticAccessError, SemanticError, SemanticValidationError
from ..loader import LoadedModel
from ..models import GovernedQuery
from .guard import PositiveGuard, effective_allowed_functions
from .lineage import ColumnUse, enforce_usage_rights, resolve_column_uses
from .masking import apply_masks
from .pbac import PbacGate, resources_from_ast
from .rls import RlsPushdown

# Physical driver names that differ from their sqlglot dialect name.
_DRIVER_DIALECTS: dict[str, str] = {
    "pg": "postgres",
    "postgresql": "postgres",
    "asyncpg": "postgres",
    "bq": "bigquery",
}

_SUBJECT_SCHEMA = "parrot.semantic.subject.v1"


def _typed(value: Any) -> Any:
    """Encode one metadata value as canonical typed JSON.

    Raises:
        SemanticAccessError: For values without a stable canonical encoding.
    """
    if value is None:
        return {"t": "null"}
    if isinstance(value, bool):
        return {"t": "bool", "v": value}
    if isinstance(value, int):
        return {"t": "int", "v": str(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SemanticAccessError("unstable_subject", "Subject metadata contains a non-finite number")
        return {"t": "float", "v": repr(value)}
    if isinstance(value, str):
        return {"t": "str", "v": value}
    if isinstance(value, (list, tuple)):
        return {"t": "list", "v": [_typed(item) for item in value]}
    if isinstance(value, (set, frozenset)):
        encoded = [_typed(item) for item in value]
        encoded.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
        return {"t": "set", "v": encoded}
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise SemanticAccessError("unstable_subject", "Subject metadata keys must be strings")
        return {"t": "map", "v": {key: _typed(item) for key, item in sorted(value.items())}}
    raise SemanticAccessError(
        "unstable_subject",
        "Subject metadata contains an unsupported value type",
        details={"type": type(value).__name__},
    )


def subject_digest(ctx: PermissionContext | None) -> str:
    """Hash canonical typed subject metadata, never the dataclass hash or repr.

    The digest covers user id, tenant id, sorted roles and every session
    metadata item (policy-relevant: RLS subject attributes are read from it),
    each encoded with an explicit type tag so ``"1"`` and ``1`` never collide.

    Args:
        ctx: Trusted request permission context; ``None`` only for ungoverned calls.

    Returns:
        Hex SHA-256 digest of the canonical subject document.

    Raises:
        SemanticAccessError: If identity fields or metadata are not canonically encodable.
    """
    if ctx is None:
        document: dict[str, Any] = {"schema": _SUBJECT_SCHEMA, "anonymous": True}
    else:
        session = ctx.session
        if not isinstance(session.user_id, str) or not isinstance(session.tenant_id, str):
            raise SemanticAccessError("unstable_subject", "Subject identity fields must be strings")
        roles = list(session.roles)
        if not all(isinstance(role, str) for role in roles):
            raise SemanticAccessError("unstable_subject", "Subject roles must be strings")
        metadata = session.metadata or {}
        if not isinstance(metadata, dict):
            raise SemanticAccessError("unstable_subject", "Subject metadata must be a mapping")
        document = {
            "schema": _SUBJECT_SCHEMA,
            "anonymous": False,
            "user_id": session.user_id,
            "tenant_id": session.tenant_id,
            "roles": sorted(roles),
            "metadata": _typed(dict(metadata)),
        }
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _dialect_for(driver: str) -> str:
    """Return the sqlglot dialect for a physical driver, denying unknown drivers."""
    dialect = _DRIVER_DIALECTS.get(driver, driver)
    try:
        sqlglot.Dialect.get_or_raise(dialect)
    except (ValueError, SqlglotError) as exc:
        raise SemanticValidationError("unsupported_dialect", "The model driver has no known SQL dialect") from exc
    return dialect


@dataclass
class _Prepared:
    """CPU-stage output handed across the PBAC await."""

    tree: exp.Expression
    resources: PhysicalResources
    uses: list[ColumnUse]


class GovernancePipeline:
    """Authorize and rewrite a clone; never mutate reusable compilation output."""

    def __init__(self, *, pbac: PbacGate, rls: RlsPushdown, allowed_functions: frozenset[str]) -> None:
        """Create a pipeline sharing only immutable collaborators across requests.

        Args:
            pbac: Fail-closed PBAC gate.
            rls: Unbound RLS pass; a request-local copy is bound per call.
            allowed_functions: Toolkit-level additive function allowlist extensions.
        """
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
    ) -> GovernedQuery:
        """Validate, qualify, authorize, resolve lineage, push RLS, mask and cap.

        Order: negative validation → qualification → resource subset/PBAC →
        usage lineage → RLS → masking → positive guard → render. CPU AST passes
        run in a worker thread; PBAC is awaited on every call. The caller
        performs the pre-compile manifest gate.

        Args:
            sql: Compiled (or raw) SQL text; never mutated.
            model: Loaded model snapshot; never mutated.
            ctx: Trusted request permission context.
            roles: Trusted roles of the subject.

        Returns:
            The governed query with exact provenance.

        Raises:
            SemanticAccessError: On any authorization, lineage or RLS denial.
            SemanticValidationError: On unsafe or unsupported SQL.
        """
        digest = subject_digest(ctx)
        dialect = _dialect_for(model.schema.driver)
        prepared = await asyncio.to_thread(self._prepare, sql, model, dialect)
        manifest = PhysicalResources(
            driver=model.schema.driver,
            tables={f"{model.schema.driver}:{table}" for table in model.schema.tables},
        )
        await self.pbac.authorize(ctx, prepared.resources, governed=model.policy.governed, manifest=manifest)
        return await asyncio.to_thread(self._finish, prepared, model, ctx, roles, dialect, digest)

    def _prepare(self, sql: str, model: LoadedModel, dialect: str) -> _Prepared:
        """Negative validation, qualification on a parsed clone, resources and lineage."""
        verdict = QueryValidator.validate_sql_ast(sql, dialect=dialect, read_only=True)
        if not verdict.get("is_safe"):
            raise SemanticValidationError("unsafe_sql", "The SQL failed read-only validation")
        try:
            statements = [statement for statement in sqlglot.parse(sql, dialect=dialect) if statement is not None]
            if len(statements) != 1:
                raise SemanticValidationError("not_select", "Exactly one statement is required")
            tree = qualify(
                statements[0].copy(),
                schema=model.schema.sqlglot_schema(),
                dialect=dialect,
                validate_qualify_columns=True,
            )
        except SemanticError:
            raise
        except SqlglotError as exc:
            raise SemanticValidationError(
                "unqualifiable_sql", "The SQL cannot be qualified against the schema"
            ) from exc
        resources = resources_from_ast(tree, model.schema.driver)
        uses = resolve_column_uses(tree, model.schema)
        return _Prepared(tree=tree, resources=resources, uses=uses)

    def _finish(
        self,
        prepared: _Prepared,
        model: LoadedModel,
        ctx: PermissionContext | None,
        roles: frozenset[str],
        dialect: str,
        digest: str,
    ) -> GovernedQuery:
        """Usage rights, RLS, masking, positive guard, render and provenance."""
        policy = model.policy
        trusted: set[int] = set()
        enforce_usage_rights(prepared.uses, policy, roles, trusted_nodes=trusted)

        tree = prepared.tree
        tables = sorted(
            ".".join(part for part in (t.catalog, t.db, t.name) if part)
            for t in tree.find_all(exp.Table)
            if ".".join(part for part in (t.catalog, t.db, t.name) if part) in model.schema.tables
        )
        rls_applied: tuple[str, ...] = ()
        if ctx is None:
            if self.rls.registry.lookup(model.schema.driver, set(tables)):
                raise SemanticAccessError("no_subject", "Row-level rules require a permission context")
        else:
            bound = self.rls._for_schema(model.schema)
            tree, rls_applied, rls_nodes = bound.apply(tree, ctx, model.schema.driver)
            if rls_nodes:
                try:
                    # Expand the injected `SELECT *` wrappers and qualify their predicate columns.
                    tree = qualify(
                        tree,
                        schema=model.schema.sqlglot_schema(),
                        dialect=dialect,
                        validate_qualify_columns=True,
                    )
                except SqlglotError as exc:
                    raise SemanticAccessError("rls_unplaceable", "RLS output cannot be re-qualified") from exc

        tree, masked, mask_nodes = apply_masks(tree, prepared.uses, policy, roles, dialect)
        trusted.update(mask_nodes)

        guard = PositiveGuard(
            model.schema,
            effective_allowed_functions(policy, self.allowed_functions),
            policy.limits,
        )
        tree = guard.check_and_limit(tree, trusted_nodes=trusted)
        limit_node = tree.args.get("limit")
        limit_value = limit_node.expression if isinstance(limit_node, exp.Limit) else limit_node
        try:
            rendered = tree.sql(dialect=dialect)
        except SqlglotError as exc:
            raise SemanticValidationError("render_failed", "The governed SQL cannot be rendered") from exc

        physical_columns = tuple(sorted({f"{use.table}.{use.column}" for use in prepared.uses}))
        return GovernedQuery(
            sql=rendered,
            dialect=dialect,
            driver=model.schema.driver,
            tables=tuple(tables),
            rls_applied=rls_applied,
            masked_columns=masked,
            limit=int(limit_value.this),
            subject_digest=digest,
            members=self._members(model, prepared, physical_columns),
            physical_columns=physical_columns,
        )

    @staticmethod
    def _members(model: LoadedModel, prepared: _Prepared, physical_columns: tuple[str, ...]) -> tuple[str, ...]:
        """Map qualified physical lineage to the root model's semantic members.

        Ambiguity is resolved conservatively: every member whose physical input
        appears in the lineage is retained (a superset never weakens later
        re-authorization). Derived metrics are retained when all their
        dependencies are, and dependencies are always closed over.
        """
        root = model.model
        used = set(physical_columns)
        table_used = any(resource.endswith(f":{root.table}") for resource in prepared.resources.tables)
        has_count_star = any(isinstance(node.this, exp.Star) for node in prepared.tree.find_all(exp.Count))
        members: set[str] = set()
        for dimension in root.dimensions:
            if f"{root.table}.{dimension.column}" in used:
                members.add(dimension.name)
        derived: dict[str, set[str]] = {}
        for metric in root.metrics:
            if metric.sql is not None:
                derived[metric.name] = _derived_dependencies(metric.sql, root.name)
            elif metric.column is not None:
                if f"{root.table}.{metric.column}" in used:
                    members.add(metric.name)
            elif table_used and has_count_star:
                members.add(metric.name)
        changed = True
        while changed:
            changed = False
            for name, dependencies in derived.items():
                if name not in members and dependencies and dependencies <= members:
                    members.add(name)
                    changed = True
        return tuple(sorted(members))


def _derived_dependencies(expression: str, model_name: str) -> set[str]:
    """Return the root-local metric names a derived expression references.

    A reference to another model can never be satisfied by root members, so it
    yields an unsatisfiable marker and the derived metric is not retained.
    """
    dependencies: set[str] = set()
    for token in expression.replace("(", " ").replace(")", " ").split():
        if "." not in token:
            continue
        owner, _, local = token.partition(".")
        if not owner.isidentifier() or not local.isidentifier():
            continue
        dependencies.add(local if owner == model_name else f"\0{owner}.{local}")
    return dependencies
