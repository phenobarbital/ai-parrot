"""Deterministic Bookstore origin evidence and isolation tests (FEAT-858 / TASK-5434)."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError
from parrot.knowledge.pageindex.segment_store import SegmentStore
from parrot.knowledge.pageindex.segments import DocumentRevision, SourceInfo, revision_id, segment_text
from parrot.models import OriginHit, OriginSection, SearchOriginKind
from parrot_tools.multistoresearch.origins.bookstore import BookstoreOrigin

LONG_PARAGRAPH = "Kant argues that the categories of the understanding " * 20
SECOND_PARAGRAPH = "Experience begins with intuition and ends with judgement under rules."
THIRD_PARAGRAPH = "A third paragraph closes the chapter with a summary of the argument."


def _card(book_id: str, scope: str = "project", title: Optional[str] = None) -> SimpleNamespace:
    """Build a minimal Bookstore card double."""
    return SimpleNamespace(book_id=book_id, title=title or f"Title {book_id}", tree_name=book_id, scope=scope)


def _revision(text: str, name: str = "Synthetic Book") -> DocumentRevision:
    """Build an immutable revision from markdown paragraphs."""
    segments = segment_text(text, ["Chapter One"])
    return DocumentRevision(
        doc_id="doc-1",
        revision=revision_id(segments),
        source=SourceInfo(name=name, kind="markdown"),
        created_at="2026-11-09T00:00:00Z",
        segments=segments,
    )


def _read(
    rev: DocumentRevision,
    tree_name: str,
    seqs: list[int],
    max_chars: int,
    *,
    first_offset: int = 0,
    revision: Optional[str] = None,
    tamper: bool = False,
    generation: int = 7,
) -> dict[str, Any]:
    """Mimic PageIndex's read loop, including its 500-character minimum budget."""
    remaining = max(max_chars, 500)
    segments: list[dict[str, Any]] = []
    for index, seq in enumerate(seqs):
        if remaining <= 0:
            break
        seg = rev.segments[seq]
        offset = first_offset if index == 0 else 0
        end = min(len(seg.text), offset + remaining)
        remaining -= end - offset
        text = seg.text[offset:end]
        if tamper:
            text = "Fabricated " + text[11:]
        segments.append(
            {
                "address": {
                    "doc_id": rev.doc_id,
                    "revision": revision or rev.revision,
                    "seq": seq,
                    "page": seg.page,
                    "ordinal": seg.ordinal,
                    "section": seg.section,
                },
                "seq": seq,
                "kind": seg.kind,
                "text": text,
                "start": offset,
                "end": end,
                "truncated": end < len(seg.text),
                "flags": [],
            }
        )
    return {
        "tree_name": tree_name,
        "doc_id": rev.doc_id,
        "revision": revision or rev.revision,
        "generation": generation,
        "segments": segments,
        "truncated": False,
        "next_cursor": None,
        "framed": "<document_text>ignored</document_text>",
    }


def _bookstore(tmp_path: Path, cards: list[SimpleNamespace]) -> Bookstore:
    """Real Bookstore facade whose catalog/search/read surface is stubbed deterministically."""
    locations = [
        LibraryLocation(scope="project", root=tmp_path / "proj" / "library"),
        LibraryLocation(scope="global", root=tmp_path / "glob" / "library"),
    ]
    store = Bookstore(locations)
    by_id = {card.book_id: card for card in cards}
    loc_by_scope = {loc.scope: loc for loc in locations}
    store.list_books = MagicMock(return_value=list(cards))
    store.catalog_search = MagicMock(return_value=[])
    store.search = AsyncMock(return_value={"query": "q", "books": []})
    store.agentic_retrieve = AsyncMock(side_effect=AssertionError("agentic retrieval must never run"))

    def resolve(book_id: str) -> tuple[SimpleNamespace, LibraryLocation]:
        if book_id not in by_id:
            raise BookstoreError(f"Unknown book {book_id!r}")
        card = by_id[book_id]
        return card, loc_by_scope[card.scope]

    store.resolve_book = MagicMock(side_effect=resolve)
    toolkit = MagicMock()
    toolkit.get_tree = AsyncMock(side_effect=KeyError("no decoration snapshot"))
    store._toolkit = MagicMock(return_value=toolkit)
    return store


def _save(store: Bookstore, scope: str, tree_name: str, rev: DocumentRevision) -> None:
    """Persist ``rev`` where the origin's SegmentStore will look for it."""
    SegmentStore(store._location(scope).trees_dir).save_revision(tree_name, rev)


@pytest.mark.asyncio
async def test_scope_and_dual_result_shapes(tmp_path: Path) -> None:
    """Filtered searches normalize LLM/BM25 candidates without scope leakage."""
    rev = _revision(f"{SECOND_PARAGRAPH}\n\n{THIRD_PARAGRAPH}")
    cards = [_card("book-a", "project"), _card("book-b", "global")]
    store = _bookstore(tmp_path, cards)
    _save(store, "project", "book-a", rev)
    _save(store, "global", "book-b", rev)
    nodes = {"n1": [0], "n2": [1]}

    async def read(book_id: str, node_id: Optional[str] = None, max_chars: int = 12000, **_: Any) -> dict:
        return _read(rev, book_id, nodes[node_id], max_chars)

    store.read_segments = AsyncMock(side_effect=read)

    # Constructor validation.
    for kwargs in ({"max_books": True}, {"max_books": 11}, {"top_k": 51}, {"top_k": 0}, {"excerpt_chars": -1},
                   {"scope": "team"}, {"timeout": float("inf")}, {"timeout": 0}, {"book_ids": "book-a"}):
        with pytest.raises(ValueError):
            BookstoreOrigin(store, **kwargs)
    origin = BookstoreOrigin(store)
    assert origin.kind is SearchOriginKind.BOOKSTORE and origin.supports_fts is False

    # LLM shape (node_list), unfiltered: Bookstore shortlists itself, duplicates collapse.
    store.search.return_value = {
        "books": [{"book_id": "book-a", "title": "A", "scope": "project", "node_list": ["n1", "n1", "n2"],
                   "context": "SYNTHETIC CONTEXT MUST NOT BE EVIDENCE"}]
    }
    hits = await origin.search("judgement", 10)
    store.search.assert_awaited_with("judgement", max_books=3, top_k=5)
    assert [hit.content for hit in hits] == [SECOND_PARAGRAPH, THIRD_PARAGRAPH]
    assert [hit.native_rank for hit in hits] == [1, 2]
    assert all("SYNTHETIC" not in hit.content for hit in hits)
    assert [hit.metadata["node_id"] for hit in hits] == ["n1", "n2"]
    assert all(hit.score is None for hit in hits)

    # BM25 shape (results[].node_id) keeps native scores; top_k caps nodes per book.
    store.search.return_value = {
        "books": [{"book_id": "book-a", "title": "A", "scope": "project",
                   "results": [{"node_id": "n2", "score": 3.5}, {"node_id": "n1", "score": 1.25}]}]
    }
    hits = await BookstoreOrigin(store, top_k=1).search("judgement", 10)
    assert [(hit.metadata["node_id"], hit.score) for hit in hits] == [("n2", 3.5)]

    # Scope filter: only global books are passed and a leaked project book is dropped.
    store.search.reset_mock()
    store.search.return_value = {
        "books": [
            {"book_id": "book-a", "node_list": ["n1"]},
            {"book_id": "book-b", "scope": "global", "node_list": ["n1"]},
        ]
    }
    hits = await BookstoreOrigin(store, scope="global").search("judgement", 5)
    assert store.search.await_args.kwargs["book_ids"] == ["book-b"]
    assert {hit.metadata["book_id"] for hit in hits} == {"book-b"}
    assert hits[0].metadata["scope"] == "global"

    # Catalog relevance orders the filtered set; stable catalog order is the fallback.
    store.catalog_search.return_value = [cards[1]]
    await BookstoreOrigin(store, book_ids=["book-a", "book-b"]).search("judgement", 5)
    assert store.search.await_args.kwargs["book_ids"] == ["book-b", "book-a"]
    await BookstoreOrigin(store, book_ids=["book-a", "book-b"], max_books=1).search("judgement", 5)
    assert store.search.await_args.kwargs["book_ids"] == ["book-b"]

    # Empty filters never fall back to an unfiltered Bookstore.search.
    store.search.reset_mock()
    project_only = _bookstore(tmp_path / "p", [_card("book-a", "project")])
    section = await BookstoreOrigin(project_only, scope="global").search_section("judgement", 5)
    assert section.hits == [] and "filter" in (section.note or "")
    project_only.search.assert_not_awaited()
    assert await BookstoreOrigin(store, book_ids=[]).search("judgement", 5) == []
    assert await origin.search("judgement", 0) == []
    store.search.assert_not_awaited()

    # Unknown explicit ids are an explanatory error, not a silent fallback.
    with pytest.raises(BookstoreError, match="ghost"):
        await BookstoreOrigin(store, book_ids=["book-a", "ghost"]).search("judgement", 5)
    store.search.assert_not_awaited()
    store.agentic_retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_pinned_clipped_excerpts(tmp_path: Path) -> None:
    """Evidence is verified against stored revision text, including clipping below 500."""
    rev = _revision(f"{LONG_PARAGRAPH.strip()}\n\n{SECOND_PARAGRAPH}\n\n{THIRD_PARAGRAPH}")
    long_text = rev.segments[0].text
    assert len(long_text) > 500
    store = _bookstore(tmp_path, [_card("book-a", "project", title="Critique")])
    _save(store, "project", "book-a", rev)
    other = _revision("Entirely different text in a superseded snapshot.")
    reads: dict[str, dict[str, Any]] = {}

    async def read(book_id: str, node_id: Optional[str] = None, max_chars: int = 12000, **_: Any) -> dict:
        if node_id == "legacy":
            raise BookstoreError("book has no segments — reindex it or run pageindex_index_segments")
        if node_id == "gone":
            raise BookstoreError("revision unavailable: doc-1@0123456789abcdef")
        spec = reads[node_id]
        return _read(spec.get("rev", rev), book_id, spec["seqs"], max_chars, **spec.get("kw", {}))

    store.read_segments = AsyncMock(side_effect=read)
    load_threads: list[int] = []
    original = SegmentStore.load_revision

    def tracking(self: SegmentStore, *args: Any) -> Optional[DocumentRevision]:
        load_threads.append(threading.get_ident())
        return original(self, *args)

    SegmentStore.load_revision = tracking  # type: ignore[method-assign]
    try:
        reads.update(
            {
                "clip": {"seqs": [0]},
                "offset": {"seqs": [0], "kw": {"first_offset": 10}},
                "multi": {"seqs": [1, 2]},
                "tampered": {"seqs": [1], "kw": {"tamper": True}},
                "stale": {"seqs": [0], "rev": other, "kw": {"revision": other.revision}},
            }
        )
        store.search.return_value = {
            "books": [{"book_id": "book-a", "node_list": ["clip", "offset", "tampered", "stale", "legacy",
                                                          "gone"]}]
        }
        origin = BookstoreOrigin(store, top_k=10, excerpt_chars=40)
        section = await origin.search_section("categories", 10)
        store.search.return_value = {"books": [{"book_id": "book-a", "node_list": ["multi"]}]}
        multi = await BookstoreOrigin(store, excerpt_chars=100).search("categories", 10)
    finally:
        SegmentStore.load_revision = original  # type: ignore[method-assign]

    assert load_threads and threading.get_ident() not in load_threads
    hits = section.hits
    by_node: dict[str, list[OriginHit]] = {}
    for hit in hits:
        by_node.setdefault(hit.metadata["node_id"], []).append(hit)
    assert set(by_node) == {"clip", "offset"}

    clip = by_node["clip"][0]
    assert clip.content == long_text[:40] and len(clip.content) == 40
    citation = clip.metadata["citation"]
    assert (citation["start"], citation["end"]) == (0, 40)
    assert rev.segments[citation["seq"]].text[citation["start"]:citation["end"]] == clip.content

    offset = by_node["offset"][0]
    assert offset.content == long_text[10:50]
    assert (offset.metadata["citation"]["start"], offset.metadata["citation"]["end"]) == (10, 50)

    # Two segments of one node: never joined, the per-node allowance is shared.
    assert [hit.metadata["citation"]["seq"] for hit in multi] == [1, 2]
    assert multi[0].content == SECOND_PARAGRAPH
    assert multi[1].content == THIRD_PARAGRAPH[: 100 - len(SECOND_PARAGRAPH)]
    assert (multi[1].metadata["citation"]["start"], multi[1].metadata["citation"]["end"]) == (
        0,
        100 - len(SECOND_PARAGRAPH),
    )
    assert [hit.native_rank for hit in multi] == [1, 2]

    # Full citation metadata, decorated with book identity, pinned to the read revision.
    assert set(citation) >= {"doc_id", "revision", "seq", "start", "end", "page", "ordinal", "section",
                             "label", "document", "excerpt", "book_id", "title"}
    assert citation["revision"] == rev.revision and citation["document"] == "Synthetic Book"
    assert citation["book_id"] == "book-a" and citation["title"] == "Critique"
    assert citation["section_path"] == ["Chapter One"] and citation["chapter"] == "Chapter One"
    assert clip.metadata["generation"] == 7 and clip.metadata["book_title"] == "Critique"
    assert clip.id == f"book-a:doc-1@{rev.revision}#0:0-40"
    assert [hit.native_rank for hit in hits] == list(range(1, len(hits) + 1))

    note = section.note or ""
    assert "1 legacy book(s)" in note
    assert "2 stale or missing revision(s)" in note
    assert "1 invalid excerpt(s)" in note
    assert note.startswith("some candidate evidence was skipped")


@pytest.mark.asyncio
async def test_limits_notes_and_cancellation(tmp_path: Path) -> None:
    """Concurrent reads preserve caps/order and per-request diagnostics."""
    rev = _revision("\n\n".join(f"Paragraph number {i} discusses topic {i} in detail." for i in range(10)))
    store = _bookstore(tmp_path, [_card("book-a")])
    _save(store, "project", "book-a", rev)
    active = 0
    peak = 0

    async def read(book_id: str, node_id: Optional[str] = None, max_chars: int = 12000, **_: Any) -> dict:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            index = int(node_id[1:])
            await asyncio.sleep(0.001 * (10 - index))  # later candidates finish first
            return _read(rev, book_id, [index], max_chars)
        finally:
            active -= 1

    store.read_segments = AsyncMock(side_effect=read)
    node_ids = [f"n{i}" for i in range(10)] + ["n0"]  # duplicate candidate collapses
    store.search.return_value = {"books": [{"book_id": "book-a", "node_list": node_ids}]}
    hits = await BookstoreOrigin(store, top_k=50).search("topic", 3)
    assert peak == 4
    assert store.read_segments.await_count == 10
    assert [hit.content for hit in hits] == [rev.segments[i].text for i in range(3)]
    assert [hit.native_rank for hit in hits] == [1, 2, 3]

    # Request-local notes: a healthy and an all-skipped request overlap without leaking.
    healthy = _bookstore(tmp_path / "h", [_card("book-a")])
    _save(healthy, "project", "book-a", rev)
    broken = _bookstore(tmp_path / "b", [_card("book-a")])
    gate = asyncio.Event()

    async def healthy_read(book_id: str, node_id: Optional[str] = None, max_chars: int = 12000, **_: Any) -> dict:
        await gate.wait()
        return _read(rev, book_id, [0], max_chars)

    async def legacy_read(*args: Any, **kwargs: Any) -> dict:
        gate.set()
        raise BookstoreError("book has no segments — reindex it or run pageindex_index_segments")

    healthy.read_segments = AsyncMock(side_effect=healthy_read)
    broken.read_segments = AsyncMock(side_effect=legacy_read)
    for facade in (healthy, broken):
        facade.search.return_value = {"books": [{"book_id": "book-a", "node_list": ["n0", "n1"]}]}
    ok_section, skipped_section = await asyncio.gather(
        BookstoreOrigin(healthy).search_section("topic", 5),
        BookstoreOrigin(broken).search_section("topic", 5),
    )
    assert isinstance(ok_section, OriginSection) and ok_section.note is None and len(ok_section.hits) == 1
    assert skipped_section.hits == [] and skipped_section.status == "ok"
    assert skipped_section.note == "all candidate evidence was skipped: 1 legacy book(s) without segments"
    assert not hasattr(BookstoreOrigin(healthy), "last_note")

    # Explicit timeout cancels child reads and releases their permits.
    blocked = _bookstore(tmp_path / "t", [_card("book-a")])
    cancelled: list[str] = []
    forever = asyncio.Event()

    async def blocking_read(book_id: str, node_id: Optional[str] = None, **_: Any) -> dict:
        try:
            await forever.wait()
        except asyncio.CancelledError:
            cancelled.append(node_id)
            raise
        return {}

    blocked.read_segments = AsyncMock(side_effect=blocking_read)
    blocked.search.return_value = {"books": [{"book_id": "book-a", "node_list": [f"n{i}" for i in range(6)]}]}
    with pytest.raises(asyncio.TimeoutError):
        await BookstoreOrigin(blocked, top_k=10, timeout=0.05).search("topic", 5)
    await asyncio.sleep(0)
    assert sorted(cancelled) == ["n0", "n1", "n2", "n3"]
    blocked.agentic_retrieve.assert_not_awaited()
    store.agentic_retrieve.assert_not_awaited()

    # Whole-backend failures (missing bm25s) still raise for the toolkit to isolate.
    store.search.side_effect = ImportError("bm25s is required for BM25 search")
    with pytest.raises(ImportError, match="bm25s"):
        await BookstoreOrigin(store).search_section("topic", 5)


def test_import_isolation_and_enum_compatibility() -> None:
    """Origin imports stay light and existing origin kinds keep their values."""
    assert {kind.value for kind in SearchOriginKind} == {"vector", "pageindex", "graphindex", "wiki", "bookstore"}
    code = (
        "import sys\n"
        "from parrot_tools.multistoresearch.origins import BookstoreOrigin, PageIndexOrigin, ParrotWikiOrigin\n"
        "assert 'parrot.knowledge.bookstore.library' not in sys.modules, 'Bookstore imported eagerly'\n"
    )
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
    completed = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr[-2000:]
