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
