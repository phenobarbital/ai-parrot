"""Sole native SQL AST compiler; no warehouse connection or engine dispatch."""

from __future__ import annotations

import json

from sqlglot import exp

from ..errors import SemanticValidationError
from ..loader import LoadedModel
from ..models import CompiledQuery, FilterGroup, FilterLeaf, Grain, SemanticQuery

NATIVE_AGGREGATIONS = ("sum", "count", "count_distinct", "avg", "min", "max")


class NativeCompiler:
    """Compile the closed semantic grammar to deterministic dialect SQL."""

    def __init__(self, model: LoadedModel) -> None:
        """Configure compilation for one immutable loaded model."""
        self.model = model
        self._dimensions = {dimension.name: dimension for dimension in model.model.dimensions}
        self._metrics = {metric.name: metric for metric in model.model.metrics}

    def compile(self, query: SemanticQuery, dialect: str) -> CompiledQuery:
        """Build SELECT with typed filters, physical provenance and deterministic keys."""
        if query.model != self.model.name:
            raise SemanticValidationError("unknown_model", "Query does not match the loaded semantic model")
        if query.saved_query is not None:
            raise SemanticValidationError("unsupported_query", "Saved queries must be expanded before compilation")
        if query.timezone is not None:
            raise SemanticValidationError("unsupported_query", "Timezone conversion is not supported by the native compiler")

        member_kinds = {member.name: member.kind for member in self.model.members}
        time_dimensions = {member.name for member in self.model.members if member.kind == "time_dimension"}
        query.validate_against(member_kinds, time_dimensions)

        selected_names = [*query.metrics, *query.dimensions, *(item.name for item in query.time_dimensions)]
        if len(selected_names) != len(set(selected_names)):
            raise SemanticValidationError("duplicate_member", "A semantic member may be selected only once")

        table = exp.to_table(self.model.model.table)
        projections: list[exp.Expression] = []
        groups: list[exp.Expression] = []
        expressions: dict[str, exp.Expression] = {}

        for name in query.metrics:
            expression = self._metric_expr(name, table)
            expressions[name] = expression
            projections.append(exp.alias_(expression, name, quoted=False))
        for name in query.dimensions:
            expression = self._dimension_expr(name, table)
            expressions[name] = expression
            projections.append(exp.alias_(expression, name, quoted=False))
            groups.append(expression)
        for time_dimension in query.time_dimensions:
            column = self._dimension_expr(time_dimension.name, table)
            expression = self._grain_expr(column, time_dimension.grain)
            key = self._time_key(time_dimension.name, time_dimension.grain)
            expressions[key] = expression
            projections.append(exp.alias_(expression, key, quoted=False))
            groups.append(expression)

        select = exp.select(*projections).from_(table)
        if query.metrics and groups:
            select.set("group", exp.Group(expressions=groups))
        elif not query.metrics:
            select.set("distinct", exp.Distinct())

        if query.filters is not None:
            predicate = self._filter_group(query.filters, table)
            if self._group_is_metric(query.filters):
                select.set("having", exp.Having(this=predicate))
            else:
                select.set("where", exp.Where(this=predicate))

        if query.order_by:
            ordered: list[exp.Ordered] = []
            for order in query.order_by:
                if order.member in time_dimensions:
                    expression = self._grain_expr(self._dimension_expr(order.member, table), order.grain)
                else:
                    expression = expressions.get(order.member)
                    if expression is None:
                        expression = self._member_expr(order.member, table)
                ordered.append(exp.Ordered(this=expression, desc=order.desc))
            select.set("order", exp.Order(expressions=ordered))

        limit = min(query.limit if query.limit is not None else self.model.policy.limits.default, self.model.policy.limits.max)
        select.set("limit", exp.Limit(expression=exp.Literal.number(limit)))
        if query.offset:
            select.set("offset", exp.Offset(expression=exp.Literal.number(query.offset)))

        return CompiledQuery(
            sql=select.sql(dialect=dialect),
            dialect=dialect,
            members=tuple(selected_names),
            tables=(self.model.model.table,),
            cache_key=self._cache_key(query, dialect),
        )

    def _cache_key(self, query: SemanticQuery, dialect: str) -> str:
        """Return the cache key shared with the asynchronous compiler entry point."""
        return json.dumps(
            [
                self.model.model_digest,
                self.model.policy_digest,
                query.canonical_json(),
                dialect,
                self.model.compiler_version,
                self.model.policy.connection,
            ],
            separators=(",", ":"),
        )

    def _column(self, column: str, table: exp.Table) -> exp.Column:
        """Return a physical column qualified by the root model's table name."""
        return exp.column(column, table=table.name)

    def _dimension_expr(self, name: str, table: exp.Table) -> exp.Column:
        """Resolve a declared local dimension to its physical column."""
        dimension = self._dimensions.get(name)
        if dimension is None:
            raise SemanticValidationError("unknown_member", "Query references an unknown dimension")
        return self._column(dimension.column, table)

    def _metric_expr(self, name: str, table: exp.Table) -> exp.Expression:
        """Resolve one supported unfiltered aggregate metric."""
        metric = self._metrics.get(name)
        if metric is None:
            raise SemanticValidationError("unknown_member", "Query references an unknown metric")
        if metric.sql is not None:
            raise SemanticValidationError("unsupported_metric", "Derived metrics are not supported by this compiler")
        if metric.filter is not None:
            raise SemanticValidationError("unsupported_metric", "Filtered metrics are not supported by this compiler")
        if metric.agg not in NATIVE_AGGREGATIONS:
            raise SemanticValidationError("unsupported_metric", "Metric aggregation is not supported")
        column = exp.Star() if metric.column is None else self._column(metric.column, table)
        if metric.agg == "count_distinct":
            return exp.Count(this=column, distinct=True)
        aggregate_types: dict[str, type[exp.AggFunc]] = {
            "sum": exp.Sum,
            "count": exp.Count,
            "avg": exp.Avg,
            "min": exp.Min,
            "max": exp.Max,
        }
        return aggregate_types[metric.agg](this=column)

    def _member_expr(self, name: str, table: exp.Table) -> exp.Expression:
        """Resolve a member for ordering or filter construction."""
        if name in self._metrics:
            return self._metric_expr(name, table)
        return self._dimension_expr(name, table)

    @staticmethod
    def _time_key(name: str, grain: Grain) -> str:
        """Return a stable result alias for a grained time dimension."""
        return f"{name}_{grain}"

    def _filter_group(self, group: FilterGroup, table: exp.Table) -> exp.Expression:
        """Recursively lower a homogeneous typed filter group to an AST predicate."""
        items = [
            self._filter_leaf(item, table) if isinstance(item, FilterLeaf) else self._filter_group(item, table)
            for item in group.items
        ]
        predicate = items[0]
        for item in items[1:]:
            predicate = exp.and_(predicate, item) if group.op == "and" else exp.or_(predicate, item)
        return predicate

    def _filter_leaf(self, leaf: FilterLeaf, table: exp.Table) -> exp.Expression:
        """Lower one validated typed filter without embedding user SQL."""
        column = self._member_expr(leaf.member, table)
        values = [self._literal(value) for value in leaf.values]
        if leaf.op == "equals":
            return exp.EQ(this=column, expression=values[0])
        if leaf.op == "not_equals":
            return exp.NEQ(this=column, expression=values[0])
        if leaf.op == "in":
            return exp.In(this=column, expressions=values)
        if leaf.op == "not_in":
            return exp.Not(this=exp.In(this=column, expressions=values))
        if leaf.op == "contains":
            escaped = str(leaf.values[0]).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = exp.Like(this=column, expression=exp.Literal.string(f"%{escaped}%"))
            return exp.Escape(this=like, expression=exp.Literal.string("\\"))
        comparisons: dict[str, type[exp.Binary]] = {
            "gt": exp.GT,
            "gte": exp.GTE,
            "lt": exp.LT,
            "lte": exp.LTE,
            "before_date": exp.LT,
            "after_date": exp.GT,
        }
        if leaf.op in comparisons:
            return comparisons[leaf.op](this=column, expression=values[0])
        if leaf.op in {"between", "in_date_range"}:
            return exp.Between(this=column, low=values[0], high=values[1])
        if leaf.op == "is_set":
            return exp.Not(this=exp.Is(this=column, expression=exp.Null()))
        if leaf.op == "not_set":
            return exp.Is(this=column, expression=exp.Null())
        raise SemanticValidationError("unsupported_filter", "Filter operation is not supported")

    @staticmethod
    def _literal(value: str | int | float | bool) -> exp.Expression:
        """Convert a validated scalar into a typed SQL AST literal."""
        if isinstance(value, bool):
            return exp.Boolean(this=value)
        if isinstance(value, (int, float)):
            return exp.Literal.number(value)
        return exp.Literal.string(value)

    def _group_is_metric(self, group: FilterGroup) -> bool:
        """Return whether a validated group targets aggregate metrics."""
        first = group.items[0]
        if isinstance(first, FilterLeaf):
            return first.member in self._metrics
        return self._group_is_metric(first)

    def _grain_expr(self, column: exp.Column, grain: Grain) -> exp.Expression:
        """Return a DATE_TRUNC expression for the requested grain."""
        return exp.DateTrunc(this=column, unit=exp.Var(this=grain.upper()))
