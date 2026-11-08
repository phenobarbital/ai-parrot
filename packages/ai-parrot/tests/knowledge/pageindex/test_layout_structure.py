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


from parrot.knowledge.pageindex.layout_structure import (
    build_structure,
    insert_layout_headings,
    items_to_tree,
)  # noqa: E402

HYBRID_PAGES = (
    "# Report Title\n\n## 1 Intro\n\nText.\n\n### 1.1 Scope\n\nText.",
    "## 2 Usage\n\nText.\n\n## Appendix\n\nText.",
)


def test_hybrid_insertion():
    """Hybrid insertion preserves siblings, nests deeper headings, and rejects shallower headings."""
    segments = _segs(*HYBRID_PAGES)
    profile = _profile(2, bookmarks=[(1, "1 Intro", 1), (1, "2 Usage", 2)])
    _, bookmark_items = score_bookmarks(profile, segments)

    items, inserted = insert_layout_headings(bookmark_items, profile, segments)

    assert inserted == 2
    assert [(item["title"], item["depth"]) for item in items] == [
        ("1 Intro", 1),
        ("1.1 Scope", 2),
        ("2 Usage", 1),
        ("Appendix", 1),
    ]
    assert "Report Title" not in [item["title"] for item in items]
    assert [node["title"] for node in items_to_tree(items, segments, profile)] == ["1 Intro", "2 Usage", "Appendix"]
    assert items_to_tree(items, segments, profile)[0]["nodes"][0]["title"] == "1.1 Scope"


def test_hybrid_rejects_noisy_layout():
    """Reliable bookmarks remain unchanged when an over-dense layout fails confidence."""
    pages = tuple(
        f"## Chapter {page}\n\n" + "\n\n".join(f"#### Note {number}" for number in range(100)) for page in range(1, 3)
    )
    profile = _profile(2, bookmarks=[(1, "Chapter 1", 1), (1, "Chapter 2", 2)])

    result = build_structure(profile, _segs(*pages), min_confidence=0.6)

    assert result is not None
    assert result.source == "bookmarks"
    assert result.report.inserted_headings == 0
    assert [candidate.source for candidate in result.report.candidates] == ["bookmarks", "layout"]
    assert result.report.candidates[1].confidence < 0.6


def test_hybrid_confidence_and_empty_mapping():
    """Hybrid confidence is the candidate minimum and unanchored bookmarks add no headings."""
    segments = _segs(HYBRID_PAGES[0], HYBRID_PAGES[1] + "\n\n## Closing.")
    profile = _profile(2, bookmarks=[(1, "1 Intro", 1), (1, "2 Usage", 2)])

    result = build_structure(profile, segments)

    assert result is not None
    assert result.source == "hybrid"
    assert result.report.confidence == min(candidate.confidence for candidate in result.report.candidates)

    unanchored_segments = _segs("Alpha marker appears here.\n\n# First", "Beta marker appears here.\n\n## Second")
    unanchored_profile = _profile(2, bookmarks=[(1, "Alpha marker", 1), (1, "Beta marker", 2)])
    score, bookmark_items = score_bookmarks(unanchored_profile, unanchored_segments)
    items, inserted = insert_layout_headings(bookmark_items, unanchored_profile, unanchored_segments)
    unanchored_result = build_structure(unanchored_profile, unanchored_segments)

    assert score.confidence == 1.0
    assert inserted == 0
    assert items == bookmark_items
    assert unanchored_result is not None
    assert unanchored_result.source == "bookmarks"
    assert unanchored_result.report.confidence == score.confidence


def test_items_to_tree_pages_and_preface():
    """Tree page ranges honor first content segments, running lines, and a Preface node."""
    segments = _segs("Front matter", "## Lead", "# Header\n\nText.\n\n## Middle", "# Header\n\n## End")
    profile = _profile(4, running=("header",))
    items = [
        {"depth": 1, "title": "Lead", "page": 2, "anchor": {"page": 2, "ordinal": 0}, "level": 2},
        {"depth": 1, "title": "Middle", "page": 3, "anchor": {"page": 3, "ordinal": 2}, "level": 2},
        {"depth": 1, "title": "End", "page": 4, "anchor": {"page": 4, "ordinal": 1}, "level": 2},
    ]

    tree = items_to_tree(items, segments, profile)

    assert [(node["title"], node["start_index"], node["end_index"]) for node in tree] == [
        ("Preface", 1, 1),
        ("Lead", 2, 3),
        ("Middle", 3, 3),
        ("End", 4, 4),
    ]
    assert all("nodes" not in node for node in tree)
    assert tree[1]["anchor"] == items[0]["anchor"]
    assert tree[1]["anchor"] is not items[0]["anchor"]


def test_choice_order_and_modes():
    """Choice prefers bookmarks, then layout, then no result; llm skips deterministic choices."""
    segments = _segs("# One", "## Two")
    layout_profile = _profile(2, rejection="non-monotonic pages")

    layout_result = build_structure(layout_profile, segments)

    assert layout_result is not None
    assert layout_result.source == "layout"
    assert layout_result.report.body_size == layout_profile.body_size
    assert layout_result.report.running_lines == len(layout_profile.running)
    mode_result = build_structure(layout_profile, segments, mode="layout")
    assert mode_result is not None
    assert mode_result.source == layout_result.source
    assert mode_result.structure == layout_result.structure
    assert mode_result.report.mode == "layout"
    assert build_structure(_profile(2), _segs("# One", "## Two."), min_confidence=0.99) is None
    assert build_structure(_profile(2, bookmarks=[(1, "One", 1), (1, "Two", 2)]), segments, mode="llm") is None
