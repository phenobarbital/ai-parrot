"""Tests for relation sheets (``parrot.knowledge.bookstore.notebooks``) — FEAT-876 TASK-5480."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import LIBRARY_NOTEBOOK, Bookstore
from parrot.knowledge.bookstore.notebooks import apply_relation_sheets, relation_sheets

from .conftest import SAMPLE_MARKDOWN


@pytest.fixture
def locations(tmp_path) -> list[LibraryLocation]:
    return [
        LibraryLocation(scope="project", root=tmp_path / "proj" / "library"),
        LibraryLocation(scope="global", root=tmp_path / "glob" / "library"),
    ]


@pytest.fixture
def store(locations, fake_adapter) -> Bookstore:
    return Bookstore(locations, adapter=fake_adapter)


async def _add(store: Bookstore, tmp_path: Path, slug: str, *, scope: str = "project") -> str:
    path = tmp_path / f"{slug}.md"
    path.write_text(SAMPLE_MARKDOWN + f"\n{slug} unique sha.\n", encoding="utf-8")
    card, _ = await store.add_book(path, scope=scope, title=slug.replace("-", " ").title())
    return card.book_id


async def _sheet(
    store: Bookstore,
    anchors: list[Any],
    *,
    book_id: Optional[str] = None,
    scope: str = "project",
    title: str = "Sheet",
    body: str = "",
    **metadata: Any,
) -> str:
    notebook = await store.ensure_notebook(book_id, scope=scope)
    toolkit = await store._ready_toolkit(notebook.scope)
    added = await toolkit.add_node(notebook.tree_name, title=title, body=body)
    await toolkit.tag_node(notebook.tree_name, added["node_id"], metadata={"anchors": anchors, **metadata})
    return added["node_id"]


@pytest.mark.asyncio
async def test_relation_sheets_project_manual_edges(store, tmp_path):
    a = await _add(store, tmp_path, "alpha-book")
    b = await _add(store, tmp_path, "beta-book")
    c = await _add(store, tmp_path, "gamma-book")

    # Default rel → parallels, one symmetric edge per pair, body as rationale.
    await _sheet(
        store,
        [{"book_id": a}, {"book_id": b}, {"book_id": c}],
        body="These three books share a theme.",
    )
    # Directed rel: the FIRST anchor is the source, one edge per other book.
    await _sheet(store, [{"book_id": c}, {"book_id": a}, {"book_id": b}], rel="influenced_by")
    # Fewer than two distinct books → no relation.
    await _sheet(store, [{"book_id": a}, {"book_id": a, "node_id": "0001"}])
    # Sectors are classification, never relation sheets.
    await _sheet(store, [{"book_id": a}, {"book_id": b}], sector_code="171", title="Ethics")
    # Invalid rel → skipped (warning).
    await _sheet(store, [{"book_id": a}, {"book_id": b}], rel="best_friends")

    relations = await relation_sheets(store)
    assert all(r.origin == "manual" and r.weight == 1.0 for r in relations)
    parallels = [r for r in relations if r.rel == "parallels"]
    assert {frozenset((r.src_book_id, r.dst_book_id)) for r in parallels} == {
        frozenset((a, b)),
        frozenset((a, c)),
        frozenset((b, c)),
    }
    assert all(r.rationale == "These three books share a theme." for r in parallels)
    directed = [r for r in relations if r.rel == "influenced_by"]
    assert {(r.src_book_id, r.dst_book_id) for r in directed} == {(c, a), (c, b)}
    assert len(relations) == 5

    written = await apply_relation_sheets(store)
    assert written == 5
    catalog = store._catalog("project")
    stored = catalog.list_relations(c, rel="influenced_by")
    assert {(r.src_book_id, r.dst_book_id, r.origin) for r in stored} == {(c, a, "manual"), (c, b, "manual")}
    assert all(r.origin == "manual" for r in catalog.list_relations(a, rel="parallels"))


@pytest.mark.asyncio
async def test_relation_sheets_resolve_by_scope_and_book_notebooks(store, tmp_path):
    a = await _add(store, tmp_path, "alpha-book")
    b = await _add(store, tmp_path, "beta-book")
    g = await _add(store, tmp_path, "global-book", scope="global")

    # A sheet inside a BOOK notebook counts too; a cross-scope anchor resolves through its scope.
    await _sheet(store, [{"book_id": a}, {"book_id": g, "scope": "global"}], book_id=a, title="Cross scope")
    # A global book anchored with the default (project) scope is not a project book → ignored (S11).
    await _sheet(store, [{"book_id": b}, {"book_id": g}], title="Wrong scope")
    # Unknown book and malformed anchors are skipped without hiding the rest.
    await _sheet(store, [{"book_id": a}, {"book_id": "nope"}, "garbage", {"node_id": "x"}], title="Noise")

    relations = await relation_sheets(store)
    assert [(r.src_book_id, r.dst_book_id, r.rationale) for r in relations] == [(a, g, "Cross scope")]
    assert await relation_sheets(store, scope="global") == []

    # The edge lives in the DB of the scope that owns its src (project).
    assert await apply_relation_sheets(store) == 1
    assert store._catalog("project").list_relations(g)
    assert not store._catalog("global").list_relations(g)


@pytest.mark.asyncio
async def test_relation_sheets_library_notebook_and_rationale_truncation(store, tmp_path):
    a = await _add(store, tmp_path, "alpha-book")
    b = await _add(store, tmp_path, "beta-book")
    await _sheet(store, [{"book_id": a}, {"book_id": b}], body="x" * 2000, rel="contrasts_with")

    relations = await relation_sheets(store)
    assert store.library_notebook("project").book_id == LIBRARY_NOTEBOOK
    assert len(relations) == 1
    assert relations[0].rel == "contrasts_with"
    assert len(relations[0].rationale) == 500


@pytest.mark.asyncio
async def test_relation_sheets_without_notebooks(store, tmp_path):
    await _add(store, tmp_path, "alpha-book")
    assert await relation_sheets(store) == []
    assert await apply_relation_sheets(store) == 0
