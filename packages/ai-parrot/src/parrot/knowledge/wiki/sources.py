"""Source collection manager for the LLM Wiki feature (FEAT-260).

Implements the "Raw Sources" layer of Karpathy's 3-layer architecture.
Tracks ingested source documents in one of two backends, matching the
wiki's ``storage_backend``:

- ``"sqlite"`` (default) — the ``sources`` table of the wiki's
  single-file SQLite retrieval plane (``wiki.db`` — see
  :mod:`parrot.knowledge.wiki.store`).  A legacy ``.manifest.json``
  found on first open is migrated into the database automatically and
  renamed to ``.manifest.json.bak``.
- ``"json"`` — a plain ``.manifest.json`` file in ``sources_dir``
  (atomic tmp-file writes), used with the SQLite-free
  ``InMemoryWikiStore`` backend.

Staleness detection reuses the same mtime + SHA-1 pattern as
``SQLitePersistence.is_stale()`` in ``graphindex/persist_sqlite.py``.

The public API is synchronous (callers off-load to a thread pool via
``asyncio.to_thread``); the sqlite mode uses short-lived per-call
``sqlite3`` connections — WAL mode makes this safe alongside the async
:class:`~parrot.knowledge.wiki.store.WikiStore` connections on the same
file.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from parrot.knowledge.wiki.models import SourceManifestEntry

#: ``wiki_sources`` collection name — matches
#: ``parrot.knowledge.wiki.arango_store.SOURCES_COLLECTION``. Duplicated
#: as a literal (rather than imported) so lightweight sqlite/json
#: consumers of this module never pull in ``asyncdb``.
_ARANGO_SOURCES_COLLECTION = "wiki_sources"

#: FEAT-402 (TASK-2073) additive columns on the `sources` table:
#: name -> SQL type. All nullable so pre-FEAT-402 databases keep
#: opening cleanly; see ``_migrate_sources_columns``.
_SOURCES_DECISION_COLUMNS: dict[str, str] = {
    "destination": "TEXT",
    "decision_source": "TEXT",
    "charter_version": "TEXT",
    "composite_score": "REAL",
}

#: FEAT-451 additive columns on the `sources` table: extracted document
#: metadata. All nullable so pre-FEAT-451 databases keep opening cleanly;
#: see ``_migrate_sources_columns``. ``doc_metadata`` is JSON-encoded
#: (sqlite has no native JSON column type) — see ``_upsert``/``_row_to_entry``.
_SOURCES_DOCUMENT_COLUMNS: dict[str, str] = {
    "doc_metadata": "TEXT",
    "content_type": "TEXT",
    "loader": "TEXT",
}


class SourceCollectionManager:
    """Manages the raw-source collection for a single wiki instance.

    Attributes:
        sources_dir: Directory where raw source files live.
        backend: ``"sqlite"`` (sources table in ``wiki.db``), ``"json"``
            (``.manifest.json`` in ``sources_dir``), or ``"arangodb"``
            (``wiki_sources`` collection in a shared ArangoDB database).
        db_path: Path of the shared ``wiki.db`` file (sqlite mode).
        manifest_path: ``.manifest.json`` location (json-mode storage;
            sqlite-mode legacy migration source).
        logger: Standard Python logger.

    Example::

        mgr = SourceCollectionManager(Path("/wiki/sources"))
        entry = mgr.add_source(Path("/docs/article.md"))
        print(entry.source_id, entry.file_hash)

        if mgr.is_stale(entry.source_id):
            mgr.reingest(...)
    """

    _MANIFEST_FILENAME: str = ".manifest.json"

    def __init__(
        self,
        sources_dir: Path,
        db_path: Path | None = None,
        backend: Literal["sqlite", "json", "arangodb"] = "sqlite",
        arango_db: Any | None = None,
        arango_store: Any | None = None,
    ) -> None:
        """Initialise the manager's chosen persistence backend.

        Args:
            sources_dir: Root directory for raw source documents.
                Created automatically if it does not exist.
            db_path: Optional explicit path of the wiki database
                (sqlite mode only).  When omitted, defaults to
                ``<sources_dir>/../wiki.db`` — the same file used by
                :class:`SQLiteWikiStore`.
            backend: ``"sqlite"`` (default), ``"json"``, or
                ``"arangodb"``.
            arango_db: Already-connected ``asyncdb`` ArangoDB driver
                instance (the same connection used by
                ``ArangoDBWikiStore`` — see its ``_db`` attribute after
                ``initialize()``). One of ``arango_db``/``arango_store``
                is required when ``backend="arangodb"``.
            arango_store: An ``ArangoDBWikiStore`` instance to lazily
                ``initialize()`` (idempotent) and read ``._db`` from at
                first use, instead of requiring an already-connected
                driver at construction time. Lets callers that cannot
                ``await`` here (e.g. ``LLMWikiToolkit.__init__``, which
                is synchronous) still wire the ``arangodb`` backend
                correctly. Takes precedence over ``arango_db`` when both
                are given.

        Raises:
            ValueError: For an unknown ``backend`` value, or when
                ``backend="arangodb"`` is given without ``arango_db``
                or ``arango_store``.
        """
        if backend not in ("sqlite", "json", "arangodb"):
            raise ValueError(
                f"Unknown sources backend {backend!r} — expected 'sqlite',"
                " 'json', or 'arangodb'"
            )
        self.sources_dir: Path = Path(sources_dir)
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.backend: str = backend
        self.db_path: Path = (
            Path(db_path) if db_path else self.sources_dir.parent / "wiki.db"
        )
        self.manifest_path: Path = self.sources_dir / self._MANIFEST_FILENAME
        self.logger: logging.Logger = logging.getLogger(__name__)
        self._manifest: dict[str, SourceManifestEntry] = {}
        self._arango_db: Any | None = arango_db
        self._arango_store: Any | None = arango_store
        self._arango_loop: asyncio.AbstractEventLoop | None = None
        if backend == "arangodb":
            if arango_db is None and arango_store is None:
                raise ValueError(
                    "SourceCollectionManager(backend='arangodb') requires"
                    " either arango_db (an already-connected connection)"
                    " or arango_store (an ArangoDBWikiStore to lazily"
                    " initialize)"
                )
            # Captured so _run_async() can tell whether a later
            # asyncio.to_thread(...) call is being bridged back onto the
            # SAME loop the arango connection is bound to (see
            # _run_async's docstring) — None when constructed outside
            # any running loop (e.g. the sync CLI `status` command).
            try:
                self._arango_loop = asyncio.get_running_loop()
            except RuntimeError:
                self._arango_loop = None
        if backend == "sqlite":
            from parrot.knowledge.wiki.store import WIKI_SCHEMA_SQL

            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.executescript(WIKI_SCHEMA_SQL)
            self._migrate_sources_columns()
            self._migrate_json_manifest()
        elif backend == "arangodb":
            pass  # validated above; connection resolved lazily at first use
        else:
            self._load_manifest()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_source(self, path: Path) -> SourceManifestEntry:
        """Register a new source file in the sources table.

        Computes the SHA-1 hash and mtime of the file at registration
        time.  If the source is already tracked (by URI), the existing
        entry is refreshed with the current hash and mtime.

        Args:
            path: Absolute or relative path to the source file.

        Returns:
            The created or updated :class:`SourceManifestEntry`.

        Raises:
            FileNotFoundError: If ``path`` does not exist.
        """
        path = Path(path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {path}")

        source_uri = str(path)
        existing_id = self._find_id_by_uri(source_uri)
        source_id = existing_id or self._generate_source_id(source_uri)

        entry = SourceManifestEntry(
            source_id=source_id,
            source_uri=source_uri,
            file_hash=self._compute_hash(path),
            mtime=path.stat().st_mtime,
            ingested_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            pages_generated=[],
            status="ingested",
        )
        self._upsert(entry)
        self.logger.debug(
            "Source added: source_id=%s uri=%s hash=%s",
            source_id,
            source_uri,
            entry.file_hash,
        )
        return entry

    def list_sources(self) -> list[SourceManifestEntry]:
        """Return all tracked sources.

        Returns:
            A list of :class:`SourceManifestEntry` objects, one per
            registered source, in insertion order.
        """
        if self.backend == "json":
            return list(self._manifest.values())
        if self.backend == "arangodb":
            return self._run_async(self._async_list_sources())
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sources ORDER BY rowid"
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get_source(self, source_id: str) -> SourceManifestEntry | None:
        """Retrieve a single source entry by its ID.

        Args:
            source_id: The stable source identifier assigned at
                registration time.

        Returns:
            The :class:`SourceManifestEntry`, or ``None`` if not found.
        """
        if self.backend == "json":
            return self._manifest.get(source_id)
        if self.backend == "arangodb":
            return self._run_async(self._async_get_source(source_id))
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sources WHERE source_id = ?", (source_id,)
            ).fetchone()
        return self._row_to_entry(row) if row else None

    def is_stale(self, source_id: str) -> bool:
        """Determine whether a tracked source has changed since last ingest.

        Replicates the ``SQLitePersistence.is_stale()`` logic: a source
        is stale when its current SHA-1 hash *or* mtime differs from the
        values recorded at ingest time.

        Args:
            source_id: The stable source identifier to check.

        Returns:
            ``True`` when the source is missing from the table, the
            underlying file no longer exists, or the file content / mtime
            has changed.  ``False`` otherwise.
        """
        entry = self.get_source(source_id)
        if entry is None:
            self.logger.debug("is_stale: source_id=%s not tracked", source_id)
            return True

        path = Path(entry.source_uri)
        if not path.exists():
            self.logger.debug(
                "is_stale: source_id=%s file gone (%s)", source_id, path
            )
            return True

        current_mtime = path.stat().st_mtime
        if current_mtime != entry.mtime:
            # Fast path: mtime changed → almost certainly stale.
            # Still verify hash to guard against mtime jitter.
            current_hash = self._compute_hash(path)
            stale = current_hash != entry.file_hash
            self.logger.debug(
                "is_stale: source_id=%s mtime_changed=True hash_changed=%s",
                source_id,
                stale,
            )
            return stale

        # mtime is identical; trust it (same as SQLitePersistence pattern).
        return False

    def mark_ingested(
        self,
        source_id: str,
        pages_generated: list[str],
        status: str = "ingested",
    ) -> SourceManifestEntry | None:
        """Update the sources table after a successful ingest run.

        Args:
            source_id: The source to update.
            pages_generated: List of wiki page IDs produced by the ingest.
            status: New lifecycle status (defaults to ``"ingested"``).

        Returns:
            The updated :class:`SourceManifestEntry`, or ``None`` if
            ``source_id`` is not tracked.
        """
        entry = self.get_source(source_id)
        if entry is None:
            self.logger.warning(
                "mark_ingested: source_id=%s not found", source_id
            )
            return None

        # Refresh hash and mtime in case the file was re-written during ingest.
        path = Path(entry.source_uri)
        if path.exists():
            entry = SourceManifestEntry(
                source_id=entry.source_id,
                source_uri=entry.source_uri,
                file_hash=self._compute_hash(path),
                mtime=path.stat().st_mtime,
                ingested_at=entry.ingested_at,
                pages_generated=pages_generated,
                status=status,
            )
            self._upsert(entry)
        return entry

    def record_decision(
        self,
        path: Path,
        *,
        destination: str,
        decision_source: str | None = None,
        charter_version: str | None = None,
        composite_score: float | None = None,
        pages_generated: list[str] | None = None,
        status: str | None = None,
    ) -> SourceManifestEntry:
        """Register or update a source with its supervised-ingestion decision.

        Sibling to :meth:`mark_ingested` (FEAT-402, TASK-2073): handles
        ALL three triage destinations, including ``"discard"`` — a
        rejected document may never have been registered via
        :meth:`add_source` at all (the triage router evaluates raw
        scanned files, not already-tracked sources), so this method
        creates a new entry when the URI isn't tracked yet rather than
        requiring one to already exist. Per spec §2: rejected docs are
        recorded with ``status="rejected"`` and are never ingested (no
        pages).

        Args:
            path: Path to the source document.
            destination: Triage destination — ``"wiki"``, ``"archive"``,
                or ``"discard"``.
            decision_source: Who/what made the decision — ``"heuristic"``,
                ``"model"``, ``"human"``, or ``"auto"``.
            charter_version: Editorial charter version the decision was
                made against (audit/reproducibility).
            composite_score: The weighted composite triage score.
            pages_generated: Wiki page IDs produced, if any. Left as the
                existing value (or empty) when not given — rejected /
                archived-without-pages documents pass ``None`` or ``[]``.
            status: Lifecycle status override. Defaults to ``"rejected"``
                when ``destination == "discard"``, else ``"ingested"``.

        Returns:
            The created or updated :class:`SourceManifestEntry`.
        """
        # Resolve to an absolute path, matching add_source's convention,
        # so find_by_uri correctly matches sources already tracked via
        # add_source (and dedupes consistently for future lookups).
        path = Path(path).resolve()
        source_uri = str(path)
        existing_id = self.find_by_uri(source_uri)
        existing = self.get_source(existing_id) if existing_id else None

        if path.exists():
            file_hash = self._compute_hash(path)
            mtime = path.stat().st_mtime
        else:
            file_hash = existing.file_hash if existing else ""
            mtime = existing.mtime if existing else 0.0

        resolved_status = status or (
            "rejected" if destination == "discard" else "ingested"
        )

        entry = SourceManifestEntry(
            source_id=(
                existing.source_id
                if existing
                else self._generate_source_id(source_uri)
            ),
            source_uri=source_uri,
            file_hash=file_hash,
            mtime=mtime,
            ingested_at=(
                existing.ingested_at
                if existing
                else datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            ),
            pages_generated=(
                pages_generated
                if pages_generated is not None
                else (existing.pages_generated if existing else [])
            ),
            status=resolved_status,
            destination=destination,
            decision_source=decision_source,
            charter_version=charter_version,
            composite_score=composite_score,
        )
        self._upsert(entry)
        self.logger.debug(
            "Recorded triage decision: source_uri=%s destination=%s"
            " decision_source=%s status=%s",
            source_uri,
            destination,
            decision_source,
            resolved_status,
        )
        return entry

    def record_document_metadata(
        self,
        source_id: str,
        *,
        doc_metadata: dict[str, Any] | None,
        content_type: str | None,
        loader: str | None,
    ) -> None:
        """Persist FEAT-451 extracted document metadata for a tracked source.

        Sibling to :meth:`mark_ingested`/:meth:`record_decision`: updates
        the descriptive document-metadata columns on an already-tracked
        source. Unlike :meth:`record_decision`, this method never creates
        a new entry — document metadata is only meaningful once the
        source itself is tracked (e.g. via :meth:`add_source` or
        :meth:`record_decision`).

        Args:
            source_id: The tracked source to update.
            doc_metadata: Extracted ``DocumentMetadata`` as a dict, or
                ``None``.
            content_type: MIME type of the source document, or ``None``.
            loader: Name of the loader used to extract the document, or
                ``None``.
        """
        entry = self.get_source(source_id)
        if entry is None:
            self.logger.warning(
                "record_document_metadata: source_id=%s not found", source_id
            )
            return

        updated = entry.model_copy(
            update={
                "doc_metadata": doc_metadata,
                "content_type": content_type,
                "loader": loader,
            }
        )
        self._upsert(updated)
        self.logger.debug(
            "Recorded document metadata: source_id=%s content_type=%s loader=%s",
            source_id,
            content_type,
            loader,
        )

    def remove_source(self, source_id: str) -> bool:
        """Remove a source from the sources table.

        Args:
            source_id: The stable source identifier to remove.

        Returns:
            ``True`` if the entry existed and was removed; ``False`` if
            ``source_id`` was not present.
        """
        if self.backend == "json":
            if source_id not in self._manifest:
                return False
            del self._manifest[source_id]
            self._save_manifest()
            self.logger.debug("Source removed: source_id=%s", source_id)
            return True
        if self.backend == "arangodb":
            removed = self._run_async(self._async_remove_source(source_id))
            if removed:
                self.logger.debug("Source removed: source_id=%s", source_id)
            return removed
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM sources WHERE source_id = ?", (source_id,)
            )
        removed = cur.rowcount > 0
        if removed:
            self.logger.debug("Source removed: source_id=%s", source_id)
        return removed

    def find_by_uri(self, source_uri: str) -> str | None:
        """Look up an existing source ID by URI (public API).

        Args:
            source_uri: The URI to search for.

        Returns:
            The matching source_id, or ``None`` if not tracked.
        """
        return self._find_id_by_uri(source_uri)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a short-lived connection to the shared wiki database.

        Per-call connections keep the sync API thread-safe when invoked
        via ``asyncio.to_thread`` (sqlite3 connections have thread
        affinity); WAL mode allows concurrency with async WikiStore
        connections on the same file.
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _upsert(self, entry: SourceManifestEntry) -> None:
        """Insert or replace one source entry in the active backend."""
        if self.backend == "json":
            self._manifest[entry.source_id] = entry
            self._save_manifest()
            return
        if self.backend == "arangodb":
            self._run_async(self._async_upsert(entry))
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sources"
                " (source_id, source_uri, file_hash, mtime, ingested_at,"
                "  pages_generated, status, destination, decision_source,"
                "  charter_version, composite_score, doc_metadata,"
                "  content_type, loader)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
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
                "  loader=excluded.loader",
                (
                    entry.source_id,
                    entry.source_uri,
                    entry.file_hash,
                    entry.mtime,
                    entry.ingested_at,
                    json.dumps(entry.pages_generated),
                    entry.status,
                    entry.destination,
                    entry.decision_source,
                    entry.charter_version,
                    entry.composite_score,
                    (
                        json.dumps(entry.doc_metadata)
                        if entry.doc_metadata is not None
                        else None
                    ),
                    entry.content_type,
                    entry.loader,
                ),
            )

    @staticmethod
    def _optional_column(row: sqlite3.Row, name: str) -> Any:
        """Read an optional ``sources`` column, tolerating rows from a
        pre-FEAT-402 schema where the column does not exist yet.

        ``SourceCollectionManager.__init__`` always runs the additive
        column migration before any query, but this stays defensive in
        case a row is ever read via a connection that bypassed that path.

        Args:
            row: The ``sqlite3.Row`` to read from.
            name: The column name to look up.

        Returns:
            The column value, or ``None`` if the column is absent.
        """
        try:
            return row[name]
        except (IndexError, KeyError):
            return None

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> SourceManifestEntry:
        """Convert a sources row into a :class:`SourceManifestEntry`."""
        try:
            pages = json.loads(row["pages_generated"] or "[]")
        except (json.JSONDecodeError, TypeError):
            pages = []
        raw_doc_metadata = SourceCollectionManager._optional_column(
            row, "doc_metadata"
        )
        try:
            doc_metadata = (
                json.loads(raw_doc_metadata) if raw_doc_metadata is not None else None
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            # A corrupt cell must never make the whole manifest unreadable.
            doc_metadata = None
        return SourceManifestEntry(
            source_id=row["source_id"],
            source_uri=row["source_uri"],
            file_hash=row["file_hash"],
            mtime=row["mtime"],
            ingested_at=row["ingested_at"],
            pages_generated=pages,
            status=row["status"],
            destination=SourceCollectionManager._optional_column(row, "destination"),
            decision_source=SourceCollectionManager._optional_column(
                row, "decision_source"
            ),
            charter_version=SourceCollectionManager._optional_column(
                row, "charter_version"
            ),
            composite_score=SourceCollectionManager._optional_column(
                row, "composite_score"
            ),
            doc_metadata=doc_metadata,
            content_type=SourceCollectionManager._optional_column(
                row, "content_type"
            ),
            loader=SourceCollectionManager._optional_column(row, "loader"),
        )

    def _compute_hash(self, path: Path) -> str:
        """Compute the SHA-1 hex digest of a file.

        Reads in 8 KiB chunks to avoid loading large files into memory.

        Args:
            path: Path to the file to hash.

        Returns:
            Lowercase hexadecimal SHA-1 digest string.
        """
        h = hashlib.sha1()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _generate_source_id(self, source_uri: str) -> str:
        """Generate a deterministic source ID from the URI.

        Uses a UUID5 (SHA-1 namespace) so that the same URI always yields
        the same ID regardless of when it was first added.

        Args:
            source_uri: The absolute source URI string.

        Returns:
            A compact ``src-<hex>`` string.
        """
        uid = uuid.uuid5(uuid.NAMESPACE_URL, source_uri)
        return f"src-{uid.hex[:12]}"

    def _find_id_by_uri(self, source_uri: str) -> str | None:
        """Look up an existing source ID by URI (internal implementation)."""
        if self.backend == "json":
            for sid, entry in self._manifest.items():
                if entry.source_uri == source_uri:
                    return sid
            return None
        if self.backend == "arangodb":
            return self._run_async(self._async_find_id_by_uri(source_uri))
        with self._connect() as conn:
            row = conn.execute(
                "SELECT source_id FROM sources WHERE source_uri = ?",
                (source_uri,),
            ).fetchone()
        return row["source_id"] if row else None

    # ------------------------------------------------------------------
    # ArangoDB-backend persistence (storage_backend="arangodb" wikis)
    # ------------------------------------------------------------------

    def _run_async(self, coro: Any) -> Any:
        """Bridge an async ArangoDB call from this manager's sync API.

        The ``arangodb`` backend's connection (``asyncdb``/``arangoasync``,
        backed by ``aiohttp``) is bound to the event loop it was created
        on — ``aiohttp``'s connector captures ``asyncio.get_running_loop()``
        at construction and cannot be driven from a different loop.  A
        naive bridge that always does ``asyncio.run(coro)`` (spinning up
        a brand-new loop whenever one isn't already running in the
        *current* thread — which is exactly the case inside an
        ``asyncio.to_thread(...)`` worker) would silently reuse the
        shared connection from that new, unrelated loop.

        So when this manager was constructed while a loop was already
        running (``self._arango_loop`` is set — the CLI's ``build``/
        ``upsert`` pipelines, which then call these sync methods via
        ``asyncio.to_thread(...)``), the coroutine is instead scheduled
        back onto *that* loop via ``run_coroutine_threadsafe`` — safe
        because ``asyncio.to_thread`` suspends the caller without
        blocking the loop, leaving it free to run the rescheduled
        coroutine concurrently. Calling a sync method directly from
        *that same* loop's own thread (no ``to_thread`` offload) would
        deadlock waiting on itself, so that combination raises instead
        of hanging.

        Outside any captured loop (e.g. the sync ``status`` command, or
        a mocked/no-op test double), this falls back to a plain
        ``asyncio.run(coro)`` — or, if some other unrelated loop happens
        to be running in the current thread, a dedicated thread's own
        fresh loop (safe there since ``self._arango_db``/``_arango_store``
        was never bound to that unrelated loop in the first place).

        Args:
            coro: The coroutine to run to completion.

        Returns:
            The coroutine's result.
        """
        if self._arango_loop is not None:
            try:
                current = asyncio.get_running_loop()
            except RuntimeError:
                current = None
            if current is self._arango_loop:
                coro.close()
                raise RuntimeError(
                    "SourceCollectionManager(backend='arangodb') sync"
                    " methods must be invoked via asyncio.to_thread(...)"
                    " when called from the same event loop the arango"
                    " connection was initialized on (calling them"
                    " directly here would deadlock)."
                )
            if current is None:
                return asyncio.run_coroutine_threadsafe(
                    coro, self._arango_loop
                ).result()

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()

    async def _resolve_arango_db(self) -> Any:
        """Return the connected ArangoDB driver for this manager's backend.

        When constructed with ``arango_store`` rather than an already-
        connected ``arango_db``, this lazily (and idempotently) connects
        it on first use — lets synchronous constructors (e.g.
        ``LLMWikiToolkit.__init__``) wire the backend without needing to
        ``await`` anything themselves.
        """
        if self._arango_store is not None:
            await self._arango_store.initialize()
            return self._arango_store._db
        return self._arango_db

    async def _arango_query(
        self, aql: str, bind_vars: dict[str, Any]
    ) -> list[Any]:
        """Run a read AQL query, treating an empty result as ``[]``.

        Same ``NoDataFound``-as-empty-result handling as
        :meth:`ArangoDBWikiStore._query` — the underlying ``asyncdb``
        driver surfaces a zero-row cursor as a non-``None`` ``error``
        string rather than an empty list.
        """
        db = await self._resolve_arango_db()
        result, error = await db.query(aql, bind_vars=bind_vars)
        if error:
            if "no data found" in str(error).lower():
                return []
            raise RuntimeError(f"ArangoDB query failed: {error}")
        return result or []

    async def _arango_execute(
        self, aql: str, bind_vars: dict[str, Any]
    ) -> list[Any]:
        """Run a write AQL statement (UPSERT/UPDATE/REMOVE)."""
        db = await self._resolve_arango_db()
        result, error = await db.execute(aql, bind_vars=bind_vars)
        if error:
            raise RuntimeError(f"ArangoDB execute failed: {error}")
        return result or []

    @staticmethod
    def _doc_to_entry(doc: dict[str, Any]) -> SourceManifestEntry:
        """Convert a ``wiki_sources`` document into a manifest entry."""
        return SourceManifestEntry(
            source_id=doc["source_id"],
            source_uri=doc["source_uri"],
            file_hash=doc["file_hash"],
            mtime=doc["mtime"],
            ingested_at=doc["ingested_at"],
            pages_generated=doc.get("pages_generated") or [],
            status=doc.get("status", "ingested"),
            doc_metadata=doc.get("doc_metadata"),
            content_type=doc.get("content_type"),
            loader=doc.get("loader"),
        )

    async def _async_upsert(self, entry: SourceManifestEntry) -> None:
        """Insert or update one source entry in ``wiki_sources`` via AQL UPSERT."""
        doc = {
            "_key": entry.source_id,
            "source_id": entry.source_id,
            "source_uri": entry.source_uri,
            "file_hash": entry.file_hash,
            "mtime": entry.mtime,
            "ingested_at": entry.ingested_at,
            "pages_generated": entry.pages_generated,
            "status": entry.status,
            "doc_metadata": entry.doc_metadata,
            "content_type": entry.content_type,
            "loader": entry.loader,
        }
        await self._arango_execute(
            "UPSERT {_key: @key} INSERT @doc UPDATE @doc IN @@collection",
            {
                "key": entry.source_id,
                "doc": doc,
                "@collection": _ARANGO_SOURCES_COLLECTION,
            },
        )

    async def _async_list_sources(self) -> list[SourceManifestEntry]:
        """Return every tracked source from ``wiki_sources``."""
        rows = await self._arango_query(
            "FOR doc IN @@collection RETURN doc",
            {"@collection": _ARANGO_SOURCES_COLLECTION},
        )
        return [self._doc_to_entry(row) for row in rows]

    async def _async_get_source(
        self, source_id: str
    ) -> SourceManifestEntry | None:
        """Fetch a single source document by its ``_key``."""
        rows = await self._arango_query(
            "FOR doc IN @@collection FILTER doc._key == @key LIMIT 1 RETURN doc",
            {"@collection": _ARANGO_SOURCES_COLLECTION, "key": source_id},
        )
        return self._doc_to_entry(rows[0]) if rows else None

    async def _async_remove_source(self, source_id: str) -> bool:
        """Delete a source document; ``True`` when a row was removed."""
        rows = await self._arango_query(
            "FOR doc IN @@collection FILTER doc._key == @key"
            " REMOVE doc IN @@collection RETURN OLD",
            {"@collection": _ARANGO_SOURCES_COLLECTION, "key": source_id},
        )
        return bool(rows)

    async def _async_find_id_by_uri(self, source_uri: str) -> str | None:
        """Look up an existing source ID by URI."""
        rows = await self._arango_query(
            "FOR doc IN @@collection FILTER doc.source_uri == @uri"
            " LIMIT 1 RETURN doc.source_id",
            {"@collection": _ARANGO_SOURCES_COLLECTION, "uri": source_uri},
        )
        return rows[0] if rows else None

    def _migrate_sources_columns(self) -> None:
        """Additively add the FEAT-402/FEAT-451 columns to ``sources``.

        Idempotent — guarded on ``PRAGMA table_info(sources)`` — and
        additive only, never rewriting or dropping existing rows/columns,
        so pre-FEAT-402 and pre-FEAT-451 databases keep opening cleanly.
        Follows the :meth:`_migrate_json_manifest` compatibility precedent
        (existing data is never touched; only missing structure is added).
        """
        with self._connect() as conn:
            existing = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(sources)").fetchall()
            }
            for column_map in (_SOURCES_DECISION_COLUMNS, _SOURCES_DOCUMENT_COLUMNS):
                for name, col_type in column_map.items():
                    if name in existing:
                        continue
                    conn.execute(f"ALTER TABLE sources ADD COLUMN {name} {col_type}")
                    self.logger.debug(
                        "Migrated sources table: added column %s (%s)", name, col_type
                    )

    def _migrate_json_manifest(self) -> None:
        """One-time migration of a legacy ``.manifest.json`` into SQLite.

        Existing rows win — a JSON entry is only imported when its
        ``source_id`` is not already in the table.  The legacy file is
        renamed to ``.manifest.json.bak`` afterwards so migration never
        repeats (and the original data is preserved).
        """
        if not self.manifest_path.exists():
            return
        try:
            raw: dict[str, Any] = json.loads(
                self.manifest_path.read_text(encoding="utf-8")
            )
            imported = 0
            for sid, data in raw.items():
                entry = SourceManifestEntry(**data)
                if self.get_source(sid) is None:
                    self._upsert(entry)
                    imported += 1
            self.manifest_path.rename(
                self.manifest_path.with_suffix(".json.bak")
            )
            self.logger.info(
                "Migrated %d legacy manifest entrie(s) from %s into %s",
                imported,
                self.manifest_path,
                self.db_path,
            )
        except (json.JSONDecodeError, KeyError, ValueError, OSError) as exc:
            self.logger.warning(
                "Could not migrate legacy manifest at %s: %s",
                self.manifest_path,
                exc,
            )

    # ------------------------------------------------------------------
    # JSON-backend persistence (storage_backend="memory" wikis)
    # ------------------------------------------------------------------

    def _load_manifest(self) -> None:
        """Load the JSON manifest from disk into ``self._manifest``.

        Silently initialises an empty manifest when the file does not
        exist or contains invalid JSON.
        """
        if not self.manifest_path.exists():
            self.logger.debug(
                "No existing manifest at %s; starting fresh", self.manifest_path
            )
            return
        try:
            raw: dict = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            self._manifest = {
                sid: SourceManifestEntry(**data) for sid, data in raw.items()
            }
            self.logger.debug(
                "Loaded manifest with %d source(s) from %s",
                len(self._manifest),
                self.manifest_path,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            self.logger.warning(
                "Could not parse manifest at %s: %s — starting fresh",
                self.manifest_path,
                exc,
            )
            self._manifest = {}

    def _save_manifest(self) -> None:
        """Persist the in-memory manifest to the JSON file.

        Serialises each :class:`SourceManifestEntry` via
        ``model_dump()``.  The file is written atomically via a
        temporary sibling to avoid partial writes.
        """
        data = {
            sid: entry.model_dump() for sid, entry in self._manifest.items()
        }
        tmp_path = self.manifest_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
        tmp_path.replace(self.manifest_path)
        self.logger.debug(
            "Saved manifest with %d source(s) to %s",
            len(data),
            self.manifest_path,
        )


def format_decision_log_details(entry: SourceManifestEntry) -> str:
    """Format a WikiBookkeeper log line for a supervised-ingestion decision.

    FEAT-402 (TASK-2073): pairs with :meth:`SourceCollectionManager.
    record_decision`. Callers pass the formatted string as the
    ``details`` argument to ``WikiBookkeeper.log_operation(wiki_dir,
    operation, details)``, choosing ``operation`` from
    ``"TRIAGE"``/``"ADMIT"``/``"ARCHIVE"``/``"DISCARD"`` — free-string
    tags, no enum (see ``bookkeeper.py`` module docstring). This helper
    only formats the details line; it does not call ``log_operation``
    itself, since the caller (TASK-2074's orchestrator wiring) owns the
    ``wiki_dir`` and ``WikiBookkeeper`` instance.

    Args:
        entry: The source manifest entry with the recorded decision
            (typically the return value of ``record_decision``).

    Returns:
        A single-line, human-readable details string: source URI,
        composite score, decision source, and charter version.
    """
    composite = (
        f"{entry.composite_score:.4f}"
        if entry.composite_score is not None
        else "n/a"
    )
    return (
        f"source: {entry.source_uri}, composite: {composite}, "
        f"decision_source: {entry.decision_source or 'n/a'}, "
        f"charter_version: {entry.charter_version or 'n/a'}"
    )
