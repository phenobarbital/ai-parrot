"""RunRecord registry — memory + Redis mirror (spec §3 Module 7, §7 "Registry keys")."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from parrot.integrations.devloop.models import RunRecord

_TERMINAL = {"completed", "failed", "cancelled"}


class RunRegistry:
    """Keys: hash ``{ns}:runs:{run_id}`` (field ``record`` = RunRecord JSON) and set ``{ns}:runs:live``."""

    def __init__(self, redis: Any, *, retention_seconds: int, namespace: str = "devloop") -> None:
        self._redis = redis
        self._retention = int(retention_seconds)
        self._ns = namespace
        self._records: Dict[str, RunRecord] = {}
        self.logger = logging.getLogger(__name__)

    def _key(self, run_id: str) -> str:
        return f"{self._ns}:runs:{run_id}"

    @property
    def _live_key(self) -> str:
        return f"{self._ns}:runs:live"

    async def save(self, record: RunRecord) -> None:
        """Save a run record — memory first, then Redis.

        Redis errors are logged, never raised: the in-memory copy is
        authoritative for the running bot (spec §7 "Registry keys").

        Args:
            record: The record to persist.
        """
        self._records[record.run_id] = record
        try:
            await self._redis.hset(self._key(record.run_id), mapping={"record": record.model_dump_json()})
            if record.phase not in _TERMINAL:
                await self._redis.sadd(self._live_key, record.run_id)
        except Exception:  # noqa: BLE001 - Redis mirror is best-effort
            self.logger.warning("RunRegistry.save: Redis mirror failed for %s", record.run_id, exc_info=True)

    async def get(self, run_id: str) -> Optional[RunRecord]:
        """Look up a record — memory hit first, else the Redis hash.

        Args:
            run_id: The run to look up.

        Returns:
            The record, or ``None`` if unknown anywhere.
        """
        if run_id in self._records:
            return self._records[run_id]
        try:
            data = await self._redis.hgetall(self._key(run_id))
        except Exception:  # noqa: BLE001 - Redis mirror is best-effort
            self.logger.warning("RunRegistry.get: Redis lookup failed for %s", run_id, exc_info=True)
            return None
        raw = data.get("record") if data else None
        if not raw:
            return None
        record = RunRecord.model_validate_json(raw)
        self._records[run_id] = record
        return record

    async def list_for(self, actor: str) -> List[RunRecord]:
        """Return every known record whose requester matches ``actor``.

        Args:
            actor: A ``Requester.actor`` string (e.g. ``slack:T1:U1``).

        Returns:
            Matching records, newest (``started_at``) first.
        """
        matches = [r for r in self._records.values() if r.requester.actor == actor]
        matches.sort(key=lambda r: r.started_at, reverse=True)
        return matches

    async def live(self) -> List[RunRecord]:
        """Return every live (non-terminal) record.

        Missing hashes (expired/evicted) are dropped with a warning
        rather than raising — used by the service's re-attach on start
        (spec §7 "Re-attach on start", AC13).

        Returns:
            The live records.
        """
        try:
            run_ids = await self._redis.smembers(self._live_key)
        except Exception:  # noqa: BLE001 - Redis mirror is best-effort
            self.logger.warning("RunRegistry.live: Redis lookup failed", exc_info=True)
            return [r for r in self._records.values() if r.phase not in _TERMINAL]

        records: List[RunRecord] = []
        for run_id in run_ids:
            record = await self.get(run_id)
            if record is None:
                self.logger.warning("RunRegistry.live: run %s is in the live set but has no hash", run_id)
                continue
            if record.phase not in _TERMINAL:
                records.append(record)
        return records

    async def mark_terminal(self, run_id: str) -> None:
        """Remove ``run_id`` from the live set and expire its hash.

        The in-memory copy is kept (so ``/devloop status`` still shows it
        until the process restarts).

        Args:
            run_id: The run to mark terminal.
        """
        try:
            await self._redis.srem(self._live_key, run_id)
            await self._redis.expire(self._key(run_id), self._retention)
        except Exception:  # noqa: BLE001 - Redis mirror is best-effort
            self.logger.warning("RunRegistry.mark_terminal: Redis update failed for %s", run_id, exc_info=True)
