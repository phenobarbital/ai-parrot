"""Deterministic PDF structure candidates (FEAT-845 M3): bookmarks, printed headings, page fallback.

Pure functions over a ``LayoutProfile`` and the revision's ``Segment`` list — no I/O.
"""

from __future__ import annotations

import logging
import math
import re
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
        return CandidateScore(source="bookmarks", confidence=0.0, entries=len(usable), anchored=0, rejected=reason), []
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
    return CandidateScore(source="bookmarks", confidence=confidence, entries=len(usable), anchored=anchored), items


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
