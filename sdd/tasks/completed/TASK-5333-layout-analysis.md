# TASK-5333: Layout analysis: profile, errors, analyze_layout (M1a)

**Feature**: FEAT-845 — PageIndex Layout Structure Builder
**Spec**: `sdd/specs/pageindex-layout-structure.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

First half of spec Module 1 ("Layout analysis and header detector"). The layout-first PDF pipeline
(spec §2 "Pipeline", step 2) needs one deterministic pass over every page's span dicts that measures the
body text size, ranks heading sizes, finds running headers/footers, records standalone bold lines (by
occurrence, with geometry — rev 0.2) and reads/validates the embedded bookmarks. The result is a
`LayoutProfile`. This task also creates the error classes and the `StructureSource` / `StructureMode`
literals every later task imports. `LayoutHeaders` (the pymupdf4llm header detector, rules 1–6) is
TASK-5334 and appends to the same file.

Spec sections: §2 "Layout analysis (`analyze_layout`)", §2 Data Models (`layout.py`), §3 Module 1,
§4 `test_layout.py` rows, AC-4, AC-8, AC-20.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` with: the literals
  `StructureSource`, `StructureMode`; constants `MAX_SIZE_LEVELS = 4`, `RUNNING_BAND = 0.08`,
  `RUNNING_MIN_SHARE = 0.3`; errors `PDFStructureError(ValueError)`, `UnreadablePDFError`,
  `NoTextLayerError`; models `Bookmark`, `RunningLine`, `BoldLine`, `LayoutProfile` (spec §2 verbatim);
  `running_key(text)`; private helpers `_is_bold(span)`, `_band(y0, y1, height)`,
  `_read_bookmarks(raw_toc, page_count)`; and `analyze_layout(pdf_path) -> LayoutProfile`.
- Implement every rule of spec §2 "Layout analysis": running lines, body size, heading sizes, standalone
  bold lines (one `BoldLine(text, bbox)` per occurrence, 1-based page key; identical text at different
  positions stays separate), bookmarks with level normalization and the three rejection reasons.
- Map a PyMuPDF open failure to `UnreadablePDFError` (AC-8, unreadable half).
- Create `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` with the seven M1a tests below.

**NOT in scope**: `LayoutHeaders` / `get_header_id` (TASK-5334, appended to this file later);
`_titles_match` use (rule 5 lives in TASK-5334 — do not import it here, ruff F401 would flag it);
scoring or structure building (TASK-5336/5337); `NoTextLayerError` *raising* (the builder raises it,
TASK-5340 — this task only defines the class); any change to `segments.py`, `pdf_to_markdown.py` or
`builder.py`; `__init__.py` exports (TASK-5340).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | CREATE | Literals, errors, models, constants, `running_key`, helpers, `analyze_layout` |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` | CREATE | Synthetic-PDF tests for the analysis pass |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.knowledge.pageindex.segments import normalize_title   # verified: segments.py:305
from pydantic import BaseModel, Field                             # used the same way in segments.py:9
import pymupdf                                                    # 1.27.1 — guarded import, see pdf_to_markdown.py:25-28
# pymupdf facts (verified in the venv): pymupdf.TEXT_FONT_BOLD == 16, pymupdf.TEXTFLAGS_TEXT == 195,
# pymupdf.FileDataError subclasses RuntimeError, Document.get_toc(simple=True) -> [[level, title, page], ...]
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
def normalize_title(title: str) -> str                       # :305 — casefold, collapse whitespace,
                                                              #   strip leading numbering + trailing punctuation

# packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py:25-28 — guarded import pattern to copy
try:
    import pymupdf
except ImportError:  # pragma: no cover — pyproject pins pymupdf.
    pymupdf = None  # type: ignore[assignment]

# pymupdf 1.27.1 — page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT) returns
#   {"width", "height", "blocks": [{"type": 0 (text) | 1 (image), "bbox", "lines": [
#       {"bbox": (x0, y0, x1, y1), "dir", "wmode", "spans": [
#           {"size": float, "flags": int, "font": str, "text": str, "bbox": (x0, y0, x1, y1), ...}]}]}]}
#   page.rect.height — page height; doc.page_count; iterating `doc` yields pages in order.
# Verified probe (this session): page.insert_text(..., fontname="hebo") -> span font "Helvetica-Bold",
#   flags 16; "helv" -> "Helvetica", flags 0. Two insert_text calls on the same baseline (bold word, then
#   regular text at x + pymupdf.get_text_length("Important ", fontname="hebo", fontsize=10)) come out as ONE
#   line with two spans — that is how a "bold run-in word" is built in tests.
# doc.set_toc() REJECTS level jumps ("bad hierarchy level") and a first level != 1, and CLAMPS
#   out-of-range pages to page_count (verified probe). Malformed bookmarks therefore cannot be written
#   with set_toc: test the normalization through the pure helper `_read_bookmarks(raw_toc, page_count)`.
```

### Does NOT Exist
- ~~`parrot.knowledge.pageindex.layout`~~ — this task creates it; nothing under `knowledge/pageindex/` reads `get_toc(` or span font data today
- ~~`PDFStructureError`, `UnreadablePDFError`, `NoTextLayerError`~~ — not defined anywhere yet
- ~~`structure_source` / `structure_mode` literals~~ — no such names anywhere in `knowledge/pageindex/`
- ~~`pymupdf_layout`~~ — not installed, never import it (pymupdf4llm only suggests it on stderr)
- ~~`pymupdf4llm.TocHeaders` for bookmarks~~ — buggy (`pymupdf_rag.py:187` calls `get_toc()` on its argument); bookmarks are read with `doc.get_toc(simple=True)` here
- ~~a shared `conftest.py` under `tests/knowledge/pageindex/`~~ — none exists; define fixtures in `test_layout.py`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_layout.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#normalize_title"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Guarded `pymupdf` import exactly like `pdf_to_markdown.py:25-28`; raise `ImportError` when it is `None`.
- Pydantic v2 models, `logger = logging.getLogger(__name__)`, `logger.debug` only (no I/O besides the PDF).

### Key Constraints
- `analyze_layout` is **sync** and opens its own `pymupdf.Document` inside the function, closing it in
  `finally` — it runs in `asyncio.to_thread` (TASK-5340); a Document is never shared across threads.
- One pass over `page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)`: collect per-line records once,
  then compute running lines → statistics → bold lines from the records.
- **Never raise for odd content**: bad bookmarks are rejected with a reason; no countable text gives
  `body_size=None` (and empty `heading_sizes` / `bold_lines`).
- Running lines: band from `_band(line_y0, line_y1, page.rect.height)` (`y0 < RUNNING_BAND × h` → top,
  `y1 > (1 − RUNNING_BAND) × h` → bottom); key = `running_key(line text)`; running when the same key in the
  same band occurs on `>= max(3, ceil(RUNNING_MIN_SHARE × page_count))` distinct pages; `page_count < 3` → none.
  Running lines are excluded from every statistic and from bold-line detection.
- Body size: character-weighted mode of `round(span["size"])` over non-empty spans of non-running lines;
  ties → the smaller size. Heading sizes: rounded sizes `> body_size` whose character share of the counted
  text is `<= 0.10`, largest first, at most `MAX_SIZE_LEVELS`.
- Standalone bold line (spec §2 verbatim): body-size line whose every non-empty span is bold
  (`_is_bold`), at most 12 words, not ending in `.` or `,`, and either the only line of its block or the
  first line of a block whose other lines are not bold. Record `BoldLine(text=normalize_title(line_text),
  bbox=tuple(float(v) for v in line["bbox"]))` under `bold_lines[page_no]` (1-based). Do NOT dedupe by text.
- Bookmarks: keep the usable list in `LayoutProfile.bookmarks` **even when rejected** (diagnostic);
  consumers check `bookmark_rejection` (TASK-5334 rule 5, TASK-5336 score). Rejection strings must contain,
  respectively: `"fewer than 2 usable"`, `"non-monotonic"`, `"per-page enumeration"` (tests match on them).
- pymupdf4llm extracts with accurate (tighter) bounding boxes; this task records bold-line boxes with the
  spec's `TEXTFLAGS_TEXT`. Probe this session: default line box `[72.0, 89.3, 148.7, 103.1]` vs pymupdf4llm
  span box `[72.0, 92.7, 148.7, 102.2]` — tighter and inside, so TASK-5334's rule 4 holds. Do not change
  the flags here; TASK-5334 owns that decision if real extraction ever disagrees.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py:25-28,78-86` — guarded import, open/close pattern
- `packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py:305` — `normalize_title`
- `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py:15-33` — building a PDF with pymupdf in `tmp_path`

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Write `layout.py` part 1 (models, errors, literals, constants, `running_key`, `_is_bold`, `_band`) — *why*: every later task imports these names; they are fixed by spec §2 Data Models.
2. Write `layout.py` part 2 (`_read_bookmarks`, `analyze_layout`) and complete the FILL INs — *why*: the pure bookmark helper is testable with raw lists, which `set_toc` cannot produce.
3. Write `test_layout.py`, fill in the test bodies, run the Validation Command — *why*: the thresholds are heuristics; synthetic PDFs pin each rule.
4. `ruff check` both files and commit only these two files — *why*: AC-18, minimal diff.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (CREATE) — part 1 of 2 (top of file)
```python
"""PDF layout analysis for PageIndex structure (FEAT-845): body/heading sizes, running lines, bookmarks."""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex.segments import normalize_title  # verified: segments.py:305

try:
    import pymupdf
except ImportError:  # pragma: no cover — pyproject pins pymupdf.
    pymupdf = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

StructureSource = Literal["bookmarks", "layout", "hybrid", "llm", "pages"]
StructureMode = Literal["auto", "layout", "llm"]

MAX_SIZE_LEVELS: int = 4
RUNNING_BAND: float = 0.08            # top/bottom fraction of the page height
RUNNING_MIN_SHARE: float = 0.3        # share of pages a running key must recur on (min 3 pages)
_HEADING_SHARE_CAP: float = 0.10      # max character share of a heading size
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
    level: int                 # >= 1, never more than previous + 1
    title: str
    page: int                  # 1-based physical page


class RunningLine(BaseModel):
    key: str                   # casefolded, whitespace collapsed, digit runs -> "#"
    band: Literal["top", "bottom"]
    pages: int                 # distinct pages it recurs on


class BoldLine(BaseModel):
    text: str                  # normalized text, diagnostic only; not occurrence identity
    bbox: tuple[float, float, float, float]  # page coordinates: x0, y0, x1, y1


class LayoutProfile(BaseModel):
    page_count: int
    body_size: Optional[int] = None          # None when no countable text
    heading_sizes: list[int] = Field(default_factory=list)   # largest first, <= MAX_SIZE_LEVELS
    running: list[RunningLine] = Field(default_factory=list)
    bold_lines: dict[int, list[BoldLine]] = Field(default_factory=dict)  # 1-based page -> occurrences
    bookmarks: list[Bookmark] = Field(default_factory=list)  # usable entries, document order
    bookmark_rejection: Optional[str] = None


def running_key(text: str) -> str:
    """Casefold, collapse whitespace, replace digit runs with '#'."""
    return _DIGITS_RE.sub("#", " ".join((text or "").casefold().split()))


def _is_bold(span: dict) -> bool:
    """Bold by font flag (``TEXT_FONT_BOLD``) or by a font name containing 'bold'."""
    return bool(int(span.get("flags", 0)) & 16) or "bold" in str(span.get("font", "")).casefold()


def _band(y0: float, y1: float, height: float) -> Optional[Literal["top", "bottom"]]:
    """'top' / 'bottom' when the line lies in the running band of a page of ``height``, else None."""
    if height <= 0:
        return None
    if y0 < RUNNING_BAND * height:
        return "top"
    if y1 > (1.0 - RUNNING_BAND) * height:
        return "bottom"
    return None
```
**Why this shape**: names, fields and comments are spec §2 Data Models verbatim — TASK-5334/5336/5340
import them, so they are not renegotiable. `16` is `pymupdf.TEXT_FONT_BOLD` (verified); it is written as a
literal so `_is_bold` works on hand-built span dicts in tests even when `pymupdf` is `None`.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (CREATE) — part 2 of 2 (append)
```python
def _read_bookmarks(raw_toc: list[list], page_count: int) -> tuple[list[Bookmark], Optional[str]]:
    """Usable, level-normalized bookmarks in document order and the rejection reason (None = accepted).

    ``raw_toc`` is ``doc.get_toc(simple=True)``: ``[[level, title, page], ...]``, page 1-based.
    """
    usable: list[Bookmark] = []
    previous_level = 0
    for entry in raw_toc:
        # FILL IN: skip entries whose stripped title is empty or whose page is outside 1..page_count;
        #   level = max(1, min(int(level), previous_level + 1)); append Bookmark; previous_level = level
        #   — bounded by spec §2 "Bookmarks" (levels never exceed the previous one by more than 1)
        raise NotImplementedError
    # FILL IN: rejection, first match wins — bounded by spec §2 "Bookmarks":
    #   len(usable) < 2 -> "fewer than 2 usable entries";
    #   any page decreasing in document order -> "non-monotonic: page decreases at entry <i>";
    #   page_count >= 4 and every level == 1 and len(usable) >= 0.8 * page_count and
    #   (>= 80 % of pages carry exactly one entry or >= 80 % of titles match _ENUM_TITLE_RE) -> "per-page enumeration"
    rejection: Optional[str] = None
    return usable, rejection


def analyze_layout(pdf_path: str) -> LayoutProfile:
    """One pass over every page's span dicts.

    Opens its own pymupdf.Document (never shared across threads). Raises UnreadablePDFError when
    PyMuPDF cannot open the file. Never raises for odd content: bad bookmarks are rejected with a
    reason, missing text yields body_size=None.
    """
    if pymupdf is None:
        raise ImportError("analyze_layout requires pymupdf; install it via the [pdf] extra.")
    try:
        doc = pymupdf.open(pdf_path)
    except RuntimeError as exc:  # pymupdf.FileDataError subclasses RuntimeError (verified)
        raise UnreadablePDFError(f"Cannot open {Path(pdf_path).name}: {exc}") from exc
    try:
        page_count = doc.page_count
        lines: list[dict] = []
        for page_no, page in enumerate(doc, start=1):
            height = page.rect.height
            for block_no, block in enumerate(page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]):
                if block.get("type") != 0:
                    continue
                # FILL IN: one record per line: {"page": page_no, "block": block_no, "index": i,
                #   "block_lines": len(block["lines"]), "spans": non-empty spans, "text": joined span text,
                #   "bbox": line["bbox"], "band": _band(y0, y1, height), "key": running_key(text)}
                #   — bounded by "one pass over page.get_text('dict')" (spec §2)
        raw_toc = doc.get_toc(simple=True)
    finally:
        doc.close()
    # FILL IN: running keys per (band, key) over distinct pages; threshold max(3, ceil(RUNNING_MIN_SHARE *
    #   page_count)); none when page_count < 3; build list[RunningLine] — bounded by spec §2 "Running lines"
    # FILL IN: Counter of round(size) weighted by len(span text) over non-running lines -> body_size
    #   (ties -> smaller; None when empty) and heading_sizes (share <= _HEADING_SHARE_CAP, largest first,
    #   [:MAX_SIZE_LEVELS]) — bounded by spec §2 "Body size" / "Heading sizes"
    # FILL IN: standalone bold lines per page (rules in Implementation Notes) as BoldLine occurrences,
    #   no text dedupe — bounded by spec §2 "Standalone bold lines" (rev 0.2) and AC-20
    bookmarks, rejection = _read_bookmarks(raw_toc, page_count)
    logger.debug("analyze_layout %s: %d pages, %d bookmarks, rejection=%s", pdf_path, page_count, len(bookmarks), rejection)
    raise NotImplementedError  # FILL IN: return LayoutProfile(...) with every computed field
```
**Why this shape**: the open/close and the single pass are fixed so the function is thread-safe and
cheap (AC-16 relies on it running in a worker thread). `_read_bookmarks` is a separate pure function
because `set_toc` cannot write level jumps or out-of-range pages (verified), so its normalization is only
testable with raw lists. `math`, `Counter` and `normalize_title` are imported for the FILL INs; drop any
that end up unused before `ruff check`.

### `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` (CREATE)
```python
"""Layout analysis of synthetic PDFs (FEAT-845 M1)."""
from __future__ import annotations

from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from parrot.knowledge.pageindex.layout import (  # noqa: E402
    UnreadablePDFError,
    _read_bookmarks,
    analyze_layout,
)

FILLER = "body text line with plenty of ordinary words for the statistics"
Item = tuple[float, float, str, float, str]   # (x, y, text, fontsize, fontname "helv" | "hebo")


def _write_pdf(path: Path, pages: list[list[Item]], toc: list[list] | None = None) -> Path:
    """Write one A4 page (595x842) per item list; ``toc`` goes through ``doc.set_toc``."""
    doc = pymupdf.open()
    try:
        for items in pages:
            page = doc.new_page()
            for x, y, text, size, font in items:
                page.insert_text((x, y), text, fontsize=size, fontname=font)
        if toc:
            doc.set_toc(toc)
        doc.save(str(path))
    finally:
        doc.close()
    return path


def _body(y0: float, n: int) -> list[Item]:
    return [(72, y0 + i * 14, FILLER, 10, "helv") for i in range(n)]


@pytest.fixture
def headed_pdf(tmp_path: Path) -> Path:
    """4 pages, body 10 pt, headings 16/12 pt, running header 'ACME Manual' and page-number footer."""
    pages = []
    for n in range(1, 5):
        pages.append([(72, 40, "ACME Manual", 9, "helv"), (280, 815, f"Page {n}", 9, "helv"),
                      (72, 100, f"{n} Chapter {n}", 16, "helv"), (72, 130, f"{n}.1 Section {n}", 12, "helv"),
                      *_body(160, 30)])
    return _write_pdf(tmp_path / "headed.pdf", pages)


def test_body_size_and_heading_sizes(headed_pdf: Path) -> None:
    """body_size == 10 and heading_sizes == [16, 12]."""
    # FILL IN: profile = analyze_layout(str(headed_pdf)); assert the two values and page_count == 4


def test_running_lines_excluded(tmp_path: Path) -> None:
    """Header (20 pt bold) and 'Page n' footer on every page are running and excluded from statistics."""
    # FILL IN: 4 pages with (72, 40, "ACME Manual", 20, "hebo") + footer + body; assert running keys
    #   {("top", "acme manual"), ("bottom", "page #")}, 20 not in heading_sizes, no BoldLine with text
    #   "acme manual"; a 2-page variant has profile.running == []


def test_bold_standalone_lines(tmp_path: Path) -> None:
    """Bold body-size standalone line recorded; a bold run-in word inside a paragraph is not."""
    # FILL IN: page with (72, 100, "Important Notes", 10, "hebo"), a run-in line built from "Important " (hebo)
    #   + regular text at x + pymupdf.get_text_length("Important ", fontname="hebo", fontsize=10), plus body;
    #   also the same standalone text "Important Notes" again at y=400 -> bold_lines[1] has exactly the two
    #   standalone occurrences (different bbox), none for the run-in line (AC-20 recording half)


def test_bookmarks_usable_and_levels_normalized() -> None:
    """Raw TOC with a level jump and an out-of-range page -> normalized, entry dropped (pure helper)."""
    # FILL IN: _read_bookmarks([[1, "A", 1], [3, "B", 2], [1, "C", 9], [1, "  ", 2], [2, "D", 3]], 4)
    #   -> titles ["A", "B", "D"] with levels [1, 2, 2] and pages [1, 2, 3] (C: page 9 > 4 dropped; blank
    #   title dropped; B's level 3 clamped to previous + 1 = 2); rejection is None


def test_bookmarks_rejected_non_monotonic(tmp_path: Path) -> None:
    """set_toc([[1, 'A', 3], [1, 'B', 1]]) -> 'non-monotonic' in profile.bookmark_rejection."""
    # FILL IN: write via _write_pdf(..., toc=...), analyze_layout; usable list kept, rejection set (AC-4)


def test_bookmarks_rejected_per_page_enumeration(tmp_path: Path) -> None:
    """One 'Page n' entry per page of a 4-page PDF -> 'per-page enumeration'."""
    # FILL IN: toc [[1, f"Page {n}", n] for n in 1..4]; assert the rejection string (AC-4)


def test_unreadable_pdf(tmp_path: Path) -> None:
    """b'%PDF-1.4 fake' -> UnreadablePDFError, a ValueError subclass (AC-8)."""
    # FILL IN: write the bytes, pytest.raises(UnreadablePDFError) around analyze_layout; isinstance ValueError
```
**Why this shape**: fixtures live in the module (no conftest — it would make the task exclusive). The
`headed_pdf` geometry keeps heading characters far below the 10 % share cap (≈22 heading chars vs ≈1900
body chars per page) and puts the header at y=40 (< 0.08 × 842 ≈ 67) and the footer at y=815
(> 0.92 × 842 ≈ 775). `test_bookmarks_usable_and_levels_normalized` tests the pure helper because
`set_toc` rejects level jumps and clamps pages (verified).

### FILL IN checklist
- [ ] `layout.py::_read_bookmarks` — usable filter + level normalization; bounded by spec §2 "Bookmarks"
- [ ] `layout.py::_read_bookmarks` — three rejection rules, stable strings; bounded by spec §2, AC-4
- [ ] `layout.py::analyze_layout` — per-line records in one pass; bounded by spec §2
- [ ] `layout.py::analyze_layout` — running lines; bounded by spec §2 "Running lines", AC-3 (analysis half)
- [ ] `layout.py::analyze_layout` — body size / heading sizes; bounded by spec §2
- [ ] `layout.py::analyze_layout` — standalone bold occurrences with bbox, no dedupe; bounded by rev 0.2, AC-20
- [ ] `layout.py::analyze_layout` — return the `LayoutProfile`
- [ ] `test_layout.py` — seven test bodies with the assertions named in each docstring

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.pageindex.layout import analyze_layout, LayoutProfile, BoldLine, PDFStructureError, UnreadablePDFError, NoTextLayerError, StructureSource, StructureMode, MAX_SIZE_LEVELS, running_key` works
- [ ] AC-4 (profile half): non-monotonic bookmarks and per-page enumerations set `bookmark_rejection` with the reason
- [ ] AC-8 (unreadable half): an unreadable file raises `UnreadablePDFError`, a `ValueError` subclass
- [ ] AC-20 (recording half): every standalone bold occurrence is stored with its page and line bbox; identical text at two positions gives two `BoldLine`s; a bold run-in word is not recorded
- [ ] Running headers/footers are detected and excluded from body/heading statistics (feeds AC-3)
- [ ] `analyze_layout` opens and closes its own Document; never raises for odd content
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout.py -q`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` is clean (AC-18)
- [ ] No new dependency

---

## Validation Commands

> Commands a registered test runner recognises — `pytest`, `vitest`, `cargo test`, `parrot e2e` or an
> `[extensions]` entry in `.parrot/test_runners.toml`. pytest: file-level only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.
> Add more tests as needed.

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_layout.py — see the blueprint block above.
# Expected outcomes:
#   test_body_size_and_heading_sizes           -> body_size == 10, heading_sizes == [16, 12]
#   test_running_lines_excluded                -> 2 running lines (top "acme manual", bottom "page #"); 20 not a heading size
#   test_bold_standalone_lines                 -> 2 BoldLine occurrences of "important notes" on page 1, none for the run-in line
#   test_bookmarks_usable_and_levels_normalized -> out-of-range + blank entries dropped, level jump clamped to previous + 1
#   test_bookmarks_rejected_non_monotonic      -> "non-monotonic" in bookmark_rejection
#   test_bookmarks_rejected_per_page_enumeration -> "per-page enumeration" in bookmark_rejection
#   test_unreadable_pdf                        -> UnreadablePDFError (isinstance ValueError)
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-structure --feature-id FEAT-845`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/pageindex-layout-structure.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/pageindex-layout-structure.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands as
   `PYTHONPATH=packages/ai-parrot/src pytest <file> -q` (the shared venv is editable-installed on the main checkout; never `uv sync` in the worktree)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5333 pageindex-layout-structure verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(filled by sdd-worker)*

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-terra (codex), 1 attempt
**Date**: 2026-11-08
**Notes**: Merged into the feature branch; lint clean. Merge-tier run (pageindex + bookstore + mcp template, 725 tests): 721 passed, 4 failed (test_adapter x2, test_okf_ontology x2), identical on a clean origin/dev baseline, so pre-existing. The engine's background validation timed out at ~60s, so the run was done directly on the host. Review feedback: none recorded.
