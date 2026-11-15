"""Redis gate store (FEAT-890 M2)."""

from __future__ import annotations

import logging
from typing import Any

from ..models import GateRecord


class RedisGateStore:
    """GateStore over an async Redis client."""

    def __init__(self, client: Any, *, prefix: str = "parrot:gates") -> None:
        """Initialize the store with an injected async Redis client."""
        self.client = client
        self.prefix = prefix
        self.logger = logging.getLogger(__name__)

    def _key(self, gate_id: str) -> str:
        """Return the Redis key for one gate record."""
        return f"{self.prefix}:{gate_id}"

    def _pending_key(self, owner: str | None = None) -> str:
        """Return the global or owner-specific pending-set key."""
        if owner is None:
            return f"{self.prefix}:pending"
        return f"{self.prefix}:pending:{owner}"

    async def put(self, record: GateRecord) -> None:
        """Write the record and maintain pending sets (global + per owner)."""
        await self.client.set(self._key(record.gate_id), record.model_dump_json())
        if record.status == "pending":
            await self.client.sadd(self._pending_key(), record.gate_id)
            await self.client.sadd(self._pending_key(record.owner), record.gate_id)
            return

        await self.client.srem(self._pending_key(), record.gate_id)
        await self.client.srem(self._pending_key(record.owner), record.gate_id)

    async def get(self, gate_id: str) -> GateRecord | None:
        """Return the record or None."""
        payload = await self.client.get(self._key(gate_id))
        if payload is None:
            return None
        return GateRecord.model_validate_json(payload)

    async def pending(self, owner: str | None = None) -> list[GateRecord]:
        """Return pending records, optionally for one owner, ordered by opened_at."""
        gate_ids = await self.client.smembers(self._pending_key(owner))
        records: list[GateRecord] = []
        for gate_id in gate_ids:
            if isinstance(gate_id, bytes):
                gate_id = gate_id.decode("utf-8")
            record = await self.get(gate_id)
            if record is not None and record.status == "pending":
                records.append(record)
        return sorted(records, key=lambda record: record.opened_at)
