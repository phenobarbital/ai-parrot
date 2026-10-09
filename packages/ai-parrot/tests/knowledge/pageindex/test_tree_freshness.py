"""FEAT-647 / TASK-4181 — PageIndexToolkit reloads trees rewritten on disk."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.pageindex.toolkit import PageIndexToolkit


def _adapter() -> MagicMock:
    a = MagicMock()
    a.model = "heavy"
    a.client = MagicMock()
    a.client.ask = AsyncMock()
    a.client.default_model = "test-model"
    return a


def _rewrite(path: Path, tree: dict) -> None:
    """Rewrite a tree file the way another process would, bumping mtime."""
    path.write_text(json.dumps(tree), encoding="utf-8")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


async def test_reload_after_external_rewrite(tmp_path):
    tk = PageIndexToolkit(_adapter(), storage_dir=tmp_path)
    await tk.create_tree("book", doc_name="v1")
    assert tk._load_tree("book")["doc_name"] == "v1"
    tk._search["book"] = object()
    _rewrite(tmp_path / "book.json", {"doc_name": "v2", "structure": []})
    assert tk._load_tree("book")["doc_name"] == "v2"
    assert "book" not in tk._search


async def test_second_instance_sees_update(tmp_path):
    a = PageIndexToolkit(_adapter(), storage_dir=tmp_path)
    b = PageIndexToolkit(_adapter(), storage_dir=tmp_path)
    await a.create_tree("book", doc_name="v1")
    assert b._load_tree("book")["doc_name"] == "v1"
    _rewrite(tmp_path / "book.json", {"doc_name": "v2", "structure": []})
    assert b._load_tree("book")["doc_name"] == "v2"


async def test_batch_keeps_cached_tree(tmp_path):
    tk = PageIndexToolkit(_adapter(), storage_dir=tmp_path)
    await tk.create_tree("book", doc_name="v1")
    tk._load_tree("book")
    async with tk._batch("book"):
        _rewrite(tmp_path / "book.json", {"doc_name": "external", "structure": []})
        assert tk._load_tree("book")["doc_name"] == "v1"


async def test_own_write_does_not_reload(tmp_path):
    tk = PageIndexToolkit(_adapter(), storage_dir=tmp_path)
    await tk.create_tree("book", doc_name="v1")
    first = tk._load_tree("book")
    first["doc_name"] = "v1b"
    tk._persist("book")
    assert tk._load_tree("book") is first


async def test_missing_and_delete(tmp_path):
    tk = PageIndexToolkit(_adapter(), storage_dir=tmp_path)
    with pytest.raises(KeyError):
        tk._load_tree("nope")
    await tk.create_tree("book", doc_name="v1")
    assert "book" in tk._tree_sigs
    await tk.delete_tree("book")
    assert "book" not in tk._tree_sigs
    with pytest.raises(KeyError):
        tk._load_tree("book")
