"""Tests for the Bookstore manager (ingestion + read surface)."""

from __future__ import annotations

import asyncio
import builtins
import os
import time
from pathlib import Path

import pytest

from parrot.knowledge.bookstore.carding import disambiguate_title
from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import (
    LIBRARY_NOTEBOOK,
    NOTEBOOK_SUFFIX,
    REPLACED_MARKER,
    _STAGING_MARKER,
    _STAGING_MAX_AGE_S,
    Bookstore,
    BookstoreError,
    notebook_tree_name,
)
from parrot.knowledge.bookstore.models import (
    BookCommunity,
    BookRelation,
    CardDraft,
    RelationJudgement,
    REL_WEIGHTS,
    TocEntry,
)

from .conftest import SAMPLE_MARKDOWN


@pytest.fixture
def locations(tmp_path) -> list[LibraryLocation]:
    return [
        LibraryLocation(scope="project", root=tmp_path / "proj" / "library"),
        LibraryLocation(scope="global", root=tmp_path / "glob" / "library"),
    ]


@pytest.fixture
def book_md(tmp_path) -> Path:
    path = tmp_path / "synthetic-handbook.md"
    path.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    return path


@pytest.fixture
def store(locations, fake_adapter) -> Bookstore:
    return Bookstore(locations, adapter=fake_adapter)


@pytest.fixture
def store_no_llm(locations) -> Bookstore:
    return Bookstore(locations)


def test_toolkit_receives_grace(store: Bookstore) -> None:
    """Use the staging retention window for generation garbage collection."""
    assert store._toolkit("project")._generation_grace_s == _STAGING_MAX_AGE_S


@pytest.mark.asyncio
async def test_add_book_markdown_with_llm(store, book_md, locations):
    card, status = await store.add_book(book_md)
    assert status == "added"
    assert card.book_id == "synthetic-handbook"
    assert card.card_origin == "llm"
    assert card.title == "Synthetic Handbook"
    assert card.authors == ["Ada Example"]
    assert "async python" in card.topics
    assert card.chapter_count >= 1
    assert card.toc_digest
    # Tree JSON + catalog row exist on disk in the project scope.
    assert (locations[0].trees_dir / "synthetic-handbook.json").is_file()
    assert (locations[0].db_path).is_file()


@pytest.mark.asyncio
async def test_add_book_changed_content_same_path_updates_in_place(store, book_md):
    card1, status1 = await store.add_book(book_md)
    book_md.write_text(SAMPLE_MARKDOWN + "\n## New chapter\n\nChanged content.\n", encoding="utf-8")
    card2, status2 = await store.add_book(book_md)
    assert (status1, status2) == ("added", "updated")
    assert card2.book_id == card1.book_id
    assert card2.source_sha256 != card1.source_sha256
    assert [c.book_id for c in store.list_books()] == [card1.book_id]
    assert store.get_toc(card2.book_id)


@pytest.mark.asyncio
async def test_add_book_same_bytes_other_path_is_skipped(store, book_md, tmp_path):
    card1, _ = await store.add_book(book_md)
    other = tmp_path / "copy.md"
    other.write_bytes(book_md.read_bytes())
    card2, status2 = await store.add_book(other)
    assert status2 == "skipped"
    assert card2.book_id == card1.book_id
    assert card2.source_path == str(book_md.resolve())


@pytest.mark.asyncio
async def test_reindex_invalidates_relations_and_communities(store, book_md, tmp_path):
    card_a, _ = await store.add_book(book_md)
    other = tmp_path / "other-book.md"
    other.write_text(SAMPLE_MARKDOWN + "\n## Other\n\nDifferent bytes.\n", encoding="utf-8")
    card_b, _ = await store.add_book(other)
    a, b = card_a.book_id, card_b.book_id
    assert a != b
    catalog = store._catalog("project")
    catalog.upsert_relations(
        [
            BookRelation(
                src_book_id=a,
                dst_book_id=b,
                rel="parallels",
                origin="llm",
                confidence=0.7,
                weight=REL_WEIGHTS["parallels"],
                computed_at="2026-09-06T00:00:00+00:00",
            )
        ]
    )
    catalog.record_judgements(a, [RelationJudgement(dst_book_id=b, rel="parallels", confidence=0.7)])
    catalog.upsert_communities(
        [
            BookCommunity(
                community_id="c1",
                label="Pair",
                label_origin="derived",
                algorithm="leiden",
                size=2,
                cohesion=1.0,
                centroid_book_id=a,
                member_book_ids=[a, b],
                computed_at="2026-09-06T00:00:00+00:00",
            )
        ]
    )
    assert store.related_books(a)
    assert catalog.judged_pairs(a) == {b}
    assert store.communities()

    book_md.write_text(SAMPLE_MARKDOWN + "\n## Changed\n\nNew content.\n", encoding="utf-8")
    _, status = await store.add_book(book_md)
    assert status == "updated"
    assert store.related_books(a) == []
    assert catalog.judged_pairs(a) == set()
    assert store.communities() == []


@pytest.mark.asyncio
async def test_add_folder_changed_file_updates_not_duplicates(store, tmp_path):
    root = tmp_path / "books"
    root.mkdir()
    (root / "one.md").write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    (root / "two.md").write_text(SAMPLE_MARKDOWN + "\n## Two\n\nSecond.\n", encoding="utf-8")
    await store.add_folder(root)
    (root / "two.md").write_text(SAMPLE_MARKDOWN + "\n## Two\n\nSecond, edited.\n", encoding="utf-8")
    out = await store.add_folder(root)
    assert sorted(r["status"] for r in out["results"]) == ["skipped", "updated"]
    assert len(store.list_books()) == 2


@pytest.mark.asyncio
async def test_add_book_sha_skip_and_force(store, book_md):
    card1, status1 = await store.add_book(book_md)
    card2, status2 = await store.add_book(book_md)
    assert (status1, status2) == ("added", "skipped")
    assert card2.book_id == card1.book_id
    _, status3 = await store.add_book(book_md, force=True)
    assert status3 == "updated"


@pytest.mark.asyncio
async def test_add_book_no_llm_fallback_card(store_no_llm, book_md):
    card, status = await store_no_llm.add_book(book_md)
    assert status == "added"
    assert card.card_origin == "fallback"
    assert card.title == "Synthetic Handbook"  # de-slugified filename
    assert card.topics  # top-level chapter titles


@pytest.mark.asyncio
async def test_add_book_manual_overrides(store, book_md):
    card, _ = await store.add_book(book_md, title="My Handbook", authors=["Me"], topics=["testing"])
    assert card.card_origin == "manual"
    assert (card.title, card.authors, card.topics) == (
        "My Handbook",
        ["Me"],
        ["testing"],
    )
    assert card.book_id == "my-handbook"


@pytest.mark.asyncio
async def test_add_book_txt_requires_llm(store_no_llm, tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("plain text", encoding="utf-8")
    with pytest.raises(BookstoreError, match="LLM"):
        await store_no_llm.add_book(txt)


@pytest.mark.asyncio
async def test_add_book_unreadable_pdf(store_no_llm, tmp_path):
    """An unreadable PDF raises BookstoreError naming the file."""
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(BookstoreError, match="Cannot index book.pdf"):
        await store_no_llm.add_book(pdf)
    assert store_no_llm.list_books() == []


def _headed_pdf(path: Path) -> Path:
    """Create a three-page PDF with bookmarks and visible headings."""
    import pymupdf

    doc = pymupdf.open()
    try:
        for page_number in range(1, 4):
            page = doc.new_page()
            page.insert_text((72, 100), f"Chapter {page_number}", fontsize=16, fontname="hebo")
            page.insert_text((72, 140), f"Section {page_number}.1", fontsize=12, fontname="hebo")
            for line_number in range(20):
                page.insert_text(
                    (72, 180 + (line_number * 18)),
                    "Body text describes the manual and its practical topics.",
                    fontsize=10,
                    fontname="helv",
                )
        doc.set_toc(
            [
                [1, "Chapter 1", 1],
                [2, "Section 1.1", 1],
                [1, "Chapter 2", 2],
                [2, "Section 2.1", 2],
                [1, "Chapter 3", 3],
                [2, "Section 3.1", 3],
            ]
        )
        doc.save(str(path))
    finally:
        doc.close()
    return path


@pytest.mark.asyncio
async def test_add_book_pdf_without_llm(store_no_llm, tmp_path, monkeypatch):
    """A real PDF uses deterministic structure without calling the null adapter."""
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.get_encoder", lambda model="gpt-4o": None)
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine", lambda force_reresolve=False: None
    )

    async def _never(*args, **kwargs):
        raise AssertionError("_NullAdapter must not be called on the PDF path")

    for name in ("ask", "ask_structured", "ask_with_finish_info"):
        monkeypatch.setattr(f"parrot.knowledge.bookstore.library._NullAdapter.{name}", _never)

    card, status = await store_no_llm.add_book(_headed_pdf(tmp_path / "manual.pdf"))

    assert status == "added"
    assert card.card_origin == "fallback"
    assert card.toc


@pytest.mark.asyncio
async def test_add_book_unsupported_format(store, tmp_path):
    bad = tmp_path / "book.pptx"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(BookstoreError, match="Unsupported format"):
        await store.add_book(bad)


@pytest.mark.asyncio
async def test_epub_without_loaders_package(store, tmp_path, monkeypatch):
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"fake epub")
    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name.startswith("parrot_loaders"):
            raise ImportError("No module named 'parrot_loaders'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    with pytest.raises(BookstoreError, match="ai-parrot-loaders"):
        await store.add_book(epub)


@pytest.mark.asyncio
async def test_slug_collision_across_scopes_is_suffixed(store, tmp_path):
    """A global book must never receive a book_id already used in the
    project scope (or vice versa) — merged listings dedupe by book_id
    with project precedence, so a collision would shadow the book."""
    a = tmp_path / "same-book.md"
    a.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    b = tmp_path / "same_book.md"
    b.write_text(SAMPLE_MARKDOWN + "\nDifferent sha.\n", encoding="utf-8")
    card_a, _ = await store.add_book(a, title="Same Book")
    card_b, _ = await store.add_book(b, scope="global", title="Same Book")
    assert card_a.book_id == "same-book"
    assert card_b.book_id == "same-book-2"
    listed = {c.book_id for c in store.list_books()}
    assert {"same-book", "same-book-2"} <= listed


@pytest.mark.asyncio
async def test_slug_collision_suffixing(store, tmp_path):
    a = tmp_path / "same-title.md"
    a.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    b = tmp_path / "same_title.md"
    b.write_text(SAMPLE_MARKDOWN + "\nExtra line to change the sha.\n", encoding="utf-8")
    card_a, _ = await store.add_book(a, title="Same Title")
    card_b, _ = await store.add_book(b, title="Same Title")
    assert card_a.book_id == "same-title"
    assert card_b.book_id == "same-title-2"


@pytest.mark.asyncio
async def test_read_surface_toc_search_and_section(store, book_md):
    card, _ = await store.add_book(book_md)
    toc = store.get_toc(card.book_id)
    assert toc["entries"]
    node_id = toc["entries"][0]["node_id"]
    section = store.read_section(card.book_id, node_id)
    assert section["book_title"] == card.title
    assert section["content"]
    hits = await store.search_book(card.book_id, "vector search")
    assert hits and {"node_id", "title", "score"} <= set(hits[0])


@pytest.mark.asyncio
async def test_read_section_reads_body_ref(store: Bookstore, book_md: Path) -> None:
    """Resolve a catalog node id through the live tree's immutable body reference."""
    card, _ = await store.add_book(book_md)
    tree = await store._toolkit("project").get_tree(card.tree_name)
    node = next(node for node in tree["structure"] if node.get("body_ref"))

    section = store.read_section(card.book_id, node["node_id"])

    assert section["content"]
    assert "synthetic handbook" in section["content"].lower()


@pytest.mark.asyncio
async def test_read_section_unknown_node(store, book_md):
    card, _ = await store.add_book(book_md)
    with pytest.raises(BookstoreError, match="Unknown section"):
        store.read_section(card.book_id, "9999")


@pytest.mark.asyncio
async def test_no_llm_search_book_is_bm25_only(store_no_llm, book_md):
    card, _ = await store_no_llm.add_book(book_md)
    hits = await store_no_llm.search_book(card.book_id, "vector search")
    assert hits
    assert all(hit["source"] == "bm25" for hit in hits)


@pytest.mark.asyncio
async def test_cross_book_search_no_llm(store_no_llm, book_md):
    card, _ = await store_no_llm.add_book(book_md)
    out = await store_no_llm.search("vector search")
    assert out["books"]
    assert out["books"][0]["book_id"] == card.book_id
    assert out["books"][0]["results"]


def _install_fake_docx_loader(monkeypatch, markdown: str):
    """Register a fake parrot_loaders.docx module in sys.modules."""
    import sys
    import types

    class _FakeMSWordLoader:
        def __init__(self, *args, **kwargs):
            pass

        def docx_to_markdown(self, path):
            return markdown

    parent = types.ModuleType("parrot_loaders")
    module = types.ModuleType("parrot_loaders.docx")
    module.MSWordLoader = _FakeMSWordLoader
    parent.docx = module
    monkeypatch.setitem(sys.modules, "parrot_loaders", parent)
    monkeypatch.setitem(sys.modules, "parrot_loaders.docx", module)


@pytest.mark.asyncio
async def test_add_book_docx_via_fake_loader(store, tmp_path, monkeypatch):
    _install_fake_docx_loader(monkeypatch, SAMPLE_MARKDOWN)
    docx = tmp_path / "handbook.docx"
    docx.write_bytes(b"fake docx bytes")
    card, status = await store.add_book(docx)
    assert status == "added"
    assert card.source_format == "docx"
    assert card.chapter_count >= 1


@pytest.mark.asyncio
async def test_docx_without_loaders_package(store, tmp_path, monkeypatch):
    docx = tmp_path / "doc.docx"
    docx.write_bytes(b"fake docx")
    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name.startswith("parrot_loaders"):
            raise ImportError("No module named 'parrot_loaders'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    with pytest.raises(BookstoreError, match="ai-parrot-loaders"):
        await store.add_book(docx)


def test_iter_folder_files_recursive(tmp_path):
    from parrot.knowledge.bookstore.library import Bookstore

    root = tmp_path / "books"
    (root / "sub").mkdir(parents=True)
    (root / "a.md").write_text("x", encoding="utf-8")
    (root / "b.png").write_bytes(b"x")
    (root / "sub" / "c.pdf").write_bytes(b"x")
    flat_supported, flat_ignored = Bookstore.iter_folder_files(root)
    assert [p.name for p in flat_supported] == ["a.md"]
    assert [p.name for p in flat_ignored] == ["b.png"]
    rec_supported, _ = Bookstore.iter_folder_files(root, recursive=True)
    assert [p.name for p in rec_supported] == ["a.md", "c.pdf"]


def test_iter_folder_files_not_a_directory(tmp_path):
    from parrot.knowledge.bookstore.library import Bookstore

    with pytest.raises(BookstoreError, match="Not a directory"):
        Bookstore.iter_folder_files(tmp_path / "missing")


@pytest.mark.asyncio
async def test_add_folder_continues_after_failures(store_no_llm, tmp_path):
    root = tmp_path / "books"
    root.mkdir()
    (root / "one.md").write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    (root / "two.md").write_text(SAMPLE_MARKDOWN + "\nDifferent sha.\n", encoding="utf-8")
    # .txt needs an LLM → fails in the no-LLM store; loop must continue.
    (root / "notes.txt").write_text("plain text", encoding="utf-8")
    (root / "cover.png").write_bytes(b"x")
    out = await store_no_llm.add_folder(root)
    by_status = {}
    for entry in out["results"]:
        by_status.setdefault(entry["status"], []).append(entry)
    assert len(by_status["added"]) == 2
    assert len(by_status["failed"]) == 1
    assert "LLM" in by_status["failed"][0]["error"]
    assert out["ignored"] and out["ignored"][0].endswith("cover.png")
    listed = {c.book_id for c in store_no_llm.list_books()}
    assert {"one", "two"} <= listed


@pytest.mark.asyncio
async def test_add_folder_rerun_skips_by_sha(store, tmp_path, book_md):
    root = tmp_path / "books"
    root.mkdir()
    (root / "one.md").write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    first = await store.add_folder(root)
    second = await store.add_folder(root)
    assert first["results"][0]["status"] == "added"
    assert second["results"][0]["status"] == "skipped"


@pytest.mark.asyncio
async def test_remove_book(store, book_md, locations):
    card, _ = await store.add_book(book_md)
    assert await store.remove_book(card.book_id) is True
    assert not (locations[0].trees_dir / f"{card.book_id}.json").exists()
    with pytest.raises(BookstoreError):
        store.get_card(card.book_id)


@pytest.mark.asyncio
async def test_global_scope_ingest_and_resolution(store, book_md, locations):
    card, _ = await store.add_book(book_md, scope="global")
    assert card.scope == "global"
    assert (locations[1].trees_dir / f"{card.book_id}.json").is_file()
    resolved, loc = store.resolve_book(card.book_id)
    assert loc.scope == "global"
    assert resolved.scope == "global"


def test_bookstore_requires_locations():
    with pytest.raises(BookstoreError):
        Bookstore([])


@pytest.mark.asyncio
async def test_null_adapter_ask_with_finish_info_raises_cleanly():
    """Defense in depth: any unguarded LLM-required path must fail with a
    clean RuntimeError, not an AttributeError, if it ever reaches the
    null adapter (mirrors ``ask_structured``'s existing contract)."""
    from parrot.knowledge.bookstore.library import _NullAdapter

    adapter = _NullAdapter()
    assert await adapter.ask("anything") == ""
    with pytest.raises(RuntimeError, match="No LLM configured"):
        await adapter.ask_structured("anything", object)
    with pytest.raises(RuntimeError, match="No LLM configured"):
        await adapter.ask_with_finish_info("anything")


# ---------------------------------------------------------------------------
# FEAT-533 — classification at carding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_book_persists_classification(store, book_md):
    card, _ = await store.add_book(book_md)
    # Re-fetch: CatalogStore.upsert() slug-normalises traditions in the
    # DB, not on the in-memory `card` object add_book() returns.
    persisted = store.get_card(card.book_id)
    assert persisted.genre == "essay"
    assert persisted.traditions == ["estoicismo"]
    assert persisted.period == "Imperio romano"


@pytest.mark.asyncio
async def test_add_book_no_llm_classification_defaults(store_no_llm, book_md):
    card, _ = await store_no_llm.add_book(book_md)
    assert card.genre == "other"
    assert card.traditions == []
    assert card.period is None


@pytest.mark.asyncio
async def test_refresh_card_carries_classification_and_keeps_community(store, book_md):
    card, _ = await store.add_book(book_md)
    catalog = store._catalog("project")
    stamped = card.model_copy(update={"community_id": "c1", "community_label": "Virtue ethics"})
    catalog.upsert(stamped)
    await store.refresh_card(card.book_id)
    # Re-fetch: CatalogStore.upsert() slug-normalises traditions in the
    # DB, not on the in-memory object refresh_card() returns.
    persisted = store.get_card(card.book_id)
    assert persisted.genre == "essay"
    assert persisted.traditions == ["estoicismo"]
    assert persisted.period == "Imperio romano"
    assert persisted.community_id == "c1"
    assert persisted.community_label == "Virtue ethics"


@pytest.mark.asyncio
async def test_refresh_card_no_llm_preserves_existing_genre(store_no_llm, book_md):
    """Regression (code review, FEAT-533): CardDraft.genre defaults to
    the non-empty sentinel "other" (unlike traditions=[]/period=None,
    which are already falsy), so the old `draft.genre or card.genre`
    pattern always picked draft.genre — silently downgrading a
    previously-classified card back to "other" on every no-LLM/fallback
    refresh."""
    card, _ = await store_no_llm.add_book(book_md)
    catalog = store_no_llm._catalog("project")
    stamped = card.model_copy(update={"genre": "essay"})
    catalog.upsert(stamped)

    await store_no_llm.refresh_card(card.book_id)

    assert store_no_llm.get_card(card.book_id).genre == "essay"


def test_card_prompt_requests_classification():
    """Not in TASK-2914's own file list (a spec gap — no test_carding.py
    exists and it isn't listed here either) but required by its Test
    Specification; placed in this already-in-scope file rather than an
    out-of-scope one (test_models.py, which happens to hold the other
    carding.py tests)."""
    from parrot.knowledge.bookstore.carding import _CARD_PROMPT

    assert "genre" in _CARD_PROMPT and "traditions" in _CARD_PROMPT


def test_disambiguate_title_not_taken_is_unchanged():
    assert disambiguate_title("Book", set(), toc_entries=[], stem="book") == "Book"


def test_disambiguate_title_uses_first_distinct_toc_entry():
    toc = [TocEntry(node_id="n1", title="Book"), TocEntry(node_id="n2", title="Chapter 3 — Modules")]
    assert disambiguate_title("Book", {"book"}, toc_entries=toc, stem="ch03") == "Book — Chapter 3 — Modules"


def test_disambiguate_title_falls_back_to_stem_then_counter():
    assert disambiguate_title("Book", {"book"}, toc_entries=[], stem="odoo_ch03") == "Book — Odoo Ch03"
    taken = {"book", "book — odoo ch03"}
    assert disambiguate_title("Book", taken, toc_entries=[], stem="odoo_ch03") == "Book — Odoo Ch03 (2)"
    taken.add("book — odoo ch03 (2)")
    assert disambiguate_title("BOOK", taken, toc_entries=[], stem="odoo_ch03") == "BOOK — Odoo Ch03 (3)"
    # a ToC entry equal to the title (case-insensitively) is not a usable hint
    toc = [TocEntry(node_id="n1", title="BOOK")]
    assert disambiguate_title("Book", {"book"}, toc_entries=toc, stem="x") == "Book — X"


@pytest.mark.asyncio
async def test_add_book_llm_duplicate_title_is_disambiguated(store, book_md, tmp_path):
    first, _ = await store.add_book(book_md)
    other = tmp_path / "second-part.md"
    other.write_text(SAMPLE_MARKDOWN + "\n## Part two\n\nDifferent bytes.\n", encoding="utf-8")
    second, status = await store.add_book(other)
    assert status == "added"
    assert first.title == "Synthetic Handbook"
    assert second.title != first.title
    assert second.title.startswith("Synthetic Handbook — ")
    assert store.get_card(first.book_id).title == "Synthetic Handbook"


@pytest.mark.asyncio
async def test_add_book_explicit_title_never_disambiguated(store, book_md, tmp_path):
    other = tmp_path / "another.md"
    other.write_text(SAMPLE_MARKDOWN + "\n## Another\n\nDifferent bytes.\n", encoding="utf-8")
    first, _ = await store.add_book(book_md, title="Same Title")
    second, _ = await store.add_book(other, title="Same Title")
    assert first.title == second.title == "Same Title"
    assert (first.book_id, second.book_id) == ("same-title", "same-title-2")


@pytest.mark.asyncio
async def test_update_card_fields_and_manual_origin(store, book_md):
    card, _ = await store.add_book(book_md)
    store._catalog("project").set_card_community(card.book_id, "c1", "Community One")
    updated = store.update_card(card.book_id, title="  New Title ", authors=["A"], topics=["t1"], summary="S")
    assert (updated.title, updated.authors, updated.topics, updated.summary) == ("New Title", ["A"], ["t1"], "S")
    assert updated.card_origin == "manual"
    reread = store.get_card(card.book_id)
    assert reread.title == "New Title" and reread.community_id == "c1"


@pytest.mark.asyncio
async def test_reindex_preserves_manual_card_edits(store, book_md):
    """issue:9013034b010f — an in-place re-index must not revert update_card edits."""
    card, _ = await store.add_book(book_md)
    store.update_card(
        card.book_id, title="Hand Title", authors=["Hand Author"], topics=["hand"], summary="Hand summary"
    )
    book_md.write_text(SAMPLE_MARKDOWN + "\n## New chapter\n\nChanged content.\n", encoding="utf-8")
    updated, status = await store.add_book(book_md)
    assert status == "updated"
    assert updated.book_id == card.book_id
    assert (updated.title, updated.authors, updated.topics, updated.summary) == (
        "Hand Title",
        ["Hand Author"],
        ["hand"],
        "Hand summary",
    )
    assert updated.card_origin == "manual"
    assert updated.source_sha256 != card.source_sha256
    reread = store.get_card(card.book_id)
    assert reread.title == "Hand Title" and reread.card_origin == "manual"


@pytest.mark.asyncio
async def test_reindex_explicit_overrides_beat_preserved_manual_fields(store, book_md):
    """Explicit title/authors on the re-index call still win over the preserved manual card."""
    card, _ = await store.add_book(book_md)
    store.update_card(card.book_id, title="Hand Title", topics=["hand"])
    book_md.write_text(SAMPLE_MARKDOWN + "\n## Another\n\nMore.\n", encoding="utf-8")
    updated, status = await store.add_book(book_md, title="Override Title", authors=["New Author"])
    assert status == "updated"
    assert updated.title == "Override Title"
    assert updated.authors == ["New Author"]
    assert updated.topics == ["hand"]
    assert updated.card_origin == "manual"


@pytest.mark.asyncio
async def test_reindex_of_llm_card_takes_fresh_draft(store, book_md):
    """A non-manual card is rebuilt from the fresh draft on re-index (unchanged behaviour)."""
    card, _ = await store.add_book(book_md)
    assert card.card_origin == "llm"
    book_md.write_text(SAMPLE_MARKDOWN + "\n## Fresh\n\nContent.\n", encoding="utf-8")
    updated, status = await store.add_book(book_md)
    assert status == "updated"
    assert updated.card_origin == "llm"
    assert updated.summary == card.summary  # fake adapter drafts the same summary


@pytest.mark.asyncio
async def test_update_card_requires_a_field(store, book_md):
    card, _ = await store.add_book(book_md)
    with pytest.raises(BookstoreError):
        store.update_card(card.book_id)
    with pytest.raises(BookstoreError):
        store.update_card(card.book_id, title="  ")
    with pytest.raises(BookstoreError):
        store.update_card("no-such-book", title="X")


@pytest.mark.asyncio
async def test_reindex_failed_ingest_keeps_old_book(store: Bookstore, book_md: Path, tmp_path: Path) -> None:
    """Preserve old JSON, card and graph on failed ingest."""
    card, _ = await store.add_book(book_md)
    store._content_store("project")
    old_json = (store._location("project").trees_dir / f"{card.book_id}.json").read_bytes()
    store.update_card(card.book_id, title="Edited title")
    other = tmp_path / "other-book.md"
    other.write_text(SAMPLE_MARKDOWN + "\n## Other\n\nDifferent bytes.\n", encoding="utf-8")
    other_card, _ = await store.add_book(other)
    catalog = store._catalog("project")
    catalog.upsert_relations(
        [
            BookRelation(
                src_book_id=card.book_id,
                dst_book_id=other_card.book_id,
                rel="parallels",
                origin="llm",
                confidence=0.7,
                weight=REL_WEIGHTS["parallels"],
                computed_at="2026-09-06T00:00:00+00:00",
            )
        ]
    )
    catalog.record_judgements(
        card.book_id,
        [RelationJudgement(dst_book_id=other_card.book_id, rel="parallels", confidence=0.7)],
    )
    catalog.upsert_communities(
        [
            BookCommunity(
                community_id="c1",
                label="Pair",
                label_origin="derived",
                algorithm="leiden",
                size=2,
                cohesion=1.0,
                centroid_book_id=card.book_id,
                member_book_ids=[card.book_id, other_card.book_id],
                computed_at="2026-09-06T00:00:00+00:00",
            )
        ]
    )
    old_relations = store.related_books(card.book_id)
    old_judgements = catalog.judged_pairs(card.book_id)
    old_communities = store.communities()
    book_md.write_text(SAMPLE_MARKDOWN + "\n## Changed\n\nNew content.\n", encoding="utf-8")

    async def fail_insert(*args, **kwargs) -> None:
        raise RuntimeError("ingest failed")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(store._toolkit("project"), "insert_markdown", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="ingest failed"):
            await store.add_book(book_md)
    finally:
        monkeypatch.undo()

    assert (store._location("project").trees_dir / f"{card.book_id}.json").read_bytes() == old_json
    assert store.get_card(card.book_id).title == "Edited title"
    assert store.related_books(card.book_id) == old_relations
    assert catalog.judged_pairs(card.book_id) == old_judgements
    assert store.communities() == old_communities
    assert not list(store._location("project").trees_dir.glob(f"*{_STAGING_MARKER}*.json"))


@pytest.mark.asyncio
async def test_reindex_success_swaps_tree_same_book_id(store: Bookstore, book_md: Path) -> None:
    """Keep identity and evict warmed content caches."""
    card, _ = await store.add_book(book_md)
    store._content_store("project")
    book_md.write_text(SAMPLE_MARKDOWN + "\n## Replacement\n\nFresh replacement content.\n", encoding="utf-8")

    updated, status = await store.add_book(book_md)

    assert status == "updated"
    assert updated.book_id == updated.tree_name == card.book_id
    assert "project" not in store._content_stores
    assert await store.search_book(card.book_id, "replacement content")


@pytest.mark.asyncio
async def test_reindex_leaves_no_replaced_tree(store: Bookstore, book_md: Path) -> None:
    """Publication replaces the live generation without creating a backup tree."""
    card, _ = await store.add_book(book_md)
    book_md.write_text(
        SAMPLE_MARKDOWN + "\n## Updated Chapter\n\n"
        "The updated chapter contains enough descriptive text to remain visible to the markdown parser.\n",
        encoding="utf-8",
    )

    _, status = await store.add_book(book_md)

    assert status == "updated"
    assert not list(store._location("project").trees_dir.glob(f"*{REPLACED_MARKER}*.json"))


@pytest.mark.asyncio
async def test_add_failed_ingest_leaves_no_tree(store: Bookstore, book_md: Path) -> None:
    """Leave no staging or card after a first-add failure."""

    async def fail_insert(*args, **kwargs) -> None:
        raise RuntimeError("ingest failed")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(store._toolkit("project"), "insert_markdown", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="ingest failed"):
            await store.add_book(book_md)
    finally:
        monkeypatch.undo()

    assert store.list_books() == []
    assert not list(store._location("project").trees_dir.glob("*.json"))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["draft", "swap"])
async def test_reindex_card_draft_and_swap_failures_keep_old_book(
    store: Bookstore, book_md: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Keep the live tree when card drafting or publishing fails."""
    card, _ = await store.add_book(book_md)
    old_json = (store._location("project").trees_dir / f"{card.book_id}.json").read_bytes()
    book_md.write_text(SAMPLE_MARKDOWN + "\n## Changed\n\nNew content.\n", encoding="utf-8")

    async def fail(*args, **kwargs) -> None:
        raise RuntimeError(f"{failure} failed")

    if failure == "draft":
        monkeypatch.setattr(store, "_draft_card", fail)
    else:
        monkeypatch.setattr(store._toolkit("project"), "rename_tree", fail)

    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        await store.add_book(book_md)

    assert (store._location("project").trees_dir / f"{card.book_id}.json").read_bytes() == old_json
    assert store.get_card(card.book_id).book_id == card.book_id
    assert not list(store._location("project").trees_dir.glob(f"*{_STAGING_MARKER}*.json"))


@pytest.mark.asyncio
async def test_sweep_restores_orphaned_replaced_tree(store: Bookstore, book_md: Path) -> None:
    """Restore backup when its live tree is absent."""
    card, _ = await store.add_book(book_md)
    backup = f"{card.book_id}{REPLACED_MARKER}deadbeef"
    toolkit = store._toolkit("project")
    await toolkit.rename_tree(card.book_id, backup)

    skipped, status = await store.add_book(book_md)

    assert status == "skipped"
    assert skipped.book_id == card.book_id
    assert (store._location("project").trees_dir / f"{card.book_id}.json").is_file()
    assert not (store._location("project").trees_dir / f"{backup}.json").exists()


@pytest.mark.asyncio
async def test_sweep_deletes_stale_staging_keeps_fresh(store: Bookstore, book_md: Path) -> None:
    """Honor the fixed one-hour threshold."""
    toolkit = store._toolkit("project")
    stale = f"stale{_STAGING_MARKER}deadbeef"
    fresh = f"fresh{_STAGING_MARKER}deadbeef"
    await toolkit.create_tree(stale)
    await toolkit.create_tree(fresh)
    stale_path = store._location("project").trees_dir / f"{stale}.json"
    os.utime(stale_path, (time.time() - _STAGING_MAX_AGE_S - 1, time.time() - _STAGING_MAX_AGE_S - 1))

    await store._sweep_reserved_trees("project")

    assert not stale_path.exists()
    assert (store._location("project").trees_dir / f"{fresh}.json").exists()


@pytest.mark.asyncio
async def test_sweep_vacuums_live_reserved_target(store: Bookstore, monkeypatch: pytest.MonkeyPatch) -> None:
    """Vacuum surviving live trees without letting a cleanup failure stop recovery."""
    toolkit = store._toolkit("project")
    live_name = "live"
    await toolkit.create_tree(live_name)
    await toolkit.create_tree(f"{live_name}{_STAGING_MARKER}deadbeef")
    vacuumed: list[str] = []

    async def failing_vacuum(tree_name: str) -> None:
        vacuumed.append(tree_name)
        raise RuntimeError("vacuum failed")

    monkeypatch.setattr(toolkit, "vacuum_tree", failing_vacuum)

    await store._sweep_reserved_trees("project")

    assert vacuumed == [live_name]


@pytest.mark.asyncio
async def test_all_taken_slugs_reserves_staging_but_ignores_replacements(store: Bookstore, book_md: Path) -> None:
    """A staging tree reserves its slug for other processes; a replacement copy does not."""
    toolkit = store._toolkit("project")
    await toolkit.create_tree(f"staged{_STAGING_MARKER}deadbeef")
    await toolkit.create_tree(f"replaced{REPLACED_MARKER}deadbeef")

    taken = store._all_taken_slugs()

    assert "staged" in taken
    assert "replaced" not in taken
    assert not any(_STAGING_MARKER in name or REPLACED_MARKER in name for name in taken)


@pytest.mark.asyncio
async def test_reindex_roundtrip_markdown(store: Bookstore, book_md: Path) -> None:
    """Read and search changed markdown under the same ID."""
    card, _ = await store.add_book(book_md)
    book_md.write_text(
        SAMPLE_MARKDOWN + "\n## Replacement Chapter\n"
        "Atomic swap roundtrip phrase with plenty of descriptive content to clear the "
        "thinning threshold of the markdown parser and keep this node visible. "
        + "The optimizer keeps a section as its own node only when it clears the minimum leaf size, "
        "so this chapter carries enough descriptive prose about swapping a book revision atomically "
        "while readers keep searching the previous revision until the new one is published. " * 4 + "\n",
        encoding="utf-8",
    )

    updated, status = await store.add_book(book_md)
    toc = store.get_toc(updated.book_id)

    assert status == "updated"
    assert updated.book_id == card.book_id
    assert any(entry["title"] == "Replacement Chapter" for entry in toc["entries"])
    assert await store.search_book(updated.book_id, "atomic swap roundtrip")


@pytest.mark.asyncio
async def test_cancelled_ingest_cleans_up_staging_tree(monkeypatch, store: Bookstore, book_md: Path) -> None:
    """A cancelled ingest must not leak its ``--staging-`` tree."""
    toolkit = store._toolkit("project")

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(toolkit, "insert_markdown", cancelled)

    with pytest.raises(asyncio.CancelledError):
        await store.add_book(book_md)

    trees_dir = store._location("project").trees_dir
    assert not list(trees_dir.glob(f"*{_STAGING_MARKER}*.json"))


@pytest.mark.asyncio
async def test_draft_card_samples_live_bodies_not_stale_legacy(
    store: Bookstore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Card the live generation: a stale ``<node_id>.md`` must never reach the LLM."""
    book_path = tmp_path / "pinned-book.md"
    book_path.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    card, _ = await store.add_book(book_path)
    tree = await store._toolkit("project").get_tree(card.tree_name)
    node = next(n for n in tree["structure"] if n.get("body_ref"))
    node_id = node["node_id"]

    # A leftover legacy sidecar, as rename_tree(overwrite=True) over a legacy
    # destination leaves behind. The unpinned loader prefers it over body_ref.
    store._content_store("project").save(card.tree_name, node_id, "STALE LEGACY BODY from another book")

    captured: list[list[str]] = []

    async def _capture(adapter, *, filename, doc_description, toc_digest, samples):
        captured.append(list(samples))
        return CardDraft(title="Pinned Book", topics=["testing"])

    monkeypatch.setattr("parrot.knowledge.bookstore.library.generate_card_fields", _capture)

    await store.refresh_card(card.book_id)

    assert captured, "generate_card_fields was never reached"
    joined = "\n".join(captured[0])
    assert "STALE LEGACY BODY" not in joined, "carding sampled a stale legacy sidecar instead of the live body"


# ----------------------------------------------------------------------
# Notebooks (FEAT-876 TASK-5477)
# ----------------------------------------------------------------------
async def _anchor_note(
    store: Bookstore, book_id: str, node_id: str, *, title: str = "A footnote", body: str = ""
) -> str:
    """Add one note anchored to ``(book_id, node_id)`` in the book's notebook; return its node id."""
    notebook = await store.ensure_notebook(book_id)
    toolkit = await store._ready_toolkit(notebook.scope)
    added = await toolkit.add_node(notebook.tree_name, title=title, body=body)
    await toolkit.tag_node(
        notebook.tree_name,
        added["node_id"],
        metadata={"anchors": [{"book_id": book_id, "node_id": node_id}], "note_kind": "footnote"},
    )
    return added["node_id"]


@pytest.mark.asyncio
async def test_notebook_lazy_registration(store, book_md):
    card, _ = await store.add_book(book_md)
    books_before = [c.book_id for c in store.list_books()]
    assert store.notebook_for(card.book_id) is None

    toolkit = await store._ready_toolkit("project")
    await toolkit.create_tree(notebook_tree_name(card.book_id))

    first = store.notebook_for(card.book_id)
    second = store.notebook_for(card.book_id)
    assert first is not None and second is not None
    assert first.book_id == first.tree_name == f"{card.book_id}{NOTEBOOK_SUFFIX}"
    assert first.kind == "notes" and first.notes_for == card.book_id
    assert first.source_format == "tree" and first.card_origin == "fallback"
    assert first.title == f"Notes — {card.title}"
    catalog = store._catalog("project")
    assert [c.book_id for c in catalog.list_cards(kind="notes")] == [first.book_id]
    assert [c.book_id for c in store.list_books()] == books_before
    assert all(c.kind == "book" for c in store.catalog_search("Notes"))

    # Library notebook: absent → None; ensure_notebook creates and registers it.
    assert store.library_notebook("project") is None
    library = await store.ensure_notebook(None, scope="project")
    assert library.book_id == LIBRARY_NOTEBOOK and library.notes_for is None
    assert store.library_notebook("project").book_id == LIBRARY_NOTEBOOK


@pytest.mark.asyncio
async def test_read_section_carries_annotations(store, book_md):
    card, _ = await store.add_book(book_md)
    assert len(card.toc) >= 2
    target, other = card.toc[0].node_id, card.toc[1].node_id
    assert store.read_section(card.book_id, target)["annotations"] == []

    note_id = await _anchor_note(store, card.book_id, target, body="Remember the event loop.")

    section = store.read_section(card.book_id, target)
    assert section["content"]  # existing keys unchanged
    assert len(section["annotations"]) == 1
    note = section["annotations"][0]
    assert note["node_id"] == note_id
    assert note["note_tree"] == notebook_tree_name(card.book_id)
    assert note["body"] == "Remember the event loop."
    assert note["note_kind"] == "footnote"
    assert note["anchor_status"] == "current"
    assert store.read_section(card.book_id, other)["annotations"] == []
    async_notes = await store.annotations_for(card.book_id, target)
    assert [n.node_id for n in async_notes] == [note_id]


@pytest.mark.asyncio
async def test_read_section_survives_corrupt_notebook(store, book_md, locations):
    card, _ = await store.add_book(book_md)
    (locations[0].trees_dir / f"{notebook_tree_name(card.book_id)}.json").write_text("{not json", encoding="utf-8")
    section = store.read_section(card.book_id, card.toc[0].node_id)
    assert section["annotations"] == []
    assert all(entry["has_notes"] is False for entry in store.get_toc(card.book_id)["entries"])


@pytest.mark.asyncio
async def test_get_toc_has_notes(store, book_md):
    card, _ = await store.add_book(book_md)
    before = store.get_toc(card.book_id)
    assert all(entry["has_notes"] is False for entry in before["entries"])
    target = card.toc[0].node_id
    await _anchor_note(store, card.book_id, target)

    toc = store.get_toc(card.book_id)
    assert set(toc) == {"book_id", "title", "toc_digest", "entries"}
    for entry, original in zip(toc["entries"], card.toc, strict=True):
        assert {k: v for k, v in entry.items() if k != "has_notes"} == original.model_dump()
        assert entry["has_notes"] is (entry["node_id"] == target)


@pytest.mark.asyncio
async def test_annotations_resolve_by_scope_and_id(tmp_path, fake_adapter):
    project = LibraryLocation(scope="project", root=tmp_path / "proj" / "library")
    glob = LibraryLocation(scope="global", root=tmp_path / "glob" / "library")
    book = tmp_path / "synthetic-handbook.md"
    book.write_text(SAMPLE_MARKDOWN, encoding="utf-8")

    # The same book id in each scope, each with its own notebook.
    global_store = Bookstore([glob], adapter=fake_adapter)
    global_card, _ = await global_store.add_book(book, scope="global")
    project_store = Bookstore([project], adapter=fake_adapter)
    project_card, _ = await project_store.add_book(book)
    assert global_card.book_id == project_card.book_id
    node_id = project_card.toc[0].node_id
    project_note = await _anchor_note(project_store, project_card.book_id, node_id, title="Project note")

    # The global book never sees the project notebook (identity is (scope, book_id)).
    assert global_store.read_section(global_card.book_id, node_id)["annotations"] == []

    # A global notebook node anchored with the default (project) scope is ignored there;
    # an explicit global anchor is honoured.
    notebook = await global_store.ensure_notebook(global_card.book_id)
    assert notebook.scope == "global"
    toolkit = await global_store._ready_toolkit("global")
    wrong = await toolkit.add_node(notebook.tree_name, title="Wrong scope")
    await toolkit.tag_node(
        notebook.tree_name,
        wrong["node_id"],
        metadata={"anchors": [{"book_id": global_card.book_id, "node_id": node_id}]},
    )
    right = await toolkit.add_node(notebook.tree_name, title="Global note")
    await toolkit.tag_node(
        notebook.tree_name,
        right["node_id"],
        metadata={"anchors": [{"book_id": global_card.book_id, "node_id": node_id, "scope": "global"}]},
    )
    global_notes = global_store.read_section(global_card.book_id, node_id)["annotations"]
    assert [n["title"] for n in global_notes] == ["Global note"]
    project_notes = project_store.read_section(project_card.book_id, node_id)["annotations"]
    assert [n["node_id"] for n in project_notes] == [project_note]


@pytest.mark.asyncio
async def test_annotations_skip_malformed_anchors(store, book_md):
    card, _ = await store.add_book(book_md)
    target = card.toc[0].node_id
    notebook = await store.ensure_notebook(card.book_id)
    toolkit = await store._ready_toolkit("project")
    added = await toolkit.add_node(notebook.tree_name, title="Mixed anchors")
    await toolkit.tag_node(
        notebook.tree_name,
        added["node_id"],
        metadata={"anchors": [{"node_id": target}, "garbage", {"book_id": card.book_id, "node_id": target}]},
    )
    notes = store.read_section(card.book_id, target)["annotations"]
    assert [n["node_id"] for n in notes] == [added["node_id"]]


@pytest.mark.asyncio
async def test_remove_book_keeps_notebook_by_default(store, book_md, locations):
    card, _ = await store.add_book(book_md)
    await _anchor_note(store, card.book_id, card.toc[0].node_id)
    name = notebook_tree_name(card.book_id)
    tree_path = locations[0].trees_dir / f"{name}.json"

    assert await store.remove_book(card.book_id) is True
    catalog = store._catalog("project")
    orphan = catalog.get(name)
    assert orphan is not None and orphan.kind == "notes" and orphan.notes_for is None
    assert tree_path.is_file()
    assert store.list_books() == []


@pytest.mark.asyncio
async def test_remove_book_with_notes_deletes_notebook(store, book_md, locations):
    card, _ = await store.add_book(book_md)
    await _anchor_note(store, card.book_id, card.toc[0].node_id)
    name = notebook_tree_name(card.book_id)

    assert await store.remove_book(card.book_id, with_notes=True) is True
    assert store._catalog("project").get(name) is None
    assert not (locations[0].trees_dir / f"{name}.json").exists()


@pytest.mark.asyncio
async def test_resolve_book_refuses_notebook(store, book_md):
    card, _ = await store.add_book(book_md)
    notebook = await store.ensure_notebook(card.book_id)
    with pytest.raises(BookstoreError):
        store.resolve_book(notebook.book_id)
    assert notebook.book_id not in [c.book_id for c in store.list_books()]
    assert all(c.kind == "book" for c in store.catalog_search("Notes"))
    assert all(c.kind == "book" for c in store.catalog_search(card.title))


# ----------------------------------------------------------------------
# remap_anchors (FEAT-876 TASK-5479)
# ----------------------------------------------------------------------
def _long(word: str) -> str:
    """A body long enough that the markdown parser keeps its section as its own node."""
    return (f"{word} content of the section, repeated at length. ") * 20


def _chapters(*sections: tuple[str, str]) -> str:
    """Markdown book with an intro and one ``##`` section per ``(title, word)``."""
    parts = ["# Remap Book\n\n" + _long("intro")]
    parts += [f"## {title}\n{_long(word)}" for title, word in sections]
    return "\n\n".join(parts) + "\n"


def _node_id_by_title(toc, title: str) -> str:
    return next(entry.node_id for entry in toc if entry.title == title)


async def _note_anchors(store: Bookstore, card, note_id: str) -> tuple[list, str]:
    """``(anchors, anchor_status)`` of one notebook node, read from the live notebook tree."""
    toolkit = await store._ready_toolkit(card.scope)
    tree = await toolkit.get_tree(notebook_tree_name(card.book_id))
    from parrot.knowledge.pageindex.utils import structure_to_list

    node = next(n for n in structure_to_list(tree["structure"]) if n["node_id"] == note_id)
    meta = node.get("metadata") or {}
    return meta["anchors"], meta.get("anchor_status", "current")


@pytest.mark.asyncio
async def test_remap_anchors_after_update(store, book_md):
    book_md.write_text(_chapters(("Chapter One", "alpha"), ("Chapter Two", "beta")), encoding="utf-8")
    card, _ = await store.add_book(book_md)
    ch2 = _node_id_by_title(card.toc, "Chapter Two")
    note_id = await _anchor_note(store, card.book_id, ch2)
    before = {
        n["node_id"]
        for n in (await (await store._ready_toolkit("project")).get_tree(notebook_tree_name(card.book_id)))["structure"]
    }

    # A new chapter inserted before Chapter Two shifts its node id; text is unchanged.
    book_md.write_text(
        _chapters(("Chapter One", "alpha"), ("Bridge", "gamma"), ("Chapter Two", "beta")), encoding="utf-8"
    )
    updated, status = await store.add_book(book_md)
    assert status == "updated"
    new_ch2 = _node_id_by_title(updated.toc, "Chapter Two")
    assert new_ch2 != ch2

    anchors, anchor_status = await _note_anchors(store, updated, note_id)
    assert anchor_status == "remapped"
    assert anchors[0]["node_id"] == new_ch2
    assert anchors[0]["revision"]
    after = {
        n["node_id"]
        for n in (await (await store._ready_toolkit("project")).get_tree(notebook_tree_name(card.book_id)))["structure"]
    }
    assert before <= after  # never deletes
    notes = await store.annotations_for(card.book_id, new_ch2)
    assert [n.node_id for n in notes] == [note_id]
    assert notes[0].anchor_status == "remapped"

    # Idempotent: a second pass finds everything current.
    assert await store.remap_anchors(card.book_id) == {"current": 1, "remapped": 0, "stale": 0}


@pytest.mark.asyncio
async def test_remap_repeated_titles_and_moved_sections(store, tmp_path):
    path = tmp_path / "dupes.md"
    path.write_text(_chapters(("Notes", "alpha"), ("Notes", "beta"), ("Moving", "gamma")), encoding="utf-8")
    card, _ = await store.add_book(path)
    first_notes = [e.node_id for e in card.toc if e.title == "Notes"][0]
    moving = _node_id_by_title(card.toc, "Moving")
    n_first = await _anchor_note(store, card.book_id, first_notes, title="n1")
    n_moving = await _anchor_note(store, card.book_id, moving, title="n2")

    # Both "Notes" bodies change (no fingerprint match, duplicate title); "Moving" moves up unchanged.
    path.write_text(_chapters(("Moving", "gamma"), ("Notes", "delta"), ("Notes", "epsilon")), encoding="utf-8")
    updated, status = await store.add_book(path)
    assert status == "updated"
    new_moving = _node_id_by_title(updated.toc, "Moving")
    assert new_moving != moving

    anchors, anchor_status = await _note_anchors(store, updated, n_first)
    assert anchor_status == "stale"
    assert anchors[0]["node_id"] == first_notes  # kept as is
    anchors, anchor_status = await _note_anchors(store, updated, n_moving)
    assert anchor_status == "remapped"
    assert anchors[0]["node_id"] == new_moving


@pytest.mark.asyncio
async def test_add_book_survives_remap_failure(store, book_md, monkeypatch):
    book_md.write_text(_chapters(("Chapter One", "alpha")), encoding="utf-8")
    card, _ = await store.add_book(book_md)
    await _anchor_note(store, card.book_id, _node_id_by_title(card.toc, "Chapter One"))

    async def boom(*args, **kwargs):
        raise RuntimeError("remap exploded")

    monkeypatch.setattr(store, "remap_anchors", boom)
    book_md.write_text(_chapters(("Chapter One", "alpha"), ("Chapter Three", "zeta")), encoding="utf-8")
    updated, status = await store.add_book(book_md)
    assert status == "updated"
    assert updated.book_id == card.book_id


@pytest.mark.asyncio
async def test_reindex_preserves_notebook_end_to_end(store, book_md):
    book_md.write_text(_chapters(("Chapter One", "alpha"), ("Chapter Two", "beta")), encoding="utf-8")
    card, _ = await store.add_book(book_md)
    ch1 = _node_id_by_title(card.toc, "Chapter One")
    ch2 = _node_id_by_title(card.toc, "Chapter Two")
    n1 = await _anchor_note(store, card.book_id, ch1, title="one", body="note one")
    n2 = await _anchor_note(store, card.book_id, ch2, title="two", body="note two")

    book_md.write_text(_chapters(("Chapter One", "alpha"), ("Chapter Two", "omega")), encoding="utf-8")
    updated, status = await store.add_book(book_md)
    assert status == "updated"

    for note_id in (n1, n2):
        anchors, anchor_status = await _note_anchors(store, updated, note_id)
        assert anchor_status in {"current", "remapped", "stale"}
        assert anchors and anchors[0]["book_id"] == card.book_id
    # Chapter One is untouched, still readable with its note attached.
    section = store.read_section(card.book_id, ch1)
    assert any(a["node_id"] == n1 for a in section["annotations"])
    bodies = (await (await store._ready_toolkit("project")).get_tree(notebook_tree_name(card.book_id)))["structure"]
    assert len(bodies) == 2
