"""Tests for parrot.knowledge.pageindex.content_store.NodeContentStore."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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


# ---- OKF dual-key / flattened concept_id tests (FEAT-238 / TASK-1559) ----


def test_flattened_concept_id_is_valid_node_id(store: NodeContentStore):
    """Flattened concept_ids (slashes → dashes) satisfy _NODE_ID_RE."""
    # ``flatten_concept_id_for_filename`` converts 'controls/nist-ir-4' →
    # 'controls--nist-ir-4', which is [A-Za-z0-9_-]+ and ≤ 64 chars.
    flat_id = "controls--nist-ir-4"
    store.save("tree", flat_id, "body")
    assert store.load("tree", flat_id) == "body"


def test_store_save_and_load_by_flattened_concept_id(store: NodeContentStore):
    """Save/load round-trip works for flattened concept_id keys."""
    store.save("tree", "playbooks--aws-ir", "content here")
    assert store.load("tree", "playbooks--aws-ir") == "content here"
    assert store.has("tree", "playbooks--aws-ir")


def test_loader_for_accepts_flattened_concept_id(store: NodeContentStore):
    """loader_for closure loads flattened concept_id keyed content."""
    store.save("tree", "controls--nist-ir-4", "sidecar body")
    loader = store.loader_for("tree")
    result = loader("controls--nist-ir-4")
    assert result == "sidecar body"


def test_loader_for_returns_none_for_missing_concept_id(store: NodeContentStore):
    """loader_for returns None for an unrecognised flattened concept_id."""
    loader = store.loader_for("tree")
    assert loader("missing--concept") is None


def test_flattened_concept_id_listed_in_node_ids(store: NodeContentStore):
    """list_node_ids includes flattened concept_id keyed sidecars."""
    store.save("tree", "section--intro", "body")
    store.save("tree", "0001", "node body")
    ids = store.list_node_ids("tree")
    assert "section--intro" in ids
    assert "0001" in ids


def test_delete_node_by_flattened_concept_id(store: NodeContentStore):
    """delete_node works for flattened concept_id keys."""
    store.save("tree", "playbooks--aws-ir", "content")
    assert store.delete_node("tree", "playbooks--aws-ir") is True
    assert store.load("tree", "playbooks--aws-ir") is None


def test_content_store_rename_tree_moves_dir_and_evicts_cache(store: NodeContentStore, tmp_path: Path) -> None:
    """Move nested content and invalidate both cache names."""
    store.save("source", "0000", "source markdown")
    embeddings_dir = tmp_path / "source" / "embeddings"
    embeddings_dir.mkdir()
    embedding_bytes = b"embedding data"
    (embeddings_dir / "vectors.bin").write_bytes(embedding_bytes)
    assert store.load("source", "0000") == "source markdown"
    store._cache_put(("destination", "0000"), "stale destination cache")

    assert store.rename_tree("source", "destination") is True

    assert not (tmp_path / "source").exists()
    assert all(key[0] not in {"source", "destination"} for key in store._cache)
    assert store.load("destination", "0000") == "source markdown"
    assert (tmp_path / "destination" / "embeddings" / "vectors.bin").read_bytes() == embedding_bytes


def test_content_store_rename_tree_missing_src_dir_returns_false(store: NodeContentStore) -> None:
    """Treat absent content as a no-op."""
    store._cache_put(("source", "0000"), "stale source cache")
    store._cache_put(("destination", "0000"), "stale destination cache")

    assert store.rename_tree("source", "destination") is False
    assert all(key[0] not in {"source", "destination"} for key in store._cache)
    with pytest.raises(ValueError):
        store.rename_tree("../source", "destination")
    with pytest.raises(ValueError):
        store.rename_tree("source", "../destination")


def test_content_store_rename_tree_refuses_existing_dst(store: NodeContentStore, tmp_path: Path) -> None:
    """Preserve both directories on collision."""
    store.save("source", "0000", "source markdown")
    store.save("destination", "0000", "destination markdown")
    source_path = tmp_path / "source" / "0000.md"
    destination_path = tmp_path / "destination" / "0000.md"

    with pytest.raises(FileExistsError):
        store.rename_tree("source", "destination")

    assert source_path.read_text(encoding="utf-8") == "source markdown"
    assert destination_path.read_text(encoding="utf-8") == "destination markdown"


def test_content_store_rename_tree_preserves_source_on_replace_failure(store: NodeContentStore, tmp_path: Path) -> None:
    """Leave the source directory intact when the filesystem move fails."""
    store.save("source", "0000", "source markdown")

    with patch("parrot.knowledge.pageindex.content_store.os.replace", side_effect=OSError("boom")):
        with pytest.raises(OSError, match="boom"):
            store.rename_tree("source", "destination")

    assert (tmp_path / "source" / "0000.md").read_text(encoding="utf-8") == "source markdown"
    assert not (tmp_path / "destination").exists()
