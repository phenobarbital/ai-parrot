"""Deterministic PDF structure candidates (FEAT-845 M3): bookmarks, printed headings, page fallback.

Pure functions over a ``LayoutProfile`` and the revision's ``Segment`` list — no I/O.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Literal, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex.layout import LayoutProfile, StructureMode, StructureSource, running_key
from parrot.knowledge.pageindex.segments import Segment, _heading_text, _titles_match, normalize_title

logger = logging.getLogger(__name__)

_EMPHASIS_RE = re.compile(r"\*\*|__|~~|`")
MAX_HEADING_WORDS = 20
MAX_HEADINGS_PER_PAGE = 8
MIN_CONTAINED_CHARS = 3


class CandidateScore(BaseModel):
    """Confidence of one deterministic structure candidate."""

    source: Literal["bookmarks", "layout"]
    confidence: float
    entries: int
    anchored: int
    rejected: Optional[str] = None
    dropped: int = 0  # out-of-order bookmarks removed before scoring (bookmarks candidate only)


class StructureReport(BaseModel):
    """How a PDF's structure was chosen (returned by the builder and ``import_pdf``)."""

    source: StructureSource
    mode: StructureMode
    min_confidence: float
    confidence: Optional[float] = None
    candidates: list[CandidateScore] = Field(default_factory=list)
    inserted_headings: int = 0
    body_size: Optional[int] = None
    running_lines: int = 0
    llm_used: bool = False
    llm_error: Optional[str] = None


class StructureResult(BaseModel):
    """A chosen deterministic structure: PageIndex nodes carrying a transient ``anchor``."""

    source: StructureSource
    structure: list[dict]
    report: StructureReport


def heading_title(text: str) -> str:
    """Remove ATX and emphasis markers and collapse whitespace."""
    stripped = _EMPHASIS_RE.sub("", _heading_text(text)).strip()
    if len(stripped) >= 2 and stripped.startswith("_") and stripped.endswith("_"):
        stripped = stripped[1:-1]
    return " ".join(stripped.split())


def _segments_by_page(segments: Sequence[Segment]) -> dict[int, list[Segment]]:
    """Return segments with pages grouped by page and kept in input order."""
    pages: dict[int, list[Segment]] = {}
    for seg in segments:
        if seg.page is not None:
            pages.setdefault(seg.page, []).append(seg)
    return pages


def _anchor(seg: Segment) -> dict[str, int]:
    """Return the stable page-local address of a segment."""
    return {"page": int(seg.page or 0), "ordinal": seg.ordinal}


def _anchor_heading(title: str, page_segments: Sequence[Segment], used: set[tuple[int, int]]) -> Optional[Segment]:
    """Return the first unused heading equal to ``title``, then the first matching one."""
    headings = [s for s in page_segments if s.kind == "heading" and (s.page, s.ordinal) not in used]
    wanted = normalize_title(title)
    for seg in headings:
        if wanted and normalize_title(heading_title(seg.text)) == wanted:
            return seg
    for seg in headings:
        if _titles_match(heading_title(seg.text), title):
            return seg
    return None


def score_bookmarks(profile: LayoutProfile, segments: Sequence[Segment]) -> tuple[CandidateScore, list[dict]]:
    """Score and anchor usable bookmarks against segments from their pages."""
    usable = list(profile.bookmarks)
    if profile.bookmark_rejection or not usable:
        reason = profile.bookmark_rejection or "no usable bookmarks"
        score = CandidateScore(
            source="bookmarks",
            confidence=0.0,
            entries=len(usable),
            anchored=0,
            rejected=reason,
            dropped=profile.bookmarks_dropped,
        )
        return score, []
    by_page = _segments_by_page(segments)
    used: set[tuple[int, int]] = set()
    items: list[dict] = []
    found = anchored = 0
    for bm in usable:
        page_segments = by_page.get(bm.page, [])
        seg = _anchor_heading(bm.title, page_segments, used)
        if seg is not None:
            used.add((int(seg.page or 0), seg.ordinal))
            anchored += 1
            found += 1
        else:
            wanted = normalize_title(bm.title)
            if len(wanted) >= MIN_CONTAINED_CHARS and any(
                wanted in normalize_title(heading_title(candidate.text)) for candidate in page_segments
            ):
                found += 1
        items.append(
            {
                "depth": bm.level,
                "title": bm.title,
                "page": bm.page,
                "anchor": _anchor(seg) if seg is not None else None,
                "level": seg.level if seg is not None else None,
            }
        )
    confidence = round(found / len(usable), 3)
    logger.debug("bookmarks: %d usable, %d found, %d anchored -> %.3f", len(usable), found, anchored, confidence)
    score = CandidateScore(
        source="bookmarks",
        confidence=confidence,
        entries=len(usable),
        anchored=anchored,
        dropped=profile.bookmarks_dropped,
    )
    return score, items


def score_layout(profile: LayoutProfile, segments: Sequence[Segment]) -> tuple[CandidateScore, list[dict]]:
    """Score non-running heading segments using cleanliness, density, and starting position."""
    running = {line.key for line in profile.running}
    headings = [
        segment
        for segment in segments
        if segment.kind == "heading"
        and heading_title(segment.text)
        and running_key(heading_title(segment.text)) not in running
    ]
    levels = sorted({segment.level for segment in headings if segment.level is not None})
    depth_of = {level: rank + 1 for rank, level in enumerate(levels)}
    items = [
        {
            "depth": depth_of.get(segment.level, 1),
            "title": heading_title(segment.text),
            "page": int(segment.page or 1),
            "anchor": _anchor(segment),
            "level": segment.level,
        }
        for segment in headings
    ]
    if len(headings) < 2:
        return (
            CandidateScore(
                source="layout",
                confidence=0.0,
                entries=len(headings),
                anchored=len(headings),
                rejected="fewer than two headings",
            ),
            items,
        )
    clean_count = sum(
        len(heading_title(segment.text).split()) <= MAX_HEADING_WORDS and not heading_title(segment.text).endswith(".")
        for segment in headings
    )
    clean = clean_count / len(headings)
    density = len(headings) / max(1, profile.page_count)
    density_factor = 1.0 if density <= MAX_HEADINGS_PER_PAGE else MAX_HEADINGS_PER_PAGE / density
    start_limit = max(3, math.ceil(0.1 * profile.page_count))
    start_factor = 1.0 if int(headings[0].page or 1) <= start_limit else 0.5
    confidence = round(clean * density_factor * start_factor, 3)
    logger.debug(
        "layout: %d headings, clean=%.3f, density_factor=%.3f, start_factor=%.3f -> %.3f",
        len(headings),
        clean,
        density_factor,
        start_factor,
        confidence,
    )
    return CandidateScore(source="layout", confidence=confidence, entries=len(headings), anchored=len(headings)), items


def page_structure(page_count: int, doc_name: str) -> list[dict]:
    """Return a document root with one ``Page <n>`` child per page."""
    children = [{"title": f"Page {n}", "start_index": n, "end_index": n} for n in range(1, page_count + 1)]
    root: dict = {"title": Path(doc_name).stem or doc_name, "start_index": 1, "end_index": max(1, page_count)}
    if children:
        root["nodes"] = children
    return [root]


def _level_to_depth(anchored: Sequence[dict]) -> dict[int, int]:
    """Map heading levels to their most common anchored bookmark depths, strictly increasing with the level.

    The majority vote picks, per level, the most common depth (ties to the shallower one). Levels are then visited
    in ascending order and kept only when their depth is greater than the depth kept for the nearest shallower
    level; ``_placed_depth`` places the headings of a dropped level from the nearest shallower mapped level. A
    single anchor at a deep level (NIST 800-53's 10 pt ``PL-10`` control) therefore cannot pull every heading of
    that level up to its depth.

    Args:
        anchored: Bookmark items anchored to a heading segment, each with ``level`` and ``depth``.

    Returns:
        The level-to-depth map, strictly increasing in depth.
    """
    counts: dict[int, Counter] = {}
    for item in anchored:
        counts.setdefault(int(item["level"]), Counter())[int(item["depth"])] += 1
    majority = {level: min(count, key=lambda depth: (-count[depth], depth)) for level, count in counts.items()}
    mapping: dict[int, int] = {}
    for level in sorted(majority):
        if mapping and majority[level] <= mapping[max(mapping)]:
            continue
        mapping[level] = majority[level]
    return mapping


def _placed_depth(level: Optional[int], mapping: dict[int, int]) -> Optional[int]:
    """Return the placement depth for an unbookmarked heading level."""
    if level is None or not mapping:
        return None
    if level in mapping:
        return mapping[level]
    lower_levels = [mapped_level for mapped_level in mapping if mapped_level < level]
    if not lower_levels:
        return None
    nearest_level = max(lower_levels)
    return mapping[nearest_level] + (level - nearest_level)


def _position_key(item: dict) -> tuple[int, int]:
    """Return a document position, placing unanchored items first on their page."""
    anchor = item.get("anchor")
    return (int(item["page"]), int(anchor["ordinal"]) if anchor else -1)


def insert_layout_headings(
    bookmark_items: list[dict], profile: LayoutProfile, segments: Sequence[Segment]
) -> tuple[list[dict], int]:
    """Apply the hybrid rule by inserting compatible unbookmarked layout headings."""
    anchored = [item for item in bookmark_items if item.get("anchor") is not None and item.get("level") is not None]
    if not anchored:
        return list(bookmark_items), 0
    mapping = _level_to_depth(anchored)
    taken = {(item["anchor"]["page"], item["anchor"]["ordinal"]) for item in anchored}
    _, layout_items = score_layout(profile, segments)
    inserted: list[dict] = []
    for item in layout_items:
        if (item["anchor"]["page"], item["anchor"]["ordinal"]) in taken:
            continue
        depth = _placed_depth(item["level"], mapping)
        if depth is not None:
            inserted.append({**item, "depth": depth})
    merged = sorted([*bookmark_items, *inserted], key=_position_key)
    logger.debug("hybrid: mapping=%s, %d headings inserted", mapping, len(inserted))
    return merged, len(inserted)


def _first_content_ordinals(segments: Sequence[Segment], profile: LayoutProfile) -> dict[int, int]:
    """Return each page's first ordinal after skipping configured running lines."""
    running = {line.key for line in profile.running}
    first: dict[int, int] = {}
    for page, page_segments in _segments_by_page(segments).items():
        for segment in page_segments:
            if running_key(heading_title(segment.text)) not in running:
                first[page] = segment.ordinal
                break
    return first


def items_to_tree(items: Sequence[dict], segments: Sequence[Segment], profile: LayoutProfile) -> list[dict]:
    """Build a nested PageIndex tree with LLM-path page-range conventions."""
    if not items:
        return []
    flat = list(items)
    if int(flat[0]["page"]) > 1:
        flat.insert(0, {"depth": 1, "title": "Preface", "page": 1, "anchor": None, "level": None})
    first = _first_content_ordinals(segments, profile)
    nodes: list[dict] = []
    for index, item in enumerate(flat):
        start = int(item["page"])
        if index == len(flat) - 1:
            end = profile.page_count
        else:
            next_item = flat[index + 1]
            next_anchor = next_item.get("anchor")
            next_page = int(next_item["page"])
            appears_at_start = next_anchor is not None and next_anchor["ordinal"] == first.get(next_page)
            end = next_page - 1 if appears_at_start else next_page
        node: dict = {"title": item["title"], "start_index": start, "end_index": max(end, start)}
        if item.get("anchor"):
            node["anchor"] = dict(item["anchor"])
        nodes.append(node)
    roots: list[dict] = []
    stack: list[tuple[int, dict]] = []
    previous = 0
    for item, node in zip(flat, nodes, strict=False):
        depth = max(1, min(int(item["depth"]), previous + 1))
        while stack and stack[-1][0] >= depth:
            stack.pop()
        (stack[-1][1].setdefault("nodes", []) if stack else roots).append(node)
        stack.append((depth, node))
        previous = depth
    return roots


def build_structure(
    profile: LayoutProfile,
    segments: Sequence[Segment],
    *,
    mode: StructureMode = "auto",
    min_confidence: float = 0.6,
) -> Optional[StructureResult]:
    """Return the selected deterministic structure or ``None`` when no candidate qualifies."""
    if mode == "llm":
        return None
    bookmarks, bookmark_items = score_bookmarks(profile, segments)
    layout, layout_items = score_layout(profile, segments)
    inserted = 0
    if bookmarks.confidence >= min_confidence:
        source: StructureSource = "bookmarks"
        items = bookmark_items
        confidence = bookmarks.confidence
        if layout.confidence >= min_confidence:
            items, inserted = insert_layout_headings(bookmark_items, profile, segments)
            if inserted:
                source = "hybrid"
                confidence = min(bookmarks.confidence, layout.confidence)
    elif layout.confidence >= min_confidence:
        source = "layout"
        items = layout_items
        confidence = layout.confidence
    else:
        logger.debug(
            "no deterministic structure: bookmarks=%.3f, layout=%.3f, threshold=%.3f",
            bookmarks.confidence,
            layout.confidence,
            min_confidence,
        )
        return None
    report = StructureReport(
        source=source,
        mode=mode,
        min_confidence=min_confidence,
        confidence=confidence,
        candidates=[bookmarks, layout],
        inserted_headings=inserted,
        body_size=profile.body_size,
        running_lines=len(profile.running),
    )
    return StructureResult(source=source, structure=items_to_tree(items, segments, profile), report=report)
