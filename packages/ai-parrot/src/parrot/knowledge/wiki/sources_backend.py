"""Source manifest backend contract and registry (FEAT-540 M7)."""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

from parrot.knowledge.wiki.models import SourceManifestEntry


@runtime_checkable
class SourceManifestBackend(Protocol):
    """Persistence contract for source-manifest operations."""

    async def upsert(self, entry: SourceManifestEntry) -> None: ...
    async def upsert_many(self, entries: list[SourceManifestEntry]) -> None: ...
    async def list_sources(self) -> list[SourceManifestEntry]: ...
    async def get_source(self, source_id: str) -> SourceManifestEntry | None: ...
    async def remove_source(self, source_id: str) -> bool: ...
    async def find_id_by_uri(self, source_uri: str) -> str | None: ...
    async def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None: ...
    async def find_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]: ...
    async def find_by_ids(self, source_ids: list[str]) -> dict[str, SourceManifestEntry]: ...
    async def find_by_external_ids(self, external_ids: list[str]) -> dict[str, SourceManifestEntry]: ...
    async def list_by_external_prefix(self, prefix: str) -> list[SourceManifestEntry]: ...


SourceBackendFactory = Callable[..., SourceManifestBackend]
_SOURCE_BACKENDS: dict[str, SourceBackendFactory] = {}


def register_source_backend(name: str, factory: SourceBackendFactory) -> None:
    """Register a source-manifest backend factory.

    Args:
        name: Stable backend name used by configuration.
        factory: Callable returning an implementation of the contract.
    """
    _SOURCE_BACKENDS[name] = factory


def create_source_backend(name: str, **options: Any) -> SourceManifestBackend:
    """Create a source-manifest backend by registered name.

    Args:
        name: Registered backend name.
        **options: Backend-specific construction options.

    Returns:
        The constructed source-manifest backend.

    Raises:
        ValueError: If ``name`` is not registered.
    """
    try:
        factory = _SOURCE_BACKENDS[name]
    except KeyError as exc:
        names = ", ".join(sorted(_SOURCE_BACKENDS))
        raise ValueError(f"Unknown sources backend {name!r} — expected one of: {names}") from exc
    return factory(**options)


class _ManagerBackend:
    """Delegate a built-in synchronous implementation to its manager."""

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    async def upsert(self, entry: SourceManifestEntry) -> None:
        self._manager._legacy_upsert(entry)

    async def upsert_many(self, entries: list[SourceManifestEntry]) -> None:
        self._manager._legacy_upsert_many(entries)

    async def list_sources(self) -> list[SourceManifestEntry]:
        return self._manager._legacy_list_sources()

    async def get_source(self, source_id: str) -> SourceManifestEntry | None:
        return self._manager._legacy_get_source(source_id)

    async def remove_source(self, source_id: str) -> bool:
        return self._manager._legacy_remove_source(source_id)

    async def find_id_by_uri(self, source_uri: str) -> str | None:
        return self._manager._legacy_find_id_by_uri(source_uri)

    async def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None:
        return self._manager._legacy_find_by_external_id(external_id)

    async def find_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]:
        return self._manager._legacy_find_by_uris(uris)

    async def find_by_ids(self, source_ids: list[str]) -> dict[str, SourceManifestEntry]:
        return self._manager._legacy_find_by_ids(source_ids)

    async def find_by_external_ids(self, external_ids: list[str]) -> dict[str, SourceManifestEntry]:
        return self._manager._legacy_find_by_external_ids(external_ids)

    async def list_by_external_prefix(self, prefix: str) -> list[SourceManifestEntry]:
        return self._manager._legacy_list_by_external_prefix(prefix)


class SqliteSourceBackend(_ManagerBackend):
    """SQLite source-manifest backend backed by the manager's schema helpers."""


class JsonSourceBackend(_ManagerBackend):
    """JSON source-manifest backend backed by the manager's manifest helpers."""


def _create_sqlite_backend(**options: Any) -> SourceManifestBackend:
    """Lazily create the SQLite implementation."""
    return SqliteSourceBackend(options["manager"])


def _create_json_backend(**options: Any) -> SourceManifestBackend:
    """Lazily create the JSON implementation."""
    return JsonSourceBackend(options["manager"])


def _create_arango_backend(**options: Any) -> SourceManifestBackend:
    """Lazily import and create the optional ArangoDB implementation."""
    from parrot.knowledge.wiki.arango_sources import ArangoSourceBackend

    return ArangoSourceBackend(arango_db=options.get("arango_db"), arango_store=options.get("arango_store"))


register_source_backend("sqlite", _create_sqlite_backend)
register_source_backend("json", _create_json_backend)
register_source_backend("arangodb", _create_arango_backend)
