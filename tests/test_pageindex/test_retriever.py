"""Tests for PageIndex retriever with mocked LLM adapter."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from parrot.pageindex.retriever import PageIndexRetriever
from parrot.pageindex.schemas import TreeSearchResult


SAMPLE_TREE = {
    "doc_name": "test.pdf",
    "structure": [
        {
            "title": "Introduction",
            "node_id": "0000",
            "start_index": 1,
            "end_index": 3,
            "summary": "Overview of the document",
        },
        {
            "title": "Methods",
            "node_id": "0001",
            "start_index": 4,
            "end_index": 8,
            "summary": "Description of methods used",
            "nodes": [
                {
                    "title": "Data Collection",
                    "node_id": "0002",
                    "start_index": 4,
                    "end_index": 5,
                    "summary": "How data was collected",
                    "text": "We collected data from surveys.",
                },
                {
                    "title": "Analysis",
                    "node_id": "0003",
                    "start_index": 6,
                    "end_index": 8,
                    "summary": "Statistical analysis methods",
                },
            ],
        },
        {
            "title": "Results",
            "node_id": "0004",
            "start_index": 9,
            "end_index": 12,
            "summary": "Key findings",
        },
    ],
}


def _make_mock_adapter(search_result: TreeSearchResult):
    """Create a mock adapter that returns a given TreeSearchResult."""
    adapter = MagicMock()
    adapter.ask_structured = AsyncMock(return_value=search_result)
    adapter.ask = AsyncMock(return_value="mocked response")
    return adapter


class TestPageIndexRetriever:

    def test_init_from_dict(self):
        adapter = MagicMock()
        retriever = PageIndexRetriever(tree=SAMPLE_TREE, adapter=adapter)
        assert retriever.structure == SAMPLE_TREE["structure"]

    def test_init_from_list(self):
        adapter = MagicMock()
        retriever = PageIndexRetriever(tree=SAMPLE_TREE["structure"], adapter=adapter)
        assert len(retriever.structure) == 3

    @pytest.mark.asyncio
    async def test_search(self):
        expected = TreeSearchResult(
            thinking="Methods section covers data collection",
            node_list=["0002", "0003"],
        )
        adapter = _make_mock_adapter(expected)
        retriever = PageIndexRetriever(tree=SAMPLE_TREE, adapter=adapter)

        result = await retriever.search("How was data collected?")
        assert isinstance(result, TreeSearchResult)
        assert result.node_list == ["0002", "0003"]

    @pytest.mark.asyncio
    async def test_search_with_expert_knowledge(self):
        expected = TreeSearchResult(
            thinking="Expert says check Methods",
            node_list=["0001"],
        )
        adapter = _make_mock_adapter(expected)
        retriever = PageIndexRetriever(
            tree=SAMPLE_TREE,
            adapter=adapter,
            expert_knowledge="Data collection is in Section 2",
        )

        result = await retriever.search("Where is the data?")
        assert result.node_list == ["0001"]
        # Verify expert knowledge was included in the prompt
        call_args = adapter.ask_structured.call_args
        assert "Expert Knowledge" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_retrieve_with_text(self):
        expected = TreeSearchResult(
            thinking="Node has text",
            node_list=["0002"],
        )
        adapter = _make_mock_adapter(expected)
        retriever = PageIndexRetriever(tree=SAMPLE_TREE, adapter=adapter)

        context = await retriever.retrieve("Survey data?")
        assert "We collected data from surveys" in context
        assert "## Data Collection" in context

    @pytest.mark.asyncio
    async def test_retrieve_with_pdf_pages(self):
        expected = TreeSearchResult(
            thinking="Check results",
            node_list=["0004"],
        )
        adapter = _make_mock_adapter(expected)
        retriever = PageIndexRetriever(tree=SAMPLE_TREE, adapter=adapter)

        pdf_pages = [(f"Page {i} content", 100) for i in range(1, 15)]
        context = await retriever.retrieve("Key findings?", pdf_pages=pdf_pages)
        assert "## Results" in context
        assert "Page 9 content" in context

    @pytest.mark.asyncio
    async def test_retrieve_with_summary_fallback(self):
        expected = TreeSearchResult(
            thinking="Check analysis",
            node_list=["0003"],
        )
        adapter = _make_mock_adapter(expected)
        retriever = PageIndexRetriever(tree=SAMPLE_TREE, adapter=adapter)

        context = await retriever.retrieve("Analysis methods?")
        assert "Statistical analysis methods" in context

    @pytest.mark.asyncio
    async def test_retrieve_empty_results(self):
        expected = TreeSearchResult(thinking="Nothing found", node_list=[])
        adapter = _make_mock_adapter(expected)
        retriever = PageIndexRetriever(tree=SAMPLE_TREE, adapter=adapter)

        context = await retriever.retrieve("Unrelated query")
        assert context == ""

    def test_get_tree_context(self):
        adapter = MagicMock()
        retriever = PageIndexRetriever(tree=SAMPLE_TREE, adapter=adapter)

        context = retriever.get_tree_context()
        assert "[0000] Introduction" in context
        assert "(pages 1-3)" in context
        assert "Summary: Overview" in context

    def test_get_tree_context_no_summaries(self):
        adapter = MagicMock()
        retriever = PageIndexRetriever(tree=SAMPLE_TREE, adapter=adapter)

        context = retriever.get_tree_context(include_summaries=False)
        parsed = json.loads(context)
        assert isinstance(parsed, list)
        assert len(parsed) == 3

    def test_get_tree_json(self):
        adapter = MagicMock()
        retriever = PageIndexRetriever(tree=SAMPLE_TREE, adapter=adapter)
        assert retriever.get_tree_json() == SAMPLE_TREE

    def test_from_json_dict(self):
        adapter = MagicMock()
        retriever = PageIndexRetriever.from_json(SAMPLE_TREE, adapter)
        assert len(retriever.structure) == 3
