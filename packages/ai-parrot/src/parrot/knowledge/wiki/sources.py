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

import hashlib
import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from parrot.knowledge.wiki.models import SourceManifestEntry
from parrot.knowledge.wiki.sources_backend import create_source_backend

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

#: FEAT-472 additive column on the `sources` table: an immutable external
#: identity (``"<source>:<id>"``, e.g. ``"fireflies:abc123"``) that lets a
#: row be found without depending on its (mutable) path/title. Nullable so
#: pre-FEAT-472 databases keep opening cleanly; see
#: ``_migrate_sources_columns``, which also (idempotently) creates
#: ``idx_sources_external_id`` for pre-existing databases.
_SOURCES_EXTERNAL_COLUMNS: dict[str, str] = {
    "external_id": "TEXT",
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

    External identity convention (FEAT-472): a source may optionally carry
    an ``external_id`` — an immutable identity in ``"<source>:<id>"`` form
    (e.g. ``"fireflies:abc123"`` for a Fireflies transcript id), distinct
    from ``source_id``/``source_uri`` which are derived from the file's
    path and change if the file is renamed or moved. Any future external
    source integration (Jira, audio notes, etc.) that needs
    identity-not-path dedup should adopt the same ``"<source>:<id>"``
    convention rather than inventing a parallel registry. See
    :meth:`find_by_external_id`, :meth:`find_entries_by_external_ids`,
    :meth:`list_by_external_prefix`, and :meth:`set_external_id`.

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
        backend: str = "sqlite",
        arango_db: Any | None = None,
        arango_store: Any | None = None,
        *,
        busy_timeout: float = 15.0,
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
        self.sources_dir: Path = Path(sources_dir)
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.backend: str = backend
        self.db_path: Path = Path(db_path) if db_path else self.sources_dir.parent / "wiki.db"
        self.manifest_path: Path = self.sources_dir / self._MANIFEST_FILENAME
        self.logger: logging.Logger = logging.getLogger(__name__)
        self.busy_timeout: float = busy_timeout
        self._manifest: dict[str, SourceManifestEntry] = {}
        self._backend = create_source_backend(
            backend,
            manager=self,
            arango_db=arango_db,
            arango_store=arango_store,
        )
        if backend in {"sqlite"}:
            from parrot.knowledge.wiki.store import WIKI_SCHEMA_SQL

            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._write("init_schema") as conn:
                conn.executescript(WIKI_SCHEMA_SQL)
            self._migrate_sources_columns()
            self._migrate_json_manifest()
        elif backend == "json":
            self._load_manifest()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_source(self, path: Path, *, external_id: str | None = None) -> SourceManifestEntry:
        """Register a new source file in the sources table.

        Computes the SHA-1 hash and mtime of the file at registration
        time.  If the source is already tracked (by URI), the existing
        entry is refreshed with the current hash and mtime.

        Args:
            path: Absolute or relative path to the source file.
            external_id: FEAT-472 immutable external identity in
                ``"<source>:<id>"`` form (e.g. ``"fireflies:abc123"``).
                ``None`` (default) leaves the source without one.

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
        existing = self.get_source(existing_id) if existing_id else None
        source_id = existing_id or self._generate_source_id(source_uri)

        # FEAT-472 bugfix: re-adding an ALREADY-tracked URI (e.g. the wiki's
        # own incremental ingest loader calling add_source on a file
        # MeetingRegistry already registered for id-keyed dedup) used to
        # silently wipe every FEAT-402/451/472 column back to its default
        # by reconstructing the entry from only the seven fields below —
        # the same class of bug TASK-2553 fixed on mark_ingested/
        # mark_ingested_many. Preserve them here too; only external_id can
        # be explicitly overridden by the caller.
        entry = SourceManifestEntry(
            source_id=source_id,
            source_uri=source_uri,
            file_hash=self._compute_hash(path),
            mtime=path.stat().st_mtime,
            ingested_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            pages_generated=[],
            status="ingested",
            external_id=(external_id if external_id is not None else (existing.external_id if existing else None)),
            destination=existing.destination if existing else None,
            decision_source=existing.decision_source if existing else None,
            charter_version=existing.charter_version if existing else None,
            composite_score=existing.composite_score if existing else None,
            doc_metadata=existing.doc_metadata if existing else None,
            content_type=existing.content_type if existing else None,
            loader=existing.loader if existing else None,
        )
        self._upsert(entry)
        self.logger.debug(
            "Source added: source_id=%s uri=%s hash=%s",
            source_id,
            source_uri,
            entry.file_hash,
        )
        return entry

    # ------------------------------------------------------------------
    # Bulk manifest operations
    #
    # The per-file API above costs one round trip per call, which is
    # invisible on a local sqlite/json manifest and dominant on a
    # server-hosted one: registering a new file used to take ~5 round
    # trips (find_by_uri, add_source's own lookup + write, mark_ingested's
    # read + write), measured at ~0.5s/file against a remote ArangoDB —
    # ~80 minutes for a 9k-file corpus. These collapse a whole scan into
    # a handful of statements. Semantics are unchanged: the same hashes,
    # the same staleness rule, the same rows.
    # ------------------------------------------------------------------

    def find_entries_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]:
        """Look up many sources by URI in as few statements as possible.

        Args:
            uris: Absolute source URIs (``str(path.resolve())``).

        Returns:
            Mapping of ``source_uri`` -> entry, containing only the URIs
            that are actually tracked.
        """
        return self._backend.find_by_uris(uris)

    def find_entries_by_ids(self, source_ids: list[str]) -> dict[str, SourceManifestEntry]:
        """Fetch many sources by id in as few statements as possible.

        Args:
            source_ids: Stable source identifiers.

        Returns:
            Mapping of ``source_id`` -> entry, for the ids that exist.
        """
        return self._backend.find_by_ids(source_ids)

    def add_sources(
        self,
        paths: list[Path],
        known: dict[str, SourceManifestEntry] | None = None,
    ) -> list[SourceManifestEntry]:
        """Register (or refresh) many source files in one write.

        The batch equivalent of :meth:`add_source`: hashes and stats every
        file locally, resolves existing ids with a single lookup, then
        writes every row in one statement.

        One deliberate difference from :meth:`add_source`: an
        already-tracked source keeps its original ``ingested_at`` and
        ``pages_generated`` instead of having them reset. The build
        pipeline registers *changed* files through here (the single-source
        path only ever saw brand-new ones), and resetting those fields
        would both re-date every re-ingested file and drop its page list
        if the run failed before ``mark_ingested_many``.

        Args:
            paths: Source file paths; each is resolved before use.
            known: Entries already read for these URIs (see
                :meth:`find_entries_by_uris`). Pass it when the caller has
                just read them to skip this method's own id-resolution
                read — one fewer round trip on a server-hosted manifest.

        Returns:
            The created/updated entries, in the order given.

        Raises:
            FileNotFoundError: If any path does not exist — same contract
                as :meth:`add_source`, reported for the whole batch.
        """
        if not paths:
            return []
        resolved = [Path(path).resolve() for path in paths]
        missing = [str(path) for path in resolved if not path.exists()]
        if missing:
            raise FileNotFoundError(f"Source file(s) not found: {', '.join(missing[:5])}")

        existing = known if known is not None else self.find_entries_by_uris([str(path) for path in resolved])
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        entries: list[SourceManifestEntry] = []
        for path in resolved:
            source_uri = str(path)
            prior = existing.get(source_uri)
            file_hash = self._compute_hash(path)
            mtime = path.stat().st_mtime
            if prior is not None:
                # FEAT-472 bugfix (same class as add_source/mark_ingested):
                # model_copy preserves external_id/doc_metadata/destination/
                # etc. instead of reconstructing from only six fields, which
                # used to silently wipe them on every re-registration of an
                # already-tracked, changed file.
                entries.append(prior.model_copy(update={"file_hash": file_hash, "mtime": mtime}))
            else:
                entries.append(
                    SourceManifestEntry(
                        source_id=self._generate_source_id(source_uri),
                        source_uri=source_uri,
                        file_hash=file_hash,
                        mtime=mtime,
                        ingested_at=now,
                        pages_generated=[],
                        status="ingested",
                    )
                )
        self._upsert_many(entries)
        self.logger.debug("add_sources: registered %d source(s)", len(entries))
        return entries

    def mark_ingested_many(
        self,
        pages_by_source: dict[str, list[str]],
        status: str = "ingested",
    ) -> None:
        """Record ingest results for many sources in one write.

        The batch equivalent of :meth:`mark_ingested`, including its
        re-hash of each file (a file rewritten *during* the ingest run
        must not be left looking fresh). Untracked ids are skipped with a
        warning, exactly as the single-source version does.

        Args:
            pages_by_source: ``source_id`` -> page ids produced for it.
            status: New lifecycle status for every source in the batch.
        """
        if not pages_by_source:
            return
        entries = self.find_entries_by_ids(list(pages_by_source))
        updated: list[SourceManifestEntry] = []
        for source_id, pages in pages_by_source.items():
            entry = entries.get(source_id)
            if entry is None:
                self.logger.warning("mark_ingested: source_id=%s not found", source_id)
                continue
            path = Path(entry.source_uri)
            if not path.exists():
                continue
            # FEAT-472: model_copy(update=...) — see mark_ingested's
            # docstring note; the batch twin had the same field-dropping bug.
            updated.append(
                entry.model_copy(
                    update={
                        "file_hash": self._compute_hash(path),
                        "mtime": path.stat().st_mtime,
                        "pages_generated": pages,
                        "status": status,
                    }
                )
            )
        if updated:
            self._upsert_many(updated)

    def list_sources(self) -> list[SourceManifestEntry]:
        """Return all tracked sources.

        Returns:
            A list of :class:`SourceManifestEntry` objects, one per
            registered source, in insertion order.
        """
        return self._backend.list_sources()

    def get_source(self, source_id: str) -> SourceManifestEntry | None:
        """Retrieve a single source entry by its ID.

        Args:
            source_id: The stable source identifier assigned at
                registration time.

        Returns:
            The :class:`SourceManifestEntry`, or ``None`` if not found.
        """
        return self._backend.get_source(source_id)

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
        return self.entry_is_stale(entry)

    def entry_is_stale(self, entry: SourceManifestEntry) -> bool:
        """Staleness of an ALREADY-FETCHED manifest entry — no DB read.

        The comparison half of :meth:`is_stale`, split out so a caller
        that has just read a batch of entries (see
        :meth:`find_entries_by_uris`) can classify them without one
        round trip per file. :meth:`is_stale` is this plus the read, so
        the rule lives in exactly one place.

        Args:
            entry: The manifest entry to compare against its file.

        Returns:
            ``True`` when the underlying file is gone or its content /
            mtime has changed since the entry was recorded.
        """
        path = Path(entry.source_uri)
        if not path.exists():
            self.logger.debug("is_stale: source_id=%s file gone (%s)", entry.source_id, path)
            return True

        current_mtime = path.stat().st_mtime
        if current_mtime != entry.mtime:
            # Fast path: mtime changed → almost certainly stale.
            # Still verify hash to guard against mtime jitter.
            current_hash = self._compute_hash(path)
            stale = current_hash != entry.file_hash
            self.logger.debug(
                "is_stale: source_id=%s mtime_changed=True hash_changed=%s",
                entry.source_id,
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
            self.logger.warning("mark_ingested: source_id=%s not found", source_id)
            return None

        # Refresh hash and mtime in case the file was re-written during ingest.
        # FEAT-472: model_copy(update=...) instead of reconstructing a fresh
        # SourceManifestEntry from scratch — the latter silently dropped
        # every FEAT-402/451/472 field (destination, doc_metadata,
        # external_id, ...) that isn't one of the seven positional ones
        # below on every re-ingest.
        path = Path(entry.source_uri)
        if path.exists():
            entry = entry.model_copy(
                update={
                    "file_hash": self._compute_hash(path),
                    "mtime": path.stat().st_mtime,
                    "pages_generated": pages_generated,
                    "status": status,
                }
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
        external_id: str | None = None,
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
            external_id: FEAT-472 immutable external identity in
                ``"<source>:<id>"`` form. ``None`` (default) leaves any
                existing value on the row unchanged when the source is
                already tracked, or leaves it unset for a new source.

        Returns:
            The created or updated :class:`SourceManifestEntry`.
        """
        # Resolve to an absolute path, matching add_source's convention,
        # so find_by_uri correctly matches sources already tracked via
        # add_source (and dedupes consistently for future lookups).
        #
        # FEAT-451 bug fix (revealed by TASK-2358's test_ingest_url):
        # Path(<url>).resolve() mangles a URL — collapses "//" to "/" and
        # resolves it against the process cwd as if it were relative, so
        # a URL source's manifest identity would never match the
        # DocumentAcquirer/ManifestDocEntry's own uri. A URL source_uri
        # is kept verbatim; only local paths are resolved.
        if urlparse(str(path)).scheme in ("http", "https"):
            source_uri = str(path)
        else:
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

        resolved_status = status or ("rejected" if destination == "discard" else "ingested")

        entry = SourceManifestEntry(
            source_id=(existing.source_id if existing else self._generate_source_id(source_uri)),
            source_uri=source_uri,
            file_hash=file_hash,
            mtime=mtime,
            ingested_at=(existing.ingested_at if existing else datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")),
            pages_generated=(
                pages_generated if pages_generated is not None else (existing.pages_generated if existing else [])
            ),
            status=resolved_status,
            destination=destination,
            decision_source=decision_source,
            charter_version=charter_version,
            composite_score=composite_score,
            external_id=(external_id if external_id is not None else (existing.external_id if existing else None)),
        )
        self._upsert(entry)
        self.logger.debug(
            "Recorded triage decision: source_uri=%s destination=%s" " decision_source=%s status=%s",
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
            self.logger.warning("record_document_metadata: source_id=%s not found", source_id)
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
        removed = self._backend.remove_source(source_id)
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
    # FEAT-472: external-id readers/writers
    # ------------------------------------------------------------------

    def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None:
        """Look up a source by its immutable external identity.

        Args:
            external_id: ``"<source>:<id>"`` value to search for (e.g.
                ``"fireflies:abc123"``).

        Returns:
            The matching :class:`SourceManifestEntry`, or ``None`` if no
            row carries that ``external_id``.
        """
        return self._backend.find_by_external_id(external_id)

    def find_entries_by_external_ids(self, external_ids: list[str]) -> dict[str, SourceManifestEntry]:
        """Look up many sources by external id in as few statements as possible.

        Args:
            external_ids: ``"<source>:<id>"`` values to search for.

        Returns:
            Mapping of ``external_id`` -> entry, containing only the ids
            that are actually tracked.
        """
        return self._backend.find_by_external_ids(external_ids)

    def list_by_external_prefix(self, prefix: str) -> list[SourceManifestEntry]:
        """List every source whose ``external_id`` starts with ``prefix``.

        Args:
            prefix: External-id prefix to match, e.g. ``"fireflies:"``.

        Returns:
            Matching entries; rows with a ``None`` external_id or a
            different prefix are excluded.
        """
        return self._backend.list_by_external_prefix(prefix)

    def set_external_id(self, source_id: str, external_id: str | None) -> SourceManifestEntry | None:
        """Set (or clear) the external identity of an already-tracked source.

        Args:
            source_id: The tracked source to update.
            external_id: New ``"<source>:<id>"`` value, or ``None`` to
                clear it.

        Returns:
            The updated :class:`SourceManifestEntry`, or ``None`` if
            ``source_id`` is not tracked.
        """
        entry = self.get_source(source_id)
        if entry is None:
            self.logger.warning("set_external_id: source_id=%s not found", source_id)
            return None
        updated = entry.model_copy(update={"external_id": external_id})
        self._upsert(updated)
        self.logger.debug("set_external_id: source_id=%s external_id=%s", source_id, external_id)
        return updated

    def update_source_uri(self, source_id: str, new_uri: Path | str) -> SourceManifestEntry | None:
        """Repoint a tracked source at a new path, keeping its ``source_id``.

        Used by repair flows that move/rename the underlying file: the
        row's identity (``source_id``, and any ``external_id``) survives
        the move; only ``source_uri``/``file_hash``/``mtime`` change.

        Args:
            source_id: The tracked source to update.
            new_uri: The file's new location. Must exist.

        Returns:
            The updated :class:`SourceManifestEntry`, or ``None`` if
            ``source_id`` is not tracked.

        Raises:
            FileNotFoundError: If ``new_uri`` does not exist.
            ValueError: If ``new_uri`` is already tracked under a
                *different* ``source_id`` (would otherwise surface as a
                ``sqlite3.IntegrityError`` on the ``source_uri`` UNIQUE
                constraint).
        """
        entry = self.get_source(source_id)
        if entry is None:
            self.logger.warning("update_source_uri: source_id=%s not found", source_id)
            return None
        path = Path(new_uri).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {path}")
        new_source_uri = str(path)
        owner_id = self._find_id_by_uri(new_source_uri)
        if owner_id is not None and owner_id != source_id:
            raise ValueError(
                f"update_source_uri: {new_source_uri!r} is already tracked" f" by a different source_id={owner_id!r}"
            )
        updated = entry.model_copy(
            update={
                "source_uri": new_source_uri,
                "file_hash": self._compute_hash(path),
                "mtime": path.stat().st_mtime,
            }
        )
        self._upsert(updated)
        self.logger.debug(
            "update_source_uri: source_id=%s new_uri=%s",
            source_id,
            new_source_uri,
        )
        return updated

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
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=self.busy_timeout,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout * 1000)}")
        return conn

    @contextmanager
    def _write(self, operation: str) -> Iterator[sqlite3.Connection]:
        """Run one SQLite write inside an explicit immediate transaction.

        Args:
            operation: Logical name of the write, used in the error.

        Yields:
            An open connection inside a ``BEGIN IMMEDIATE`` transaction.

        Raises:
            WikiStoreBusy: The writer lock was not acquired within
                ``busy_timeout``. Raised only at the begin boundary.
        """
        from parrot.knowledge.wiki.store import WikiStoreBusy

        conn = self._connect()
        try:
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                # Codes, not message substrings (spec §7):
                # 5 = SQLITE_BUSY, 517 = SQLITE_BUSY_SNAPSHOT.
                if getattr(exc, "sqlite_errorcode", None) in (5, 517):
                    raise WikiStoreBusy(self.db_path, operation, self.busy_timeout) from exc
                raise
            try:
                yield conn
            except BaseException:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:  # pragma: no cover - rollback best effort
                    self.logger.debug("rollback failed after %s", operation, exc_info=True)
                raise
            # `executescript` (used by the schema-replay call site) issues
            # an implicit COMMIT before running, so a transaction may
            # already be closed by the time we get here — commit only if
            # one is still open.
            if conn.in_transaction:
                conn.execute("COMMIT")
        finally:
            # The pre-existing `with self._connect() as conn:` pattern
            # commits/rolls back but never CLOSES — close explicitly here.
            conn.close()

    def _upsert(self, entry: SourceManifestEntry) -> None:
        """Insert or replace one source entry in the active backend."""
        self._backend.upsert(entry)

    def _upsert_many(self, entries: list[SourceManifestEntry]) -> None:
        """Insert or replace many source entries in ONE statement.

        The batch twin of :meth:`_upsert` — same SQL, same document
        shape, one round trip (or one sqlite transaction, or one manifest
        save) instead of ``len(entries)``.

        Args:
            entries: Entries to write; an empty list is a no-op.
        """
        self._backend.upsert_many(entries)

    @staticmethod
    def _entry_params(entry: SourceManifestEntry) -> tuple:
        """Bind parameters for :data:`parrot.knowledge.wiki.sources_backend._SOURCES_UPSERT_SQL`, in column order."""
        return (
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
            (json.dumps(entry.doc_metadata) if entry.doc_metadata is not None else None),
            entry.content_type,
            entry.loader,
            entry.external_id,
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
        raw_doc_metadata = SourceCollectionManager._optional_column(row, "doc_metadata")
        try:
            doc_metadata = json.loads(raw_doc_metadata) if raw_doc_metadata is not None else None
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
            decision_source=SourceCollectionManager._optional_column(row, "decision_source"),
            charter_version=SourceCollectionManager._optional_column(row, "charter_version"),
            composite_score=SourceCollectionManager._optional_column(row, "composite_score"),
            doc_metadata=doc_metadata,
            content_type=SourceCollectionManager._optional_column(row, "content_type"),
            loader=SourceCollectionManager._optional_column(row, "loader"),
            external_id=SourceCollectionManager._optional_column(row, "external_id"),
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
        return self._backend.find_id_by_uri(source_uri)

    def _migrate_sources_columns(self) -> None:
        """Additively add the FEAT-402/FEAT-451/FEAT-472 columns to ``sources``.

        Idempotent — guarded on ``PRAGMA table_info(sources)`` — and
        additive only, never rewriting or dropping existing rows/columns,
        so pre-FEAT-402, pre-FEAT-451, and pre-FEAT-472 databases keep
        opening cleanly. Follows the :meth:`_migrate_json_manifest`
        compatibility precedent (existing data is never touched; only
        missing structure is added). Also (idempotently, via ``CREATE
        INDEX IF NOT EXISTS``) creates ``idx_sources_external_id`` so a
        pre-existing database gains the same index a fresh one gets from
        ``WIKI_SCHEMA_SQL``.
        """
        with self._write("migrate_sources") as conn:
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(sources)").fetchall()}
            for column_map in (_SOURCES_DECISION_COLUMNS, _SOURCES_DOCUMENT_COLUMNS, _SOURCES_EXTERNAL_COLUMNS):
                for name, col_type in column_map.items():
                    if name in existing:
                        continue
                    conn.execute(f"ALTER TABLE sources ADD COLUMN {name} {col_type}")
                    self.logger.debug("Migrated sources table: added column %s (%s)", name, col_type)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_external_id ON sources(external_id)")

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
            raw: dict[str, Any] = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            imported = 0
            for sid, data in raw.items():
                entry = SourceManifestEntry(**data)
                if self.get_source(sid) is None:
                    self._upsert(entry)
                    imported += 1
            self.manifest_path.rename(self.manifest_path.with_suffix(".json.bak"))
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
            self.logger.debug("No existing manifest at %s; starting fresh", self.manifest_path)
            return
        try:
            raw: dict = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            self._manifest = {sid: SourceManifestEntry(**data) for sid, data in raw.items()}
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
        data = {sid: entry.model_dump() for sid, entry in self._manifest.items()}
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
    composite = f"{entry.composite_score:.4f}" if entry.composite_score is not None else "n/a"
    return (
        f"source: {entry.source_uri}, composite: {composite}, "
        f"decision_source: {entry.decision_source or 'n/a'}, "
        f"charter_version: {entry.charter_version or 'n/a'}"
    )
