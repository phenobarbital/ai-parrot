"""Native fallback compiler: v1 subset straight to a sqlglot AST (spec §3 Module 5)."""

from __future__ import annotations

import logging
from functools import reduce
from typing import Any

from sqlglot import exp

from ..errors import SemanticValidationError
from ..loader import LoadedModel
from ..models import CompiledQuery, Grain, SemanticQuery

NATIVE_AGGREGATIONS = ("sum", "count", "count_distinct", "avg", "min", "max")


class NativeCompiler:
    """Compile a SemanticQuery against one LoadedModel without sidemantic's compiler."""

    def __init__(self, model: LoadedModel) -> None:
        """Initialize the compiler with a loaded semantic model."""
        self.model = model
        self.logger = logging.getLogger(__name__)

    def compile(self, query: SemanticQuery, dialect: str) -> CompiledQuery:
        """Build a subset sqlglot select statement.

        Raises:
            SemanticValidationError: If a query uses unsupported metrics, filters, or
                a relationship that can fan out an aggregate.
        """
        member_kinds = {member.name: member.kind for member in self.model.members}
        time_dimensions = {member.name for member in self.model.members if member.kind == "time_dimension"}
        query.validate_against(member_kinds, time_dimensions)

        owners = self._member_owners()
        requested_members = [*query.metrics, *query.dimensions]
        requested_members.extend(item.name for item in query.time_dimensions)
        requested_members.extend(item.member for item in query.order_by)
        if query.filters is not None:
            requested_members.extend(self._filter_members(query.filters))
        joins = self._joins_for({owners.get(member, self.model.name) for member in requested_members})

        dimensions: dict[str, exp.Expression] = {
            name: self._dimension_expr(name, owners) for name in query.dimensions
        }
        for time_dimension in query.time_dimensions:
            dimensions[time_dimension.name] = self._grain_expr(
                self._dimension_expr(time_dimension.name, owners), time_dimension.grain
            )

        metrics = {name: self._metric_expr(name, owners) for name in query.metrics}
        projections = [exp.alias_(expression, name, quoted=False) for name, expression in dimensions.items()]
        projections.extend(exp.alias_(expression, name, quoted=False) for name, expression in metrics.items())
        if not projections:
            raise SemanticValidationError("unsupported_query")

        root_model = self.model.layer.graph.models[self.model.name]
        statement = exp.select(*projections).from_(self._table_expr(root_model.table, self.model.name))
        for hop in joins:
            target = self.model.layer.graph.models[hop.to_model]
            on = reduce(
                exp.and_,
                [
                    exp.EQ(
                        this=exp.column(from_column, table=hop.from_model),
                        expression=exp.column(to_column, table=hop.to_model),
                    )
                    for from_column, to_column in zip(hop.from_columns, hop.to_columns, strict=True)
                ],
            )
            statement = statement.join(self._table_expr(target.table, hop.to_model), on=on, join_type="LEFT")

        if query.filters is not None:
            predicate = self._filter_expr(query.filters, owners, dimensions, metrics)
            if self._filter_is_metric(query.filters, member_kinds):
                statement = statement.having(predicate)
            else:
                statement = statement.where(predicate)
        if dimensions:
            statement = statement.group_by(*dimensions.values())
        for order in query.order_by:
            expression = dimensions.get(order.member) or metrics.get(order.member)
            if expression is None:
                expression = self._dimension_expr(order.member, owners)
            statement = statement.order_by(exp.Ordered(this=expression, desc=order.desc))
        if query.limit is not None:
            statement = statement.limit(query.limit)
        if query.offset:
            statement = statement.offset(query.offset)

        return CompiledQuery(
            sql=statement.sql(dialect=dialect),
            dialect=dialect,
            engine="native",
            members=tuple(dict.fromkeys(requested_members)),
            tables=tuple(sorted({self.model.layer.graph.models[name].table for name in {self.model.name, *[hop.to_model for hop in joins]}})),
            cache_key="",
        )

    def _grain_expr(self, column: exp.Column, grain: Grain) -> exp.Expression:
        """Return a sqlglot ``DATE_TRUNC`` expression for ``grain``."""
        return exp.DateTrunc(this=column, unit=exp.Var(this=grain.upper()))

    def _member_owners(self) -> dict[str, str]:
        """Map semantic members to their declaring sidemantic model."""
        owners: dict[str, str] = {}
        for graph_model in self.model.layer.graph.models.values():
            for member in [*graph_model.dimensions, *graph_model.metrics]:
                owners.setdefault(member.name, graph_model.name)
        return owners

    @staticmethod
    def _table_expr(table: str, alias: str) -> exp.Table:
        """Return a qualified physical table with its semantic-model alias."""
        expression = exp.to_table(table)
        expression.set("alias", exp.TableAlias(this=exp.to_identifier(alias)))
        return expression

    def _joins_for(self, target_models: set[str]) -> list[Any]:
        """Return join hops from the root to requested models, rejecting fan-out paths."""
        joins: dict[tuple[str, str], Any] = {}
        for target in sorted(target_models - {self.model.name}):
            try:
                path = self.model.layer.graph.find_relationship_path(self.model.name, target)
            except (KeyError, ValueError) as error:
                raise SemanticValidationError("unsupported_join") from error
            for hop in path:
                if hop.relationship not in {"many_to_one", "one_to_one"}:
                    raise SemanticValidationError("fan_out")
                joins[(hop.from_model, hop.to_model)] = hop
        return list(joins.values())

    def _dimension_expr(self, member: str, owners: dict[str, str]) -> exp.Column:
        """Return one declared dimension as a qualified physical column."""
        owner = owners.get(member, self.model.name)
        dimension = next(
            (item for item in self.model.layer.graph.models[owner].dimensions if item.name == member), None
        )
        if dimension is None:
            raise SemanticValidationError("unsupported_dimension", details={"member": member})
        expression = dimension.sql or dimension.name
        if not expression.isidentifier():
            raise SemanticValidationError("unsupported_dimension", details={"member": member})
        return exp.column(expression, table=owner)

    def _metric_expr(self, member: str, owners: dict[str, str]) -> exp.Expression:
        """Return one supported aggregation over a declared physical metric expression."""
        owner = owners.get(member, self.model.name)
        metric = next((item for item in self.model.layer.graph.models[owner].metrics if item.name == member), None)
        if metric is None or metric.agg not in NATIVE_AGGREGATIONS or metric.type is not None:
            raise SemanticValidationError("unsupported_metric", details={"member": member})
        if metric.sql == "*":
            argument: exp.Expression = exp.Star()
        elif metric.sql and metric.sql.isidentifier():
            argument = exp.column(metric.sql, table=owner)
        else:
            raise SemanticValidationError("unsupported_metric", details={"member": member})
        aggregations: dict[str, type[exp.AggFunc]] = {
            "sum": exp.Sum,
            "count": exp.Count,
            "avg": exp.Avg,
            "min": exp.Min,
            "max": exp.Max,
        }
        if metric.agg == "count_distinct":
            return exp.Count(this=exp.Distinct(expressions=[argument]))
        return aggregations[metric.agg](this=argument)

    def _filter_expr(
        self,
        item: Any,
        owners: dict[str, str],
        dimensions: dict[str, exp.Expression],
        metrics: dict[str, exp.Expression],
    ) -> exp.Expression:
        """Build the declared filter-tree subset with typed SQL literals."""
        if hasattr(item, "items"):
            expressions = [self._filter_expr(child, owners, dimensions, metrics) for child in item.items]
            if not expressions:
                raise SemanticValidationError("unsupported_filter")
            return reduce(exp.and_ if item.op == "and" else exp.or_, expressions)
        column = metrics.get(item.member) or dimensions.get(item.member) or self._dimension_expr(item.member, owners)
        values = [self._literal(value) for value in item.values]
        if item.op == "equals" and len(values) == 1:
            return exp.EQ(this=column, expression=values[0])
        if item.op == "not_equals" and len(values) == 1:
            return exp.NEQ(this=column, expression=values[0])
        if item.op == "in" and values:
            return exp.In(this=column, expressions=values)
        if item.op == "not_in" and values:
            return exp.Not(this=exp.In(this=column, expressions=values))
        if item.op == "contains" and len(values) == 1:
            return exp.Like(this=column, expression=exp.Literal.string(f"%{item.values[0]}%"))
        if item.op in {"gt", "after_date"} and len(values) == 1:
            return exp.GT(this=column, expression=values[0])
        if item.op in {"gte"} and len(values) == 1:
            return exp.GTE(this=column, expression=values[0])
        if item.op in {"lt", "before_date"} and len(values) == 1:
            return exp.LT(this=column, expression=values[0])
        if item.op in {"lte"} and len(values) == 1:
            return exp.LTE(this=column, expression=values[0])
        if item.op in {"between", "in_date_range"} and len(values) == 2:
            return exp.Between(this=column, low=values[0], high=values[1])
        if item.op == "is_set" and not values:
            return exp.Not(this=exp.Is(this=column, expression=exp.Null()))
        if item.op == "not_set" and not values:
            return exp.Is(this=column, expression=exp.Null())
        raise SemanticValidationError("unsupported_filter", details={"op": item.op})

    @staticmethod
    def _filter_members(item: Any) -> list[str]:
        """Collect filter members recursively in source order."""
        if hasattr(item, "items"):
            return [member for child in item.items for member in NativeCompiler._filter_members(child)]
        return [item.member]

    @staticmethod
    def _filter_is_metric(item: Any, member_kinds: dict[str, str]) -> bool:
        """Return whether a validated filter group belongs in ``HAVING``."""
        return all(member_kinds[member] == "metric" for member in NativeCompiler._filter_members(item))

    @staticmethod
    def _literal(value: str | int | float | bool) -> exp.Expression:
        """Render a typed sqlglot literal without accepting raw SQL."""
        if isinstance(value, bool):
            return exp.Boolean(this=value)
        if isinstance(value, (int, float)):
            return exp.Literal.number(str(value))
        return exp.Literal.string(value)
