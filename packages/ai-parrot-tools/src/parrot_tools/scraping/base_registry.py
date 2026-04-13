"""
BasePlanRegistry — Generic disk-backed plan registry.

Provides the shared 3-tier URL lookup and CRUD operations for all plan
registry types. Subclass with a concrete plan model (e.g. ``ScrapingPlan``
or ``ExtractionPlan``) to get a fully functional registry without
duplicating boilerplate.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Generic, List, Optional, TypeVar

import aiofiles
from pydantic import BaseModel

from .plan import PlanRegistryEntry, _normalize_url, _compute_fingerprint

T = TypeVar("T", bound=BaseModel)


class BasePlanRegistry(Generic[T]):
    """Generic disk-backed plan registry with 3-tier URL lookup.

    Provides load/save, lookup (exact → path-prefix → domain), register,
    touch, remove, and invalidate operations against a JSON index file on
    disk.  All write operations are guarded by an ``asyncio.Lock``.

    Subclasses should override ``register`` if they need plan-type-specific
    index entry construction.

    Args:
        plans_dir: Directory for plan files and the index file.
            Defaults to ``scraping_plans`` in the current working directory.
        index_filename: Name of the JSON index file inside ``plans_dir``.
            Defaults to ``registry.json``.
    """

    def __init__(
        self,
        plans_dir: Optional[Path] = None,
        index_filename: str = "registry.json",
    ) -> None:
        self.plans_dir = plans_dir or Path("scraping_plans")
        self._index_path = self.plans_dir / index_filename
        self._entries: Dict[str, PlanRegistryEntry] = {}  # keyed by fingerprint
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    async def load(self) -> None:
        """Load registry index from disk.

        Reads the index JSON file and populates the in-memory entries dict.
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

        from urllib.parse import urlparse
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

    async def register(self, plan: T, relative_path: str) -> None:
        """Register a plan in the index and persist to disk.

        Builds a ``PlanRegistryEntry`` from the plan's ``name``, ``url``,
        ``domain``, ``fingerprint``, and optional ``version`` / ``tags``
        attributes, then saves the updated index.

        Args:
            plan: The plan object to register. Must have ``name``, ``url``,
                ``domain``, and ``fingerprint`` attributes.
            relative_path: Path to the plan file relative to ``plans_dir``.
        """
        entry = PlanRegistryEntry(
            name=getattr(plan, "name", None) or "",
            plan_version=str(getattr(plan, "version", "1.0")),
            url=plan.url,  # type: ignore[attr-defined]
            domain=plan.domain,  # type: ignore[attr-defined]
            fingerprint=plan.fingerprint,  # type: ignore[attr-defined]
            path=relative_path,
            created_at=datetime.now(timezone.utc),
            tags=getattr(plan, "tags", []),
        )
        async with self._lock:
            self._entries[plan.fingerprint] = entry  # type: ignore[attr-defined]
            await self._save_index()
        self.logger.info(
            "Registered plan '%s' (fingerprint=%s)",
            getattr(plan, "name", ""),
            plan.fingerprint,  # type: ignore[attr-defined]
        )

    async def touch(self, fingerprint: str) -> None:
        """Update last_used_at and increment use_count for an entry.

        Args:
            fingerprint: The fingerprint of the entry to touch.
        """
        async with self._lock:
            entry = self._entries.get(fingerprint)
            if entry is None:
                self.logger.warning(
                    "Cannot touch: fingerprint '%s' not found", fingerprint
                )
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

    async def invalidate(self, fingerprint: str) -> None:
        """Invalidate and remove an entry by fingerprint.

        Args:
            fingerprint: The fingerprint of the entry to remove.
        """
        async with self._lock:
            if fingerprint not in self._entries:
                self.logger.warning(
                    "Cannot invalidate: fingerprint '%s' not found", fingerprint
                )
                return
            name = self._entries[fingerprint].name
            del self._entries[fingerprint]
            await self._save_index()
        self.logger.info(
            "Invalidated plan (fingerprint=%s, name=%s)", fingerprint, name
        )

    async def _save_index(self) -> None:
        """Persist the in-memory index to the index file.

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
