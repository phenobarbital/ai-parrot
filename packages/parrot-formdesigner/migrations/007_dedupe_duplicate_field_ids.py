#!/usr/bin/env python3
"""Migration 007: Repair `form_schemas` rows that 006 skipped (FEAT-393 follow-up).

`006_backfill_element_uids.py` refuses to touch any document whose tree
contains a duplicate `field_id` — it records the row in
`BackfillReport.skipped_duplicates` and moves on, because an ambiguous
`field_id` cannot be safely resolved to a `field_uid` for rule references.
That leaves those rows in a state no code path can recover from:

  * `FormSchema._validate_unique_identity` (added 2026-07-31, TASK-1996)
    rejects them, so `PostgresFormStorage.load()` logs and returns `None`
    and `FormRegistry.load_from_storage()` silently drops the form — it
    reads as "deleted", not "broken"; and
  * because 006 skipped them, they never received their element UIDs, so
    `field_uid`/`section_uid`/`subsection_uid` are re-minted from
    `default_factory=uuid.uuid4` on every single load — unstable identity
    for blob object keys (`{form_uid}/{field_uid}/{blob_id}`) and for
    partial-save Redis keys.

Each condition blocks the other's repair, so this migration does both in
one pass, in order: rename the colliding `field_id`s, then round-trip the
now-valid document exactly as 006 does (mint + persist UIDs, rewrite rule
references via `resolve_rule_references`).

Why RENAME and not DROP:
    `field_id` stopped being identity in FEAT-393 — the spec keeps it as
    "the human-editable name/key" and explicitly makes renaming it a legal
    patch (`sdd/specs/formdesigner-field-uid.spec.md`, Goals). Dropping the
    later occurrence (which is what the networkninja importer does at
    IMPORT time, `tools/services/networkninja.py:536`) destroys a field
    definition that is already persisted; renaming preserves it. The FIRST
    occurrence always keeps the original `field_id`, so `form_data.data`
    (still `field_id`-keyed) and any rule authored against that name keep
    resolving to the same field they resolved to before — the duplicate was
    unaddressable anyway, since every lookup was first-match.

Idempotent: a row that already validates is reported as `already_valid`
and never written, so re-running after a partial or interrupted run is
safe. Rename suffixes are checked against every `field_id` in the document,
so a second pass cannot produce `field_x__2__2`.

Prerequisites:
    - `006_backfill_element_uids.py` has been run (this migration repairs
      precisely the rows 006 reported under "Skipped (duplicate field_id)").
    - `asyncpg` installed (already a dependency of `parrot_formdesigner`).

Usage:
    # Report only — this is the DEFAULT. Nothing is written.
    python migrations/007_dedupe_duplicate_field_ids.py --dsn postgresql://... \\
        --schema navigator

    # Apply the repairs.
    python migrations/007_dedupe_duplicate_field_ids.py --dsn postgresql://... \\
        --schema navigator --apply

Exit codes:
    0 - success (including a report-only run)
    1 - connection or query failure
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterator
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

#: Separator between the original `field_id` and its disambiguating index.
#: Double underscore, so a renamed id stays a legal identifier and remains
#: visually traceable back to the column it came from.
RENAME_SEPARATOR = "__"


# ---------------------------------------------------------------------------
# Pure, in-memory document repair (no DB — unit-testable directly)
# ---------------------------------------------------------------------------


def walk_field_dicts(items: list[Any]) -> Iterator[dict[str, Any]]:
    """Yield every field dict in a raw `schema_json` section item list.

    Mirrors `core.schema.walk_fields()` EXACTLY — subsections recursed,
    then each field yielded parent-before-children (GROUP `children`, then
    ARRAY `item_template`). The order matters: it is what decides which
    occurrence of a duplicated `field_id` counts as "first" and therefore
    keeps its name. A traversal that disagreed with the model's would
    rename a different occurrence than the validator complained about.

    A subsection is distinguished from a field by the absence of
    `field_id` (`FormSubsection` carries `subsection_id`/`fields`). Any
    document reaching this function has already parsed as a `FormSchema`
    at the field level — it failed only the model-level uniqueness
    validator — so every field dict is well-formed.

    Args:
        items: A section's raw ``fields`` list (field and/or subsection dicts).

    Yields:
        Every field dict in the tree, parent-before-children order.
    """
    for item in items:
        if not isinstance(item, dict):
            continue
        if "field_id" not in item:
            yield from walk_field_dicts(item.get("fields") or [])
            continue
        yield item
        children = item.get("children")
        if children:
            yield from walk_field_dicts(children)
        template = item.get("item_template")
        if template is not None:
            yield from walk_field_dicts([template])


def _reserved_names(data: dict[str, Any]) -> set[str]:
    """Collect every name a renamed `field_id` must not collide with.

    That is every `field_id` in the tree, plus every metadata key —
    `FormSchema._validate_metadata` rejects a metadata key that collides
    with a `field_id`, so a rename landing on one would turn a repairable
    row into an unrepairable one.

    Args:
        data: A raw ``schema_json`` document.

    Returns:
        The set of names already claimed in the document.
    """
    found: set[str] = set()
    for section in data.get("sections") or []:
        if isinstance(section, dict):
            for field_dict in walk_field_dicts(section.get("fields") or []):
                found.add(str(field_dict.get("field_id")))
    for entry in data.get("metadata") or []:
        if isinstance(entry, dict) and entry.get("key") is not None:
            found.add(str(entry["key"]))
    return found


def _next_available_name(base: str, taken: set[str]) -> str:
    """Return the first `{base}__{n}` (n >= 2) not already in ``taken``."""
    index = 2
    while f"{base}{RENAME_SEPARATOR}{index}" in taken:
        index += 1
    return f"{base}{RENAME_SEPARATOR}{index}"


def dedupe_field_ids(data: dict[str, Any]) -> list[tuple[str, str]]:
    """Rename duplicate `field_id`s in a raw document, IN PLACE.

    First occurrence wins — it keeps the original name. Every later
    occurrence is renamed to the first free `{field_id}__{n}`, checked
    against every `field_id` in the whole document (not just the ones seen
    so far), so a repair can never collide with a name that appears later
    in the tree or with a suffix a previous run already assigned.

    Rule references are deliberately NOT rewritten. A condition authored
    against the duplicated name resolved, before this migration, to the
    first match in traversal order; the first occurrence keeps that name,
    so the reference keeps resolving to the very same field. Rewriting
    would silently re-point it at a field it never addressed.

    Args:
        data: A raw ``schema_json`` document. Mutated in place.

    Returns:
        The renames applied, as ``(old_field_id, new_field_id)`` pairs in
        traversal order. Empty when the document had no duplicates.
    """
    taken = _reserved_names(data)
    seen: set[str] = set()
    renames: list[tuple[str, str]] = []

    for section in data.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for field_dict in walk_field_dicts(section.get("fields") or []):
            field_id = str(field_dict.get("field_id"))
            if field_id not in seen:
                seen.add(field_id)
                continue
            new_id = _next_available_name(field_id, taken)
            field_dict["field_id"] = new_id
            taken.add(new_id)
            seen.add(new_id)
            renames.append((field_id, new_id))

    return renames


@dataclass
class DocumentRepairResult:
    """Result of repairing one `form_schemas.schema_json` document.

    Attributes:
        repaired_json: The repaired document, or ``None`` when the row was
            not written (already valid, or unrepairable).
        renames: ``(old_field_id, new_field_id)`` pairs applied.
        skipped_reason: ``"already_valid"`` when the document needed no
            repair, or ``"unrepairable: ..."`` when it still fails
            validation after deduplication (e.g. a duplicate
            client-supplied ``field_uid``, which this migration does not
            touch). ``None`` on a successful repair.
    """

    repaired_json: dict[str, Any] | None = None
    renames: list[tuple[str, str]] = field(default_factory=list)
    skipped_reason: str | None = None


def repair_schema_document(data: dict[str, Any]) -> DocumentRepairResult:
    """Repair a single document that 006 skipped for duplicate `field_id`.

    Deduplicates, then performs the SAME round-trip 006 performs on the
    documents it accepted — `FormSchema.model_validate()` (which mints any
    missing element UIDs via `default_factory`) followed by
    `resolve_rule_references()` — so a repaired row lands in exactly the
    state it would have been in had 006 not skipped it.

    Args:
        data: The parsed JSONB document (a `FormSchema`-shaped dict). Not
            mutated — the deduplication runs against a deep copy.

    Returns:
        A `DocumentRepairResult` — either the repaired document, or a skip
        reason (never both).
    """
    try:
        FormSchema.model_validate(data)
    except ValidationError:
        pass
    else:
        return DocumentRepairResult(skipped_reason="already_valid")

    candidate = json.loads(json.dumps(data))
    renames = dedupe_field_ids(candidate)

    try:
        form = FormSchema.model_validate(candidate)
    except ValidationError as exc:
        messages = [e["msg"] for e in exc.errors()]
        return DocumentRepairResult(renames=renames, skipped_reason=f"unrepairable: {messages}")

    resolved = resolve_rule_references(form)
    return DocumentRepairResult(repaired_json=resolved.model_dump(mode="json"), renames=renames)


# ---------------------------------------------------------------------------
# DB-backed batch runner
# ---------------------------------------------------------------------------


@dataclass
class RepairReport:
    """Summary of a `repair_duplicate_field_ids` run.

    Attributes:
        repaired: Number of rows whose `schema_json` was (or, in report-only
            mode, would be) rewritten.
        renames: Mapping of `form_schemas.id` (as str) to the renames applied
            to that row.
        already_valid: Number of rows that needed no repair (the normal
            result for every row 006 successfully migrated).
        unrepairable: Mapping of `form_schemas.id` (as str) to the reason the
            row still fails validation after deduplication. Never written.
        dry_run: Whether this report was produced without writing.
    """

    repaired: int = 0
    renames: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    already_valid: int = 0
    unrepairable: dict[str, str] = field(default_factory=dict)
    dry_run: bool = False

    def summary(self) -> str:
        """Return a human-readable one-paragraph summary."""
        lines = [
            f"Repaired: {self.repaired} row(s)" + (" (report only — no writes performed)" if self.dry_run else ""),
        ]
        for row_id, pairs in self.renames.items():
            lines.append(f"  - form_schemas.id={row_id}:")
            for old, new in pairs:
                lines.append(f"      {old!r} -> {new!r}")
        lines.append(f"Already valid (no repair needed): {self.already_valid} row(s)")
        lines.append(f"Unrepairable: {len(self.unrepairable)} row(s)")
        for row_id, reason in self.unrepairable.items():
            lines.append(f"  - form_schemas.id={row_id}: {reason}")
        return "\n".join(lines)


async def repair_duplicate_field_ids(
    pool: asyncpg.Pool,
    *,
    schema: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
) -> RepairReport:
    """Rename duplicate `field_id`s and finish 006's backfill, row by row.

    Args:
        pool: Connected asyncpg pool.
        schema: Validated Postgres schema containing `form_schemas`.
        batch_size: Number of rows processed per batch.
        dry_run: If True, computes the report WITHOUT writing any updates.

    Returns:
        A `RepairReport` summarizing the run.
    """
    validate_identifier(schema, kind="schema")
    form_schemas_qt = qualified_table(schema, "form_schemas")

    report = RepairReport(dry_run=dry_run)

    async with pool.acquire() as conn:
        # Keyset pagination on `id` — same reasoning as 006 and 003: an
        # unbounded WHERE re-fetch never lets skipped/unchanged rows leave
        # the result set, which loops forever. A strictly-increasing cursor
        # visits each row exactly once per run.
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

                result = repair_schema_document(data)
                row_id = str(row["id"])

                if result.repaired_json is not None:
                    report.repaired += 1
                    report.renames[row_id] = result.renames
                    if not dry_run:
                        await conn.execute(
                            f"""
                            UPDATE {form_schemas_qt}
                            SET schema_json = $1::jsonb
                            WHERE id = $2
                            """,
                            json.dumps(result.repaired_json),
                            row["id"],
                        )
                elif result.skipped_reason == "already_valid":
                    report.already_valid += 1
                else:
                    report.unrepairable[row_id] = result.skipped_reason or "unknown"

                last_id = row["id"]

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rename duplicate field_ids in form_schemas rows that migration "
            "006 skipped, then finish 006's element-UID backfill on them "
            "(FEAT-393 follow-up). Reports only unless --apply is passed."
        )
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
        help=f"Rows processed per batch (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the repairs. WITHOUT this flag the script only reports.",
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
        report = await repair_duplicate_field_ids(
            pool,
            schema=args.schema,
            batch_size=args.batch_size,
            dry_run=not args.apply,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary, report and exit cleanly
        print(f"error: migration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await pool.close()

    print(report.summary())
    if report.dry_run and report.repaired:
        print("\nRe-run with --apply to write these repairs.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    return asyncio.run(_async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
