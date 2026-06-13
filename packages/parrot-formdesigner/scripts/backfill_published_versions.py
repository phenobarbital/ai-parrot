#!/usr/bin/env python
"""CLI wrapper for ``FormVersionService.backfill_published()``.

Marks all pre-existing forms in a tenant as published at their current
``version`` value, enabling ``FormVersionService`` for that tenant.

Usage:
    python scripts/backfill_published_versions.py --tenant navigator
    python scripts/backfill_published_versions.py --tenant navigator --dry-run
    python scripts/backfill_published_versions.py --tenant navigator --dsn "postgres://..."

Environment variables:
    PARROT_DB_DSN — fallback DSN when ``--dsn`` is not passed.

Exit codes:
    0 — success (including dry-run with 0 changes)
    1 — error
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_published_versions")


async def _run(tenant: str, dsn: str | None, dry_run: bool) -> int:
    """Run the backfill for the given tenant.

    Args:
        tenant: Tenant slug to backfill.
        dsn: Optional Postgres DSN. Falls back to PARROT_DB_DSN env var.
        dry_run: If True, log what would change without persisting.

    Returns:
        Number of forms backfilled (or that would be backfilled).
    """
    from parrot_formdesigner.services.form_version import FormVersionService
    from parrot_formdesigner.services.registry import FormRegistry
    from parrot_formdesigner.services.storage import PostgresFormStorage

    dsn = dsn or os.environ.get("PARROT_DB_DSN")
    storage = None

    if dsn:
        logger.info("Connecting to Postgres: %s", dsn[:30] + "…" if len(dsn) > 30 else dsn)
        try:
            storage = PostgresFormStorage(dsn=dsn)
        except Exception as exc:
            logger.warning("Could not create PostgresFormStorage: %s — using in-memory only", exc)

    registry = FormRegistry(storage=storage)

    if storage is not None:
        try:
            await registry.load_from_storage(tenant=tenant)
            logger.info("Loaded existing forms for tenant '%s' from storage", tenant)
        except Exception as exc:
            logger.warning("Could not load forms from storage: %s — proceeding with empty registry", exc)

    svc = FormVersionService(registry, storage=storage)
    changed = await svc.backfill_published(tenant=tenant, dry_run=dry_run)

    if storage is not None:
        try:
            await storage.close()
        except Exception:
            pass

    return changed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill pre-existing forms as published v1.0 snapshots.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--tenant",
        required=True,
        help="Tenant slug to backfill (e.g. 'navigator', 'epson').",
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help=(
            "Postgres DSN (e.g. 'postgres://user:pw@host/db'). "
            "Falls back to PARROT_DB_DSN env var when not provided."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would change without persisting anything.",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for the backfill script."""
    args = _parse_args()
    if args.dry_run:
        logger.info("DRY-RUN mode — no data will be modified")

    try:
        changed = asyncio.run(_run(args.tenant, args.dsn, args.dry_run))
        action = "[dry-run] would backfill" if args.dry_run else "backfilled"
        logger.info("Done — %s %d form(s) for tenant '%s'", action, changed, args.tenant)
        sys.exit(0)
    except Exception as exc:
        logger.exception("Backfill failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
