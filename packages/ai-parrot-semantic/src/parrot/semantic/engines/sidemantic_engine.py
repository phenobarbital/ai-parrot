"""Sidemantic compile adapter: synchronous, CPU-only, and database-free."""

from __future__ import annotations

from functools import reduce
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp

from ..errors import SemanticValidationError
from ..models import CompiledQuery, FilterGroup, FilterLeaf, ModelMember, SemanticQuery

if TYPE_CHECKING:
    from ..loader import LoadedModel


def filter_tree_to_sidemantic(filters: FilterGroup | None, members: dict[str, ModelMember]) -> list[str]:
    """Translate a typed filter tree into sidemantic SQL filter expressions."""
    if filters is None:
        return []

    def render(item: FilterLeaf | FilterGroup) -> exp.Expression:
        if isinstance(item, FilterGroup):
            if not item.items:
                raise SemanticValidationError("unsupported_filter")
            expressions = [render(child) for child in item.items]
            combinator = exp.and_ if item.op == "and" else exp.or_
            return reduce(combinator, expressions)

        if item.member not in members:
            raise SemanticValidationError("unknown_member", details={"member": item.member})
        column = _member_column(item.member)
        values = [_literal(value) for value in item.values]
        if item.op == "equals" and len(values) == 1:
            return exp.EQ(this=column, expression=values[0])
        if item.op == "not_equals" and len(values) == 1:
            return exp.NEQ(this=column, expression=values[0])
        if item.op == "in" and values:
            return exp.In(this=column, expressions=values)
        if item.op == "not_in" and values:
            return exp.Not(this=exp.In(this=column, expressions=values))
        if item.op == "contains" and len(item.values) == 1:
            return exp.Like(this=column, expression=exp.Literal.string(f"%{item.values[0]}%"))
        if item.op == "gt" and len(values) == 1:
            return exp.GT(this=column, expression=values[0])
        if item.op == "gte" and len(values) == 1:
            return exp.GTE(this=column, expression=values[0])
        if item.op == "lt" and len(values) == 1:
            return exp.LT(this=column, expression=values[0])
        if item.op == "lte" and len(values) == 1:
            return exp.LTE(this=column, expression=values[0])
        if item.op in {"between", "in_date_range"} and len(values) == 2:
            return exp.Between(this=column, low=values[0], high=values[1])
        if item.op == "is_set" and not values:
            return exp.Not(this=exp.Is(this=column, expression=exp.Null()))
        if item.op == "not_set" and not values:
            return exp.Is(this=column, expression=exp.Null())
        if item.op == "before_date" and len(values) == 1:
            return exp.LT(this=column, expression=values[0])
        if item.op == "after_date" and len(values) == 1:
            return exp.GT(this=column, expression=values[0])
        raise SemanticValidationError("unsupported_filter", details={"op": item.op})

    return [render(filters).sql()]


def compile_sidemantic(query: SemanticQuery, model: "LoadedModel", dialect: str) -> CompiledQuery:
    """Compile through sidemantic without passing user attributes or opening a connection."""
    member_kinds = {member.name: member.kind for member in model.members}
    time_dimensions = {member.name for member in model.members if member.kind == "time_dimension"}
    query.validate_against(member_kinds, time_dimensions)
    owners = _member_owners(model)
    metrics = [_qualified(member, owners, model.name) for member in query.metrics]
    dimensions = [_qualified(member, owners, model.name) for member in query.dimensions]
    dimensions.extend(
        (
            f"{_qualified(item.name, owners, model.name)}__{item.grain}"
            if item.grain
            else _qualified(item.name, owners, model.name)
        )
        for item in query.time_dimensions
    )
    order_by = [
        f"{_qualified(item.member, owners, model.name)}{'__' + item.grain if item.grain else ''} {'desc' if item.desc else 'asc'}"
        for item in query.order_by
    ]
    filters = filter_tree_to_sidemantic(query.filters, {member.name: member for member in model.members})
    sql = model.layer.compile(
        metrics=metrics or None,
        dimensions=dimensions or None,
        filters=filters or None,
        order_by=order_by or None,
        limit=query.limit,
        offset=query.offset or None,
        dialect=dialect,
        timezone=query.timezone,
        saved_query=query.saved_query,
    )
    tree = sqlglot.parse_one(sql, read=dialect)
    physical_tables = set(model.schema.tables)
    tables = sorted(
        {
            qualified
            for table in tree.find_all(exp.Table)
            if (qualified := ".".join(part for part in (table.catalog, table.db, table.name) if part))
            in physical_tables
        }
    )
    referenced = [*query.metrics, *query.dimensions]
    referenced.extend(item.name for item in query.time_dimensions)
    referenced.extend(item.member for item in query.order_by)
    if query.filters is not None:
        referenced.extend(_filter_members(query.filters))
    return CompiledQuery(
        sql=sql,
        dialect=dialect,
        engine="sidemantic",
        members=tuple(dict.fromkeys(referenced)),
        tables=tuple(tables),
        cache_key="",
    )


def _literal(value: str | int | float | bool) -> exp.Expression:
    """Render a typed sqlglot literal without interpolating raw SQL."""
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, (int, float)):
        return exp.Literal.number(str(value))
    return exp.Literal.string(value)


def _member_column(member: str) -> exp.Column:
    """Construct a safe semantic-member column reference."""
    model_name, separator, name = member.rpartition(".")
    return exp.column(name, table=model_name) if separator else exp.column(member)


def _member_owners(model: "LoadedModel") -> dict[str, str]:
    """Map member names to their declaring sidemantic model, preferring the root."""
    owners: dict[str, str] = {}
    ordered = sorted(model.layer.graph.models.values(), key=lambda item: item.name != model.name)
    for graph_model in ordered:
        for member in [*graph_model.dimensions, *graph_model.metrics]:
            owners.setdefault(member.name, graph_model.name)
    for name, metric in model.layer.graph.metrics.items():
        owner = model.layer.graph.metric_owners.get(name)
        if owner:
            owners.setdefault(metric.name, owner)
    return owners


def _qualified(member: str, owners: dict[str, str], default_model: str) -> str:
    """Qualify a semantic member for sidemantic's compile API."""
    if "." in member:
        return member
    return f"{owners.get(member, default_model)}.{member}"


def _filter_members(group: FilterGroup) -> list[str]:
    """Collect filter members recursively in source order."""
    members: list[str] = []
    for item in group.items:
        if isinstance(item, FilterLeaf):
            members.append(item.member)
        else:
            members.extend(_filter_members(item))
    return members
