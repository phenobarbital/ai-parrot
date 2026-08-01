"""RedisCheckpointStore — ephemeral tier (FEAT-399, TASK-2049).

Per-flow latest pointer, ormsgpack-encoded checkpoint bodies, a bounded
history zset, and a resume lease — all under a ``flowckpt:{flow_id}:*``
key namespace. Every write refreshes the TTL on the flow's data keys
(latest/cp/history); the lease key has its own independent ``PX`` TTL.

Connection pattern copied from ``RedisResultStorage``
(``core/storage/backends/redis.py``, FEAT-147): AsyncDB ``redis``
driver, lazy ``_ensure()``, idempotent ``close()``.

Note: the AsyncDB ``redis`` driver connects with ``decode_responses=True``
(redis-py decodes every reply as UTF-8 text), so the binary ormsgpack
payload from ``FlowStateSerializer`` is base64-encoded to a UTF-8-safe
string before ``SET`` and base64-decoded after ``GET`` — storing raw
ormsgpack bytes directly would raise ``UnicodeDecodeError`` on read.
"""
from __future__ import annotations

import base64
from typing import Any

from asyncdb import AsyncDB
from navconfig.logging import logging

from parrot.bots.flows.core.checkpoint.model import FlowCheckpoint
from parrot.bots.flows.core.checkpoint.serializer import FlowStateSerializer
from parrot.conf import (
    FLOW_CHECKPOINT_HISTORY,
    FLOW_CHECKPOINT_REDIS_TTL,
    REDIS_URL,
)

from .base import CheckpointStore


def _latest_key(flow_id: str) -> str:
    return f"flowckpt:{flow_id}:latest"


def _cp_key(flow_id: str, checkpoint_id: int) -> str:
    return f"flowckpt:{flow_id}:cp:{checkpoint_id}"


def _history_key(flow_id: str) -> str:
    return f"flowckpt:{flow_id}:history"


def _lease_key(flow_id: str) -> str:
    return f"flowckpt:{flow_id}:lease"


class RedisCheckpointStore(CheckpointStore):
    """Ephemeral checkpoint tier: Redis with per-flow TTL + bounded history.

    Args:
        dsn: Redis DSN; defaults to ``REDIS_URL``.
        ttl: Retention TTL in seconds for a flow's data keys; defaults to
            ``FLOW_CHECKPOINT_REDIS_TTL`` (86400s / 24h).
        history: Maximum retained checkpoints per flow; defaults to
            ``FLOW_CHECKPOINT_HISTORY`` (10).
    """

    def __init__(
        self,
        dsn: str | None = None,
        ttl: int | None = None,
        history: int | None = None,
    ) -> None:
        self._dsn = dsn or REDIS_URL
        self._ttl: int = FLOW_CHECKPOINT_REDIS_TTL if ttl is None else ttl
        self._history: int = FLOW_CHECKPOINT_HISTORY if history is None else history
        self._conn: AsyncDB | None = None
        self._serializer = FlowStateSerializer()
        self.logger = logging.getLogger("parrot.flows.checkpoint.redis")

    async def _ensure(self) -> AsyncDB:
        """Lazily open the Redis connection on first use."""
        if self._conn is None:
            self._conn = AsyncDB("redis", dsn=self._dsn)
            await self._conn.connection()
        return self._conn

    def _encode_payload(self, checkpoint: FlowCheckpoint) -> str:
        packed = self._serializer.encode(checkpoint.model_dump(mode="json"))
        return base64.b64encode(packed).decode("ascii")

    def _decode_payload(self, value: str) -> FlowCheckpoint:
        packed = base64.b64decode(value.encode("ascii"))
        payload = self._serializer.decode(packed)
        return FlowCheckpoint.model_validate(payload)

    async def put(self, checkpoint: FlowCheckpoint) -> None:
        """Persist a checkpoint and refresh TTL on the flow's data keys."""
        conn = await self._ensure()
        flow_id = checkpoint.flow_id
        cp_id = checkpoint.checkpoint_id
        value = self._encode_payload(checkpoint)

        await conn.execute("SET", _cp_key(flow_id, cp_id), value, "EX", str(self._ttl))
        await conn.execute("SET", _latest_key(flow_id), str(cp_id), "EX", str(self._ttl))
        await conn.execute("ZADD", _history_key(flow_id), str(cp_id), str(cp_id))
        await conn.execute("EXPIRE", _history_key(flow_id), str(self._ttl))

        # Trim history to N: drop the lowest-score members beyond the
        # retained window. Their `cp:*` keys are left to expire via their
        # own TTL — latest()/history() never reference a trimmed id again.
        await conn.execute(
            "ZREMRANGEBYRANK", _history_key(flow_id), 0, -(self._history + 1)
        )

    async def latest(self, flow_id: str) -> FlowCheckpoint | None:
        """Return the most recent checkpoint for a flow, if any."""
        conn = await self._ensure()
        latest_id = await conn.execute("GET", _latest_key(flow_id))
        if latest_id is None:
            return None
        return await self.get(flow_id, int(latest_id))

    async def get(self, flow_id: str, checkpoint_id: int) -> FlowCheckpoint | None:
        """Return a specific checkpoint by id."""
        conn = await self._ensure()
        raw = await conn.execute("GET", _cp_key(flow_id, checkpoint_id))
        if raw is None:
            return None
        return self._decode_payload(raw)

    async def history(self, flow_id: str, limit: int = 10) -> list[FlowCheckpoint]:
        """Return the retained checkpoint history for a flow, newest first."""
        conn = await self._ensure()
        ids = await conn.execute("ZREVRANGE", _history_key(flow_id), 0, limit - 1)
        checkpoints: list[FlowCheckpoint] = []
        for cp_id in ids or []:
            cp = await self.get(flow_id, int(cp_id))
            if cp is not None:
                checkpoints.append(cp)
        return checkpoints

    async def list_flows(self, status: str | None = None) -> list[dict[str, Any]]:
        """List known flows (via SCAN over ``flowckpt:*:latest``), optionally filtered by status."""
        conn = await self._ensure()
        flows: list[dict[str, Any]] = []
        cursor = "0"
        pattern = "flowckpt:*:latest"
        while True:
            result = await conn.execute(
                "SCAN", cursor, "MATCH", pattern, "COUNT", "100"
            )
            cursor, keys = result[0], result[1]
            for key in keys or []:
                # key shape: flowckpt:{flow_id}:latest
                flow_id = key.split(":")[1]
                cp = await self.latest(flow_id)
                if cp is None:
                    continue
                if status is not None and cp.status != status:
                    continue
                flows.append(
                    {
                        "flow_id": cp.flow_id,
                        "flow_name": cp.flow_name,
                        "status": cp.status,
                        "checkpoint_id": cp.checkpoint_id,
                    }
                )
            if str(cursor) == "0":
                break
        return flows

    async def delete_flow(self, flow_id: str) -> None:
        """Delete every ``flowckpt:{flow_id}:*`` key for a flow."""
        conn = await self._ensure()
        ids = await conn.execute("ZRANGE", _history_key(flow_id), 0, -1)
        keys_to_delete = [_cp_key(flow_id, int(cp_id)) for cp_id in (ids or [])]
        keys_to_delete += [
            _latest_key(flow_id),
            _history_key(flow_id),
            _lease_key(flow_id),
        ]
        await conn.execute("DEL", *keys_to_delete)

    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        """Acquire the resume lease via ``SET key holder NX PX ttl*1000``."""
        conn = await self._ensure()
        result = await conn.execute(
            "SET", _lease_key(flow_id), holder, "NX", "PX", str(ttl * 1000)
        )
        return bool(result)

    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        """Renew the resume lease; only succeeds if ``holder`` currently owns it.

        Note: the ownership check and the renewal ``SET`` are two
        round-trips (not atomic via Lua) — acceptable for v1 per spec §7
        ("Redis lease is advisory... acceptable for v1, matches
        at-least-once semantics").
        """
        conn = await self._ensure()
        current = await conn.execute("GET", _lease_key(flow_id))
        if current != holder:
            return False
        await conn.execute("SET", _lease_key(flow_id), holder, "PX", str(ttl * 1000))
        return True

    async def release_lease(self, flow_id: str, holder: str) -> None:
        """Release the resume lease; a no-op (logged) if not owned by ``holder``."""
        conn = await self._ensure()
        current = await conn.execute("GET", _lease_key(flow_id))
        if current != holder:
            self.logger.warning(
                "release_lease: holder mismatch for flow_id=%s "
                "(requested by %s, held by %s)",
                flow_id,
                holder,
                current,
            )
            return
        await conn.execute("DEL", _lease_key(flow_id))

    async def close(self) -> None:
        """Release the Redis connection. Safe to call multiple times."""
        if self._conn is not None:
            try:
                await self._conn.close()
            finally:
                self._conn = None
