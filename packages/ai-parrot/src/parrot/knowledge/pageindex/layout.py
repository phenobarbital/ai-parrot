"""PDF layout analysis for PageIndex structure (FEAT-845): body/heading sizes, running lines, bookmarks."""

from __future__ import annotations

import bisect
import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex.segments import normalize_title

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
MAX_BOLD_LEVELS: int = 2
"""Bold-row heading levels: the body size plus at most one larger body-text size."""
ROW_OVERLAP: float = 0.5
"""Lines of one block share a visual row when their vertical extents overlap by this share of the shorter one."""
BOLD_REPEAT_MIN_PAGES: int = 3
"""A bold row whose running_key text occurs on this many distinct pages is a label or table header."""
_LIST_MARKER_RE = re.compile(r"^\(\s*[A-Za-z0-9]{1,4}\s*\)")
_LIST_TAIL_RE = re.compile(r"(?:[;:]|;\s*(?:and|or))$", re.IGNORECASE)
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
    """A standalone bold row (body size or a larger body-text size) and its page geometry."""

    text: str
    bbox: tuple[float, float, float, float]
    size: Optional[int] = None  # rounded font size of the row; None (older profiles) means the body size


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
    bold_sizes: list[int] = Field(default_factory=list)  # largest first, body last; [] means [body_size]


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


def _bold_sizes(size_counts: Mapping[int, int], body_size: Optional[int], heading_sizes: Sequence[int]) -> list[int]:
    """Return the body size preceded by at most ``MAX_BOLD_LEVELS - 1`` larger body-text sizes, largest first.

    A body-text size is above ``body_size``, not in ``heading_sizes`` and holds more than
    ``_HEADING_SHARE_CAP`` of the counted characters.

    Args:
        size_counts: Characters per rounded font size, running lines excluded.
        body_size: The dominant size, or None for a document without text.
        heading_sizes: The size-ranked heading sizes.

    Returns:
        Sizes whose standalone bold rows are heading candidates; ``[]`` when ``body_size`` is None.
    """
    if body_size is None:
        return []
    total = sum(size_counts.values())
    secondary = sorted(
        (
            size
            for size, count in size_counts.items()
            if size > body_size and size not in heading_sizes and total and count / total > _HEADING_SHARE_CAP
        ),
        reverse=True,
    )
    return [*secondary[: MAX_BOLD_LEVELS - 1], body_size]


def _visual_rows(block_lines: Sequence[dict]) -> list[list[dict]]:
    """Group a block's lines, in order, into visual rows.

    A line joins the current row when its vertical extent overlaps the row's extent by at least
    ``ROW_OVERLAP`` of the shorter of the two heights; otherwise it starts a new row.

    Args:
        block_lines: Line dicts of one block, in PyMuPDF order, each with a ``bbox``.

    Returns:
        The rows, each a list of line dicts.
    """
    rows: list[list[dict]] = []
    for line in block_lines:
        y0, y1 = float(line["bbox"][1]), float(line["bbox"][3])
        if rows:
            row_y0 = min(float(other["bbox"][1]) for other in rows[-1])
            row_y1 = max(float(other["bbox"][3]) for other in rows[-1])
            if min(y1, row_y1) - max(y0, row_y0) >= ROW_OVERLAP * min(y1 - y0, row_y1 - row_y0):
                rows[-1].append(line)
                continue
        rows.append([line])
    return rows


def _row_all_bold(row: Sequence[dict]) -> bool:
    """Return whether a row has spans and every one of them is bold."""
    spans = [span for line in row for span in line["spans"]]
    return bool(spans) and all(_is_bold(span) for span in spans)


def _row_text(row: Sequence[dict]) -> str:
    """Return the row's line texts joined by single spaces."""
    return " ".join(line["text"] for line in row if line["text"]).strip()


def _bold_row_size(row: Sequence[dict], bold_sizes: Sequence[int]) -> Optional[int]:
    """Return the row's rounded size when the row is a bold heading candidate, else None.

    Candidate: every span bold; one rounded size, in ``bold_sizes``; the joined text has at most
    ``_MAX_BOLD_WORDS`` words, does not end with ``.`` or ``,``, is not a list item (``_LIST_MARKER_RE`` /
    ``_LIST_TAIL_RE``), and its first alphanumeric character is not lowercase.

    Args:
        row: The row's line dicts.
        bold_sizes: Sizes eligible for bold-row headings.

    Returns:
        The row size, or None when the row is not a candidate.
    """
    if not _row_all_bold(row):
        return None
    sizes = {round(float(span["size"])) for line in row for span in line["spans"]}
    if len(sizes) != 1:
        return None
    size = next(iter(sizes))
    if size not in bold_sizes:
        return None
    text = _row_text(row)
    if not text or len(text.split()) > _MAX_BOLD_WORDS or text.endswith((".", ",")):
        return None
    if _LIST_MARKER_RE.match(text) or _LIST_TAIL_RE.search(text):
        return None
    first = next((char for char in text if char.isalnum()), "")
    if first.islower():
        return None
    return size


def _collect_bold_lines(
    lines: Sequence[dict], running_keys: set[tuple[str, str]], bold_sizes: Sequence[int]
) -> dict[int, list[BoldLine]]:
    """Return standalone bold heading rows per page, without rows repeated on ``BOLD_REPEAT_MIN_PAGES`` pages.

    A row is standalone when its block has one row, or it is the block's first row and no other row of the
    block is all-bold. Rows containing a running line are skipped.

    Args:
        lines: Every line dict of the document, in page/block/line order.
        running_keys: ``(band, key)`` pairs of the running headers and footers.
        bold_sizes: Sizes eligible for bold-row headings.

    Returns:
        Bold rows keyed by 1-based page number, in document order.
    """
    blocks: dict[tuple[int, int], list[dict]] = {}
    for line in lines:
        blocks.setdefault((line["page"], line["block"]), []).append(line)
    candidates: list[tuple[int, str, BoldLine]] = []
    for (page_no, _), block_lines in blocks.items():
        rows = _visual_rows(block_lines)
        for row_index, row in enumerate(rows):
            if any((line["band"], line["key"]) in running_keys for line in row):
                continue
            size = _bold_row_size(row, bold_sizes)
            if size is None:
                continue
            standalone = len(rows) == 1 or (row_index == 0 and not any(_row_all_bold(other) for other in rows[1:]))
            if not standalone:
                continue
            text = _row_text(row)
            bbox = (
                min(float(line["bbox"][0]) for line in row),
                min(float(line["bbox"][1]) for line in row),
                max(float(line["bbox"][2]) for line in row),
                max(float(line["bbox"][3]) for line in row),
            )
            candidates.append((page_no, running_key(text), BoldLine(text=normalize_title(text), bbox=bbox, size=size)))
    pages_by_key: dict[str, set[int]] = {}
    for page_no, key, _ in candidates:
        pages_by_key.setdefault(key, set()).add(page_no)
    bold_lines: dict[int, list[BoldLine]] = {}
    for page_no, key, bold_line in candidates:
        if len(pages_by_key[key]) < BOLD_REPEAT_MIN_PAGES:
            bold_lines.setdefault(page_no, []).append(bold_line)
    return bold_lines


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

    bold_sizes = _bold_sizes(size_counts, body_size, heading_sizes)
    bold_lines = _collect_bold_lines(lines, running_keys, bold_sizes)

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
        bold_sizes=bold_sizes,
        bookmarks=bookmarks,
        bookmark_rejection=rejection,
        bookmarks_dropped=dropped,
    )


def _bookmark_prefix_match(text: str, title: str) -> bool:
    """Return whether a span's text is a bookmark title, a word-boundary prefix of it, or begins with all of it.

    Both sides go through ``normalize_title``; empty sides never match. A mid-title word (``attempts.`` in
    ``AC-7 UNSUCCESSFUL LOGON ATTEMPTS``) does not match; the title's first span does.

    Args:
        text: The span text.
        title: A usable bookmark title on the span's page.

    Returns:
        True when the span equals, starts, or begins with the whole title.
    """
    span, wanted = normalize_title(text), normalize_title(title)
    if not span or not wanted:
        return False
    return span == wanted or wanted.startswith(span + " ") or span.startswith(wanted + " ")


class LayoutHeaders:
    """pymupdf4llm ``hdr_info`` object driven by a LayoutProfile (rules 1-6 of spec §2)."""

    TOLERANCE: float = 0.5

    def __init__(self, profile: LayoutProfile) -> None:
        self.profile = profile
        self._size_rank: dict[int, int] = {size: rank for rank, size in enumerate(profile.heading_sizes)}
        self._body_bold_prefix = "#" * (len(profile.heading_sizes) + 1) + " "
        bold_sizes = profile.bold_sizes or ([profile.body_size] if profile.body_size is not None else [])
        base = len(profile.heading_sizes) + 1
        self._bold_prefixes: dict[int, str] = {
            size: "#" * min(6, base + rank) + " " for rank, size in enumerate(bold_sizes)
        }
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
        if page_no is not None and bbox is not None and bold and size in self._bold_prefixes:
            if self._inside_bold_line(page_no, bbox):
                return self._bold_prefixes[size]
        if page_no is not None and (bold or (body is not None and size > body and size not in self._bold_prefixes)):
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
        """Return whether ``text`` is a usable bookmark title of ``page_no`` or a word-boundary prefix of one."""
        return any(_bookmark_prefix_match(text, title) for title in self._bookmark_titles.get(page_no, []))
