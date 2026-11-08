# TASK-5336: Structure candidates and scores (M3a)

**Feature**: FEAT-845 — PageIndex Layout Structure Builder
**Spec**: `sdd/specs/pageindex-layout-structure.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5333
**Assigned-to**: unassigned

---

## Context

Spec §2 ("Titles", "Bookmarks candidate", "Layout candidate", "Page fallback") and §3 Module 3.
The layout-first PDF pipeline scores two deterministic structure candidates — the PDF's embedded
**bookmarks** and its printed **layout** headings — against the heading segments produced by the
layout-aware extraction, and falls back to one node per **page** when neither is reliable. This task
creates `layout_structure.py` with the report models, `heading_title`, both scoring functions and
`page_structure`. TASK-5337 appends the hybrid insertion, the tree builder and the choice
(`build_structure`) to the same file.

Everything here is **pure**: no I/O, no pymupdf, no logging beyond `logger.debug` (spec §7
"Patterns to Follow"), so every rule is unit-testable on hand-built `Segment` lists and `LayoutProfile`s.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` with:
  - the Pydantic models `CandidateScore`, `StructureReport`, `StructureResult` (spec §2 Data Models, verbatim);
  - `heading_title(text)` (spec §2 "Titles");
  - `score_bookmarks(profile, segments)` (spec §2 "Bookmarks candidate");
  - `score_layout(profile, segments)` (spec §2 "Layout candidate");
  - `page_structure(page_count, doc_name)` (spec §2 "Page fallback").
- Create `packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py` with
  `test_heading_title`, `test_score_bookmarks_found_and_anchored`, `test_score_layout_factors`,
  `test_page_structure`.

**NOT in scope**:
- `insert_layout_headings`, `items_to_tree`, `build_structure` (TASK-5337 appends them).
- Anything in `layout.py` (TASK-5333 / TASK-5334), the builder (TASK-5340), `segments.py` (TASK-5338).
- Unknown-mode validation (the builder raises it, TASK-5340).
- A `conftest.py` — fixtures stay local to the test module.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` | CREATE | Report models, `heading_title`, `score_bookmarks`, `score_layout`, `page_structure` |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py` | CREATE | Unit tests for the four functions |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.knowledge.pageindex.segments import Segment, _heading_text, _titles_match, normalize_title
# verified: segments.py:33 (Segment), :340 (_heading_text), :312 (_titles_match), :305 (normalize_title)
from parrot.knowledge.pageindex.segments import segment_pages      # tests only; verified: segments.py:231
from pydantic import BaseModel, Field                              # used across pageindex (segments.py:9)
import logging, math, re                                           # stdlib
from pathlib import Path                                           # stdlib
from typing import Literal, Optional, Sequence                     # stdlib
```

#### Created by TASK-5333 (dependency — must be `done` before you start)
```python
from parrot.knowledge.pageindex.layout import (
    Bookmark,          # level: int (>=1), title: str, page: int (1-based)
    LayoutProfile,     # page_count, body_size, heading_sizes, running: list[RunningLine], bold_lines, bookmarks, bookmark_rejection
    RunningLine,       # key: str, band: Literal["top","bottom"], pages: int   (tests only)
    StructureMode,     # Literal["auto", "layout", "llm"]
    StructureSource,   # Literal["bookmarks", "layout", "hybrid", "llm", "pages"]
    running_key,       # casefold, collapse whitespace, digit runs -> "#"
)
```
Re-verify with `grep -n "^class \|^def \|^StructureSource\|^StructureMode" packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py`
before writing code. If a name differs, STOP and report — do not adapt silently.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)")                      # :15
class Segment(BaseModel):                                          # :33
    seq: int                                                       # :36  global position in the revision
    kind: SegmentKind                                              # :37  "heading" | "paragraph" | "list" | "table" | "code" | "caption" | "other"
    page: Optional[int] = None                                     # :38  1-based for PDF segments
    ordinal: int                                                   # :39  restarts at 0 on every page
    level: Optional[int] = None                                    # :41  ATX level (number of '#') for headings
    text: str                                                      # :42  heading text keeps its marker: "### **1 Introduction**"
def split_blocks(markdown) -> list[tuple[SegmentKind, str, Optional[int]]]   # :150; heading block = ("heading", raw line, len('#'*)) at :169-172
def segment_pages(pages: list[tuple[int, str]]) -> list[Segment]   # :231 (ordinal restarts per page)
_NUM_PREFIX_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s*")               # :299
def normalize_title(title: str) -> str                             # :305 casefold, collapse ws, strip leading numbering + trailing punct
def _titles_match(a: str, b: str) -> bool                          # :312 equality, or containment of the shorter (>= 3 chars) in the longer
def _heading_text(text: str) -> str                                # :340 group 2 of _HEADER_RE on text.strip(), else text unchanged

# packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py
def list_to_tree(data: list[dict]) -> list[dict]                   # :371 — LLM-path node shape: title/start_index/end_index, "nodes" deleted when empty (:398-404)
```

### Does NOT Exist
- ~~`parrot.knowledge.pageindex.layout_structure`~~ — this task creates it; nothing imports it yet.
- ~~`segments.heading_title`~~ / ~~`segments.strip_emphasis`~~ — no emphasis stripper exists; `normalize_title`
  does NOT strip `**` (spec §7 "Emphasis in heading text").
- ~~`LayoutProfile.headings`~~ / ~~`LayoutProfile.page_height`~~ — the profile carries no heading list and no page geometry.
- ~~`Segment.title`~~ / ~~`Segment.bbox`~~ — segments carry text only; titles come from `heading_title(seg.text)`.
- ~~`list_to_tree` keeping extra keys~~ — it rebuilds nodes from title/start/end/nodes only, so M3 builds its own tree (TASK-5337).
- ~~`insert_layout_headings`, `items_to_tree`, `build_structure`~~ — TASK-5337, not this task.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#Segment",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#_heading_text",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#_titles_match",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#normalize_title",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#segment_pages"
  ]
}
```

---

## Implementation Notes

### Item and node shapes (shared with TASK-5337 / TASK-5340 — do not change)
- **Item** (flat, document order): `{"depth": int (1-based), "title": str, "page": int,
  "anchor": {"page": int, "ordinal": int} | None, "level": Optional[int]}`.
  `level` is the anchor heading segment's ATX level (`Segment.level`); `None` for an unanchored bookmark.
- **Node**: `{"title", "start_index", "end_index", "nodes"?: [...], "anchor"?: {...}}` — `nodes` only when
  non-empty (mirrors `utils.list_to_tree`, utils.py:398-404); `anchor` only when the item had one.
- `score_bookmarks` / `score_layout` return `(CandidateScore, list[dict])`. A rejected bookmark set scores
  `0.0` with `rejected = profile.bookmark_rejection`; fewer than two layout headings score `0.0` with
  `rejected = "fewer than two headings"`.

### Key Constraints
- Pure functions, Pydantic v2 models, `logger = logging.getLogger(__name__)`, `logger.debug` only.
- Every title comparison goes through `normalize_title` / `_titles_match` on `heading_title(...)` output, so
  bookmarks, layout and `attach_pdf_document` agree on "same title" (spec §7).
- Confidence values are rounded to 3 decimals.
- A heading segment anchors **at most one** bookmark.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py:305-320` — title normalization to reuse.
- `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py:371-408` — LLM-path tree shape to mirror.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Confirm TASK-5333 is `done` and its names match the "Created by TASK-5333" block — *why*: this module imports them at load time.
2. Write `layout_structure.py` from Block 1 (models + `heading_title`) and Block 2 (scores + page fallback) as one file — *why*: TASK-5337 appends below `page_structure`, so keep it last.
3. Complete the FILL IN markers — *why*: they are the spec §2 rules; the test cases below pin them.
4. Write `test_layout_structure.py` from Block 3 and fill the test bodies — *why*: spec §4 lists exactly these four M3a tests.
5. Run the Validation Commands and `ruff check` on both files — *why*: AC-18.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` (CREATE) — Block 1 of 2
```python
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
MAX_HEADING_WORDS = 20      # layout "clean" share: at most 20 words, not ending in "."
MAX_HEADINGS_PER_PAGE = 8   # density factor threshold
MIN_CONTAINED_CHARS = 3     # bookmark "found" containment floor


class CandidateScore(BaseModel):
    """Confidence of one deterministic structure candidate."""

    source: Literal["bookmarks", "layout"]
    confidence: float          # 0..1, 3 decimals
    entries: int               # usable bookmarks or heading segments considered
    anchored: int              # entries anchored to a heading segment
    rejected: Optional[str] = None


class StructureReport(BaseModel):
    """How a PDF's structure was chosen (returned by the builder and ``import_pdf``)."""

    source: StructureSource
    mode: StructureMode
    min_confidence: float
    confidence: Optional[float] = None       # chosen score; min of both for hybrid; None for llm/pages
    candidates: list[CandidateScore] = Field(default_factory=list)
    inserted_headings: int = 0               # hybrid insertions
    body_size: Optional[int] = None
    running_lines: int = 0
    llm_used: bool = False
    llm_error: Optional[str] = None          # message when the LLM pipeline raised


class StructureResult(BaseModel):
    """A chosen deterministic structure: PageIndex nodes carrying a transient ``anchor``."""

    source: StructureSource
    structure: list[dict]
    report: StructureReport


def heading_title(text: str) -> str:
    """ATX marker and emphasis markers removed, whitespace collapsed.

    ``### **1 Introduction**`` -> ``1 Introduction``; ``## **1** **Introduction**`` -> ``1 Introduction``.
    Non-heading text is returned emphasis-stripped and whitespace-collapsed.
    """
    stripped = _EMPHASIS_RE.sub("", _heading_text(text))
    # FILL IN: also strip a surrounding single "_" emphasis pair (e.g. "_Scope_" -> "Scope") — bounded by spec §2
    #   "Titles" (`**`, `__`, surrounding `_`, backticks, `~~`); underscores inside words stay (snake_case titles).
    return " ".join(stripped.split())


def _segments_by_page(segments: Sequence[Segment]) -> dict[int, list[Segment]]:
    """Page -> its segments in ordinal order (segments without a page are ignored)."""
    pages: dict[int, list[Segment]] = {}
    for seg in segments:
        if seg.page is not None:
            pages.setdefault(seg.page, []).append(seg)
    return pages


def _anchor(seg: Segment) -> dict[str, int]:
    return {"page": int(seg.page or 0), "ordinal": seg.ordinal}
```
**Why this shape**: the three models are spec §2 Data Models verbatim (rev 0.2 comment on `confidence`);
`StructureReport.confidence` is set by TASK-5337 and the builder, never here. `heading_title` is the single
place emphasis is stripped — every comparison in this module and in TASK-5337 goes through it, because
pymupdf4llm wraps bold heading lines in `**…**` (spec §7). The helpers are private and reused by TASK-5337.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` (CREATE) — Block 2 of 2 (append below Block 1)
```python
def _anchor_heading(title: str, page_segments: Sequence[Segment], used: set[tuple[int, int]]) -> Optional[Segment]:
    """First unused heading segment of the page equal to ``title`` (normalized), else the first matching one."""
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
    """Score and anchor the usable bookmarks; items are (depth, title, page, anchor) dicts.

    A bookmark is *found* when anchored to a heading segment of its page, or when its normalized title
    (>= 3 characters) is contained in the emphasis-stripped, normalized text of any segment of its page.
    ``confidence = found / usable``; rejected bookmarks score 0.
    """
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
            used.add((seg.page, seg.ordinal))
            anchored += 1
            found += 1
        else:
            # FILL IN: found-by-containment — normalize_title(bm.title) has >= MIN_CONTAINED_CHARS characters and is a
            #   substring of normalize_title(heading_title(s.text)) for some s in page_segments → found += 1 (not
            #   anchored) — bounded by spec §2 "Bookmarks candidate"; a title-in-paragraph counts as found only.
            raise NotImplementedError
        items.append({"depth": bm.level, "title": bm.title, "page": bm.page,
                      "anchor": _anchor(seg) if seg is not None else None,
                      "level": seg.level if seg is not None else None})
    confidence = round(found / len(usable), 3)
    logger.debug("bookmarks: %d usable, %d found, %d anchored -> %.3f", len(usable), found, anchored, confidence)
    return CandidateScore(source="bookmarks", confidence=confidence, entries=len(usable), anchored=anchored), items


def score_layout(profile: LayoutProfile, segments: Sequence[Segment]) -> tuple[CandidateScore, list[dict]]:
    """Score the heading segments; items carry depth = rank of the heading level.

    Headings are the ``heading`` segments with a non-empty title whose ``running_key`` is not a running
    line of the profile. ``confidence = clean x density_factor x start_factor`` (3 decimals).
    """
    running = {line.key for line in profile.running}
    headings = [s for s in segments
                if s.kind == "heading" and heading_title(s.text) and running_key(heading_title(s.text)) not in running]
    levels = sorted({s.level for s in headings if s.level is not None})
    depth_of = {level: rank + 1 for rank, level in enumerate(levels)}
    items = [{"depth": depth_of.get(s.level, 1), "title": heading_title(s.text), "page": int(s.page or 1),
              "anchor": _anchor(s), "level": s.level} for s in headings]
    if len(headings) < 2:
        return CandidateScore(source="layout", confidence=0.0, entries=len(headings), anchored=len(headings),
                              rejected="fewer than two headings"), items
    # FILL IN: clean = share of headings whose heading_title has <= MAX_HEADING_WORDS words and does not end in ".";
    #   density = len(headings) / max(1, profile.page_count); density_factor = 1.0 if density <= MAX_HEADINGS_PER_PAGE
    #   else MAX_HEADINGS_PER_PAGE / density; start_factor = 1.0 if the first heading's page
    #   <= max(3, math.ceil(0.1 * profile.page_count)) else 0.5; confidence = round(product, 3) — bounded by spec §2
    #   "Layout candidate" exactly (no extra factors).
    raise NotImplementedError


def page_structure(page_count: int, doc_name: str) -> list[dict]:
    """One root titled Path(doc_name).stem with one 'Page <n>' child per page."""
    children = [{"title": f"Page {n}", "start_index": n, "end_index": n} for n in range(1, page_count + 1)]
    root: dict = {"title": Path(doc_name).stem or doc_name, "start_index": 1, "end_index": max(1, page_count)}
    if children:
        root["nodes"] = children
    return [root]
```
**Why this shape**: anchoring is two-pass (normalized equality, then `_titles_match`) over the page's unused
heading segments, exactly as spec §2 says, so "anchors unique" holds by the `used` set. `score_layout`
returns its items even below two headings — TASK-5337's hybrid rule reuses them; the score alone decides
whether they are used. `page_structure` omits `nodes` only for a zero-page document, matching the
`list_to_tree` convention. Do NOT add logging at INFO level here (pure module).

### `packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py` (CREATE)
```python
"""FEAT-845 M3 — structure candidates, scores and page fallback (pure, hand-built inputs)."""
from __future__ import annotations

import pytest

from parrot.knowledge.pageindex.layout import Bookmark, LayoutProfile, RunningLine
from parrot.knowledge.pageindex.layout_structure import (
    heading_title, page_structure, score_bookmarks, score_layout,
)
from parrot.knowledge.pageindex.segments import segment_pages


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", lambda t, model="gpt-4o": max(1, len(t)))


def _segs(*pages: str):
    """Segments of 1-based pages given as markdown strings."""
    return segment_pages([(n, md) for n, md in enumerate(pages, start=1)])


def _profile(page_count: int, bookmarks=(), rejection=None, running=()) -> LayoutProfile:
    return LayoutProfile(page_count=page_count, body_size=10, heading_sizes=[16, 12],
                         bookmarks=[Bookmark(level=l, title=t, page=p) for l, t, p in bookmarks],
                         bookmark_rejection=rejection,
                         running=[RunningLine(key=k, band="top", pages=page_count) for k in running])


@pytest.mark.parametrize("text, expected", [
    ("### **1 Introduction**", "1 Introduction"),
    ("## **1** **Introduction**", "1 Introduction"),
    ("# `Code`  ~~Old~~ Title", "Code Old Title"),
    ("## _Scope_", "Scope"),
    ("plain paragraph", "plain paragraph"),
])
def test_heading_title(text, expected):
    """ATX marker and emphasis stripped, whitespace collapsed (spec §2 Titles)."""
    assert heading_title(text) == expected


def test_score_bookmarks_found_and_anchored():
    """Found ratio; anchors unique; title-in-paragraph is found but not anchored (spec §4, AC-4 score part)."""
    # FILL IN: build segments with _segs("# Intro\n\nText.", "Para mentions Scope here.\n\n## Usage\n\nMore.") and a
    #   profile with bookmarks [(1,"Intro",1),(2,"Scope",2),(1,"Usage",2),(1,"Missing",2)] → confidence 0.75,
    #   anchored == 2, items[1]["anchor"] is None, items[0]["anchor"] == {"page": 1, "ordinal": 0}, items carry the
    #   anchored segment's level; a second bookmark with the same title on a page with ONE heading anchors only once;
    #   a profile with bookmark_rejection="non-monotonic ..." → confidence 0.0, rejected names it, items == [].
    raise NotImplementedError


def test_score_layout_factors():
    """< 2 headings → 0; sentence-like headings lower `clean`; density and start factors (spec §2, §4)."""
    # FILL IN: one heading → 0.0 and rejected == "fewer than two headings"; 4 headings with one ending in "." →
    #   clean 0.75; 20 headings on a 1-page doc → factor 8/20 (confidence 0.4); first heading on page 5 of 10 →
    #   start_factor 0.5; a heading equal to a running key (profile running=("acme manual",)) is excluded; depth is
    #   the rank of the level (levels {2, 3} → depths {1, 2}).
    raise NotImplementedError


def test_page_structure():
    """Root titled by stem, one child per page (spec §2 Page fallback)."""
    tree = page_structure(3, "/books/My Doc.pdf")
    assert tree == [{"title": "My Doc", "start_index": 1, "end_index": 3, "nodes": [
        {"title": "Page 1", "start_index": 1, "end_index": 1},
        {"title": "Page 2", "start_index": 2, "end_index": 2},
        {"title": "Page 3", "start_index": 3, "end_index": 3},
    ]}]
```
**Why this shape**: segments are built with the real FEAT-840 splitter (`segment_pages`) rather than by hand,
so `kind`/`level`/`ordinal` are exactly what the builder will produce; `count_tokens` is stubbed (tiktoken
may download its BPE file). `_profile` builds a valid `LayoutProfile` without pymupdf.

### FILL IN checklist
- [ ] `layout_structure.py::heading_title` — surrounding single `_` pair stripped; bounded by spec §2 "Titles"
- [ ] `layout_structure.py::score_bookmarks` — found-by-containment branch (>= 3 chars, normalized, any segment of the page); bounded by spec §2 "Bookmarks candidate"
- [ ] `layout_structure.py::score_layout` — `clean × density_factor × start_factor`; bounded by spec §2 "Layout candidate"
- [ ] `test_layout_structure.py::test_score_bookmarks_found_and_anchored` — assertions listed in the stub
- [ ] `test_layout_structure.py::test_score_layout_factors` — assertions listed in the stub

---

## Acceptance Criteria

- [ ] `layout_structure.py` exists with `CandidateScore`, `StructureReport`, `StructureResult`, `heading_title`,
  `score_bookmarks`, `score_layout`, `page_structure` exactly as the blueprint fixes them.
- [ ] AC-4 (score part): a rejected bookmark set scores `0.0` with the profile's rejection reason in
  `CandidateScore.rejected`.
- [ ] Bookmark anchors are unique per heading segment; title-in-paragraph counts as found, not anchored.
- [ ] Layout confidence follows `clean × density_factor × start_factor` (3 decimals); running-key headings excluded.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py -q`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py` is clean.
- [ ] Imports work: `from parrot.knowledge.pageindex.layout_structure import score_bookmarks, score_layout, page_structure`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_heading_title` | `### **1 Introduction**`, `## **1** **Introduction**` → `1 Introduction`; backticks / `~~` / surrounding `_` stripped |
| `test_score_bookmarks_found_and_anchored` | found ratio 0.75 on the stub's inputs; anchors unique; paragraph containment found-not-anchored; rejected → 0.0 with reason |
| `test_score_layout_factors` | fewer than 2 headings → 0; sentence-like headings lower `clean`; density `8/density`; start factor 0.5; running keys excluded; depth = level rank |
| `test_page_structure` | root titled by stem, one `Page <n>` child per page |

(Block 3 above is the scaffold.)

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-structure --feature-id FEAT-845`)
2. **Read the spec** at the path listed above for full context (§2 "Titles", "Bookmarks candidate",
   "Layout candidate", "Page fallback"; §3 Module 3)
3. **Check dependencies** — TASK-5333 must be `"done"` in `sdd/tasks/index/pageindex-layout-structure.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm the TASK-5333 names in `layout.py`
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/pageindex-layout-structure.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands as
   `PYTHONPATH=packages/ai-parrot/src pytest <file> -q` (the shared venv is editable-installed on the main checkout;
   never `uv sync` inside the worktree)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5336 pageindex-layout-structure verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(filled by sdd-worker)*

**Completed by**: sdd-worker orchestrator, MCP seat, 1 attempt
**Date**: 2026-11-08
**Notes**: Merged into the feature branch; lint clean. Pageindex suite run directly on the host: only the 4 pre-existing failures (test_adapter x2, test_okf_ontology x2) that also fail on clean origin/dev. Engine background validation is capped at ~60s so it is not used. No review feedback recorded.
