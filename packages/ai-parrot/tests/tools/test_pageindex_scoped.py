"""Unit tests for PageIndexToolkit.search_documents_scoped (TASK-1089).

Tests the new multi-tree scoped search method that routes queries to a
SUBSET of indexed PageIndex trees rather than the entire collection.

All tests use mocked PageIndexRetriever instances so no LLM calls are made.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.pageindex.schemas import TreeSearchResult
from parrot.tools.pageindex_toolkit import PageIndexToolkit, SearchScopedInput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_retriever_mock(
    thinking: str = "relevant section found",
    node_list: list[str] | None = None,
    context: str = "retrieved context",
    tree_context: str = "tree context blob",
) -> MagicMock:
    """Return a mock PageIndexRetriever with deterministic search / retrieve."""
    retriever = MagicMock()
    retriever.search = AsyncMock(
        return_value=TreeSearchResult(
            thinking=thinking,
            node_list=node_list if node_list is not None else ["node-1"],
        )
    )
    retriever.retrieve = AsyncMock(return_value=context)
    retriever.get_tree_context = MagicMock(return_value=tree_context)
    return retriever


def _make_toolkit_with_indices(
    tree_map: dict[str, dict[str, Any]],
) -> PageIndexToolkit:
    """Return a PageIndexToolkit with pre-loaded _indices (no real client)."""
    toolkit = PageIndexToolkit.__new__(PageIndexToolkit)
    toolkit._indices = tree_map
    # Provide a real logger via the base-class pattern
    import logging
    toolkit.logger = logging.getLogger("test.pageindex_scoped")
    return toolkit


# ---------------------------------------------------------------------------
# Tests — SearchScopedInput schema
# ---------------------------------------------------------------------------


class TestSearchScopedInputSchema:
    """Tests that SearchScopedInput validates correctly."""

    def test_minimal_valid_input(self) -> None:
        """tree_ids and query are the only required fields."""
        inp = SearchScopedInput(tree_ids=["t1", "t2"], query="what is the policy?")
        assert inp.tree_ids == ["t1", "t2"]
        assert inp.query == "what is the policy?"
        assert inp.include_tree_context is False
        assert inp.max_trees == 10

    def test_include_tree_context_defaults_false(self) -> None:
        """include_tree_context must default to False."""
        inp = SearchScopedInput(tree_ids=["t1"], query="q")
        assert inp.include_tree_context is False

    def test_max_trees_defaults_to_10(self) -> None:
        """max_trees must default to 10."""
        inp = SearchScopedInput(tree_ids=["t1"], query="q")
        assert inp.max_trees == 10

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields must raise ValidationError (extra='forbid')."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SearchScopedInput(tree_ids=["t1"], query="q", extra_field="bad")

    def test_empty_tree_ids_is_valid(self) -> None:
        """Empty tree_ids list must be accepted by the schema."""
        inp = SearchScopedInput(tree_ids=[], query="q")
        assert inp.tree_ids == []


# ---------------------------------------------------------------------------
# Tests — search_documents_scoped method
# ---------------------------------------------------------------------------


class TestSearchDocumentsScopedBasic:
    """Tests for the core scoped search behaviour."""

    @pytest.mark.asyncio
    async def test_empty_tree_ids_returns_empty_status(self) -> None:
        """Calling with tree_ids=[] must return status='empty' without invoking PageIndex."""
        toolkit = _make_toolkit_with_indices({})
        result = await toolkit.search_documents_scoped(
            tree_ids=[], query="anything"
        )
        assert result["status"] == "empty"
        assert result["scoped_results"] == []

    @pytest.mark.asyncio
    async def test_single_tree_returns_ok_status(self) -> None:
        """A single matching tree_id must return status='ok' with one entry."""
        retriever = _make_retriever_mock(thinking="found it", node_list=["n1"])
        toolkit = _make_toolkit_with_indices(
            {"tree-a": {"tree": {"doc_name": "policy.md"}, "retriever": retriever}}
        )
        result = await toolkit.search_documents_scoped(
            tree_ids=["tree-a"], query="commissions"
        )
        assert result["status"] == "ok"
        assert len(result["scoped_results"]) == 1
        entry = result["scoped_results"][0]
        assert entry["tree_id"] == "tree-a"
        assert entry["doc_name"] == "policy.md"
        assert entry["node_list"] == ["n1"]
        assert entry["thinking"] == "found it"

    @pytest.mark.asyncio
    async def test_multiple_trees_calls_each_retriever(self) -> None:
        """Three valid tree_ids must produce three scoped_results entries."""
        r1 = _make_retriever_mock(thinking="tree1", context="ctx1")
        r2 = _make_retriever_mock(thinking="tree2", context="ctx2")
        r3 = _make_retriever_mock(thinking="tree3", context="ctx3")

        toolkit = _make_toolkit_with_indices(
            {
                "tree-1": {"tree": {"doc_name": "doc1"}, "retriever": r1},
                "tree-2": {"tree": {"doc_name": "doc2"}, "retriever": r2},
                "tree-3": {"tree": {"doc_name": "doc3"}, "retriever": r3},
            }
        )
        result = await toolkit.search_documents_scoped(
            tree_ids=["tree-1", "tree-2", "tree-3"],
            query="policy",
        )

        assert result["status"] == "ok"
        assert len(result["scoped_results"]) == 3
        tree_ids_returned = [e["tree_id"] for e in result["scoped_results"]]
        assert set(tree_ids_returned) == {"tree-1", "tree-2", "tree-3"}

        # Each retriever must have been called exactly once
        r1.search.assert_called_once_with("policy")
        r2.search.assert_called_once_with("policy")
        r3.search.assert_called_once_with("policy")

    @pytest.mark.asyncio
    async def test_only_requested_trees_are_searched(self) -> None:
        """Only the trees listed in tree_ids must be searched; others are untouched."""
        r1 = _make_retriever_mock()
        r2 = _make_retriever_mock()
        r3 = _make_retriever_mock()

        toolkit = _make_toolkit_with_indices(
            {
                "tree-1": {"tree": {}, "retriever": r1},
                "tree-2": {"tree": {}, "retriever": r2},
                "tree-3": {"tree": {}, "retriever": r3},
            }
        )
        await toolkit.search_documents_scoped(
            tree_ids=["tree-1", "tree-3"],
            query="query",
        )

        r1.search.assert_called_once()
        r3.search.assert_called_once()
        # tree-2 must NOT have been searched
        r2.search.assert_not_called()
        r2.retrieve.assert_not_called()

    @pytest.mark.asyncio
    async def test_retrieve_called_for_each_tree(self) -> None:
        """retrieve() must be called once per tree in addition to search()."""
        r1 = _make_retriever_mock(context="context for tree-1")
        toolkit = _make_toolkit_with_indices(
            {"tree-1": {"tree": {}, "retriever": r1}}
        )
        result = await toolkit.search_documents_scoped(
            tree_ids=["tree-1"], query="bonus policy"
        )
        r1.retrieve.assert_called_once_with("bonus policy")
        assert result["scoped_results"][0]["context"] == "context for tree-1"

    @pytest.mark.asyncio
    async def test_result_entry_shape(self) -> None:
        """Each scoped_results entry must have the correct keys."""
        retriever = _make_retriever_mock(
            thinking="thinking text",
            node_list=["node-a", "node-b"],
            context="the context string",
        )
        toolkit = _make_toolkit_with_indices(
            {"tid": {"tree": {"doc_name": "my-doc.md"}, "retriever": retriever}}
        )
        result = await toolkit.search_documents_scoped(
            tree_ids=["tid"], query="query"
        )
        entry = result["scoped_results"][0]
        assert "tree_id" in entry
        assert "doc_name" in entry
        assert "node_list" in entry
        assert "thinking" in entry
        assert "context" in entry
        # tree_context must NOT be present when include_tree_context=False
        assert "tree_context" not in entry


# ---------------------------------------------------------------------------
# Tests — missing tree_ids handling
# ---------------------------------------------------------------------------


class TestMissingTreeIds:
    """Tests for silent skip behaviour when tree_ids are missing."""

    @pytest.mark.asyncio
    async def test_missing_tree_id_is_skipped_silently(self) -> None:
        """A tree_id not in _indices must be skipped without raising."""
        retriever = _make_retriever_mock()
        toolkit = _make_toolkit_with_indices(
            {"real-tree": {"tree": {"doc_name": "real.md"}, "retriever": retriever}}
        )
        result = await toolkit.search_documents_scoped(
            tree_ids=["real-tree", "ghost-tree"],
            query="query",
        )
        assert result["status"] == "ok"
        assert len(result["scoped_results"]) == 1
        assert result["scoped_results"][0]["tree_id"] == "real-tree"

    @pytest.mark.asyncio
    async def test_missing_tree_id_logs_warning(self, caplog) -> None:
        """Missing tree_ids must produce a WARNING log entry."""
        import logging

        toolkit = _make_toolkit_with_indices({})
        with caplog.at_level(logging.WARNING):
            result = await toolkit.search_documents_scoped(
                tree_ids=["ghost-tree"], query="q"
            )

        assert result["status"] == "empty"
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("ghost-tree" in msg for msg in warning_messages), (
            f"Expected WARNING about 'ghost-tree', got: {warning_messages}"
        )

    @pytest.mark.asyncio
    async def test_all_missing_returns_empty_status(self) -> None:
        """When all tree_ids are missing, status must be 'empty'."""
        toolkit = _make_toolkit_with_indices({})
        result = await toolkit.search_documents_scoped(
            tree_ids=["ghost-1", "ghost-2"],
            query="q",
        )
        assert result["status"] == "empty"
        assert result["scoped_results"] == []

    @pytest.mark.asyncio
    async def test_two_valid_one_missing_returns_two_results(self) -> None:
        """Mixed valid and missing tree_ids must produce results for valid only."""
        r1 = _make_retriever_mock()
        r2 = _make_retriever_mock()

        toolkit = _make_toolkit_with_indices(
            {
                "tree-a": {"tree": {}, "retriever": r1},
                "tree-b": {"tree": {}, "retriever": r2},
            }
        )
        result = await toolkit.search_documents_scoped(
            tree_ids=["tree-a", "tree-b", "ghost"],
            query="q",
        )
        assert result["status"] == "ok"
        assert len(result["scoped_results"]) == 2


# ---------------------------------------------------------------------------
# Tests — include_tree_context
# ---------------------------------------------------------------------------


class TestIncludeTreeContext:
    """Tests for the include_tree_context option."""

    @pytest.mark.asyncio
    async def test_include_tree_context_false_omits_tree_context_key(self) -> None:
        """When include_tree_context=False, tree_context must NOT appear."""
        retriever = _make_retriever_mock()
        toolkit = _make_toolkit_with_indices(
            {"t": {"tree": {}, "retriever": retriever}}
        )
        result = await toolkit.search_documents_scoped(
            tree_ids=["t"], query="q", include_tree_context=False
        )
        entry = result["scoped_results"][0]
        assert "tree_context" not in entry
        retriever.get_tree_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_include_tree_context_true_adds_tree_context_key(self) -> None:
        """When include_tree_context=True, tree_context must appear in results."""
        retriever = _make_retriever_mock(tree_context="[node-1] Section A")
        toolkit = _make_toolkit_with_indices(
            {"t": {"tree": {}, "retriever": retriever}}
        )
        result = await toolkit.search_documents_scoped(
            tree_ids=["t"], query="q", include_tree_context=True
        )
        entry = result["scoped_results"][0]
        assert "tree_context" in entry
        assert entry["tree_context"] == "[node-1] Section A"
        retriever.get_tree_context.assert_called_once_with(include_summaries=True)


# ---------------------------------------------------------------------------
# Tests — max_trees cap
# ---------------------------------------------------------------------------


class TestMaxTreesCap:
    """Tests for the max_trees hard cap."""

    @pytest.mark.asyncio
    async def test_max_trees_caps_number_of_searches(self) -> None:
        """search_documents_scoped must not search more than max_trees trees."""
        indices = {
            f"tree-{i}": {"tree": {"doc_name": f"doc-{i}.md"}, "retriever": _make_retriever_mock()}
            for i in range(15)
        }
        toolkit = _make_toolkit_with_indices(indices)
        tree_ids = [f"tree-{i}" for i in range(15)]

        result = await toolkit.search_documents_scoped(
            tree_ids=tree_ids,
            query="q",
            max_trees=5,
        )
        # Only the first 5 trees must have been searched
        assert result["status"] == "ok"
        assert len(result["scoped_results"]) == 5

    @pytest.mark.asyncio
    async def test_default_max_trees_is_10(self) -> None:
        """Without specifying max_trees, at most 10 trees must be searched."""
        indices = {
            f"tree-{i}": {"tree": {}, "retriever": _make_retriever_mock()}
            for i in range(12)
        }
        toolkit = _make_toolkit_with_indices(indices)
        tree_ids = [f"tree-{i}" for i in range(12)]

        result = await toolkit.search_documents_scoped(
            tree_ids=tree_ids, query="q"
        )
        assert len(result["scoped_results"]) == 10


# ---------------------------------------------------------------------------
# Tests — doc_name fallback
# ---------------------------------------------------------------------------


class TestDocNameFallback:
    """Tests that doc_name is None when not in the tree record."""

    @pytest.mark.asyncio
    async def test_doc_name_is_none_when_absent(self) -> None:
        """When the tree record has no doc_name, entry['doc_name'] must be None."""
        retriever = _make_retriever_mock()
        toolkit = _make_toolkit_with_indices(
            {"t": {"tree": {}, "retriever": retriever}}  # no doc_name key
        )
        result = await toolkit.search_documents_scoped(
            tree_ids=["t"], query="q"
        )
        assert result["scoped_results"][0]["doc_name"] is None

    @pytest.mark.asyncio
    async def test_doc_name_present_when_in_tree(self) -> None:
        """When tree has doc_name, it must appear in the entry."""
        retriever = _make_retriever_mock()
        toolkit = _make_toolkit_with_indices(
            {"t": {"tree": {"doc_name": "sales-commissions-policy.md"}, "retriever": retriever}}
        )
        result = await toolkit.search_documents_scoped(
            tree_ids=["t"], query="q"
        )
        assert result["scoped_results"][0]["doc_name"] == "sales-commissions-policy.md"


# ---------------------------------------------------------------------------
# Tests — method discoverability
# ---------------------------------------------------------------------------


class TestMethodDiscoverability:
    """Tests that search_documents_scoped is a tool and is discoverable."""

    def test_method_exists_on_toolkit(self) -> None:
        """search_documents_scoped must be a method on PageIndexToolkit."""
        assert hasattr(PageIndexToolkit, "search_documents_scoped")
        assert callable(getattr(PageIndexToolkit, "search_documents_scoped"))

    def test_method_has_tool_schema_annotation(self) -> None:
        """search_documents_scoped must carry the _args_schema attribute from @tool_schema."""
        method = PageIndexToolkit.search_documents_scoped
        # @tool_schema attaches _args_schema to the decorated function
        assert hasattr(method, "_args_schema"), (
            "search_documents_scoped must be decorated with @tool_schema(SearchScopedInput)"
        )

    def test_schema_is_search_scoped_input(self) -> None:
        """The attached _args_schema must be SearchScopedInput."""
        method = PageIndexToolkit.search_documents_scoped
        assert method._args_schema is SearchScopedInput

    def test_search_scoped_input_in_toolkit_module(self) -> None:
        """SearchScopedInput must be importable from pageindex_toolkit."""
        from parrot.tools.pageindex_toolkit import SearchScopedInput as SSI

        assert SSI is SearchScopedInput
