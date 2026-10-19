"""Load a models directory into governed semantic models."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from .errors import SemanticPolicyError
from .models import ModelMember
from .ossie import is_ossie_document, validate_ossie_document
from .policy import ModelPolicy, load_policy

logger = logging.getLogger(__name__)

_MODEL_SUFFIXES = {".aml", ".json", ".lkml", ".malloy", ".sql", ".tds", ".tdsx", ".tml", ".twb", ".twbx", ".yaml", ".yml"}
_TYPE_BY_DIMENSION = {"boolean": "BOOLEAN", "categorical": "TEXT", "numeric": "DOUBLE", "time": "TIMESTAMP"}


class PhysicalSchema(BaseModel):
    """Physical tables and columns declared by a semantic model graph."""

    driver: str
    tables: dict[str, dict[str, str]]

    def sqlglot_schema(self) -> dict[str, dict[str, dict[str, str]]]:
        """Return the nested mapping accepted by ``sqlglot`` qualification."""
        out: dict[str, dict[str, dict[str, str]]] = {}
        for qualified, columns in self.tables.items():
            schema, separator, table = qualified.partition(".")
            if not separator:
                out.setdefault("", {})[schema] = dict(columns)
            else:
                out.setdefault(schema, {})[table] = dict(columns)
        return out


class LoadedModel(BaseModel):
    """One governed semantic entry point and its shared compiled graph."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    layer: Any
    policy: ModelPolicy
    members: list[ModelMember]
    schema: PhysicalSchema
    model_digest: str
    policy_digest: str
    engine_version: str


class SemanticModelLoader:
    """Load sidemantic definitions and matching ai-parrot policy side-files."""

    def __init__(self, models_dir: Path, *, driver: str) -> None:
        """Initialize a loader for ``models_dir`` without opening a database connection."""
        self.models_dir = Path(models_dir)
        self.driver = driver
        self._fingerprint: str | None = None
        self.logger = logger

    def load(self) -> dict[str, LoadedModel]:
        """Load every policy-backed model and reject embedded sidemantic security."""
        from sidemantic import SemanticLayer, __version__
        from sidemantic.loaders import load_from_directory

        if not self.models_dir.is_dir():
            raise SemanticPolicyError("models_dir_missing")

        source_files = self._source_files()
        policy_files = sorted(self.models_dir.glob("*.policy.yaml"))
        self._validate_sources(source_files)

        layer = SemanticLayer(dialect=self.driver, auto_register=False, engine="python")
        try:
            with tempfile.TemporaryDirectory(prefix="parrot-semantic-") as staging:
                staging_dir = Path(staging) / "models"
                shutil.copytree(self.models_dir, staging_dir)
                ossie_dir = Path(staging) / "ossie"
                ossie_dir.mkdir()
                for ossie_path in staging_dir.rglob("*.ossie.json"):
                    shutil.move(ossie_path, ossie_dir / ossie_path.name)
                load_from_directory(layer, staging_dir, strict=True)
                time_fields = self._make_ossie_importer_compatible(ossie_dir)
                if any(ossie_dir.iterdir()):
                    ossie_layer = SemanticLayer(dialect=self.driver, auto_register=False, engine="python")
                    load_from_directory(ossie_layer, ossie_dir, strict=True)
                    for imported in ossie_layer.graph.models.values():
                        for dimension in imported.dimensions:
                            if dimension.name in time_fields.get(imported.name, set()):
                                dimension.type = "time"
                                dimension.granularity = dimension.granularity or "day"
                        if imported.name not in layer.graph.models:
                            layer.add_model(imported)
                    for metric in ossie_layer.graph.metrics.values():
                        if metric.name not in layer.graph.metrics:
                            layer.add_metric(metric)
        except SemanticPolicyError:
            raise
        except Exception as error:
            raise SemanticPolicyError("invalid_model") from error

        if any(getattr(model, "security", None) is not None for model in layer.graph.models.values()):
            raise SemanticPolicyError("security_block")

        schema = PhysicalSchema(driver=self.driver, tables=self._physical_tables(layer))
        members = self._members(layer)
        model_digest = self._digest_files(source_files)
        loaded: dict[str, LoadedModel] = {}
        for policy_path in policy_files:
            name = policy_path.name.removesuffix(".policy.yaml")
            if name not in layer.graph.models:
                raise SemanticPolicyError("policy_model_mismatch", details={"model": name})
            policy = load_policy(policy_path, members, set(schema.tables))
            loaded[name] = LoadedModel(
                name=name,
                layer=layer,
                policy=policy,
                members=members,
                schema=schema,
                model_digest=model_digest,
                policy_digest=policy.digest(),
                engine_version=__version__,
            )

        queryable_names = {name for name in layer.graph.models if name in {path.name.removesuffix(".policy.yaml") for path in policy_files}}
        if not loaded or queryable_names != set(loaded):
            raise SemanticPolicyError("missing_policy")
        root_names = {self._root_name(path) for path in source_files if self._root_name(path)}
        missing = sorted(name for name in root_names if name in layer.graph.models and name not in loaded)
        if missing:
            raise SemanticPolicyError("missing_policy", details={"models": missing})

        self._fingerprint = self._directory_fingerprint()
        return loaded

    def reload_if_changed(self) -> bool:
        """Re-read definitions when any file digest changed."""
        fingerprint = self._directory_fingerprint()
        if fingerprint == self._fingerprint:
            return False
        self.load()
        return True

    def _source_files(self) -> list[Path]:
        """Return model inputs while excluding ai-parrot policy side-files."""
        return sorted(
            path
            for path in self.models_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in _MODEL_SUFFIXES and not path.name.endswith(".policy.yaml")
        )

    def _validate_sources(self, source_files: list[Path]) -> None:
        """Validate Ossie inputs and reject native YAML security blocks before loading."""
        for path in source_files:
            if path.name.lower().endswith(".ossie.json"):
                try:
                    document = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    raise SemanticPolicyError("ossie_invalid") from error
                if not isinstance(document, dict) or not is_ossie_document(document):
                    raise SemanticPolicyError("ossie_invalid")
                validate_ossie_document(document)
            elif path.suffix.lower() in {".yaml", ".yml"}:
                try:
                    document = yaml.safe_load(path.read_text(encoding="utf-8"))
                except (OSError, yaml.YAMLError) as error:
                    raise SemanticPolicyError("invalid_model") from error
                if self._contains_security(document):
                    raise SemanticPolicyError("security_block")

    @staticmethod
    def _make_ossie_importer_compatible(staging_dir: Path) -> dict[str, set[str]]:
        """Add fields implied by Ossie primary keys for sidemantic 0.12.0 lowering.

        Ossie 0.1.1 permits a physical primary-key declaration without repeating the
        key in ``fields``. Sidemantic 0.12.0 requires that repetition. The source is
        validated and left unchanged; only the private import staging copy is expanded.
        """
        time_fields: dict[str, set[str]] = {}
        for path in staging_dir.rglob("*.ossie.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            changed = False
            for semantic_model in document.get("semantic_model", []):
                model_name = semantic_model.get("name", "")
                for dataset in semantic_model.get("datasets", []):
                    fields = dataset.setdefault("fields", [])
                    field_names = {field.get("name") for field in fields}
                    for field in fields:
                        dimension = field.get("dimension") or {}
                        if dimension.get("is_time") is True:
                            time_fields.setdefault(model_name, set()).add(field.get("name", ""))
                            dimension["is_time"] = False
                            changed = True
                    for key in dataset.get("primary_key", []):
                        if key in field_names:
                            continue
                        fields.append(
                            {
                                "name": key,
                                "expression": {
                                    "dialects": [{"dialect": "ANSI_SQL", "expression": key}],
                                },
                                "dimension": {"is_time": False},
                            }
                        )
                        changed = True
            if changed:
                path.write_text(json.dumps(document), encoding="utf-8")
        return time_fields

    @classmethod
    def _contains_security(cls, value: object) -> bool:
        """Return whether a parsed model document contains a ``security`` key."""
        if isinstance(value, dict):
            return "security" in value or any(cls._contains_security(item) for item in value.values())
        if isinstance(value, list):
            return any(cls._contains_security(item) for item in value)
        return False

    @staticmethod
    def _members(layer: Any) -> list[ModelMember]:
        """Derive the public member catalog from the loaded sidemantic graph."""
        members: dict[str, ModelMember] = {}
        for model in layer.graph.models.values():
            for dimension in model.dimensions:
                kind = "time_dimension" if dimension.type == "time" else "dimension"
                members.setdefault(
                    dimension.name,
                    ModelMember(
                        name=dimension.name,
                        kind=kind,
                        description=dimension.description or "",
                        grain=dimension.granularity,
                    ),
                )
            for metric in model.metrics:
                members.setdefault(
                    metric.name,
                    ModelMember(name=metric.name, kind="metric", description=getattr(metric, "description", None) or ""),
                )
        for metric in layer.graph.metrics.values():
            members.setdefault(
                metric.name,
                ModelMember(name=metric.name, kind="metric", description=getattr(metric, "description", None) or ""),
            )
        return list(members.values())

    @staticmethod
    def _physical_tables(layer: Any) -> dict[str, dict[str, str]]:
        """Build physical schema metadata solely from declarations in the model graph."""
        tables: dict[str, dict[str, str]] = {}
        for model in layer.graph.models.values():
            if not model.table:
                continue
            columns = tables.setdefault(model.table, {})
            for primary_key in model.primary_key_columns:
                columns.setdefault(primary_key, "BIGINT")
            for dimension in model.dimensions:
                expression = dimension.sql or dimension.name
                if expression.isidentifier():
                    metadata = dimension.metadata or {}
                    columns[expression] = str(metadata.get("data_type") or _TYPE_BY_DIMENSION[dimension.type]).upper()
            for metric in model.metrics:
                expression = metric.sql
                if expression and expression.isidentifier():
                    metadata = getattr(metric, "metadata", None) or {}
                    columns.setdefault(expression, str(metadata.get("data_type") or "DOUBLE").upper())
        return tables

    @staticmethod
    def _digest_files(paths: list[Path], root: Path | None = None) -> str:
        """Hash sorted relative paths and contents without relying on mtimes."""
        digest = hashlib.sha256()
        base = root or (Path(paths[0]).parent if paths else Path("."))
        for path in paths:
            try:
                relative = path.relative_to(base)
            except ValueError:
                relative = path
            digest.update(relative.as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def _directory_fingerprint(self) -> str:
        """Hash every regular file below the configured model directory."""
        paths = sorted(path for path in self.models_dir.rglob("*") if path.is_file())
        return self._digest_files(paths, self.models_dir)

    @staticmethod
    def _root_name(path: Path) -> str | None:
        """Return a conventional root model name for native source filenames."""
        if path.name.lower().endswith(".ossie.json"):
            return None
        if path.suffix.lower() not in {".yaml", ".yml", ".sql"}:
            return None
        return path.stem
