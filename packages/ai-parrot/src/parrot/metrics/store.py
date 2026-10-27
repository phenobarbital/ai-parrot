"""MetricStore protocol and the in-memory backend (FEAT-756 M2)."""
from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from parrot.metrics.models import MetricDefinition


@runtime_checkable
class MetricStore(Protocol):
    """Persistence boundary for tenant-scoped metric definitions."""

    async def get(self, metric_id: str, *, tenant: str | None) -> MetricDefinition | None:
        """Return one definition in exactly that namespace, or ``None``."""

    async def list(self, *, tenant: str | None, program: str | None = None) -> list[MetricDefinition]:
        """Return every definition of one namespace without visibility filtering."""

    async def save(self, definition: MetricDefinition, *, overwrite: bool = False) -> str:
        """Insert or upsert a definition and return its identifier."""

    async def delete(self, metric_id: str, *, tenant: str | None) -> bool:
        """Remove one definition and report whether it was present."""


class InMemoryMetricStore:
    """Dict-backed ``MetricStore`` for tests, notebooks and agents without Postgres."""

    def __init__(self, definitions: Iterable[MetricDefinition] = ()) -> None:
        """Pre-load definitions, raising ``ValueError`` for duplicate keys."""
        self._rows: dict[tuple[str | None, str], MetricDefinition] = {}
        for definition in definitions:
            self._put(definition, overwrite=False)

    def _put(self, definition: MetricDefinition, *, overwrite: bool) -> str:
        """Store a deep copy of one definition and return its identifier."""
        key = (definition.tenant, definition.id)
        if key in self._rows and not overwrite:
            raise ValueError(f"metric {definition.id!r} already exists for tenant {definition.tenant!r}")
        self._rows[key] = definition.model_copy(deep=True)
        return definition.id

    async def get(self, metric_id: str, *, tenant: str | None) -> MetricDefinition | None:
        """Return a deep copy of a metric definition in its exact namespace."""
        definition = self._rows.get((tenant, metric_id))
        return definition.model_copy(deep=True) if definition is not None else None

    async def list(self, *, tenant: str | None, program: str | None = None) -> list[MetricDefinition]:
        """Return sorted deep copies of definitions in one namespace."""
        definitions = [
            definition
            for (definition_tenant, _), definition in self._rows.items()
            if definition_tenant == tenant and (program is None or definition.program == program)
        ]
        return [definition.model_copy(deep=True) for definition in sorted(definitions, key=lambda item: item.id)]

    async def save(self, definition: MetricDefinition, *, overwrite: bool = False) -> str:
        """Insert or upsert a definition."""
        return self._put(definition, overwrite=overwrite)

    async def delete(self, metric_id: str, *, tenant: str | None) -> bool:
        """Remove one definition and report whether it was present."""
        return self._rows.pop((tenant, metric_id), None) is not None
