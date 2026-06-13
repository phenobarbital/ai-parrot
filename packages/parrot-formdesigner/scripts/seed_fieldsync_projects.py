"""Seed ``fieldsync.projects`` from ``networkninja.projects`` (idempotente).

Lee los proyectos existentes de la tabla read-only ``networkninja.projects``
e inserta/actualiza filas en ``fieldsync.projects`` usando ON CONFLICT DO
NOTHING para garantizar idempotencia (segunda ejecución no duplica filas).

Columnas verificadas en ``networkninja.projects`` (2026-06-12):
    project_id, project_name, description, start_timestamp, end_timestamp,
    orgid, client_id, client_name, is_active, accounting_code

NUNCA escribe de vuelta a ``networkninja.projects`` — es solo fuente de
lectura para el seed inicial.

Uso::

    python scripts/seed_fieldsync_projects.py --dsn postgresql://...
    python scripts/seed_fieldsync_projects.py --dsn postgresql://... --dry-run

Flags:
    --dsn       Cadena de conexión asyncpg (o DATABASE_URL del entorno).
    --dry-run   Muestra cuántas filas se inserirían sin ejecutar nada.
    --batch     Tamaño del batch de INSERT (default: 200).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

logger = logging.getLogger("seed_fieldsync_projects")


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_SELECT_NETWORKNINJA = """
SELECT
    project_id,
    project_name,
    description,
    start_timestamp,
    end_timestamp,
    orgid,
    client_id,
    is_active,
    accounting_code
FROM networkninja.projects
ORDER BY project_id
"""

_UPSERT_FIELDSYNC = """
INSERT INTO fieldsync.projects
    (client_id, name, description, accounting_code,
     start_timestamp, end_timestamp, is_active, org_id)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (client_id, accounting_code) DO NOTHING
"""


# ---------------------------------------------------------------------------
# Core seed logic (async)
# ---------------------------------------------------------------------------


async def _seed(dsn: str, *, dry_run: bool, batch_size: int) -> None:
    """Perform the actual seed operation.

    Args:
        dsn: asyncpg connection string.
        dry_run: When True, read rows and report counts but insert nothing.
        batch_size: Number of rows per INSERT batch.
    """
    try:
        import asyncpg  # type: ignore[import-untyped]
    except ImportError:
        logger.error("asyncpg is required: pip install asyncpg")
        sys.exit(1)

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(_SELECT_NETWORKNINJA)

        total = len(rows)
        logger.info("Found %d row(s) in networkninja.projects", total)

        if dry_run:
            logger.info("[DRY-RUN] Would insert/skip up to %d row(s).", total)
            return

        inserted = 0
        skipped = 0
        for offset in range(0, total, batch_size):
            batch = rows[offset : offset + batch_size]
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for row in batch:
                        status = await conn.execute(
                            _UPSERT_FIELDSYNC,
                            row["client_id"],
                            row["project_name"],
                            row["description"],
                            row["accounting_code"],
                            row["start_timestamp"],
                            row["end_timestamp"],
                            row["is_active"],
                            row["orgid"],
                        )
                        # asyncpg returns "INSERT 0 1" on success, "INSERT 0 0"
                        # when ON CONFLICT DO NOTHING fires.
                        if status.endswith(" 1"):
                            inserted += 1
                        else:
                            skipped += 1

        logger.info(
            "Seed complete: %d inserted, %d skipped (already existed).",
            inserted,
            skipped,
        )
    finally:
        await pool.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed fieldsync.projects from networkninja.projects."
    )
    parser.add_argument(
        "--dsn",
        default=os.environ.get("DATABASE_URL"),
        help="asyncpg DSN (default: $DATABASE_URL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many rows would be inserted without writing.",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=200,
        help="Batch size for INSERT operations (default: 200).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the seed script.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]`` when ``None``).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    args = _parse_args(argv)
    if not args.dsn:
        logger.error("--dsn is required (or set DATABASE_URL)")
        sys.exit(1)
    asyncio.run(_seed(args.dsn, dry_run=args.dry_run, batch_size=args.batch))


if __name__ == "__main__":
    main()
