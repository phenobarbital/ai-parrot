"""Tests for parrot.pageindex.toolkit.PageIndexToolkit (in-toolkit surface)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.pageindex.ingest import IngestedMarkdown
from parrot.pageindex.schemas import TreeSearchResult
from parrot.pageindex.toolkit import PageIndexToolkit


def _adapter() -> MagicMock:
    # The toolkit instantiates a real PageIndexLLMAdapter for the lightweight
    # model using ``adapter.client``; that adapter calls ``client.ask`` so the
    # client itself must expose an AsyncMock.
    a = MagicMock()
    a.model = "heavy"
    client_response = MagicMock()
    client_response.output = "cot analysis"
    client_response.structured_output = None
    a.client = MagicMock()
    a.client.ask = AsyncMock(return_value=client_response)
    a.client.default_model = "test-model"
    a.ask = AsyncMock(return_value="cot analysis")
    a.ask_structured = AsyncMock(return_value=IngestedMarkdown(
        title="Synthetic Doc",
        summary="A short summary.",
        markdown=(
            "# Synthetic Doc\n\n"
            "Top level introduction to the synthetic document with "
            "enough text to clear the thinning threshold of the parser.\n\n"
            "## Section A\n"
            "Section A covers the first half of the document with "
            "additional descriptive content that makes the node visible.\n\n"
            "## Section B\n"
            "Section B covers the second half of the document with "
            "the remaining descriptive content for the synthetic example.\n"
        ),
    ))
    return a


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    # tiktoken downloads encodings on first use; in offline environments
    # we bypass it with a whitespace-tokenised approximation. Functional
    # behaviour of the indexer is unaffected.
    def _approx(text: str, model: str = "gpt-4o") -> int:
        # Use char count so even short snippets clear thin_tree's 50-token gate.
        return max(1, len(text or ""))
    monkeypatch.setattr("parrot.pageindex.utils.count_tokens", _approx)
    monkeypatch.setattr("parrot.pageindex.md_builder.count_tokens", _approx)


@pytest.fixture
def toolkit(tmp_path: Path) -> PageIndexToolkit:
    return PageIndexToolkit(
        adapter=_adapter(),
        storage_dir=tmp_path,
        lightweight_model="light",
    )


def test_tool_discovery_exposes_expected_names(toolkit: PageIndexToolkit):
    names = set(toolkit.list_tool_names())
    expected = {
        "pageindex_list_trees",
        "pageindex_create_tree",
        "pageindex_get_tree",
        "pageindex_search",
        "pageindex_retrieve",
        "pageindex_insert_markdown",
        "pageindex_insert_content",
        "pageindex_import_file",
        "pageindex_import_folder",
        "pageindex_delete_node",
    }
    missing = expected - names
    assert not missing, f"missing tools: {missing}"


@pytest.mark.asyncio
async def test_create_tree_persists_to_disk(toolkit: PageIndexToolkit, tmp_path: Path):
    await toolkit.create_tree("docs", doc_name="My Docs")
    assert (tmp_path / "docs.json").is_file()
    listed = await toolkit.list_trees()
    assert "docs" in listed


@pytest.mark.asyncio
async def test_create_tree_rejects_duplicate(toolkit: PageIndexToolkit):
    await toolkit.create_tree("docs")
    with pytest.raises(ValueError):
        await toolkit.create_tree("docs")


@pytest.mark.asyncio
async def test_insert_markdown_then_search(monkeypatch, toolkit: PageIndexToolkit):
    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])
    monkeypatch.setattr(
        "parrot.pageindex.hybrid_search.PageIndexRetriever.search", fake_search,
    )
    await toolkit.create_tree("kb")
    md = (
        "# Tutorial\n\n"
        "Welcome to the tutorial section of the manual. This guide covers "
        "every part of the workflow you need to know before getting started.\n\n"
        "## Installation\n"
        "Run the official installer binary with administrator privileges. "
        "The installer extracts the runtime, the language packs and the "
        "default configuration profile into /opt/app.\n\n"
        "## Configuration\n"
        "Edit the config.yaml file to override custom settings such as the "
        "default port, the database connection string and the logging level. "
        "The configuration loader watches the file and reloads on change.\n"
    )
    result = await toolkit.insert_markdown("kb", md)
    assert result["new_node_ids"]

    hits = await toolkit.search(
        "kb", "installer admin", top_k=3, use_llm_walk=False, use_bm25=True,
    )
    assert hits, "BM25 should return at least one match"
    titles = [h["title"] for h in hits]
    assert any("Installation" in t for t in titles)


@pytest.mark.asyncio
async def test_insert_content_uses_two_step_ingest(toolkit: PageIndexToolkit):
    await toolkit.create_tree("kb")
    result = await toolkit.insert_content("kb", "raw blob of content", hint="docs")
    assert result["title"] == "Synthetic Doc"
    tree = await toolkit.get_tree("kb")
    titles = [n["title"] for n in tree["structure"]]
    assert "Synthetic Doc" in titles


@pytest.mark.asyncio
async def test_get_tree_unknown_raises(toolkit: PageIndexToolkit):
    with pytest.raises(KeyError):
        await toolkit.get_tree("missing")


@pytest.mark.asyncio
async def test_delete_node_returns_false_for_unknown_id(toolkit: PageIndexToolkit):
    await toolkit.create_tree("kb")
    result = await toolkit.delete_node("kb", "9999")
    assert result == {"tree_name": "kb", "removed": False}


@pytest.mark.asyncio
async def test_lightweight_adapter_built_when_model_given(tmp_path: Path):
    a = _adapter()
    tk = PageIndexToolkit(adapter=a, storage_dir=tmp_path, lightweight_model="light")
    assert tk._light_adapter is not None
    assert tk._light_adapter.model == "light"
    assert tk._light_adapter.client is a.client


@pytest.mark.asyncio
async def test_no_lightweight_adapter_when_omitted(tmp_path: Path):
    tk = PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path)
    assert tk._light_adapter is None


@pytest.mark.asyncio
async def test_import_pdf_splices_into_tree(monkeypatch, toolkit: PageIndexToolkit, tmp_path: Path):
    pdf = tmp_path / "fake_compliance.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")

    async def fake_build_page_index(doc, adapter, options=None, **kwargs):
        return {
            "doc_name": "fake_compliance.pdf",
            "doc_description": "stubbed compliance document",
            "structure": [
                {"title": "Article 1 — Subject matter",
                 "node_id": "0000",
                 "summary": "Scope of the regulation."},
                {"title": "Article 5 — Principles",
                 "node_id": "0001",
                 "summary": "Lawful, fair and transparent processing."},
            ],
            "_node_markdown": {
                "0000": "# Article 1\n\nFull markdown body of article 1.",
                "0001": "# Article 5\n\nLawful basis details and recitals.",
            },
        }

    monkeypatch.setattr(
        "parrot.pageindex.toolkit.build_page_index", fake_build_page_index,
    )

    await toolkit.create_tree("compliance")
    result = await toolkit.import_pdf("compliance", str(pdf))
    assert result["doc_name"] == "fake_compliance.pdf"
    assert result["doc_description"] == "stubbed compliance document"
    assert len(result["new_node_ids"]) == 2

    tree = await toolkit.get_tree("compliance")
    titles = [n["title"] for n in tree["structure"]]
    assert "Article 1 — Subject matter" in titles
    assert "Article 5 — Principles" in titles


@pytest.mark.asyncio
async def test_import_pdf_missing_file_raises(toolkit: PageIndexToolkit, tmp_path: Path):
    await toolkit.create_tree("compliance")
    with pytest.raises(FileNotFoundError):
        await toolkit.import_pdf("compliance", str(tmp_path / "missing.pdf"))


# ---------------------------------------------------------------------------
# FEAT-189: content-store + LLM-Wiki extensions
# ---------------------------------------------------------------------------

import json


def _fake_build_pdf(monkeypatch):
    async def _build(doc, adapter, options=None, **kwargs):
        return {
            "doc_name": "demo.pdf",
            "structure": [
                {"title": "Article 1",
                 "node_id": "0000",
                 "summary": "Scope."},
                {"title": "Article 5",
                 "node_id": "0001",
                 "summary": "Principles."},
                {"title": "Article 32",
                 "node_id": "0002",
                 "summary": "Security."},
            ],
            "_node_markdown": {
                "0000": "# Article 1\nVERBATIM_BODY_OF_ARTICLE_1.\n",
                "0001": "# Article 5\nVERBATIM_BODY_OF_ARTICLE_5.\n",
                "0002": "# Article 32\nVERBATIM_BODY_OF_ARTICLE_32.\n",
            },
        }
    monkeypatch.setattr("parrot.pageindex.toolkit.build_page_index", _build)


@pytest.mark.asyncio
async def test_toolkit_import_pdf_persists_sidecar(
    monkeypatch, toolkit: PageIndexToolkit, tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)
    await toolkit.create_tree("compliance")
    await toolkit.import_pdf("compliance", str(pdf))

    content_dir = tmp_path / "compliance"
    md_files = sorted(p.name for p in content_dir.iterdir() if p.suffix == ".md")
    assert md_files == ["0000.md", "0001.md", "0002.md"]

    # Persisted JSON tree must not carry inline text or _node_markdown.
    with (tmp_path / "compliance.json").open() as f:
        persisted = json.load(f)
    assert "_node_markdown" not in persisted
    for node in persisted["structure"]:
        assert "text" not in node


@pytest.mark.asyncio
async def test_toolkit_retrieve_returns_markdown_not_summary(
    monkeypatch, toolkit: PageIndexToolkit, tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)

    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=["0000"])
    monkeypatch.setattr(
        "parrot.pageindex.hybrid_search.PageIndexRetriever.search", fake_search,
    )

    await toolkit.create_tree("compliance")
    await toolkit.import_pdf("compliance", str(pdf))

    text = await toolkit.retrieve("compliance", "scope of regulation", top_k=1)
    assert "VERBATIM_BODY_OF_ARTICLE_1" in text


@pytest.mark.asyncio
async def test_toolkit_retrieve_falls_back_to_summary_when_no_content(
    monkeypatch, toolkit: PageIndexToolkit, tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)

    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=["0000"])
    monkeypatch.setattr(
        "parrot.pageindex.hybrid_search.PageIndexRetriever.search", fake_search,
    )

    await toolkit.create_tree("compliance")
    await toolkit.import_pdf("compliance", str(pdf))
    # Manually wipe the sidecar; retrieve must still return summary text.
    (tmp_path / "compliance" / "0000.md").unlink()
    toolkit._content_store._cache.clear()

    text = await toolkit.retrieve("compliance", "scope", top_k=1)
    assert "Scope" in text
    assert "VERBATIM_BODY_OF_ARTICLE_1" not in text


@pytest.mark.asyncio
async def test_toolkit_tag_node_set_merge(
    monkeypatch, toolkit: PageIndexToolkit, tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)
    await toolkit.create_tree("compliance")
    await toolkit.import_pdf("compliance", str(pdf))

    tree = await toolkit.get_tree("compliance")
    target_id = tree["structure"][0]["node_id"]

    await toolkit.tag_node("compliance", target_id, categories=["a", "b"])
    result = await toolkit.tag_node("compliance", target_id, categories=["b", "c"])
    assert result["categories"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_toolkit_tag_node_metadata_shallow_merge(
    monkeypatch, toolkit: PageIndexToolkit, tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)
    await toolkit.create_tree("compliance")
    await toolkit.import_pdf("compliance", str(pdf))

    tree = await toolkit.get_tree("compliance")
    target_id = tree["structure"][0]["node_id"]

    await toolkit.tag_node("compliance", target_id, metadata={"k1": "v1", "k2": "old"})
    result = await toolkit.tag_node("compliance", target_id, metadata={"k2": "new", "k3": "v3"})
    assert result["metadata"] == {"k1": "v1", "k2": "new", "k3": "v3"}


@pytest.mark.asyncio
async def test_toolkit_delete_node_removes_sidecar(
    monkeypatch, toolkit: PageIndexToolkit, tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)
    await toolkit.create_tree("compliance")
    await toolkit.import_pdf("compliance", str(pdf))

    tree = await toolkit.get_tree("compliance")
    target_id = tree["structure"][0]["node_id"]
    sidecar = tmp_path / "compliance" / f"{target_id}.md"
    assert sidecar.is_file()

    await toolkit.delete_node("compliance", target_id)
    assert not sidecar.is_file()
    # And the LRU cache entry is gone.
    assert ("compliance", target_id) not in toolkit._content_store._cache


@pytest.mark.asyncio
async def test_toolkit_search_filters_by_categories(
    monkeypatch, toolkit: PageIndexToolkit, tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)

    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])
    monkeypatch.setattr(
        "parrot.pageindex.hybrid_search.PageIndexRetriever.search", fake_search,
    )

    await toolkit.create_tree("compliance")
    await toolkit.import_pdf("compliance", str(pdf))
    tree = await toolkit.get_tree("compliance")
    by_title = {n["title"]: n["node_id"] for n in tree["structure"]}

    await toolkit.tag_node("compliance", by_title["Article 1"], categories=["X"])
    await toolkit.tag_node("compliance", by_title["Article 5"], categories=["X"])
    # Article 32 left untagged.

    results = await toolkit.search(
        "compliance",
        query="article",
        top_k=10,
        use_bm25=True,
        use_llm_walk=False,
        categories=["X"],
    )
    returned_ids = {r["node_id"] for r in results}
    assert by_title["Article 32"] not in returned_ids
    assert returned_ids.issubset({by_title["Article 1"], by_title["Article 5"]})


@pytest.mark.asyncio
async def test_toolkit_search_filters_by_metadata(
    monkeypatch, toolkit: PageIndexToolkit, tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)

    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])
    monkeypatch.setattr(
        "parrot.pageindex.hybrid_search.PageIndexRetriever.search", fake_search,
    )

    await toolkit.create_tree("compliance")
    await toolkit.import_pdf("compliance", str(pdf))
    tree = await toolkit.get_tree("compliance")
    by_title = {n["title"]: n["node_id"] for n in tree["structure"]}

    await toolkit.tag_node(
        "compliance", by_title["Article 5"], metadata={"tsc": "CC7.2"},
    )

    results = await toolkit.search(
        "compliance",
        query="article",
        top_k=10,
        use_bm25=True,
        use_llm_walk=False,
        metadata_filter={"tsc": "CC7.2"},
    )
    assert [r["node_id"] for r in results] == [by_title["Article 5"]]


@pytest.mark.asyncio
async def test_tag_node_unknown_id_raises(toolkit: PageIndexToolkit):
    await toolkit.create_tree("kb")
    with pytest.raises(KeyError):
        await toolkit.tag_node("kb", "9999", categories=["x"])


@pytest.mark.asyncio
async def test_delete_tree_clears_sidecar_and_json(
    monkeypatch, toolkit: PageIndexToolkit, tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)
    await toolkit.create_tree("compliance")
    await toolkit.import_pdf("compliance", str(pdf))

    assert (tmp_path / "compliance.json").is_file()
    assert (tmp_path / "compliance").is_dir()

    result = await toolkit.delete_tree("compliance")
    assert result["tree_removed"] is True
    assert result["sidecars_removed"] >= 1
    assert not (tmp_path / "compliance.json").is_file()
    assert not (tmp_path / "compliance").is_dir()


@pytest.mark.asyncio
async def test_create_tree_wipes_orphan_content_dir(
    toolkit: PageIndexToolkit, tmp_path: Path,
):
    # Simulate a stale content directory from a prior tree of the same name.
    orphan_dir = tmp_path / "compliance"
    orphan_dir.mkdir()
    (orphan_dir / "0000.md").write_text("stale")

    await toolkit.create_tree("compliance")
    # The stale sidecar must be gone — otherwise retrieve() would serve it.
    assert not (orphan_dir / "0000.md").exists()
