"""Positive SQL guard: single SELECT, allowlisted tables/columns/functions, forced LIMIT."""

from __future__ import annotations

from sqlglot import exp
from sqlglot.optimizer.scope import build_scope

from ..errors import SemanticValidationError
from ..loader import PhysicalSchema
from ..models import Limits
from ..policy import ModelPolicy

# §8 Q4 — COUNT DISTINCT is exp.Count(distinct); operators are nodes, always allowed
DEFAULT_ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {"SUM", "COUNT", "AVG", "MIN", "MAX", "DATE_TRUNC", "EXTRACT", "COALESCE", "CAST", "LOWER", "UPPER"}
)

# Structural expressions modelled as functions by sqlglot; they carry no caller-callable behaviour.
_STRUCTURAL_FUNCTIONS: tuple[type[exp.Expression], ...] = (exp.Case, exp.Exists)

# Dialect spellings that sqlglot parses into distinct truncation nodes for the same allowlisted function.
_FUNCTION_ALIASES: dict[str, str] = {
    "TIMESTAMP_TRUNC": "DATE_TRUNC",
    "DATETIME_TRUNC": "DATE_TRUNC",
    "TIMESTAMPTRUNC": "DATE_TRUNC",
    "TIME_TRUNC": "DATE_TRUNC",
}

_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Command,
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Into,
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Use,
    exp.Pragma,
)


def effective_allowed_functions(policy: ModelPolicy, extra: frozenset[str] | None) -> frozenset[str]:
    """DEFAULT ∪ (extra or ∅) ∪ policy.allowed_functions — additive only (§8 Q4).

    Args:
        policy: Model policy contributing per-model extensions.
        extra: Toolkit-level additive extensions.

    Returns:
        The upper-cased effective allowlist.
    """
    return (
        DEFAULT_ALLOWED_FUNCTIONS
        | frozenset(f.upper() for f in (extra or frozenset()))
        | frozenset(f.upper() for f in policy.allowed_functions)
    )


def _function_name(node: exp.Func) -> str:
    """Return the canonical upper-case name of a function node."""
    name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
    name = name.upper()
    return _FUNCTION_ALIASES.get(name, name)


def _table_name(table: exp.Table) -> str:
    """Return the schema-map name of a table reference."""
    return ".".join(part for part in (table.catalog, table.db, table.name) if part)


class PositiveGuard:
    """Positive allowlist over a qualified, governed query AST."""

    def __init__(self, schema: PhysicalSchema, allowed_functions: frozenset[str], limits: Limits) -> None:
        """Create a guard.

        Args:
            schema: Model-owned physical schema map.
            allowed_functions: Effective upper-case function allowlist.
            limits: Policy row limits (default injected, max clamped).
        """
        self.schema = schema
        self.allowed_functions = frozenset(f.upper() for f in allowed_functions)
        self.limits = limits

    def check_and_limit(self, tree: exp.Expression, *, trusted_nodes: set[int] | None = None) -> exp.Expression:
        """Exactly one exp.Select root (CTEs allowed); every table/column in schema; functions allowlisted;
        no exp.Command/DDL/DML; inject (policy default) or clamp (policy max) LIMIT.

        Args:
            tree: Qualified query AST (mutated in place for the LIMIT).
            trusted_nodes: Identities of pipeline-injected nodes (RLS/masking); only these may
                use functions outside the allowlist. Caller-supplied nodes are never trusted.

        Returns:
            The same tree with an enforced LIMIT.

        Raises:
            SemanticValidationError: codes "not_select", "unknown_table", "unknown_column",
                "function_not_allowed", "command_forbidden", "invalid_limit".
        """
        trusted = trusted_nodes or set()
        for node in tree.walk():
            if isinstance(node, _FORBIDDEN_NODES):
                raise SemanticValidationError("command_forbidden", "Only read-only SELECT statements are allowed")
        if not isinstance(tree, exp.Select):
            # Covers UNION/INTERSECT roots and multi-statement exp.Block trees.
            raise SemanticValidationError("not_select", "The statement root must be a single SELECT")
        self._check_functions(tree, trusted)
        self._check_sources(tree)
        self._apply_limit(tree)
        return tree

    def _check_functions(self, tree: exp.Expression, trusted: set[int]) -> None:
        """Reject every non-allowlisted function that the pipeline did not inject."""
        for node in tree.find_all(exp.Func):
            if isinstance(node, _STRUCTURAL_FUNCTIONS) or id(node) in trusted:
                continue
            if isinstance(node, exp.If) and isinstance(node.parent, exp.Case):
                # WHEN branches of a CASE expression, not a caller-invoked IF() function.
                continue
            if _function_name(node) not in self.allowed_functions:
                raise SemanticValidationError(
                    "function_not_allowed",
                    "The query uses a function outside the allowlist",
                    details={"function": _function_name(node)},
                )

    def _check_sources(self, tree: exp.Select) -> None:
        """Require known physical tables and columns in every scope."""
        root = build_scope(tree)
        if root is None:
            raise SemanticValidationError("not_select", "The query has no resolvable scope")
        for scope in root.traverse():
            for table in scope.tables:
                if not isinstance(table.this, exp.Identifier):
                    raise SemanticValidationError("unknown_table", "Table sources must be plain tables")
                if table.name in scope.cte_sources and not table.db and not table.catalog:
                    continue
                if _table_name(table) not in self.schema.tables:
                    raise SemanticValidationError("unknown_table", "The query references an unknown table")
            if isinstance(scope.expression, exp.Select):
                for projection in scope.expression.expressions:
                    if isinstance(projection, exp.Star) or (
                        isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star)
                    ):
                        raise SemanticValidationError("unknown_column", "Star projections must be expanded")
            aliases = {
                select.alias for select in getattr(scope.expression, "selects", []) if isinstance(select, exp.Alias)
            }
            for column in scope.columns:
                if isinstance(column.this, exp.Star):
                    raise SemanticValidationError("unknown_column", "Star projections must be expanded")
                if not column.table:
                    if column.name in aliases:
                        continue
                    raise SemanticValidationError("unknown_column", "The query references an unqualified column")
                selected = scope.selected_sources.get(column.table)
                if selected is None:
                    raise SemanticValidationError("unknown_column", "A column references an unknown source")
                _, source = selected
                if isinstance(source, exp.Table):
                    columns = self.schema.tables.get(_table_name(source))
                    if columns is None or column.name not in columns:
                        raise SemanticValidationError("unknown_column", "The query references an unknown column")
                elif not any(select.alias_or_name == column.name for select in source.expression.selects):
                    raise SemanticValidationError("unknown_column", "A derived column is not projected by its source")

    def _apply_limit(self, tree: exp.Select) -> None:
        """Inject the policy default LIMIT or clamp an existing one to the policy max."""
        limit = tree.args.get("limit")
        requested = self.limits.default
        if limit is not None:
            value = limit.expression if isinstance(limit, exp.Limit) else limit
            if not isinstance(value, exp.Literal) or value.is_string:
                raise SemanticValidationError("invalid_limit", "LIMIT must be an integer literal")
            try:
                requested = int(value.this)
            except ValueError as exc:
                raise SemanticValidationError("invalid_limit", "LIMIT must be an integer literal") from exc
            if requested < 0:
                raise SemanticValidationError("invalid_limit", "LIMIT must not be negative")
        tree.limit(min(requested, self.limits.max), copy=False)
