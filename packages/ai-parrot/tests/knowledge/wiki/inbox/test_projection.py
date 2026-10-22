"""Focused FEAT-626 projection regression and failure-path tests."""

import os
from pathlib import Path

import pytest
import yaml

from parrot.knowledge.wiki.inbox.projection import render_doc_markdown, write_doc_markdown, write_inbox_index


def _page(cid: str = "doc:a/b", **kw: object) -> dict:
    page = {
        "concept_id": cid,
        "title": "Title",
        "category": "document",
        "summary": "sum",
        "body": "Hello body",
        "updated_at": "2026-01-01T00:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
        "content_hash": "abc",
    }
    page.update(kw)
    return page


def test_render_doc_markdown_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Equal page input yields identical output and ordered custom tags."""
    page = _page()
    before = dict(page)
    a = render_doc_markdown(page, [], ["x", "y", "x"])
    b = render_doc_markdown(page, [], ["x", "y", "x"])
    assert a.encode() == b.encode()
    assert page == before
    front = a.split("---\n")[1]
    assert yaml.safe_load(front)["tags"] == ["document", "x", "y"]
    assert yaml.safe_load(front)["content_hash"] == "abc"
    assert a.endswith("---\n\nHello body")


def test_write_doc_markdown_atomic_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Check category/flat-id path and absence of temporary files."""
    path = write_doc_markdown(tmp_path, _page(), [], ["t"])
    assert path.parent == tmp_path / "documents"
    assert path.suffix == ".md" and path.exists()
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_projection_write_failure_preserves_previous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject replacement failure and retain existing output without temp leaks."""
    path = write_doc_markdown(tmp_path, _page(), [], [])
    old = path.read_text()

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_doc_markdown(tmp_path, _page(body="new"), [], [])
    assert path.read_text() == old
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_index_is_sorted_and_contains_only_inbox_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify sorted relative links to supplied document pages."""
    pages = [_page("doc:z", title="Zed"), _page("doc:a", title="Aye")]
    idx = write_inbox_index(tmp_path, pages)
    text = idx.read_text()
    assert idx == tmp_path / "index.md"
    assert text.index("[Aye](documents/") < text.index("[Zed](documents/")
    assert text.count("## [") == 2
    assert [p.name for p in tmp_path.iterdir()] == ["index.md"]
