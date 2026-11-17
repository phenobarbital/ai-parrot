"""Copy user-store documents from DocumentDB into Redis (FEAT-878).

Sealed values are copied verbatim and are not re-sealed.

Usage::

    python -m parrot.userstore.copy --dry-run
    python -m parrot.userstore.copy
    python -m parrot.userstore.copy --collections user_credentials,user_llm_keys --overwrite
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from parrot.interfaces.documentdb import DocumentDb

from .collections import USER_STORE_COLLECTIONS, CollectionSpec
from .redis_documents import RedisDocumentStore

logger = logging.getLogger("parrot.userstore.copy")

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class CopyReport:
    """Per-collection counts produced by a copy operation."""

    copied: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    duplicates: dict[str, int] = field(default_factory=dict)
    failed: dict[str, int] = field(default_factory=dict)

    @property
    def any_failed(self) -> bool:
        """Return whether at least one source document failed to copy."""
        return any(self.failed.values())


def _when(value: Any) -> datetime | None:
    """Return an aware datetime for an ``updated_at`` value, or ``None``."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else ""))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _newest_per_key(
    spec: CollectionSpec,
    docs: list[dict[str, Any]],
    report: CopyReport,
) -> list[dict[str, Any]]:
    """Collapse duplicate keys to the newest document and count discarded documents."""
    newest: dict[tuple[str, ...], dict[str, Any]] = {}
    for document in docs:
        key = tuple(str(document.get(field)) for field in spec.key_fields)
        current = newest.get(key)
        if current is None:
            newest[key] = document
            continue
        report.duplicates[spec.name] += 1
        if (_when(document.get("updated_at")) or _EPOCH) > (_when(current.get("updated_at")) or _EPOCH):
            newest[key] = document
    return list(newest.values())


def _identity(spec: CollectionSpec, document: dict[str, Any]) -> tuple[Any, ...]:
    """Return only the collection key fields used to identify a document in logs."""
    return tuple(document.get(field) for field in spec.key_fields)


async def _copy_collection(
    spec: CollectionSpec,
    report: CopyReport,
    *,
    dry_run: bool,
    overwrite: bool,
) -> None:
    """Copy one DocumentDB collection into its Redis document store."""
    for counts in (report.copied, report.skipped, report.duplicates, report.failed):
        counts.setdefault(spec.name, 0)

    async with DocumentDb() as db:
        documents = await db.read(spec.name, {}) or []
    clean_documents = [{key: value for key, value in document.items() if key != "_id"} for document in documents]
    store = RedisDocumentStore(spec)

    for document in _newest_per_key(spec, clean_documents, report):
        try:
            existing = await store.get(document)
            should_write = existing is None
            if existing is not None and overwrite:
                source_updated = _when(document.get("updated_at"))
                target_updated = _when(existing.get("updated_at"))
                should_write = source_updated is not None and source_updated > (target_updated or _EPOCH)

            if not should_write:
                report.skipped[spec.name] += 1
                continue
            if not dry_run:
                await store.put(document)
            report.copied[spec.name] += 1
        except Exception as exc:  # noqa: BLE001 - malformed input and storage failures are counted per document
            report.failed[spec.name] += 1
            logger.warning(
                "userstore copy failed collection=%s identity=%s error=%s",
                spec.name,
                _identity(spec, document),
                type(exc).__name__,
            )


async def copy_to_redis(
    collections: Sequence[str] | None = None,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> CopyReport:
    """Copy selected collections, defaulting to every registered user-store collection."""
    report = CopyReport()
    for name in collections or list(USER_STORE_COLLECTIONS):
        await _copy_collection(USER_STORE_COLLECTIONS[name], report, dry_run=dry_run, overwrite=overwrite)
    return report


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(prog="python -m parrot.userstore.copy")
    parser.add_argument("--dry-run", action="store_true", help="count changes without writing to Redis")
    parser.add_argument("--overwrite", action="store_true", help="replace existing documents only when source is newer")
    parser.add_argument("--collections", help="comma-separated collection names (default: all)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the copy CLI and return 1 on document failures or 2 on bad arguments."""
    parser = _parser()
    args = parser.parse_args(argv)
    collections = [name.strip() for name in args.collections.split(",") if name.strip()] if args.collections else None
    unknown = sorted(set(collections or ()) - USER_STORE_COLLECTIONS.keys())
    if unknown:
        parser.error(
            f"unknown collection(s): {', '.join(unknown)}; valid names: {', '.join(sorted(USER_STORE_COLLECTIONS))}"
        )

    report = asyncio.run(copy_to_redis(collections, dry_run=args.dry_run, overwrite=args.overwrite))
    label = "would copy" if args.dry_run else "copied"
    print(f"{label}: {report.copied}")
    print(f"skipped: {report.skipped}")
    print(f"duplicates: {report.duplicates}")
    print(f"failed: {report.failed}")
    return 1 if report.any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
