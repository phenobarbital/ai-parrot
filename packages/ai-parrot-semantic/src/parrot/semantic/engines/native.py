"""Sole native SQL AST compiler; no warehouse connection or engine dispatch."""

from __future__ import annotations

import ast
import json
from collections import deque
from dataclasses import dataclass

from sqlglot import exp

from ..errors import SemanticValidationError
from ..loader import LoadedModel
from ..model import Metric, Relationship, SemanticModel
from ..models import CompiledQuery, FilterGroup, FilterLeaf, Grain, SemanticQuery

NATIVE_AGGREGATIONS = ("sum", "count", "count_distinct", "avg", "min", "max")


_FILTER_DIALECTS = frozenset({"duckdb", "postgres"})
_AGGREGATE_TYPES: dict[str, type[exp.AggFunc]] = {
    "sum": exp.Sum,
    "count": exp.Count,
    "avg": exp.Avg,
    "min": exp.Min,
    "max": exp.Max,
}


@dataclass(frozen=True)
class _Plan:
    """Join plan for one compilation: base model, ordered joins and per-model qualifiers."""

    base: str
    joins: tuple[tuple[str, str, Relationship], ...]
    qualifiers: dict[str, str]
    aliased: bool

    @property
    def models(self) -> tuple[str, ...]:
        """Return the planned models in deterministic base-first order."""
        return (self.base, *(child for _, child, _ in self.joins))


class NativeCompiler:
    """Compile the closed semantic grammar to deterministic dialect SQL.

    Instances hold only the immutable loaded model; every compilation builds its own plan.
    """

    def __init__(self, model: LoadedModel) -> None:
        """Configure compilation for one immutable loaded model."""
        self.model = model
        self._graph: dict[str, SemanticModel] = {model.name: model.model, **model.related_models}

    # ------------------------------------------------------------------ public

    def dependencies(self, metric: str) -> tuple[str, ...]:
        """Return qualified metric names the metric depends on, dependencies first.

        Args:
            metric: A bare root-model or ``model.metric`` qualified metric name.

        Returns:
            Deterministic post-order of qualified names ending with the metric itself.
        """
        model_name, local = self._split(metric)
        order: list[str] = []
        self._walk_dependencies(model_name, local, order, set())
        return tuple(order)

    def compile(self, query: SemanticQuery, dialect: str) -> CompiledQuery:
        """Build SELECT with typed filters, physical provenance and deterministic keys."""
        if query.model != self.model.name:
            raise SemanticValidationError("unknown_model", "Query does not match the loaded semantic model")
        if query.saved_query is not None:
            raise SemanticValidationError("unsupported_query", "Saved queries must be expanded before compilation")
        if query.timezone is not None:
            raise SemanticValidationError(
                "unsupported_query", "Timezone conversion is not supported by the native compiler"
            )

        member_kinds, time_dimensions = self._member_universe()
        query.validate_against(member_kinds, time_dimensions)

        selected_names = [*query.metrics, *query.dimensions, *(item.name for item in query.time_dimensions)]
        if len(selected_names) != len(set(selected_names)):
            raise SemanticValidationError("duplicate_member", "A semantic member may be selected only once")

        plan = self._plan(query)
        projections: list[exp.Expression] = []
        groups: list[exp.Expression] = []
        expressions: dict[str, exp.Expression] = {}

        for name in query.metrics:
            expression = self._member_expr(name, plan, dialect)
            expressions[name] = expression
            projections.append(self._alias(expression, name))
        for name in query.dimensions:
            expression = self._member_expr(name, plan, dialect)
            expressions[name] = expression
            projections.append(self._alias(expression, name))
            groups.append(expression)
        for time_dimension in query.time_dimensions:
            column = self._member_expr(time_dimension.name, plan, dialect)
            expression = self._grain_expr(column, time_dimension.grain)
            key = self._time_key(time_dimension.name, time_dimension.grain)
            expressions[key] = expression
            projections.append(self._alias(expression, key))
            groups.append(expression)

        select = exp.select(*projections).from_(self._table_expr(plan.base, plan))
        for _parent, child, relationship in plan.joins:
            select = select.join(
                self._table_expr(child, plan),
                on=self._join_condition(relationship, plan),
                join_type=relationship.join_type,
            )
        if query.metrics and groups:
            select.set("group", exp.Group(expressions=groups))
        elif not query.metrics:
            select.set("distinct", exp.Distinct())

        if query.filters is not None:
            predicate = self._filter_group(query.filters, plan, dialect)
            if self._group_is_metric(query.filters):
                select.set("having", exp.Having(this=predicate))
            else:
                select.set("where", exp.Where(this=predicate))

        if query.order_by:
            ordered: list[exp.Ordered] = []
            for order in query.order_by:
                if order.member in time_dimensions:
                    expression = self._grain_expr(self._member_expr(order.member, plan, dialect), order.grain)
                else:
                    expression = expressions.get(order.member)
                    if expression is None:
                        expression = self._member_expr(order.member, plan, dialect)
                ordered.append(exp.Ordered(this=expression, desc=order.desc))
            select.set("order", exp.Order(expressions=ordered))

        limit = min(
            query.limit if query.limit is not None else self.model.policy.limits.default, self.model.policy.limits.max
        )
        select.set("limit", exp.Limit(expression=exp.Literal.number(limit)))
        if query.offset:
            select.set("offset", exp.Offset(expression=exp.Literal.number(query.offset)))

        return CompiledQuery(
            sql=select.sql(dialect=dialect),
            dialect=dialect,
            members=tuple(selected_names),
            tables=tuple(self._graph[name].table for name in plan.models),
            cache_key=self._cache_key(query, dialect),
        )

    # ------------------------------------------------------------- resolution

    def _split(self, name: str) -> tuple[str, str]:
        """Split a member name into (model, local member); bare names belong to the root model."""
        if "." in name:
            model_name, local = name.split(".", 1)
            if model_name in self._graph:
                return model_name, local
            raise SemanticValidationError("unknown_member", "Query references an unknown model qualifier")
        return self.model.name, name

    def _member_universe(self) -> tuple[dict[str, str], set[str]]:
        """Return member kinds and time-dimension names, bare for the root and qualified for all models."""
        kinds: dict[str, str] = {member.name: member.kind for member in self.model.members}
        times: set[str] = {member.name for member in self.model.members if member.kind == "time_dimension"}
        for model_name in sorted(self._graph):
            graph_model = self._graph[model_name]
            for metric in graph_model.metrics:
                kinds[f"{model_name}.{metric.name}"] = "metric"
            for dimension in graph_model.dimensions:
                qualified = f"{model_name}.{dimension.name}"
                kinds[qualified] = "time_dimension" if dimension.kind == "time" else "dimension"
                if dimension.kind == "time":
                    times.add(qualified)
        return kinds, times

    def _metric_of(self, model_name: str, local: str) -> Metric:
        """Return a declared metric or fail closed."""
        for metric in self._graph[model_name].metrics:
            if metric.name == local:
                return metric
        raise SemanticValidationError("unknown_member", "Query references an unknown metric")

    def _is_metric(self, name: str) -> bool:
        """Return whether a member name denotes a metric."""
        model_name, local = self._split(name)
        return any(metric.name == local for metric in self._graph[model_name].metrics)

    def _walk_dependencies(self, model_name: str, local: str, order: list[str], visiting: set[str]) -> None:
        """Post-order walk of derived metric references in sorted (deterministic) order."""
        qualified = f"{model_name}.{local}"
        if qualified in order:
            return
        if qualified in visiting:
            raise SemanticValidationError("derived_metric_cycle", "Derived metric dependencies contain a cycle")
        metric = self._metric_of(model_name, local)
        visiting.add(qualified)
        if metric.sql is not None:
            for reference in sorted(self._references(metric.sql)):
                ref_model, ref_local = reference.split(".", 1)
                if ref_model not in self._graph:
                    raise SemanticValidationError("unknown_metric", "Derived metric references an unknown metric")
                self._walk_dependencies(ref_model, ref_local, order, visiting)
        visiting.discard(qualified)
        order.append(qualified)

    @staticmethod
    def _references(expression: str) -> set[str]:
        """Return qualified metric references of a closed arithmetic expression."""
        references: set[str] = set()
        for node in ast.walk(ast.parse(expression, mode="eval")):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                references.add(f"{node.value.id}.{node.attr}")
        return references

    def _aggregate_models(self, name: str) -> set[str]:
        """Return the models whose physical rows feed the aggregates behind a metric member."""
        models: set[str] = set()
        for qualified in self.dependencies(name):
            model_name, local = qualified.split(".", 1)
            if self._metric_of(model_name, local).sql is None:
                models.add(model_name)
        return models

    # --------------------------------------------------------------- planning

    def _referenced_members(self, query: SemanticQuery) -> list[str]:
        """Return every member the query touches, in a deterministic order."""
        names = [*query.metrics, *query.dimensions, *(item.name for item in query.time_dimensions)]
        names.extend(order.member for order in query.order_by)
        names.extend(sorted(SemanticQuery._filter_members(query.filters)))
        return names

    def _plan(self, query: SemanticQuery) -> _Plan:
        """Plan joins at measure grain: only many-to-one hops from the measure model are allowed."""
        measure_models: set[str] = set()
        dimension_models: set[str] = set()
        for name in self._referenced_members(query):
            if self._is_metric(name):
                measure_models.update(self._aggregate_models(name))
            else:
                dimension_models.add(self._split(name)[0])
        if len(measure_models) > 1:
            raise SemanticValidationError(
                "join_fanout",
                "Aggregates from different model grains would fan out",
                details={"models": sorted(measure_models)},
            )
        base = next(iter(measure_models)) if measure_models else self.model.name
        targets = sorted(dimension_models - {base})

        adjacency = self._adjacency()
        parents = self._bfs(base, adjacency)
        joins: list[tuple[str, str, Relationship]] = []
        planned = {base}
        for target in targets:
            if target not in parents:
                raise SemanticValidationError("unresolved_join", "No declared relationship path to a model")
            path: list[str] = []
            node = target
            while node != base:
                path.append(node)
                node = parents[node]
            for child in reversed(path):
                parent = parents[child]
                if child in planned:
                    continue
                relationship = adjacency[parent][child]
                if measure_models and not (relationship.to_model == parent and relationship.from_model == child):
                    raise SemanticValidationError(
                        "join_fanout",
                        "Join would fan out the aggregate grain",
                        details={"from": parent, "to": child},
                    )
                joins.append((parent, child, relationship))
                planned.add(child)
        aliased = bool(joins)
        qualifiers = {
            name: (name if aliased else self._graph[name].table.rsplit(".", 1)[-1]) for name in sorted(planned)
        }
        return _Plan(base=base, joins=tuple(joins), qualifiers=qualifiers, aliased=aliased)

    def _adjacency(self) -> dict[str, dict[str, Relationship]]:
        """Return the undirected relationship graph, rejecting parallel or cyclic paths."""
        adjacency: dict[str, dict[str, Relationship]] = {name: {} for name in sorted(self._graph)}
        seen: dict[tuple[str, str], Relationship] = {}
        for owner in sorted(self._graph):
            for relationship in self._graph[owner].relationships:
                if relationship.from_model not in self._graph or relationship.to_model not in self._graph:
                    continue
                edge = (relationship.from_model, relationship.to_model)
                key = tuple(sorted(edge))
                if key in seen and seen[key] != relationship:
                    raise SemanticValidationError("ambiguous_join_path", "Models have more than one join path")
                seen[key] = relationship
                adjacency[relationship.from_model][relationship.to_model] = relationship
                adjacency[relationship.to_model][relationship.from_model] = relationship
        if len(seen) >= len(self._graph) and self._has_cycle(adjacency):
            raise SemanticValidationError("ambiguous_join_path", "The relationship graph has an ambiguous path")
        return adjacency

    @staticmethod
    def _has_cycle(adjacency: dict[str, dict[str, Relationship]]) -> bool:
        """Detect a cycle in the undirected relationship graph."""
        visited: set[str] = set()
        for start in sorted(adjacency):
            if start in visited:
                continue
            stack: list[tuple[str, str | None]] = [(start, None)]
            while stack:
                node, parent = stack.pop()
                if node in visited:
                    return True
                visited.add(node)
                stack.extend((n, node) for n in sorted(adjacency[node]) if n != parent)
        return False

    @staticmethod
    def _bfs(base: str, adjacency: dict[str, dict[str, Relationship]]) -> dict[str, str]:
        """Return deterministic parent pointers of the BFS tree from the base model."""
        parents: dict[str, str] = {}
        seen = {base}
        queue: deque[str] = deque([base])
        while queue:
            node = queue.popleft()
            for neighbor in sorted(adjacency[node]):
                if neighbor not in seen:
                    seen.add(neighbor)
                    parents[neighbor] = node
                    queue.append(neighbor)
        return parents

    def _table_expr(self, model_name: str, plan: _Plan) -> exp.Expression:
        """Return the (aliased when joined) physical table of a model."""
        table = exp.to_table(self._graph[model_name].table)
        if plan.aliased:
            return exp.alias_(table, plan.qualifiers[model_name], table=True)
        return table

    def _join_condition(self, relationship: Relationship, plan: _Plan) -> exp.Expression:
        """Return the composite-key equality for a declared relationship."""
        condition: exp.Expression | None = None
        for from_column, to_column in zip(relationship.from_columns, relationship.to_columns, strict=True):
            equality = exp.EQ(
                this=exp.column(from_column, table=plan.qualifiers[relationship.from_model]),
                expression=exp.column(to_column, table=plan.qualifiers[relationship.to_model]),
            )
            condition = equality if condition is None else exp.and_(condition, equality)
        assert condition is not None
        return condition

    @staticmethod
    def _alias(expression: exp.Expression, name: str) -> exp.Expression:
        """Alias a projection; qualified member names are quoted."""
        return exp.alias_(expression, name, quoted="." in name)

    # -------------------------------------------------------------- lowering

    def _column(self, model_name: str, column: str, plan: _Plan) -> exp.Column:
        """Return a physical column qualified for its planned model."""
        if model_name not in plan.qualifiers:
            raise SemanticValidationError("unresolved_join", "Member belongs to a model outside the join plan")
        return exp.column(column, table=plan.qualifiers[model_name])

    def _dimension_expr(self, name: str, plan: _Plan) -> exp.Column:
        """Resolve a declared dimension to its physical column."""
        model_name, local = self._split(name)
        for dimension in self._graph[model_name].dimensions:
            if dimension.name == local:
                return self._column(model_name, dimension.column, plan)
        raise SemanticValidationError("unknown_member", "Query references an unknown dimension")

    def _member_expr(self, name: str, plan: _Plan, dialect: str) -> exp.Expression:
        """Resolve a metric or dimension member to an AST expression."""
        if self._is_metric(name):
            model_name, local = self._split(name)
            return self._metric_expr(model_name, local, plan, dialect, frozenset())
        return self._dimension_expr(name, plan)

    def _metric_expr(
        self, model_name: str, local: str, plan: _Plan, dialect: str, visiting: frozenset[str]
    ) -> exp.Expression:
        """Lower an aggregate (optionally filtered) or derived metric."""
        metric = self._metric_of(model_name, local)
        qualified = f"{model_name}.{local}"
        if qualified in visiting:
            raise SemanticValidationError("derived_metric_cycle", "Derived metric dependencies contain a cycle")
        if metric.sql is not None:
            return self._derived_expr(metric.sql, plan, dialect, visiting | {qualified})
        if metric.agg not in NATIVE_AGGREGATIONS:
            raise SemanticValidationError("unsupported_metric", "Metric aggregation is not supported")
        column: exp.Expression = exp.Star() if metric.column is None else self._column(model_name, metric.column, plan)
        predicate = None
        if metric.filter is not None:
            predicate = self._filter_group(metric.filter, plan, dialect, owner=model_name)
        if predicate is not None and dialect not in _FILTER_DIALECTS:
            argument: exp.Expression = exp.Literal.number(1) if isinstance(column, exp.Star) else column
            column = exp.Case(ifs=[exp.If(this=predicate, true=argument)])
            predicate = None
        if metric.agg == "count_distinct":
            aggregate: exp.Expression = exp.Count(this=exp.Distinct(expressions=[column]))
        else:
            aggregate = _AGGREGATE_TYPES[metric.agg](this=column)
        if predicate is not None:
            return exp.Filter(this=aggregate, expression=exp.Where(this=predicate))
        return aggregate

    def _derived_expr(self, expression: str, plan: _Plan, dialect: str, visiting: frozenset[str]) -> exp.Expression:
        """Lower the closed arithmetic grammar; division returns NULL for a zero denominator."""

        def lower(node: ast.AST) -> exp.Expression:
            if isinstance(node, ast.Expression):
                return lower(node.body)
            if isinstance(node, ast.BinOp):
                left, right = self._paren(lower(node.left)), self._paren(lower(node.right))
                if isinstance(node.op, ast.Add):
                    return exp.Add(this=left, expression=right)
                if isinstance(node.op, ast.Sub):
                    return exp.Sub(this=left, expression=right)
                if isinstance(node.op, ast.Mult):
                    return exp.Mul(this=left, expression=right)
                if isinstance(node.op, ast.Div):
                    zero = exp.EQ(this=right.copy(), expression=exp.Literal.number(0))
                    return exp.Case(
                        ifs=[exp.If(this=zero, true=exp.Null())], default=exp.Div(this=left, expression=right)
                    )
            if isinstance(node, ast.UnaryOp):
                operand = self._paren(lower(node.operand))
                return exp.Neg(this=operand) if isinstance(node.op, ast.USub) else operand
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return exp.Literal.number(node.value)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id not in self._graph:
                    raise SemanticValidationError("unknown_metric", "Derived metric references an unknown metric")
                return self._metric_expr(node.value.id, node.attr, plan, dialect, visiting)
            raise SemanticValidationError("unsupported_metric", "Derived metric expression is not supported")

        return lower(ast.parse(expression, mode="eval"))

    @staticmethod
    def _paren(expression: exp.Expression) -> exp.Expression:
        """Wrap compound arithmetic so SQL precedence matches the declared expression."""
        if isinstance(expression, (exp.Binary, exp.Case, exp.Neg)):
            return exp.Paren(this=expression)
        return expression

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

    @staticmethod
    def _time_key(name: str, grain: Grain) -> str:
        """Return a stable result alias for a grained time dimension."""
        return f"{name}_{grain}"

    def _filter_group(self, group: FilterGroup, plan: _Plan, dialect: str, owner: str | None = None) -> exp.Expression:
        """Recursively lower a homogeneous typed filter group to an AST predicate."""
        items = [
            (
                self._filter_leaf(item, plan, dialect, owner)
                if isinstance(item, FilterLeaf)
                else self._filter_group(item, plan, dialect, owner)
            )
            for item in group.items
        ]
        predicate = items[0]
        for item in items[1:]:
            predicate = exp.and_(predicate, item) if group.op == "and" else exp.or_(predicate, item)
        return predicate

    def _filter_leaf(self, leaf: FilterLeaf, plan: _Plan, dialect: str, owner: str | None) -> exp.Expression:
        """Lower one validated typed filter without embedding user SQL."""
        member = leaf.member if owner is None or "." in leaf.member else f"{owner}.{leaf.member}"
        column = self._member_expr(member, plan, dialect)
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
            return self._is_metric(first.member)
        return self._group_is_metric(first)

    def _grain_expr(self, column: exp.Column, grain: Grain) -> exp.Expression:
        """Return a DATE_TRUNC expression for the requested grain."""
        return exp.DateTrunc(this=column, unit=exp.Var(this=grain.upper()))
