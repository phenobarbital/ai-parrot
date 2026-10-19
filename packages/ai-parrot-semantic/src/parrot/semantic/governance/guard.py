"""Positive SQL guard: single SELECT, allowlisted tables/columns/functions, forced LIMIT."""

from __future__ import annotations

from sqlglot import exp

from ..errors import SemanticValidationError
from ..loader import PhysicalSchema
from ..models import Limits
from ..policy import ModelPolicy

# §8 Q4 — COUNT DISTINCT is exp.Count(distinct); operators are nodes, always allowed
DEFAULT_ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {"SUM", "COUNT", "AVG", "MIN", "MAX", "DATE_TRUNC", "EXTRACT", "COALESCE", "CAST", "LOWER", "UPPER"}
)


def effective_allowed_functions(policy: ModelPolicy, extra: frozenset[str] | None) -> frozenset[str]:
    """Return the additive default, toolkit, and policy function allowlists."""
    return (
        DEFAULT_ALLOWED_FUNCTIONS
        | {function.upper() for function in (extra or frozenset())}
        | {function.upper() for function in policy.allowed_functions}
    )


class PositiveGuard:
    """Validate a SQL AST against positive schema and function allowlists."""

    def __init__(self, schema: PhysicalSchema, allowed_functions: frozenset[str], limits: Limits) -> None:
        """Initialize the guard with the physical schema and policy limits."""
        self.schema = schema
        self.allowed_functions = {function.upper() for function in allowed_functions}
        self.limits = limits

    @staticmethod
    def _table_name(table: exp.Table) -> str:
        """Return a schema-qualified physical table name."""
        return ".".join(part for part in (table.catalog, table.db, table.name) if part)

    @staticmethod
    def _enclosing_select(expression: exp.Expression) -> exp.Select | None:
        """Return the nearest SELECT containing an expression."""
        parent = expression.parent
        while parent is not None and not isinstance(parent, exp.Select):
            parent = parent.parent
        return parent

    @staticmethod
    def _exported_columns(
        subquery: exp.Subquery, schema_tables: dict[str, dict[str, str]], trusted: set[int]
    ) -> set[str]:
        """Columns a derived table exports; a trusted ``SELECT * FROM <table>`` (RLS) exports that table's columns."""
        query = subquery.this
        if (
            id(query) in trusted
            and isinstance(query, exp.Select)
            and len(query.expressions) == 1
            and isinstance(query.expressions[0], exp.Star)
        ):
            source = query.args.get("from_") or query.args.get("from")
            table = source.this if source is not None else None
            if isinstance(table, exp.Table) and not query.args.get("joins"):
                name = ".".join(part for part in (table.catalog, table.db, table.name) if part).casefold()
                columns = schema_tables.get(name)
                if columns is not None:
                    return {column.casefold() for column in columns}
        return {name.casefold() for name in query.named_selects}

    def check_and_limit(
        self,
        tree: exp.Expression,
        *,
        requested_limit: int | None = None,
        trusted_nodes: set[int] | None = None,
    ) -> exp.Expression:
        """Validate a single SELECT and inject or clamp its LIMIT.

        Args:
            tree: Parsed SQL expression to validate in place.
            requested_limit: Optional caller-requested row limit.
            trusted_nodes: ``id()`` of nodes injected by RLS push-down / masking (trusted by identity, never by
                label). They are exempt from the star and function allowlists; tables are still checked.

        Returns:
            The validated expression with an enforced LIMIT.

        Raises:
            SemanticValidationError: If the statement, resource, column, or function is not allowed.
        """
        forbidden = (
            exp.Command,
            exp.Insert,
            exp.Update,
            exp.Delete,
            exp.Create,
            exp.Drop,
            exp.Alter,
            exp.Merge,
            exp.TruncateTable,
            exp.Copy,
        )
        if any(isinstance(node, forbidden) for node in tree.walk()):
            raise SemanticValidationError("command_forbidden")
        if not isinstance(tree, exp.Select):
            raise SemanticValidationError("not_select")

        trusted = trusted_nodes or set()
        cte_names = {cte.alias_or_name.casefold() for cte in tree.find_all(exp.CTE)}
        schema_tables = {name.casefold(): columns for name, columns in self.schema.tables.items()}
        scoped_sources: dict[int, dict[str, set[str]]] = {}

        for cte in tree.find_all(exp.CTE):
            owner = self._enclosing_select(cte)
            if owner is not None and isinstance(cte.this, exp.Query):
                scoped_sources.setdefault(id(owner), {})[cte.alias_or_name.casefold()] = {
                    name.casefold() for name in cte.this.named_selects
                }
        for subquery in tree.find_all(exp.Subquery):
            owner = self._enclosing_select(subquery)
            if owner is not None and subquery.alias_or_name and isinstance(subquery.this, exp.Query):
                scoped_sources.setdefault(id(owner), {})[subquery.alias_or_name.casefold()] = self._exported_columns(
                    subquery, schema_tables, trusted
                )

        for table in tree.find_all(exp.Table):
            if table.name.casefold() in cte_names and not table.db and not table.catalog:
                continue
            table_name = self._table_name(table).casefold()
            columns = schema_tables.get(table_name)
            if columns is None:
                raise SemanticValidationError("unknown_table", details={"table": self._table_name(table)})
            normalized_columns = {column.casefold() for column in columns}
            owner = self._enclosing_select(table)
            if owner is not None:
                sources = scoped_sources.setdefault(id(owner), {})
                sources[table.alias_or_name.casefold()] = normalized_columns

        for star in tree.find_all(exp.Star):
            if id(star) in trusted:
                continue
            if not isinstance(star.parent, exp.Count):
                raise SemanticValidationError("unknown_column", details={"column": "*"})

        for column in tree.find_all(exp.Column):
            if isinstance(column.this, exp.Star):
                if id(column) in trusted or id(column.this) in trusted:
                    continue
                raise SemanticValidationError("unknown_column", details={"column": column.sql()})
            column_name = column.name.casefold()
            owner = self._enclosing_select(column)
            sources = scoped_sources.get(id(owner), {}) if owner is not None else {}
            if column.table:
                columns = sources.get(column.table.casefold())
                outer = self._enclosing_select(owner) if owner is not None else None
                while columns is None and outer is not None:
                    columns = scoped_sources.get(id(outer), {}).get(column.table.casefold())
                    outer = self._enclosing_select(outer)
                if columns is None or column_name not in columns:
                    raise SemanticValidationError("unknown_column", details={"column": column.sql()})
            elif sum(column_name in columns for columns in sources.values()) != 1:
                raise SemanticValidationError("unknown_column", details={"column": column.sql()})

        for function in tree.find_all(exp.Func):
            if id(function) in trusted:
                continue
            function_name = function.name if isinstance(function, exp.Anonymous) else function.sql_name()
            if function_name.upper() not in self.allowed_functions:
                raise SemanticValidationError("function_not_allowed", details={"function": function_name.upper()})

        existing_limit = tree.args.get("limit")
        existing_value: int | None = None
        if existing_limit is not None and isinstance(existing_limit.expression, exp.Literal):
            try:
                existing_value = int(existing_limit.expression.this)
            except (TypeError, ValueError):
                existing_value = None
        limit = min(requested_limit or existing_value or self.limits.default, self.limits.max)
        return tree.limit(limit, copy=False)
