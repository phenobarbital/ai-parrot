"""Integration tests for TASK-1576: builder/loader wiring for FEAT-240."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.graphindex.builder import GraphIndexBuilder
from parrot.knowledge.graphindex.extractors.code import CodeExtractor
from parrot.knowledge.graphindex.extractors.odoo_code import OdooCodeExtractor


# ---------------------------------------------------------------------------
# Shared helpers / minimal stubs
# ---------------------------------------------------------------------------


def _mock_embedder() -> Any:
    """Return a mock GraphIndexEmbedder that does nothing."""
    embedder = MagicMock()
    embedder.embed = AsyncMock(side_effect=lambda nodes: nodes)
    return embedder


def _mock_persistence() -> Any:
    """Return a mock persistence with no-op methods."""
    p = MagicMock()
    p.persist_graph = AsyncMock(
        return_value={"nodes_persisted": 0, "edges_persisted": 0}
    )
    p.replace_document_slice = AsyncMock(
        return_value={"nodes_replaced": 0, "edges_replaced": 0}
    )
    return p


def _mock_null_persistence() -> Any:
    """Return a mock persistence WITHOUT is_stale (simulates ArangoDB backend)."""
    p = _mock_persistence()
    # Ensure is_stale does not exist on this mock
    del p.is_stale
    return p


def _mock_sqlite_persistence(stale: bool = True) -> Any:
    """Return a mock SQLitePersistence WITH is_stale."""
    p = _mock_persistence()
    p.is_stale = AsyncMock(return_value=stale)
    return p


def _make_builder(
    persistence=None,
    code_extractor_class=None,
) -> GraphIndexBuilder:
    """Create a GraphIndexBuilder with minimal mocks."""
    kwargs = {}
    if code_extractor_class is not None:
        kwargs["code_extractor_class"] = code_extractor_class
    return GraphIndexBuilder(
        persistence=persistence or _mock_null_persistence(),
        embedder=_mock_embedder(),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Tests: constructor
# ---------------------------------------------------------------------------


class TestBuilderConstructor:
    """Tests for the code_extractor_class constructor parameter."""

    def test_default_extractor_is_code_extractor(self):
        """Without code_extractor_class, the builder uses CodeExtractor."""
        builder = _make_builder()
        assert builder._code_extractor_class is CodeExtractor

    def test_custom_extractor_class_stored(self):
        """code_extractor_class is stored on the builder."""
        builder = _make_builder(code_extractor_class=OdooCodeExtractor)
        assert builder._code_extractor_class is OdooCodeExtractor

    def test_accepts_odoo_code_extractor(self):
        """GraphIndexBuilder accepts OdooCodeExtractor without error."""
        builder = GraphIndexBuilder(
            persistence=_mock_null_persistence(),
            embedder=_mock_embedder(),
            code_extractor_class=OdooCodeExtractor,
        )
        assert builder._code_extractor_class is OdooCodeExtractor


# ---------------------------------------------------------------------------
# Tests: extractor instantiation in _extract_code
# ---------------------------------------------------------------------------


class TestExtractCodeExtractorClass:
    """Tests that _extract_code instantiates the configured extractor class."""

    @pytest.mark.asyncio
    async def test_extract_code_uses_configured_class(self, tmp_path):
        """_extract_code instantiates code_extractor_class, not CodeExtractor."""
        py_file = tmp_path / "mod.py"
        py_file.write_text("x = 1\n")

        instantiated = []

        class TrackingExtractor(CodeExtractor):
            def __init__(self):
                super().__init__()
                instantiated.append(self)

        builder = _make_builder(code_extractor_class=TrackingExtractor)

        # Minimal SourceConfig-like object
        sources = MagicMock()
        sources.code_paths = [str(tmp_path)]
        sources.loader_sources = []
        sources.skill_paths = []

        await builder._extract_code(sources)
        assert len(instantiated) >= 1, "Configured extractor class was not instantiated"

    @pytest.mark.asyncio
    async def test_extract_code_passes_mtime(self, tmp_path):
        """_extract_code passes mtime keyword argument to extractor.extract()."""
        py_file = tmp_path / "mod.py"
        py_file.write_text("x = 1\n")

        extract_kwargs: list[dict] = []

        class RecordingExtractor(CodeExtractor):
            async def extract(self, file_path, source, *, mtime=None):
                extract_kwargs.append({"file_path": file_path, "mtime": mtime})
                return await super().extract(file_path, source, mtime=mtime)

        builder = _make_builder(code_extractor_class=RecordingExtractor)
        sources = MagicMock()
        sources.code_paths = [str(tmp_path)]
        sources.loader_sources = []
        sources.skill_paths = []

        await builder._extract_code(sources)
        assert len(extract_kwargs) >= 1
        assert extract_kwargs[0]["mtime"] is not None
        assert isinstance(extract_kwargs[0]["mtime"], float)

    @pytest.mark.asyncio
    async def test_extract_code_skips_unchanged_files(self, tmp_path):
        """When is_stale returns False, extract() is NOT called for that file."""
        py_file = tmp_path / "mod.py"
        content = "x = 1\n"
        py_file.write_text(content)

        persistence = _mock_sqlite_persistence(stale=False)

        extract_calls = []

        class TrackingExtractor(CodeExtractor):
            async def extract(self, file_path, source, *, mtime=None):
                extract_calls.append(file_path)
                return await super().extract(file_path, source, mtime=mtime)

        builder = _make_builder(
            persistence=persistence,
            code_extractor_class=TrackingExtractor,
        )
        sources = MagicMock()
        sources.code_paths = [str(tmp_path)]
        sources.loader_sources = []
        sources.skill_paths = []
        # Give sources a ctx attribute so is_stale can be called
        sources.ctx = MagicMock()
        sources.ctx.tenant_id = "test"

        await builder._extract_code(sources)

        # is_stale was called
        assert persistence.is_stale.called
        # extract was NOT called (file is not stale)
        assert len(extract_calls) == 0

    @pytest.mark.asyncio
    async def test_extract_code_processes_stale_files(self, tmp_path):
        """When is_stale returns True, extract() IS called for that file."""
        py_file = tmp_path / "mod.py"
        py_file.write_text("x = 1\n")

        persistence = _mock_sqlite_persistence(stale=True)

        extract_calls = []

        class TrackingExtractor(CodeExtractor):
            async def extract(self, file_path, source, *, mtime=None):
                extract_calls.append(file_path)
                return await super().extract(file_path, source, mtime=mtime)

        builder = _make_builder(
            persistence=persistence,
            code_extractor_class=TrackingExtractor,
        )
        sources = MagicMock()
        sources.code_paths = [str(tmp_path)]
        sources.loader_sources = []
        sources.skill_paths = []
        sources.ctx = MagicMock()

        await builder._extract_code(sources)

        assert len(extract_calls) >= 1

    @pytest.mark.asyncio
    async def test_extract_code_no_stale_check_without_is_stale(self, tmp_path):
        """When persistence has no is_stale, all files are extracted."""
        py_file = tmp_path / "mod.py"
        py_file.write_text("x = 1\n")

        persistence = _mock_null_persistence()
        assert not hasattr(persistence, "is_stale")

        extract_calls = []

        class TrackingExtractor(CodeExtractor):
            async def extract(self, file_path, source, *, mtime=None):
                extract_calls.append(file_path)
                return await super().extract(file_path, source, mtime=mtime)

        builder = _make_builder(
            persistence=persistence,
            code_extractor_class=TrackingExtractor,
        )
        sources = MagicMock()
        sources.code_paths = [str(tmp_path)]
        sources.loader_sources = []
        sources.skill_paths = []

        await builder._extract_code(sources)

        # File extracted without is_stale guard
        assert len(extract_calls) >= 1


# ---------------------------------------------------------------------------
# Tests: loader SQLite backend
# ---------------------------------------------------------------------------


class TestLoaderSQLiteBackend:
    """Tests for sqlite_dir parameter in GraphIndexLoader."""

    def test_loader_accepts_sqlite_dir(self, tmp_path):
        """GraphIndexLoader accepts sqlite_dir without error."""
        from parrot.knowledge.graphindex.loader import GraphIndexLoader

        loader = GraphIndexLoader(sqlite_dir=tmp_path)
        assert loader._sqlite_dir == tmp_path

    def test_loader_sqlite_dir_none_by_default(self):
        """sqlite_dir defaults to None."""
        from parrot.knowledge.graphindex.loader import GraphIndexLoader

        loader = GraphIndexLoader()
        assert loader._sqlite_dir is None

    @pytest.mark.asyncio
    async def test_make_persistence_returns_sqlite_when_dir_given(self, tmp_path):
        """_make_persistence returns SQLitePersistence when sqlite_dir is set."""
        from parrot.knowledge.graphindex.loader import GraphIndexLoader
        from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence

        loader = GraphIndexLoader(sqlite_dir=tmp_path)
        persistence = await loader._make_persistence()
        assert isinstance(persistence, SQLitePersistence)


# ---------------------------------------------------------------------------
# Tests: exports
# ---------------------------------------------------------------------------


class TestExports:
    """Tests that new components are exported from the graphindex package."""

    def test_sqlite_persistence_exported(self):
        """SQLitePersistence is importable from parrot.knowledge.graphindex."""
        from parrot.knowledge.graphindex import SQLitePersistence

        assert SQLitePersistence is not None

    def test_sqlite_graph_reader_exported(self):
        """SQLiteGraphReader is importable from parrot.knowledge.graphindex."""
        from parrot.knowledge.graphindex import SQLiteGraphReader

        assert SQLiteGraphReader is not None

    def test_odoo_code_extractor_exported_from_graphindex(self):
        """OdooCodeExtractor is importable from parrot.knowledge.graphindex."""
        from parrot.knowledge.graphindex import OdooCodeExtractor

        assert OdooCodeExtractor is not None

    def test_odoo_code_extractor_exported_from_extractors(self):
        """OdooCodeExtractor is importable from parrot.knowledge.graphindex.extractors."""
        from parrot.knowledge.graphindex.extractors import OdooCodeExtractor

        assert OdooCodeExtractor is not None
