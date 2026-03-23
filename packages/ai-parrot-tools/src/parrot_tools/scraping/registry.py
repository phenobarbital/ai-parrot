"""
PlanRegistry — Async, disk-backed index mapping URLs to saved plan files.

Maintains a `registry.json` file that maps URL fingerprints to plan file
locations. Provides three-tier lookup: exact fingerprint → path-prefix → domain.
All write mutations are guarded with asyncio.Lock.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import aiofiles

from .plan import PlanRegistryEntry, ScrapingPlan, _normalize_url, _compute_fingerprint


class PlanRegistry:
    """Async, disk-backed index mapping URLs to saved plan files.

    Args:
        plans_dir: Directory where plan files and registry.json are stored.
            Defaults to ``scraping_plans`` in the current working directory.
    """

    def __init__(self, plans_dir: Optional[Path] = None) -> None:
        self.plans_dir = plans_dir or Path("scraping_plans")
        self._index_path = self.plans_dir / "registry.json"
        self._entries: dict[str, PlanRegistryEntry] = {}  # keyed by fingerprint
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    async def load(self) -> None:
        """Load registry index from disk.

        Reads ``registry.json`` and populates the in-memory entries dict.
        If the file does not exist, starts with an empty registry.
        """
        if not self._index_path.exists():
            self._entries = {}
            return
        try:
            async with aiofiles.open(self._index_path, "r", encoding="utf-8") as f:
                raw = await f.read()
            data = json.loads(raw)
            self._entries = {
                fp: PlanRegistryEntry.model_validate(entry)
                for fp, entry in data.items()
            }
            self.logger.info("Loaded %d entries from registry", len(self._entries))
        except (json.JSONDecodeError, ValueError) as exc:
            self.logger.warning("Failed to load registry: %s", exc)
            self._entries = {}

    def lookup(self, url: str) -> Optional[PlanRegistryEntry]:
        """Three-tier lookup: exact fingerprint -> path-prefix -> domain.

        Args:
            url: Target URL to look up.

        Returns:
            Matching ``PlanRegistryEntry`` or ``None`` if no match.
        """
        normalized = _normalize_url(url)
        fingerprint = _compute_fingerprint(normalized)

        # Tier 1: exact fingerprint match
        if fingerprint in self._entries:
            return self._entries[fingerprint]

        parsed = urlparse(normalized)
        lookup_path = parsed.path.rstrip("/")

        # Tier 2: path-prefix match
        best_match: Optional[PlanRegistryEntry] = None
        best_prefix_len = -1
        for entry in self._entries.values():
            entry_normalized = _normalize_url(entry.url)
            entry_parsed = urlparse(entry_normalized)
            if entry_parsed.netloc != parsed.netloc:
                continue
            entry_path = entry_parsed.path.rstrip("/")
            if lookup_path.startswith(entry_path) and len(entry_path) > best_prefix_len:
                best_match = entry
                best_prefix_len = len(entry_path)

        if best_match is not None:
            return best_match

        # Tier 3: domain-only match
        for entry in self._entries.values():
            if entry.domain == parsed.netloc:
                return entry

        return None

    def get_by_name(self, name: str) -> Optional[PlanRegistryEntry]:
        """Look up an entry by plan name.

        Args:
            name: Plan name to search for.

        Returns:
            Matching entry or ``None``.
        """
        for entry in self._entries.values():
            if entry.name == name:
                return entry
        return None

    def list_all(self) -> List[PlanRegistryEntry]:
        """Return all registry entries.

        Returns:
            List of all ``PlanRegistryEntry`` objects in the registry.
        """
        return list(self._entries.values())

    async def register(self, plan: ScrapingPlan, relative_path: str) -> None:
        """Register a plan in the index and persist to disk.

        Args:
            plan: The ``ScrapingPlan`` to register.
            relative_path: Path to the plan file relative to ``plans_dir``.
        """
        entry = PlanRegistryEntry(
            name=plan.name or "",
            plan_version=plan.version,
            url=plan.url,
            domain=plan.domain,
            fingerprint=plan.fingerprint,
            path=relative_path,
            created_at=plan.created_at,
            tags=plan.tags,
        )
        async with self._lock:
            self._entries[plan.fingerprint] = entry
            await self._save_index()
        self.logger.info("Registered plan '%s' (fingerprint=%s)", plan.name, plan.fingerprint)

    async def touch(self, fingerprint: str) -> None:
        """Update last_used_at and increment use_count for an entry.

        Args:
            fingerprint: The fingerprint of the entry to touch.
        """
        async with self._lock:
            entry = self._entries.get(fingerprint)
            if entry is None:
                self.logger.warning("Cannot touch: fingerprint '%s' not found", fingerprint)
                return
            entry.last_used_at = datetime.now(timezone.utc)
            entry.use_count += 1
            await self._save_index()

    async def remove(self, name: str) -> bool:
        """Remove an entry by name.

        Args:
            name: The plan name to remove.

        Returns:
            ``True`` if the entry was found and removed, ``False`` otherwise.
        """
        async with self._lock:
            target_fp = None
            for fp, entry in self._entries.items():
                if entry.name == name:
                    target_fp = fp
                    break
            if target_fp is None:
                return False
            del self._entries[target_fp]
            await self._save_index()
        self.logger.info("Removed plan '%s' from registry", name)
        return True

    async def _save_index(self) -> None:
        """Persist the in-memory index to registry.json.

        Must be called within the lock.
        """
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        data = {
            fp: entry.model_dump(mode="json")
            for fp, entry in self._entries.items()
        }
        raw = json.dumps(data, indent=2, default=str)
        async with aiofiles.open(self._index_path, "w", encoding="utf-8") as f:
            await f.write(raw)
