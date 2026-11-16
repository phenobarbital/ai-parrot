"""FEAT-876 M3 — LibraryPageIndexToolkit routing and write policy."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from parrot.knowledge.bookstore.config import resolve_locations
from parrot.knowledge.bookstore.library import LIBRARY_NOTEBOOK, NOTEBOOK_SUFFIX, Bookstore
from parrot.knowledge.bookstore.pageindex import LibraryPageIndexToolkit
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, PageIndexWriteDenied

from .conftest import SAMPLE_MARKDOWN

GLOBAL_MARKDOWN = (
    "# Global Treatise\n\n"
    "An introduction to the global treatise with enough descriptive text to clear the thinning "
    "threshold of the markdown parser and keep the root visible.\n\n"
    "## Part One\n"
    "Part one covers stoic ethics and the discipline of assent with plenty of descriptive content.\n\n"
    "## Part Two\n"
    "Part two covers epicurean physics and the swerve of atoms with the remaining example content.\n"
)

FREE_DOC = "# Field Notes\n\n## Edelweiss\nAll about edelweiss flowers in the high alpine meadows.\n"

#: Every write tool of the facade with minimal arguments (``_authorize`` runs before any argument is used).
_WRITE_CALLS: list[tuple[str, dict]] = [
    ("delete_tree", {}),
    ("vacuum_tree", {}),
    ("optimize", {"apply": True}),
    ("index_segments", {}),
    ("insert_markdown", {"markdown": "# X\n\nbody"}),
    ("insert_ebook", {"sections": []}),
    ("insert_content", {"content": "x"}),
    ("import_file", {"file_path": "/nonexistent.md"}),
    ("import_pdf", {"pdf_path": "/nonexistent.pdf"}),
    ("import_folder", {"folder_path": "/nonexistent"}),
    ("tag_node", {"node_id": "0000", "metadata": {"x": 1}}),
    ("add_node", {"title": "Note"}),
    ("update_node", {"node_id": "0000", "title": "New"}),
    ("update_node_content", {"node_id": "0000", "body": "x"}),
    ("delete_node", {"node_id": "0000"}),
]


@pytest.fixture
def two_scope_locations(tmp_path, monkeypatch):
    """project + global LibraryLocation under tmp_path; PARROT_LIBRARY_DIR / PARROT_HOME monkeypatched."""
    monkeypatch.setenv("PARROT_LIBRARY_DIR", str(tmp_path / "proj" / "library"))
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    locations = resolve_locations(tmp_path)
    assert [loc.scope for loc in locations] == ["project", "global"]
    return locations


@pytest.fixture
async def library(tmp_path, two_scope_locations, fake_adapter):
    """A project book and a global book, ingested through Bookstore (the only catalog writer)."""
    project_md = tmp_path / "synthetic-handbook.md"
    project_md.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    global_md = tmp_path / "global-treatise.md"
    global_md.write_text(GLOBAL_MARKDOWN, encoding="utf-8")
    store = Bookstore(two_scope_locations, adapter=fake_adapter)
    project_card, _ = await store.add_book(project_md)
    global_card, _ = await store.add_book(global_md, scope="global")
    return store, project_card, global_card


@pytest.fixture
def facade(tmp_path, two_scope_locations) -> LibraryPageIndexToolkit:
    return LibraryPageIndexToolkit(project_root=tmp_path)


def _tool_names(toolkit) -> set[str]:
    return {tool.name for tool in toolkit.get_tools()}


def test_facade_serves_same_names_as_pageindex_toolkit(tmp_path, facade) -> None:
    """AC-1: the served set is PageIndex's plus pageindex_list_library_trees, with the same parameters."""
    plain = PageIndexToolkit(storage_dir=tmp_path / "plain")
    assert _tool_names(facade) == _tool_names(plain) | {"pageindex_list_library_trees"}
    assert facade.llm_dependent_tools == PageIndexToolkit.llm_dependent_tools
    for tool in plain.get_tools():
        method = tool.name[len("pageindex_") :]
        ours = set(inspect.signature(getattr(facade, method)).parameters)
        theirs = set(inspect.signature(getattr(plain, method)).parameters)
        if method == "create_tree":
            assert ours == theirs | {"scope"}
        else:
            assert ours == theirs, method
        assert getattr(facade, method).__doc__, method


@pytest.mark.asyncio
async def test_facade_routes_global_tree(library, facade) -> None:
    store, project_card, global_card = library
    scope, card, kind, toolkit = facade._resolve(global_card.tree_name)
    assert (scope, kind) == ("global", "book")
    assert card is not None and card.book_id == global_card.book_id
    assert toolkit is facade._store._toolkit("global")
    tree = await facade.get_tree(global_card.tree_name)
    assert tree["structure"]
    scope, _, kind, _ = facade._resolve(project_card.tree_name)
    assert (scope, kind) == ("project", "book")


@pytest.mark.asyncio
@pytest.mark.parametrize("op, kwargs", _WRITE_CALLS)
async def test_facade_denies_book_tree_with_hint(library, facade, op, kwargs) -> None:
    """AC-2: every write tool on a catalogued book is refused with the ``<id>_notes`` hint; the tree is untouched."""
    _, project_card, global_card = library
    for card in (project_card, global_card):
        before = await facade.get_generation(card.tree_name)
        with pytest.raises(PageIndexWriteDenied) as excinfo:
            await getattr(facade, op)(card.tree_name, **kwargs)
        assert f"{card.book_id}{NOTEBOOK_SUFFIX}" in str(excinfo.value)
        assert await facade.get_generation(card.tree_name) == before


@pytest.mark.asyncio
async def test_facade_optimize_plan_on_book_is_a_read(library, facade, monkeypatch) -> None:
    """optimize(apply=False) only plans: the policy is consulted only for apply=True."""
    _, project_card, _ = library
    calls: list[tuple] = []

    async def fake_optimize(self, tree_name, *args, **kwargs):
        calls.append((tree_name, kwargs))
        return {"planned": True}

    monkeypatch.setattr(PageIndexToolkit, "optimize", fake_optimize)
    assert await facade.optimize(project_card.tree_name, apply=False) == {"planned": True}
    assert calls and calls[0][0] == project_card.tree_name


@pytest.mark.asyncio
async def test_facade_denies_create_and_rename_onto_book(library, facade) -> None:
    _, project_card, _ = library
    with pytest.raises(PageIndexWriteDenied):
        await facade.create_tree(project_card.tree_name)
    with pytest.raises(PageIndexWriteDenied):
        await facade.rename_tree(project_card.tree_name, "free-copy")


@pytest.mark.asyncio
async def test_facade_denies_rename_of_notebook(library, facade) -> None:
    """Catalogued notebook: rename/delete refused; node ops allowed."""
    store, project_card, _ = library
    notebook = await store.ensure_notebook(project_card.book_id)
    assert notebook.kind == "notes"
    with pytest.raises(PageIndexWriteDenied):
        await facade.rename_tree(notebook.tree_name, "elsewhere")
    with pytest.raises(PageIndexWriteDenied):
        await facade.delete_tree(notebook.tree_name)
    added = await facade.add_node(notebook.tree_name, title="Reading note", body="An observation.")
    await facade.tag_node(notebook.tree_name, added["node_id"], metadata={"note_kind": "note"})
    await facade.update_node(notebook.tree_name, added["node_id"], title="Renamed note")
    await facade.delete_node(notebook.tree_name, added["node_id"])
    assert notebook.tree_name in await facade.list_trees()


@pytest.mark.asyncio
async def test_facade_rename_authorizes_both_endpoints(library, facade) -> None:
    """S4: free → book name, book → free name and free → notebook name are refused."""
    _, project_card, global_card = library
    await facade.create_tree("scratch")
    with pytest.raises(PageIndexWriteDenied):
        await facade.rename_tree("scratch", project_card.tree_name, overwrite=True)
    with pytest.raises(PageIndexWriteDenied):
        await facade.rename_tree("scratch", global_card.tree_name, overwrite=True)
    with pytest.raises(PageIndexWriteDenied):
        await facade.rename_tree(project_card.tree_name, "stolen")
    with pytest.raises(PageIndexWriteDenied):
        await facade.rename_tree("scratch", f"{project_card.book_id}{NOTEBOOK_SUFFIX}")
    with pytest.raises(PageIndexWriteDenied):
        await facade.rename_tree("scratch", LIBRARY_NOTEBOOK)
    # Cross-scope rename onto an existing tree of the other library is refused.
    await facade.create_tree("elsewhere", scope="global")
    with pytest.raises(PageIndexWriteDenied):
        await facade.rename_tree("scratch", "elsewhere", overwrite=True)
    # free → free inside one scope is allowed.
    result = await facade.rename_tree("scratch", "scratch-2")
    assert result["dst"] == "scratch-2"
    assert "scratch-2" in await facade.list_trees() and "scratch" not in await facade.list_trees()


@pytest.mark.asyncio
async def test_facade_classifies_unregistered_notebook_by_name(library, facade) -> None:
    """S2: ``<book>_notes`` with no catalog row is already a notebook; the facade never writes the catalog."""
    store, project_card, global_card = library
    for card, scope in ((project_card, "project"), (global_card, "global")):
        name = f"{card.book_id}{NOTEBOOK_SUFFIX}"
        await facade.create_tree(name, scope=scope)
        assert store._catalog(scope).get(name) is None
        resolved_scope, resolved_card, kind, _ = facade._resolve(name)
        assert (resolved_scope, resolved_card, kind) == (scope, None, "notes")
        with pytest.raises(PageIndexWriteDenied):
            await facade.rename_tree(name, "renamed-notes")
        with pytest.raises(PageIndexWriteDenied):
            await facade.delete_tree(name)
        added = await facade.add_node(name, title="Footnote", body="Body")
        await facade.tag_node(name, added["node_id"], metadata={"note_kind": "footnote"})
        # Still no row: lazy registration belongs to Bookstore's read side.
        assert store._catalog(scope).get(name) is None
    # ``_library_notes`` is a notebook by name in either scope.
    await facade.create_tree(LIBRARY_NOTEBOOK, scope="global")
    assert facade._resolve(LIBRARY_NOTEBOOK)[:3] == ("global", None, "notes")
    with pytest.raises(PageIndexWriteDenied):
        await facade.delete_tree(LIBRARY_NOTEBOOK)


@pytest.mark.asyncio
async def test_facade_book_notebook_scope_is_the_books(library, facade) -> None:
    _, _, global_card = library
    with pytest.raises(PageIndexWriteDenied):
        await facade.create_tree(f"{global_card.book_id}{NOTEBOOK_SUFFIX}", scope="project")
    with pytest.raises(ValueError):
        await facade.create_tree("anything", scope="nowhere")


@pytest.mark.asyncio
async def test_facade_reserved_names_hidden_and_denied(library, facade) -> None:
    store, _, _ = library
    reserved = "draft--staging-123"
    toolkit = await store._ready_toolkit("project")
    await toolkit.create_tree(reserved)
    assert reserved not in await facade.list_trees()
    assert reserved not in {entry["tree_name"] for entry in await facade.list_library_trees()}
    with pytest.raises(PageIndexWriteDenied):
        await facade.add_node(reserved, title="x")
    with pytest.raises(PageIndexWriteDenied):
        await facade.create_tree("x--replaced-1")


@pytest.mark.asyncio
async def test_facade_no_llm_filtering_matches_pageindex(tmp_path, two_scope_locations, monkeypatch) -> None:
    """S7: without ``llm:`` the factory serves the same set as the plain server; search/retrieve are BM25-only."""
    pytest.importorskip("bm25s")
    from parrot.mcp.toolkit_seed import seed_toolkit_sections
    from parrot.mcp.toolkit_server import create_toolkit_mcp_server

    root = tmp_path / "repo"
    root.mkdir()
    seed_toolkit_sections(root, ["pageindex", "pageindex-library"])
    plain = create_toolkit_mcp_server("pageindex", root)
    library_server = create_toolkit_mcp_server("pageindex-library", root)
    assert set(library_server.tools) == set(plain.tools) | {"pageindex_list_library_trees"}
    assert not set(library_server.tools) & PageIndexToolkit.llm_dependent_tools

    facade = library_server._owned_toolkit
    assert isinstance(facade, LibraryPageIndexToolkit)
    assert facade._store.has_llm is False
    await facade.create_tree("guide")
    await facade.insert_markdown("guide", FREE_DOC)
    hits = await facade.search("guide", "edelweiss")
    assert hits and all(hit["source"] == "bm25" for hit in hits)
    text = await facade.retrieve("guide", "edelweiss")
    assert "edelweiss" in text.lower()


@pytest.mark.asyncio
async def test_facade_retrieve_is_bounded(facade) -> None:
    pytest.importorskip("bm25s")
    facade._max_result_chars = 60
    await facade.create_tree("long")
    body = "\n\n".join(f"Paragraph {i} about edelweiss in the alpine meadows." for i in range(20))
    await facade.insert_markdown("long", f"# Long\n\n## Edelweiss\n{body}\n")
    text = await facade.retrieve("long", "edelweiss")
    assert "[truncated:" in text and "lower top_k or narrow the query]" in text


@pytest.mark.asyncio
async def test_facade_list_trees_schema_unchanged(library, facade) -> None:
    """S6: list_trees is list[str]; list_library_trees carries scope and kind."""
    store, project_card, global_card = library
    await store.ensure_notebook(project_card.book_id)
    await facade.create_tree(f"{global_card.book_id}{NOTEBOOK_SUFFIX}", scope="global")  # unregistered notebook
    await facade.create_tree("scratch")
    names = await facade.list_trees()
    assert isinstance(names, list) and all(isinstance(name, str) for name in names)
    assert names == sorted(set(names))
    assert {project_card.tree_name, global_card.tree_name, "scratch"} <= set(names)
    listing = {(e["tree_name"], e["scope"]): e["kind"] for e in await facade.list_library_trees()}
    assert all(set(e) == {"tree_name", "scope", "kind"} for e in await facade.list_library_trees())
    assert listing[(project_card.tree_name, "project")] == "book"
    assert listing[(global_card.tree_name, "global")] == "book"
    assert listing[(f"{project_card.book_id}{NOTEBOOK_SUFFIX}", "project")] == "notes"
    assert listing[(f"{global_card.book_id}{NOTEBOOK_SUFFIX}", "global")] == "notes"
    assert listing[("scratch", "project")] == "free"


@pytest.mark.asyncio
async def test_facade_allows_free_tree(library, facade) -> None:
    """An uncatalogued tree is fully writable (structural and node ops)."""
    await facade.create_tree("scratch", doc_name="Scratch")
    assert facade._resolve("scratch")[2] == "free"
    await facade.insert_markdown("scratch", FREE_DOC)
    added = await facade.add_node("scratch", title="Extra", body="More text.")
    await facade.update_node_content("scratch", added["node_id"], "Changed text.")
    await facade.tag_node("scratch", added["node_id"], categories=["misc"])
    await facade.delete_node("scratch", added["node_id"])
    await facade.vacuum_tree("scratch")
    await facade.rename_tree("scratch", "scratch-renamed")
    removed = await facade.delete_tree("scratch-renamed")
    assert removed["tree_removed"] is True
    # A global free tree is routed to the global library.
    await facade.create_tree("global-scratch", scope="global")
    assert facade._resolve("global-scratch")[0] == "global"
    await facade.add_node("global-scratch", title="Note")


@pytest.mark.asyncio
async def test_mcp_write_then_bookstore_read(library, facade) -> None:
    """AC-8: a note written through the facade appears in Bookstore.read_section in the same process."""
    store, project_card, _ = library
    node_id = project_card.toc[0].node_id
    notebook = f"{project_card.book_id}{NOTEBOOK_SUFFIX}"
    await facade.create_tree(notebook)
    added = await facade.add_node(notebook, title="Footnote", body="A virtual footnote.")
    await facade.tag_node(
        notebook,
        added["node_id"],
        metadata={"note_kind": "footnote", "anchors": [{"book_id": project_card.book_id, "node_id": node_id}]},
    )
    section = store.read_section(project_card.book_id, node_id)
    assert [note["node_id"] for note in section["annotations"]] == [added["node_id"]]
    assert section["annotations"][0]["note_tree"] == notebook


@pytest.mark.asyncio
async def test_concurrent_notebook_writes_and_reads(library, facade) -> None:
    """FEAT-876 §4 / S12: parallel creators and readers leave exactly one ``kind=notes`` row per notebook."""
    import asyncio

    store, project_card, _ = library
    node_id = project_card.toc[0].node_id
    notebook = f"{project_card.book_id}{NOTEBOOK_SUFFIX}"

    async def create() -> None:
        try:
            await facade.create_tree(notebook)
        except ValueError:
            pass  # a racing creator won; the tree exists

    async def read() -> None:
        await asyncio.to_thread(store.read_section, project_card.book_id, node_id)
        await asyncio.to_thread(store.notebook_for, project_card.book_id)

    await asyncio.gather(
        *(create() for _ in range(4)), *(read() for _ in range(8)), store.ensure_notebook(project_card.book_id)
    )
    notes = [c for c in store._catalog("project").list_cards(kind="notes") if c.tree_name == notebook]
    assert len(notes) == 1 and notes[0].notes_for == project_card.book_id
    assert all(c.kind == "book" for c in store.list_books())


@pytest.mark.asyncio
async def test_project_and_global_lookups_under_concurrency(library, facade) -> None:
    """FEAT-876 S11: concurrent reads resolve annotations through each book's own scope only."""
    import asyncio

    store, project_card, global_card = library
    for card, scope in ((project_card, "project"), (global_card, "global")):
        notebook = await store.ensure_notebook(card.book_id, scope=scope)
        toolkit = await store._ready_toolkit(scope)
        added = await toolkit.add_node(notebook.tree_name, title=f"note-{scope}", body=scope)
        await toolkit.tag_node(
            notebook.tree_name,
            added["node_id"],
            metadata={"anchors": [{"book_id": card.book_id, "scope": scope, "node_id": card.toc[0].node_id}]},
        )

    async def notes(card):
        section = await asyncio.to_thread(store.read_section, card.book_id, card.toc[0].node_id)
        return [n["title"] for n in section["annotations"]]

    results = await asyncio.gather(*(notes(project_card) for _ in range(6)), *(notes(global_card) for _ in range(6)))
    assert results[:6] == [["note-project"]] * 6
    assert results[6:] == [["note-global"]] * 6


@pytest.mark.asyncio
async def test_unknown_tree_probe_has_no_side_effects(tmp_path, two_scope_locations) -> None:
    """Reading a tree that exists nowhere raises and creates no scope directory."""
    facade = LibraryPageIndexToolkit(project_root=tmp_path)
    before = sorted(p.name for p in tmp_path.rglob("*"))
    with pytest.raises(FileNotFoundError):
        await facade.search("no-such-tree", "anything")
    assert sorted(p.name for p in tmp_path.rglob("*")) == before
