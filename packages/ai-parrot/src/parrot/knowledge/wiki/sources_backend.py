"""Source manifest backend contract and registry (FEAT-540 M7).

:class:`SourceManifestBackend` is a **synchronous** contract — it is what
:class:`~parrot.knowledge.wiki.sources.SourceCollectionManager`'s sync API
talks to.  Local kinds (``sqlite``, ``json``) implement it directly, so
their I/O never touches an event loop.  Async-native kinds (``arangodb``)
implement :class:`AsyncSourceManifestBackend` and are wrapped in
:class:`AsyncSourceBackendBridge`, the only place a coroutine is bridged
into sync code.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Callable, Protocol, runtime_checkable

from parrot.knowledge.wiki.models import SourceManifestEntry

#: The one definition of the sqlite ``sources`` upsert, shared by the
#: single-row and batch writers so the 15-column statement can never drift.
_SOURCES_UPSERT_SQL = (
    "INSERT INTO sources"
    " (source_id, source_uri, file_hash, mtime, ingested_at,"
    "  pages_generated, status, destination, decision_source,"
    "  charter_version, composite_score, doc_metadata,"
    "  content_type, loader, external_id)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    " ON CONFLICT(source_id) DO UPDATE SET"
    "  source_uri=excluded.source_uri, file_hash=excluded.file_hash,"
    "  mtime=excluded.mtime, ingested_at=excluded.ingested_at,"
    "  pages_generated=excluded.pages_generated, status=excluded.status,"
    "  destination=excluded.destination,"
    "  decision_source=excluded.decision_source,"
    "  charter_version=excluded.charter_version,"
    "  composite_score=excluded.composite_score,"
    "  doc_metadata=excluded.doc_metadata,"
    "  content_type=excluded.content_type,"
    "  loader=excluded.loader,"
    "  external_id=excluded.external_id"
)

#: Max bind parameters per sqlite ``IN (...)`` clause. SQLite's own
#: ``SQLITE_MAX_VARIABLE_NUMBER`` defaults to 999 on older builds, so the
#: bulk readers chunk below that rather than assuming a modern limit.
_SQLITE_IN_CHUNK = 500


@runtime_checkable
class SourceManifestBackend(Protocol):
    """Synchronous persistence contract for source-manifest operations."""

    def upsert(self, entry: SourceManifestEntry) -> None: ...
    def upsert_many(self, entries: list[SourceManifestEntry]) -> None: ...
    def list_sources(self) -> list[SourceManifestEntry]: ...
    def get_source(self, source_id: str) -> SourceManifestEntry | None: ...
    def remove_source(self, source_id: str) -> bool: ...
    def find_id_by_uri(self, source_uri: str) -> str | None: ...
    def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None: ...
    def find_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]: ...
    def find_by_ids(self, source_ids: list[str]) -> dict[str, SourceManifestEntry]: ...
    def find_by_external_ids(self, external_ids: list[str]) -> dict[str, SourceManifestEntry]: ...
    def list_by_external_prefix(self, prefix: str) -> list[SourceManifestEntry]: ...


@runtime_checkable
class AsyncSourceManifestBackend(Protocol):
    """Asynchronous twin of :class:`SourceManifestBackend` (network backends)."""

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
        factory: Callable returning a *synchronous* implementation of the
            contract (wrap async backends in :class:`AsyncSourceBackendBridge`).
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


class SqliteSourceBackend:
    """SQLite source-manifest backend (the ``sources`` table of ``wiki.db``).

    Fully synchronous: short-lived per-call ``sqlite3`` connections obtained
    from the owning manager's ``_connect()`` / ``_write()`` helpers.
    """

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    def upsert(self, entry: SourceManifestEntry) -> None:
        with self._manager._write("upsert_source") as conn:
            conn.execute(_SOURCES_UPSERT_SQL, self._manager._entry_params(entry))

    def upsert_many(self, entries: list[SourceManifestEntry]) -> None:
        if not entries:
            return
        with self._manager._write("upsert_sources") as conn:
            conn.executemany(_SOURCES_UPSERT_SQL, [self._manager._entry_params(e) for e in entries])

    def list_sources(self) -> list[SourceManifestEntry]:
        with self._manager._connect() as conn:
            rows = conn.execute("SELECT * FROM sources ORDER BY rowid").fetchall()
        return [self._manager._row_to_entry(row) for row in rows]

    def get_source(self, source_id: str) -> SourceManifestEntry | None:
        with self._manager._connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        return self._manager._row_to_entry(row) if row else None

    def remove_source(self, source_id: str) -> bool:
        # A real DML write — must go through the bounded `BEGIN IMMEDIATE`
        # transaction like every other writer, so contention maps to a typed
        # `WikiStoreBusy` instead of a raw `sqlite3.OperationalError` (AC-3).
        with self._manager._write("remove_source") as conn:
            cur = conn.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))
        return cur.rowcount > 0

    def find_id_by_uri(self, source_uri: str) -> str | None:
        with self._manager._connect() as conn:
            row = conn.execute("SELECT source_id FROM sources WHERE source_uri = ?", (source_uri,)).fetchone()
        return row["source_id"] if row else None

    def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None:
        with self._manager._connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE external_id = ? LIMIT 1", (external_id,)).fetchone()
        return self._manager._row_to_entry(row) if row else None

    def _find_in_column(self, column: str, values: list[str]) -> list[SourceManifestEntry]:
        """Fetch rows whose ``column`` is in ``values``, chunked under the bind limit."""
        ordered = list(set(values))
        entries: list[SourceManifestEntry] = []
        with self._manager._connect() as conn:
            for start in range(0, len(ordered), _SQLITE_IN_CHUNK):
                chunk = ordered[start : start + _SQLITE_IN_CHUNK]
                placeholders = ",".join("?" * len(chunk))
                # ``column`` is one of three hard-coded names below and the
                # f-string builds only the "?,?,?" placeholder run — values
                # are always bound, never interpolated.
                rows = conn.execute(
                    f"SELECT * FROM sources WHERE {column} IN ({placeholders})",
                    chunk,
                ).fetchall()
                entries.extend(self._manager._row_to_entry(row) for row in rows)
        return entries

    def find_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]:
        if not uris:
            return {}
        return {e.source_uri: e for e in self._find_in_column("source_uri", uris)}

    def find_by_ids(self, source_ids: list[str]) -> dict[str, SourceManifestEntry]:
        if not source_ids:
            return {}
        return {e.source_id: e for e in self._find_in_column("source_id", source_ids)}

    def find_by_external_ids(self, external_ids: list[str]) -> dict[str, SourceManifestEntry]:
        if not external_ids:
            return {}
        return {e.external_id: e for e in self._find_in_column("external_id", external_ids) if e.external_id is not None}

    def list_by_external_prefix(self, prefix: str) -> list[SourceManifestEntry]:
        with self._manager._connect() as conn:
            # LIKE with a trailing '%' after escaping SQLite's own LIKE
            # wildcards ('%', '_') in the prefix itself, so a literal
            # prefix containing those characters cannot widen the match.
            escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            rows = conn.execute(
                "SELECT * FROM sources WHERE external_id LIKE ? ESCAPE '\\'",
                (f"{escaped}%",),
            ).fetchall()
        return [self._manager._row_to_entry(row) for row in rows]


class JsonSourceBackend:
    """JSON source-manifest backend (``.manifest.json`` in ``sources_dir``).

    Operates on the owning manager's in-memory ``_manifest`` dict and
    persists it through the manager's ``_save_manifest()``.
    """

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    def upsert(self, entry: SourceManifestEntry) -> None:
        self._manager._manifest[entry.source_id] = entry
        self._manager._save_manifest()

    def upsert_many(self, entries: list[SourceManifestEntry]) -> None:
        if not entries:
            return
        for entry in entries:
            self._manager._manifest[entry.source_id] = entry
        self._manager._save_manifest()

    def list_sources(self) -> list[SourceManifestEntry]:
        return list(self._manager._manifest.values())

    def get_source(self, source_id: str) -> SourceManifestEntry | None:
        return self._manager._manifest.get(source_id)

    def remove_source(self, source_id: str) -> bool:
        if source_id not in self._manager._manifest:
            return False
        del self._manager._manifest[source_id]
        self._manager._save_manifest()
        return True

    def find_id_by_uri(self, source_uri: str) -> str | None:
        for sid, entry in self._manager._manifest.items():
            if entry.source_uri == source_uri:
                return sid
        return None

    def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None:
        for entry in self._manager._manifest.values():
            if entry.external_id == external_id:
                return entry
        return None

    def find_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]:
        wanted = set(uris)
        return {e.source_uri: e for e in self._manager._manifest.values() if e.source_uri in wanted}

    def find_by_ids(self, source_ids: list[str]) -> dict[str, SourceManifestEntry]:
        wanted = set(source_ids)
        return {sid: e for sid, e in self._manager._manifest.items() if sid in wanted}

    def find_by_external_ids(self, external_ids: list[str]) -> dict[str, SourceManifestEntry]:
        wanted = set(external_ids)
        return {
            e.external_id: e
            for e in self._manager._manifest.values()
            if e.external_id is not None and e.external_id in wanted
        }

    def list_by_external_prefix(self, prefix: str) -> list[SourceManifestEntry]:
        return [
            e for e in self._manager._manifest.values() if e.external_id is not None and e.external_id.startswith(prefix)
        ]


class AsyncSourceBackendBridge:
    """Expose an async source backend through the synchronous contract.

    The ``arangodb`` connection (``asyncdb``/``arangoasync`` on ``aiohttp``)
    is bound to the event loop it was created on, so:

    - when the bridge was built while a loop was running (``loop`` is set —
      the CLI ``build``/``upsert`` pipelines, which then call the sync API
      via ``asyncio.to_thread``), coroutines are scheduled back onto *that*
      loop with ``run_coroutine_threadsafe``.  Calling the sync API directly
      from that same loop's thread would deadlock, so that raises instead;
    - otherwise the coroutine runs in a **dedicated worker thread** with its
      own fresh loop.  The caller's thread is never handed to ``asyncio.run``,
      so its event-loop state (current loop, running loop) is left exactly as
      it was found.
    """

    def __init__(self, backend: AsyncSourceManifestBackend) -> None:
        self._backend = backend
        try:
            self._loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def _run(self, coro: Any) -> Any:
        """Run ``coro`` to completion from sync code without disturbing the caller's loop."""
        loop = self._loop
        if loop is not None and loop.is_running() and not loop.is_closed():
            try:
                current = asyncio.get_running_loop()
            except RuntimeError:
                current = None
            if current is loop:
                coro.close()
                raise RuntimeError(
                    "SourceCollectionManager(backend='arangodb') sync methods must be invoked via "
                    "asyncio.to_thread(...) when called from the same event loop the arango connection "
                    "was initialized on (calling them directly here would deadlock)."
                )
            if current is None:
                return asyncio.run_coroutine_threadsafe(coro, loop).result()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()

    def upsert(self, entry: SourceManifestEntry) -> None:
        self._run(self._backend.upsert(entry))

    def upsert_many(self, entries: list[SourceManifestEntry]) -> None:
        self._run(self._backend.upsert_many(entries))

    def list_sources(self) -> list[SourceManifestEntry]:
        return self._run(self._backend.list_sources())

    def get_source(self, source_id: str) -> SourceManifestEntry | None:
        return self._run(self._backend.get_source(source_id))

    def remove_source(self, source_id: str) -> bool:
        return self._run(self._backend.remove_source(source_id))

    def find_id_by_uri(self, source_uri: str) -> str | None:
        return self._run(self._backend.find_id_by_uri(source_uri))

    def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None:
        return self._run(self._backend.find_by_external_id(external_id))

    def find_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]:
        return self._run(self._backend.find_by_uris(uris))

    def find_by_ids(self, source_ids: list[str]) -> dict[str, SourceManifestEntry]:
        return self._run(self._backend.find_by_ids(source_ids))

    def find_by_external_ids(self, external_ids: list[str]) -> dict[str, SourceManifestEntry]:
        return self._run(self._backend.find_by_external_ids(external_ids))

    def list_by_external_prefix(self, prefix: str) -> list[SourceManifestEntry]:
        return self._run(self._backend.list_by_external_prefix(prefix))


def _create_sqlite_backend(**options: Any) -> SourceManifestBackend:
    """Lazily create the SQLite implementation."""
    return SqliteSourceBackend(options["manager"])


def _create_json_backend(**options: Any) -> SourceManifestBackend:
    """Lazily create the JSON implementation."""
    return JsonSourceBackend(options["manager"])


def _create_arango_backend(**options: Any) -> SourceManifestBackend:
    """Lazily import the optional ArangoDB implementation and bridge it to sync."""
    from parrot.knowledge.wiki.arango_sources import ArangoSourceBackend

    return AsyncSourceBackendBridge(
        ArangoSourceBackend(arango_db=options.get("arango_db"), arango_store=options.get("arango_store"))
    )


register_source_backend("sqlite", _create_sqlite_backend)
register_source_backend("json", _create_json_backend)
register_source_backend("arangodb", _create_arango_backend)
