"""Tests for `bookstore export-wiki` + namespace registration."""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError
from parrot.knowledge.bookstore.models import BookCard, BookRelation

_NOW = "2026-09-06T00:00:00+00:00"


def _card(book_id: str, **overrides) -> BookCard:
    data = {
        "book_id": book_id,
        "title": book_id.replace("-", " ").title(),
        "tree_name": book_id,
        "source_path": f"/books/{book_id}.md",
        "source_sha256": f"{book_id:0<64}"[:64],
        "source_format": "md",
        "added_at": _NOW,
    }
    data.update(overrides)
    return BookCard(**data)


@pytest.fixture
def locations(tmp_path) -> list[LibraryLocation]:
    return [
        LibraryLocation(scope="project", root=tmp_path / "proj" / "library"),
        LibraryLocation(scope="global", root=tmp_path / "glob" / "library"),
    ]


@pytest.fixture
def store_with_relations(locations) -> Bookstore:
    bookstore = Bookstore(locations)
    project = bookstore._catalog("project")
    for card in (
        _card("a", authors=["Author A"]),
        _card("b", authors=["Author A"]),
        _card("c", authors=["Author B"]),
    ):
        project.upsert(card)
    project.upsert_relations(
        [
            BookRelation(
                src_book_id="a",
                dst_book_id="b",
                rel="same_author",
                origin="deterministic",
                computed_at=_NOW,
            ),
            BookRelation(
                src_book_id="a",
                dst_book_id="c",
                rel="parallels",
                origin="llm",
                confidence=0.7,
                computed_at=_NOW,
            ),
        ]
    )
    return bookstore


@pytest.fixture
def git_root(tmp_path) -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    return root


@pytest.mark.asyncio
async def test_export_wiki_pages_and_edges(store_with_relations, tmp_path):
    from parrot.knowledge.wiki.store import SQLiteWikiStore

    out_dir = tmp_path / "wiki-out"
    result = await store_with_relations.export_wiki(out_dir, register=False)
    assert result["pages"] == 3
    assert result["edges"] == 2

    read_store = SQLiteWikiStore(out_dir / "wiki.db", read_only=True)
    pages = await read_store.dump_pages()
    assert len(pages) == 3
    assert {p["concept_id"] for p in pages} == {"book:a", "book:b", "book:c"}
    assert all(p["category"] == "book" for p in pages)

    edges = await read_store.dump_edges()
    assert len(edges) == 2
    by_pair = {(e["src"], e["dst"]): e["rel"] for e in edges}
    assert by_pair[("book:a", "book:b")] == "same_author"
    assert by_pair[("book:a", "book:c")] == "parallels"


@pytest.mark.asyncio
async def test_export_wiki_writes_graph_html(store_with_relations, tmp_path):
    out_dir = tmp_path / "wiki-out"
    result = await store_with_relations.export_wiki(out_dir, register=False)
    assert Path(result["html"]).is_file()
    assert Path(result["json"]).is_file()


@pytest.mark.asyncio
async def test_export_wiki_idempotent_rerun(store_with_relations, tmp_path):
    from parrot.knowledge.wiki.store import SQLiteWikiStore

    out_dir = tmp_path / "wiki-out"
    await store_with_relations.export_wiki(out_dir, register=False)

    # Drop a relation — the stale edge must not survive a re-export.
    store_with_relations._catalog("project").delete_relations(book_id="c")
    result = await store_with_relations.export_wiki(out_dir, register=False)
    assert result["edges"] == 1

    read_store = SQLiteWikiStore(out_dir / "wiki.db", read_only=True)
    edges = await read_store.dump_edges()
    assert len(edges) == 1


@pytest.mark.asyncio
async def test_export_wiki_registers_namespace_project(git_root, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(git_root.parent / "home"))
    locations = [LibraryLocation(scope="project", root=git_root / ".parrot" / "library")]
    bookstore = Bookstore(locations)
    catalog = bookstore._catalog("project")
    for card in (_card("a"), _card("b"), _card("c")):
        catalog.upsert(card)

    result = await bookstore.export_wiki(scope="project", register=True)

    wiki_json = git_root / ".parrot" / "wiki.json"
    assert wiki_json.is_file()
    data = json.loads(wiki_json.read_text(encoding="utf-8"))
    assert "bookstore" in data["namespaces"]
    assert data["namespaces"]["bookstore"]["store"] == str(Path(".parrot") / "library" / "wiki")
    assert result["registered_in"] == str(wiki_json)


@pytest.mark.asyncio
async def test_export_wiki_registers_namespace_global(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("PARROT_HOME", str(home))
    locations = [LibraryLocation(scope="global", root=tmp_path / "glob" / "library")]
    bookstore = Bookstore(locations)
    catalog = bookstore._catalog("global")
    for card in (_card("a"), _card("b"), _card("c")):
        catalog.upsert(card)

    result = await bookstore.export_wiki(scope="global", register=True)

    registry_path = home / "wikis.json"
    assert registry_path.is_file()
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    assert "bookstore" in data["namespaces"]
    assert Path(data["namespaces"]["bookstore"]["store"]).is_absolute()
    assert result["registered_in"] == str(registry_path)


@pytest.mark.asyncio
async def test_export_wiki_conflicting_namespace_refused(git_root, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(git_root.parent / "home"))
    from parrot.knowledge.wiki.project import (
        WikiNamespaceConfig,
        load_project_config,
        save_project_config,
    )

    config = load_project_config(git_root)
    config.namespaces["bookstore"] = WikiNamespaceConfig(
        store="/some/other/place",
        backend="sqlite",
    )
    save_project_config(git_root, config)

    locations = [LibraryLocation(scope="project", root=git_root / ".parrot" / "library")]
    bookstore = Bookstore(locations)
    catalog = bookstore._catalog("project")
    for card in (_card("a"), _card("b"), _card("c")):
        catalog.upsert(card)

    with pytest.raises(BookstoreError):
        await bookstore.export_wiki(scope="project", register=True)

    reloaded = load_project_config(git_root)
    assert reloaded.namespaces["bookstore"].store == "/some/other/place"


@pytest.mark.asyncio
async def test_export_wiki_no_register_flag(git_root, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(git_root.parent / "home"))
    locations = [LibraryLocation(scope="project", root=git_root / ".parrot" / "library")]
    bookstore = Bookstore(locations)
    catalog = bookstore._catalog("project")
    for card in (_card("a"), _card("b"), _card("c")):
        catalog.upsert(card)

    result = await bookstore.export_wiki(scope="project", register=False)

    assert result["registered_in"] is None
    assert not (git_root / ".parrot" / "wiki.json").exists()


@pytest.mark.asyncio
async def test_export_wiki_without_wiki_package(store_with_relations, monkeypatch, tmp_path):
    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name.startswith("parrot.knowledge.wiki"):
            raise ImportError("No module named 'parrot.knowledge.wiki'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)

    with pytest.raises(BookstoreError, match="wiki"):
        await store_with_relations.export_wiki(tmp_path / "out", register=False)

    # Catalog untouched by the failed export.
    assert store_with_relations._catalog("project").list_cards()


@pytest.mark.asyncio
async def test_export_wiki_out_outside_git_root_raises_clean_error(git_root, monkeypatch, tmp_path):
    """Regression (code review, FEAT-533): register_namespace's bare
    Path.relative_to(git_root) call raised an uncaught ValueError (raw
    traceback) instead of a BookstoreError/ClickException when --out
    pointed outside the repo."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    locations = [LibraryLocation(scope="project", root=git_root / ".parrot" / "library")]
    bookstore = Bookstore(locations)
    catalog = bookstore._catalog("project")
    for card in (_card("a"), _card("b"), _card("c")):
        catalog.upsert(card)

    outside_dir = tmp_path / "outside-the-repo"
    with pytest.raises(BookstoreError, match="outside the project git root"):
        await bookstore.export_wiki(outside_dir, scope="project", register=True)
