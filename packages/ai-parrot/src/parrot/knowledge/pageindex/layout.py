"""PDF layout analysis for PageIndex structure (FEAT-845): body/heading sizes, running lines, bookmarks."""

from __future__ import annotations

import bisect
import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex.segments import _titles_match, normalize_title

try:
    import pymupdf
except ImportError:  # pragma: no cover — pyproject pins pymupdf.
    pymupdf = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

StructureSource = Literal["bookmarks", "layout", "hybrid", "llm", "pages"]
StructureMode = Literal["auto", "layout", "llm"]

MAX_SIZE_LEVELS: int = 4
RUNNING_BAND: float = 0.08
RUNNING_MIN_SHARE: float = 0.3
_HEADING_SHARE_CAP: float = 0.10
_MAX_BOLD_WORDS: int = 12
BOOKMARK_MAX_DROPPED_SHARE: float = 0.05
"""Out-of-order entries an outline may lose (share of its valid entries, rounded down) and still be used."""
_ENUM_TITLE_RE = re.compile(r"^(page|p\.?)?\s*\d+$", re.IGNORECASE)
_DIGITS_RE = re.compile(r"\d+")


class PDFStructureError(ValueError):
    """A PDF cannot be indexed (base class; tool callers see the message)."""


class UnreadablePDFError(PDFStructureError):
    """PyMuPDF could not open the file."""


class NoTextLayerError(PDFStructureError):
    """No page carries any text (scanned PDF); OCR is not supported."""


class Bookmark(BaseModel):
    """A usable, level-normalized PDF bookmark."""

    level: int
    title: str
    page: int


class RunningLine(BaseModel):
    """A repeated header or footer line."""

    key: str
    band: Literal["top", "bottom"]
    pages: int


class BoldLine(BaseModel):
    """A standalone body-size bold line and its page geometry."""

    text: str
    bbox: tuple[float, float, float, float]


class LayoutProfile(BaseModel):
    """Deterministic layout signals extracted from a PDF."""

    page_count: int
    body_size: Optional[int] = None
    heading_sizes: list[int] = Field(default_factory=list)
    running: list[RunningLine] = Field(default_factory=list)
    bold_lines: dict[int, list[BoldLine]] = Field(default_factory=dict)
    bookmarks: list[Bookmark] = Field(default_factory=list)
    bookmark_rejection: Optional[str] = None
    bookmarks_dropped: int = 0


def running_key(text: str) -> str:
    """Casefold, collapse whitespace, replace digit runs with '#'."""
    return _DIGITS_RE.sub("#", " ".join((text or "").casefold().split()))


def _is_bold(span: dict) -> bool:
    """Identify a bold span by its font flag or font name."""
    return bool(int(span.get("flags", 0)) & 16) or "bold" in str(span.get("font", "")).casefold()


def _band(y0: float, y1: float, height: float) -> Optional[Literal["top", "bottom"]]:
    """Return the running-header/footer band for a line, if it has one."""
    if height <= 0:
        return None
    if y0 < RUNNING_BAND * height:
        return "top"
    if y1 > (1.0 - RUNNING_BAND) * height:
        return "bottom"
    return None


def _keep_page_order(pages: Sequence[int]) -> list[int]:
    """Return the indices of one longest non-decreasing subsequence of ``pages``, in order.

    Deterministic patience sort (``bisect.bisect_right`` over the tails, predecessor links); empty input
    returns ``[]``.

    Args:
        pages: Page numbers in outline order.

    Returns:
        The indices of the kept entries, ascending.
    """
    tails: list[int] = []
    tail_indices: list[int] = []
    previous = [-1] * len(pages)
    for index, page in enumerate(pages):
        position = bisect.bisect_right(tails, page)
        if position == len(tails):
            tails.append(page)
            tail_indices.append(index)
        else:
            tails[position] = page
            tail_indices[position] = index
        previous[index] = tail_indices[position - 1] if position else -1
    kept: list[int] = []
    cursor = tail_indices[-1] if tail_indices else -1
    while cursor != -1:
        kept.append(cursor)
        cursor = previous[cursor]
    return kept[::-1]


def _read_bookmarks(raw_toc: list[list], page_count: int) -> tuple[list[Bookmark], Optional[str], int]:
    """Return usable normalized bookmarks, any rejection reason and the out-of-order entries dropped.

    ``raw_toc`` is ``doc.get_toc(simple=True)``: ``[[level, title, page], ...]``. Valid entries are collected
    first; when the entries outside ``_keep_page_order`` number at most
    ``floor(BOOKMARK_MAX_DROPPED_SHARE * len(entries))`` they are removed, otherwise nothing is removed and the
    outline is rejected as non-monotonic. Levels are normalized after the removal.

    Args:
        raw_toc: The PDF outline as returned by PyMuPDF.
        page_count: Number of pages in the document.

    Returns:
        ``(usable, rejection, dropped)``; ``dropped`` is 0 whenever the outline is rejected as non-monotonic.
    """
    entries: list[tuple[int, str, int]] = []
    for entry in raw_toc:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        level_raw, title_raw, page_raw = entry[:3]
        title = str(title_raw).strip()
        try:
            page = int(page_raw)
            level = int(level_raw)
        except (TypeError, ValueError):
            continue
        if not title or not 1 <= page <= page_count:
            continue
        entries.append((level, title, page))

    keep = _keep_page_order([page for _, _, page in entries])
    removable = len(entries) - len(keep)
    dropped = 0
    if 0 < removable <= math.floor(BOOKMARK_MAX_DROPPED_SHARE * len(entries)):
        entries = [entries[index] for index in keep]
        dropped = removable

    usable: list[Bookmark] = []
    previous_level = 0
    for level, title, page in entries:
        level = max(1, min(level, previous_level + 1))
        usable.append(Bookmark(level=level, title=title, page=page))
        previous_level = level

    if len(usable) < 2:
        return usable, "fewer than 2 usable entries", dropped

    for index, (previous, current) in enumerate(zip(usable, usable[1:], strict=False), start=2):
        if current.page < previous.page:
            return usable, f"non-monotonic: page decreases at entry {index}", 0

    page_entries = Counter(bookmark.page for bookmark in usable)
    one_per_page = sum(count == 1 for count in page_entries.values()) >= 0.8 * page_count
    enumeration_titles = sum(bool(_ENUM_TITLE_RE.fullmatch(bookmark.title)) for bookmark in usable) >= 0.8 * len(usable)
    if (
        page_count >= 4
        and all(bookmark.level == 1 for bookmark in usable)
        and len(usable) >= 0.8 * page_count
        and (one_per_page or enumeration_titles)
    ):
        return usable, "per-page enumeration", dropped
    return usable, None, dropped


def analyze_layout(pdf_path: str) -> LayoutProfile:
    """Analyze PDF span geometry, sizes, bold lines, running text, and bookmarks."""
    if pymupdf is None:
        raise ImportError("analyze_layout requires pymupdf; install it via the [pdf] extra.")
    try:
        doc = pymupdf.open(pdf_path)
    except RuntimeError as exc:
        raise UnreadablePDFError(f"Cannot open {Path(pdf_path).name}: {exc}") from exc
    try:
        page_count = doc.page_count
        lines: list[dict] = []
        for page_no, page in enumerate(doc, start=1):
            height = page.rect.height
            page_dict = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
            for block_no, block in enumerate(page_dict["blocks"]):
                if block.get("type") != 0:
                    continue
                block_lines = block.get("lines", [])
                for index, line in enumerate(block_lines):
                    spans = [span for span in line.get("spans", []) if str(span.get("text", "")).strip()]
                    text = "".join(str(span["text"]) for span in spans).strip()
                    bbox = line["bbox"]
                    lines.append(
                        {
                            "page": page_no,
                            "block": block_no,
                            "index": index,
                            "block_lines": len(block_lines),
                            "spans": spans,
                            "text": text,
                            "bbox": bbox,
                            "band": _band(float(bbox[1]), float(bbox[3]), height),
                            "key": running_key(text),
                        }
                    )
        raw_toc = doc.get_toc(simple=True)
    finally:
        doc.close()

    running_pages: dict[tuple[str, str], set[int]] = {}
    if page_count >= 3:
        for line in lines:
            band = line["band"]
            if band is not None and line["key"]:
                running_pages.setdefault((band, line["key"]), set()).add(line["page"])
    running_threshold = max(3, math.ceil(RUNNING_MIN_SHARE * page_count))
    running = [
        RunningLine(key=key, band=band, pages=len(pages))
        for (band, key), pages in sorted(running_pages.items())
        if len(pages) >= running_threshold
    ]
    running_keys = {(line.band, line.key) for line in running}

    counted_spans = [
        span for line in lines if (line["band"], line["key"]) not in running_keys for span in line["spans"]
    ]
    size_counts: Counter[int] = Counter()
    for span in counted_spans:
        size_counts[round(float(span["size"]))] += len(str(span["text"]))
    body_size = min(size_counts, key=lambda size: (-size_counts[size], size)) if size_counts else None
    total_characters = sum(size_counts.values())
    heading_sizes = (
        sorted(
            (
                size
                for size, count in size_counts.items()
                if size > body_size and count / total_characters <= _HEADING_SHARE_CAP
            ),
            reverse=True,
        )[:MAX_SIZE_LEVELS]
        if body_size is not None
        else []
    )

    bold_lines: dict[int, list[BoldLine]] = {}
    for line in lines:
        if (line["band"], line["key"]) in running_keys or body_size is None:
            continue
        spans = line["spans"]
        if not spans or any(round(float(span["size"])) != body_size or not _is_bold(span) for span in spans):
            continue
        text = line["text"]
        if len(text.split()) > _MAX_BOLD_WORDS or text.endswith((".", ",")):
            continue
        other_lines = [
            other
            for other in lines
            if other["page"] == line["page"] and other["block"] == line["block"] and other["index"] != line["index"]
        ]
        standalone = line["block_lines"] == 1 or (
            line["index"] == 0
            and all(not other["spans"] or not all(_is_bold(span) for span in other["spans"]) for other in other_lines)
        )
        if standalone:
            bold_lines.setdefault(line["page"], []).append(
                BoldLine(text=normalize_title(text), bbox=tuple(float(value) for value in line["bbox"]))
            )

    bookmarks, rejection, dropped = _read_bookmarks(raw_toc, page_count)
    if dropped:
        logger.info(
            "analyze_layout %s: dropped %d out-of-order bookmark(s) of %d", pdf_path, dropped, len(bookmarks) + dropped
        )
    logger.debug(
        "analyze_layout %s: %d pages, %d bookmarks, rejection=%s", pdf_path, page_count, len(bookmarks), rejection
    )
    return LayoutProfile(
        page_count=page_count,
        body_size=body_size,
        heading_sizes=heading_sizes,
        running=running,
        bold_lines=bold_lines,
        bookmarks=bookmarks,
        bookmark_rejection=rejection,
        bookmarks_dropped=dropped,
    )


class LayoutHeaders:
    """pymupdf4llm ``hdr_info`` object driven by a LayoutProfile (rules 1-6 of spec §2)."""

    TOLERANCE: float = 0.5

    def __init__(self, profile: LayoutProfile) -> None:
        self.profile = profile
        self._size_rank: dict[int, int] = {size: rank for rank, size in enumerate(profile.heading_sizes)}
        self._body_bold_prefix = "#" * (len(profile.heading_sizes) + 1) + " "
        self._running: dict[str, list[str]] = {}
        for line in profile.running:
            self._running.setdefault(line.band, []).append(line.key)
        self._bookmark_titles: dict[int, list[str]] = {}
        if profile.bookmark_rejection is None:
            for bookmark in profile.bookmarks:
                self._bookmark_titles.setdefault(bookmark.page, []).append(bookmark.title)

    def get_header_id(self, span: dict, page: Any = None) -> str:
        """Return a heading prefix or an empty string for the supplied ``span``."""
        text = str(span.get("text") or "")
        if not text.strip():
            return ""
        bbox = tuple(float(value) for value in span["bbox"]) if span.get("bbox") is not None else None
        page_no = int(page.number) + 1 if page is not None else None
        if page is not None and bbox is not None and self._in_running_line(text, bbox, float(page.rect.height)):
            return ""
        size = round(float(span.get("size") or 0))
        if size in self._size_rank:
            return "#" * (self._size_rank[size] + 1) + " "
        bold = _is_bold(span)
        body = self.profile.body_size
        if page_no is not None and bbox is not None and bold and body is not None and size == body:
            if self._inside_bold_line(page_no, bbox):
                return self._body_bold_prefix
        if page_no is not None and (bold or (body is not None and size > body)):
            if self._matches_bookmark(page_no, text):
                return self._body_bold_prefix
        return ""

    def _in_running_line(self, text: str, bbox: tuple[float, ...], height: float) -> bool:
        """Return whether ``text`` is part of a recorded running line in its page band."""
        band = _band(bbox[1], bbox[3], height)
        key = running_key(text)
        return band is not None and any(key in running for running in self._running.get(band, []))

    def _inside_bold_line(self, page_no: int, bbox: tuple[float, ...]) -> bool:
        """Return whether ``bbox`` is inside a recorded standalone bold line on ``page_no``."""
        x0, y0, x1, y1 = bbox
        tolerance = self.TOLERANCE
        return any(
            x0 >= bold_line.bbox[0] - tolerance
            and y0 >= bold_line.bbox[1] - tolerance
            and x1 <= bold_line.bbox[2] + tolerance
            and y1 <= bold_line.bbox[3] + tolerance
            for bold_line in self.profile.bold_lines.get(page_no, [])
        )

    def _matches_bookmark(self, page_no: int, text: str) -> bool:
        """Return whether ``text`` matches a usable bookmark on ``page_no``."""
        return any(_titles_match(text, title) for title in self._bookmark_titles.get(page_no, []))
