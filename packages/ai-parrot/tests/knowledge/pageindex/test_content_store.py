"""Tests for parrot.knowledge.pageindex.content_store.NodeContentStore."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.pageindex.content_store import NodeContentStore


@pytest.fixture
def store(tmp_path: Path) -> NodeContentStore:
    return NodeContentStore(tmp_path)


def test_node_content_store_roundtrip(store: NodeContentStore):
    store.save("docs", "0000", "# Hello\n\nWorld")
    assert store.has("docs", "0000")
    assert store.load("docs", "0000") == "# Hello\n\nWorld"


def test_load_missing_returns_none(store: NodeContentStore):
    assert store.load("docs", "0000") is None
    assert not store.has("docs", "0000")


def test_node_content_store_lru_eviction(tmp_path: Path):
    store = NodeContentStore(tmp_path, cache_size=2)
    store.save("docs", "0000", "alpha")
    store.save("docs", "0001", "beta")
    store.save("docs", "0002", "gamma")
    # Three saves with cache_size=2 → "0000" evicted from cache.
    # Cache state holds 0001 + 0002; touching 0000 must hit disk and refill.
    assert ("docs", "0000") not in store._cache
    assert store.load("docs", "0000") == "alpha"
    assert ("docs", "0000") in store._cache
    # And re-touching one of the others must still work.
    assert store.load("docs", "0001") == "beta"


def test_node_content_store_delete_node_invalidates_cache(store: NodeContentStore):
    store.save("docs", "0000", "alpha")
    assert store.load("docs", "0000") == "alpha"
    assert store.delete_node("docs", "0000") is True
    assert store.load("docs", "0000") is None
    # delete_node on a missing file returns False.
    assert store.delete_node("docs", "0000") is False


def test_node_content_store_delete_tree_clears_directory(store: NodeContentStore, tmp_path: Path):
    store.save("docs", "0000", "alpha")
    store.save("docs", "0001", "beta")
    store.save("docs", "0002", "gamma")
    count = store.delete_tree("docs")
    assert count == 3
    assert not (tmp_path / "docs").is_dir()
    # Cache for that tree must also be empty.
    assert all(key[0] != "docs" for key in store._cache)


def test_node_content_store_isolated_trees(store: NodeContentStore):
    store.save("a", "0000", "from-a")
    store.save("b", "0000", "from-b")
    assert store.load("a", "0000") == "from-a"
    assert store.load("b", "0000") == "from-b"


def test_node_content_store_list_node_ids(store: NodeContentStore):
    store.save("docs", "0002", "c")
    store.save("docs", "0000", "a")
    store.save("docs", "0001", "b")
    assert store.list_node_ids("docs") == ["0000", "0001", "0002"]
    # Foreign files in the tree dir are ignored.
    other = Path(store._dir / "docs" / "README.txt")
    other.write_text("notes")
    assert store.list_node_ids("docs") == ["0000", "0001", "0002"]


def test_node_content_store_loader_for_returns_closure(store: NodeContentStore):
    store.save("docs", "0000", "alpha")
    loader = store.loader_for("docs")
    assert loader("0000") == "alpha"
    assert loader("9999") is None


def test_node_content_store_validates_names(store: NodeContentStore):
    with pytest.raises(ValueError):
        store.save("../escape", "0000", "x")
    with pytest.raises(ValueError):
        store.save("docs", "../escape", "x")
    with pytest.raises(ValueError):
        store.save("with space", "0000", "x")


def test_node_content_store_overwrites_existing(store: NodeContentStore):
    store.save("docs", "0000", "v1")
    store.save("docs", "0000", "v2")
    assert store.load("docs", "0000") == "v2"
