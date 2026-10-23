"""SourceCollectionManager sync calls must not disturb the caller's event loop."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.wiki.models import SourceManifestEntry
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.sources_backend import AsyncSourceBackendBridge, JsonSourceBackend, SqliteSourceBackend
from .test_source_backends import FakeArangoDb


def _entry(source_id: str) -> SourceManifestEntry:
    return SourceManifestEntry(
        source_id=source_id,
        source_uri=f"/documents/{source_id}.md",
        file_hash="h",
        mtime=1.0,
        ingested_at="2026-10-15T00:00:00Z",
    )


def _exercise(manager: SourceCollectionManager) -> None:
    manager._upsert(_entry("a"))
    manager._upsert_many([_entry("b")])
    assert manager.get_source("a") is not None
    assert len(manager.list_sources()) == 2


@pytest.mark.parametrize("backend", ["sqlite", "json", "arangodb"])
def test_sync_calls_leave_event_loop_usable(tmp_path: Path, backend: str) -> None:
    """After sync manager calls, get_event_loop() and a later asyncio.run() still work."""
    asyncio.set_event_loop(asyncio.new_event_loop())
    loop_before = asyncio.get_event_loop()
    options: dict[str, Any] = {"backend": backend}
    if backend == "arangodb":
        options["arango_db"] = FakeArangoDb()
    manager = SourceCollectionManager(tmp_path / backend / "sources", **options)

    _exercise(manager)

    assert asyncio.get_event_loop() is loop_before
    assert asyncio.run(asyncio.sleep(0, "ok")) == "ok"
    loop_before.close()


@pytest.mark.parametrize("backend", ["sqlite", "json"])
def test_local_backends_are_synchronous(tmp_path: Path, backend: str) -> None:
    """Local kinds use sync backends directly (no asyncio bridge)."""
    manager = SourceCollectionManager(tmp_path / "sources", backend=backend)
    assert isinstance(manager._backend, SqliteSourceBackend if backend == "sqlite" else JsonSourceBackend)
    assert not isinstance(manager._backend, AsyncSourceBackendBridge)


@pytest.mark.asyncio
async def test_local_backend_works_inside_running_loop(tmp_path: Path) -> None:
    """Sync manager calls from within a running loop do not spawn a new loop."""
    manager = SourceCollectionManager(tmp_path / "sources", backend="sqlite")
    running = asyncio.get_running_loop()
    _exercise(manager)
    assert asyncio.get_running_loop() is running


def test_arango_document_shape_is_original_twelve_fields(tmp_path: Path) -> None:
    """The Arango backend persists exactly the original 12 document fields."""
    db = FakeArangoDb()
    manager = SourceCollectionManager(tmp_path / "sources", backend="arangodb", arango_db=db)
    manager._upsert(_entry("a"))
    assert set(db.documents["a"]) == {
        "_key", "source_id", "source_uri", "file_hash", "mtime", "ingested_at",
        "pages_generated", "status", "doc_metadata", "content_type", "loader", "external_id",
    }
