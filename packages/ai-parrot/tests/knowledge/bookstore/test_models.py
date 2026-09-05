"""Tests for bookstore models, slugs, and ToC derivation."""

from __future__ import annotations

from pathlib import Path

from parrot.knowledge.bookstore.carding import (
    derive_toc,
    fallback_card_fields,
    slugify,
    unique_slug,
)
from parrot.knowledge.bookstore.models import BookCard, TocEntry


def _card(**overrides) -> BookCard:
    data = {
        "book_id": "clean-code",
        "title": "Clean Code",
        "authors": ["Robert C. Martin"],
        "topics": ["refactoring", "naming"],
        "summary": "Line one.\nLine two.",
        "tree_name": "clean-code",
        "source_path": "/books/clean-code.pdf",
        "source_sha256": "ab" * 32,
        "source_format": "pdf",
        "added_at": "2026-09-05T00:00:00+00:00",
    }
    data.update(overrides)
    return BookCard(**data)


def test_bookcard_json_roundtrip():
    card = _card(toc=[TocEntry(node_id="0000", title="Intro", depth=1)])
    restored = BookCard.model_validate_json(card.model_dump_json())
    assert restored == card


def test_bookcard_brief_is_compact():
    brief = _card().brief()
    assert brief["book_id"] == "clean-code"
    assert brief["summary"] == "Line one."
    assert "toc" not in brief and "toc_digest" not in brief


def test_slugify_normalizes_accents_and_symbols():
    assert slugify("Cien Años de Soledad!") == "cien-anos-de-soledad"
    assert slugify("  __ ") == "book"
    assert len(slugify("x" * 300)) <= 64


def test_unique_slug_suffixes():
    taken = {"clean-code", "clean-code-2"}
    assert unique_slug("clean-code", taken) == "clean-code-3"
    assert unique_slug("other", taken) == "other"


def test_derive_toc_depth_cap_and_pages(sample_tree):
    entries, digest = derive_toc(sample_tree, max_depth=2)
    titles = [e.title for e in entries]
    assert titles == ["Chapter One", "Event Loops", "Chapter Two"]
    assert "Too Deep" not in digest
    assert entries[0].start_page == 1 and entries[0].end_page == 20
    assert "1 Chapter One (pp. 1-20)" in digest
    assert "  1.1 Event Loops (pp. 3-10)" in digest
    assert "2 Chapter Two (pp. 21-40)" in digest


def test_derive_toc_without_pages():
    tree = {"structure": [{"title": "Solo", "node_id": "0000", "nodes": []}]}
    entries, digest = derive_toc(tree)
    assert entries[0].start_page is None
    assert digest == "1 Solo"


def test_fallback_card_fields_uses_filename_and_chapters(sample_tree):
    entries, _ = derive_toc(sample_tree)
    draft = fallback_card_fields(Path("/books/the_pragmatic-programmer.pdf"), entries)
    assert draft.title == "The Pragmatic Programmer"
    assert draft.topics == ["Chapter One", "Chapter Two"]
    assert draft.summary == ""
