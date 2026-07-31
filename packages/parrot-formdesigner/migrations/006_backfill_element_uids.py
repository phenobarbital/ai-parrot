#!/usr/bin/env python3
"""Migration 006: Backfill element UIDs + rewrite rule references (FEAT-393).

For each `form_schemas` row, round-trips `schema_json` through
`FormSchema.model_validate()` — which mints a fresh `field_uid`/
`section_uid`/`subsection_uid` (via each model's `default_factory=
uuid.uuid4`) for any tree level that doesn't already carry one, while
preserving already-present UIDs unchanged. Documents with a duplicate
`field_id` anywhere in the tree are rejected by
`FormSchema._validate_unique_identity` (FEAT-393, Module 2) — these are
reported and the row is SKIPPED entirely (never written), since an
ambiguous `field_id` cannot be safely resolved to a `field_uid` for rule
references. Successfully-validated documents then have their rule
references (`depends_on`/`post_depends`) rewritten from authored
`field_id` to `field_uid` via `resolve_rule_references` (idempotent by
construction).

Also scans `form_data` (submissions) for blob_ref-shaped values still on
the legacy `{form_id}/{field_id}/{blob_id}` object-store key pattern —
REPORT ONLY. Object-store keys are never rewritten (rewriting a live S3/
GCS/local key is a separate, deliberate operational decision outside this
migration's scope).

Idempotent: `migrate_schema_document()` produces byte-identical output for
an already-migrated document (no field is re-minted, no rule reference is
re-written), and `backfill_element_uids()` only issues an UPDATE when the
migrated JSON differs from the stored JSON — re-running after a partial
or interrupted run is safe.

Prerequisites:
    - `004_form_uid_uuid_type.sql` and `005_question_bank_question_id.sql`
      (or, at minimum, TASK-1995/1996/1997/2006's code already deployed).
    - `asyncpg` installed (already a dependency of `parrot_formdesigner`).

Usage:
    python migrations/006_backfill_element_uids.py --dsn postgresql://... \\
        --schema navigator [--batch-size 1000] [--dry-run]

Exit codes:
    0 - success (including a successful --dry-run)
    1 - connection or query failure
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

try:
    import asyncpg
except ImportError:  # pragma: no cover - exercised only when asyncpg is absent
    asyncpg = None  # type: ignore[assignment]

from parrot_formdesigner.core.resolution import resolve_rule_references
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services._identifiers import (
    qualified_table,
    validate_identifier,
)

DEFAULT_BATCH_SIZE = 1000

_DUPLICATE_FIELD_ID_RE = re.compile(r"Duplicate field_id '([^']+)'")
_BLOB_REF_SCHEMES = ("s3://", "gs://", "file://", "temp://")


# ---------------------------------------------------------------------------
# Pure, in-memory document migration (no DB — unit-testable directly)
# ---------------------------------------------------------------------------


@dataclass
class DocumentMigrationResult:
    """Result of migrating one `form_schemas.schema_json` document.

    Attributes:
        migrated_json: The migrated document, or ``None`` if the row was
            skipped (duplicate field_id / validation failure).
        skipped_reason: ``"duplicate_field_id"`` or a generic
            ``"validation_error: ..."`` message, or ``None`` on success.
        duplicate_field_ids: The offending ``field_id``s, when
            ``skipped_reason == "duplicate_field_id"``.
        changed: Whether ``migrated_json`` differs from the input
            document (``False`` for an already-migrated, idempotent
            document).
    """

    migrated_json: dict[str, Any] | None
    skipped_reason: str | None = None
    duplicate_field_ids: list[str] = field(default_factory=list)
    changed: bool = False


def migrate_schema_document(data: dict[str, Any]) -> DocumentMigrationResult:
    """Migrate a single `form_schemas.schema_json` document in memory.

    Args:
        data: The parsed JSONB document (a `FormSchema`-shaped dict).

    Returns:
        A `DocumentMigrationResult` — either the migrated document, or a
        skip reason (never both).
    """
    try:
        form = FormSchema.model_validate(data)
    except ValidationError as exc:
        messages = [e["msg"] for e in exc.errors()]
        duplicates = sorted(
            {
                m.group(1)
                for msg in messages
                for m in [_DUPLICATE_FIELD_ID_RE.search(msg)]
                if m
            }
        )
        if duplicates:
            return DocumentMigrationResult(
                migrated_json=None,
                skipped_reason="duplicate_field_id",
                duplicate_field_ids=duplicates,
            )
        return DocumentMigrationResult(
            migrated_json=None,
            skipped_reason=f"validation_error: {messages}",
        )

    resolved = resolve_rule_references(form)
    migrated_json = resolved.model_dump(mode="json")
    return DocumentMigrationResult(
        migrated_json=migrated_json, changed=migrated_json != data
    )


def _has_adjacent_uid_pair(parts: list[str]) -> bool:
    """True if any two ADJACENT path segments both parse as UUIDs."""
    for i in range(len(parts) - 1):
        try:
            uuid.UUID(parts[i])
            uuid.UUID(parts[i + 1])
            return True
        except ValueError:
            continue
    return False


def is_legacy_blob_ref(value: str) -> bool:
    """True if ``value`` is a blob_ref still on the legacy key pattern.

    A blob_ref looks like ``{scheme}://[{bucket}/]{form}/{field}/{blob_id}``
    (see ``services/blob_storage.py``). The NEW key pattern has two
    adjacent UUID segments (``{form_uid}/{field_uid}``); the LEGACY
    pattern does not (``{form_id}/{field_id}`` are editable slugs).

    Args:
        value: Candidate string value from submission data.

    Returns:
        ``True`` if ``value`` looks like a blob_ref on the legacy pattern,
        ``False`` otherwise (including non-blob-ref strings).
    """
    for scheme in _BLOB_REF_SCHEMES:
        if value.startswith(scheme):
            path = value[len(scheme):]
            return not _has_adjacent_uid_pair(path.split("/"))
    return False


def find_legacy_blob_refs(value: Any) -> list[str]:
    """Recursively scan a JSON-like value for legacy-pattern blob_refs.

    Args:
        value: A submission's ``data`` dict (or any nested JSON value).

    Returns:
        List of blob_ref strings still on the legacy
        ``{form_id}/{field_id}/`` key pattern. Report only — this
        migration NEVER rewrites object-store keys.
    """
    found: list[str] = []
    if isinstance(value, str):
        if is_legacy_blob_ref(value):
            found.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            found.extend(find_legacy_blob_refs(v))
    elif isinstance(value, list):
        for v in value:
            found.extend(find_legacy_blob_refs(v))
    return found


# ---------------------------------------------------------------------------
# DB-backed batch runner
# ---------------------------------------------------------------------------


@dataclass
class BackfillReport:
    """Summary of a `backfill_element_uids` run.

    Attributes:
        migrated: Number of `form_schemas` rows whose `schema_json` was
            (or, in `--dry-run` mode, would be) rewritten.
        skipped_duplicates: Mapping of `form_schemas.id` (as str) to the
            list of duplicate `field_id`s found in that row's document.
            These rows are never written.
        legacy_blob_refs: `form_data` blob_ref values still on the legacy
            `{form_id}/{field_id}/` key pattern (report only).
        dry_run: Whether this report was produced without writing.
    """

    migrated: int = 0
    skipped_duplicates: dict[str, list[str]] = field(default_factory=dict)
    legacy_blob_refs: list[str] = field(default_factory=list)
    dry_run: bool = False

    def summary(self) -> str:
        """Return a human-readable one-paragraph summary."""
        lines = [
            f"Migrated: {self.migrated} row(s)"
            + (" (dry-run — no writes performed)" if self.dry_run else ""),
            f"Skipped (duplicate field_id): {len(self.skipped_duplicates)} row(s)",
        ]
        for row_id, dups in self.skipped_duplicates.items():
            lines.append(f"  - form_schemas.id={row_id}: {', '.join(dups)}")
        lines.append(
            f"Legacy-pattern blob refs (report only, never rewritten): "
            f"{len(self.legacy_blob_refs)}"
        )
        for ref in self.legacy_blob_refs:
            lines.append(f"  - {ref}")
        return "\n".join(lines)


async def backfill_element_uids(
    pool: asyncpg.Pool,
    *,
    schema: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
) -> BackfillReport:
    """Backfill element UIDs + rewrite rule references in `form_schemas`.

    Args:
        pool: Connected asyncpg pool.
        schema: Validated Postgres schema containing `form_schemas`.
        batch_size: Number of rows processed per batch.
        dry_run: If True, computes the report WITHOUT writing any updates.

    Returns:
        A `BackfillReport` summarizing the run (schema_json only — see
        `scan_legacy_blob_refs` for the `form_data` blob-ref report).
    """
    validate_identifier(schema, kind="schema")
    form_schemas_qt = qualified_table(schema, "form_schemas")

    report = BackfillReport(dry_run=dry_run)

    async with pool.acquire() as conn:
        # Keyset pagination on `id` — see 003_migrate_form_data.py for why
        # a plain re-fetch of an unbounded WHERE clause is unsafe here too:
        # skipped/unchanged rows never "leave" a naive re-fetch, which
        # would loop forever. Tracking a strictly-increasing cursor
        # guarantees each row is visited exactly once per run.
        last_id: object | None = None
        while True:
            if last_id is None:
                rows = await conn.fetch(
                    f"""
                    SELECT id, schema_json FROM {form_schemas_qt}
                    ORDER BY id
                    LIMIT $1
                    """,
                    batch_size,
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT id, schema_json FROM {form_schemas_qt}
                    WHERE id > $1
                    ORDER BY id
                    LIMIT $2
                    """,
                    last_id,
                    batch_size,
                )
            if not rows:
                break

            for row in rows:
                raw = row["schema_json"]
                data = json.loads(raw) if isinstance(raw, str) else raw

                result = migrate_schema_document(data)
                if result.skipped_reason is not None:
                    report.skipped_duplicates[str(row["id"])] = (
                        result.duplicate_field_ids or [result.skipped_reason]
                    )
                elif result.changed:
                    report.migrated += 1
                    if not dry_run:
                        await conn.execute(
                            f"""
                            UPDATE {form_schemas_qt}
                            SET schema_json = $1::jsonb
                            WHERE id = $2
                            """,
                            json.dumps(result.migrated_json),
                            row["id"],
                        )
                # else: already migrated — no-op, nothing to write.

                last_id = row["id"]

    return report


async def scan_legacy_blob_refs(
    pool: asyncpg.Pool,
    *,
    schema: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[str]:
    """Scan `form_data.data` for blob_refs still on the legacy key pattern.

    Report only — never rewrites object-store keys.

    Args:
        pool: Connected asyncpg pool.
        schema: Validated Postgres schema containing `form_data`.
        batch_size: Number of rows processed per batch.

    Returns:
        List of legacy-pattern blob_ref strings found across all
        submissions.
    """
    validate_identifier(schema, kind="schema")
    form_data_qt = qualified_table(schema, "form_data")

    legacy_refs: list[str] = []

    async with pool.acquire() as conn:
        last_id: object | None = None
        while True:
            if last_id is None:
                rows = await conn.fetch(
                    f"SELECT id, data FROM {form_data_qt} ORDER BY id LIMIT $1",
                    batch_size,
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT id, data FROM {form_data_qt}
                    WHERE id > $1
                    ORDER BY id
                    LIMIT $2
                    """,
                    last_id,
                    batch_size,
                )
            if not rows:
                break

            for row in rows:
                raw = row["data"]
                data = json.loads(raw) if isinstance(raw, str) else raw
                legacy_refs.extend(find_legacy_blob_refs(data))
                last_id = row["id"]

    return legacy_refs


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill form_schemas element UIDs + rewrite rule references, "
            "and report legacy-pattern blob refs (FEAT-393, TASK-2008)."
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
        report = await backfill_element_uids(
            pool,
            schema=args.schema,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
        report.legacy_blob_refs = await scan_legacy_blob_refs(
            pool, schema=args.schema, batch_size=args.batch_size
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
