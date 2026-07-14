"""Source collection manager for the LLM Wiki feature (FEAT-260).

Implements the "Raw Sources" layer of Karpathy's 3-layer architecture.
Tracks ingested source documents in the ``sources`` table of the wiki's
single-file SQLite retrieval plane (``wiki.db`` — see
:mod:`parrot.knowledge.wiki.store`), replacing the legacy
``.manifest.json`` file.  A legacy manifest found on first open is
migrated into the database automatically and renamed to
``.manifest.json.bak``.

Staleness detection reuses the same mtime + SHA-1 pattern as
``SQLitePersistence.is_stale()`` in ``graphindex/persist_sqlite.py``.

The public API is synchronous (callers off-load to a thread pool via
``asyncio.to_thread``), so this module uses the stdlib ``sqlite3``
driver with short-lived per-call connections — WAL mode makes this safe
alongside the async :class:`~parrot.knowledge.wiki.store.WikiStore`
connections on the same file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from parrot.knowledge.wiki.models import SourceManifestEntry
from parrot.knowledge.wiki.store import WIKI_SCHEMA_SQL


class SourceCollectionManager:
    """Manages the raw-source collection for a single wiki instance.

    Attributes:
        sources_dir: Directory where raw source files live.
        db_path: Path of the shared ``wiki.db`` SQLite file.
        manifest_path: Legacy ``.manifest.json`` location (migration only).
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
        db_path: Optional[Path] = None,
    ) -> None:
        """Initialise the manager, the schema, and migrate legacy data.

        Args:
            sources_dir: Root directory for raw source documents.
                Created automatically if it does not exist.
            db_path: Optional explicit path of the wiki database.  When
                omitted, defaults to ``<sources_dir>/../wiki.db`` — the
                same file used by :class:`WikiStore`.
        """
        self.sources_dir: Path = Path(sources_dir)
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.db_path: Path = (
            Path(db_path) if db_path else self.sources_dir.parent / "wiki.db"
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path: Path = self.sources_dir / self._MANIFEST_FILENAME
        self.logger: logging.Logger = logging.getLogger(__name__)
        with self._connect() as conn:
            conn.executescript(WIKI_SCHEMA_SQL)
        self._migrate_json_manifest()

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
            ingested_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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
            registered source, in insertion (rowid) order.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sources ORDER BY rowid"
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get_source(self, source_id: str) -> Optional[SourceManifestEntry]:
        """Retrieve a single source entry by its ID.

        Args:
            source_id: The stable source identifier assigned at
                registration time.

        Returns:
            The :class:`SourceManifestEntry`, or ``None`` if not found.
        """
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
    ) -> Optional[SourceManifestEntry]:
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

    def remove_source(self, source_id: str) -> bool:
        """Remove a source from the sources table.

        Args:
            source_id: The stable source identifier to remove.

        Returns:
            ``True`` if the entry existed and was removed; ``False`` if
            ``source_id`` was not present.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM sources WHERE source_id = ?", (source_id,)
            )
        removed = cur.rowcount > 0
        if removed:
            self.logger.debug("Source removed: source_id=%s", source_id)
        return removed

    def find_by_uri(self, source_uri: str) -> Optional[str]:
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
        """Insert or replace one sources row from a manifest entry."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sources"
                " (source_id, source_uri, file_hash, mtime, ingested_at,"
                "  pages_generated, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(source_id) DO UPDATE SET"
                "  source_uri=excluded.source_uri, file_hash=excluded.file_hash,"
                "  mtime=excluded.mtime, ingested_at=excluded.ingested_at,"
                "  pages_generated=excluded.pages_generated, status=excluded.status",
                (
                    entry.source_id,
                    entry.source_uri,
                    entry.file_hash,
                    entry.mtime,
                    entry.ingested_at,
                    json.dumps(entry.pages_generated),
                    entry.status,
                ),
            )

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> SourceManifestEntry:
        """Convert a sources row into a :class:`SourceManifestEntry`."""
        try:
            pages = json.loads(row["pages_generated"] or "[]")
        except (json.JSONDecodeError, TypeError):
            pages = []
        return SourceManifestEntry(
            source_id=row["source_id"],
            source_uri=row["source_uri"],
            file_hash=row["file_hash"],
            mtime=row["mtime"],
            ingested_at=row["ingested_at"],
            pages_generated=pages,
            status=row["status"],
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

    def _find_id_by_uri(self, source_uri: str) -> Optional[str]:
        """Look up an existing source ID by URI (internal implementation)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT source_id FROM sources WHERE source_uri = ?",
                (source_uri,),
            ).fetchone()
        return row["source_id"] if row else None

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
