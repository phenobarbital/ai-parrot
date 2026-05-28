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
