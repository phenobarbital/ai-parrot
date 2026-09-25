"""SchemaStore — SQLiteWikiStore specialisation for schema.db with columns."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import aiosqlite

from parrot.knowledge.wiki.schema.models import ColumnRecord
from parrot.knowledge.wiki.store import SQLitePragmaPolicy
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord

COLUMNS_DDL = """
CREATE TABLE IF NOT EXISTS columns (
    table_id TEXT NOT NULL, ordinal INTEGER NOT NULL, name TEXT NOT NULL, data_type TEXT NOT NULL,
    nullable INTEGER NOT NULL DEFAULT 1, dflt TEXT, comment TEXT, is_primary_key INTEGER NOT NULL DEFAULT 0,
    fk_target TEXT, PRIMARY KEY (table_id, name));
CREATE INDEX IF NOT EXISTS idx_columns_name ON columns(name);
CREATE INDEX IF NOT EXISTS idx_columns_fk ON columns(fk_target);
"""


class SchemaStore(SQLiteWikiStore):
    """SQLiteWikiStore specialisation for schema.db with a columns side table."""

    COLUMNS_DDL = COLUMNS_DDL

    def __init__(
        self,
        db_path: str | Path,
        wiki_name: str = "schema",
        *,
        read_only: bool = False,
        sqlite_policy: Optional[SQLitePragmaPolicy] = None,
        persistent_writer: bool = False,
    ) -> None:
        """Initialize a schema store."""
        super().__init__(
            db_path=db_path,
            wiki_name=wiki_name,
            read_only=read_only,
            sqlite_policy=sqlite_policy,
            persistent_writer=persistent_writer,
        )

    async def _ensure_columns_table(self, conn: aiosqlite.Connection) -> None:
        """Create the columns side table lazily."""
        for statement in COLUMNS_DDL.split(";"):
            if statement.strip():
                await conn.execute(statement)

    @staticmethod
    def _column_from_row(row: aiosqlite.Row) -> ColumnRecord:
        """Build a column record from a side-table row."""
        return ColumnRecord(
            table_id=row["table_id"],
            ordinal=row["ordinal"],
            name=row["name"],
            data_type=row["data_type"],
            nullable=bool(row["nullable"]),
            default=row["dflt"],
            comment=row["comment"],
            is_primary_key=bool(row["is_primary_key"]),
            fk_target=row["fk_target"],
        )

    async def _replace_columns_conn(
        self,
        conn: aiosqlite.Connection,
        columns: list[ColumnRecord],
        table_ids: set[str],
    ) -> int:
        """Replace all column rows for the supplied table ids."""
        await self._ensure_columns_table(conn)
        for table_id in table_ids:
            await conn.execute("DELETE FROM columns WHERE table_id = ?", (table_id,))
        rows = [
            (
                column.table_id,
                column.ordinal,
                column.name,
                column.data_type,
                int(column.nullable),
                column.default,
                column.comment,
                int(column.is_primary_key),
                column.fk_target,
            )
            for column in columns
        ]
        if rows:
            await conn.executemany("INSERT INTO columns VALUES (?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    async def upsert_columns(self, columns: list[ColumnRecord]) -> int:
        """Replace all rows of each table id present in ``columns``."""
        self._assert_writable()
        async with self._write("upsert_columns") as conn:
            return await self._replace_columns_conn(conn, columns, {column.table_id for column in columns})

    async def columns_for(self, table_id: str) -> list[ColumnRecord]:
        """Return columns for one table ordered by ordinal."""
        async with self._read() as conn:
            async with conn.execute(
                "SELECT * FROM columns WHERE table_id = ? ORDER BY ordinal",
                (table_id,),
            ) as cur:
                return [self._column_from_row(row) for row in await cur.fetchall()]

    async def find_columns(
        self,
        name: Optional[str] = None,
        fk_target_prefix: Optional[str] = None,
        limit: int = 50,
    ) -> list[ColumnRecord]:
        """Find columns by name substring and/or foreign-key target prefix."""
        clauses: list[str] = []
        params: list[Any] = []
        if name is not None:
            clauses.append("name LIKE ?")
            params.append(f"%{name}%")
        if fk_target_prefix is not None:
            clauses.append("fk_target LIKE ?")
            params.append(f"{fk_target_prefix}%")
        sql = "SELECT * FROM columns"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY table_id, ordinal LIMIT ?"
        params.append(limit)
        async with self._read() as conn:
            async with conn.execute(sql, params) as cur:
                return [self._column_from_row(row) for row in await cur.fetchall()]

    async def _replace_source_slice_conn(
        self,
        conn: aiosqlite.Connection,
        source_id: str,
        pages: list[WikiPageRecord],
        edges: list[tuple[str, str, str]],
    ) -> dict[str, int]:
        """Replace a page slice using an existing transaction."""
        new_ids = {page.concept_id for page in pages}
        async with conn.execute("SELECT concept_id FROM pages WHERE source_id = ?", (source_id,)) as cur:
            old_ids = [row["concept_id"] for row in await cur.fetchall()]

        preserved: list[tuple[str, str, str]] = []
        if old_ids:
            old_set = set(old_ids)
            placeholders = ",".join("?" for _ in old_ids)
            async with conn.execute(
                "SELECT src, dst, rel FROM edges WHERE dst IN (" + placeholders + ")",
                old_ids,
            ) as cur:
                preserved = [
                    (row["src"], row["dst"], row["rel"])
                    for row in await cur.fetchall()
                    if row["src"] not in old_set and row["dst"] in new_ids
                ]
            await conn.executemany("DELETE FROM embeddings WHERE concept_id = ?", [(cid,) for cid in old_ids])
            await conn.executemany("DELETE FROM edges WHERE src = ? OR dst = ?", [(cid, cid) for cid in old_ids])
            await conn.execute("DELETE FROM pages WHERE source_id = ?", (source_id,))

        await conn.execute("DELETE FROM symbols WHERE source_id = ?", (source_id,))
        await self._upsert_pages_conn(conn, pages)
        await self._insert_edges_conn(conn, edges)
        if preserved:
            await self._insert_edges_conn(conn, preserved)
        return {"pages_deleted": len(old_ids), "pages_written": len(pages), "edges_written": len(edges)}

    async def replace_schema_slice(
        self,
        origin: str,
        pages: list[WikiPageRecord],
        columns: list[ColumnRecord],
        edges: list[tuple[str, str, str, str]],
    ) -> dict[str, Any]:
        """Replace schema pages, edges, and columns atomically."""
        self._assert_writable()
        new_table_ids = {page.concept_id for page in pages if page.category == "table"}
        normalized_edges = [(src, dst, rel) for src, dst, rel, _provenance in edges]
        async with self._write("replace_schema_slice") as conn:
            await self._ensure_columns_table(conn)
            async with conn.execute(
                "SELECT concept_id FROM pages WHERE source_id = ? AND category = 'table'",
                (f"schema:{origin}",),
            ) as cur:
                old_table_ids = {row["concept_id"] for row in await cur.fetchall()}
            report = await self._replace_source_slice_conn(
                conn,
                f"schema:{origin}",
                pages,
                normalized_edges,
            )
            report["columns_written"] = await self._replace_columns_conn(
                conn,
                columns,
                old_table_ids | new_table_ids,
            )
        return report
