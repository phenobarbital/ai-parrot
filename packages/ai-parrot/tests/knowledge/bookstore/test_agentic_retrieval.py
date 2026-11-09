"""Deterministic regression coverage for Bookstore's agentic facade."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError


def _bookstore(tmp_path: Path, *, with_llm: bool = True) -> Bookstore:
    """Build a facade with a single synthetic project location."""
    adapter = MagicMock() if with_llm else None
    return Bookstore([LibraryLocation(scope="project", root=tmp_path / "library")], adapter=adapter)


def _card() -> MagicMock:
    """Return the card fields exercised by the facade."""
    return MagicMock(book_id="book", title="Synthetic Book", tree_name="book", toc=[])


@pytest.mark.asyncio
async def test_delegate_once(tmp_path: Path) -> None:
    """Bookstore delegates once, forwards arguments, and preserves evidence fields."""
    bookstore = _bookstore(tmp_path)
    card = _card()
    toolkit = MagicMock()
    toolkit.list_documents = AsyncMock(return_value=[{"doc_id": "doc", "revision": "rev"}])
    toolkit.agentic_retrieve = AsyncMock(
        return_value={
            "generation": 3,
            "answer": "answer",
            "grounded": True,
            "stopped": "budget",
            "usage": {"tokens": 2},
            "citations": [
                {"doc_id": "doc", "revision": "rev", "seq": 1, "start": 4, "end": 9, "excerpt": "exact", "label": "p. 1"}
            ],
        }
    )
    toolkit.get_tree = AsyncMock(
        return_value={
            "generation": {"id": 3},
            "structure": [
                {"title": "Chapter", "doc_id": "doc", "revision": "rev", "owned": [[0, 3]], "nodes": []}
            ],
        }
    )
    bookstore.resolve_book = MagicMock(return_value=(card, LibraryLocation(scope="project", root=tmp_path / "library")))
    bookstore._toolkit = MagicMock(return_value=toolkit)

    bundle = await bookstore.agentic_retrieve("book", "question", 2, False, 100, 3, 4.5)

    toolkit.agentic_retrieve.assert_awaited_once_with(
        "book", "question", top_k=2, draft_answer=False, budget_chars=100, max_reads=3, timeout_s=4.5
    )
    assert bundle["answer"] == "answer"
    assert bundle["grounded"] is True
    assert bundle["stopped"] == "budget"
    assert bundle["usage"] == {"tokens": 2}
    assert bundle["citations"][0]["start"] == 4
    assert bundle["citations"][0]["end"] == 9
    assert bundle["citations"][0]["section_path"] == ["Chapter"]
    assert bundle["rendered_citations"] == "[Synthetic Book, Chapter, p. 1]"


@pytest.mark.asyncio
async def test_generation_safe_labels(tmp_path: Path) -> None:
    """Old citations retain their stored section rather than current ownership."""
    bookstore = _bookstore(tmp_path)
    card = _card()
    toolkit = MagicMock()
    toolkit.get_tree = AsyncMock(
        return_value={
            "generation": {"id": 2},
            "structure": [
                {"title": "Current Chapter", "doc_id": "doc", "revision": "new", "owned": [[0, 3]], "nodes": []}
            ],
        }
    )
    bookstore._toolkit = MagicMock(return_value=toolkit)
    source = {
        "generation": 1,
        "citations": [
            {
                "doc_id": "doc",
                "revision": "old",
                "seq": 1,
                "start": 2,
                "end": 5,
                "excerpt": "exact",
                "label": "p. 1",
                "section": ["Stored Chapter", "Stored Section"],
            }
        ],
        "ledger": [{"start": 2, "end": 5}],
    }

    decorated = await bookstore._decorate_citations(card, "project", source)

    assert source["citations"][0] == {
        "doc_id": "doc",
        "revision": "old",
        "seq": 1,
        "start": 2,
        "end": 5,
        "excerpt": "exact",
        "label": "p. 1",
        "section": ["Stored Chapter", "Stored Section"],
    }
    assert decorated["citations"][0]["section_path"] == ["Stored Chapter", "Stored Section"]
    assert decorated["citations"][0]["chapter"] == "Stored Chapter"
    assert decorated["ledger"] == source["ledger"]


@pytest.mark.asyncio
async def test_visible_error_contract(tmp_path: Path) -> None:
    """Missing models and segments fail visibly without a PageIndex provider call."""
    bookstore = _bookstore(tmp_path, with_llm=False)
    card = _card()
    bookstore.resolve_book = MagicMock(return_value=(card, LibraryLocation(scope="project", root=tmp_path / "library")))
    toolkit = MagicMock()
    bookstore._toolkit = MagicMock(return_value=toolkit)

    with pytest.raises(BookstoreError, match="requires an LLM"):
        await bookstore.agentic_retrieve("book", "question")
    toolkit.agentic_retrieve.assert_not_called()

    bookstore = _bookstore(tmp_path)
    bookstore.resolve_book = MagicMock(return_value=(card, LibraryLocation(scope="project", root=tmp_path / "library")))
    toolkit = MagicMock()
    toolkit.list_documents = AsyncMock(return_value=[])
    toolkit.agentic_retrieve = AsyncMock()
    bookstore._toolkit = MagicMock(return_value=toolkit)

    with pytest.raises(BookstoreError, match="no segments"):
        await bookstore.agentic_retrieve("book", "question")
    toolkit.agentic_retrieve.assert_not_awaited()

    toolkit.list_documents = AsyncMock(return_value=[{"doc_id": "doc", "revision": "rev"}])
    toolkit.agentic_retrieve = AsyncMock(
        side_effect=ValueError("NoLoopClient (stub) declares supports_tool_loop=False")
    )
    with pytest.raises(BookstoreError, match="NoLoopClient"):
        await bookstore.agentic_retrieve("book", "question")

    toolkit.agentic_retrieve = AsyncMock(side_effect=ValueError("top_k must be a positive integer"))
    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        await bookstore.agentic_retrieve("book", "question", top_k=0)
