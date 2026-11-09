"""Deterministic regression coverage for Bookstore's segment revision guard."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError
from parrot.knowledge.pageindex.segments import RevisionMismatchError


def _store_with_read(tmp_path: Path, result: dict[str, object]) -> tuple[Bookstore, MagicMock]:
    """Build a bookstore whose segment read returns ``result`` without filesystem I/O."""
    location = LibraryLocation(scope="project", root=tmp_path / "library")
    store = Bookstore([location])
    card = MagicMock(book_id="book-1", title="Synthetic Book", tree_name="synthetic-book")
    toolkit = MagicMock()
    toolkit.read_segments = AsyncMock(return_value=result)
    store.resolve_book = MagicMock(return_value=(card, location))
    store._toolkit = MagicMock(return_value=toolkit)
    store._document_of = AsyncMock(return_value={"doc_id": "doc-1", "revision": "before-reimport"})
    return store, toolkit


@pytest.mark.asyncio
async def test_returned_revision_guard(tmp_path: Path) -> None:
    """Matching and mismatching result revisions are distinguished."""
    result = {"revision": "revision-1", "segments": [], "framed": "safe text"}
    store, toolkit = _store_with_read(tmp_path, result)

    matching = await store.read_segments("book-1", 0, 1, expected_revision="revision-1")
    omitted = await store.read_segments("book-1", expected_revision=None)

    assert matching == {"book_id": "book-1", "book_title": "Synthetic Book", **result}
    assert omitted == matching
    assert toolkit.read_segments.await_count == 2

    with pytest.raises(RevisionMismatchError, match="Expected revision 'revision-2'"):
        await store.read_segments("book-1", expected_revision="revision-2")

    toolkit.read_segments.side_effect = ValueError("legacy read failure")
    with pytest.raises(BookstoreError, match="legacy read failure"):
        await store.read_segments("book-1")


@pytest.mark.asyncio
async def test_lookup_read_race(tmp_path: Path) -> None:
    """Re-import after document lookup cannot expose mismatched text."""
    result = {"revision": "after-reimport", "segments": [], "framed": "new snapshot text"}
    store, toolkit = _store_with_read(tmp_path, result)
    events: list[str] = []

    async def document_lookup(*args: object) -> dict[str, str]:
        events.append("lookup")
        return {"doc_id": "doc-1", "revision": "before-reimport"}

    async def read_after_reimport(*args: object, **kwargs: object) -> dict[str, object]:
        assert events == ["lookup"]
        events.append("read")
        return result

    store._document_of = AsyncMock(side_effect=document_lookup)
    toolkit.read_segments = AsyncMock(side_effect=read_after_reimport)

    with pytest.raises(RevisionMismatchError, match="before-reimport"):
        await store.read_segments("book-1", expected_revision="before-reimport")

    assert events == ["lookup", "read"]


@pytest.mark.asyncio
async def test_cursor_mismatch(tmp_path: Path) -> None:
    """Cursor mismatch retains its typed exception."""
    store, toolkit = _store_with_read(tmp_path, {"revision": "revision-1", "segments": [], "framed": "text"})
    mismatch = RevisionMismatchError("cursor names another revision")
    toolkit.read_segments.side_effect = mismatch

    with pytest.raises(RevisionMismatchError) as raised:
        await store.read_segments("book-1", cursor="doc-1@old#0+0")

    assert raised.value is mismatch
