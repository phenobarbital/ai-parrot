"""A2UI finance example — upsert the two ``finance_projection_*`` slugs into PRODUCTION ``public.queries``.

Run: ENV=prod python examples/a2ui_finance/seed_finance.py --dry-run   # print the rows, write nothing
     ENV=prod python examples/a2ui_finance/seed_finance.py --yes       # upsert both slugs (idempotent)

Both slugs read ``troc.finance_projection`` (the table behind ``agents/finance_reporter.py``). The money columns are
cast to ``float8`` INSIDE the slug SQL so any ``sum(...)`` a widget requests through ``fields`` comes back numeric
(a raw ``numeric`` column would reach pandas as ``object`` and fail the linked builder's dtype check).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import asyncpg
from querysource.conf import default_dsn  # writable primary; asyncpg_url is a read-only replica

sys.path.insert(0, str(Path(__file__).resolve().parent))

from finance_dashboard import LATEST_SLUG, PROGRAM, SNAPSHOTS_SLUG  # noqa: E402

logger = logging.getLogger("a2ui_finance.seed")

TABLE = "troc.finance_projection"
_CAST_SELECT = (
    "SELECT snapshot_date, division, project, "
    "rev_actual::float8 AS rev_actual, rev_budget::float8 AS rev_budget, "
    "ebitda_actual::float8 AS ebitda_actual, ebitda_budget::float8 AS ebitda_budget "
    f"FROM {TABLE}"
)
#: ``{fields}`` / ``{where_cond}`` are QuerySource's projection and WHERE placeholders; the subquery alias keeps the
#: GROUP BY / ORDER BY QuerySource appends valid (same shape as examples/a2ui/seed_by_course.py).
SNAPSHOTS_QUERY_RAW = f"SELECT {{fields}} FROM ({_CAST_SELECT}) t {{where_cond}}"
LATEST_QUERY_RAW = (
    f"SELECT {{fields}} FROM ({_CAST_SELECT} WHERE snapshot_date = (SELECT max(snapshot_date) FROM {TABLE})) t "
    "{where_cond}"
)
FIELDS = [
    '"snapshot_date"',
    '"division"',
    '"project"',
    '"rev_actual"',
    '"rev_budget"',
    '"ebitda_actual"',
    '"ebitda_budget"',
]
SLUGS: dict[str, tuple[str, str]] = {
    SNAPSHOTS_SLUG: (
        f"Finance projection: daily budget-variance snapshots per division/project ({TABLE})",
        SNAPSHOTS_QUERY_RAW,
    ),
    LATEST_SLUG: (
        f"Finance projection: rows of the latest snapshot_date only ({TABLE})",
        LATEST_QUERY_RAW,
    ),
}

# A single-column, non-partial UNIQUE index on public.queries(query_slug): what ON CONFLICT (query_slug) needs.
UNIQUE_SLUG_INDEX_SQL = """
SELECT 1
FROM pg_index i
JOIN pg_class c ON c.oid = i.indrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0]
WHERE n.nspname = 'public' AND c.relname = 'queries' AND a.attname = 'query_slug'
  AND i.indisunique AND i.indnatts = 1 AND i.indpred IS NULL
"""
PROGRAM_ID_SQL = (
    "SELECT program_id FROM public.queries WHERE program_slug = $1 AND program_id IS NOT NULL "
    "ORDER BY updated_at DESC NULLS LAST, query_slug LIMIT 1"
)
# The parser of a sibling slug of the SAME program (its provider is the Postgres one the finance SQL needs).
PARSER_SQL = (
    "SELECT parser FROM public.queries WHERE program_slug = $1 AND provider = 'db' AND parser IS NOT NULL "
    "ORDER BY updated_at DESC NULLS LAST, query_slug LIMIT 1"
)
OWNER_SQL = "SELECT program_slug FROM public.queries WHERE query_slug = $1"

COLUMNS = (
    "query_slug",
    "description",
    "query_raw",
    "fields",
    "program_id",
    "program_slug",
    "provider",
    "parser",
    "is_raw",
    "is_cached",
    "cache_timeout",
)
_PLACEHOLDERS = ", ".join(f"${i}" for i in range(1, len(COLUMNS) + 1))
_ASSIGNMENTS = ", ".join(f"{col} = ${i}" for i, col in enumerate(COLUMNS[1:], start=2))

# `xmax = 0` is true only for a freshly inserted row, so RETURNING tells insert from update without a second query.
UPSERT_SQL = f"""
INSERT INTO public.queries ({', '.join(COLUMNS)}, created_at, updated_at)
VALUES ({_PLACEHOLDERS}, now(), now())
ON CONFLICT (query_slug) DO UPDATE SET
    {', '.join(f"{col} = EXCLUDED.{col}" for col in COLUMNS[1:])},
    updated_at = now()
RETURNING (xmax = 0) AS inserted
"""
FALLBACK_UPDATE_SQL = f"""
UPDATE public.queries SET {_ASSIGNMENTS}, updated_at = now()
WHERE query_slug = $1
"""
FALLBACK_INSERT_SQL = f"""
INSERT INTO public.queries ({', '.join(COLUMNS)}, created_at, updated_at)
VALUES ({_PLACEHOLDERS}, now(), now())
"""


def rows_for(program: str, program_id: Any, parser: Any) -> list[tuple[Any, ...]]:
    """The two ``public.queries`` rows, in ``COLUMNS`` order."""
    return [
        (slug, description, query_raw, FIELDS, program_id, program, "db", parser, False, False, 3600)
        for slug, (description, query_raw) in SLUGS.items()
    ]


async def has_unique_slug_index(conn: asyncpg.Connection) -> bool:
    """Return True when public.queries has a single-column, non-partial unique index on query_slug."""
    return await conn.fetchval(UNIQUE_SLUG_INDEX_SQL) is not None


async def resolve_defaults(
    conn: asyncpg.Connection, program: str, program_id: int | None, parser: str | None
) -> tuple[int, str]:
    """Resolve ``program_id`` and ``parser`` from a sibling slug of ``program`` unless given explicitly.

    Raises:
        RuntimeError: When either value cannot be resolved — an invalid row is never written.
    """
    if program_id is None:
        program_id = await conn.fetchval(PROGRAM_ID_SQL, program)
        if program_id is None:
            raise RuntimeError(
                f"no public.queries row for program {program!r} to copy program_id from; pass --program-id"
            )
    if parser is None:
        parser = await conn.fetchval(PARSER_SQL, program)
        if not parser:
            raise RuntimeError(f"no provider='db' row for program {program!r} to copy the parser from; pass --parser")
    return int(program_id), str(parser)


async def refuse_foreign_slug(conn: asyncpg.Connection, slug: str, program: str) -> None:
    """Never take over a slug that already belongs to another program.

    Raises:
        RuntimeError: When ``slug`` exists under a different ``program_slug``.
    """
    owner = await conn.fetchval(OWNER_SQL, slug)
    if owner is not None and owner != program:
        raise RuntimeError(f"slug {slug!r} already belongs to program {owner!r}; refusing to overwrite it")


async def seed(
    conn: asyncpg.Connection | None = None,
    *,
    program: str = PROGRAM,
    program_id: int | None = None,
    parser: str | None = None,
) -> dict[str, str]:
    """Upsert both slugs; return ``{slug: 'inserted' | 'updated'}``.

    Both rows go in ONE transaction, each under an advisory lock keyed on its slug, so concurrent runs cannot both
    insert (the fallback path has no unique index to protect it).
    """
    own_connection = conn is None
    if conn is None:
        conn = await asyncpg.connect(default_dsn)
    try:
        async with conn.transaction():
            program_id, parser = await resolve_defaults(conn, program, program_id, parser)
            logger.info("writing program_slug=%s program_id=%s parser=%s", program, program_id, parser)
            unique = await has_unique_slug_index(conn)
            outcome: dict[str, str] = {}
            for values in rows_for(program, program_id, parser):
                slug = values[0]
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", slug)
                await refuse_foreign_slug(conn, slug, program)
                if unique:
                    inserted = await conn.fetchval(UPSERT_SQL, *values)
                    outcome[slug] = "inserted" if inserted else "updated"
                    continue
                updated = await conn.execute(FALLBACK_UPDATE_SQL, *values)
                if updated == "UPDATE 0":
                    await conn.execute(FALLBACK_INSERT_SQL, *values)
                    outcome[slug] = "inserted"
                else:
                    outcome[slug] = "updated"
            return outcome
    finally:
        if own_connection:
            await conn.close()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: refuses to write without --yes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="confirm the write to production public.queries")
    parser.add_argument("--dry-run", action="store_true", help="print the rows that would be written and exit")
    parser.add_argument("--program", default=PROGRAM, help=f"program_slug of the new rows (default: {PROGRAM})")
    parser.add_argument("--program-id", type=int, default=None, help="program_id (default: copied from the program)")
    parser.add_argument("--parser", default=None, help="QuerySource parser name (default: copied from the program)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.dry_run:
        unresolved = "<copied from an existing row of the program at --yes time>"
        for values in rows_for(args.program, args.program_id or unresolved, args.parser or unresolved):
            sys.stdout.write(json.dumps(dict(zip(COLUMNS, values, strict=True)), indent=2, default=str) + "\n")
        return 0
    if not args.yes:
        logger.error("Refusing to write %s to production public.queries without --yes.", ", ".join(SLUGS))
        return 2
    try:
        result = asyncio.run(seed(program=args.program, program_id=args.program_id, parser=args.parser))
    except Exception as exc:  # noqa: BLE001 - CLI boundary: report and exit non-zero
        logger.error("Seed failed: %s", exc)
        return 1
    for slug, outcome in result.items():
        logger.info("%s: %s", slug, outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
