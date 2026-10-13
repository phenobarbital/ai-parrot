#!/usr/bin/env python3
"""Migration 010 (FEAT-649): voice envelope inventory, orphan blob_refs, reversible downgrade.

Reports by default; writes only with ``--apply`` (``--downgrade --apply`` reverts envelopes to their
``answer`` scalar and JSONB sink columns back to TEXT).

Orphan detection supports ``--blob-url`` as a filesystem path or ``file://`` root only; any other
scheme reports "orphan check skipped (unsupported blob url)".

Usage:
    python migrations/010_voice_envelope_report.py --dsn "$DSN" --schema navigator [--blob-url file:///var/blobs]
    python migrations/010_voice_envelope_report.py --dsn "$DSN" --schema navigator --downgrade --apply

Exit codes:
    0 - success
    1 - connection or query failure
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]

from parrot_formdesigner.services._identifiers import qualified_table, validate_identifier

DEFAULT_BATCH_SIZE = 1000


def is_envelope(value: Any) -> bool:
    """Local mirror of core.voice_answer.is_voice_envelope (kept standalone on purpose)."""
    return isinstance(value, dict) and "answer" in value and (value.get("source") == "speech" or "blob_ref" in value)


@dataclass
class EnvelopeReport:
    """Inventory + orphan + downgrade summary."""

    envelopes_by_field: dict[str, int] = field(default_factory=dict)  # "form_uid/field_id" → count
    orphan_blob_refs: list[str] = field(default_factory=list)
    downgraded: int = 0
    lost_blob_refs: int = 0
    orphan_check: str = "skipped"
    applied: bool = False
    sink_columns_downgraded: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Return a human-readable summary."""
        total = sum(self.envelopes_by_field.values())
        lines = [f"Voice envelopes: {total} across {len(self.envelopes_by_field)} form/field pair(s)"]
        lines.extend(f"  - {key}: {count}" for key, count in sorted(self.envelopes_by_field.items()))
        lines.append(f"Orphan check: {self.orphan_check}")
        lines.append(f"Orphan blob_refs: {len(self.orphan_blob_refs)}")
        lines.extend(f"  - {ref}" for ref in self.orphan_blob_refs)
        if self.downgraded or self.lost_blob_refs or self.sink_columns_downgraded:
            mode = "applied" if self.applied else "would apply (dry — pass --apply to write)"
            lines.append(
                f"Downgrade {mode}: {self.downgraded} envelope(s) to scalar, "
                f"{self.lost_blob_refs} blob_ref(s) lost, "
                f"{len(self.sink_columns_downgraded)} sink column(s) JSONB -> TEXT"
            )
            lines.extend(f"  - {c}" for c in self.sink_columns_downgraded)
        return "\n".join(lines)


def blob_exists(blob_url: str | None, blob_ref: str) -> bool | None:
    """True/False for a ``file://``/path root; None when the URL scheme is unsupported (check skipped)."""
    if not blob_url:
        return None
    parsed = urlparse(blob_url)
    if parsed.scheme in ("", "file"):
        root = Path(unquote(parsed.path) if parsed.scheme == "file" else blob_url)
    else:
        return None
    key = blob_ref.split("://", 1)[1] if "://" in blob_ref else blob_ref
    key = key.lstrip("/")
    candidates = [root / key]
    # Key layout is {prefix}{form_uid}/{field_uid}/{blob_id}; a bucket segment may precede it.
    parts = key.split("/")
    if len(parts) > 3:
        candidates.append(root / "/".join(parts[-3:]))
    return any(c.exists() for c in candidates)


def _load_sink_helpers() -> Any:
    """Load the sibling 009 sink script (not a package) for ``envelope_columns``."""
    path = Path(__file__).with_name("009_voice_envelope_sink_tables.py")
    spec = importlib.util.spec_from_file_location("voice_envelope_sink_009_sibling", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _downgrade_sql(qualified: str, column: str) -> str:
    """``ALTER COLUMN … TYPE TEXT`` that unwraps envelopes and keeps bare JSON scalars (never NULLs them)."""
    return (
        f'ALTER TABLE {qualified} ALTER COLUMN "{column}" TYPE TEXT USING '
        f"(CASE WHEN jsonb_typeof(\"{column}\") = 'object' AND \"{column}\" ? 'answer' "
        f"THEN \"{column}\"->>'answer' ELSE \"{column}\" #>> '{{}}' END)"
    )


async def _downgrade_sink_columns(conn: Any, form_schemas_qt: str, report: EnvelopeReport, apply: bool) -> None:
    helpers = _load_sink_helpers()
    seen: set[tuple[str, str, str]] = set()
    rows = await conn.fetch(f"SELECT id, schema_json FROM {form_schemas_qt} ORDER BY id")
    for row in rows:
        doc = _as_dict(row["schema_json"])
        target = ((doc.get("persistence") or {}).get("data")) or {}
        if target.get("type") != "postgres_table":
            continue
        t_schema = validate_identifier(str(target.get("schema_name") or target.get("schema")), kind="schema")
        table = validate_identifier(str(target.get("table")), kind="table")
        existing = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = $1 AND table_name = $2",
            t_schema,
            table,
        )
        types = {r["column_name"]: str(r["data_type"]).lower() for r in existing}
        for col in helpers.envelope_columns(doc):
            key = (t_schema, table, col)
            if key in seen or types.get(col) != "jsonb":
                continue
            seen.add(key)
            qt = qualified_table(t_schema, table)
            cid = validate_identifier(col, kind="column")
            report.sink_columns_downgraded.append(f"{t_schema}.{table}.{col}")
            if apply:
                await conn.execute(_downgrade_sql(qt, cid))


async def run_report(
    pool: Any,
    *,
    schema: str,
    blob_url: str | None = None,
    downgrade: bool = False,
    apply: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> EnvelopeReport:
    """Scan form_data.data for envelopes; optionally downgrade (only when apply=True)."""
    validate_identifier(schema, kind="schema")
    form_data_qt = qualified_table(schema, "form_data")
    form_schemas_qt = qualified_table(schema, "form_schemas")
    report = EnvelopeReport(applied=bool(downgrade and apply))
    probe = blob_exists(blob_url, "x://probe") if blob_url else None
    report.orphan_check = (
        "performed"
        if probe is not None
        else ("skipped (unsupported blob url)" if blob_url else "skipped (no --blob-url)")
    )

    async with pool.acquire() as conn:
        # A destructive downgrade is all-or-nothing: form_data rewrites and column ALTERs share one transaction.
        async with conn.transaction() if (downgrade and apply) else nullcontext():
            await _scan(conn, report, form_data_qt, form_schemas_qt, blob_url, probe, downgrade, apply, batch_size)
    return report


async def _scan(
    conn: Any,
    report: EnvelopeReport,
    form_data_qt: str,
    form_schemas_qt: str,
    blob_url: str | None,
    probe: Any,
    downgrade: bool,
    apply: bool,
    batch_size: int,
) -> None:
    """Scan ``form_data`` in batches, then (optionally) downgrade the sink columns."""
    last_id: Any = None
    while True:
        if last_id is None:
            rows = await conn.fetch(f"SELECT id, form_uid, data FROM {form_data_qt} ORDER BY id LIMIT $1", batch_size)
        else:
            rows = await conn.fetch(
                f"SELECT id, form_uid, data FROM {form_data_qt} WHERE id > $1 ORDER BY id LIMIT $2",
                last_id,
                batch_size,
            )
        if not rows:
            break
        for row in rows:
            last_id = row["id"]
            data = _as_dict(row["data"])
            new_data = dict(data)
            changed = False
            for fid, value in data.items():
                if not is_envelope(value):
                    continue
                key = f"{row['form_uid']}/{fid}"
                report.envelopes_by_field[key] = report.envelopes_by_field.get(key, 0) + 1
                ref = value.get("blob_ref")
                if ref:
                    if report.orphan_check == "performed" and blob_exists(blob_url, str(ref)) is False:
                        report.orphan_blob_refs.append(str(ref))
                    if downgrade:
                        report.lost_blob_refs += 1
                if downgrade:
                    new_data[fid] = value.get("answer")
                    report.downgraded += 1
                    changed = True
            if changed and apply:
                await conn.execute(
                    f"UPDATE {form_data_qt} SET data = $1::jsonb WHERE id = $2",
                    json.dumps(new_data),
                    row["id"],
                )
    if downgrade:
        await _downgrade_sink_columns(conn, form_schemas_qt, report, apply)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Voice envelope inventory, orphan blob_refs and reversible downgrade (FEAT-649, TASK-4230)."
    )
    parser.add_argument("--dsn", required=True, help="asyncpg DSN, e.g. postgresql://user:pw@host/db")
    parser.add_argument("--schema", required=True, help="Postgres schema containing form_schemas/form_data")
    parser.add_argument("--blob-url", default=None, help="file:// or filesystem root for the orphan blob check")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Rows per batch")
    parser.add_argument(
        "--downgrade", action="store_true", help="Revert envelopes to scalars (destructive with --apply)"
    )
    parser.add_argument("--apply", action="store_true", help="Actually write; without it nothing is modified")
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
        report = await run_report(
            pool,
            schema=args.schema,
            blob_url=args.blob_url,
            downgrade=args.downgrade,
            apply=args.apply,
            batch_size=args.batch_size,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary, report and exit cleanly
        print(f"error: report failed: {exc}", file=sys.stderr)
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
