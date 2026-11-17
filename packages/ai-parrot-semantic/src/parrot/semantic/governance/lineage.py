"""Column-usage lineage: projection rights are distinct from usage rights."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, build_scope

from ..errors import SemanticAccessError
from ..loader import PhysicalSchema
from ..policy import ModelPolicy


class ColumnUse(BaseModel):
    """One physical column use and the SQL context that consumes it."""

    column: str
    table: str
    context: Literal["projection", "where", "having", "join", "group_by", "order_by", "window", "derived"]


def _local_columns(scope: Scope) -> list[exp.Column]:
    """Return columns owned by a scope, including output-alias references."""
    columns: list[exp.Column] = []
    for column in scope.expression.find_all(exp.Column):
        query = column.find_ancestor(exp.Select, exp.Union)
        if query is scope.expression:
            columns.append(column)
    return columns


def _physical_table(table: exp.Table, schema: PhysicalSchema) -> str:
    """Return and validate a schema-map table name."""
    name = ".".join(part for part in (table.catalog, table.db, table.name) if part)
    if name not in schema.tables:
        raise SemanticAccessError("unresolved_lineage", "A physical table is absent from the schema map")
    return name


def _projection(scope: Scope, name: str) -> exp.Expression:
    """Find exactly one named projection in a derived source."""
    matches = [selection for selection in scope.expression.selects if selection.alias_or_name == name]
    if len(matches) != 1:
        raise SemanticAccessError("unresolved_lineage", "A derived column cannot be resolved uniquely")
    selection = matches[0]
    return selection.this if isinstance(selection, exp.Alias) else selection


def _resolve_column(
    column: exp.Column,
    scope: Scope,
    schema: PhysicalSchema,
    active: set[tuple[int, int]],
) -> set[tuple[str, str]]:
    """Resolve one scoped column through table, CTE, and subquery sources."""
    marker = (id(column), id(scope))
    if marker in active:
        raise SemanticAccessError("unresolved_lineage", "Column lineage contains a cycle")
    active.add(marker)
    try:
        if not column.table:
            expression = _projection(scope, column.name)
            referenced = list(expression.find_all(exp.Column))
            if isinstance(expression, exp.Column):
                referenced.insert(0, expression)
            referenced = list(dict.fromkeys(referenced))
            if not referenced:
                raise SemanticAccessError("unresolved_lineage", "An output alias has no physical lineage")
            resolved: set[tuple[str, str]] = set()
            for reference in referenced:
                resolved.update(_resolve_column(reference, scope, schema, active))
            return resolved

        selected = scope.selected_sources.get(column.table)
        if selected is None:
            raise SemanticAccessError("unresolved_lineage", "A column source cannot be resolved")
        _, source = selected
        if isinstance(source, exp.Table):
            table = _physical_table(source, schema)
            if column.name not in schema.tables[table]:
                raise SemanticAccessError("unresolved_lineage", "A column is absent from the schema map")
            return {(table, column.name)}
        if isinstance(source, Scope):
            expression = _projection(source, column.name)
            references = list(expression.find_all(exp.Column))
            if isinstance(expression, exp.Column):
                references.insert(0, expression)
            references = list(dict.fromkeys(references))
            if not references:
                raise SemanticAccessError("unresolved_lineage", "A derived column has no physical lineage")
            resolved = set()
            for reference in references:
                resolved.update(_resolve_column(reference, source, schema, active))
            return resolved
        raise SemanticAccessError("unresolved_lineage", "An unsupported source has no safe column lineage")
    finally:
        active.remove(marker)


def _column_context(column: exp.Column, scope: Scope) -> str:
    """Classify a column by the nearest enclosing SQL clause."""
    ancestors: list[exp.Expression] = []
    current = column.parent
    while current is not None and current is not scope.expression:
        ancestors.append(current)
        current = current.parent

    if any(isinstance(node, exp.Window) for node in ancestors):
        return "window"
    clause_types: tuple[tuple[type[exp.Expression], str], ...] = (
        (exp.Where, "where"),
        (exp.Having, "having"),
        (exp.Join, "join"),
        (exp.Group, "group_by"),
        (exp.Order, "order_by"),
    )
    for node in ancestors:
        for clause_type, context in clause_types:
            if isinstance(node, clause_type):
                return context

    selection = next((node for node in ancestors if node.parent is scope.expression), None)
    if isinstance(selection, exp.Alias):
        selection = selection.this
    return "projection" if selection is column else "derived"


def resolve_column_uses(tree: exp.Expression, schema: PhysicalSchema) -> list[ColumnUse]:
    """Resolve aliases, CTEs, subqueries, and expressions to physical columns.

    Args:
        tree: A qualified sqlglot query AST.
        schema: Model-owned physical schema map.

    Returns:
        Deterministic, de-duplicated physical column uses.

    Raises:
        SemanticAccessError: If any column cannot be traced safely.
    """
    root = build_scope(tree)
    if root is None:
        raise SemanticAccessError("unresolved_lineage", "The query has no resolvable scope")

    uses: list[ColumnUse] = []
    seen: set[tuple[str, str, str]] = set()
    for scope in root.traverse():
        for column in _local_columns(scope):
            context = _column_context(column, scope)
            for table, name in sorted(_resolve_column(column, scope, schema, set())):
                key = (table, name, context)
                if key in seen:
                    continue
                seen.add(key)
                uses.append(ColumnUse(column=name, table=table, context=context))
    return uses


def enforce_usage_rights(
    uses: list[ColumnUse],
    policy: ModelPolicy,
    roles: frozenset[str],
    *,
    trusted_nodes: set[int],
) -> None:
    """Deny non-projection physical-column use without an explicit grant.

    ``trusted_nodes`` is intentionally not interpreted as caller-controlled
    column labels. The pipeline resolves usage before its own RLS and masking
    nodes are injected, and retains strong references to those nodes for later
    passes.

    Args:
        uses: Resolved physical column uses from the unmodified query.
        policy: Model governance policy.
        roles: Trusted roles from the permission context.
        trusted_nodes: Pipeline-owned AST identities; never column names.

    Raises:
        SemanticAccessError: If a non-projection use lacks permission.
    """
    del trusted_nodes
    for use in uses:
        qualified_column = f"{use.table}.{use.column}"
        if use.context != "projection" and not policy.usage_allowed(roles, qualified_column):
            raise SemanticAccessError(
                "usage_denied",
                "A physical column lacks non-projection usage rights",
                details={"column": qualified_column},
            )
