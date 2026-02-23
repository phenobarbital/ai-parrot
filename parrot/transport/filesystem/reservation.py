"""ReservationManager — cooperative resource reservations via filesystem."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 300.0  # 5 minutes


class ReservationManager:
    """Cooperative resource reservation using JSON files on the filesystem.

    Agents declare which resources they are working on so others can avoid
    collisions. Reservations are advisory (cooperative), not enforced at
    OS level. They use all-or-nothing semantics: if any requested resource
    is held by another agent, the entire acquisition fails.

    Resource paths are hashed to SHA-256 prefix filenames to avoid
    filesystem path issues.

    Args:
        reservations_dir: Path to the reservations directory.
        agent_id: The agent ID that owns reservations from this manager.
    """

    def __init__(self, reservations_dir: Path, agent_id: str) -> None:
        self._dir = reservations_dir
        self._agent_id = agent_id

    def _reservation_path(self, resource: str) -> Path:
        """Return the file path for a resource reservation.

        Args:
            resource: The resource identifier to hash.

        Returns:
            Path to the reservation JSON file.
        """
        h = hashlib.sha256(resource.encode()).hexdigest()[:16]
        return self._dir / f"{h}.json"

    async def acquire(
        self,
        paths: List[str],
        reason: str = "",
        timeout: Optional[float] = None,
    ) -> bool:
        """Acquire reservations on a list of resources (all-or-nothing).

        If any resource is held by another agent and not expired, the
        entire acquisition fails and no reservations are written.

        The same agent can re-acquire a resource it already holds.

        Args:
            paths: List of resource identifiers to reserve.
            reason: Human-readable reason for the reservation.
            timeout: TTL in seconds for the reservation. Defaults to
                ``_DEFAULT_TIMEOUT``.

        Returns:
            True if all resources were acquired, False if any conflict.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        if timeout is None:
            timeout = _DEFAULT_TIMEOUT
        now = time.time()

        # Phase 1: check all resources for conflicts.
        for resource in paths:
            existing = await self._read_reservation(resource)
            if existing is None:
                continue
            # Same agent can re-acquire.
            if existing.get("agent_id") == self._agent_id:
                continue
            # Check expiration.
            expires_at = existing.get("expires_at", 0)
            if expires_at and now > expires_at:
                continue  # Expired — treat as available.
            # Conflict: another agent holds this resource.
            logger.debug(
                "Reservation conflict on %r: held by %s",
                resource,
                existing.get("agent_id"),
            )
            return False

        # Phase 2: write all reservations.
        for resource in paths:
            data = {
                "resource": resource,
                "agent_id": self._agent_id,
                "reason": reason,
                "acquired_at": now,
                "expires_at": now + timeout,
            }
            await self._write_reservation(resource, data)
        logger.debug(
            "Agent %s acquired reservations on %d resources",
            self._agent_id,
            len(paths),
        )
        return True

    async def release(self, paths: List[str]) -> None:
        """Release reservations on specific resources.

        Only removes reservation files owned by this agent.

        Args:
            paths: List of resource identifiers to release.
        """
        for resource in paths:
            res_path = self._reservation_path(resource)
            existing = await self._read_reservation(resource)
            if existing is not None and existing.get("agent_id") == self._agent_id:
                try:
                    res_path.unlink()
                except FileNotFoundError:
                    pass
        logger.debug("Agent %s released %d reservations", self._agent_id, len(paths))

    async def release_all(self) -> None:
        """Release all reservations owned by this agent."""
        if not self._dir.exists():
            return
        for path in self._dir.iterdir():
            if path.suffix != ".json" or path.name.startswith("."):
                continue
            data = await self._read_path(path)
            if data is not None and data.get("agent_id") == self._agent_id:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        logger.debug("Agent %s released all reservations", self._agent_id)

    async def list_active(self) -> List[Dict[str, Any]]:
        """List all non-expired reservations.

        Returns:
            List of reservation dicts that have not expired.
        """
        if not self._dir.exists():
            return []
        now = time.time()
        results: List[Dict[str, Any]] = []
        for path in self._dir.iterdir():
            if path.suffix != ".json" or path.name.startswith("."):
                continue
            data = await self._read_path(path)
            if data is None:
                continue
            expires_at = data.get("expires_at", 0)
            if expires_at and now > expires_at:
                continue  # Expired.
            results.append(data)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _write_reservation(
        self, resource: str, data: Dict[str, Any]
    ) -> None:
        """Write reservation data using write-then-rename for atomicity."""
        self._dir.mkdir(parents=True, exist_ok=True)
        target = self._reservation_path(resource)
        tmp_path = target.with_suffix(".tmp")
        async with aiofiles.open(tmp_path, "w") as f:
            await f.write(json.dumps(data, indent=2))
        tmp_path.rename(target)

    async def _read_reservation(
        self, resource: str
    ) -> Optional[Dict[str, Any]]:
        """Read reservation data for a resource."""
        return await self._read_path(self._reservation_path(resource))

    async def _read_path(self, path: Path) -> Optional[Dict[str, Any]]:
        """Read and parse a reservation JSON file."""
        try:
            async with aiofiles.open(path, "r") as f:
                content = await f.read()
            return json.loads(content)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.debug("Failed to read reservation %s: %s", path, exc)
            return None
