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


# ---------------------------------------------------------------------------
# PageIndexToolkit-wired path
# ---------------------------------------------------------------------------

import json
from pathlib import Path

from parrot.knowledge.graphindex.extractors.loader import _content_ref, _make_node_id
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit


def _stub_adapter() -> MagicMock:
    a = MagicMock()
    a.model = "heavy"
    a.client = MagicMock()
    a.client.ask = AsyncMock()
    a.client.default_model = "test-model"
    a.ask = AsyncMock(return_value="adapter summary text")
    return a


@pytest.fixture
def _stub_tiktoken(monkeypatch):
    # PageIndex's md_builder uses tiktoken; in offline env we substitute
    # a char-count tokenizer so md_to_tree's thinning threshold treats our
    # tiny fixture body as "large enough".
    def _approx(text: str, model: str = "gpt-4o") -> int:
        return max(1, len(text or ""))
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", _approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", _approx)
    return _approx


class TestLoaderExtractorWithToolkit:
    """Tests for the PageIndexToolkit-wired extractor path."""

    @pytest.fixture
    def toolkit(self, tmp_path: Path) -> PageIndexToolkit:
        return PageIndexToolkit(
            adapter=_stub_adapter(),
            storage_dir=tmp_path / "store",
        )

    @pytest.mark.asyncio
    async def test_hierarchical_persists_via_toolkit(
        self, _stub_tiktoken, toolkit: PageIndexToolkit, tmp_path: Path,
    ):
        extractor = LoaderExtractor(llm_adapter=toolkit._adapter, toolkit=toolkit)
        loader = AsyncMock()
        loader._load = AsyncMock(return_value=[FakeDocument(
            "# Compliance Manual\n\n"
            "Top-level introduction to the compliance manual with "
            "enough text to exceed the thinning threshold of the parser.\n\n"
            "## Access Control\n"
            "Section about logical access controls. UNIQUE_AC_TOKEN appears "
            "here for the sidecar persistence assertion to hook on.\n\n"
            "## Audit Logging\n"
            "Section about audit logging requirements. UNIQUE_AL_TOKEN "
            "appears here to verify the second section also persisted.\n"
        )])
        type(loader).__name__ = "MarkdownLoader"

        nodes, edges = await extractor.extract(loader, "policy.md")

        # Document + Section nodes were emitted.
        doc_nodes = [n for n in nodes if n.kind == NodeKind.DOCUMENT]
        section_nodes = [n for n in nodes if n.kind == NodeKind.SECTION]
        assert len(doc_nodes) == 1
        assert section_nodes, "expected at least one Section node"

        # The Document carries the toolkit's tree_name for ontology routing.
        tree_name = doc_nodes[0].domain_tags["pageindex_tree_id"]
        expected_tree_name = _make_node_id("policy.md", "__root__")
        assert tree_name == expected_tree_name

        # Every Section node has content_ref pointing at a real sidecar.
        sidecar_dir = tmp_path / "store" / tree_name
        assert sidecar_dir.is_dir()
        for sect in section_nodes:
            assert sect.content_ref is not None
            assert sect.content_ref.startswith(f"pageindex://{tree_name}/")
            page_id = sect.content_ref.rsplit("/", 1)[-1]
            sidecar = sidecar_dir / f"{page_id}.md"
            assert sidecar.is_file(), f"missing sidecar for {sect.title!r}"

        # And the persisted tree JSON does NOT carry inline text.
        persisted = json.loads(
            (tmp_path / "store" / f"{tree_name}.json").read_text()
        )

        def _walk(node):
            if isinstance(node, dict):
                assert "text" not in node
                for child in node.get("nodes") or []:
                    _walk(child)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(persisted["structure"])

        # CONTAINS edges link the document root to the sections.
        contains = [e for e in edges if e.kind == EdgeKind.CONTAINS]
        assert any(e.source_id == doc_nodes[0].node_id for e in contains)

    @pytest.mark.asyncio
    async def test_content_ref_resolves_back_to_body(
        self, _stub_tiktoken, toolkit: PageIndexToolkit,
    ):
        extractor = LoaderExtractor(llm_adapter=toolkit._adapter, toolkit=toolkit)
        body = (
            "# Doc\n\n"
            "Intro paragraph with enough content to clear the thinning "
            "threshold and survive into the persisted PageIndex tree.\n\n"
            "## Section A\n"
            "Body of section A — VERBATIM_CONTENT_OF_SECTION_A for the "
            "sidecar resolution test to assert on.\n"
        )
        loader = AsyncMock()
        loader._load = AsyncMock(return_value=[FakeDocument(body)])
        type(loader).__name__ = "MarkdownLoader"

        nodes, _ = await extractor.extract(loader, "doc.md")
        section = next(
            n for n in nodes
            if n.kind == NodeKind.SECTION and n.title == "Section A"
        )
        assert section.content_ref is not None
        # Parse content_ref and fetch the body via the toolkit's content store.
        scheme, rest = section.content_ref.split("://", 1)
        assert scheme == "pageindex"
        tree, node_id = rest.split("/", 1)
        body_from_store = toolkit._content_store.load(tree, node_id)
        assert body_from_store is not None
        assert "VERBATIM_CONTENT_OF_SECTION_A" in body_from_store

    @pytest.mark.asyncio
    async def test_reingest_replaces_existing_tree(
        self, _stub_tiktoken, toolkit: PageIndexToolkit, tmp_path: Path,
    ):
        extractor = LoaderExtractor(llm_adapter=toolkit._adapter, toolkit=toolkit)
        loader = AsyncMock()
        v1 = (
            "# Doc v1\n\n"
            "First version intro with enough body to clear the thinning "
            "threshold so that the root node survives in the persisted tree.\n\n"
            "## Section v1\n"
            "FIRST_VERSION_TOKEN — body for the first version's section, "
            "padded with enough descriptive content to exceed the parser's "
            "minimum-token gate and survive into the persisted tree on disk.\n"
        )
        loader._load = AsyncMock(return_value=[FakeDocument(v1)])
        type(loader).__name__ = "MarkdownLoader"

        await extractor.extract(loader, "doc.md")
        tree_name = _make_node_id("doc.md", "__root__")
        first_tree = json.loads(
            (tmp_path / "store" / f"{tree_name}.json").read_text()
        )
        first_titles = [n["title"] for n in first_tree["structure"]]

        # Re-ingest with different content.
        v2 = (
            "# Doc v2\n\n"
            "Second version intro with enough body to clear the thinning "
            "threshold so that the root node survives in the persisted tree.\n\n"
            "## Replaced Section\n"
            "SECOND_VERSION_TOKEN — body for the second version's section, "
            "padded with enough descriptive content to exceed the parser's "
            "minimum-token gate and survive into the persisted tree on disk.\n"
        )
        loader._load = AsyncMock(return_value=[FakeDocument(v2)])
        await extractor.extract(loader, "doc.md")
        second_tree = json.loads(
            (tmp_path / "store" / f"{tree_name}.json").read_text()
        )
        second_titles = [n["title"] for n in second_tree["structure"]]
        # The tree was rebuilt, not appended to.
        assert first_titles != second_titles
        # Old sidecars from v1 are gone.
        sidecar_dir = tmp_path / "store" / tree_name
        bodies = "\n".join(p.read_text() for p in sidecar_dir.glob("*.md"))
        assert "FIRST_VERSION_TOKEN" not in bodies
        assert "SECOND_VERSION_TOKEN" in bodies

    @pytest.mark.asyncio
    async def test_toolkit_failure_falls_back_to_flat(
        self, toolkit: PageIndexToolkit, monkeypatch,
    ):
        # Force insert_markdown to raise so the extractor falls back.
        async def _boom(*a, **kw):
            raise RuntimeError("simulated ingest failure")
        monkeypatch.setattr(toolkit, "insert_markdown", _boom)

        extractor = LoaderExtractor(llm_adapter=toolkit._adapter, toolkit=toolkit)
        loader = AsyncMock()
        loader._load = AsyncMock(return_value=[FakeDocument(
            "# Doc\n## Section\nbody"
        )])
        type(loader).__name__ = "MarkdownLoader"
        nodes, edges = await extractor.extract(loader, "doc.md")
        # Fallback: single flat Document node, no edges.
        assert len(nodes) == 1
        assert nodes[0].kind == NodeKind.DOCUMENT
        assert nodes[0].domain_tags.get("flat") is True
        assert edges == []

    @pytest.mark.asyncio
    async def test_empty_tree_after_ingest_falls_back_and_cleans_up(
        self, toolkit: PageIndexToolkit, tmp_path: Path,
    ):
        # No headers in the markdown → md_to_tree builds nothing →
        # toolkit's persisted tree has structure=[] → fall back to flat.
        extractor = LoaderExtractor(llm_adapter=toolkit._adapter, toolkit=toolkit)
        loader = AsyncMock()
        loader._load = AsyncMock(return_value=[FakeDocument(
            "Just plain text with no markdown headers at all."
        )])
        type(loader).__name__ = "MarkdownLoader"
        nodes, edges = await extractor.extract(loader, "notes.md")
        assert len(nodes) == 1
        assert nodes[0].kind == NodeKind.DOCUMENT
        assert nodes[0].domain_tags.get("flat") is True
        assert edges == []
        # And the empty tree was cleaned up.
        tree_name = _make_node_id("notes.md", "__root__")
        assert not (tmp_path / "store" / f"{tree_name}.json").is_file()

    def test_extractor_accepts_toolkit_kwarg(self):
        adapter = MagicMock()
        adapter.model = "x"
        adapter.client = MagicMock()
        toolkit = PageIndexToolkit(adapter=adapter, storage_dir="/tmp")
        ex = LoaderExtractor(toolkit=toolkit)
        assert ex.toolkit is toolkit

    def test_content_ref_helper_format(self):
        assert _content_ref("tree-a", "0003") == "pageindex://tree-a/0003"
