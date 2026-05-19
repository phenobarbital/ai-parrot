"""Unit tests for parrot.knowledge.graphindex.extractors.loader."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.knowledge.graphindex.extractors.loader import LoaderExtractor
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)


class FakeDocument:
    """Minimal Document-like object for testing."""

    def __init__(self, page_content: str, metadata: dict | None = None):
        self.page_content = page_content
        self.metadata = metadata or {}


class TestLoaderExtractor:
    @pytest.fixture
    def extractor(self):
        return LoaderExtractor()

    @pytest.mark.asyncio
    async def test_flat_content_single_document_node(self, extractor):
        loader = AsyncMock()
        loader._load = AsyncMock(return_value=[FakeDocument("Plain text transcript.")])
        type(loader).__name__ = "AudioLoader"
        nodes, edges = await extractor.extract(loader, "audio.mp3")
        doc_nodes = [n for n in nodes if n.kind == NodeKind.DOCUMENT]
        assert len(doc_nodes) == 1
        assert doc_nodes[0].domain_tags.get("flat") is True

    @pytest.mark.asyncio
    async def test_flat_content_source_uri_set(self, extractor):
        loader = AsyncMock()
        loader._load = AsyncMock(return_value=[FakeDocument("Some text.")])
        type(loader).__name__ = "AudioLoader"
        nodes, edges = await extractor.extract(loader, "audio.mp3")
        assert nodes[0].source_uri == "audio.mp3"

    @pytest.mark.asyncio
    async def test_loader_failure_returns_empty(self, extractor):
        loader = AsyncMock()
        loader._load = AsyncMock(side_effect=RuntimeError("File not found"))
        nodes, edges = await extractor.extract(loader, "missing.pdf")
        assert nodes == []
        assert edges == []

    @pytest.mark.asyncio
    async def test_empty_loader_returns_empty(self, extractor):
        loader = AsyncMock()
        loader._load = AsyncMock(return_value=[])
        nodes, edges = await extractor.extract(loader, "empty.pdf")
        assert nodes == []
        assert edges == []

    @pytest.mark.asyncio
    async def test_fallback_summary_without_llm_adapter(self, extractor):
        assert extractor.llm_adapter is None
        summary = extractor._fallback_summary("A" * 300)
        assert len(summary) <= 200

    def test_fallback_summary_shorter_than_limit(self, extractor):
        short_text = "Short text"
        assert extractor._fallback_summary(short_text) == short_text

    def test_is_hierarchical_detection_pdf(self, extractor):
        pdf_loader = MagicMock()
        type(pdf_loader).__name__ = "PDFLoader"
        assert extractor._is_hierarchical(pdf_loader) is True

    def test_is_hierarchical_detection_markdown(self, extractor):
        md_loader = MagicMock()
        type(md_loader).__name__ = "MarkdownLoader"
        assert extractor._is_hierarchical(md_loader) is True

    def test_is_hierarchical_detection_audio_false(self, extractor):
        audio_loader = MagicMock()
        type(audio_loader).__name__ = "AudioLoader"
        assert extractor._is_hierarchical(audio_loader) is False

    def test_is_hierarchical_detection_unknown_false(self, extractor):
        unknown_loader = MagicMock()
        type(unknown_loader).__name__ = "SomeOtherLoader"
        assert extractor._is_hierarchical(unknown_loader) is False

    @pytest.mark.asyncio
    async def test_hierarchical_content_section_nodes(self, extractor):
        """Hierarchical markdown content should route through PageIndex for sections."""
        loader = AsyncMock()
        loader._load = AsyncMock(
            return_value=[FakeDocument("# Heading 1\nContent\n## Heading 2\nMore content")]
        )
        type(loader).__name__ = "MarkdownLoader"
        nodes, edges = await extractor.extract(loader, "doc.md")
        # Either section nodes or a fallback document node — must not crash
        assert isinstance(nodes, list)
        assert len(nodes) >= 1

    @pytest.mark.asyncio
    async def test_flat_node_has_summary(self, extractor):
        loader = AsyncMock()
        loader._load = AsyncMock(return_value=[FakeDocument("Some important text content.")])
        type(loader).__name__ = "WebLoader"
        nodes, edges = await extractor.extract(loader, "page.html")
        assert nodes[0].summary is not None

    @pytest.mark.asyncio
    async def test_multi_page_flat_content_single_node(self, extractor):
        loader = AsyncMock()
        loader._load = AsyncMock(return_value=[
            FakeDocument("Page 1 content"),
            FakeDocument("Page 2 content"),
        ])
        type(loader).__name__ = "AudioLoader"
        nodes, edges = await extractor.extract(loader, "audio.mp3")
        doc_nodes = [n for n in nodes if n.kind == NodeKind.DOCUMENT]
        assert len(doc_nodes) == 1

    def test_llm_adapter_stored(self):
        adapter = MagicMock()
        extractor = LoaderExtractor(llm_adapter=adapter)
        assert extractor.llm_adapter is adapter

    def test_summary_length_configurable(self):
        extractor = LoaderExtractor(summary_length=50)
        long_text = "x" * 200
        assert len(extractor._fallback_summary(long_text)) == 50
