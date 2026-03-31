from __future__ import annotations

import asyncio

from parrot.tools.pageindex_toolkit import PageIndexToolkit


class _FakeClient:
    async def close(self):
        return None


class _FakeSearchResult:
    def __init__(self, thinking: str, node_list: list[int]):
        self.thinking = thinking
        self.node_list = node_list


class _FakeRetriever:
    def __init__(self, tree, adapter, model):
        self.tree = tree

    async def search(self, query: str):
        return _FakeSearchResult(thinking=f"searching {query}", node_list=[1, 2])

    async def retrieve(self, query: str):
        return f"context for {query}"

    def get_tree_context(self, include_summaries: bool = True):
        return "tree-context"


async def _fake_md_to_tree(md_text, adapter, options, doc_name):
    return {
        "doc_name": doc_name,
        "structure": [{"title": "Intro", "text": md_text}],
    }


def test_pageindex_toolkit_index_and_search(monkeypatch):
    monkeypatch.setattr("parrot.tools.pageindex_toolkit.md_to_tree", _fake_md_to_tree)
    monkeypatch.setattr("parrot.tools.pageindex_toolkit.PageIndexRetriever", _FakeRetriever)

    toolkit = PageIndexToolkit(client=_FakeClient())

    index_result = asyncio.run(
        toolkit.index_documents(
            documents=["# Doc A\nBody", "# Doc B\nBody"],
            document_names=["a.md", "b.md"],
        )
    )

    assert index_result["status"] == "indexed"
    assert index_result["document_count"] == 2
    assert index_result["index_id"]

    search_result = asyncio.run(
        toolkit.search_documents(
            index_id=index_result["index_id"],
            query="find intro",
            include_tree_context=True,
        )
    )

    assert search_result["status"] == "ok"
    assert search_result["node_list"] == [1, 2]
    assert search_result["context"] == "context for find intro"
    assert search_result["tree_context"] == "tree-context"


def test_pageindex_toolkit_search_unknown_index():
    toolkit = PageIndexToolkit(client=_FakeClient())

    result = asyncio.run(toolkit.search_documents(index_id="missing", query="anything"))

    assert result["status"] == "not_found"
