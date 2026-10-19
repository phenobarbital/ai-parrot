"""RLS push-down: filtered base scans below aggregation, typed literals, fail closed."""
from __future__ import annotations

import logging

import sqlglot
from sqlglot import exp

from parrot.auth import PermissionContext, RlsRegistry
from parrot.auth.rls_registry import RlsPredicate

from ..errors import SemanticAccessError
from ..loader import PhysicalSchema


class RlsPushdown:
    """Rewrite governed physical-table scans with RLS filters below aggregation."""

    def __init__(self, registry: RlsRegistry) -> None:
        """Initialize the push-down pass with its RLS rule registry."""
        self.registry = registry
        self.logger = logging.getLogger(__name__)

    def apply(
        self,
        tree: exp.Expression,
        ctx: PermissionContext,
        driver: str,
        *,
        schema: PhysicalSchema,
    ) -> tuple[exp.Expression, tuple[str, ...], set[int]]:
        """Wrap governed base scans as filtered subqueries below aggregation.

        Returns:
            The rewritten tree, applied rule descriptions without subject values,
            and identities of trusted injected nodes.

        Raises:
            SemanticAccessError: If an RLS predicate cannot be rendered or placed
                deterministically.
        """
        if (
            any(tree.find_all(exp.Lateral))
            or any(tree.find_all(exp.Unnest))
            or any(with_clause.args.get("recursive") for with_clause in tree.find_all(exp.With))
        ):
            raise SemanticAccessError("rls_unplaceable")

        physical_tables: list[tuple[exp.Table, str]] = []
        for table_node in tree.find_all(exp.Table):
            if not isinstance(table_node.this, exp.Identifier):
                raise SemanticAccessError("rls_unplaceable")
            table_name = ".".join(part for part in (table_node.db, table_node.name) if part)
            if table_name in schema.tables:
                physical_tables.append((table_node, table_name))

        rules = self.registry.lookup(driver, {table_name for _, table_name in physical_tables})
        rules_by_table: dict[str, list[object]] = {}
        for rule in rules:
            rules_by_table.setdefault(rule.table, []).append(rule)

        descriptions: list[str] = []
        trusted_node_ids: set[int] = set()
        for table_node, table_name in physical_tables:
            table_rules = rules_by_table.get(table_name, [])
            if not table_rules:
                continue

            conditions: list[exp.Expression] = []
            for rule in table_rules:
                try:
                    predicate = self.registry.render(rule, ctx)
                except Exception as error:
                    raise SemanticAccessError("rls_render_failed") from error
                conditions.append(self._predicate_expr(predicate, schema, table_name))
                descriptions.append(rule.description)

            condition = exp.and_(*conditions)
            original_alias = table_node.alias_or_name
            base_table = table_node.copy()
            base_table.set("alias", None)
            replacement = exp.select("*").from_(base_table).where(condition).subquery(alias=original_alias)
            table_node.replace(replacement)
            trusted_node_ids.update(id(node) for node in replacement.walk())

        return tree, tuple(descriptions), trusted_node_ids

    def _predicate_expr(self, pred: RlsPredicate, schema: PhysicalSchema, table: str) -> exp.Expression:
        """Parse an RLS predicate and substitute placeholders with typed literals.

        Args:
            pred: Rendered predicate with bound values kept outside its SQL text.
            schema: Physical column types for the governed model.
            table: Schema-qualified physical table governed by ``pred``.

        Returns:
            A predicate expression containing only typed SQL literals.

        Raises:
            SemanticAccessError: If a predicate cannot be parsed or typed against
                the physical schema.
        """
        try:
            condition = sqlglot.parse_one(pred.sql_predicate)
        except Exception as error:
            raise SemanticAccessError("rls_unplaceable") from error

        for placeholder in list(condition.find_all(exp.Placeholder)):
            values = pred.bound_params.get(placeholder.name)
            if values is None:
                raise SemanticAccessError("rls_unplaceable")
            column = self._placeholder_column(placeholder)
            column_type = schema.tables.get(table, {}).get(column)
            if column_type is None:
                raise SemanticAccessError("rls_unplaceable")
            try:
                literals = [self._literal(value, column_type) for value in values]
            except ValueError as error:
                raise SemanticAccessError("rls_unplaceable") from error
            replacement: exp.Expression
            if len(literals) == 1:
                replacement = literals[0]
            else:
                replacement = exp.Tuple(expressions=literals)
            placeholder.replace(replacement)

        return condition

    @staticmethod
    def _placeholder_column(placeholder: exp.Placeholder) -> str:
        """Find the physical predicate column associated with a placeholder."""
        current = placeholder.parent
        while current is not None:
            columns = list(current.find_all(exp.Column))
            if columns:
                return columns[0].name
            current = current.parent
        raise SemanticAccessError("rls_unplaceable")

    @staticmethod
    def _literal(value: str, column_type: str) -> exp.Literal:
        """Create a typed SQL literal using the declared physical column type."""
        normalized_type = column_type.upper()
        if any(marker in normalized_type for marker in ("INT", "DECIMAL", "NUMERIC", "DOUBLE", "FLOAT", "REAL")):
            return exp.Literal.number(value)
        return exp.Literal.string(value)
