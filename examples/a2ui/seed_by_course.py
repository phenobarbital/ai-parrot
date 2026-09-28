"""FEAT-610 — upsert the interim `polestar_graduates_by_course` slug into PRODUCTION public.queries.

Run: ENV=prod python examples/a2ui/seed_by_course.py --yes
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

import asyncpg

BASE_SLUG = "polestar_graduates_directory"
NEW_SLUG = "polestar_graduates_by_course"
QUERY_RAW = (
    "SELECT {fields} FROM (SELECT d.student_uid, e->>'course' AS course, e->>'category' AS category "
    "FROM polestar.vw_graduates_directory d "
    "CROSS JOIN LATERAL jsonb_array_elements(d.graduation_details) e "
    "WHERE e->>'course' IS NOT NULL) t {where_cond}"
)

logger = logging.getLogger("a2ui.seed_by_course")


def get_dsn() -> str:
    """Return the asyncpg DSN from environment or querysource config."""
    dsn = os.environ.get("QS_ASYNCPG_URL")
    if dsn:
        return dsn
    try:
        from parrot_tools.querysource._qs import default_dsn

        return default_dsn()
    except ImportError:
        pass
    raise RuntimeError(
        "No database connection configured. Set QS_ASYNCPG_URL or install querysource[db]."
    )


async def has_unique_index(conn: asyncpg.Connection, table: str, column: str) -> bool:
    """Check if a unique index exists on the given table column."""
    query = """
        SELECT 1
        FROM pg_indexes
        WHERE tablename = $1
          AND indexdef LIKE '%UNIQUE%'
          AND indexdef LIKE '%' || $2 || '%'
    """
    return await conn.fetchval(query, table, column) is not None


async def seed() -> str:
    """Copy BASE_SLUG's row, swap slug + query_raw, upsert idempotently; return 'inserted' | 'updated'."""
    dsn = get_dsn()
    conn = await asyncpg.connect(dsn)
    try:
        # Check for unique index on query_slug
        has_unique = await has_unique_index(conn, "queries", "query_slug")

        # Fetch the base slug row
        base_row = await conn.fetchrow(
            "SELECT query_slug, query_name, query_raw, query_description, "
            "query_type, is_active, created_by, created_at, updated_at "
            "FROM public.queries WHERE query_slug = $1",
            BASE_SLUG,
        )
        if base_row is None:
            raise RuntimeError(f"Base slug {BASE_SLUG} not found in public.queries")

        # Prepare the new row values
        new_row: dict[str, Any] = {
            "query_slug": NEW_SLUG,
            "query_name": base_row["query_name"].replace(BASE_SLUG, NEW_SLUG) if base_row["query_name"] else NEW_SLUG,
            "query_raw": QUERY_RAW,
            "query_description": base_row["query_description"],
            "query_type": base_row["query_type"],
            "is_active": base_row["is_active"],
            "created_by": base_row["created_by"],
            "created_at": base_row["created_at"],
            "updated_at": base_row["updated_at"],
        }

        if has_unique:
            # Use ON CONFLICT for idempotent upsert
            await conn.execute(
                """
                INSERT INTO public.queries (query_slug, query_name, query_raw, query_description,
                    query_type, is_active, created_by, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (query_slug) DO UPDATE SET
                    query_name = EXCLUDED.query_name,
                    query_raw = EXCLUDED.query_raw,
                    query_description = EXCLUDED.query_description,
                    query_type = EXCLUDED.query_type,
                    is_active = EXCLUDED.is_active,
                    updated_at = EXCLUDED.updated_at
                """,
                new_row["query_slug"],
                new_row["query_name"],
                new_row["query_raw"],
                new_row["query_description"],
                new_row["query_type"],
                new_row["is_active"],
                new_row["created_by"],
                new_row["created_at"],
                new_row["updated_at"],
            )
            # Check if it was an insert or update
            existing = await conn.fetchrow(
                "SELECT updated_at FROM public.queries WHERE query_slug = $1",
                NEW_SLUG,
            )
            if existing and existing["updated_at"] == new_row["updated_at"]:
                return "inserted"
            return "updated"
        else:
            # Fallback: UPDATE then INSERT if no rows affected
            updated = await conn.execute(
                """
                UPDATE public.queries SET
                    query_name = $1,
                    query_raw = $2,
                    query_description = $3,
                    query_type = $4,
                    is_active = $5,
                    updated_at = $6
                WHERE query_slug = $7
                """,
                new_row["query_name"],
                new_row["query_raw"],
                new_row["query_description"],
                new_row["query_type"],
                new_row["is_active"],
                new_row["updated_at"],
                NEW_SLUG,
            )
            if updated == "UPDATE 0":
                await conn.execute(
                    """
                    INSERT INTO public.queries (query_slug, query_name, query_raw, query_description,
                        query_type, is_active, created_by, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    new_row["query_slug"],
                    new_row["query_name"],
                    new_row["query_raw"],
                    new_row["query_description"],
                    new_row["query_type"],
                    new_row["is_active"],
                    new_row["created_by"],
                    new_row["created_at"],
                    new_row["updated_at"],
                )
                return "inserted"
            return "updated"
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="confirm the write to production public.queries")
    args = parser.parse_args(argv)
    if not args.yes:
        print(f"Refusing to write {NEW_SLUG} to production public.queries without --yes.")
        return 2
    try:
        result = asyncio.run(seed())
        print(result)
        return 0
    except Exception as e:
        logger.error("Seed failed: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())