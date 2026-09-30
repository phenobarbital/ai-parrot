"""Tests for the Bookstore manager (ingestion + read surface)."""

from __future__ import annotations

import builtins
import os
import time
from pathlib import Path

import pytest

from parrot.knowledge.bookstore.carding import disambiguate_title
from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import (
    _REPLACED_MARKER,
    _STAGING_MARKER,
    _STAGING_MAX_AGE_S,
    Bookstore,
    BookstoreError,
)
from parrot.knowledge.bookstore.models import BookCommunity, BookRelation, RelationJudgement, REL_WEIGHTS, TocEntry

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
async def test_add_book_pdf_requires_llm(store_no_llm, tmp_path):
    """PDF ToC detection/structuring always needs an LLM (FEAT-531 bug).

    Ingest must fail fast with a clear ``BookstoreError`` — not deep
    inside the PageIndex builder with ``'_NullAdapter' object has no
    attribute 'ask_with_finish_info'`` (an AttributeError, not a
    BookstoreError, so it used to bypass the CLI's clean-error handling
    and crash with a full traceback).
    """
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(BookstoreError, match="LLM"):
        await store_no_llm.add_book(pdf)


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
    backup = f"{card.book_id}{_REPLACED_MARKER}deadbeef"
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
async def test_all_taken_slugs_ignores_reserved_names(store: Bookstore, book_md: Path) -> None:
    """Ignore staging and replacement names."""
    toolkit = store._toolkit("project")
    await toolkit.create_tree(f"book{_STAGING_MARKER}deadbeef")
    await toolkit.create_tree(f"book{_REPLACED_MARKER}deadbeef")

    assert "book" not in store._all_taken_slugs()


@pytest.mark.asyncio
async def test_reindex_roundtrip_markdown(store: Bookstore, book_md: Path) -> None:
    """Read and search changed markdown under the same ID."""
    card, _ = await store.add_book(book_md)
    book_md.write_text(
        SAMPLE_MARKDOWN + "\n## Replacement Chapter\n\nAtomic swap roundtrip phrase.\n",
        encoding="utf-8",
    )

    updated, status = await store.add_book(book_md)
    toc = store.get_toc(updated.book_id)

    assert status == "updated"
    assert updated.book_id == card.book_id
    assert any(entry["title"] == "Replacement Chapter" for entry in toc["entries"])
    assert await store.search_book(updated.book_id, "atomic swap roundtrip")
