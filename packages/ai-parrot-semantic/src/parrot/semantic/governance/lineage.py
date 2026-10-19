"""Column-usage lineage: projection rights ≠ usage rights; unresolved lineage fails closed."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, build_scope

from ..errors import SemanticAccessError
from ..loader import PhysicalSchema
from ..policy import ModelPolicy

UsageContext = Literal["projection", "where", "having", "join", "group_by", "order_by", "window", "derived"]


class ColumnUse(BaseModel):
    """One physical column use and the SQL context that requires it."""

    column: str
    table: str
    context: UsageContext


def _selected_expression(scope: Scope, name: str) -> exp.Expression | None:
    """Return the expression exported from ``scope`` as ``name``."""
    expression = scope.expression
    if not isinstance(expression, exp.Query):
        return None
    for selection in expression.selects:
        if selection.alias_or_name == name:
            return selection.this if isinstance(selection, exp.Alias) else selection
    return None


def _column_context(column: exp.Column, scope: Scope) -> UsageContext:
    """Classify a column from its nearest enclosing SQL clause."""
    ancestors: list[exp.Expression] = []
    parent = column.parent
    while parent is not None and parent is not scope.expression:
        ancestors.append(parent)
        parent = parent.parent

    if any(isinstance(node, exp.Window) for node in ancestors):
        return "window"
    clauses: tuple[tuple[type[exp.Expression], UsageContext], ...] = (
        (exp.Where, "where"),
        (exp.Having, "having"),
        (exp.Join, "join"),
        (exp.Group, "group_by"),
        (exp.Order, "order_by"),
    )
    for ancestor in ancestors:
        for clause_type, context in clauses:
            if isinstance(ancestor, clause_type):
                return context

    selection = next(
        (
            candidate
            for candidate in getattr(scope.expression, "selects", ())
            if candidate is column or any(node is column for node in candidate.walk())
        ),
        None,
    )
    if selection is None:
        raise SemanticAccessError("unresolved_lineage")
    selected = selection.this if isinstance(selection, exp.Alias) else selection
    return "projection" if selected is column else "derived"


def _physical_table_name(table: exp.Table) -> str:
    """Return the schema-qualified physical table name used by PhysicalSchema."""
    return ".".join(part for part in (table.db, table.name) if part)


def _source_for(scope: Scope, source_name: str) -> exp.Table | Scope | None:
    """Find a local or correlated source, walking parent scopes when necessary."""
    current: Scope | None = scope
    while current is not None:
        source = current.sources.get(source_name)
        if source is not None:
            return source
        current = current.parent
    return None


def _resolve_column(
    column: exp.Column,
    scope: Scope,
    schema: PhysicalSchema,
    context: UsageContext,
    resolving: set[tuple[int, str]],
) -> list[ColumnUse]:
    """Resolve one qualified or exported column to physical schema columns."""
    source_name = column.table
    source = _source_for(scope, source_name) if source_name else None

    if isinstance(source, exp.Table):
        table_name = _physical_table_name(source)
        columns = schema.tables.get(table_name)
        if columns is None or column.name not in columns:
            raise SemanticAccessError("unresolved_lineage")
        return [ColumnUse(column=column.name, table=table_name, context=context)]

    if isinstance(source, Scope):
        key = (id(source), column.name)
        if key in resolving:
            raise SemanticAccessError("unresolved_lineage")
        selected = _selected_expression(source, column.name)
        if selected is None:
            raise SemanticAccessError("unresolved_lineage")
        nested_context = context
        if context == "projection" and not isinstance(selected, exp.Column):
            nested_context = "derived"
        nested_columns = list(selected.find_all(exp.Column))
        if isinstance(selected, exp.Column):
            nested_columns.insert(0, selected)
        if not nested_columns:
            raise SemanticAccessError("unresolved_lineage")
        resolving.add(key)
        try:
            uses: list[ColumnUse] = []
            seen_nodes: set[int] = set()
            for nested in nested_columns:
                if id(nested) in seen_nodes:
                    continue
                seen_nodes.add(id(nested))
                uses.extend(_resolve_column(nested, source, schema, nested_context, resolving))
            return uses
        finally:
            resolving.remove(key)

    if not source_name:
        selected = _selected_expression(scope, column.name)
        if selected is not None and selected is not column:
            nested_context = context
            if context == "projection" and not isinstance(selected, exp.Column):
                nested_context = "derived"
            nested_columns = list(selected.find_all(exp.Column))
            if isinstance(selected, exp.Column):
                nested_columns.insert(0, selected)
            uses: list[ColumnUse] = []
            seen_nodes: set[int] = set()
            for nested in nested_columns:
                if id(nested) in seen_nodes or nested is column:
                    continue
                seen_nodes.add(id(nested))
                uses.extend(_resolve_column(nested, scope, schema, nested_context, resolving))
            if uses:
                return uses

    raise SemanticAccessError("unresolved_lineage")


def resolve_column_uses(tree: exp.Expression, schema: PhysicalSchema) -> list[ColumnUse]:
    """Walk aliases, CTEs, subqueries, and expressions back to physical columns."""
    root = build_scope(tree)
    if root is None:
        raise SemanticAccessError("unresolved_lineage")

    uses: list[ColumnUse] = []
    seen: set[tuple[str, str, UsageContext]] = set()
    for scope in root.traverse():
        scope_columns = [node for node in scope.walk() if isinstance(node, exp.Column)]
        for column in scope_columns:
            context = _column_context(column, scope)
            for use in _resolve_column(column, scope, schema, context, set()):
                key = (use.table, use.column, use.context)
                if key not in seen:
                    seen.add(key)
                    uses.append(use)
    return uses


def enforce_usage_rights(
    uses: list[ColumnUse],
    policy: ModelPolicy,
    roles: frozenset[str],
    *,
    trusted_nodes: set[int],
    sensitive_members: frozenset[str] = frozenset(),
) -> None:
    """Deny non-projection uses of restricted columns without explicit usage rights.

    Usage rights apply only to *restricted* columns (spec AC6 "masked or hidden", FEAT-704 decision A,
    2026-10-19): a column governed by a mask, or one whose name is a member declared ``sensitive: true``.
    Unrestricted columns (e.g. a granted metric's aggregate input ``SUM(amount)``) need no usage grant;
    the positive guard still allowlists every table and column.

    Args:
        uses: Resolved physical-column uses.
        policy: Model policy holding masks and usage grants.
        roles: Roles active for the request.
        trusted_nodes: Unused; trusted AST nodes never become ``ColumnUse`` values.
        sensitive_members: Names of model members declared ``sensitive``.

    Raises:
        SemanticAccessError: ``usage_denied`` for a restricted column used without rights.
    """
    del trusted_nodes  # Trusted AST nodes are removed by the caller before they become ColumnUse values.
    for use in uses:
        if use.context == "projection":
            continue
        column = f"{use.table}.{use.column}"
        restricted = policy.mask_rule(column) is not None or policy.member_for(column) in sensitive_members
        if restricted and not policy.usage_allowed(roles, column):
            raise SemanticAccessError("usage_denied", details={"column": column})


def enforce_projection_rights(
    uses: list[ColumnUse],
    policy: ModelPolicy,
    roles: frozenset[str],
    members: list,
    *,
    include_derived: bool = False,
) -> None:
    """Deny returning a column whose backing member is not granted to ``roles`` (issue:4adcfffcd99a).

    A projected column passes when it backs a member in ``policy.allowed_members(roles, ...)`` or when it is
    rendered masked for these roles. ``include_derived`` (raw SQL) applies the same rule to derived uses, so
    wrapping a column in a function (``UPPER(tenant_id)``) cannot return it either; structured compiler output
    is already member-checked by the catalog and keeps derived metric inputs ungated.

    Raises:
        SemanticAccessError: ``member_not_granted`` with the offending physical column.
    """
    contexts = {"projection", "derived"} if include_derived else {"projection"}
    allowed = policy.allowed_members(roles, members)
    for use in uses:
        if use.context not in contexts:
            continue
        column = f"{use.table}.{use.column}"
        if policy.mask_for(roles, column) is not None:
            continue
        if policy.member_for(column) not in allowed:
            raise SemanticAccessError("member_not_granted", details={"column": column})
