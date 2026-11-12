"""Tenant-scoped catalog of accounting models (FEAT-713 M8)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Mapping

from .errors import ModelValidationError, Problem
from .loader import load_model, load_spec
from .models import AccountingModel, AccountingModelSpec, ChartSnapshot, MetricDef

if TYPE_CHECKING:
    from .live import ModelLiveStatus

SnapshotProvider = Callable[[str, str, AccountingModelSpec], Awaitable[ChartSnapshot]]
Key = tuple[str, str]

_SUFFIXES = (".yaml", ".yml")


def _prefixed(path: Path, problems: list[Problem]) -> list[Problem]:
    """Return *problems* with each message prefixed by the offending file (quoted)."""
    return [problem.model_copy(update={"message": f"{str(path)!r}: {problem.message}"}) for problem in problems]


class ModelCatalog:
    """Indexes ``<models_dir>/<tenant>/<model>.yaml`` specs; loads selected models atomically.

    Specs are parsed once at construction and are available without any chart snapshot. Models are loaded
    only for the keys a caller supplies snapshots for; each batch is validated in full before it is published
    by swapping the model mapping under a lock, so readers never observe a partially loaded batch.
    """

    def __init__(self, models_dir: Path) -> None:
        """Scan and parse every ``<tenant>/<model>.yaml`` (or ``.yml``) under *models_dir*.

        Args:
            models_dir: Root directory holding one sub-directory per tenant. A missing directory yields an
                empty catalog.

        Raises:
            ModelValidationError: When a YAML cannot be parsed, when its declared ``tenant``/``model`` differ
                from its directory/file names, or when two files map to the same ``(tenant, model)``. The
                message names the offending file.
        """
        self.models_dir = Path(models_dir)
        self._lock = threading.Lock()
        self._paths: dict[Key, Path] = {}
        self._specs: dict[Key, AccountingModelSpec] = {}
        self._models: dict[Key, AccountingModel] = {}
        self._flags: dict[Key, "ModelLiveStatus"] = {}
        if not self.models_dir.is_dir():
            return
        for tenant_dir in sorted(p for p in self.models_dir.iterdir() if p.is_dir()):
            for path in sorted(p for p in tenant_dir.iterdir() if p.is_file() and p.suffix in _SUFFIXES):
                key: Key = (tenant_dir.name, path.stem)
                if key in self._paths:
                    message = f"duplicate model definition {str(path)!r} (already defined by {str(self._paths[key])!r})"
                    raise ModelValidationError([Problem(code="dangling_ref", message=message)], message=message)
                spec = self._parse(path)
                self._check_identity(path, key, spec)
                self._paths[key] = path
                self._specs[key] = spec

    @staticmethod
    def _parse(path: Path) -> AccountingModelSpec:
        """Parse one model file; re-raise schema errors with the file named."""
        try:
            return load_spec(path)
        except ModelValidationError as exc:
            raise ModelValidationError(
                _prefixed(path, exc.problems), message=f"invalid model file {str(path)!r}: {exc}"
            ) from exc

    @staticmethod
    def _check_identity(path: Path, key: Key, spec: AccountingModelSpec) -> None:
        """Require the YAML's ``tenant``/``model`` to equal the directory/file names."""
        tenant, model = key
        if spec.tenant == tenant and spec.model == model:
            return
        message = (
            f"model file {str(path)!r} declares tenant={spec.tenant!r}, model={spec.model!r} "
            f"but its path implies tenant={tenant!r}, model={model!r}"
        )
        raise ModelValidationError([Problem(code="dangling_ref", message=message)], message=message)

    def specs(self) -> dict[Key, AccountingModelSpec]:
        """Parsed YAML specs keyed (tenant, model) — available before snapshots exist."""
        return dict(self._specs)

    def load(
        self,
        snapshots: Mapping[Key, ChartSnapshot],
        columns: Mapping[Key, Mapping[str, str]] | None = None,
    ) -> None:
        """Load only supplied keys; validate the whole batch before atomic publication.

        Args:
            snapshots: Chart snapshot per ``(tenant, model)`` to load.
            columns: Optional journal column types per key, forwarded to load-time validation.

        Raises:
            KeyError: When a key is not in the catalog (nothing is published).
            ModelValidationError: When any model of the batch fails validation or its identity no longer matches
                its path; carries every problem of the batch and names each failing file (nothing is published).
        """
        unknown = sorted(key for key in snapshots if key not in self._paths)
        if unknown:
            raise KeyError(f"unknown accounting model(s): {', '.join(repr(key) for key in unknown)}")
        batch: dict[Key, AccountingModel] = {}
        problems: list[Problem] = []
        failed: list[str] = []
        for key in sorted(snapshots):
            path = self._paths[key]
            key_columns = columns.get(key) if columns is not None else None
            try:
                model = load_model(path, snapshots[key], columns=key_columns)
                self._check_identity(path, key, model.spec)
            except ModelValidationError as exc:
                problems.extend(_prefixed(path, exc.problems))
                failed.append(repr(str(path)))
                continue
            batch[key] = model
        if failed:
            raise ModelValidationError(
                problems,
                message=f"{len(problems)} model validation problem(s) in {', '.join(failed)}; nothing was loaded",
            )
        with self._lock:
            published = dict(self._models)
            published.update(batch)
            self._models = published

    def reload(
        self,
        snapshots: Mapping[Key, ChartSnapshot],
        columns: Mapping[Key, Mapping[str, str]] | None = None,
    ) -> None:
        """Validate replacements before atomic publication; caller invalidates replaced model hashes."""
        self.load(snapshots, columns)

    def get(self, tenant: str, model: str) -> AccountingModel:
        """The loaded model; KeyError when not loaded."""
        return self._models[(tenant, model)]

    def is_loaded(self, tenant: str, model: str) -> bool:
        """Whether ``(tenant, model)`` has a published model."""
        return (tenant, model) in self._models

    def metrics(self, tenant: str) -> list[tuple[str, str, MetricDef]]:
        """(model, metric name, definition) from parsed specs for one tenant; no snapshot access."""
        rows = [
            (model, name, definition)
            for (spec_tenant, model), spec in self._specs.items()
            if spec_tenant == tenant
            for name, definition in spec.metrics.items()
        ]
        return sorted(rows, key=lambda row: (row[0], row[1]))

    def flags(self, tenant: str, model: str) -> "ModelLiveStatus | None":
        """The latest live status recorded for ``(tenant, model)``, if any."""
        return self._flags.get((tenant, model))

    def set_flags(self, status: "ModelLiveStatus") -> None:
        """Record *status* for its ``(status.tenant, status.model)``."""
        with self._lock:
            self._flags[(status.tenant, status.model)] = status
