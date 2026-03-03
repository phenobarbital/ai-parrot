"""
File-based Research Memory Implementation
==========================================

Filesystem-based implementation of ResearchMemory with in-memory cache.

Features:
- In-memory cache (OrderedDict for LRU) for fast reads
- Fire-and-forget writes to filesystem using asyncio.create_task()
- Async file I/O with aiofiles
- Cache warming at startup from existing files
- Per-path locking to prevent write conflicts
- LRU eviction when cache exceeds max_size

Directory structure:
    {base_path}/{domain}/{crew_id}/{period_key}.json

Example:
    research_memory/
    ├── macro/
    │   └── research_crew_macro/
    │       ├── 2026-03-01.json
    │       └── 2026-03-02.json
    ├── crypto/
    │   └── research_crew_crypto/
    │       ├── 2026-03-03T00-00-00.json
    │       └── 2026-03-03T04-00-00.json
    └── _historical/  (for archived documents)
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import aiofiles

from .abstract import ResearchMemory
from .schemas import (
    ALL_DOMAINS,
    AuditEvent,
    DOMAIN_TO_CREW,
    ResearchDocument,
)


class FileResearchMemory(ResearchMemory):
    """Filesystem-based research memory with in-memory cache.

    This is the primary implementation of ResearchMemory for the collective
    memory system. It provides fast reads via an in-memory cache and
    non-blocking writes via fire-and-forget disk persistence.

    Attributes:
        base_path: Root directory for research document storage.
        cache_max_size: Maximum number of documents to keep in memory.
        warmup_on_init: If True, load existing documents into cache on start().

    Example:
        >>> memory = FileResearchMemory(
        ...     base_path="/var/data/research_memory",
        ...     cache_max_size=100,
        ... )
        >>> await memory.start()
        >>>
        >>> # Store a document (cache + fire-and-forget disk write)
        >>> doc_id = await memory.store(document)
        >>>
        >>> # Fast lookup from cache
        >>> exists = await memory.exists("research_crew_macro", "2026-03-03")
        >>>
        >>> await memory.stop()
    """

    # Domain to crew mapping for directory structure
    DOMAIN_CREW_MAP = DOMAIN_TO_CREW

    # Maximum audit log size before rotation (10MB)
    MAX_LOG_SIZE_BYTES = 10 * 1024 * 1024

    def __init__(
        self,
        base_path: str = "./research_memory",
        cache_max_size: int = 100,
        warmup_on_init: bool = True,
        debug: bool = False,
    ):
        """Initialize the file research memory.

        Args:
            base_path: Root directory for storage (created if not exists).
            cache_max_size: Maximum documents to cache in memory (LRU eviction).
            warmup_on_init: Load existing documents into cache on start().
            debug: Enable debug logging.
        """
        super().__init__(debug=debug)
        self.base_path = Path(base_path)
        self.cache_max_size = cache_max_size
        self.warmup_on_init = warmup_on_init

        # LRU cache: OrderedDict[tuple[crew_id, period_key], ResearchDocument]
        # OrderedDict maintains insertion order; we move accessed items to end
        self._cache: OrderedDict[tuple[str, str], ResearchDocument] = OrderedDict()

        # Per-path locks to prevent concurrent writes to same file
        self._locks: dict[str, asyncio.Lock] = {}

        # Global lock for cache operations
        self._cache_lock = asyncio.Lock()

        # Startup flag
        self._started = False

        # Audit log path and lock
        self._audit_log_path: Path | None = None
        self._audit_log_lock = asyncio.Lock()

    # =========================================================================
    # LIFECYCLE METHODS
    # =========================================================================

    async def start(self) -> None:
        """Initialize the memory store.

        Creates directory structure for all domains and optionally
        warms the cache from existing files.

        Raises:
            RuntimeError: If start() is called twice without stop().
        """
        if self._started:
            self.logger.warning("FileResearchMemory already started")
            return

        # Create base directory
        self.base_path.mkdir(parents=True, exist_ok=True)

        # Create directory structure for each domain/crew
        for domain in ALL_DOMAINS:
            crew_id = self.DOMAIN_CREW_MAP.get(domain, f"research_crew_{domain}")
            domain_dir = self.base_path / domain / crew_id
            domain_dir.mkdir(parents=True, exist_ok=True)

        # Create audit log directory
        audit_dir = self.base_path / "_audit_log"
        audit_dir.mkdir(parents=True, exist_ok=True)
        self._audit_log_path = audit_dir / "research_events.jsonl"

        # Create historical archive directory
        historical_dir = self.base_path / "_historical"
        historical_dir.mkdir(parents=True, exist_ok=True)

        # Run cleanup BEFORE cache warming to archive old documents
        archived = await self.cleanup()
        if archived > 0:
            self.logger.info(f"Startup cleanup archived {archived} documents")

        # Warm cache from remaining files
        if self.warmup_on_init:
            await self._warm_cache()

        self._started = True
        self.logger.info(
            f"FileResearchMemory started at {self.base_path} "
            f"(cache_max_size={self.cache_max_size})"
        )

    async def stop(self) -> None:
        """Gracefully shut down the memory system.

        Waits briefly for any pending fire-and-forget writes to complete.
        """
        if not self._started:
            return

        # Give pending tasks a moment to complete
        # In production, you might want to track pending tasks explicitly
        await asyncio.sleep(0.1)

        self._started = False
        self.logger.info("FileResearchMemory stopped")

    # =========================================================================
    # CORE CRUD OPERATIONS
    # =========================================================================

    async def store(self, document: ResearchDocument) -> str:
        """Store a research document with fire-and-forget persistence.

        The document is immediately added to the in-memory cache for fast
        subsequent reads. Disk persistence happens asynchronously via
        asyncio.create_task() - the caller doesn't wait for disk I/O.

        Args:
            document: The research document to store.

        Returns:
            The document ID.

        Raises:
            ValueError: If document is invalid.
        """
        cache_key = (document.crew_id, document.period_key)

        async with self._cache_lock:
            # Update cache immediately (LRU: move to end)
            self._cache[cache_key] = document
            self._cache.move_to_end(cache_key)

            # Evict oldest entries if over max size
            while len(self._cache) > self.cache_max_size:
                evicted_key, _ = self._cache.popitem(last=False)
                if self.debug:
                    self.logger.debug(f"LRU evicted: {evicted_key}")

        # Fire-and-forget disk write
        asyncio.create_task(self._persist_to_disk(document))

        if self.debug:
            self.logger.debug(
                f"Stored document {document.id} for {document.crew_id} "
                f"period={document.period_key}"
            )

        return document.id

    async def get(
        self,
        crew_id: str,
        period_key: str,
    ) -> Optional[ResearchDocument]:
        """Get a specific research document by crew and period.

        Checks in-memory cache first, then falls back to disk.

        Args:
            crew_id: The research crew identifier.
            period_key: The period in ISO format.

        Returns:
            The document if found, None otherwise.
        """
        cache_key = (crew_id, period_key)

        # Check cache first
        async with self._cache_lock:
            if cache_key in self._cache:
                # Move to end for LRU
                self._cache.move_to_end(cache_key)
                return self._cache[cache_key]

        # Not in cache, try to load from disk
        domain = self._extract_domain_from_crew_id(crew_id)
        if domain is None:
            return None

        file_path = self._get_file_path(domain, crew_id, period_key)
        if not file_path.exists():
            return None

        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
            document = ResearchDocument.model_validate_json(content)

            # Add to cache
            async with self._cache_lock:
                self._cache[cache_key] = document
                self._cache.move_to_end(cache_key)

                # Evict if needed
                while len(self._cache) > self.cache_max_size:
                    self._cache.popitem(last=False)

            return document

        except Exception as e:
            self.logger.warning(f"Failed to load {file_path}: {e}")
            return None

    async def exists(
        self,
        crew_id: str,
        period_key: str,
    ) -> bool:
        """Check if a research document exists.

        Fast existence check - checks cache first, then disk.

        Args:
            crew_id: The research crew identifier.
            period_key: The period in ISO format.

        Returns:
            True if document exists, False otherwise.
        """
        cache_key = (crew_id, period_key)

        # Check cache first (fast path)
        async with self._cache_lock:
            if cache_key in self._cache:
                return True

        # Check disk
        domain = self._extract_domain_from_crew_id(crew_id)
        if domain is None:
            return False

        file_path = self._get_file_path(domain, crew_id, period_key)
        return file_path.exists()

    async def get_latest(
        self,
        domain: str,
    ) -> Optional[ResearchDocument]:
        """Get the most recent research document for a domain.

        Searches both cache and disk for the newest document.

        Args:
            domain: The research domain (macro, equity, crypto, sentiment, risk).

        Returns:
            The latest document if found, None otherwise.
        """
        crew_id = self.DOMAIN_CREW_MAP.get(domain)
        if crew_id is None:
            self.logger.warning(f"Unknown domain: {domain}")
            return None

        # Collect documents from cache for this domain
        candidates: list[ResearchDocument] = []

        async with self._cache_lock:
            for (cached_crew_id, _), doc in self._cache.items():
                if cached_crew_id == crew_id:
                    candidates.append(doc)

        # Also check disk for files not in cache
        domain_dir = self.base_path / domain / crew_id
        if domain_dir.exists():
            # Get all JSON files, sorted by name descending (most recent first)
            json_files = sorted(domain_dir.glob("*.json"), reverse=True)

            for file_path in json_files[:5]:  # Check top 5 most recent
                period_key = self._period_key_from_filename(file_path.stem)
                cache_key = (crew_id, period_key)

                # Skip if already in candidates from cache
                async with self._cache_lock:
                    if cache_key in self._cache:
                        continue

                try:
                    async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                        content = await f.read()
                    doc = ResearchDocument.model_validate_json(content)
                    candidates.append(doc)
                except Exception as e:
                    self.logger.warning(f"Failed to load {file_path}: {e}")

        if not candidates:
            return None

        # Return the one with the most recent generated_at
        return max(candidates, key=lambda d: d.generated_at)

    async def get_history(
        self,
        domain: str,
        last_n: int = 5,
    ) -> list[ResearchDocument]:
        """Get the N most recent documents for a domain.

        Args:
            domain: The research domain.
            last_n: Number of documents to retrieve.

        Returns:
            List of documents ordered by generated_at descending (newest first).
        """
        crew_id = self.DOMAIN_CREW_MAP.get(domain)
        if crew_id is None:
            return []

        documents: dict[str, ResearchDocument] = {}  # period_key -> doc

        # Collect from cache
        async with self._cache_lock:
            for (cached_crew_id, period_key), doc in self._cache.items():
                if cached_crew_id == crew_id:
                    documents[period_key] = doc

        # Collect from disk
        domain_dir = self.base_path / domain / crew_id
        if domain_dir.exists():
            json_files = sorted(domain_dir.glob("*.json"), reverse=True)

            for file_path in json_files[: last_n * 2]:  # Load extra to account for cache overlap
                period_key = self._period_key_from_filename(file_path.stem)
                if period_key in documents:
                    continue

                try:
                    async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                        content = await f.read()
                    doc = ResearchDocument.model_validate_json(content)
                    documents[period_key] = doc
                except Exception as e:
                    self.logger.warning(f"Failed to load {file_path}: {e}")

        # Sort by generated_at descending and take last_n
        sorted_docs = sorted(
            documents.values(),
            key=lambda d: d.generated_at,
            reverse=True,
        )
        return sorted_docs[:last_n]

    async def query(
        self,
        domains: Optional[list[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> list[ResearchDocument]:
        """Query documents with filters.

        Args:
            domains: Filter by domains (None = all domains).
            since: Filter documents generated after this time.
            until: Filter documents generated before this time.

        Returns:
            List of matching documents ordered by generated_at descending.
        """
        target_domains = domains if domains else ALL_DOMAINS
        results: list[ResearchDocument] = []

        for domain in target_domains:
            crew_id = self.DOMAIN_CREW_MAP.get(domain)
            if crew_id is None:
                continue

            # Check cache
            async with self._cache_lock:
                for (cached_crew_id, _), doc in self._cache.items():
                    if cached_crew_id != crew_id:
                        continue
                    if since and doc.generated_at < since:
                        continue
                    if until and doc.generated_at > until:
                        continue
                    results.append(doc)

            # Check disk
            domain_dir = self.base_path / domain / crew_id
            if not domain_dir.exists():
                continue

            for file_path in domain_dir.glob("*.json"):
                period_key = self._period_key_from_filename(file_path.stem)
                cache_key = (crew_id, period_key)

                # Skip if already added from cache
                async with self._cache_lock:
                    if cache_key in self._cache:
                        continue

                try:
                    async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                        content = await f.read()
                    doc = ResearchDocument.model_validate_json(content)

                    if since and doc.generated_at < since:
                        continue
                    if until and doc.generated_at > until:
                        continue

                    results.append(doc)
                except Exception as e:
                    self.logger.warning(f"Failed to load {file_path}: {e}")

        # Sort by generated_at descending
        return sorted(results, key=lambda d: d.generated_at, reverse=True)

    # =========================================================================
    # CLEANUP & ARCHIVAL
    # =========================================================================

    async def cleanup(
        self,
        retention_days: int = 7,
    ) -> int:
        """Archive documents older than retention period.

        Moves old documents to _historical/{year-month}/ folder instead of
        deleting. Also removes them from the in-memory cache and logs
        cleanup events.

        Args:
            retention_days: Days to retain documents in active storage.

        Returns:
            Count of documents archived.
        """
        cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=retention_days)

        archived_count = 0
        historical_base = self.base_path / "_historical"
        historical_base.mkdir(parents=True, exist_ok=True)

        for domain in ALL_DOMAINS:
            crew_id = self.DOMAIN_CREW_MAP.get(domain)
            if crew_id is None:
                continue

            domain_dir = self.base_path / domain / crew_id
            if not domain_dir.exists():
                continue

            for file_path in list(domain_dir.glob("*.json")):
                try:
                    async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                        content = await f.read()
                    doc = ResearchDocument.model_validate_json(content)

                    if doc.generated_at < cutoff:
                        # Archive to _historical/{year-month}/{domain}/{crew_id}/
                        year_month = doc.generated_at.strftime("%Y-%m")
                        dest_dir = historical_base / year_month / domain / crew_id
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        dest_path = dest_dir / file_path.name
                        file_path.rename(dest_path)

                        # Remove from cache
                        cache_key = (doc.crew_id, doc.period_key)
                        async with self._cache_lock:
                            self._cache.pop(cache_key, None)

                        # Fire-and-forget audit log for cleanup event
                        asyncio.create_task(
                            self._log_audit_event(
                                AuditEvent(
                                    event_type="cleaned",
                                    crew_id=doc.crew_id,
                                    period_key=doc.period_key,
                                    domain=doc.domain,
                                    actor="system",
                                    details={
                                        "archived_to": str(dest_path),
                                        "retention_days": retention_days,
                                    },
                                )
                            )
                        )

                        archived_count += 1
                        if self.debug:
                            self.logger.debug(f"Archived {file_path.name} to {dest_path}")

                except Exception as e:
                    self.logger.warning(f"Failed to process {file_path}: {e}")

        if archived_count > 0:
            self.logger.info(f"Cleanup archived {archived_count} documents")
        return archived_count

    # =========================================================================
    # AUDIT TRAIL
    # =========================================================================

    async def get_audit_events(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        event_type: Optional[str] = None,
    ) -> list[AuditEvent]:
        """Query audit trail events.

        Reads from the append-only JSONL audit log file.

        Args:
            since: Filter events after this time.
            until: Filter events before this time.
            event_type: Filter by event type.

        Returns:
            List of matching audit events.
        """
        if self._audit_log_path is None or not self._audit_log_path.exists():
            return []

        events: list[AuditEvent] = []

        try:
            async with aiofiles.open(self._audit_log_path, "r", encoding="utf-8") as f:
                async for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event = AuditEvent.model_validate_json(line)

                        if since and event.timestamp < since:
                            continue
                        if until and event.timestamp > until:
                            continue
                        if event_type and event.event_type != event_type:
                            continue

                        events.append(event)
                    except Exception:
                        # Skip malformed lines
                        continue

        except Exception as e:
            self.logger.warning(f"Failed to read audit log: {e}")

        return events

    async def _log_audit_event(self, event: AuditEvent) -> None:
        """Append an audit event to the log file with rotation.

        The log file is rotated when it exceeds MAX_LOG_SIZE_BYTES (10MB).
        Uses a lock to prevent concurrent writes.

        Args:
            event: The audit event to log.
        """
        if self._audit_log_path is None:
            return

        async with self._audit_log_lock:
            try:
                # Check if rotation is needed
                await self._rotate_log_if_needed()

                # Append event to log
                async with aiofiles.open(self._audit_log_path, "a", encoding="utf-8") as f:
                    await f.write(event.model_dump_json() + "\n")
            except Exception as e:
                self.logger.warning(f"Failed to write audit event: {e}")

    async def _rotate_log_if_needed(self) -> None:
        """Rotate log file if it exceeds MAX_LOG_SIZE_BYTES.

        Renames current log to research_events.jsonl.1, .2, etc.
        """
        if self._audit_log_path is None or not self._audit_log_path.exists():
            return

        try:
            size = self._audit_log_path.stat().st_size
            if size < self.MAX_LOG_SIZE_BYTES:
                return

            # Find next rotation number
            rotated = 1
            while (self._audit_log_path.parent / f"{self._audit_log_path.name}.{rotated}").exists():
                rotated += 1

            # Rename current to rotated
            rotated_path = self._audit_log_path.parent / f"{self._audit_log_path.name}.{rotated}"
            self._audit_log_path.rename(rotated_path)
            self.logger.info(f"Rotated audit log to {rotated_path.name}")

        except Exception as e:
            self.logger.warning(f"Failed to rotate audit log: {e}")

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _get_file_path(self, domain: str, crew_id: str, period_key: str) -> Path:
        """Generate file path for a document.

        Args:
            domain: The research domain.
            crew_id: The crew identifier.
            period_key: The period key (may contain colons).

        Returns:
            Path to the JSON file.
        """
        # Sanitize period_key for filename (replace : with -)
        safe_period = period_key.replace(":", "-")
        return self.base_path / domain / crew_id / f"{safe_period}.json"

    def _period_key_from_filename(self, filename: str) -> str:
        """Convert filename back to period_key.

        Args:
            filename: The filename without extension.

        Returns:
            The period_key with colons restored.
        """
        # If filename has format like 2026-03-03T14-00-00, restore to 2026-03-03T14:00:00
        if "T" in filename:
            parts = filename.split("T")
            if len(parts) == 2:
                date_part = parts[0]
                time_part = parts[1].replace("-", ":")
                return f"{date_part}T{time_part}"
        return filename

    def _extract_domain_from_crew_id(self, crew_id: str) -> Optional[str]:
        """Extract domain from crew_id.

        Args:
            crew_id: e.g., "research_crew_macro"

        Returns:
            Domain string or None if not found.
        """
        for domain, cid in self.DOMAIN_CREW_MAP.items():
            if cid == crew_id:
                return domain
        # Fallback: try to extract from crew_id pattern
        if crew_id.startswith("research_crew_"):
            return crew_id.replace("research_crew_", "")
        return None

    async def _persist_to_disk(self, document: ResearchDocument) -> None:
        """Async persist document to filesystem.

        Uses per-path locking to prevent concurrent writes to the same file.

        Args:
            document: The document to persist.
        """
        path = self._get_file_path(
            document.domain, document.crew_id, document.period_key
        )
        lock = self._locks.setdefault(str(path), asyncio.Lock())

        async with lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                async with aiofiles.open(path, "w", encoding="utf-8") as f:
                    await f.write(document.model_dump_json(indent=2))

                if self.debug:
                    self.logger.debug(f"Persisted {path}")

                # Log audit event
                await self._log_audit_event(
                    AuditEvent(
                        event_type="stored",
                        crew_id=document.crew_id,
                        period_key=document.period_key,
                        domain=document.domain,
                        actor=document.crew_id,
                        details={"document_id": document.id},
                    )
                )

            except Exception as e:
                self.logger.error(f"Failed to persist {path}: {e}")

    async def _warm_cache(self) -> None:
        """Load existing documents into cache at startup.

        Loads up to 20 most recent documents per domain to populate
        the cache for fast initial reads.
        """
        count = 0

        for domain in ALL_DOMAINS:
            crew_id = self.DOMAIN_CREW_MAP.get(domain)
            if crew_id is None:
                continue

            domain_dir = self.base_path / domain / crew_id
            if not domain_dir.exists():
                continue

            # Get all JSON files, sorted by name descending (newest first)
            files = sorted(domain_dir.glob("*.json"), reverse=True)

            # Load up to 20 most recent per domain
            for file_path in files[:20]:
                try:
                    async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                        content = await f.read()
                    doc = ResearchDocument.model_validate_json(content)

                    cache_key = (doc.crew_id, doc.period_key)
                    self._cache[cache_key] = doc
                    count += 1

                    if count >= self.cache_max_size:
                        break
                except Exception as e:
                    self.logger.warning(f"Failed to load {file_path}: {e}")

            if count >= self.cache_max_size:
                break

        self.logger.info(f"Cache warmed with {count} documents")
