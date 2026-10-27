"""Frozen, clean-room semantic graph built from public format definitions."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .errors import SemanticPolicyError
from .models import FilterGroup, Grain

_ARITHMETIC_OPERATORS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
_TYPE_PARAMETERS = re.compile(r"\s*\([^)]*\)\s*$")
_TYPE_ALIASES = {
    "bigint": "integer",
    "int": "integer",
    "int2": "integer",
    "int4": "integer",
    "int8": "integer",
    "smallint": "integer",
    "decimal": "numeric",
    "double": "numeric",
    "double precision": "numeric",
    "float": "numeric",
    "float4": "numeric",
    "float8": "numeric",
    "real": "numeric",
    "char": "text",
    "character": "text",
    "character varying": "text",
    "string": "text",
    "varchar": "text",
    "bool": "boolean",
    "datetime": "timestamp",
    "timestamptz": "timestamp",
    "timestamp with time zone": "timestamp",
    "timestamp without time zone": "timestamp",
}


class _FrozenDict(dict[str, str]):
    """A serializable dictionary that rejects mutation after publication."""

    @staticmethod
    def _immutable(*args: object, **kwargs: object) -> None:
        """Reject an attempted mutation."""
        raise TypeError("semantic model columns are immutable")

    __delitem__ = _immutable
    __ior__ = _immutable
    __setitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


class Dimension(BaseModel, frozen=True):
    """Named physical dimension with optional time grain."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Literal["categorical", "numeric", "time"]
    column: str
    grain: Grain | None = None

    def model_post_init(self, __context: Any) -> None:
        """Validate the time-grain contract."""
        if self.kind == "time" and self.grain is None:
            _fail("invalid_dimension", "Time dimensions require a grain", dimension=self.name)
        if self.kind != "time" and self.grain is not None:
            _fail("invalid_dimension", "Only time dimensions may declare a grain", dimension=self.name)


class Metric(BaseModel, frozen=True):
    """An aggregate input or a closed derived-metric expression."""

    model_config = ConfigDict(extra="forbid")

    name: str
    agg: Literal["sum", "count", "count_distinct", "avg", "min", "max"] | None = None
    column: str | None = None
    sql: str | None = None
    filter: FilterGroup | None = None

    def model_post_init(self, __context: Any) -> None:
        """Enforce mutually exclusive aggregate and derived shapes."""
        if self.agg is None and self.sql is None:
            _fail("invalid_metric", "A metric requires either agg or sql", metric=self.name)
        if self.agg is not None and self.sql is not None:
            _fail("invalid_metric", "Aggregate metrics cannot declare sql", metric=self.name)
        if self.sql is not None and (self.column is not None or self.filter is not None):
            _fail("invalid_metric", "Derived metrics cannot declare column or filter", metric=self.name)
        if self.agg in {"sum", "count_distinct", "avg", "min", "max"} and self.column is None:
            _fail("invalid_metric", f"{self.agg} requires a physical column", metric=self.name)
        if self.filter is not None:
            object.__setattr__(self, "filter", copy.deepcopy(self.filter))


class Relationship(BaseModel, frozen=True):
    """Declared paired keys from one-side primary key to many-side foreign key."""

    model_config = ConfigDict(extra="forbid")

    from_model: str
    to_model: str
    cardinality: Literal["one_to_many"]
    from_columns: tuple[str, ...]
    to_columns: tuple[str, ...]
    join_type: Literal["inner", "left"] = "left"

    def model_post_init(self, __context: Any) -> None:
        """Reject malformed local key pairs before graph resolution."""
        if not self.from_columns or not self.to_columns:
            _fail("invalid_relationship", "Relationship key tuples cannot be empty")
        if len(self.from_columns) != len(self.to_columns):
            _fail("invalid_relationship", "Relationship key tuples must be equally sized")
        if self.from_model == self.to_model:
            _fail("invalid_relationship", "Self-joins are not supported", model=self.from_model)


class SemanticModel(BaseModel, frozen=True):
    """Physical schema and semantic members, with a canonical digest."""

    model_config = ConfigDict(extra="forbid")

    name: str
    table: str
    columns: dict[str, str]
    primary_key: tuple[str, ...]
    dimensions: tuple[Dimension, ...]
    metrics: tuple[Metric, ...]
    relationships: tuple[Relationship, ...]

    def model_post_init(self, __context: Any) -> None:
        """Publish an immutable snapshot of the physical schema."""
        object.__setattr__(self, "columns", _FrozenDict(copy.deepcopy(self.columns)))

    def digest(self) -> str:
        """Return canonical JSON SHA-256 without mutating nested definitions."""
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


def validate_model_graph(models: dict[str, SemanticModel]) -> None:
    """Reject unresolved references, cycles, incompatible keys and ambiguous joins.

    Args:
        models: Models keyed by their declared names.

    Raises:
        SemanticPolicyError: If any physical, metric, or relationship contract is invalid.
    """
    snapshot = dict(models)
    for key in sorted(snapshot):
        model = snapshot[key]
        if key != model.name:
            _fail("model_name_mismatch", "Model map key must match the declared name", key=key, model=model.name)
        _validate_model_members(model)

    adjacency: dict[str, set[str]] = {name: set() for name in snapshot}
    edges: set[tuple[str, str]] = set()
    for owner_name in sorted(snapshot):
        for relationship in snapshot[owner_name].relationships:
            _validate_relationship(relationship, snapshot)
            edge = tuple(sorted((relationship.from_model, relationship.to_model)))
            if edge in edges:
                _fail(
                    "ambiguous_join_path",
                    "Models cannot have more than one declared join path",
                    models=list(edge),
                )
            edges.add(edge)
            adjacency[relationship.from_model].add(relationship.to_model)
            adjacency[relationship.to_model].add(relationship.from_model)

    _validate_unambiguous_paths(adjacency)
    _validate_derived_metrics(snapshot, adjacency)


def _validate_model_members(model: SemanticModel) -> None:
    """Validate one model's physical columns and local semantic members."""
    if not model.columns or any(not column or not physical_type for column, physical_type in model.columns.items()):
        _fail("invalid_physical_schema", "Physical columns and types must be non-empty", model=model.name)
    if not model.primary_key:
        _fail("invalid_primary_key", "A model primary key cannot be empty", model=model.name)
    _require_columns(model, model.primary_key, "primary key")

    dimension_names: set[str] = set()
    for dimension in model.dimensions:
        if dimension.name in dimension_names:
            _fail("duplicate_member", "Dimension names must be unique", model=model.name, member=dimension.name)
        dimension_names.add(dimension.name)
        _require_columns(model, (dimension.column,), f"dimension {dimension.name}")

    metric_names: set[str] = set()
    for metric in model.metrics:
        if metric.name in metric_names or metric.name in dimension_names:
            _fail("duplicate_member", "Semantic member names must be unique", model=model.name, member=metric.name)
        metric_names.add(metric.name)
        if metric.column is not None:
            _require_columns(model, (metric.column,), f"metric {metric.name}")
        if metric.filter is not None:
            for member in sorted(_filter_members(metric.filter)):
                local_member = member.split(".", 1)[-1]
                qualifier = member.split(".", 1)[0] if "." in member else model.name
                if qualifier != model.name or local_member not in dimension_names:
                    _fail(
                        "invalid_metric_filter",
                        "Aggregate metric filters may reference dimensions only",
                        model=model.name,
                        metric=metric.name,
                        member=member,
                    )


def _require_columns(model: SemanticModel, columns: tuple[str, ...], purpose: str) -> None:
    """Require physical columns to exist on a model."""
    missing = sorted(column for column in columns if column not in model.columns)
    if missing:
        _fail(
            "unknown_column",
            f"Unknown physical column in {purpose}",
            model=model.name,
            columns=missing,
        )


def _filter_members(group: FilterGroup) -> set[str]:
    """Collect filter leaves without depending on their concrete leaf class."""
    members: set[str] = set()
    for item in group.items:
        if isinstance(item, FilterGroup):
            members.update(_filter_members(item))
        else:
            members.add(item.member)
    return members


def _validate_relationship(relationship: Relationship, models: dict[str, SemanticModel]) -> None:
    """Resolve and validate a one-to-many relationship's paired physical keys."""
    unknown = sorted({relationship.from_model, relationship.to_model}.difference(models))
    if unknown:
        _fail("unknown_model", "Relationship references an unknown model", models=unknown)
    one = models[relationship.from_model]
    many = models[relationship.to_model]
    if relationship.from_columns != one.primary_key:
        _fail(
            "invalid_relationship_key",
            "One-to-many from_columns must equal the one-side primary key",
            model=one.name,
        )
    _require_columns(one, relationship.from_columns, "relationship key")
    _require_columns(many, relationship.to_columns, "relationship key")
    for from_column, to_column in zip(relationship.from_columns, relationship.to_columns, strict=True):
        from_type = _canonical_type(one.columns[from_column])
        to_type = _canonical_type(many.columns[to_column])
        if from_type != to_type:
            _fail(
                "incompatible_join_key",
                "Relationship key columns have incompatible physical types",
                from_column=f"{one.name}.{from_column}",
                to_column=f"{many.name}.{to_column}",
            )


def _canonical_type(physical_type: str) -> str:
    """Normalize common SQL type aliases for structural join compatibility."""
    normalized = " ".join(_TYPE_PARAMETERS.sub("", physical_type.strip().lower()).split())
    return _TYPE_ALIASES.get(normalized, normalized)


def _validate_unambiguous_paths(adjacency: dict[str, set[str]]) -> None:
    """Reject cycles, which create more than one path between model pairs."""
    visited: set[str] = set()

    def visit(node: str, parent: str | None) -> None:
        visited.add(node)
        for neighbor in sorted(adjacency[node]):
            if neighbor == parent:
                continue
            if neighbor in visited:
                _fail("ambiguous_join_path", "The relationship graph contains an ambiguous join path")
            visit(neighbor, node)

    for model_name in sorted(adjacency):
        if model_name not in visited:
            visit(model_name, None)


def _validate_derived_metrics(models: dict[str, SemanticModel], adjacency: dict[str, set[str]]) -> None:
    """Validate derived expressions and walk their dependencies deterministically."""
    nodes = {f"{model.name}.{metric.name}": metric for model in models.values() for metric in model.metrics}
    dependencies: dict[str, tuple[str, ...]] = {}
    for qualified_name in sorted(nodes):
        metric = nodes[qualified_name]
        if metric.sql is None:
            dependencies[qualified_name] = ()
            continue
        references = _derived_references(metric.sql, qualified_name)
        unknown = sorted(references.difference(nodes))
        if unknown:
            _fail(
                "unknown_metric",
                "Derived metric references an unknown metric",
                metric=qualified_name,
                references=unknown,
            )
        source_model = qualified_name.split(".", 1)[0]
        for reference in sorted(references):
            target_model = reference.split(".", 1)[0]
            if source_model != target_model and not _has_path(source_model, target_model, adjacency):
                _fail(
                    "unresolved_metric",
                    "Cross-model derived metric requires a declared relationship path",
                    metric=qualified_name,
                    reference=reference,
                )
        dependencies[qualified_name] = tuple(sorted(references))

    state: dict[str, Literal["visiting", "visited"]] = {}

    def visit(metric_name: str) -> None:
        if state.get(metric_name) == "visiting":
            _fail("derived_metric_cycle", "Derived metric dependencies contain a cycle", metric=metric_name)
        if state.get(metric_name) == "visited":
            return
        state[metric_name] = "visiting"
        for dependency in dependencies[metric_name]:
            visit(dependency)
        state[metric_name] = "visited"

    for metric_name in sorted(dependencies):
        visit(metric_name)


def _derived_references(expression: str, metric_name: str) -> set[str]:
    """Parse the closed arithmetic grammar and return qualified metric references."""
    try:
        root = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        _fail("invalid_derived_expression", "Derived metric SQL is not valid arithmetic", metric=metric_name)
        raise AssertionError from exc

    references: set[str] = set()

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            walk(node.body)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, _ARITHMETIC_OPERATORS):
            walk(node.left)
            walk(node.right)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            walk(node.operand)
        elif (
            isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
        ):
            return
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            references.add(f"{node.value.id}.{node.attr}")
        else:
            _fail(
                "invalid_derived_expression",
                "Derived metrics permit qualified metric references, numbers, parentheses and arithmetic only",
                metric=metric_name,
            )

    walk(root)
    return references


def _has_path(source: str, target: str, adjacency: dict[str, set[str]]) -> bool:
    """Return whether two models are connected by declared relationships."""
    pending = [source]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(sorted(adjacency[current].difference(visited), reverse=True))
    return False


def _fail(code: str, message: str, **details: Any) -> None:
    """Raise a structured semantic model policy error."""
    raise SemanticPolicyError(code, message, details=details)
