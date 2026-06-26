"""Source collection manager for the LLM Wiki feature (FEAT-260).

Implements the "Raw Sources" layer of Karpathy's 3-layer architecture.
Tracks ingested source documents via a JSON manifest persisted to
``.manifest.json`` inside the wiki's sources directory.

Staleness detection reuses the same mtime + SHA-1 pattern as
``SQLitePersistence.is_stale()`` in ``graphindex/persist_sqlite.py``,
but stores state in a plain JSON file rather than SQLite so the
manifest remains human-readable without a database dependency.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from parrot.knowledge.wiki.models import SourceManifestEntry


class SourceCollectionManager:
    """Manages the raw-source collection for a single wiki instance.

    Attributes:
        sources_dir: Directory where raw source files live.
        manifest_path: Path to the ``.manifest.json`` file that tracks
            all ingested sources.
        logger: Standard Python logger.

    Example::

        mgr = SourceCollectionManager(Path("/wiki/sources"))
        entry = mgr.add_source(Path("/docs/article.md"))
        print(entry.source_id, entry.file_hash)

        if mgr.is_stale(entry.source_id):
            mgr.reingest(...)
    """

    _MANIFEST_FILENAME: str = ".manifest.json"

    def __init__(self, sources_dir: Path) -> None:
        """Initialise the manager and load the existing manifest.

        Args:
            sources_dir: Root directory for raw source documents.
                Created automatically if it does not exist.
        """
        self.sources_dir: Path = Path(sources_dir)
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path: Path = self.sources_dir / self._MANIFEST_FILENAME
        self.logger: logging.Logger = logging.getLogger(__name__)
        self._manifest: dict[str, SourceManifestEntry] = {}
        self._load_manifest()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_source(self, path: Path) -> SourceManifestEntry:
        """Register a new source file in the manifest.

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
        # Re-use existing ID if the file was already tracked
        existing_id = self._find_id_by_uri(source_uri)
        source_id = existing_id or self._generate_source_id(source_uri)

        file_hash = self._compute_hash(path)
        mtime = path.stat().st_mtime
        ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        entry = SourceManifestEntry(
            source_id=source_id,
            source_uri=source_uri,
            file_hash=file_hash,
            mtime=mtime,
            ingested_at=ingested_at,
            pages_generated=[],
            status="ingested",
        )
        self._manifest[source_id] = entry
        self._save_manifest()
        self.logger.debug(
            "Source added: source_id=%s uri=%s hash=%s",
            source_id,
            source_uri,
            file_hash,
        )
        return entry

    def list_sources(self) -> list[SourceManifestEntry]:
        """Return all tracked sources.

        Returns:
            A list of :class:`SourceManifestEntry` objects, one per
            registered source.  Order is insertion order (Python 3.7+).
        """
        return list(self._manifest.values())

    def get_source(self, source_id: str) -> Optional[SourceManifestEntry]:
        """Retrieve a single source entry by its ID.

        Args:
            source_id: The stable source identifier assigned at
                registration time.

        Returns:
            The :class:`SourceManifestEntry`, or ``None`` if not found.
        """
        return self._manifest.get(source_id)

    def is_stale(self, source_id: str) -> bool:
        """Determine whether a tracked source has changed since last ingest.

        Replicates the ``SQLitePersistence.is_stale()`` logic: a source
        is stale when its current SHA-1 hash *or* mtime differs from the
        values recorded at ingest time.

        Args:
            source_id: The stable source identifier to check.

        Returns:
            ``True`` when the source is missing from the manifest, the
            underlying file no longer exists, or the file content / mtime
            has changed.  ``False`` otherwise.
        """
        entry = self._manifest.get(source_id)
        if entry is None:
            self.logger.debug("is_stale: source_id=%s not in manifest", source_id)
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
                "is_stale: source_id=%s mtime_changed=%s hash_changed=%s stale=%s",
                source_id,
                True,
                stale,
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
        """Update the manifest after a successful ingest run.

        Args:
            source_id: The source to update.
            pages_generated: List of wiki page IDs produced by the ingest.
            status: New lifecycle status (defaults to ``"ingested"``).

        Returns:
            The updated :class:`SourceManifestEntry`, or ``None`` if
            ``source_id`` is not tracked.
        """
        entry = self._manifest.get(source_id)
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
            self._manifest[source_id] = entry
            self._save_manifest()
        return entry

    def remove_source(self, source_id: str) -> bool:
        """Remove a source from the manifest.

        Args:
            source_id: The stable source identifier to remove.

        Returns:
            ``True`` if the entry existed and was removed; ``False`` if
            ``source_id`` was not present in the manifest.
        """
        if source_id not in self._manifest:
            return False
        del self._manifest[source_id]
        self._save_manifest()
        self.logger.debug("Source removed: source_id=%s", source_id)
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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

    def find_by_uri(self, source_uri: str) -> Optional[str]:
        """Look up an existing source ID by URI (public API).

        Args:
            source_uri: The URI to search for.

        Returns:
            The matching source_id, or ``None`` if not tracked.
        """
        return self._find_id_by_uri(source_uri)

    def _find_id_by_uri(self, source_uri: str) -> Optional[str]:
        """Look up an existing source ID by URI (internal implementation).

        Args:
            source_uri: The URI to search for.

        Returns:
            The matching source_id, or ``None`` if not tracked.
        """
        for sid, entry in self._manifest.items():
            if entry.source_uri == source_uri:
                return sid
        return None

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
                sid: SourceManifestEntry(**data)
                for sid, data in raw.items()
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
