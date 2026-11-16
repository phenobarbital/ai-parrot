"""Deterministic export of committed review evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore

EXPORT_FORMAT_VERSION = "v1"


class ExportError(Exception):
    """Raised when a review archive cannot be written safely."""


def _utcnow() -> datetime:
    """Return the current aware UTC time."""
    return datetime.now(timezone.utc)


def _write_archive(destination: Path, payload: bytes) -> None:
    """Atomically replace an archive using a destination-local unique temporary file."""
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as archive_file:
            archive_file.write(payload)
            archive_file.flush()
            os.fsync(archive_file.fileno())
        os.replace(temporary_path, destination)
    except Exception as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise ExportError(f"failed to write review export to {destination}: {exc}") from exc


async def export_reviews(
    *,
    namespace: MemoryNamespace,
    destination: Path,
    store: EpisodicMemoryStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Export the configured store's committed reviews as a replayable archive.

    Args:
        namespace: Exact namespace whose committed reviews are exported.
        destination: Archive path to atomically replace.
        store: Configured episodic store containing the authoritative reviews.
        clock: Optional aware clock for deterministic archive tests.

    Returns:
        Metadata about the written archive.

    Raises:
        ValueError: If no configured episodic store is supplied or the clock is naive.
        ExportError: If the archive cannot be written safely.
    """
    if store is None:
        raise ValueError("export requires the configured episodic store")

    reviews = await store.list_reviews(namespace)
    exported_at = (clock or _utcnow)()
    if exported_at.tzinfo is None or exported_at.utcoffset() is None:
        raise ValueError("export clock must return an aware datetime")

    archive = {
        "format": EXPORT_FORMAT_VERSION,
        "exported_at": exported_at.astimezone(timezone.utc).isoformat(),
        "namespace": namespace.model_dump(mode="json"),
        "provenance": {
            "backend": "SQLiteEpisodeBackend",
            "table": "reviews",
            "persisted_fields": ["command", "apply_revision", "recorded_at"],
            "optional_record_fields": [
                "grade",
                "before",
                "after",
                "parameter_id",
                "memory_error_signature",
            ],
        },
        "reviews": reviews,
    }
    payload = json.dumps(archive, sort_keys=True, separators=(",", ":")).encode("utf-8")
    content_hash = hashlib.sha256(payload).hexdigest()
    await asyncio.to_thread(_write_archive, destination, payload)
    return {
        "export_path": str(destination),
        "record_count": len(reviews),
        "content_hash": content_hash,
        "format_version": EXPORT_FORMAT_VERSION,
    }
