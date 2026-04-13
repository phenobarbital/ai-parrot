"""
ExtractionPlanRegistry — Disk-backed registry for ExtractionPlans.

Extends ``BasePlanRegistry`` with extraction-specific lifecycle management:
  - success/failure tracking with automatic invalidation after 3 consecutive failures
  - per-fingerprint JSON file storage
  - pre-built plan loading from a developer-curated directory
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import aiofiles

from .base_registry import BasePlanRegistry
from .extraction_models import ExtractionPlan
from .plan import PlanRegistryEntry, _normalize_url, _compute_fingerprint


class ExtractionPlanRegistry(BasePlanRegistry[ExtractionPlan]):
    """Disk-backed registry for ExtractionPlans with cache lifecycle management.

    Extends ``BasePlanRegistry`` with extraction-specific features:
    - success/failure tracking
    - automatic invalidation after 3 consecutive failures
    - pre-built plan loading from a directory

    Args:
        plans_dir: Directory for plan files and the ``extraction_registry.json`` index.
            Defaults to ``scraping_plans`` in the current working directory.
    """

    FAILURE_THRESHOLD = 3

    def __init__(self, plans_dir: Optional[Path] = None) -> None:
        super().__init__(plans_dir=plans_dir, index_filename="extraction_registry.json")
        # Track failure counts per fingerprint (in-memory, augments PlanRegistryEntry)
        self._failure_counts: dict[str, int] = {}

    async def register_extraction_plan(self, plan: ExtractionPlan) -> None:
        """Register an ExtractionPlan in the registry.

        Saves the plan as a JSON file named ``<fingerprint>.json`` and registers
        it in the index.

        Args:
            plan: The ExtractionPlan to register.
        """
        filename = f"{plan.fingerprint}.json"
        filepath = self.plans_dir / filename
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        plan_json = plan.model_dump_json(indent=2)
        async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
            await f.write(plan_json)
        await self.register(plan, filename)

    async def load_plan(self, fingerprint: str) -> Optional[ExtractionPlan]:
        """Load an ExtractionPlan from disk by fingerprint.

        Args:
            fingerprint: The fingerprint of the plan to load.

        Returns:
            The ExtractionPlan if found, None otherwise.
        """
        entry = self._entries.get(fingerprint)
        if entry is None:
            return None
        filepath = self.plans_dir / entry.path
        if not filepath.exists():
            return None
        try:
            async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                raw = await f.read()
            return ExtractionPlan.model_validate_json(raw)
        except Exception as exc:
            self.logger.warning("Failed to load plan from %s: %s", filepath, exc)
            return None

    async def lookup_plan(self, url: str) -> Optional[ExtractionPlan]:
        """Look up and load an ExtractionPlan for a URL.

        Uses the 3-tier URL lookup from ``BasePlanRegistry`` to find a matching
        registry entry, then loads the plan JSON from disk.

        Args:
            url: URL to look up.

        Returns:
            ExtractionPlan if found in registry, None otherwise.
        """
        entry = self.lookup(url)
        if entry is None:
            return None
        return await self.load_plan(entry.fingerprint)

    async def record_success(self, fingerprint: str) -> None:
        """Record a successful extraction. Resets the failure count.

        Also calls ``touch()`` to update last_used_at and increment use_count.

        Args:
            fingerprint: The plan fingerprint.
        """
        self._failure_counts[fingerprint] = 0
        await self.touch(fingerprint)
        self.logger.debug("Recorded success for fingerprint=%s", fingerprint)

    async def record_failure(self, fingerprint: str) -> None:
        """Record a failed extraction. Invalidates after 3 consecutive failures.

        When the failure count reaches ``FAILURE_THRESHOLD``, the plan is
        removed from the registry so that fresh LLM recon can regenerate it.

        Args:
            fingerprint: The plan fingerprint.
        """
        count = self._failure_counts.get(fingerprint, 0) + 1
        self._failure_counts[fingerprint] = count
        self.logger.warning(
            "Extraction failure %d/%d for fingerprint=%s",
            count,
            self.FAILURE_THRESHOLD,
            fingerprint,
        )
        if count >= self.FAILURE_THRESHOLD:
            self.logger.warning(
                "Invalidating plan after %d failures (fingerprint=%s)",
                count,
                fingerprint,
            )
            await self.invalidate(fingerprint)
            self._failure_counts.pop(fingerprint, None)

    async def load_prebuilt(self, directory: Path) -> int:
        """Load pre-built ExtractionPlan JSON files from a directory.

        Each JSON file must be parseable as an ``ExtractionPlan``.  The
        ``source`` field is overridden to ``"developer"`` to mark these as
        developer-curated plans.

        Args:
            directory: Path to directory containing JSON ExtractionPlan files.

        Returns:
            Count of plans successfully loaded.
        """
        if not directory.exists():
            self.logger.warning(
                "Pre-built plans directory does not exist: %s", directory
            )
            return 0

        count = 0
        for json_file in directory.glob("*.json"):
            try:
                async with aiofiles.open(json_file, "r", encoding="utf-8") as f:
                    raw = await f.read()
                data = json.loads(raw)
                data["source"] = "developer"  # enforce developer source
                plan = ExtractionPlan.model_validate(data)
                await self.register_extraction_plan(plan)
                count += 1
                self.logger.info("Loaded pre-built plan from %s", json_file.name)
            except Exception as exc:
                self.logger.warning(
                    "Failed to load pre-built plan %s: %s", json_file, exc
                )

        return count
