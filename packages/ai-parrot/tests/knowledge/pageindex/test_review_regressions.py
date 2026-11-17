"""Regression coverage for PageIndex parsing, storage and retrieval review."""

import errno
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from parrot.knowledge.pageindex import locks
from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch
from parrot.knowledge.pageindex.llm_adapter import extract_json as adapter_extract_json
from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.utils import extract_json
from parrot.knowledge.pageindex.vector_walk import FlatMatrixSearch, embedding_tree_walk
from parrot.knowledge.pageindex.md_builder import md_to_tree
from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.generation import body_sha16
from parrot.knowledge.pageindex.okf.bundle import export_okf_bundle
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit


@pytest.mark.parametrize("parse", [extract_json, adapter_extract_json])
def test_json_repairs_preserve_quoted_content(parse) -> None:
    """Repairs must not change literal None, whitespace or comma/bracket text."""
    raw = '{"text": "None  remains ,] and ,}", "missing": None, }'
    assert parse(raw) == {"text": "None  remains ,] and ,}", "missing": None}


@pytest.mark.parametrize("name", ["../outside", "/tmp/outside", "tree\n"])
def test_embedding_names_are_validated(tmp_path: Path, name: str) -> None:
    """All embedding operations must remain within the tree namespace."""
    store = NodeEmbeddingStore(tmp_path, "model", 2)
    with pytest.raises(ValueError):
        store.build_tree_matrix(name, [{"node_id": "1"}], lambda texts: np.ones((len(texts), 2)))
    with pytest.raises(ValueError):
        store.invalidate_tree(name)
    with pytest.raises(ValueError):
        JSONTreeStore(tmp_path)._path_for(name)


def test_duplicate_content_embedded_once(tmp_path: Path) -> None:
    """Equal content shares one embedding even within a cold batch."""
    store = NodeEmbeddingStore(tmp_path, "model", 2)
    embed = MagicMock(return_value=np.array([[1, 2]], dtype=np.float32))
    matrix, order = store.build_tree_matrix(
        "tree", [{"node_id": "1", "title": "same"}, {"node_id": "2", "title": "same"}], embed
    )
    embed.assert_called_once_with(["same"])
    assert order == ["1", "2"]
    np.testing.assert_array_equal(matrix, [[1, 2], [1, 2]])


def test_matrix_isolated_by_model(tmp_path: Path) -> None:
    """A model switch cannot silently reuse another model's matrix."""
    first = NodeEmbeddingStore(tmp_path, "first", 2)
    first.build_tree_matrix("tree", [{"node_id": "1"}], lambda texts: np.ones((len(texts), 2)))
    assert NodeEmbeddingStore(tmp_path, "second", 2).load_tree_matrix("tree") is None


@pytest.mark.parametrize("vectors", [np.ones((1, 3)), np.array([[float("nan"), 1]])])
def test_bad_embedding_batch_not_persisted(tmp_path: Path, vectors: np.ndarray) -> None:
    """Reject malformed vectors before poisoning the cache."""
    store = NodeEmbeddingStore(tmp_path, "model", 2)
    with pytest.raises(ValueError, match="invalid embedding batch"):
        store.build_tree_matrix("tree", [{"node_id": "1"}], lambda texts: vectors)
    assert not list(tmp_path.rglob("*.npy"))


@pytest.mark.asyncio
async def test_beam_scores_roots_and_uses_snapshot_key() -> None:
    """A relevant root leaf must compete with branches using the requested generation."""
    tree = {
        "doc_name": "Display title",
        "structure": [{"node_id": "leaf"}, {"node_id": "branch", "nodes": [{"node_id": "child"}]}],
    }
    store = MagicMock()
    store.load_tree_matrix.return_value = (np.array([[1, 0], [0, 1], [0, 1]]), ["leaf", "branch", "child"])
    result = await embedding_tree_walk(tree, np.array([1, 0]), store, beam_width=1, tree_name="tree", generation_id=7)
    assert result == ["leaf"]
    store.load_tree_matrix.assert_called_once_with("tree", generation_id=7)


def test_rrf_does_not_reward_duplicate_nodes() -> None:
    """One signal contributes at most once per node."""
    assert HybridPageIndexSearch._rrf_fuse([["a", "a", "b"]]) == HybridPageIndexSearch._rrf_fuse([["a", "b"]])


def test_negative_top_k_returns_no_results() -> None:
    """Negative slicing must not return nearly the entire corpus."""
    search = FlatMatrixSearch(np.eye(2), ["a", "b"])
    assert search.search(np.array([1, 0]), -1) == []


@pytest.mark.asyncio
async def test_lock_propagates_non_contention_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Descriptor or filesystem errors must not be retried as contention."""
    monkeypatch.setattr(locks.fcntl, "flock", MagicMock(side_effect=OSError(errno.EBADF, "bad descriptor")))
    with pytest.raises(OSError) as caught:
        async with locks.tree_lock(tmp_path, "tree", timeout=0):
            pytest.fail("lock unexpectedly acquired")
    assert caught.value.errno == errno.EBADF


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "markdown", ["A short important fact.", "# Fact\nShort but important.", "Preface.\n# Fact\nBody."]
)
async def test_markdown_keeps_short_text(markdown: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Markdown imports preserve short sections and text before headings."""
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", lambda text: len(text))
    tree = await md_to_tree(markdown)
    text = "\n".join(node["text"] for node in tree["structure"])
    for line in markdown.splitlines():
        if not line.startswith("#"):
            assert line in text


def test_export_reads_snapshot_body(tmp_path: Path) -> None:
    """An immutable body takes precedence over an obsolete OKF projection."""
    store = NodeContentStore(tmp_path / "storage")
    key = f"fact.{body_sha16('current body')}"
    store.save_body("tree", key, "current body")
    store.save("tree", "fact", "obsolete body")
    tree = {"structure": [{"node_id": "0000", "concept_id": "fact", "type": "Section", "body_ref": key}]}
    export_okf_bundle(tree, "tree", store, tmp_path / "export")
    exported = (tmp_path / "export" / "sections" / "fact.md").read_text()
    assert "current body" in exported
    assert "obsolete body" not in exported


@pytest.mark.asyncio
async def test_retrieve_uses_search_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A concurrent node renumber cannot substitute a different document's text."""
    toolkit = PageIndexToolkit(storage_dir=tmp_path)
    await toolkit.create_tree("tree")
    await toolkit.add_node("tree", title="original", body="original evidence")

    async def search(engine: HybridPageIndexSearch, **kwargs: object) -> list[dict]:
        await toolkit.update_node_content("tree", "0000", "replacement evidence")
        return [{"node_id": "0000"}]

    monkeypatch.setattr(HybridPageIndexSearch, "search", search)
    result = await toolkit.retrieve("tree", "evidence")
    assert "original evidence" in result
    assert "replacement evidence" not in result


@pytest.mark.asyncio
async def test_load_does_not_cache_old_tree_with_new_signature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file replaced between load and stat is noticed on the next read."""
    store = JSONTreeStore(tmp_path)
    store.save("tree", {"doc_name": "old", "structure": []})
    toolkit = PageIndexToolkit(storage_dir=tmp_path)
    original_load = toolkit._store.load

    def replace_after_read(name: str) -> dict:
        old = original_load(name)
        store.save(name, {"doc_name": "replacement", "structure": []})
        return old

    monkeypatch.setattr(toolkit._store, "load", replace_after_read)
    assert toolkit._load_tree("tree")["doc_name"] == "old"
    monkeypatch.setattr(toolkit._store, "load", original_load)
    assert toolkit._load_tree("tree")["doc_name"] == "replacement"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('Here is the JSON:\n```json\n{"a": 1}\n```', {"a": 1}),
        ('Sure:\n```json\n{"physical_index": None}\n```', {"physical_index": None}),
        ('{"text": "line one\nline two"}', {"text": "line one\nline two"}),
        ('{"text": "a\tb", }', {"text": "a\tb"}),
        ('{"code": "```py\\nx\\n```", }', {"code": "```py\nx\n```"}),
    ],
)
def test_json_accepts_prose_fences_and_raw_newlines(raw: str, expected: dict) -> None:
    """Prose before a fence and raw newlines in strings are common LLM output."""
    assert extract_json(raw) == expected


@pytest.mark.asyncio
async def test_markdown_preamble_is_sibling_of_level_two_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text before '##' headings must not become the parent of every section."""
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", lambda text: len(text))
    tree = await md_to_tree("Intro.\n\n## Install\nRun it.\n\n## Usage\nCall it.")
    assert [node["title"] for node in tree["structure"]] == ["Introduction", "Install", "Usage"]
    assert all("nodes" not in node for node in tree["structure"])
    assert tree["structure"][0]["text"] == "Intro."
