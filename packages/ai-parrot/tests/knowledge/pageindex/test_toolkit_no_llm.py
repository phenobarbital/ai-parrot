"""PageIndexToolkit without an LLM adapter (FEAT-842 M1/M2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

from parrot.clients.base import AbstractClient
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

LLM_TOOLS = {
    "pageindex_insert_content",
    "pageindex_import_file",
    "pageindex_import_folder",
    "pageindex_import_pdf",
    "pageindex_search_documents_scoped",
}

_FILLER = (
    "the quick survey notes record observations gathered across many seasons of careful fieldwork "
    "by volunteers who walked the same transects every month and wrote down what they saw "
    "including weather conditions timing and the general behaviour of the species encountered"
)

DOC = f"""# Field Guide

## Alpine Plants
Edelweiss grows on high alpine ridges above the tree line. {_FILLER}.

## Coastal Birds
Cormorants nest on coastal cliffs facing the open sea. {_FILLER}.

## River Fish
Grayling prefer cold clear rivers with gravel beds. {_FILLER}.
"""


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    # tiktoken may download encodings on first use; approximate with char count.
    def _approx(text: str, model: str = "gpt-4o") -> int:
        return max(1, len(text or ""))

    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", _approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", _approx)


def _client() -> MagicMock:
    client = MagicMock(spec=AbstractClient)
    client.default_model = "test-model"
    return client


def _walk(nodes: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for node in nodes:
        yield node
        yield from _walk(node.get("nodes") or [])


def test_constructs_without_adapter(tmp_path: Path) -> None:
    """AC-1."""
    tk = PageIndexToolkit(storage_dir=tmp_path)
    assert tk.has_llm is False
    with pytest.raises(ValueError, match="storage_dir"):
        PageIndexToolkit(storage_dir=None)


def test_positional_and_keyword_adapter_unchanged(tmp_path: Path) -> None:
    """AC-1: PageIndexToolkit(a, d) and PageIndexToolkit(adapter=a, storage_dir=d)."""
    adapter = PageIndexLLMAdapter(client=_client(), model="m")
    positional = PageIndexToolkit(adapter, tmp_path / "a")
    keyword = PageIndexToolkit(adapter=adapter, storage_dir=tmp_path / "b")
    for tk in (positional, keyword):
        assert tk._adapter is adapter
        assert tk.has_llm is True
        assert tk._model == "m"


def test_llm_client_is_wrapped(tmp_path: Path) -> None:
    """AC-2."""
    client = _client()
    tk = PageIndexToolkit(storage_dir=tmp_path, llm_client=client, model="m", lightweight_model="light")
    assert tk.has_llm is True
    assert tk._adapter.client is client
    assert tk._adapter.model == "m"
    assert tk._light_adapter is not None
    assert tk._light_adapter.client is client
    assert tk._light_adapter.model == "light"


def test_lightweight_model_ignored_without_llm(tmp_path: Path) -> None:
    tk = PageIndexToolkit(storage_dir=tmp_path, lightweight_model="light")
    assert tk._light_adapter is None
    assert tk._model is None


def test_adapter_and_llm_client_together_raise(tmp_path: Path) -> None:
    """AC-2."""
    adapter = PageIndexLLMAdapter(client=_client(), model="m")
    with pytest.raises(ValueError, match="either adapter or llm_client"):
        PageIndexToolkit(adapter=adapter, storage_dir=tmp_path, llm_client=_client())


def test_llm_dependent_tools_names(tmp_path: Path) -> None:
    """AC-3."""
    tk = PageIndexToolkit(storage_dir=tmp_path)
    assert PageIndexToolkit.llm_dependent_tools == LLM_TOOLS
    assert LLM_TOOLS <= set(tk.list_tool_names())


async def test_search_and_retrieve_without_adapter(tmp_path: Path) -> None:
    """AC-4: BM25 only, retrieve returns text, insert_markdown assigns SECTION types."""
    pytest.importorskip("bm25s")
    tk = PageIndexToolkit(storage_dir=tmp_path)
    await tk.create_tree("guide")
    await tk.insert_markdown("guide", DOC)

    results = await tk.search("guide", "edelweiss", use_llm_walk=True)
    assert results
    assert all(r["source"] == "bm25" for r in results)
    assert results[0]["title"] == "Alpine Plants"

    text = await tk.retrieve("guide", "edelweiss")
    assert text
    assert "Edelweiss" in text

    tree = await tk.get_tree("guide")
    nodes = list(_walk(tree["structure"]))
    assert nodes
    # Offline ingest never calls an LLM: nodes are untyped on a fresh tree (T3 classification is
    # gated on OKF-enriched trees and falls back to Section without an adapter).
    assert {node.get("type", "Section") for node in nodes} == {"Section"}


async def test_llm_walk_only_without_adapter_raises(tmp_path: Path) -> None:
    """AC-4."""
    pytest.importorskip("bm25s")
    tk = PageIndexToolkit(storage_dir=tmp_path)
    await tk.create_tree("guide")
    await tk.insert_markdown("guide", DOC)
    with pytest.raises(ValueError, match="LLM walk requested"):
        await tk.search("guide", "edelweiss", use_bm25=False, use_llm_walk=True)


_TAIL = "lower top_k or narrow the query]"


def test_bound_text_none_is_identity(tmp_path: Path) -> None:
    """AC-6: None keeps the output byte-identical."""
    tk = PageIndexToolkit(storage_dir=tmp_path)
    assert tk._bound_text(["## A\nx", "## B\ny"]) == "## A\nx\n\n## B\ny"
    assert tk._bound_text([]) == ""


def test_bound_text_within_limit_is_identity(tmp_path: Path) -> None:
    tk = PageIndexToolkit(storage_dir=tmp_path, max_result_chars=100)
    assert tk._bound_text(["## A\nx", "## B\ny"]) == "## A\nx\n\n## B\ny"


def test_bound_text_keeps_whole_parts_and_marks(tmp_path: Path) -> None:
    """AC-6: whole parts kept while they fit; marker names chars and sections dropped."""
    parts = [f"## S{i}\n" + "word " * 10 for i in range(3)]
    tk = PageIndexToolkit(storage_dir=tmp_path, max_result_chars=len(parts[0]) + 5)
    out = tk._bound_text(parts)
    assert out.startswith(parts[0] + "\n\n[truncated:")
    assert "## S1" not in out
    assert out.endswith(_TAIL)
    assert "in 2 further sections" in out
    dropped = len("\n\n".join(parts)) - len(parts[0])
    assert f"{dropped} more characters" in out


def test_bound_text_cuts_first_part_after_title(tmp_path: Path) -> None:
    """AC-6: an oversized first part is cut at a paragraph break, never inside '## title'."""
    first = "## Title\n" + "\n\n".join(["para " * 20] * 5)
    parts = [first, "## Other\nbody"]
    limit = 150
    tk = PageIndexToolkit(storage_dir=tmp_path, max_result_chars=limit)
    out = tk._bound_text(parts)
    marker_len = len(out) - len(out.split("\n\n[truncated:")[0])
    assert out.startswith("## Title\n")
    assert out.endswith(_TAIL)
    assert len(out) <= limit + marker_len
    assert "in 1 further sections" in out


def test_bound_text_tiny_limit_keeps_title_line(tmp_path: Path) -> None:
    tk = PageIndexToolkit(storage_dir=tmp_path, max_result_chars=3)
    out = tk._bound_text(["## A long title\nbody text here", "## B\nz"])
    assert out.startswith("## A long title")
    assert out.endswith(_TAIL)


async def test_retrieve_is_bounded(tmp_path: Path) -> None:
    """AC-6 end to end: retrieve on a no-LLM toolkit honours max_result_chars."""
    pytest.importorskip("bm25s")
    tk = PageIndexToolkit(storage_dir=tmp_path, max_result_chars=200)
    await tk.create_tree("guide")
    await tk.insert_markdown("guide", DOC)
    out = await tk.retrieve("guide", "edelweiss alpine coastal river", top_k=3)
    assert out.endswith(_TAIL)
    assert out.startswith("## ")
    unbounded = PageIndexToolkit(storage_dir=tmp_path)
    full = await unbounded.retrieve("guide", "edelweiss alpine coastal river", top_k=3)
    assert len(full) > 200
    assert not full.endswith(_TAIL)
