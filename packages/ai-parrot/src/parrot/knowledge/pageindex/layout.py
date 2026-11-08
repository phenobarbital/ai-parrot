"""PDF layout analysis for PageIndex structure (FEAT-845): body/heading sizes, running lines, bookmarks."""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Literal, Optional

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


def _read_bookmarks(raw_toc: list[list], page_count: int) -> tuple[list[Bookmark], Optional[str]]:
    """Return usable normalized bookmarks and any rejection reason.

    ``raw_toc`` is ``doc.get_toc(simple=True)``: ``[[level, title, page], ...]``.
    """
    usable: list[Bookmark] = []
    previous_level = 0
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
        level = max(1, min(level, previous_level + 1))
        usable.append(Bookmark(level=level, title=title, page=page))
        previous_level = level

    if len(usable) < 2:
        return usable, "fewer than 2 usable entries"

    for index, (previous, current) in enumerate(zip(usable, usable[1:]), start=2):
        if current.page < previous.page:
            return usable, f"non-monotonic: page decreases at entry {index}"

    page_entries = Counter(bookmark.page for bookmark in usable)
    one_per_page = sum(count == 1 for count in page_entries.values()) >= 0.8 * page_count
    enumeration_titles = sum(bool(_ENUM_TITLE_RE.fullmatch(bookmark.title)) for bookmark in usable) >= 0.8 * len(usable)
    if (
        page_count >= 4
        and all(bookmark.level == 1 for bookmark in usable)
        and len(usable) >= 0.8 * page_count
        and (one_per_page or enumeration_titles)
    ):
        return usable, "per-page enumeration"
    return usable, None


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

    bookmarks, rejection = _read_bookmarks(raw_toc, page_count)
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
    )
