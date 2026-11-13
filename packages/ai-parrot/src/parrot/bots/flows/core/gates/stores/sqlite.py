"""SQLite gate store — default local backend (FEAT-890 M2)."""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from ..models import GateRecord


class SQLiteGateStore:
    """GateStore on one SQLite file; schema created on first use."""

    def __init__(self, path: Path) -> None:
        """Initialize the store at the supplied SQLite database path."""
        self.path = Path(path)
        self.logger = logging.getLogger(__name__)

    async def _initialize(self, connection: aiosqlite.Connection) -> None:
        """Create the durable gate table when it does not already exist."""
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gates (
                gate_id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                status TEXT NOT NULL,
                opened_at REAL NOT NULL,
                body TEXT NOT NULL
            )
            """
        )
        await connection.commit()

    async def put(self, record: GateRecord) -> None:
        """Upsert one complete gate record."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as connection:
            await self._initialize(connection)
            await connection.execute(
                """
                INSERT INTO gates (gate_id, owner, status, opened_at, body)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(gate_id) DO UPDATE SET
                    owner = excluded.owner,
                    status = excluded.status,
                    opened_at = excluded.opened_at,
                    body = excluded.body
                """,
                (record.gate_id, record.owner, record.status, record.opened_at, record.model_dump_json()),
            )
            await connection.commit()

    async def get(self, gate_id: str) -> GateRecord | None:
        """Return the gate record identified by ``gate_id``, if present."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as connection:
            await self._initialize(connection)
            async with connection.execute("SELECT body FROM gates WHERE gate_id = ?", (gate_id,)) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return GateRecord.model_validate_json(row[0])

    async def pending(self, owner: str | None = None) -> list[GateRecord]:
        """Return chronologically ordered pending records, optionally for one owner."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        query = "SELECT body FROM gates WHERE status = ?"
        parameters: tuple[str, ...] = ("pending",)
        if owner is not None:
            query += " AND owner = ?"
            parameters = ("pending", owner)
        query += " ORDER BY opened_at"

        async with aiosqlite.connect(self.path) as connection:
            await self._initialize(connection)
            async with connection.execute(query, parameters) as cursor:
                rows = await cursor.fetchall()
        return [GateRecord.model_validate_json(row[0]) for row in rows]
