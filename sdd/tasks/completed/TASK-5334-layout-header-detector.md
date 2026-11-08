# TASK-5334: Layout header detector: LayoutHeaders (M1b)

**Feature**: FEAT-845 — PageIndex Layout Structure Builder
**Spec**: `sdd/specs/pageindex-layout-structure.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5333
**Assigned-to**: unassigned

---

## Context

Second half of spec Module 1. pymupdf4llm's default `IdentifyHeaders` treats every span at or below
12 pt as body text (`pymupdf_rag.py:89`), so the fixture's ten bookmarked section titles come out as plain
paragraphs and FEAT-840's segments carry almost no headings. `LayoutHeaders` is the `hdr_info` object the
builder passes to `pymupdf4llm.to_markdown` (through `extract_markdown_per_page(hdr_info=…)`, TASK-5335):
it decides, span by span, whether a line is a heading, from the `LayoutProfile` that TASK-5333 computes.
Rules 1–6 of spec §2 "Header detector", including the rev 0.2 geometry rule 4 (a bold body-size span is a
heading only when it lies inside a recorded standalone bold line's bounding box).

Spec sections: §2 "Header detector (`LayoutHeaders`)", §3 Module 1 skeleton, §4 `test_layout.py` rows
`test_header_detector_rules` and `test_bold_heading_occurrence_collision`, AC-3, AC-20.

---

## Scope

- Append `class LayoutHeaders` to `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py`, after the
  end of `analyze_layout`, with `__init__(profile)` and `get_header_id(span, page=None) -> str` implementing
  rules 1–6 in order, plus private helpers `_in_running_line`, `_inside_bold_line`, `_matches_bookmark`.
- Extend `layout.py`'s imports: `_titles_match` from `segments` (rule 5) and `Any` from `typing`.
- Append three tests to `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py`:
  `test_header_detector_rules` (hand-built spans + a fake page), `test_bold_heading_occurrence_collision`
  (through real `pymupdf4llm.to_markdown(..., hdr_info=LayoutHeaders(profile))`) and
  `test_running_lines_never_headings` (real extraction, AC-3).

**NOT in scope**: forwarding `hdr_info` from `extract_markdown_per_page` (TASK-5335 — this task calls
`pymupdf4llm.to_markdown` directly in its tests so it does not depend on 5335); heading titles / scoring
(TASK-5336); builder wiring (TASK-5340); changing any rule of `analyze_layout` other than the bold-line
bbox flags decision described in Implementation Notes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | Add `LayoutHeaders` (rules 1–6) and its imports |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` | MODIFY | Append the three detector tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.knowledge.pageindex.segments import _titles_match, normalize_title  # verified: segments.py:312, :305
import pymupdf4llm                                                              # 0.0.27 — to_markdown(doc, *, hdr_info=None, page_chunks=False, ...) (verified: hdr_info and page_chunks in signature)
```

### Created by TASK-5333 (dependency — confirm in `layout.py` before starting)
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py
from parrot.knowledge.pageindex.segments import normalize_title   # the import line this task extends
from typing import Literal, Optional                              # this task adds Any
RUNNING_BAND: float = 0.08
class BoldLine(BaseModel): text: str; bbox: tuple[float, float, float, float]
class RunningLine(BaseModel): key: str; band: Literal["top", "bottom"]; pages: int
class Bookmark(BaseModel): level: int; title: str; page: int
class LayoutProfile(BaseModel): page_count; body_size: Optional[int]; heading_sizes: list[int];
    running: list[RunningLine]; bold_lines: dict[int, list[BoldLine]]; bookmarks: list[Bookmark];
    bookmark_rejection: Optional[str]
def running_key(text: str) -> str
def _is_bold(span: dict) -> bool
def _band(y0: float, y1: float, height: float) -> Optional[Literal["top", "bottom"]]
def analyze_layout(pdf_path: str) -> LayoutProfile
# test_layout.py: from parrot.knowledge.pageindex.layout import (  # noqa: E402 … ) block,
#   helpers _write_pdf(path, pages, toc=None), _body(y0, n), FILLER
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
def normalize_title(title: str) -> str            # :305 — strips leading numbering ("2 Getting Started" -> "getting started")
def _titles_match(a: str, b: str) -> bool         # :312 — equality, or containment when the shorter has >= 3 chars

# .venv/.../pymupdf4llm/helpers/pymupdf_rag.py (0.0.27)
#   :415-423 hdr_info dispatch: an object with a callable get_header_id is used as-is
#   :425-431 max_header_id(spans, page): calls get_header_id(s, page=page) for every span of a line and
#            keeps the SHORTEST non-empty prefix ("#" * (min_len - 1) + " ")
#   :621     hdr_string = max_header_id(spans, page=parms.page) — `page` is a pymupdf Page:
#            page.number is 0-based, page.rect.height is the height
#   :623-631 header lines whose spans are all bold are wrapped in **…** ("# **Important Notes**")
#   :1187-1193 its textpage flags are CLIP | ACCURATE_BBOXES | COLLECT_STYLES
# .venv/.../pymupdf4llm/helpers/get_text_lines.py
#   :89-99  adjacent spans of one line with the same style are joined (text concatenated, bbox |= union)
#   :118-137 span["bbox"] is a pymupdf.Rect (always read it as tuple(span["bbox"]))
#   spans carry "text", "size", "flags", "font", "char_flags", "bbox"
# Verified probe (this session, Helvetica, 10 pt): analyze_layout-style line bbox of a standalone bold line
#   [72.0, 89.3, 148.7, 103.1] vs the span bbox pymupdf4llm hands to get_header_id [72.0, 92.7, 148.7, 102.2];
#   bold run-in "Important " span bbox [72.0, 132.7, 120.9, 142.2]; output lines
#   '# **Important Notes**' and '**Important** remarks follow in regular text.'
```

### Does NOT Exist
- ~~`LayoutHeaders`~~ — this task creates it
- ~~`pymupdf4llm.TocHeaders` as a working alternative~~ — `pymupdf_rag.py:187` calls `get_toc()` on its argument; a path string raises `AttributeError`; never use it
- ~~`IdentifyHeaders(body_limit=…)` tuning~~ — `LayoutHeaders` replaces it, it does not subclass or configure it
- ~~a `page` argument that is always present~~ — `get_header_id` must work with `page=None` (hand-built tests); rules 2, 4, 5 need the page and do not fire without it
- ~~`span["bbox"]` as a tuple~~ — in pymupdf4llm it is a `pymupdf.Rect`; in hand-built tests it may be a tuple: always `tuple(float(v) for v in span["bbox"])`
- ~~`heading_title`~~ — TASK-5336 (`layout_structure.py`), not this file

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_layout.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#_titles_match",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#normalize_title"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
pymupdf4llm's own detector shape (`IdentifyHeaders.get_header_id(self, span: dict, page=None) -> str`,
`pymupdf_rag.py:154`): return `""` for body text, otherwise `"#" * level + " "`.

### Key Constraints
- Rules in order (spec §2): 1 empty text → `""`; 2 running line (same band, same normalized key) → `""`;
  3 `round(span["size"])` at heading-size rank *i* → `"#" * (i + 1) + " "`; 4 bold, at body size, bbox inside
  a recorded `BoldLine` bbox of that page (0.5 pt tolerance on each edge) → body-bold level
  `"#" * (len(heading_sizes) + 1) + " "`; 5 bold or above body size and the span's text matches a usable
  bookmark title of the same page via `_titles_match` → body-bold level; 6 otherwise `""`.
- Text containment alone never qualifies under rule 4 (rev 0.2): a bold run-in word repeating part of a
  heading has a different bbox and must get `""`.
- Rule 2: the span's band is `_band(y0, y1, page.rect.height)` and `running_key(span text)` is contained
  in a running key of that band (a running line may be split across spans).
- Rule 5 uses bookmarks only when `profile.bookmark_rejection is None` — *because* a rejected bookmark set
  (non-monotonic, per-page enumeration) is not evidence of a heading.
- `body_size is None` (no countable text): rule 4 cannot fire; rule 5 needs a bold span.
- Pages: `page.number` is 0-based; profile pages are 1-based → `page_no = page.number + 1`.
- **Bbox flag gotcha**: pymupdf4llm builds spans with `ACCURATE_BBOXES` (`pymupdf_rag.py:1187-1193`) while
  `analyze_layout` reads `TEXTFLAGS_TEXT` (195, no `TEXT_ACCURATE_BBOXES` = 512). Accurate boxes are normally
  tighter and inside the default ones (probe above), so rule 4 holds. If
  `test_bold_heading_occurrence_collision` fails through real extraction because a heading span pokes out of
  its recorded line box, you may record the bold-line bboxes in `analyze_layout` with
  `pymupdf.TEXTFLAGS_TEXT | pymupdf.TEXT_ACCURATE_BBOXES` (this task owns `layout.py`) — never widen the
  tolerance — and record the deviation in the Completion Note.

### References in Codebase
- `.venv/lib/python3.12/site-packages/pymupdf4llm/helpers/pymupdf_rag.py:154,415-431,621-631` — detector protocol
- `packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py:305-320` — title helpers

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Extend the two imports in `layout.py` — *why*: rule 5 needs `_titles_match`; `get_header_id` takes `page: Any`.
2. Append `LayoutHeaders` after the end of `analyze_layout` and complete the three helpers — *why*: the rule order in `get_header_id` is fixed by spec §2; only the geometry/containment helpers carry judgement.
3. Extend the test import block and append the three tests — *why*: hand-built spans pin each rule; real extraction pins rev 0.2's collision case and AC-3.
4. Run the Validation Command; if the collision test fails on geometry, apply the flags decision in Implementation Notes — *why*: AC-20 must hold through pymupdf4llm, not only on hand-built spans.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY)
```python
# occurrences: 1 (created by TASK-5333; verify: grep -c 'from parrot.knowledge.pageindex.segments import normalize_title' packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py)
# REPLACE `from parrot.knowledge.pageindex.segments import normalize_title  # verified: segments.py:305` WITH:
from parrot.knowledge.pageindex.segments import _titles_match, normalize_title  # verified: segments.py:312, :305

# occurrences: 1 (created by TASK-5333; verify: grep -c 'from typing import Literal, Optional' packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py)
# REPLACE `from typing import Literal, Optional` WITH:
from typing import Any, Literal, Optional

# occurrences: 1 (verify: grep -c 'def analyze_layout(' packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py)
# APPEND after the last line of `def analyze_layout(` (end of file at the time this task starts):


class LayoutHeaders:
    """pymupdf4llm ``hdr_info`` object driven by a LayoutProfile (rules 1-6 of spec §2)."""

    TOLERANCE: float = 0.5   # points, on each bbox edge (rule 4)

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
        """Return '' or '#'*level + ' '; ``page`` is the pymupdf Page (``page.number`` 0-based)."""
        text = str(span.get("text") or "")
        if not text.strip():
            return ""                                                     # rule 1
        bbox = tuple(float(v) for v in span["bbox"]) if span.get("bbox") is not None else None
        page_no = int(page.number) + 1 if page is not None else None
        if page is not None and bbox is not None and self._in_running_line(text, bbox, float(page.rect.height)):
            return ""                                                     # rule 2
        size = round(float(span.get("size") or 0))
        if size in self._size_rank:
            return "#" * (self._size_rank[size] + 1) + " "                # rule 3
        bold = _is_bold(span)
        body = self.profile.body_size
        if page_no is not None and bbox is not None and bold and body is not None and size == body:
            if self._inside_bold_line(page_no, bbox):
                return self._body_bold_prefix                             # rule 4
        if page_no is not None and (bold or (body is not None and size > body)):
            if self._matches_bookmark(page_no, text):
                return self._body_bold_prefix                             # rule 5
        return ""                                                         # rule 6

    def _in_running_line(self, text: str, bbox: tuple[float, ...], height: float) -> bool:
        """The span sits in a running band and its key is part of a running key of that band."""
        # FILL IN: band = _band(bbox[1], bbox[3], height); key = running_key(text); True when band is not None
        #   and any(key in running for running in self._running.get(band, [])) — bounded by rule 2, AC-3
        raise NotImplementedError

    def _inside_bold_line(self, page_no: int, bbox: tuple[float, ...]) -> bool:
        """The span's bbox lies within a recorded standalone bold line of ``page_no`` (TOLERANCE per edge)."""
        # FILL IN: any BoldLine in self.profile.bold_lines.get(page_no, []) with x0 >= bx0 - T, y0 >= by0 - T,
        #   x1 <= bx1 + T, y1 <= by1 + T — geometry only, never text (rev 0.2) — bounded by rule 4, AC-20
        raise NotImplementedError

    def _matches_bookmark(self, page_no: int, text: str) -> bool:
        """The span's text matches a usable bookmark title of ``page_no`` (``_titles_match``)."""
        # FILL IN: any(_titles_match(text, title) for title in self._bookmark_titles.get(page_no, []))
        #   — bounded by rule 5 (equality or containment of >= 3 chars, segments.py:312)
        raise NotImplementedError
```
**Why this shape**: `get_header_id`'s rule order is spec §2 verbatim and is the part every later task relies
on (heading segments are what TASK-5336 scores and TASK-5338 anchors to), so it is written out; only the
three predicates are FILL INs. Indexing the profile once in `__init__` keeps the per-span call cheap —
pymupdf4llm calls it for every span of every line.

### `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` (MODIFY)
```python
# occurrences: 1 (created by TASK-5333; verify: grep -c 'from parrot.knowledge.pageindex.layout import (' packages/ai-parrot/tests/knowledge/pageindex/test_layout.py)
# EXTEND that import block with: Bookmark, BoldLine, LayoutHeaders, LayoutProfile, RunningLine
# and add below `pymupdf = pytest.importorskip("pymupdf")`:
pymupdf4llm = pytest.importorskip("pymupdf4llm")
# and `from types import SimpleNamespace` to the stdlib imports.

# APPEND at the end of the file:


def _span(text: str, size: float, bbox: tuple[float, float, float, float], bold: bool = False) -> dict:
    """A span dict shaped like pymupdf4llm's (bbox as a pymupdf.Rect)."""
    return {"text": text, "size": size, "flags": 16 if bold else 0, "char_flags": 0,
            "font": "Helvetica-Bold" if bold else "Helvetica", "bbox": pymupdf.Rect(bbox)}


def _page(number: int) -> SimpleNamespace:
    return SimpleNamespace(number=number, rect=SimpleNamespace(height=842.0))


def test_header_detector_rules() -> None:
    """Rules 1-6 on hand-built spans; a body span containing a heading's words gets ''."""
    profile = LayoutProfile(
        page_count=2, body_size=10, heading_sizes=[16, 12],
        running=[RunningLine(key="acme manual", band="top", pages=4)],
        bold_lines={1: [BoldLine(text="important notes", bbox=(72.0, 89.3, 148.7, 103.1))]},
        bookmarks=[Bookmark(level=1, title="2 Getting Started", page=2)],
    )
    hdr = LayoutHeaders(profile)
    # FILL IN: assert, with page=_page(0) unless noted:
    #   rule 1: _span("  ", 16, …) -> ""
    #   rule 2: _span("ACME Manual", 16, (72, 30, 160, 46), bold=True) -> ""  (would be "# " by size)
    #   rule 3: sizes 16 -> "# ", 12 -> "## ", 15.6 -> "# "; also with page=None -> "# "
    #   rule 4: _span("Important Notes", 10, (72.0, 92.7, 148.7, 102.2), bold=True) -> "### ";
    #           run-in _span("Important ", 10, (72.0, 132.7, 120.9, 142.2), bold=True) -> "";
    #           same heading span with page=None -> ""
    #   rule 5: page=_page(1): _span("Getting Started", 10, (72, 200, 200, 212), bold=True) -> "### ";
    #           non-bold body span "Getting Started is easy" at 10 pt -> ""; a profile copy with
    #           bookmark_rejection="non-monotonic: …" -> ""
    #   rule 6: plain body span -> ""


def test_bold_heading_occurrence_collision(tmp_path: Path) -> None:
    """No bookmarks; standalone 'Important Notes' and a run-in bold 'Important' on one page (AC-20)."""
    # FILL IN: one page: (72, 100, "Important Notes", 10, "hebo"); run-in line at y=140 built from
    #   "Important " (hebo) + "remarks follow in regular text." (helv) at x = 72 +
    #   pymupdf.get_text_length("Important ", fontname="hebo", fontsize=10); *_body(200, 30).
    #   profile = analyze_layout(str(path)); assert len(profile.bold_lines[1]) == 1.
    #   chunks = pymupdf4llm.to_markdown(str(path), page_chunks=True, hdr_info=LayoutHeaders(profile))
    #   heading lines = [l for l in chunks[0]["text"].splitlines() if l.startswith("#")]:
    #   exactly one, containing "Important Notes"; none containing "remarks"


def test_running_lines_never_headings(tmp_path: Path) -> None:
    """A 16 pt bold running header and a 'Page n' footer never become '#' lines; their text is kept (AC-3)."""
    # FILL IN: 4 pages, each (72, 40, "ACME Manual", 16, "hebo"), (280, 815, f"Page {n}", 10, "helv"),
    #   (72, 100, f"{n} Chapter {n}", 16, "helv"), (72, 130, f"{n}.1 Section {n}", 12, "helv"), *_body(160, 30).
    #   Real extraction with LayoutHeaders(analyze_layout(...)): no '#' line contains "ACME Manual" or
    #   "Page "; "ACME Manual" still occurs in every page's text; "# " chapter lines do exist
```
**Why this shape**: hand-built spans exercise each rule in isolation (and `page=None`, which only tests
can produce); the two real-extraction tests call `pymupdf4llm.to_markdown` directly so this task does not
depend on TASK-5335, and they are the only way to catch the bbox-flag mismatch described above. The
running header is deliberately 16 pt bold — a heading size — so only rule 2 can keep it out.

### FILL IN checklist
- [ ] `layout.py::LayoutHeaders._in_running_line` — band + running-key containment; bounded by rule 2, AC-3
- [ ] `layout.py::LayoutHeaders._inside_bold_line` — bbox within a BoldLine of the page, 0.5 pt per edge, no text test; bounded by rule 4, AC-20
- [ ] `layout.py::LayoutHeaders._matches_bookmark` — `_titles_match` against same-page titles; bounded by rule 5
- [ ] `test_layout.py::test_header_detector_rules` — every assertion listed
- [ ] `test_layout.py::test_bold_heading_occurrence_collision` — real extraction; bounded by AC-20
- [ ] `test_layout.py::test_running_lines_never_headings` — real extraction; bounded by AC-3
- [ ] (only if the collision test fails on geometry) accurate-bbox flags for bold-line boxes in `analyze_layout` + Completion Note

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.pageindex.layout import LayoutHeaders` works; `LayoutHeaders(profile).get_header_id(span, page=page)` follows rules 1–6 in order
- [ ] AC-3: running headers and page-number footers present on every page are never heading lines in real pymupdf4llm extraction, and their text is still present
- [ ] AC-20: body-bold heading eligibility uses page and line geometry; a separate bold run-in occurrence with matching text is not promoted by the standalone-bold rule, including through pymupdf4llm extraction
- [ ] A body span that merely contains a heading's words gets `""` (rules 3–5 need a larger or bold span)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout.py -q` (TASK-5333's tests included)
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` is clean (AC-18)

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
# packages/ai-parrot/tests/knowledge/pageindex/test_layout.py — appended tests, see the blueprint block.
#   test_header_detector_rules             -> each rule's expected prefix ("", "# ", "## ", "### ")
#   test_bold_heading_occurrence_collision -> one '#' line ("# **Important Notes**"), the run-in line stays body
#   test_running_lines_never_headings      -> no '#' line with "ACME Manual" / "Page "; header text still present
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
   `PYTHONPATH=packages/ai-parrot/src pytest <file> -q` (never `uv sync` in the worktree)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5334 pageindex-layout-structure verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(filled by sdd-worker)*

**Completed by**: sdd-worker orchestrator, MCP seat, 1 attempt
**Date**: 2026-11-08
**Notes**: Merged into the feature branch; lint clean. Pageindex suite run directly on the host: only the 4 pre-existing failures (test_adapter x2, test_okf_ontology x2) that also fail on clean origin/dev. Engine background validation is capped at ~60s so it is not used. No review feedback recorded.
