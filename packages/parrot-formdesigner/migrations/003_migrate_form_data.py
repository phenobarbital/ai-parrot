#!/usr/bin/env python3
"""Migration 003: Backfill form_data.form_uid from form_schemas (FEAT-389).

Performs the same logical backfill as `002_add_form_uid_submissions.sql`,
but in batches with explicit tie-breaking and an orphan report — prefer
this script over the raw SQL migration for production backfills where a
form_id may map to more than one form_schemas row (e.g. a deleted and
recreated form reusing the same slug).

Idempotent: only rows where `form_data.form_uid IS NULL` are touched, so
re-running after a partial or interrupted run is safe.

Prerequisites:
    - `001_add_form_uid.sql` and `002_add_form_uid_submissions.sql`
      (or at minimum, the `form_uid` column) already applied to both
      `form_schemas` and `form_data`.
    - `asyncpg` installed (already a dependency of `parrot_formdesigner`).

Usage:
    python migrations/003_migrate_form_data.py --dsn postgresql://... \\
        --schema navigator [--batch-size 1000] [--dry-run]

Exit codes:
    0 - success (including a successful --dry-run)
    1 - connection or query failure
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field

try:
    import asyncpg
except ImportError:  # pragma: no cover - exercised only when asyncpg is absent
    asyncpg = None  # type: ignore[assignment]

from parrot_formdesigner.services._identifiers import (
    qualified_table,
    validate_identifier,
)

DEFAULT_BATCH_SIZE = 1000


@dataclass
class MigrationReport:
    """Summary of a `backfill_form_uid` run.

    Attributes:
        backfilled: Number of `form_data` rows whose `form_uid` was set.
        orphaned: `form_data.id` values with no matching `form_schemas`
            row (the parent form was deleted) — these remain
            `form_uid IS NULL` and are never retried.
        dry_run: Whether this report was produced without writing.
    """

    backfilled: int = 0
    orphaned: list[str] = field(default_factory=list)
    dry_run: bool = False

    def summary(self) -> str:
        """Return a human-readable one-paragraph summary."""
        lines = [
            f"Backfilled: {self.backfilled} row(s)"
            + (" (dry-run — no writes performed)" if self.dry_run else ""),
            f"Orphaned (no matching form_schemas row): {len(self.orphaned)} row(s)",
        ]
        if self.orphaned:
            lines.append("Orphaned form_data.id values:")
            lines.extend(f"  - {rid}" for rid in self.orphaned)
        return "\n".join(lines)


async def backfill_form_uid(
    pool: asyncpg.Pool,
    *,
    schema: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
) -> MigrationReport:
    """Backfill `form_data.form_uid` from `form_schemas` in batches.

    For each batch of `form_data` rows missing `form_uid`, resolves the
    owning `form_schemas` row by `form_id`, breaking ties by preferring
    the most recently created `form_schemas` row (``ORDER BY created_at
    DESC``) when a slug maps to more than one `form_uid`. Rows with no
    matching `form_schemas` entry are reported as orphans and left alone.

    Args:
        pool: Connected asyncpg pool.
        schema: Validated Postgres schema containing both tables.
        batch_size: Number of `form_data` rows to process per batch.
        dry_run: If True, computes the report WITHOUT writing any updates.

    Returns:
        A `MigrationReport` summarizing the backfill.
    """
    validate_identifier(schema, kind="schema")
    form_data_qt = qualified_table(schema, "form_data")
    form_schemas_qt = qualified_table(schema, "form_schemas")

    report = MigrationReport(dry_run=dry_run)

    async with pool.acquire() as conn:
        # Keyset pagination on `fd.id` (NOT a plain `WHERE form_uid IS NULL
        # LIMIT n` re-fetch) — this is load-bearing, not a style choice.
        # `form_uid` only becomes non-NULL when a row is BOTH matched AND
        # written (`if not dry_run: UPDATE ...`), so a plain re-fetch of
        # `WHERE form_uid IS NULL` never shrinks past:
        #   - orphaned rows (no matching form_schemas row — never written,
        #     any mode), or
        #   - EVERY row, in `--dry-run` mode (nothing is ever written).
        # Either case reproduces the exact same batch forever. Tracking a
        # strictly-increasing `last_id` cursor guarantees each row is
        # visited exactly once per run, independent of whether it was
        # written, orphaned, or in dry-run mode.
        last_id: object | None = None
        while True:
            if last_id is None:
                rows = await conn.fetch(
                    f"""
                    SELECT fd.id AS row_id, fd.form_id AS form_id
                    FROM {form_data_qt} fd
                    WHERE fd.form_uid IS NULL
                    ORDER BY fd.id
                    LIMIT $1
                    """,
                    batch_size,
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT fd.id AS row_id, fd.form_id AS form_id
                    FROM {form_data_qt} fd
                    WHERE fd.form_uid IS NULL AND fd.id > $1
                    ORDER BY fd.id
                    LIMIT $2
                    """,
                    last_id,
                    batch_size,
                )
            if not rows:
                break

            for row in rows:
                match = await conn.fetchrow(
                    f"""
                    SELECT form_uid FROM {form_schemas_qt}
                    WHERE form_id = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    row["form_id"],
                )
                if match is None:
                    report.orphaned.append(str(row["row_id"]))
                else:
                    if not dry_run:
                        await conn.execute(
                            f"""
                            UPDATE {form_data_qt}
                            SET form_uid = $1
                            WHERE id = $2
                            """,
                            match["form_uid"],
                            row["row_id"],
                        )
                    report.backfilled += 1

                # Advance the cursor regardless of match/orphan/dry_run —
                # this row must never be reconsidered in a later batch.
                last_id = row["row_id"]

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill form_data.form_uid from form_schemas (FEAT-389, "
            "TASK-1975)."
        )
    )
    parser.add_argument(
        "--dsn", required=True, help="asyncpg DSN, e.g. postgresql://user:pw@host/db"
    )
    parser.add_argument(
        "--schema",
        required=True,
        help="Postgres schema containing form_schemas/form_data (e.g. navigator)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Rows processed per batch (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print the report without writing any updates",
    )
    return parser


async def _async_main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    if asyncpg is None:
        print("error: asyncpg is not installed", file=sys.stderr)
        return 1

    try:
        pool = await asyncpg.create_pool(dsn=args.dsn)
    except Exception as exc:  # noqa: BLE001 - CLI boundary, report and exit cleanly
        print(f"error: could not connect to database: {exc}", file=sys.stderr)
        return 1

    try:
        report = await backfill_form_uid(
            pool,
            schema=args.schema,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary, report and exit cleanly
        print(f"error: migration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await pool.close()

    print(report.summary())
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    return asyncio.run(_async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
