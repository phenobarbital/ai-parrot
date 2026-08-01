"""Unit tests for SourceCollectionManager's ArangoDB backend (FEAT-400, TASK-2060).

Mocks the ``arango_db`` connection the same way ``test_arango_store.py``
mocks ``asyncdb`` — no real ArangoDB server is needed.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.knowledge.wiki.models import SourceManifestEntry
from parrot.knowledge.wiki.sources import SourceCollectionManager


@pytest.fixture
def mock_arango_db():
    """Mocked ``asyncdb`` ArangoDB driver instance (already connected)."""
    db = MagicMock()
    db.query = AsyncMock(return_value=([], None))
    db.execute = AsyncMock(return_value=([], None))
    return db


@pytest.fixture
def manager(tmp_path: Path, mock_arango_db) -> SourceCollectionManager:
    """``SourceCollectionManager`` wired to the mocked ArangoDB connection."""
    return SourceCollectionManager(
        tmp_path / "sources", backend="arangodb", arango_db=mock_arango_db
    )


def _entry(source_id: str = "src-abc123") -> SourceManifestEntry:
    return SourceManifestEntry(
        source_id=source_id,
        source_uri=f"/docs/{source_id}.md",
        file_hash="deadbeef",
        mtime=123.456,
        ingested_at="2026-08-01T00:00:00Z",
        pages_generated=["p1", "p2"],
        status="ingested",
    )


class TestSourceCollectionManagerArangoInit:
    """Construction and validation of the ``arangodb`` backend."""

    def test_backend_accepted(self, tmp_path: Path, mock_arango_db):
        mgr = SourceCollectionManager(
            tmp_path / "sources", backend="arangodb", arango_db=mock_arango_db
        )
        assert mgr.backend == "arangodb"
        assert mgr._arango_db is mock_arango_db

    def test_arangodb_backend_requires_connection(self, tmp_path: Path):
        with pytest.raises(ValueError, match="requires an arango_db connection"):
            SourceCollectionManager(tmp_path / "sources", backend="arangodb")

    def test_unknown_backend_still_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Unknown sources backend"):
            SourceCollectionManager(tmp_path / "sources", backend="postgres")

    def test_sqlite_backend_unaffected(self, tmp_path: Path):
        mgr = SourceCollectionManager(tmp_path / "sources", backend="sqlite")
        assert mgr.backend == "sqlite"

    def test_json_backend_unaffected(self, tmp_path: Path):
        mgr = SourceCollectionManager(tmp_path / "sources", backend="json")
        assert mgr.backend == "json"


class TestSourceCollectionManagerArangoCRUD:
    """Public API dispatches correctly for the ``arangodb`` backend."""

    def test_upsert_via_add_source_like_call(self, manager, mock_arango_db):
        entry = _entry()
        manager._upsert(entry)
        mock_arango_db.execute.assert_awaited_once()
        aql = mock_arango_db.execute.call_args.args[0]
        bind_vars = mock_arango_db.execute.call_args.kwargs["bind_vars"]
        assert "UPSERT" in aql
        assert bind_vars["doc"]["source_id"] == entry.source_id
        assert bind_vars["@collection"] == "wiki_sources"

    def test_list_sources(self, manager, mock_arango_db):
        mock_arango_db.query = AsyncMock(
            return_value=(
                [
                    {
                        "source_id": "src-1",
                        "source_uri": "/a.md",
                        "file_hash": "h1",
                        "mtime": 1.0,
                        "ingested_at": "2026-08-01T00:00:00Z",
                        "pages_generated": ["p1"],
                        "status": "ingested",
                    }
                ],
                None,
            )
        )
        sources = manager.list_sources()
        assert len(sources) == 1
        assert sources[0].source_id == "src-1"

    def test_get_source_found(self, manager, mock_arango_db):
        mock_arango_db.query = AsyncMock(
            return_value=(
                [
                    {
                        "source_id": "src-1",
                        "source_uri": "/a.md",
                        "file_hash": "h1",
                        "mtime": 1.0,
                        "ingested_at": "2026-08-01T00:00:00Z",
                        "pages_generated": [],
                        "status": "ingested",
                    }
                ],
                None,
            )
        )
        entry = manager.get_source("src-1")
        assert entry is not None
        assert entry.source_id == "src-1"

    def test_get_source_not_found(self, manager, mock_arango_db):
        mock_arango_db.query = AsyncMock(return_value=([], None))
        assert manager.get_source("missing") is None

    def test_remove_source_found(self, manager, mock_arango_db):
        mock_arango_db.query = AsyncMock(
            return_value=([{"source_id": "src-1"}], None)
        )
        assert manager.remove_source("src-1") is True

    def test_remove_source_not_found(self, manager, mock_arango_db):
        mock_arango_db.query = AsyncMock(return_value=([], None))
        assert manager.remove_source("missing") is False

    def test_find_by_uri_found(self, manager, mock_arango_db):
        mock_arango_db.query = AsyncMock(return_value=(["src-1"], None))
        assert manager.find_by_uri("/a.md") == "src-1"

    def test_find_by_uri_not_found(self, manager, mock_arango_db):
        mock_arango_db.query = AsyncMock(return_value=([], None))
        assert manager.find_by_uri("/missing.md") is None

    def test_mark_ingested_roundtrip(self, manager, mock_arango_db, tmp_path):
        # get_source() (query) then _upsert() (execute) inside mark_ingested().
        src_file = tmp_path / "article.md"
        src_file.write_text("hello")
        existing = _entry("src-1")
        existing = SourceManifestEntry(
            **{**existing.model_dump(), "source_uri": str(src_file)}
        )
        mock_arango_db.query = AsyncMock(
            return_value=([existing.model_dump()], None)
        )
        updated = manager.mark_ingested("src-1", ["p1", "p2"], status="ingested")
        assert updated is not None
        assert updated.pages_generated == ["p1", "p2"]
        mock_arango_db.execute.assert_awaited_once()

    def test_mark_ingested_missing_source(self, manager, mock_arango_db):
        mock_arango_db.query = AsyncMock(return_value=([], None))
        assert manager.mark_ingested("missing", ["p1"]) is None


class TestArangoQueryHelpers:
    """Direct coverage of the private AQL bridging helpers."""

    @pytest.mark.asyncio
    async def test_arango_query_no_data_found_returns_empty(
        self, manager, mock_arango_db
    ):
        mock_arango_db.query = AsyncMock(
            return_value=(None, "ArangoDB: No Data Found")
        )
        result = await manager._arango_query("FOR doc IN @@collection RETURN doc", {})
        assert result == []

    @pytest.mark.asyncio
    async def test_arango_query_raises_on_real_error(self, manager, mock_arango_db):
        mock_arango_db.query = AsyncMock(return_value=(None, "Connection refused"))
        with pytest.raises(RuntimeError):
            await manager._arango_query("FOR doc IN @@collection RETURN doc", {})

    @pytest.mark.asyncio
    async def test_arango_execute_raises_on_error(self, manager, mock_arango_db):
        mock_arango_db.execute = AsyncMock(return_value=(None, "Write failed"))
        with pytest.raises(RuntimeError):
            await manager._arango_execute("REMOVE 'x' IN @@collection", {})
