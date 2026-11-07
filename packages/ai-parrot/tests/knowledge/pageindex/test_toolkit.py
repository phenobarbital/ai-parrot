"""Tests for parrot.knowledge.pageindex.toolkit.PageIndexToolkit (in-toolkit surface)."""

from __future__ import annotations

from pathlib import Path
import threading
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.pageindex.ingest import IngestedMarkdown
from parrot.knowledge.pageindex.locks import lock_path
from parrot.knowledge.pageindex.schemas import TreeSearchResult
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, _REPLACED_MARKER
from parrot.knowledge.pageindex.utils import structure_to_list
from parrot.knowledge.okf.utils import flatten_concept_id_for_filename

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
    a.ask_structured = AsyncMock(
        return_value=IngestedMarkdown(
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
        )
    )
    return a


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    # tiktoken downloads encodings on first use; in offline environments
    # we bypass it with a whitespace-tokenised approximation. Functional
    # behaviour of the indexer is unaffected.
    def _approx(text: str, model: str = "gpt-4o") -> int:
        # Use char count so even short snippets clear thin_tree's 50-token gate.
        return max(1, len(text or ""))

    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", _approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", _approx)


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
        "pageindex_delete_tree",
        "pageindex_get_generation",
        "pageindex_get_tree",
        "pageindex_search",
        "pageindex_search_documents_scoped",
        "pageindex_retrieve",
        "pageindex_tag_node",
        "pageindex_add_node",
        "pageindex_update_node",
        "pageindex_update_node_content",
        "pageindex_vacuum_tree",
        "pageindex_insert_markdown",
        "pageindex_insert_content",
        "pageindex_import_file",
        "pageindex_import_folder",
        "pageindex_import_pdf",
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
async def test_create_tree_publishes_generation_one(toolkit: PageIndexToolkit):
    await toolkit.create_tree("g")

    assert (await toolkit.get_generation("g"))["id"] == 1


@pytest.mark.asyncio
async def test_write_nested_joins(toolkit: PageIndexToolkit):
    await toolkit.create_tree("g")

    async with toolkit._write("g"):
        async with toolkit._write("g"):
            pass

    assert (await toolkit.get_generation("g"))["id"] == 2


@pytest.mark.asyncio
async def test_mutate_retries_stale_generation(toolkit: PageIndexToolkit):
    await toolkit.create_tree("g")
    calls = 0

    async def apply(txn):
        nonlocal calls
        calls += 1
        if calls == 1:
            externally_written = toolkit._store.load("g")
            externally_written["doc_name"] = "external writer"
            externally_written["generation"]["id"] += 1
            toolkit._store.save("g", externally_written)
        txn.tree["doc_name"] = "mutated"
        return calls

    assert await toolkit._mutate("g", apply) == 2
    assert (await toolkit.get_tree("g"))["doc_name"] == "mutated"


@pytest.mark.asyncio
async def test_reader_keeps_generation(toolkit: PageIndexToolkit):
    await toolkit.create_tree("g")

    async def add_first(txn):
        node = {"node_id": "0000", "title": "Entry", "nodes": []}
        txn.tree["structure"].append(node)
        txn.set_body(node, "first body")

    await toolkit._mutate("g", add_first)
    old_tree = await toolkit.get_tree("g")
    old_loader = toolkit._content_store.loader_for("g", old_tree)

    async def replace_body(txn):
        txn.set_body(txn.tree["structure"][0], "second body")

    await toolkit._mutate("g", replace_body)

    assert old_tree["structure"][0]["body_ref"] != (await toolkit.get_tree("g"))["structure"][0]["body_ref"]
    assert old_loader("0000") == "first body"


@pytest.mark.asyncio
async def test_first_write_migrates_legacy_bodies(toolkit: PageIndexToolkit):
    legacy_tree = {
        "doc_name": "legacy",
        "structure": [
            {
                "node_id": "0001",
                "concept_id": "legacy/entry",
                "title": "Legacy entry",
                "nodes": [],
            }
        ],
    }
    toolkit._store.save("legacy", legacy_tree)
    toolkit._content_store.save(
        "legacy",
        flatten_concept_id_for_filename("legacy/entry"),
        "---\nconcept_id: legacy/entry\n---\nlegacy body",
    )

    async def noop(txn):
        return None

    await toolkit._mutate("legacy", noop)
    node = (await toolkit.get_tree("legacy"))["structure"][0]

    assert node["body_ref"]
    assert toolkit._content_store.load_node("legacy", node) == "legacy body"


@pytest.mark.asyncio
async def test_search_engine_is_pinned_per_generation(toolkit: PageIndexToolkit):
    await toolkit.create_tree("g")
    old_engine = toolkit._search_for("g")
    old_tree = old_engine._tree

    async def noop(txn):
        return None

    await toolkit._mutate("g", noop)
    new_engine = toolkit._search_for("g")

    assert new_engine is not old_engine
    assert old_engine._tree is old_tree


@pytest.mark.asyncio
async def test_delete_tree_removes_bodies_and_lock(toolkit: PageIndexToolkit, tmp_path: Path):
    await toolkit.create_tree("g")
    toolkit._content_store.save("g", "0000", "body")
    embeddings = tmp_path / "g" / "embeddings"
    embeddings.mkdir()
    (embeddings / "g.g1.matrix.npy").write_bytes(b"matrix")
    lock = lock_path(tmp_path, "g")
    lock.parent.mkdir(exist_ok=True)
    lock.touch()

    await toolkit.delete_tree("g")

    assert not (tmp_path / "g.json").exists()
    assert not (tmp_path / "g" / "bodies").exists()
    assert not embeddings.exists()
    assert not lock.exists()


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
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_search,
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
        "kb",
        "installer admin",
        top_k=3,
        use_llm_walk=False,
        use_bm25=True,
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
                {"title": "Article 1 — Subject matter", "node_id": "0000", "summary": "Scope of the regulation."},
                {
                    "title": "Article 5 — Principles",
                    "node_id": "0001",
                    "summary": "Lawful, fair and transparent processing.",
                },
            ],
            "_node_markdown": {
                "0000": "# Article 1\n\nFull markdown body of article 1.",
                "0001": "# Article 5\n\nLawful basis details and recitals.",
            },
        }

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.build_page_index",
        fake_build_page_index,
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
                {"title": "Article 1", "node_id": "0000", "summary": "Scope."},
                {"title": "Article 5", "node_id": "0001", "summary": "Principles."},
                {"title": "Article 32", "node_id": "0002", "summary": "Security."},
            ],
            "_node_markdown": {
                "0000": "# Article 1\nVERBATIM_BODY_OF_ARTICLE_1.\n",
                "0001": "# Article 5\nVERBATIM_BODY_OF_ARTICLE_5.\n",
                "0002": "# Article 32\nVERBATIM_BODY_OF_ARTICLE_32.\n",
            },
        }

    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", _build)


@pytest.mark.asyncio
async def test_toolkit_import_pdf_stores_blobs(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)
    await toolkit.create_tree("compliance")
    await toolkit.import_pdf("compliance", str(pdf))

    tree = await toolkit.get_tree("compliance")
    assert all(node.get("body_ref") for node in tree["structure"])
    assert toolkit._content_store.load("compliance", "0000") == "# Article 1\nVERBATIM_BODY_OF_ARTICLE_1.\n"
    assert not list((tmp_path / "compliance").glob("*.md"))

    # Persisted JSON tree must not carry inline text or _node_markdown.
    with (tmp_path / "compliance.json").open() as f:
        persisted = json.load(f)
    assert "_node_markdown" not in persisted
    for node in persisted["structure"]:
        assert "text" not in node


@pytest.mark.asyncio
async def test_toolkit_retrieve_returns_markdown_not_summary(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)

    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=["0000"])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_search,
    )

    await toolkit.create_tree("compliance")
    await toolkit.import_pdf("compliance", str(pdf))

    text = await toolkit.retrieve("compliance", "scope of regulation", top_k=1)
    assert "VERBATIM_BODY_OF_ARTICLE_1" in text


@pytest.mark.asyncio
async def test_toolkit_retrieve_falls_back_to_summary_when_no_content(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)

    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=["0000"])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_search,
    )

    await toolkit.create_tree("compliance")
    await toolkit.import_pdf("compliance", str(pdf))
    node = (await toolkit.get_tree("compliance"))["structure"][0]
    toolkit._content_store.body_path("compliance", node["body_ref"]).unlink()
    toolkit._content_store._cache.clear()

    text = await toolkit.retrieve("compliance", "scope", top_k=1)
    assert "Scope" in text
    assert "VERBATIM_BODY_OF_ARTICLE_1" not in text


@pytest.mark.asyncio
async def test_toolkit_tag_node_set_merge(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
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
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
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
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)
    await toolkit.create_tree("compliance")
    await toolkit.import_pdf("compliance", str(pdf))

    tree = await toolkit.get_tree("compliance")
    target_node = tree["structure"][0]
    target_id = target_node["node_id"]
    assert target_node["body_ref"]
    assert toolkit._content_store.load("compliance", target_id) == "# Article 1\nVERBATIM_BODY_OF_ARTICLE_1.\n"

    await toolkit.delete_node("compliance", target_id)
    assert all(node["title"] != "Article 1" for node in (await toolkit.get_tree("compliance"))["structure"])
    # And the LRU cache entry is gone.
    assert ("compliance", target_id) not in toolkit._content_store._cache


@pytest.mark.asyncio
async def test_toolkit_search_filters_by_categories(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)

    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_search,
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
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    _fake_build_pdf(monkeypatch)

    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_search,
    )

    await toolkit.create_tree("compliance")
    await toolkit.import_pdf("compliance", str(pdf))
    tree = await toolkit.get_tree("compliance")
    by_title = {n["title"]: n["node_id"] for n in tree["structure"]}

    await toolkit.tag_node(
        "compliance",
        by_title["Article 5"],
        metadata={"tsc": "CC7.2"},
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
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
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
    assert result["sidecars_removed"] == 0
    assert not (tmp_path / "compliance.json").is_file()
    assert not (tmp_path / "compliance").is_dir()


@pytest.mark.asyncio
async def test_insert_markdown_stores_blobs_and_strips_text(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    async def fake_retriever_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_retriever_search,
    )
    await toolkit.create_tree("kb")
    md = (
        "# Tutorial\n\n"
        "Welcome to the tutorial section of the manual. This guide covers "
        "every part of the workflow you need to know before getting started.\n\n"
        "## Installation\n"
        "Run the official installer binary with administrator privileges. "
        "The installer extracts the runtime, the language packs and the "
        "default configuration profile into /opt/app. UNIQUE_INSTALL_MARKER.\n\n"
        "## Configuration\n"
        "Edit the config.yaml file to override custom settings such as the "
        "default port, the database connection string and the logging level. "
        "The configuration loader watches the file and reloads on change.\n"
    )
    await toolkit.insert_markdown("kb", md)

    # Persisted JSON contains no inline text on any node.
    with (tmp_path / "kb.json").open() as f:
        persisted = json.load(f)

    def _walk(node):
        if isinstance(node, dict):
            assert "text" not in node, f"node {node.get('title')!r} still has inline text"
            for child in node.get("nodes") or []:
                _walk(child)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(persisted["structure"])

    nodes = [node for node in structure_to_list(persisted["structure"]) if node.get("body_ref")]
    assert nodes, "expected nodes with body blobs"
    assert any("UNIQUE_INSTALL_MARKER" in (toolkit._content_store.load_node("kb", node) or "") for node in nodes)
    assert not list((tmp_path / "kb").glob("*.md"))


@pytest.mark.asyncio
async def test_insert_markdown_retrieve_returns_body(
    monkeypatch,
    toolkit: PageIndexToolkit,
):
    async def fake_retriever_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_retriever_search,
    )
    await toolkit.create_tree("kb")
    md = (
        "# Tutorial\n\n"
        "Welcome to the tutorial section of the manual. This guide covers "
        "every part of the workflow you need to know before getting started.\n\n"
        "## Installation\n"
        "Run the official installer binary with administrator privileges. "
        "The installer extracts the runtime, the language packs and the "
        "default configuration profile into /opt/app. UNIQUE_INSTALL_MARKER.\n"
    )
    await toolkit.insert_markdown("kb", md)

    text = await toolkit.retrieve("kb", "installer admin", top_k=3)
    assert "UNIQUE_INSTALL_MARKER" in text


@pytest.mark.asyncio
async def test_import_folder_persists_sidecars(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    async def fake_retriever_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_retriever_search,
    )
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "alpha.md").write_text(
        "# Alpha\n\n"
        "Alpha section body of substantial length with descriptive content "
        "to clear the thinning threshold. UNIQUE_ALPHA_TOKEN appears here.\n"
        "## Subalpha\n"
        "Sub-section under alpha with more descriptive content to ensure "
        "the leaf node survives the markdown-builder thin pass.\n",
        encoding="utf-8",
    )
    (src / "sub" / "beta.md").write_text(
        "# Beta\n\n"
        "Beta section body of substantial length with descriptive content "
        "to clear the thinning threshold. UNIQUE_BETA_TOKEN appears here.\n"
        "## Subbeta\n"
        "Sub-section under beta with more descriptive content to ensure "
        "the leaf node survives the markdown-builder thin pass.\n",
        encoding="utf-8",
    )
    # Insertable content avoids needing real LLM calls via the stub adapter.
    await toolkit.create_tree("docs")
    await toolkit.import_folder("docs", str(src), glob_pattern="*.md")

    # The persisted tree carries no inline text on any node.
    with (tmp_path / "docs.json").open() as f:
        persisted = json.load(f)

    def _walk(node):
        if isinstance(node, dict):
            assert "text" not in node
            for child in node.get("nodes") or []:
                _walk(child)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(persisted["structure"])

    nodes = [node for node in structure_to_list(persisted["structure"]) if node.get("body_ref")]
    assert nodes, "expected nodes with body blobs after folder import"
    assert all(toolkit._content_store.load_node("docs", node) for node in nodes)
    assert not list((tmp_path / "docs").glob("*.md"))


@pytest.mark.asyncio
async def test_add_node_creates_root_leaf_atomically(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    async def fake_retriever_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_retriever_search,
    )
    await toolkit.create_tree("kb")
    result = await toolkit.add_node(
        "kb",
        title="Finding 17",
        body="UNIQUE_FINDING_BODY — the IAM role allows iam:PassRole on *.",
        summary="Excess IAM PassRole permissions.",
        categories=["security", "iam"],
        metadata={"severity": "high"},
    )
    assert result["node_id"]
    assert result["parent_node_id"] is None
    tree = await toolkit.get_tree("kb")
    titles = [n["title"] for n in tree["structure"]]
    assert "Finding 17" in titles

    # Persisted JSON does NOT contain inline text.
    with (tmp_path / "kb.json").open() as f:
        persisted = json.load(f)
    for node in persisted["structure"]:
        assert "text" not in node
    # The immutable body blob is addressed by the inserted node's body_ref.
    node = next(n for n in persisted["structure"] if n["title"] == "Finding 17")
    assert node["body_ref"]
    body_path = tmp_path / "kb" / "bodies" / f"{node['body_ref']}.md"
    assert body_path.is_file()
    assert "UNIQUE_FINDING_BODY" in body_path.read_text()
    # Categories and metadata round-trip on the node.
    assert node["categories"] == ["iam", "security"]
    assert node["metadata"] == {"severity": "high"}


@pytest.mark.asyncio
async def test_add_node_under_existing_parent(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    async def fake_retriever_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_retriever_search,
    )
    await toolkit.create_tree("kb")
    parent = await toolkit.add_node("kb", title="Findings", body="")
    parent_id = parent["node_id"]
    child = await toolkit.add_node(
        "kb",
        title="Finding A",
        body="UNIQUE_CHILD_BODY",
        parent_node_id=parent_id,
    )

    tree = await toolkit.get_tree("kb")
    # Parent kept its slot at root.
    root_titles = [n["title"] for n in tree["structure"]]
    assert root_titles == ["Findings"]
    # Child sits under it.
    parent_node = tree["structure"][0]
    child_titles = [n["title"] for n in (parent_node.get("nodes") or [])]
    assert child_titles == ["Finding A"]
    # Child has a node_id (possibly renumbered).
    child_id_in_tree = parent_node["nodes"][0]["node_id"]
    child_node = parent_node["nodes"][0]
    assert toolkit._content_store.load_node("kb", child_node) == "UNIQUE_CHILD_BODY"
    # Returned id matches what's in the tree.
    assert child["node_id"] == child_id_in_tree


@pytest.mark.asyncio
async def test_add_node_then_retrieve_returns_body(
    monkeypatch,
    toolkit: PageIndexToolkit,
):
    async def fake_retriever_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_retriever_search,
    )
    await toolkit.create_tree("kb")
    await toolkit.add_node(
        "kb",
        title="Finding 42",
        body="UNIQUE_RETRIEVABLE_TOKEN appears in this body.",
        summary="The body is retrievable.",
    )
    text = await toolkit.retrieve("kb", "Finding 42", top_k=3)
    assert "UNIQUE_RETRIEVABLE_TOKEN" in text


@pytest.mark.asyncio
async def test_add_node_rejects_empty_title(toolkit: PageIndexToolkit):
    await toolkit.create_tree("kb")
    with pytest.raises(ValueError):
        await toolkit.add_node("kb", title="   ", body="x")


@pytest.mark.asyncio
async def test_update_node_content_publishes(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    async def fake_retriever_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_retriever_search,
    )
    await toolkit.create_tree("kb")
    res = await toolkit.add_node("kb", title="Finding", body="OLD_BODY")
    node_id = res["node_id"]

    before_generation = (await toolkit.get_tree("kb"))["generation"]["id"]
    await toolkit.update_node_content("kb", node_id, "NEW_BODY content here")

    tree = await toolkit.get_tree("kb")
    assert tree["generation"]["id"] == before_generation + 1
    assert tree["structure"][0]["title"] == "Finding"
    assert toolkit._content_store.load_node("kb", tree["structure"][0]) == "NEW_BODY content here"


@pytest.mark.asyncio
async def test_update_node_content_marks_bm25_dirty(
    monkeypatch,
    toolkit: PageIndexToolkit,
):
    async def fake_retriever_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_retriever_search,
    )
    await toolkit.create_tree("kb")
    # Add two nodes so BM25 has something to score against.
    res = await toolkit.add_node("kb", title="Finding A", body="alpha body")
    await toolkit.add_node("kb", title="Finding B", body="beta body")
    # Force BM25 build.
    await toolkit.search("kb", "alpha", top_k=3, use_llm_walk=False)
    await toolkit.update_node_content("kb", res["node_id"], "alpha_v2 token")
    assert "kb" not in toolkit._search
    # New token is now findable; old one is not.
    hits = await toolkit.search(
        "kb",
        "alpha_v2",
        top_k=3,
        use_llm_walk=False,
        use_bm25=True,
    )
    assert any(h["node_id"] == res["node_id"] for h in hits)


@pytest.mark.asyncio
async def test_update_node_content_unknown_id_raises(toolkit: PageIndexToolkit):
    await toolkit.create_tree("kb")
    with pytest.raises(KeyError):
        await toolkit.update_node_content("kb", "9999", "body")


@pytest.mark.asyncio
async def test_update_node_renames_and_resummarizes(
    monkeypatch,
    toolkit: PageIndexToolkit,
):
    async def fake_retriever_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_retriever_search,
    )
    await toolkit.create_tree("kb")
    res = await toolkit.add_node(
        "kb",
        title="Old Title",
        body="b",
        summary="Old summary",
    )
    node_id = res["node_id"]

    result = await toolkit.update_node(
        "kb",
        node_id,
        title="New Title",
        summary="New summary",
    )
    assert result["title"] == "New Title"
    assert result["summary"] == "New summary"

    tree = await toolkit.get_tree("kb")
    node = tree["structure"][0]
    assert node["title"] == "New Title"
    assert node["summary"] == "New summary"


@pytest.mark.asyncio
async def test_update_node_partial_update(
    monkeypatch,
    toolkit: PageIndexToolkit,
):
    async def fake_retriever_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.hybrid_search.PageIndexRetriever.search",
        fake_retriever_search,
    )
    await toolkit.create_tree("kb")
    res = await toolkit.add_node(
        "kb",
        title="Keep Title",
        body="b",
        summary="Old summary",
    )
    node_id = res["node_id"]
    await toolkit.update_node("kb", node_id, summary="Replaced")
    tree = await toolkit.get_tree("kb")
    node = tree["structure"][0]
    assert node["title"] == "Keep Title"
    assert node["summary"] == "Replaced"


@pytest.mark.asyncio
async def test_update_node_requires_at_least_one_field(toolkit: PageIndexToolkit):
    await toolkit.create_tree("kb")
    res = await toolkit.add_node("kb", title="x", body="y")
    with pytest.raises(ValueError):
        await toolkit.update_node("kb", res["node_id"])


@pytest.mark.asyncio
async def test_update_node_unknown_id_raises(toolkit: PageIndexToolkit):
    await toolkit.create_tree("kb")
    with pytest.raises(KeyError):
        await toolkit.update_node("kb", "9999", title="x")


@pytest.mark.asyncio
async def test_create_tree_wipes_orphan_content_dir(
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    # Simulate a stale content directory from a prior tree of the same name.
    orphan_dir = tmp_path / "compliance"
    orphan_dir.mkdir()
    (orphan_dir / "0000.md").write_text("stale")

    await toolkit.create_tree("compliance")
    # The stale sidecar must be gone — otherwise retrieve() would serve it.
    assert not (orphan_dir / "0000.md").exists()


# ---------------------------------------------------------------------------
# search_documents_scoped — multi-tree fan-out (ported from the old toolkit)
# ---------------------------------------------------------------------------


async def _seed_scoped_tree(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
    tree_name: str,
    doc_name: str,
    body_token: str,
) -> None:
    pdf = tmp_path / f"{tree_name}.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")

    async def _build(doc, adapter, options=None, **kwargs):
        return {
            "doc_name": doc_name,
            "structure": [
                {"title": "Section A", "node_id": "0000", "summary": f"Summary A for {tree_name}"},
                {"title": "Section B", "node_id": "0001", "summary": f"Summary B for {tree_name}"},
            ],
            "_node_markdown": {
                "0000": f"# Section A\n{body_token}_A\n",
                "0001": f"# Section B\n{body_token}_B\n",
            },
        }

    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", _build)
    await toolkit.create_tree(tree_name, doc_name=doc_name)
    await toolkit.import_pdf(tree_name, str(pdf))


@pytest.mark.asyncio
async def test_search_documents_scoped_empty_returns_empty(
    toolkit: PageIndexToolkit,
):
    result = await toolkit.search_documents_scoped(tree_names=[], query="q")
    assert result == {"status": "empty", "scoped_results": []}


@pytest.mark.asyncio
async def test_search_documents_scoped_single_tree(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    await _seed_scoped_tree(monkeypatch, toolkit, tmp_path, "kb1", "policy.md", "TOKEN1")

    async def fake_search(self, query):
        return TreeSearchResult(thinking="found it", node_list=["0000"])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.PageIndexRetriever.search",
        fake_search,
    )
    result = await toolkit.search_documents_scoped(
        tree_names=["kb1"],
        query="anything",
    )
    assert result["status"] == "ok"
    assert len(result["scoped_results"]) == 1
    entry = result["scoped_results"][0]
    assert entry["tree_name"] == "kb1"
    assert entry["doc_name"] == "policy.md"
    assert entry["node_list"] == ["0000"]
    assert entry["thinking"] == "found it"
    assert "TOKEN1_A" in entry["context"]
    assert "tree_context" not in entry


@pytest.mark.asyncio
async def test_search_documents_scoped_multiple_trees_fan_out(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    await _seed_scoped_tree(monkeypatch, toolkit, tmp_path, "kb1", "a.md", "ALPHA")
    await _seed_scoped_tree(monkeypatch, toolkit, tmp_path, "kb2", "b.md", "BETA")
    await _seed_scoped_tree(monkeypatch, toolkit, tmp_path, "kb3", "c.md", "GAMMA")

    async def fake_search(self, query):
        return TreeSearchResult(thinking="t", node_list=["0001"])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.PageIndexRetriever.search",
        fake_search,
    )
    result = await toolkit.search_documents_scoped(
        tree_names=["kb1", "kb3"],
        query="q",
    )
    assert result["status"] == "ok"
    tree_names = [e["tree_name"] for e in result["scoped_results"]]
    assert tree_names == ["kb1", "kb3"]  # kb2 explicitly excluded


@pytest.mark.asyncio
async def test_search_documents_scoped_missing_tree_skipped(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
    caplog,
):
    await _seed_scoped_tree(monkeypatch, toolkit, tmp_path, "real", "real.md", "X")

    async def fake_search(self, query):
        return TreeSearchResult(thinking="t", node_list=["0000"])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.PageIndexRetriever.search",
        fake_search,
    )

    import logging

    with caplog.at_level(logging.WARNING, logger="parrot.knowledge.pageindex"):
        result = await toolkit.search_documents_scoped(
            tree_names=["real", "ghost"],
            query="q",
        )
    assert result["status"] == "ok"
    assert [e["tree_name"] for e in result["scoped_results"]] == ["real"]
    assert any("ghost" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_search_documents_scoped_all_missing_returns_empty(
    toolkit: PageIndexToolkit,
):
    result = await toolkit.search_documents_scoped(
        tree_names=["ghost-1", "ghost-2"],
        query="q",
    )
    assert result == {"status": "empty", "scoped_results": []}


@pytest.mark.asyncio
async def test_search_documents_scoped_include_tree_context(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    await _seed_scoped_tree(monkeypatch, toolkit, tmp_path, "kb", "doc.md", "X")

    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=["0000"])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.PageIndexRetriever.search",
        fake_search,
    )
    result = await toolkit.search_documents_scoped(
        tree_names=["kb"],
        query="q",
        include_tree_context=True,
    )
    entry = result["scoped_results"][0]
    assert "tree_context" in entry
    assert "Section A" in entry["tree_context"]


@pytest.mark.asyncio
async def test_search_documents_scoped_respects_max_trees(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    for i in range(5):
        await _seed_scoped_tree(
            monkeypatch,
            toolkit,
            tmp_path,
            f"kb{i}",
            f"d{i}.md",
            f"T{i}",
        )

    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=[])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.PageIndexRetriever.search",
        fake_search,
    )
    result = await toolkit.search_documents_scoped(
        tree_names=[f"kb{i}" for i in range(5)],
        query="q",
        max_trees=2,
    )
    assert len(result["scoped_results"]) == 2
    assert [e["tree_name"] for e in result["scoped_results"]] == ["kb0", "kb1"]


@pytest.mark.asyncio
async def test_search_documents_scoped_falls_back_to_summary_when_no_sidecar(
    monkeypatch,
    toolkit: PageIndexToolkit,
    tmp_path: Path,
):
    await _seed_scoped_tree(monkeypatch, toolkit, tmp_path, "kb", "d.md", "BODY")
    node = (await toolkit.get_tree("kb"))["structure"][0]
    toolkit._content_store.body_path("kb", node["body_ref"]).unlink()
    toolkit._content_store._cache.clear()

    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=["0000"])

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.PageIndexRetriever.search",
        fake_search,
    )
    result = await toolkit.search_documents_scoped(tree_names=["kb"], query="q")
    entry = result["scoped_results"][0]
    assert "BODY_A" not in entry["context"]
    assert "Summary A for kb" in entry["context"]


# ---- OKF integration tests (FEAT-238 / TASK-1559) -------------------------


@pytest.mark.asyncio
async def test_insert_markdown_t3_classifies_in_okf_tree(monkeypatch, toolkit: PageIndexToolkit, tmp_path: Path):
    """In an OKF-migrated tree, insert_markdown runs T3 for new untyped nodes.

    T3 only activates when the tree already has at least one typed node
    (backward compatibility gate).  We pre-seed one typed node to enable T3.
    """
    from parrot.knowledge.pageindex.okf.ontology import ConceptType
    from parrot.knowledge.pageindex.utils import structure_to_list

    await toolkit.create_tree("okf_test")
    # Pre-seed a typed node to enable T3 gate.
    tree = toolkit._trees["okf_test"]
    tree["structure"] = [
        {
            "node_id": "0000",
            "concept_id": "seed/section",
            "type": "Section",
            "title": "Seed",
            "summary": "Pre-existing typed node",
            "nodes": [],
        }
    ]

    md = "# OKF Node\n\n" "This is a short description of the OKF node being inserted for testing purposes.\n"
    await toolkit.insert_markdown("okf_test", md)
    tree = await toolkit.get_tree("okf_test")
    nodes = structure_to_list(tree.get("structure", []))
    # New nodes inserted after the seed must also have a type.
    new_nodes = [n for n in nodes if n.get("title") != "Seed"]
    assert new_nodes, "Expected new nodes after insert_markdown"
    for node in new_nodes:
        assert node.get("type") is not None, f"Node {node.get('node_id')!r} missing type after T3 step"
    # With a mock adapter, the fallback is Section.
    assert all(n.get("type") == ConceptType.SECTION.value for n in new_nodes)


def test_set_okf_toolkit_registers_tools(toolkit: PageIndexToolkit, tmp_path: Path):
    """set_okf_toolkit registers OKF tools in get_tools() output."""
    from parrot.knowledge.pageindex.content_store import NodeContentStore
    from parrot.knowledge.pageindex.okf.graph import KnowledgeGraph
    from parrot.knowledge.pageindex.okf.tools import OKFToolkit

    enriched_tree = {
        "doc_name": "guide.pdf",
        "structure": [
            {
                "node_id": "0000",
                "concept_id": "controls/c1",
                "type": "Control",
                "title": "Control 1",
                "summary": "A test control",
                "relates_to": [],
                "nodes": [],
            }
        ],
    }
    graph = KnowledgeGraph(enriched_tree)
    store = NodeContentStore(tmp_path)
    okf_tk = OKFToolkit(enriched_tree, graph, store, "guide")
    toolkit.set_okf_toolkit("guide", okf_tk)

    all_tools = toolkit.get_tools()
    # Should have the standard toolkit tools + 6 OKF tools.
    assert len(all_tools) > len(toolkit.__class__.mro())  # at least some tools
    # OKF toolkit returns 9 tools (6 read tools + FEAT-216 lint/export/import).
    assert len(okf_tk.get_tools()) == 9


# ---- tree rename (FEAT-615 / TASK-3887) -----------------------------------


async def _seed_rename_tree(toolkit: PageIndexToolkit, name: str, body: str) -> str:
    """Create a tree with one sidecar and return its node id."""
    await toolkit.create_tree(name)
    result = await toolkit.add_node(name, title=name, body=body)
    return result["node_id"]


@pytest.mark.asyncio
async def test_rename_tree_basic(toolkit: PageIndexToolkit, tmp_path: Path) -> None:
    """Publish source content into a new destination generation."""
    await _seed_rename_tree(toolkit, "source", "SOURCE_BODY")

    result = await toolkit.rename_tree("source", "destination")

    assert result == {"src": "source", "dst": "destination", "replaced": False, "generation": 1}
    assert not (tmp_path / "source.json").exists()
    assert not (tmp_path / "source").exists()
    assert (tmp_path / "destination.json").is_file()
    tree = await toolkit.get_tree("destination")
    assert toolkit._content_store.load_node("destination", tree["structure"][0]) == "SOURCE_BODY"
    assert tree["structure"][0]["title"] == "source"


@pytest.mark.asyncio
async def test_rename_tree_refuses_existing_dst_without_overwrite(toolkit: PageIndexToolkit, tmp_path: Path) -> None:
    """Reject collisions without mutating either tree."""
    await _seed_rename_tree(toolkit, "source", "SOURCE_BODY")
    await _seed_rename_tree(toolkit, "destination", "DESTINATION_BODY")

    with pytest.raises(ValueError, match="already exists"):
        await toolkit.rename_tree("source", "destination")

    source_tree = await toolkit.get_tree("source")
    destination_tree = await toolkit.get_tree("destination")
    assert toolkit._content_store.load_node("source", source_tree["structure"][0]) == "SOURCE_BODY"
    assert toolkit._content_store.load_node("destination", destination_tree["structure"][0]) == "DESTINATION_BODY"


@pytest.mark.asyncio
async def test_rename_tree_no_backup_tree(toolkit: PageIndexToolkit) -> None:
    """Overwrite publication never creates a replacement backup tree."""
    await _seed_rename_tree(toolkit, "source", "SOURCE_BODY")
    await _seed_rename_tree(toolkit, "destination", "DESTINATION_BODY")

    result = await toolkit.rename_tree("source", "destination", overwrite=True)

    assert result == {"src": "source", "dst": "destination", "replaced": True, "generation": 3}
    tree = await toolkit.get_tree("destination")
    assert toolkit._content_store.load_node("destination", tree["structure"][0]) == "SOURCE_BODY"
    assert not any(_REPLACED_MARKER in name for name in await toolkit.list_trees())


@pytest.mark.asyncio
async def test_rename_tree_no_window(toolkit: PageIndexToolkit) -> None:
    """An overwrite keeps the destination JSON visible throughout publication."""
    await _seed_rename_tree(toolkit, "source", "SOURCE_BODY")
    await _seed_rename_tree(toolkit, "destination", "DESTINATION_BODY")
    observations: list[bool] = []
    started = threading.Event()
    stopped = threading.Event()

    def poll() -> None:
        observations.append(toolkit._store.exists("destination"))
        started.set()
        while not stopped.is_set():
            observations.append(toolkit._store.exists("destination"))
            time.sleep(0.001)

    thread = threading.Thread(target=poll)
    thread.start()
    assert started.wait(timeout=1)
    try:
        await toolkit.rename_tree("source", "destination", overwrite=True)
    finally:
        stopped.set()
        thread.join(timeout=1)

    assert observations
    assert all(observations)


@pytest.mark.asyncio
async def test_rename_tree_projection_failure_keeps_both(monkeypatch, toolkit: PageIndexToolkit) -> None:
    """A strict destination projection failure leaves both JSON trees unchanged."""
    await _seed_rename_tree(toolkit, "source", "SOURCE_BODY")
    await _seed_rename_tree(toolkit, "destination", "DESTINATION_BODY")

    async def enrich(txn) -> None:
        txn.tree["structure"][0]["type"] = "Section"

    await toolkit._mutate("source", enrich)
    source_before = toolkit._store.load("source")
    destination_before = toolkit._store.load("destination")

    def fail_projection(tree_name: str, tree: dict) -> bool:
        raise RuntimeError("injected projection failure")

    monkeypatch.setattr(toolkit, "_project_okf_sidecars", fail_projection)
    with pytest.raises(RuntimeError, match="injected projection failure"):
        await toolkit.rename_tree("source", "destination", overwrite=True)

    assert toolkit._store.load("source") == source_before
    assert toolkit._store.load("destination") == destination_before
    destination_tree = await toolkit.get_tree("destination")
    assert toolkit._content_store.load_node("destination", destination_tree["structure"][0]) == "DESTINATION_BODY"


@pytest.mark.asyncio
async def test_rename_tree_invalidates_search_engine_cache(toolkit: PageIndexToolkit) -> None:
    """Drop stale tree and search caches after a successful rename."""
    await _seed_rename_tree(toolkit, "source", "SOURCE_BODY")
    await _seed_rename_tree(toolkit, "destination", "DESTINATION_BODY")
    toolkit._search_for("source")
    toolkit._search_for("destination")
    embedding_store = MagicMock()
    toolkit._embedding_store = embedding_store

    await toolkit.rename_tree("source", "destination", overwrite=True)

    assert "source" not in toolkit._trees
    assert "source" not in toolkit._search
    assert "destination" not in toolkit._search
    embedding_store.invalidate_tree.assert_called_once_with("source")


@pytest.mark.asyncio
async def test_rename_tree_reprojects_okf_sidecars(toolkit: PageIndexToolkit) -> None:
    """Reproject an enriched tree after it has its destination URI."""
    await _seed_rename_tree(toolkit, "source", "SOURCE_BODY")
    async def enrich(txn) -> None:
        txn.tree["structure"][0].update({"concept_id": "source/node", "type": "Section"})

    await toolkit._mutate("source", enrich)
    projected: list[str] = []

    def project(tree_name: str, tree: dict) -> bool:
        projected.append(tree_name)
        return True

    toolkit._project_okf_sidecars = project
    await toolkit.rename_tree("source", "destination")

    assert projected == ["destination"]


def test_rename_tree_exposed_as_tool(toolkit: PageIndexToolkit) -> None:
    """Expose rename through normal prefixed toolkit discovery."""
    tool = toolkit.get_tool("pageindex_rename_tree")

    assert tool is not None
    fields = tool.args_schema.model_fields
    assert {"src", "dst", "overwrite"} <= set(fields)
    assert fields["overwrite"].default is False


@pytest.mark.asyncio
async def test_rename_tree_refuses_inside_write(toolkit: PageIndexToolkit) -> None:
    """Reject open source or destination write participation and invalid input."""
    await _seed_rename_tree(toolkit, "source", "SOURCE_BODY")
    await _seed_rename_tree(toolkit, "destination", "DESTINATION_BODY")

    with pytest.raises(ValueError):
        await toolkit.rename_tree("source", "source")
    with pytest.raises(ValueError):
        await toolkit.rename_tree("bad/name", "new")
    with pytest.raises(KeyError):
        await toolkit.rename_tree("missing", "new")
    with pytest.raises(KeyError):  # 128-char names are valid; the source is simply absent
        await toolkit.rename_tree("s" * 128, "d" * 128)
    async with toolkit._write("source"):
        with pytest.raises(ValueError, match="open write"):
            await toolkit.rename_tree("source", "new")
    async with toolkit._write("destination"):
        with pytest.raises(ValueError, match="open write"):
            await toolkit.rename_tree("source", "destination", overwrite=True)


@pytest.mark.asyncio
async def test_delete_node_leaves_blobs_for_sweep(toolkit: PageIndexToolkit, tmp_path: Path):
    """delete_node leaves immutable body blobs for the grace-period sweep."""
    await toolkit.create_tree("cleanup_test")
    added = await toolkit.add_node("cleanup_test", "Control 1", "body")
    tree = await toolkit.get_tree("cleanup_test")
    body_ref = tree["structure"][0]["body_ref"]
    body_path = tmp_path / "cleanup_test" / "bodies" / f"{body_ref}.md"

    result = await toolkit.delete_node("cleanup_test", added["node_id"])
    assert result["removed"] is True
    assert body_path.is_file()


@pytest.mark.asyncio
async def test_add_node_body_ref(toolkit: PageIndexToolkit, tmp_path: Path):
    """add_node stores its body in a content-addressed blob."""
    await toolkit.create_tree("kb")
    added = await toolkit.add_node("kb", "Finding", "body")
    tree = await toolkit.get_tree("kb")
    node = tree["structure"][0]

    assert node["node_id"] == added["node_id"]
    assert node["body_ref"]
    assert not (tmp_path / "kb" / f"{node['node_id']}.md").exists()
    assert toolkit._content_store.load_node("kb", node) == "body"


@pytest.mark.asyncio
async def test_delete_node_removes_flat_sidecars_of_removed_subtree(toolkit: PageIndexToolkit):
    """OKF flat-concept sidecars are never swept, so delete_node must remove them itself."""
    await toolkit.create_tree("okf")
    keep = await toolkit.add_node("okf", title="Keep", body="keep body")
    drop = await toolkit.add_node("okf", title="Drop", body="drop body")
    tree = await toolkit.get_tree("okf")
    by_id = {n["node_id"]: n for n in structure_to_list(tree["structure"])}
    keep_flat = flatten_concept_id_for_filename(by_id[keep["node_id"]]["concept_id"])
    drop_flat = flatten_concept_id_for_filename(by_id[drop["node_id"]]["concept_id"])
    toolkit._content_store.save("okf", keep_flat, "keep sidecar")
    toolkit._content_store.save("okf", drop_flat, "drop sidecar")

    result = await toolkit.delete_node("okf", drop["node_id"])

    assert result["removed"] is True
    assert not toolkit._content_store.has("okf", drop_flat)
    assert toolkit._content_store.load("okf", keep_flat) == "keep sidecar"


@pytest.mark.asyncio
async def test_noop_mutations_do_not_mint_a_generation(toolkit: PageIndexToolkit):
    await toolkit.create_tree("n")
    added = await toolkit.add_node("n", title="Tagged", body="b", categories=["a"])
    before = (await toolkit.get_generation("n"))["id"]

    assert (await toolkit.delete_node("n", "9999"))["removed"] is False
    await toolkit.tag_node("n", added["node_id"], categories=["a"])  # already present

    assert (await toolkit.get_generation("n"))["id"] == before
    await toolkit.tag_node("n", added["node_id"], categories=["b"])  # a real change still publishes
    assert (await toolkit.get_generation("n"))["id"] == before + 1


@pytest.mark.asyncio
async def test_create_tree_rejects_existing_without_wiping_bodies(toolkit: PageIndexToolkit):
    await toolkit.create_tree("c")
    added = await toolkit.add_node("c", title="Entry", body="precious")
    tree = await toolkit.get_tree("c")
    node = next(n for n in structure_to_list(tree["structure"]) if n["node_id"] == added["node_id"])

    with pytest.raises(ValueError, match="already exists"):
        await toolkit.create_tree("c")

    assert toolkit._content_store.load_node("c", node) == "precious"
