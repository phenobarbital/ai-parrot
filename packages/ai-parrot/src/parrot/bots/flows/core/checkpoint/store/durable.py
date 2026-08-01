"""DurableCheckpointStore — sqlite | postgres | mongodb (FEAT-399, TASK-2050).

The durable tier: suspended flows are dumped here for indefinite
recovery; `durable=True` flows write-through on every checkpoint. One
asyncdb-parametrized implementation covering all three drivers (FEAT-147
backend pattern). Storage model: one row/document per checkpoint keyed
`(flow_id, checkpoint_id)`, with `payload` (the ormsgpack bytes from
`FlowStateSerializer`) as the source of truth — the other columns are
indexed metadata mirrored from the checkpoint for cheap filtering
(`list_flows(status=...)`) without decoding every payload.

No TTL/expiry: durability is the point (spec §1 two-tier rationale);
deletion is explicit via `delete_flow` or the HTTP handlers (TASK-2055).

Durable stores are NOT the lease authority — the checkpointer always
takes leases on the ephemeral Redis store (spec §3 Module 6); the lease
methods here raise `NotImplementedError`.

Driver notes (verified empirically against throwaway sqlite/postgres/
mongo instances — the installed asyncdb version's per-driver method
signatures differ enough that this is NOT a copy-paste of
``PostgresResultStorage``):
- **sqlite**: ``execute()`` binds named ``:param`` kwargs; ``fetchrow()``/
  ``fetch_one()`` bind a positional list via the literal ``parameters=``
  kwarg (``?`` placeholders); ``fetch_all()`` wraps arbitrary kwargs into
  a named-parameter dict (``:param`` placeholders again).
- **postgres**: the asyncdb ``pg`` driver's own ``fetch``/``fetchrow``
  are cursor-only (no ``sentence`` argument) in the installed version —
  ``fetch_one``/``fetch_all`` (positional ``$1, $2, ...``) are the
  sentence-taking read methods to use instead.
- **mongodb**: the asyncdb module is named ``mongo`` (not ``mongodb``)
  and requires a ``params`` dict (host/port/database/...) — passing only
  a raw ``dsn=`` string is silently discarded by the driver's DSN
  builder. ``execute(collection, operation, *args, **kwargs)`` dispatches
  to the underlying Motor collection method; ``query()`` supports
  ``sort=``/``limit=`` kwargs and returns ``[docs, error]``.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from asyncdb import AsyncDB
from navconfig.logging import logging

from parrot.bots.flows.core.checkpoint.model import FlowCheckpoint
from parrot.bots.flows.core.checkpoint.serializer import FlowStateSerializer
from parrot.conf import FLOW_CHECKPOINT_DURABLE_STORE

from .base import CheckpointStore

_TABLE = "flow_checkpoints"

# Checkpoint-store driver name -> underlying asyncdb module name.
_ASYNCDB_DRIVER = {
    "sqlite": "sqlite",
    "postgres": "pg",
    "mongodb": "mongo",
}


class DurableCheckpointStore(CheckpointStore):
    """Durable checkpoint tier: one row/document per (flow_id, checkpoint_id).

    Args:
        driver: One of ``"sqlite"``, ``"postgres"``, ``"mongodb"``.
        dsn: Backend DSN; defaults to ``FLOW_CHECKPOINT_DURABLE_STORE``
            then a driver-specific fallback.

    Raises:
        ValueError: If ``driver`` is not a recognized durable backend.
    """

    def __init__(self, driver: str = "sqlite", dsn: str | None = None) -> None:
        if driver not in _ASYNCDB_DRIVER:
            raise ValueError(
                f"Unknown DurableCheckpointStore driver: {driver!r}. "
                f"Valid drivers: {sorted(_ASYNCDB_DRIVER)}"
            )
        self._driver = driver
        self._dsn = dsn or FLOW_CHECKPOINT_DURABLE_STORE or self._default_dsn(driver)
        self._conn: AsyncDB | None = None
        self._table_ready = False
        self._serializer = FlowStateSerializer()
        self.logger = logging.getLogger("parrot.flows.checkpoint.durable")

    @staticmethod
    def _default_dsn(driver: str) -> str:
        if driver == "sqlite":
            return "flow_checkpoints.db"
        if driver == "postgres":
            return "postgres://postgres:postgres@localhost:5432/postgres"
        return "mongodb://localhost:27017/ai_parrot_checkpoints"

    async def _ensure(self) -> AsyncDB:
        """Lazily open the connection and ensure the table/index exists."""
        if self._conn is None:
            asyncdb_driver = _ASYNCDB_DRIVER[self._driver]
            if asyncdb_driver == "mongo":
                parsed = urlparse(self._dsn)
                params: dict[str, Any] = {
                    "host": parsed.hostname or "localhost",
                    "port": parsed.port or 27017,
                    "database": (parsed.path or "").lstrip("/")
                    or "ai_parrot_checkpoints",
                }
                if parsed.username:
                    params["username"] = parsed.username
                if parsed.password:
                    params["password"] = parsed.password
                self._conn = AsyncDB("mongo", dsn=self._dsn, params=params)
            else:
                self._conn = AsyncDB(asyncdb_driver, dsn=self._dsn)
            await self._conn.connection()
        if not self._table_ready:
            await self._ensure_table(self._conn)
            self._table_ready = True
        return self._conn

    async def _ensure_table(self, conn: AsyncDB) -> None:
        """Issue idempotent DDL (SQL drivers) or index creation (Mongo)."""
        if self._driver == "sqlite":
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                "  flow_id TEXT NOT NULL,"
                "  checkpoint_id INTEGER NOT NULL,"
                "  parent_checkpoint_id INTEGER,"
                "  status TEXT NOT NULL,"
                "  flow_name TEXT NOT NULL,"
                "  created_at TEXT NOT NULL,"
                "  lossy INTEGER NOT NULL DEFAULT 0,"
                "  payload BLOB NOT NULL,"
                "  PRIMARY KEY (flow_id, checkpoint_id)"
                ")"
            )
        elif self._driver == "postgres":
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                "  flow_id TEXT NOT NULL,"
                "  checkpoint_id BIGINT NOT NULL,"
                "  parent_checkpoint_id BIGINT,"
                "  status TEXT NOT NULL,"
                "  flow_name TEXT NOT NULL,"
                "  created_at TIMESTAMPTZ NOT NULL,"
                "  lossy BOOLEAN NOT NULL DEFAULT FALSE,"
                "  payload BYTEA NOT NULL,"
                "  PRIMARY KEY (flow_id, checkpoint_id)"
                ")"
            )
        else:  # mongodb
            try:
                await conn.execute(
                    _TABLE,
                    "create_index",
                    [("flow_id", 1), ("checkpoint_id", -1)],
                    unique=True,
                )
            except Exception as exc:  # noqa: BLE001 - index creation must never block startup
                self.logger.warning(
                    "DurableCheckpointStore: failed to ensure Mongo index: %s", exc
                )

    def _decode(self, payload: bytes) -> FlowCheckpoint:
        return FlowCheckpoint.model_validate(self._serializer.decode(payload))

    async def put(self, checkpoint: FlowCheckpoint) -> None:
        """Upsert a checkpoint keyed by ``(flow_id, checkpoint_id)``."""
        conn = await self._ensure()
        payload = self._serializer.encode(checkpoint.model_dump(mode="json"))

        if self._driver == "sqlite":
            await conn.execute(
                f"INSERT INTO {_TABLE} "
                "(flow_id, checkpoint_id, parent_checkpoint_id, status, "
                " flow_name, created_at, lossy, payload) "
                "VALUES (:flow_id, :checkpoint_id, :parent_checkpoint_id, "
                " :status, :flow_name, :created_at, :lossy, :payload) "
                "ON CONFLICT (flow_id, checkpoint_id) DO UPDATE SET "
                "parent_checkpoint_id=excluded.parent_checkpoint_id, "
                "status=excluded.status, flow_name=excluded.flow_name, "
                "created_at=excluded.created_at, lossy=excluded.lossy, "
                "payload=excluded.payload",
                flow_id=checkpoint.flow_id,
                checkpoint_id=checkpoint.checkpoint_id,
                parent_checkpoint_id=checkpoint.parent_checkpoint_id,
                status=checkpoint.status,
                flow_name=checkpoint.flow_name,
                created_at=checkpoint.created_at.isoformat(),
                lossy=int(checkpoint.lossy),
                payload=payload,
            )
        elif self._driver == "postgres":
            await conn.execute(
                f"INSERT INTO {_TABLE} "
                "(flow_id, checkpoint_id, parent_checkpoint_id, status, "
                " flow_name, created_at, lossy, payload) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
                "ON CONFLICT (flow_id, checkpoint_id) DO UPDATE SET "
                "parent_checkpoint_id = EXCLUDED.parent_checkpoint_id, "
                "status = EXCLUDED.status, flow_name = EXCLUDED.flow_name, "
                "created_at = EXCLUDED.created_at, lossy = EXCLUDED.lossy, "
                "payload = EXCLUDED.payload",
                checkpoint.flow_id,
                checkpoint.checkpoint_id,
                checkpoint.parent_checkpoint_id,
                checkpoint.status,
                checkpoint.flow_name,
                checkpoint.created_at,
                checkpoint.lossy,
                payload,
            )
        else:  # mongodb
            doc = {
                "flow_id": checkpoint.flow_id,
                "checkpoint_id": checkpoint.checkpoint_id,
                "parent_checkpoint_id": checkpoint.parent_checkpoint_id,
                "status": checkpoint.status,
                "flow_name": checkpoint.flow_name,
                "created_at": checkpoint.created_at,
                "lossy": checkpoint.lossy,
                "payload": payload,
            }
            await conn.execute(
                _TABLE,
                "update_one",
                {"flow_id": checkpoint.flow_id, "checkpoint_id": checkpoint.checkpoint_id},
                {"$set": doc},
                upsert=True,
            )

    async def latest(self, flow_id: str) -> FlowCheckpoint | None:
        """Return the checkpoint with the highest ``checkpoint_id`` for a flow."""
        conn = await self._ensure()

        if self._driver == "sqlite":
            row = await conn.fetchrow(
                f"SELECT payload FROM {_TABLE} WHERE flow_id = ? "
                "ORDER BY checkpoint_id DESC LIMIT 1",
                parameters=[flow_id],
            )
            if not row:
                return None
            return self._decode(row[0])
        elif self._driver == "postgres":
            row = await conn.fetch_one(
                f"SELECT payload FROM {_TABLE} WHERE flow_id = $1 "
                "ORDER BY checkpoint_id DESC LIMIT 1",
                flow_id,
            )
            if not row:
                return None
            return self._decode(row["payload"])
        else:  # mongodb
            docs, error = await conn.query(
                _TABLE, {"flow_id": flow_id}, sort=[("checkpoint_id", -1)], limit=1
            )
            if error or not docs:
                return None
            return self._decode(docs[0]["payload"])

    async def get(self, flow_id: str, checkpoint_id: int) -> FlowCheckpoint | None:
        """Return a specific checkpoint by id."""
        conn = await self._ensure()

        if self._driver == "sqlite":
            row = await conn.fetchrow(
                f"SELECT payload FROM {_TABLE} "
                "WHERE flow_id = ? AND checkpoint_id = ?",
                parameters=[flow_id, checkpoint_id],
            )
            if not row:
                return None
            return self._decode(row[0])
        elif self._driver == "postgres":
            row = await conn.fetch_one(
                f"SELECT payload FROM {_TABLE} "
                "WHERE flow_id = $1 AND checkpoint_id = $2",
                flow_id,
                checkpoint_id,
            )
            if not row:
                return None
            return self._decode(row["payload"])
        else:  # mongodb
            docs, error = await conn.query(
                _TABLE, {"flow_id": flow_id, "checkpoint_id": checkpoint_id}, limit=1
            )
            if error or not docs:
                return None
            return self._decode(docs[0]["payload"])

    async def history(self, flow_id: str, limit: int = 10) -> list[FlowCheckpoint]:
        """Return the checkpoint history for a flow, newest first."""
        conn = await self._ensure()

        if self._driver == "sqlite":
            rows = await conn.fetch_all(
                f"SELECT payload FROM {_TABLE} WHERE flow_id = :flow_id "
                "ORDER BY checkpoint_id DESC LIMIT :limit",
                flow_id=flow_id,
                limit=limit,
            )
            return [self._decode(row[0]) for row in (rows or [])]
        elif self._driver == "postgres":
            rows = await conn.fetch_all(
                f"SELECT payload FROM {_TABLE} WHERE flow_id = $1 "
                "ORDER BY checkpoint_id DESC LIMIT $2",
                flow_id,
                limit,
            )
            return [self._decode(row["payload"]) for row in (rows or [])]
        else:  # mongodb
            docs, error = await conn.query(
                _TABLE,
                {"flow_id": flow_id},
                sort=[("checkpoint_id", -1)],
                limit=limit,
            )
            if error:
                return []
            return [self._decode(doc["payload"]) for doc in docs]

    async def list_flows(self, status: str | None = None) -> list[dict[str, Any]]:
        """List flows using each flow's latest checkpoint, optionally by status."""
        conn = await self._ensure()

        if self._driver == "sqlite":
            sql = (
                f"SELECT flow_id, checkpoint_id, flow_name, status FROM {_TABLE} t1 "
                f"WHERE checkpoint_id = (SELECT MAX(checkpoint_id) FROM {_TABLE} t2 "
                "WHERE t2.flow_id = t1.flow_id)"
            )
            kwargs: dict[str, Any] = {}
            if status is not None:
                sql += " AND status = :status"
                kwargs["status"] = status
            rows = await conn.fetch_all(sql, **kwargs)
            return [
                {
                    "flow_id": row[0],
                    "checkpoint_id": row[1],
                    "flow_name": row[2],
                    "status": row[3],
                }
                for row in (rows or [])
            ]
        elif self._driver == "postgres":
            sql = (
                f"SELECT flow_id, checkpoint_id, flow_name, status FROM {_TABLE} t1 "
                f"WHERE checkpoint_id = (SELECT MAX(checkpoint_id) FROM {_TABLE} t2 "
                "WHERE t2.flow_id = t1.flow_id)"
            )
            params: list[Any] = []
            if status is not None:
                sql += " AND status = $1"
                params.append(status)
            rows = await conn.fetch_all(sql, *params)
            return [
                {
                    "flow_id": row["flow_id"],
                    "checkpoint_id": row["checkpoint_id"],
                    "flow_name": row["flow_name"],
                    "status": row["status"],
                }
                for row in (rows or [])
            ]
        else:  # mongodb
            flow_ids, error = await conn.execute(_TABLE, "distinct", "flow_id")
            if error or not flow_ids:
                return []
            flows: list[dict[str, Any]] = []
            for flow_id in flow_ids:
                docs, err = await conn.query(
                    _TABLE, {"flow_id": flow_id}, sort=[("checkpoint_id", -1)], limit=1
                )
                if err or not docs:
                    continue
                doc = docs[0]
                if status is not None and doc.get("status") != status:
                    continue
                flows.append(
                    {
                        "flow_id": doc["flow_id"],
                        "checkpoint_id": doc["checkpoint_id"],
                        "flow_name": doc["flow_name"],
                        "status": doc["status"],
                    }
                )
            return flows

    async def delete_flow(self, flow_id: str) -> None:
        """Delete every checkpoint for a flow."""
        conn = await self._ensure()

        if self._driver == "sqlite":
            await conn.execute(
                f"DELETE FROM {_TABLE} WHERE flow_id = :flow_id", flow_id=flow_id
            )
        elif self._driver == "postgres":
            await conn.execute(f"DELETE FROM {_TABLE} WHERE flow_id = $1", flow_id)
        else:  # mongodb
            await conn.execute(_TABLE, "delete_many", {"flow_id": flow_id})

    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        """Durable stores are not the lease authority.

        Raises:
            NotImplementedError: Always — the checkpointer always takes
                leases on the ephemeral Redis store (spec §3 Module 6).
        """
        raise NotImplementedError("lease requires the redis store")

    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        """Durable stores are not the lease authority.

        Raises:
            NotImplementedError: Always — see :meth:`acquire_lease`.
        """
        raise NotImplementedError("lease requires the redis store")

    async def release_lease(self, flow_id: str, holder: str) -> None:
        """Durable stores are not the lease authority.

        Raises:
            NotImplementedError: Always — see :meth:`acquire_lease`.
        """
        raise NotImplementedError("lease requires the redis store")

    async def close(self) -> None:
        """Release the underlying connection. Safe to call multiple times."""
        if self._conn is not None:
            try:
                await self._conn.close()
            finally:
                self._conn = None
                self._table_ready = False
