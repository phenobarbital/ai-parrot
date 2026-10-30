"""Rewrite projected masked columns per MaskRule.strategy (null / md5-hash / partial)."""

from __future__ import annotations

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, build_scope

from ..errors import SemanticAccessError
from ..loader import PhysicalSchema
from ..policy import MaskRule, ModelPolicy
from .lineage import ColumnUse, _resolve_column

_PARTIAL_VISIBLE_CHARS = 2
_PARTIAL_SUFFIX = "****"


def _schema_from_uses(uses: list[ColumnUse]) -> PhysicalSchema:
    """Build a lineage-only schema map from already-resolved physical uses."""
    tables: dict[str, dict[str, str]] = {}
    for use in uses:
        tables.setdefault(use.table, {})[use.column] = "TEXT"
    return PhysicalSchema(driver="lineage", tables=tables)


def _scope_index(root: Scope) -> dict[int, Scope]:
    """Map every query expression identity to its scope."""
    return {id(scope.expression): scope for scope in root.traverse()}


def _projection_lineage(
    projection: exp.Expression,
    root: Scope,
    scopes: dict[int, Scope],
    schema: PhysicalSchema,
) -> set[str]:
    """Resolve every physical column a root projection derives from.

    Raises:
        SemanticAccessError: When a projection cannot be traced safely.
    """
    if any(isinstance(node, exp.Star) and not isinstance(node.parent, exp.Count) for node in projection.walk()):
        raise SemanticAccessError("unresolved_lineage", "A star projection must be expanded before masking")
    resolved: set[str] = set()
    for column in projection.find_all(exp.Column):
        query = column.find_ancestor(exp.Select, exp.Union)
        scope = scopes.get(id(query)) if query is not None else root
        if scope is None:
            raise SemanticAccessError("unresolved_lineage", "A projected column has no resolvable scope")
        if not column.table and scope is root:
            # Output-alias references inside the root projection list do not occur in valid SQL.
            raise SemanticAccessError("unresolved_lineage", "A projected column is not qualified")
        pairs = _resolve_column(column, scope, schema, set())
        resolved.update(f"{table}.{name}" for table, name in pairs)
    return resolved


def _as_text(expression: exp.Expression, dialect: str) -> exp.Expression:
    """Cast an expression to the dialect's text type."""
    return exp.Cast(this=expression, to=exp.DataType.build("TEXT", dialect=dialect))


def _strategy_expression(rule: MaskRule, original: exp.Expression, dialect: str) -> exp.Expression:
    """Return the masking expression for one strategy."""
    if rule.strategy == "null":
        return exp.Null()
    if rule.strategy == "hash":
        return exp.MD5(this=_as_text(original, dialect))
    return exp.Concat(
        expressions=[
            exp.Substring(
                this=_as_text(original, dialect),
                start=exp.Literal.number(1),
                length=exp.Literal.number(_PARTIAL_VISIBLE_CHARS),
            ),
            exp.Literal.string(_PARTIAL_SUFFIX),
        ],
        safe=True,
        coalesce=True,
    )


_STRICTNESS = {"null": 0, "hash": 1, "partial": 2}


def apply_masks(
    tree: exp.Expression,
    uses: list[ColumnUse],
    policy: ModelPolicy,
    roles: frozenset[str],
    dialect: str,
) -> tuple[exp.Expression, tuple[str, ...], set[int]]:
    """Rewrite projected masked columns in place.

    Every root projection whose physical lineage includes a masked column (for
    the given roles) is replaced by the strategy expression, aliased to the
    original output name. Derived projections (``UPPER(email)``, windows,
    CTE/subquery passthroughs) are masked as a whole. When several masked
    columns feed one projection, the strictest strategy wins.

    Args:
        tree: A qualified sqlglot query AST (mutated in place).
        uses: Physical column uses resolved from the unmodified query.
        policy: Model governance policy.
        roles: Trusted roles from the permission context.
        dialect: Target SQL dialect.

    Returns:
        The rewritten tree, sorted masked ``table.column`` names, and the
        identities of every pipeline-injected node.

    Raises:
        SemanticAccessError: When masked lineage cannot be placed safely.
    """
    # Every use context is a candidate: the root-projection lineage below decides what is exposed
    # (a window or CASE over a masked column still projects it).
    candidates = {
        f"{use.table}.{use.column}": rule
        for use in uses
        if (rule := policy.mask_for(roles, f"{use.table}.{use.column}")) is not None
    }
    if not candidates:
        return tree, (), set()
    if not isinstance(tree, exp.Select):
        raise SemanticAccessError("unresolved_lineage", "Masked columns require a single SELECT root")
    root = build_scope(tree)
    if root is None:
        raise SemanticAccessError("unresolved_lineage", "The query has no resolvable scope")
    scopes = _scope_index(root)
    schema = _schema_from_uses(uses)

    masked: set[str] = set()
    trusted: set[int] = set()
    projections = list(tree.expressions)
    for index, projection in enumerate(projections):
        lineage = _projection_lineage(projection, root, scopes, schema)
        hits = sorted(lineage.intersection(candidates))
        if not hits:
            continue
        rule = min((candidates[name] for name in hits), key=lambda item: _STRICTNESS[item.strategy])
        original = projection.this if isinstance(projection, exp.Alias) else projection
        output_name = projection.alias_or_name
        inner = original.copy()
        replacement = exp.alias_(
            _strategy_expression(rule, inner, dialect), output_name or f"masked_{index}", quoted=True, copy=False
        )
        # Only pipeline-built wrapper nodes are trusted; the caller's original expression never is.
        caller_ids = {id(node) for node in inner.walk()}
        trusted.update(id(node) for node in replacement.walk() if id(node) not in caller_ids)
        projection.replace(replacement)
        masked.update(hits)
    return tree, tuple(sorted(masked)), trusted
