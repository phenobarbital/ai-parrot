"""
PlanRegistry — Async, disk-backed index mapping URLs to saved plan files.

Maintains a ``registry.json`` file that maps URL fingerprints to plan file
locations. Provides three-tier lookup: exact fingerprint → path-prefix → domain.
All write mutations are guarded with asyncio.Lock.

Now implemented as a thin subclass of ``BasePlanRegistry[ScrapingPlan]`` —
shared registry logic lives in ``base_registry.py``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base_registry import BasePlanRegistry
from .plan import PlanRegistryEntry, ScrapingPlan


class PlanRegistry(BasePlanRegistry[ScrapingPlan]):
    """Async, disk-backed index mapping URLs to saved ScrapingPlan files.

    Thin subclass of ``BasePlanRegistry`` specialised for ``ScrapingPlan``
    objects.  Overrides ``register`` to use the ScrapingPlan's own
    ``created_at`` and ``tags`` fields.

    Args:
        plans_dir: Directory where plan files and ``registry.json`` are stored.
            Defaults to ``scraping_plans`` in the current working directory.
    """

    def __init__(self, plans_dir: Optional[Path] = None) -> None:
        super().__init__(plans_dir=plans_dir, index_filename="registry.json")

    async def register(self, plan: ScrapingPlan, relative_path: str) -> None:
        """Register a ScrapingPlan in the index and persist to disk.

        Overrides the base implementation to use ``plan.created_at`` and
        ``plan.tags`` directly from the ScrapingPlan model.

        Args:
            plan: The ``ScrapingPlan`` to register.
            relative_path: Path to the plan file relative to ``plans_dir``.
        """
        from datetime import datetime, timezone
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
        self.logger.info(
            "Registered plan '%s' (fingerprint=%s)", plan.name, plan.fingerprint
        )
