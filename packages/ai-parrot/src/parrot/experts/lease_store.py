"""Lease-capable SQLite checkpoint store for local expert runs (FEAT-890).

``DurableCheckpointStore`` deliberately is not the lease authority: the
``FlowCheckpointer`` always takes the resume lease on the main store, so a
durable backend alone cannot checkpoint an ``AgentsFlow`` run. That forces
Redis on a laptop-only ``parrot experts run``. This subclass keeps the durable
SQLite storage for checkpoints and adds the three lease methods on a small
sibling SQLite file, so concurrent ``resume`` of one run is still refused —
across processes — without any server.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

from parrot.bots.flows.core.checkpoint.store.durable import DurableCheckpointStore

_LEASE_DDL = (
    "CREATE TABLE IF NOT EXISTS flow_leases ("
    "  flow_id TEXT PRIMARY KEY,"
    "  holder TEXT NOT NULL,"
    "  expires_at REAL NOT NULL"
    ")"
)


class LeaseDurableCheckpointStore(DurableCheckpointStore):
    """SQLite checkpoint store that also owns the resume lease (single machine).

    Args:
        path: SQLite file for the checkpoints. Leases live in ``<path>.leases``.
    """

    def __init__(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(driver="sqlite", dsn=str(path))
        self._lease_path = path.with_name(path.name + ".leases")

    def _connect(self) -> sqlite3.Connection:
        """Open the lease database and make sure its table exists."""
        conn = sqlite3.connect(self._lease_path, timeout=10, isolation_level=None)
        conn.execute(_LEASE_DDL)
        return conn

    def _acquire(self, flow_id: str, holder: str, ttl: int) -> bool:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = time.time()
            row = conn.execute("SELECT holder, expires_at FROM flow_leases WHERE flow_id = ?", (flow_id,)).fetchone()
            if row is not None and row[1] > now and row[0] != holder:
                conn.execute("ROLLBACK")
                return False
            conn.execute(
                "INSERT INTO flow_leases (flow_id, holder, expires_at) VALUES (?, ?, ?) "
                "ON CONFLICT(flow_id) DO UPDATE SET holder = excluded.holder, expires_at = excluded.expires_at",
                (flow_id, holder, now + ttl),
            )
            conn.execute("COMMIT")
            return True
        finally:
            conn.close()

    def _renew(self, flow_id: str, holder: str, ttl: int) -> bool:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = time.time()
            cursor = conn.execute(
                "UPDATE flow_leases SET expires_at = ? WHERE flow_id = ? AND holder = ? AND expires_at > ?",
                (now + ttl, flow_id, holder, now),
            )
            conn.execute("COMMIT")
            return cursor.rowcount == 1
        finally:
            conn.close()

    def _release(self, flow_id: str, holder: str) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM flow_leases WHERE flow_id = ? AND holder = ?", (flow_id, holder))
        finally:
            conn.close()

    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        """Take the lease unless another holder owns an unexpired one."""
        return await asyncio.to_thread(self._acquire, flow_id, holder, ttl)

    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        """Extend the lease only when ``holder`` owns an unexpired one."""
        return await asyncio.to_thread(self._renew, flow_id, holder, ttl)

    async def release_lease(self, flow_id: str, holder: str) -> None:
        """Drop the lease; releasing someone else's lease is a no-op."""
        await asyncio.to_thread(self._release, flow_id, holder)
