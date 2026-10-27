"""Signed served ledger with fail-closed durable persistence."""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any, Awaitable, Callable

from parrot.interagent import ServedLedgerEntry
from parrot.security.audit_ledger import AbstractKMSSigner

Sink = Callable[[str], Awaitable[None]]


class LedgerUnavailable(Exception):
    """Indicate that a required durable ledger commit failed."""


class ServedLedger:
    """Sign served entries and retain only successfully acknowledged records."""

    def __init__(self, signer: AbstractKMSSigner, sink: Sink | None = None, *, max_entries: int = 10_000) -> None:
        """Initialize the ledger.

        Args:
            signer: Asynchronous signer used for every entry.
            sink: Optional durable JSON storage callable.
            max_entries: Maximum number of signed entries retained in memory.
        """
        self._signer = signer
        self._sink = sink
        self._recent: deque[ServedLedgerEntry] = deque(maxlen=max_entries)
        self.logger = logging.getLogger(__name__)

    @property
    def durable(self) -> bool:
        """Return whether a durable sink is configured."""
        return self._sink is not None

    async def append(self, entry: ServedLedgerEntry, *, required: bool = True) -> ServedLedgerEntry:
        """Sign and durably commit an entry before acknowledging it.

        Args:
            entry: Unsigned served-ledger record.
            required: Whether a sink failure must prevent acknowledgment.

        Returns:
            The signed entry.

        Raises:
            LedgerUnavailable: If a required durable commit fails.
        """
        signature = await self._signer.sign(entry.canonical_bytes())
        signed = entry.model_copy(update={"signature": signature})
        if self._sink is not None:
            try:
                await self._sink(signed.model_dump_json())
            except Exception as exc:  # noqa: BLE001 - sink implementations can raise arbitrary transport errors
                if required:
                    raise LedgerUnavailable(str(exc)) from exc
                self.logger.error("ServedLedger: sink failed (not required): %s", exc)
        self._recent.append(signed)
        return signed

    async def verify(self, entry: ServedLedgerEntry) -> bool:
        """Verify an entry signature against its canonical bytes."""
        return await self._signer.verify(entry.canonical_bytes(), entry.signature)

    def recent(self, *, limit: int = 100) -> list[ServedLedgerEntry]:
        """Return at most the newest ``limit`` retained entries."""
        if limit <= 0:
            return []
        return list(self._recent)[-limit:]


def postgres_ledger_sink(dsn_or_pool: str | Any, *, table: str = "squawk_served_ledger") -> Sink:
    """Build an asyncpg sink that inserts signed entries idempotently.

    Args:
        dsn_or_pool: PostgreSQL DSN or an existing asyncpg-compatible pool.
        table: Destination table created by ``squawk_served_ledger.sql``.

    Returns:
        An asynchronous JSON storage callable.
    """
    import asyncpg

    state: dict[str, Any] = {"pool": None if isinstance(dsn_or_pool, str) else dsn_or_pool}
    query = f"""
        INSERT INTO {table} (
            entry_id, created_at, caller, cap_id, category, contract_hash,
            args_digest, status, result_kind, result_digest, cost, backing,
            trace_id, correlation_id, signature, raw
        ) VALUES (
            $1, $2::timestamptz, $3::jsonb, $4, $5, $6,
            $7, $8, $9, $10, $11::jsonb, $12,
            $13, $14, $15, $16::jsonb
        )
        ON CONFLICT (entry_id) DO NOTHING
    """

    async def sink(payload: str) -> None:
        """Insert one serialized ``ServedLedgerEntry`` into PostgreSQL."""
        if state["pool"] is None:
            state["pool"] = await asyncpg.create_pool(dsn_or_pool)
        row = json.loads(payload)
        async with state["pool"].acquire() as connection:
            await connection.execute(
                query,
                row["entry_id"],
                row["created_at"],
                json.dumps(row["caller"]),
                row["cap_id"],
                row["category"],
                row["contract_hash"],
                row["args_digest"],
                row["status"],
                row["result_kind"],
                row["result_digest"],
                json.dumps(row["cost"]),
                row["backing"],
                row["trace_id"],
                row["correlation_id"],
                row["signature"],
                payload,
            )

    return sink
