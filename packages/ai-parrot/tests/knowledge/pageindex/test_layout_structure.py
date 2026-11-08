"""FEAT-845 M3 — structure candidates, scores and page fallback (pure, hand-built inputs)."""

from __future__ import annotations

import pytest

from parrot.knowledge.pageindex.layout import Bookmark, LayoutProfile, RunningLine
from parrot.knowledge.pageindex.layout_structure import heading_title, page_structure, score_bookmarks, score_layout
from parrot.knowledge.pageindex.segments import segment_pages


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", lambda text, model="gpt-4o": max(1, len(text)))


def _segs(*pages: str):
    """Return segments of 1-based pages supplied as markdown strings."""
    return segment_pages([(number, markdown) for number, markdown in enumerate(pages, start=1)])


def _profile(page_count: int, bookmarks=(), rejection=None, running=()) -> LayoutProfile:
    """Build a valid layout profile for candidate-scoring tests."""
    return LayoutProfile(
        page_count=page_count,
        body_size=10,
        heading_sizes=[16, 12],
        bookmarks=[Bookmark(level=level, title=title, page=page) for level, title, page in bookmarks],
        bookmark_rejection=rejection,
        running=[RunningLine(key=key, band="top", pages=page_count) for key in running],
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        ("### **1 Introduction**", "1 Introduction"),
        ("## **1** **Introduction**", "1 Introduction"),
        ("# `Code`  ~~Old~~ Title", "Code Old Title"),
        ("## _Scope_", "Scope"),
        ("plain paragraph", "plain paragraph"),
    ],
)
def test_heading_title(text, expected):
    """ATX marker and emphasis are stripped and whitespace is collapsed."""
    assert heading_title(text) == expected


def test_score_bookmarks_found_and_anchored():
    """Found ratio includes paragraphs while anchors remain unique per heading."""
    segments = _segs("# Intro\n\nText.", "Para mentions Scope here.\n\n## Usage\n\nMore.")
    profile = _profile(
        2,
        bookmarks=[(1, "Intro", 1), (2, "Scope", 2), (1, "Usage", 2), (1, "Missing", 2)],
    )

    score, items = score_bookmarks(profile, segments)

    assert score.confidence == 0.75
    assert score.anchored == 2
    assert items[0]["anchor"] == {"page": 1, "ordinal": 0}
    assert items[0]["level"] == 1
    assert items[1]["anchor"] is None
    assert items[1]["level"] is None
    assert items[2]["level"] == 2

    duplicate_score, duplicate_items = score_bookmarks(
        _profile(1, bookmarks=[(1, "Intro", 1), (1, "Intro", 1)]),
        _segs("# Intro"),
    )
    assert duplicate_score.anchored == 1
    assert duplicate_items[0]["anchor"] == {"page": 1, "ordinal": 0}
    assert duplicate_items[1]["anchor"] is None

    rejected_score, rejected_items = score_bookmarks(
        _profile(2, bookmarks=[(1, "Intro", 1), (1, "Usage", 2)], rejection="non-monotonic pages"),
        segments,
    )
    assert rejected_score.confidence == 0.0
    assert rejected_score.rejected == "non-monotonic pages"
    assert rejected_items == []


def test_score_layout_factors():
    """Layout confidence applies the clean, density, and start factors exactly."""
    one_score, _ = score_layout(_profile(1), _segs("# Only"))
    assert one_score.confidence == 0.0
    assert one_score.rejected == "fewer than two headings"

    clean_score, _ = score_layout(_profile(1), _segs("# One\n\n## Two.\n\n### Three\n\n#### Four"))
    assert clean_score.confidence == 0.75

    dense_markdown = "\n\n".join(f"## Heading {number}" for number in range(20))
    dense_score, _ = score_layout(_profile(1), _segs(dense_markdown))
    assert dense_score.confidence == 0.4

    late_segments = _segs("", "", "", "", "# Late\n\n## Later")
    late_score, _ = score_layout(_profile(10), late_segments)
    assert late_score.confidence == 0.5

    running_score, running_items = score_layout(
        _profile(1, running=("acme manual",)),
        _segs("# ACME Manual\n\n## Intro\n\n### Detail"),
    )
    assert running_score.entries == 2
    assert [item["depth"] for item in running_items] == [1, 2]


def test_page_structure():
    """Page fallback uses the source stem and one child per page."""
    tree = page_structure(3, "/books/My Doc.pdf")
    assert tree == [
        {
            "title": "My Doc",
            "start_index": 1,
            "end_index": 3,
            "nodes": [
                {"title": "Page 1", "start_index": 1, "end_index": 1},
                {"title": "Page 2", "start_index": 2, "end_index": 2},
                {"title": "Page 3", "start_index": 3, "end_index": 3},
            ],
        }
    ]
