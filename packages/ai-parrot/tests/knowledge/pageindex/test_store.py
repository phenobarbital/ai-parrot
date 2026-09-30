"""Tests for parrot.knowledge.pageindex.store.JSONTreeStore."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from parrot.knowledge.pageindex.store import JSONTreeStore


@pytest.fixture
def store(tmp_path: Path) -> JSONTreeStore:
    return JSONTreeStore(tmp_path)


def test_save_load_roundtrip(store: JSONTreeStore):
    tree = {"doc_name": "demo", "structure": [{"title": "root", "node_id": "0000"}]}
    store.save("demo", tree)
    assert store.exists("demo")
    loaded = store.load("demo")
    assert loaded == tree


def test_list_names_sorted(store: JSONTreeStore):
    store.save("b_one", {"structure": []})
    store.save("a_two", {"structure": []})
    assert store.list_names() == ["a_two", "b_one"]


def test_list_names_ignores_unrelated_files(store: JSONTreeStore, tmp_path: Path):
    store.save("docs", {"structure": []})
    (tmp_path / "README.md").write_text("hi")
    (tmp_path / "not!a!valid!name.json").write_text("{}")
    assert store.list_names() == ["docs"]


def test_invalid_name_rejected(store: JSONTreeStore):
    with pytest.raises(ValueError):
        store.save("../escape", {"structure": []})
    with pytest.raises(ValueError):
        store.exists("with space")
    with pytest.raises(ValueError):
        store.load("")


def test_delete(store: JSONTreeStore):
    store.save("docs", {"structure": []})
    assert store.delete("docs") is True
    assert store.delete("docs") is False
    assert not store.exists("docs")


def test_atomic_write_cleans_temp_on_failure(store: JSONTreeStore, tmp_path: Path):
    boom = RuntimeError("simulated replace failure")
    with patch("parrot.knowledge.pageindex.store.os.replace", side_effect=boom):
        with pytest.raises(RuntimeError):
            store.save("docs", {"structure": []})
    leftover = [p.name for p in tmp_path.iterdir()]
    assert all(not name.endswith(".tmp") for name in leftover), leftover


def test_store_strips_node_markdown_on_save(store: JSONTreeStore, tmp_path: Path):
    tree = {
        "doc_name": "demo",
        "structure": [{"title": "root", "node_id": "0000"}],
        "_node_markdown": {"0000": "# leaked body"},
    }
    store.save("demo", tree)
    with (tmp_path / "demo.json").open() as f:
        loaded = json.load(f)
    assert "_node_markdown" not in loaded
    # And the in-memory dict passed in was not mutated.
    assert "_node_markdown" in tree


def test_save_overwrites_existing(store: JSONTreeStore, tmp_path: Path):
    store.save("docs", {"structure": [{"title": "v1"}]})
    store.save("docs", {"structure": [{"title": "v2"}]})
    with (tmp_path / "docs.json").open() as f:
        loaded = json.load(f)
    assert loaded["structure"][0]["title"] == "v2"


def test_json_store_rename_moves_file(store: JSONTreeStore, tmp_path: Path) -> None:
    """Preserve bytes and remove the old JSON name."""
    source_bytes = b'{"structure":["source"]}\n'
    (tmp_path / "source.json").write_bytes(source_bytes)

    store.rename("source", "destination")

    assert not (tmp_path / "source.json").exists()
    assert (tmp_path / "destination.json").read_bytes() == source_bytes


def test_json_store_rename_refuses_existing_dst(store: JSONTreeStore, tmp_path: Path) -> None:
    """Keep both JSON files intact on collision."""
    source_bytes = b'{"structure":["source"]}\n'
    destination_bytes = b'{"structure":["destination"]}\n'
    (tmp_path / "source.json").write_bytes(source_bytes)
    (tmp_path / "destination.json").write_bytes(destination_bytes)

    with pytest.raises(FileExistsError):
        store.rename("source", "destination")

    assert (tmp_path / "source.json").read_bytes() == source_bytes
    assert (tmp_path / "destination.json").read_bytes() == destination_bytes


def test_json_store_rename_invalid_or_missing_source(store: JSONTreeStore) -> None:
    """Reject unsafe names and absent source."""
    with pytest.raises(ValueError):
        store.rename("../source", "destination")
    with pytest.raises(ValueError):
        store.rename("source", "../destination")
    with pytest.raises(FileNotFoundError):
        store.rename("source", "destination")


def test_json_store_rename_preserves_source_on_replace_failure(
    store: JSONTreeStore, tmp_path: Path
) -> None:
    """Leave the source JSON intact when the filesystem move fails."""
    source_bytes = b'{"structure":["source"]}\n'
    (tmp_path / "source.json").write_bytes(source_bytes)

    with patch("parrot.knowledge.pageindex.store.os.replace", side_effect=OSError("boom")):
        with pytest.raises(OSError, match="boom"):
            store.rename("source", "destination")

    assert (tmp_path / "source.json").read_bytes() == source_bytes
    assert not (tmp_path / "destination.json").exists()
