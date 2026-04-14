"""
ExtractionPlanRegistry — Disk-backed registry for ExtractionPlans.

Extends ``BasePlanRegistry`` with extraction-specific lifecycle management:
  - success/failure tracking with automatic invalidation after 3 consecutive
    failures; counts are persisted in the registry index so they survive
    process restarts
  - per-fingerprint JSON file storage
  - pre-built plan loading from a developer-curated directory
  - lazy load: index + pre-built plans are loaded on first ``lookup_plan()``
    call so the async-incompatible ``__init__`` stays sync
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, Optional

import aiofiles

from .base_registry import BasePlanRegistry
from .extraction_models import ExtractionPlan
from .plan import _normalize_url, _compute_fingerprint


class ExtractionPlanRegistry(BasePlanRegistry[ExtractionPlan]):
    """Disk-backed registry for ExtractionPlans with cache lifecycle management.

    Extends ``BasePlanRegistry`` with extraction-specific features:

    - success/failure tracking persisted to the registry index JSON so failure
      counts survive service restarts
    - automatic invalidation after ``FAILURE_THRESHOLD`` consecutive failures
    - pre-built plan loading from a developer-curated directory
    - lazy initialisation: ``load()`` and ``load_prebuilt()`` are called on
      the first ``lookup_plan()`` call, keeping the sync ``__init__`` clean

    Args:
        plans_dir: Directory for plan files and the ``extraction_registry.json``
            index.  Defaults to ``scraping_plans`` in the current working
            directory.
        prebuilt_dir: Directory containing pre-built plan JSON files.
            Defaults to ``DEFAULT_PREBUILT_DIR`` (the ``_prebuilt/``
            sub-directory shipped with this package).
    """

    FAILURE_THRESHOLD: ClassVar[int] = 3

    #: Default pre-built plans directory (shipped with the package).
    DEFAULT_PREBUILT_DIR: ClassVar[Path] = (
        Path(__file__).parent / "extraction_plans" / "_prebuilt"
    )

    def __init__(
        self,
        plans_dir: Optional[Path] = None,
        prebuilt_dir: Optional[Path] = None,
    ) -> None:
        super().__init__(plans_dir=plans_dir, index_filename="extraction_registry.json")
        self._prebuilt_dir: Path = prebuilt_dir or self.DEFAULT_PREBUILT_DIR
        self._registry_loaded: bool = False

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    async def load_with_prebuilt(self) -> None:
        """Load the registry index and all pre-built plans from disk.

        Safe to call multiple times — subsequent calls are no-ops.
        Pre-built plans are only registered if they are not already in the
        index (identified by fingerprint) to avoid overwriting cached plans.
        """
        if self._registry_loaded:
            return
        await self.load()
        await self.load_prebuilt(self._prebuilt_dir)
        self._registry_loaded = True

    # ------------------------------------------------------------------
    # Plan I/O
    # ------------------------------------------------------------------

    async def register_extraction_plan(self, plan: ExtractionPlan) -> None:
        """Register an ExtractionPlan in the registry.

        Saves the plan as a JSON file named ``<fingerprint>.json`` and
        registers it in the index.

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
            The ExtractionPlan if found, ``None`` otherwise.
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

        Performs lazy initialisation on the first call: loads the registry
        index and all pre-built plans from disk.  Uses the 3-tier URL lookup
        from ``BasePlanRegistry`` to find a matching registry entry, then
        loads the plan JSON from disk.

        Args:
            url: URL to look up.

        Returns:
            ExtractionPlan if found in registry or pre-built plans, ``None``
            otherwise.
        """
        await self.load_with_prebuilt()
        entry = self.lookup(url)
        if entry is None:
            return None
        return await self.load_plan(entry.fingerprint)

    # ------------------------------------------------------------------
    # Lifecycle tracking (persisted via consecutive_failures in the index)
    # ------------------------------------------------------------------

    async def record_success(self, fingerprint: str) -> None:
        """Record a successful extraction and reset the consecutive failure count.

        Also updates ``last_used_at`` and increments ``use_count`` in the
        registry index.

        Args:
            fingerprint: The plan fingerprint.
        """
        async with self._lock:
            entry = self._entries.get(fingerprint)
            if entry is not None:
                entry.consecutive_failures = 0
                entry.last_used_at = datetime.now(timezone.utc)
                entry.use_count += 1
                await self._save_index()
        self.logger.debug("Recorded success for fingerprint=%s", fingerprint)

    async def record_failure(self, fingerprint: str) -> None:
        """Record a failed extraction. Invalidates after ``FAILURE_THRESHOLD`` failures.

        The failure count is persisted in the registry index so that
        consecutive failures are counted correctly across process restarts.
        When the count reaches ``FAILURE_THRESHOLD``, the plan is removed
        from the registry so that fresh LLM recon can regenerate it.

        Args:
            fingerprint: The plan fingerprint.
        """
        async with self._lock:
            entry = self._entries.get(fingerprint)
            if entry is None:
                self.logger.warning(
                    "record_failure: fingerprint '%s' not in registry", fingerprint
                )
                return
            entry.consecutive_failures += 1
            count = entry.consecutive_failures
            self.logger.warning(
                "Extraction failure %d/%d for fingerprint=%s",
                count,
                self.FAILURE_THRESHOLD,
                fingerprint,
            )
            if count >= self.FAILURE_THRESHOLD:
                self.logger.warning(
                    "Invalidating plan after %d consecutive failures (fingerprint=%s)",
                    count,
                    fingerprint,
                )
                del self._entries[fingerprint]
            await self._save_index()

    # ------------------------------------------------------------------
    # Pre-built plan loading
    # ------------------------------------------------------------------

    async def load_prebuilt(self, directory: Path) -> int:
        """Load pre-built ExtractionPlan JSON files from a directory.

        Each JSON file must be parseable as an ``ExtractionPlan``.  The
        ``source`` field is overridden to ``"developer"`` to mark these as
        developer-curated plans.  Plans whose fingerprint is already in the
        registry are skipped so cached plans are not overwritten.

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
        for json_file in sorted(directory.glob("*.json")):
            try:
                async with aiofiles.open(json_file, "r", encoding="utf-8") as f:
                    raw = await f.read()
                data = json.loads(raw)
                data["source"] = "developer"  # enforce developer source
                plan = ExtractionPlan.model_validate(data)
                # Skip plans already in the registry (cached plans take precedence)
                if plan.fingerprint in self._entries:
                    self.logger.debug(
                        "Pre-built plan '%s' already in registry, skipping",
                        json_file.name,
                    )
                    continue
                await self.register_extraction_plan(plan)
                count += 1
                self.logger.info("Loaded pre-built plan from %s", json_file.name)
            except Exception as exc:
                self.logger.warning(
                    "Failed to load pre-built plan %s: %s", json_file, exc
                )

        return count
