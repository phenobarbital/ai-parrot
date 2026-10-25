"""RLS push-down: filtered base scans below aggregation, typed literals, fail closed."""

from __future__ import annotations

import logging
import re

import sqlglot
from sqlglot import exp

from parrot.auth import PermissionContext, RlsPredicate, RlsRegistry

from ..errors import SemanticAccessError
from ..loader import PhysicalSchema

_NUMERIC_LITERAL = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_NUMERIC_TYPES = frozenset(
    {
    "BIGINT",
    "BIGNUMERIC",
    "DECIMAL",
    "DOUBLE",
    "FLOAT",
    "FLOAT64",
    "INT",
    "INT2",
    "INT4",
    "INT8",
    "INT64",
    "INTEGER",
    "MEDIUMINT",
    "NUMERIC",
    "REAL",
    "SMALLINT",
    "TINYINT",
    }
)


class RlsPushdown:
    """Apply registry RLS rules to qualified physical table scans."""

    def __init__(self, registry: RlsRegistry) -> None:
        """Create an unbound RLS pass over a shared read-only registry.

        Args:
            registry: Registry used to look up and render row-level rules.
        """
        self.registry = registry
        self.logger = logging.getLogger(__name__)
        self._schema: PhysicalSchema | None = None

    def apply(
        self,
        tree: exp.Expression,
        ctx: PermissionContext,
        driver: str,
    ) -> tuple[exp.Expression, tuple[str, ...], set[int]]:
        """Wrap every RLS-governed base scan as a filtered subquery below aggregation.

        Args:
            tree: Qualified query AST. The caller-owned tree is never mutated.
            ctx: Trusted request-local permission context.
            driver: Canonical physical driver used by the registry.

        Returns:
            The rewritten tree, applied rule descriptions without values, and
            identities of nodes injected by this pass.

        Raises:
            SemanticAccessError: If schema binding is absent, rule rendering
                fails, or a source cannot be rewritten deterministically.
        """
        schema = self._schema
        if schema is None:
            raise SemanticAccessError("rls_unplaceable", "RLS requires a request-local physical schema")

        rewritten = tree.copy()
        self._reject_unplaceable(rewritten)
        physical_tables = [
            (table, self._table_name(table))
            for table in rewritten.find_all(exp.Table)
            if self._table_name(table) in schema.tables
        ]
        table_names = {table_name for _, table_name in physical_tables}
        rules = sorted(
            self.registry.lookup(driver, table_names),
            key=lambda rule: (rule.table, rule.description, rule.predicate_template),
        )
        applied: list[str] = []
        applied_seen: set[tuple[str, str, str]] = set()
        trusted_nodes: set[int] = set()
        for table, table_name in physical_tables:
            table_rules = [rule for rule in rules if rule.table == table_name]
            if not table_rules:
                continue

            conditions: list[exp.Expression] = []
            for rule in table_rules:
                try:
                    predicate = self.registry.render(rule, ctx)
                    if predicate.table != table_name:
                        raise ValueError("Rendered RLS predicate changed its physical table")
                    conditions.append(self._predicate_expr(predicate, schema, table_name))
                except Exception as exc:
                    self.logger.warning("RLS rule rendering failed for table %s", table_name)
                    raise SemanticAccessError("rls_render_failed", "Unable to render a row-level rule") from exc
                key = (rule.table, rule.description, rule.predicate_template)
                if key not in applied_seen:
                    applied_seen.add(key)
                    applied.append(rule.description)

            condition = conditions[0]
            for additional in conditions[1:]:
                condition = exp.and_(condition, additional)

            alias = table.alias_or_name or table.name
            inner_table = table.copy()
            inner_table.set("alias", None)
            wrapper = exp.select("*").from_(inner_table).where(condition).subquery(alias)
            table.replace(wrapper)
            trusted_nodes.update(id(node) for node in wrapper.walk())

        return rewritten, tuple(applied), trusted_nodes

    def _predicate_expr(self, pred: RlsPredicate, schema: PhysicalSchema, table: str) -> exp.Expression:
        """Parse a predicate and replace placeholders with typed literals.

        Args:
            pred: Rendered predicate whose values remain separately bound.
            schema: Qualified request-local physical schema.
            table: Physical table governed by the predicate.

        Returns:
            A sqlglot condition containing no unresolved placeholders.

        Raises:
            ValueError: If the predicate, bindings, or referenced columns are invalid.
        """
        if table not in schema.tables:
            raise ValueError("RLS predicate table is absent from the physical schema")
        parsed = sqlglot.parse(pred.sql_predicate)
        if len(parsed) != 1 or parsed[0] is None:
            raise ValueError("RLS predicate must contain exactly one condition")
        condition = parsed[0]
        if not isinstance(condition, (exp.Predicate, exp.And, exp.Or, exp.Not, exp.Boolean)):
            raise ValueError("RLS predicate must be a boolean condition")

        columns = list(condition.find_all(exp.Column))
        if any(column.name not in schema.tables[table] for column in columns):
            raise ValueError("RLS predicate references a column outside its physical table")
        if condition.find(exp.Select) is not None or condition.find(exp.Table) is not None:
            raise ValueError("RLS predicate cannot contain a query source")

        placeholders = list(condition.find_all(exp.Placeholder))
        placeholder_names = {str(placeholder.this) for placeholder in placeholders}
        if placeholder_names != set(pred.bound_params):
            raise ValueError("RLS predicate placeholders do not match its bound parameters")

        for placeholder in placeholders:
            name = str(placeholder.this)
            column = self._placeholder_column(placeholder)
            if column.name not in schema.tables[table]:
                raise ValueError("RLS binding has no schema-qualified column type")
            values = pred.bound_params[name]
            if not values:
                raise ValueError("RLS binding cannot be empty")
            literals = [self._typed_literal(value, schema.tables[table][column.name]) for value in values]
            replacement: exp.Expression
            if len(literals) == 1:
                replacement = literals[0]
            else:
                replacement = exp.Tuple(expressions=literals)
            placeholder.replace(replacement)

        return condition

    def _for_schema(self, schema: PhysicalSchema) -> RlsPushdown:
        """Return a fresh pass sharing only the registry and bound to one schema.

        Args:
            schema: Qualified schema for one governance request.

        Returns:
            A new request-local pass. Neither this instance nor the schema is mutated.
        """
        bound = RlsPushdown(self.registry)
        bound._schema = schema
        return bound

    @staticmethod
    def _table_name(table: exp.Table) -> str:
        """Return a fully qualified identifier table name, or an empty marker."""
        if not isinstance(table.this, exp.Identifier):
            return ""
        return ".".join(part for part in (table.catalog, table.db, table.name) if part)

    @staticmethod
    def _reject_unplaceable(tree: exp.Expression) -> None:
        """Reject source forms for which base-scan placement is ambiguous."""
        if any(with_clause.args.get("recursive") for with_clause in tree.find_all(exp.With)):
            raise SemanticAccessError("rls_unplaceable", "Recursive CTEs cannot be governed by RLS push-down")
        if tree.find(exp.Lateral) is not None or tree.find(exp.Unnest) is not None:
            raise SemanticAccessError("rls_unplaceable", "Lateral and UNNEST sources cannot be governed")
        if tree.find(exp.Values) is not None:
            raise SemanticAccessError("rls_unplaceable", "VALUES sources cannot be governed")
        if any(not isinstance(table.this, exp.Identifier) for table in tree.find_all(exp.Table)):
            raise SemanticAccessError("rls_unplaceable", "Table-valued functions cannot be governed")

    @staticmethod
    def _placeholder_column(placeholder: exp.Placeholder) -> exp.Column:
        """Resolve the physical column that supplies a placeholder's type."""
        parent = placeholder.parent
        if isinstance(parent, exp.In) and isinstance(parent.this, exp.Column):
            return parent.this
        if isinstance(parent, (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)):
            other = parent.expression if parent.this is placeholder else parent.this
            if isinstance(other, exp.Column):
                return other
        if isinstance(parent, exp.Between) and isinstance(parent.this, exp.Column):
            return parent.this
        raise ValueError("RLS placeholder is not bound to a supported column predicate")

    @staticmethod
    def _typed_literal(value: str, column_type: str) -> exp.Literal:
        """Build an injection-safe literal using the declared physical type."""
        normalized_type = column_type.strip().upper()
        type_name = re.split(r"[\s(]", normalized_type, maxsplit=1)[0]
        if type_name in _NUMERIC_TYPES:
            if not _NUMERIC_LITERAL.fullmatch(value.strip()):
                raise ValueError("RLS numeric binding is not a valid number")
            return exp.Literal.number(value.strip())
        return exp.Literal.string(value)
