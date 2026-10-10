#!/usr/bin/env python3
"""Migration 009 (FEAT-649): per-form sink columns TEXT → JSONB for voice answer envelopes.

For every ``form_schemas`` row whose ``persistence.data.type == "postgres_table"``, converts each
envelope-capable column still typed text to ``JSONB USING jsonb_build_object('answer', col)``.

Idempotent: columns already typed ``jsonb`` are skipped. Run in a maintenance window, ``--dry-run`` first.

Usage:
    python migrations/009_voice_envelope_sink_tables.py --dsn postgresql://... \\
        --schema navigator [--batch-size 1000] [--dry-run]

Exit codes:
    0 - success (including a successful --dry-run)
    1 - connection or query failure
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import Any

try:
    import asyncpg
except ImportError:  # pragma: no cover - exercised only when asyncpg is absent
    asyncpg = None  # type: ignore[assignment]

from parrot_formdesigner.services._identifiers import qualified_table, validate_identifier

DEFAULT_BATCH_SIZE = 1000
_SEP = "__"
_NON_VOICE_TYPES = frozenset(
    {
        "hidden",
        "file",
        "image",
        "image_dropzone",
        "multi_upload",
        "signature",
        "signature_pad",
        "credit_card",
        "password",
        "array",
    }
)


@dataclass
class SinkMigrationReport:
    """Summary of a sink-table conversion run."""

    altered: list[str] = field(default_factory=list)  # "schema.table.column"
    skipped: list[str] = field(default_factory=list)  # already jsonb / missing column
    dry_run: bool = False

    def summary(self) -> str:
        """Return a human-readable summary."""
        lines = [
            f"Altered: {len(self.altered)} column(s)" + (" (dry-run — no writes performed)" if self.dry_run else ""),
            f"Skipped (already jsonb / missing): {len(self.skipped)} column(s)",
        ]
        if self.altered:
            lines.append("Altered columns:")
            lines.extend(f"  - {item}" for item in self.altered)
        return "\n".join(lines)


def _walk(items: list[Any], prefix: str = ""):
    """Yield ``(column_name, field_dict)`` mirroring ``services/sinks/mapper.py:_walk_tabular``."""
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if "field_id" not in item:
            # FormSubsection — transparently walked.
            yield from _walk(item.get("fields") or [], prefix)
            continue
        name = f"{prefix}{_SEP}{item['field_id']}" if prefix else str(item["field_id"])
        if item.get("field_type") == "group" and item.get("children"):
            yield from _walk(item["children"], name)
        else:
            yield name, item


def envelope_columns(schema_json: dict[str, Any]) -> list[str]:
    """Return the envelope-capable column names of one form's ``schema_json`` (pure)."""
    voice = schema_json.get("voice")
    voice_on = isinstance(voice, dict) and voice.get("enabled") is not False
    columns: list[str] = []
    for section in schema_json.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for name, fld in _walk(section.get("fields") or []):
            if fld.get("answer_envelope") == "voice" or (voice_on and fld.get("field_type") not in _NON_VOICE_TYPES):
                if name not in columns:
                    columns.append(name)
    return columns


def alter_sql(schema_name: str, table: str, column: str) -> str:
    """Return the ``ALTER COLUMN … TYPE JSONB`` statement for one column (identifiers validated)."""
    qt = qualified_table(schema_name, table)
    col = validate_identifier(column, kind="column")
    return f'ALTER TABLE {qt} ALTER COLUMN "{col}" TYPE JSONB USING jsonb_build_object(\'answer\', "{col}")'


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


async def migrate_sink_tables(
    pool: Any, *, schema: str, batch_size: int = DEFAULT_BATCH_SIZE, dry_run: bool = False
) -> SinkMigrationReport:
    """Convert envelope-capable sink columns for every postgres_table form in ``schema``."""
    validate_identifier(schema, kind="schema")
    form_schemas_qt = qualified_table(schema, "form_schemas")
    report = SinkMigrationReport(dry_run=dry_run)
    done: set[tuple[str, str, str]] = set()

    async with pool.acquire() as conn:
        last_id: Any = None
        while True:
            if last_id is None:
                rows = await conn.fetch(
                    f"SELECT id, schema_json FROM {form_schemas_qt} ORDER BY id LIMIT $1",
                    batch_size,
                )
            else:
                rows = await conn.fetch(
                    f"SELECT id, schema_json FROM {form_schemas_qt} WHERE id > $1 ORDER BY id LIMIT $2",
                    last_id,
                    batch_size,
                )
            if not rows:
                break
            for row in rows:
                last_id = row["id"]
                doc = _as_dict(row["schema_json"])
                target = ((doc.get("persistence") or {}).get("data")) or {}
                if target.get("type") != "postgres_table":
                    continue
                target_schema = validate_identifier(str(target.get("schema_name") or target.get("schema")), kind="schema")
                table = validate_identifier(str(target.get("table")), kind="table")
                columns = [c for c in envelope_columns(doc) if (target_schema, table, c) not in done]
                if not columns:
                    continue
                existing = await conn.fetch(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = $1 AND table_name = $2",
                    target_schema,
                    table,
                )
                types = {r["column_name"]: str(r["data_type"]).lower() for r in existing}
                statements: list[tuple[str, str]] = []
                for col in columns:
                    done.add((target_schema, table, col))
                    label = f"{target_schema}.{table}.{col}"
                    if types.get(col) in (None, "jsonb"):
                        report.skipped.append(label)
                        continue
                    statements.append((label, alter_sql(target_schema, table, col)))
                if not statements:
                    continue
                if dry_run:
                    report.altered.extend(label for label, _ in statements)
                    continue
                async with conn.transaction():
                    for _, sql in statements:
                        await conn.execute(sql)
                report.altered.extend(label for label, _ in statements)
    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert envelope-capable per-form sink columns to JSONB (FEAT-649, TASK-4230)."
    )
    parser.add_argument("--dsn", required=True, help="asyncpg DSN, e.g. postgresql://user:pw@host/db")
    parser.add_argument(
        "--schema",
        required=True,
        help="Postgres schema containing form_schemas (e.g. navigator)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"form_schemas rows processed per batch (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print the report without altering any table",
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
        report = await migrate_sink_tables(
            pool, schema=args.schema, batch_size=args.batch_size, dry_run=args.dry_run
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
