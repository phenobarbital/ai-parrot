"""FEAT-610 — upsert the interim `polestar_graduates_by_course` slug into PRODUCTION public.queries.

Run: ENV=prod python examples/a2ui/seed_by_course.py --yes
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

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
    raise RuntimeError("No database connection configured. Set QS_ASYNCPG_URL or install querysource[db].")


# A single-column, non-partial UNIQUE index on public.queries(query_slug) — exactly what ON CONFLICT (query_slug) needs.
UNIQUE_SLUG_INDEX_SQL = """
SELECT 1
FROM pg_index i
JOIN pg_class c ON c.oid = i.indrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0]
WHERE n.nspname = 'public' AND c.relname = 'queries' AND a.attname = 'query_slug'
  AND i.indisunique AND i.indnatts = 1 AND i.indpred IS NULL
"""

BASE_ROW_SQL = (
    "SELECT query_slug, query_name, query_raw, query_description, query_type, is_active, created_by, created_at "
    "FROM public.queries WHERE query_slug = $1"
)

# `xmax = 0` is true only for a freshly inserted row, so RETURNING tells insert from update without a second query.
UPSERT_SQL = """
INSERT INTO public.queries (query_slug, query_name, query_raw, query_description,
    query_type, is_active, created_by, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
ON CONFLICT (query_slug) DO UPDATE SET
    query_name = EXCLUDED.query_name,
    query_raw = EXCLUDED.query_raw,
    query_description = EXCLUDED.query_description,
    query_type = EXCLUDED.query_type,
    is_active = EXCLUDED.is_active,
    updated_at = now()
RETURNING (xmax = 0) AS inserted
"""

FALLBACK_UPDATE_SQL = """
UPDATE public.queries SET query_name = $2, query_raw = $3, query_description = $4,
    query_type = $5, is_active = $6, updated_at = now()
WHERE query_slug = $1
"""

FALLBACK_INSERT_SQL = """
INSERT INTO public.queries (query_slug, query_name, query_raw, query_description,
    query_type, is_active, created_by, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
"""


async def has_unique_slug_index(conn: asyncpg.Connection) -> bool:
    """Return True when public.queries has a single-column, non-partial unique index on query_slug."""
    return await conn.fetchval(UNIQUE_SLUG_INDEX_SQL) is not None


async def seed(conn: asyncpg.Connection | None = None) -> str:
    """Copy BASE_SLUG's row, swap slug + query_raw and upsert atomically; return 'inserted' | 'updated'.

    The whole operation runs in one transaction under an advisory lock keyed on the slug, so concurrent runs cannot
    both insert (the fallback path has no unique index to protect it).
    """
    own_connection = conn is None
    if conn is None:
        conn = await asyncpg.connect(get_dsn())
    try:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", NEW_SLUG)
            base_row = await conn.fetchrow(BASE_ROW_SQL, BASE_SLUG)
            if base_row is None:
                raise RuntimeError(f"Base slug {BASE_SLUG} not found in public.queries")
            name = base_row["query_name"].replace(BASE_SLUG, NEW_SLUG) if base_row["query_name"] else NEW_SLUG
            values = (
                NEW_SLUG,
                name,
                QUERY_RAW,
                base_row["query_description"],
                base_row["query_type"],
                base_row["is_active"],
                base_row["created_by"],
                base_row["created_at"],
            )
            if await has_unique_slug_index(conn):
                inserted = await conn.fetchval(UPSERT_SQL, *values)
                return "inserted" if inserted else "updated"
            updated = await conn.execute(FALLBACK_UPDATE_SQL, *values[:6])
            if updated == "UPDATE 0":
                await conn.execute(FALLBACK_INSERT_SQL, *values)
                return "inserted"
            return "updated"
    finally:
        if own_connection:
            await conn.close()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: refuses to write without --yes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="confirm the write to production public.queries")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not args.yes:
        logger.error("Refusing to write %s to production public.queries without --yes.", NEW_SLUG)
        return 2
    try:
        result = asyncio.run(seed())
    except Exception as exc:  # noqa: BLE001 - CLI boundary: report and exit non-zero
        logger.error("Seed failed: %s", exc)
        return 1
    logger.info("%s: %s", NEW_SLUG, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
