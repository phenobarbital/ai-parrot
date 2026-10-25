"""Own-format and Ossie loader into the typed semantic graph."""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from .errors import SemanticPolicyError
from .model import Dimension, Metric, SemanticModel, validate_model_graph
from .models import ModelMember
from .ossie import is_ossie_document, validate_ossie_document
from .policy import ModelPolicy, load_policy
from .version import __version__

_AGGREGATE_EXPRESSION = re.compile(
    r"^(?P<aggregate>SUM|COUNT|COUNT_DISTINCT|AVG|MIN|MAX)\((?P<column>\*|[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*)\)$"
)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PhysicalSchema(BaseModel):
    """Qualified physical columns and types for AST qualification."""

    model_config = ConfigDict(frozen=True)

    driver: str
    tables: dict[str, dict[str, str]]

    def sqlglot_schema(self) -> dict[str, Any]:
        """Return the dialect-aware nested schema accepted by sqlglot.

        Table names are split only on qualification separators, preserving every
        catalog, schema, and table component supplied by the model author.
        """
        schema: dict[str, Any] = {}
        for qualified_table, columns in self.tables.items():
            parts = qualified_table.split(".")
            if not all(parts):
                raise SemanticPolicyError("invalid_table", "Physical table names cannot contain empty qualifiers")
            current = schema
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = dict(columns)
        return schema


class LoadedModel(BaseModel):
    """Model with resolved graph, policy and deterministic version digests."""

    model_config = ConfigDict(frozen=True)

    name: str
    model: SemanticModel
    related_models: dict[str, SemanticModel]
    policy: ModelPolicy
    members: list[ModelMember]
    schema: PhysicalSchema
    model_digest: str
    policy_digest: str
    compiler_version: str


class SemanticModelLoader:
    """Publish an immutable, completely validated model-directory snapshot."""

    def __init__(self, models_dir: Path, *, driver: str) -> None:
        """Configure a loader for one model directory and warehouse driver."""
        self.models_dir = models_dir
        self.driver = driver
        self._fingerprint: str | None = None
        self._snapshot: dict[str, LoadedModel] | None = None

    def load(self) -> dict[str, LoadedModel]:
        """Load model/policy pairs, rejecting unsupported format or bindings."""
        fingerprint, snapshot = self._build_snapshot()
        self._fingerprint = fingerprint
        self._snapshot = snapshot
        return snapshot

    def reload_if_changed(self) -> bool:
        """Atomically replace the snapshot only after full validation."""
        fingerprint = self._directory_fingerprint()
        if self._snapshot is not None and fingerprint == self._fingerprint:
            return False
        fingerprint, snapshot = self._build_snapshot(fingerprint)
        self._fingerprint = fingerprint
        self._snapshot = snapshot
        return True

    def _build_snapshot(self, fingerprint: str | None = None) -> tuple[str, dict[str, LoadedModel]]:
        """Build a complete candidate snapshot without publishing partial state."""
        if not self.models_dir.is_dir():
            raise SemanticPolicyError("invalid_models_dir", "Model directory does not exist")
        documents = self._load_documents()
        models = self._models_from_documents(documents)
        validate_model_graph(models)
        related = {name: self._reachable_models(name, models) for name in models}
        snapshots: dict[str, LoadedModel] = {}
        for name, model in models.items():
            related_models = {related_name: models[related_name] for related_name in related[name]}
            graph_models = {name: model, **related_models}
            members = _members_for(model)
            tables = {graph_model.table for graph_model in graph_models.values()}
            policy_path = self.models_dir / f"{name}.policy.yaml"
            if not policy_path.is_file():
                raise SemanticPolicyError(
                    "missing_policy", "Each semantic model requires a policy side-file", details={"model": name}
                )
            policy = load_policy(policy_path, members, tables)
            schema = PhysicalSchema(
                driver=self.driver,
                tables={graph_model.table: dict(graph_model.columns) for graph_model in graph_models.values()},
            )
            snapshots[name] = LoadedModel(
                name=name,
                model=model,
                related_models=related_models,
                policy=policy,
                members=members,
                schema=schema,
                model_digest=_graph_digest(model, related_models),
                policy_digest=policy.digest(),
                compiler_version=__version__,
            )
        return fingerprint or self._directory_fingerprint(), snapshots

    def _load_documents(self) -> list[dict[str, Any]]:
        """Read model documents while excluding policy side-files."""
        paths = [
            path
            for path in sorted(self.models_dir.iterdir())
            if path.is_file()
            and path.suffix.lower() in {".yaml", ".yml", ".json"}
            and not path.name.endswith(".policy.yaml")
        ]
        if not paths:
            raise SemanticPolicyError("missing_model", "Model directory contains no model documents")
        documents: list[dict[str, Any]] = []
        for path in paths:
            try:
                loaded = (
                    json.loads(path.read_text()) if path.suffix.lower() == ".json" else yaml.safe_load(path.read_text())
                )
            except (OSError, ValueError, yaml.YAMLError) as exc:
                raise SemanticPolicyError(
                    "invalid_model", "Unable to parse model document", details={"path": path.name}
                ) from exc
            if not isinstance(loaded, dict):
                raise SemanticPolicyError(
                    "invalid_model", "Model documents must be mappings", details={"path": path.name}
                )
            documents.append(loaded)
        return documents

    def _models_from_documents(self, documents: list[dict[str, Any]]) -> dict[str, SemanticModel]:
        """Lower own YAML and validated Ossie documents into graph models."""
        models: dict[str, SemanticModel] = {}
        for document in documents:
            lowered = _lower_ossie(document) if is_ossie_document(document) else _lower_own_format(document)
            for model in lowered:
                if model.name in models:
                    raise SemanticPolicyError(
                        "duplicate_model", "Model names must be unique", details={"model": model.name}
                    )
                models[model.name] = model
        return models

    @staticmethod
    def _reachable_models(root: str, models: dict[str, SemanticModel]) -> tuple[str, ...]:
        """Return the connected model graph in deterministic breadth-first order."""
        adjacency = {name: set() for name in models}
        for model in models.values():
            for relationship in model.relationships:
                adjacency[relationship.from_model].add(relationship.to_model)
                adjacency[relationship.to_model].add(relationship.from_model)
        pending = deque([root])
        visited = {root}
        while pending:
            current = pending.popleft()
            for neighbor in sorted(adjacency[current]):
                if neighbor not in visited:
                    visited.add(neighbor)
                    pending.append(neighbor)
        return tuple(sorted(visited.difference({root})))

    def _directory_fingerprint(self) -> str:
        """Return a content fingerprint for all model and policy files."""
        if not self.models_dir.is_dir():
            raise SemanticPolicyError("invalid_models_dir", "Model directory does not exist")
        digest = hashlib.sha256()
        for path in sorted(path for path in self.models_dir.iterdir() if path.is_file()):
            digest.update(path.name.encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()


def _lower_own_format(document: dict[str, Any]) -> list[SemanticModel]:
    """Validate the compact own-format YAML envelope."""
    if set(document) != {"models"} or not isinstance(document["models"], list):
        raise SemanticPolicyError("invalid_model", "Own-format documents require exactly a models list")
    try:
        return [SemanticModel.model_validate(item) for item in document["models"]]
    except Exception as exc:
        raise SemanticPolicyError("invalid_model", "Own-format model does not match the typed graph") from exc


def _lower_ossie(document: dict[str, Any]) -> list[SemanticModel]:
    """Lower the supported public Ossie subset without inferring hidden semantics."""
    validate_ossie_document(document)
    result: list[SemanticModel] = []
    for semantic_model in document["semantic_model"]:
        datasets = semantic_model["datasets"]
        if len(datasets) != 1:
            raise SemanticPolicyError("unsupported_ossie", "Ossie documents with multiple datasets are unsupported")
        dataset = datasets[0]
        primary_key = dataset.get("primary_key")
        if not isinstance(primary_key, list) or not primary_key:
            raise SemanticPolicyError("unsupported_ossie", "Ossie datasets require a primary_key")
        fields = dataset.get("fields", [])
        dimensions: list[Dimension] = []
        columns: dict[str, str] = {}
        for field in fields:
            name = field["name"]
            expression = _ansi_expression(field["expression"], "field")
            if expression != name or not _IDENTIFIER.fullmatch(name):
                raise SemanticPolicyError("unsupported_ossie", "Ossie fields must be simple ANSI_SQL columns")
            columns[name] = "UNKNOWN"
            dimension = field.get("dimension")
            if dimension is not None:
                dimensions.append(
                    Dimension(
                        name=name, kind="time" if dimension.get("is_time") else "categorical", column=name, grain="day"
                    )
                    if dimension.get("is_time")
                    else Dimension(name=name, kind="categorical", column=name)
                )
        metrics = [_ossie_metric(metric, dataset["name"]) for metric in semantic_model.get("metrics", [])]
        if semantic_model.get("relationships"):
            raise SemanticPolicyError(
                "unsupported_ossie",
                "Ossie relationships cannot be lowered without public physical type metadata",
            )
        try:
            result.append(
                SemanticModel(
                    name=dataset["name"],
                    table=dataset["source"],
                    columns=columns,
                    primary_key=tuple(primary_key),
                    dimensions=tuple(dimensions),
                    metrics=tuple(metrics),
                    relationships=(),
                )
            )
        except Exception as exc:
            raise SemanticPolicyError(
                "unsupported_ossie", "Ossie document cannot be lowered into the typed graph"
            ) from exc
    return result


def _ansi_expression(expression: dict[str, Any], kind: str) -> str:
    """Return one ANSI_SQL expression and reject ambiguous dialect variants."""
    dialects = expression["dialects"]
    if len(dialects) != 1 or dialects[0]["dialect"] != "ANSI_SQL":
        raise SemanticPolicyError("unsupported_ossie", f"Ossie {kind} requires one ANSI_SQL expression")
    return dialects[0]["expression"]


def _ossie_metric(metric: dict[str, Any], dataset_name: str) -> Metric:
    """Lower a simple public Ossie aggregate expression into a typed metric."""
    expression = _ansi_expression(metric["expression"], "metric")
    match = _AGGREGATE_EXPRESSION.fullmatch(expression)
    if match is None:
        raise SemanticPolicyError("unsupported_ossie", "Ossie metrics must be simple aggregate expressions")
    aggregate = match.group("aggregate").lower()
    column = match.group("column")
    if column != "*":
        owner, column = column.split(".", 1)
        if owner != dataset_name:
            raise SemanticPolicyError("unsupported_ossie", "Ossie metric expression references another dataset")
    return Metric(name=metric["name"], agg=aggregate, column=None if column == "*" else column)


def _members_for(model: SemanticModel) -> list[ModelMember]:
    """Derive policy-visible semantic member metadata from one root model."""
    members = [ModelMember(name=metric.name, kind="metric") for metric in model.metrics]
    members.extend(
        ModelMember(
            name=dimension.name,
            kind="time_dimension" if dimension.kind == "time" else "dimension",
            grain=dimension.grain,
        )
        for dimension in model.dimensions
    )
    return members


def _graph_digest(model: SemanticModel, related_models: dict[str, SemanticModel]) -> str:
    """Return a root version that changes when any reachable definition changes."""
    graph = {model.name: model, **related_models}
    payload = {name: graph[name].model_dump(mode="json") for name in sorted(graph)}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()
