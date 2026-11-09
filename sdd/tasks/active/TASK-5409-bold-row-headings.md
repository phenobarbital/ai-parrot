# TASK-5409: Bold-row headings at body-text sizes, with list/lowercase/repeat guards

**Feature**: FEAT-855 — PageIndex Layout Structure Fixes
**Spec**: `sdd/specs/pageindex-layout-structure-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5408
**Assigned-to**: unassigned

**Discovered-from**: `issue:a3d282c67ed0`

---

## Context

Spec §1 causes 2–4 (bold-row half) and §3 Module 2. NIST 800-53's control headings are 11 pt bold and AICPA's
section sub-headings 12 pt bold, both on a 10 pt body; those sizes carry so much prose that the 10 % share cap keeps
them out of `heading_sizes`, and the bold-line rule only accepts exactly the body size. 800-53 also stores `AC-2` and
`ACCOUNT MANAGEMENT` as two PyMuPDF lines of one block on one baseline, so neither is "standalone". Meanwhile the
body-size rule already turns bold list items (`(a) Have expired;`) into headings. This task moves bold detection to
visual rows, adds one larger body-text size, gives each bold size its own heading level, and adds the list,
lowercase-start and repeated-text guards.

---

## Scope

- Add constants `MAX_BOLD_LEVELS`, `ROW_OVERLAP`, `BOLD_REPEAT_MIN_PAGES`, `_LIST_MARKER_RE`, `_LIST_TAIL_RE`.
- Add `BoldLine.size` and `LayoutProfile.bold_sizes` (defaulted).
- Add helpers `_bold_sizes`, `_visual_rows`, `_row_all_bold`, `_bold_row_size`, `_collect_bold_lines`.
- Replace `analyze_layout`'s bold-line loop with `_collect_bold_lines`; pass `bold_sizes` to the profile.
- `LayoutHeaders`: per-size `_bold_prefixes`; rule 4 uses them.
- Tests for rows, sizes, split rows, guards and prefix levels.

**NOT in scope**: the bookmark rule (rule 5) and `_matches_bookmark` (TASK-5410); outline repair (TASK-5408, done
first); `heading_sizes` computation, `_HEADING_SHARE_CAP`, `score_layout`; the wiki (TASK-5411).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | constants, fields, helpers, bold-row detection, per-size prefixes |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` | MODIFY | new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# layout.py (after TASK-5408 adds bisect and Sequence)
import re                                                 # verified: layout.py:7
from typing import Any, Literal, Optional                  # verified: layout.py:10 (TASK-5408 adds Sequence; ADD Mapping here)
from parrot.knowledge.pageindex.segments import _titles_match, normalize_title  # verified: layout.py:14
# tests: as test_layout.py:13-22, plus `_visual_rows` added to that import list
import pymupdf, pymupdf4llm   # via pytest.importorskip, verified: test_layout.py:10-11
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py
_HEADING_SHARE_CAP: float = 0.10                           # line 30
_MAX_BOLD_WORDS: int = 12                                  # line 31
class BoldLine(BaseModel): text: str; bbox: tuple[float, float, float, float]   # lines 64-68
class LayoutProfile(BaseModel): ...; bold_lines: dict[int, list[BoldLine]]; ...  # line 71 (bold_lines line 78)
def running_key(text: str) -> str                          # line 83
def _is_bold(span: dict) -> bool                           # line 88
def analyze_layout(pdf_path: str) -> LayoutProfile:        # line 147
    # each line dict: page, block, index, block_lines, spans (whitespace-only spans removed), text, bbox, band, key
    #   (lines 166-180); running_keys: set[(band, key)] (198); size_counts: Counter[int] of chars per rounded size
    #   over non-running lines (203-205); body_size (206); heading_sizes (208-219);
    #   bold-line loop to replace: `bold_lines: dict[int, list[BoldLine]] = {}` (221) through line 243
class LayoutHeaders:                                       # line 260
    def __init__(self, profile: LayoutProfile) -> None:    # line 265
        self._size_rank = {...}                            # line 267
        self._body_bold_prefix = "#" * (len(profile.heading_sizes) + 1) + " "   # line 268
    def get_header_id(self, span: dict, page: Any = None) -> str:   # line 277
        # rule 4 today (lines 289-293):
        # bold = _is_bold(span); body = self.profile.body_size
        # if page_no is not None and bbox is not None and bold and body is not None and size == body:
        #     if self._inside_bold_line(page_no, bbox): return self._body_bold_prefix
    def _inside_bold_line(self, page_no: int, bbox: tuple[float, ...]) -> bool:   # line 305 (unchanged)

# pymupdf4llm 0.0.27 helpers/pymupdf_rag.py:425 — max_header_id: a line takes the SHORTEST non-empty prefix
#   among its spans, so tagging every span of a visual row makes the row one heading line.
```

### Does NOT Exist
- ~~`LayoutProfile.bold_sizes`~~, ~~`BoldLine.size`~~, ~~`_visual_rows`~~, ~~`_bold_sizes`~~, ~~`_bold_row_size`~~,
  ~~`_row_all_bold`~~, ~~`_collect_bold_lines`~~, ~~`LayoutHeaders._bold_prefixes`~~ — created by this task.
- ~~a small-caps / font-variant detector~~ — not added (spec Non-Goals).
- ~~`BoldLine.level`~~ — the level is derived from `size` in `LayoutHeaders`, never stored.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_layout.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#BoldLine",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#LayoutProfile",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#analyze_layout",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#LayoutHeaders",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#_is_bold",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#running_key"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- With no secondary text size, every prefix must equal today's (`_bold_prefixes == {body: _body_bold_prefix}`) —
  `test_header_detector_rules` and `test_bold_heading_occurrence_collision` must pass unchanged.
- Standalone keeps today's meaning at row level: the block has one row, or the row is the first row and no other row
  of the block is all-bold. Skip any row containing a running line.
- The repeat filter counts **distinct pages** per `running_key(row text)`; two equal rows on one page are kept
  (`test_bold_standalone_lines` has two `Important Notes` on page 1).
- Guards check the **raw** joined row text (not `normalize_title`, which casefolds and strips `;`).
- Prefix depth is capped at 6 `#` (markdown's maximum); `heading_sizes` has at most 4 entries and `bold_sizes` at
  most 2, so the cap is defensive.

### References in Codebase
- `layout.py:221-243` — the loop being replaced (keep its word cap and `.`/`,` rule).

---

## Implementation Blueprint

### Steps (in order)
1. Add `Mapping` to the typing import — *why*: `_bold_sizes` signature (spec skeleton).
2. Add the constants below `BOOKMARK_MAX_DROPPED_SHARE` (added by TASK-5408) — *why*: spec §3 M2.
3. Add `size` to `BoldLine` and `bold_sizes` to `LayoutProfile` — *why*: defaults keep old profiles valid.
4. Add the five helpers between `_band` and `_keep_page_order` — *why*: pure functions unit-test without PDFs.
5. Replace the bold-line loop with `bold_sizes = _bold_sizes(...)` + `bold_lines = _collect_bold_lines(...)` and pass
   `bold_sizes=bold_sizes` to `LayoutProfile(...)` — *why*: one place computes sizes, one place decides rows.
6. Add `_bold_prefixes` in `LayoutHeaders.__init__` and switch rule 4 — *why*: one heading level per bold size.
7. Write the tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — constants)
```python
# occurrences: 1 (verified: grep -c '_MAX_BOLD_WORDS: int = 12' layout.py) — insert after the
# BOOKMARK_MAX_DROPPED_SHARE docstring that TASK-5408 placed below this anchor (verified: layout.py:31)
MAX_BOLD_LEVELS: int = 2
"""Bold-row heading levels: the body size plus at most one larger body-text size."""
ROW_OVERLAP: float = 0.5
"""Lines of one block share a visual row when their vertical extents overlap by this share of the shorter one."""
BOLD_REPEAT_MIN_PAGES: int = 3
"""A bold row whose running_key text occurs on this many distinct pages is a label or table header."""
_LIST_MARKER_RE = re.compile(r"^\(\s*[A-Za-z0-9]{1,4}\s*\)")
_LIST_TAIL_RE = re.compile(r"(?:[;:]|;\s*(?:and|or))$", re.IGNORECASE)
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — fields)
```python
# occurrences: 1 (verified: grep -c '    bbox: tuple[float, float, float, float]' layout.py)
# AFTER — insert below `    bbox: tuple[float, float, float, float]` (verified: layout.py:68)
    size: Optional[int] = None
# In LayoutProfile, insert below `    bookmarks_dropped: int = 0` (added by TASK-5408 after layout.py:80):
    bold_sizes: list[int] = Field(default_factory=list)
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — helpers, insert above `_keep_page_order`)
```python
def _bold_sizes(size_counts: Mapping[int, int], body_size: Optional[int], heading_sizes: Sequence[int]) -> list[int]:
    """Return the body size preceded by at most ``MAX_BOLD_LEVELS - 1`` larger body-text sizes, largest first."""
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
    """Group a block's lines, in order, into visual rows (vertical overlap >= ``ROW_OVERLAP`` of the shorter)."""
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
    """Whether a row has spans and every one of them is bold."""
    spans = [span for line in row for span in line["spans"]]
    return bool(spans) and all(_is_bold(span) for span in spans)


def _bold_row_size(row: Sequence[dict], bold_sizes: Sequence[int]) -> Optional[int]:
    """Return the row's rounded size when the row is a bold heading candidate, else None (spec §3 M2)."""
    if not _row_all_bold(row):
        return None
    sizes = {round(float(span["size"])) for line in row for span in line["spans"]}
    # FILL IN: return None unless len(sizes) == 1 and that size is in bold_sizes; join the line texts with " "
    #   (strip); return None when the text is empty, has more than _MAX_BOLD_WORDS words, ends with "." or ",",
    #   matches _LIST_MARKER_RE (match) or _LIST_TAIL_RE (search), or its first alphanumeric char is lowercase;
    #   else return the size — bounded by spec §3 M2 `_bold_row_size` docstring
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — `_collect_bold_lines`, after `_bold_row_size`)
```python
def _collect_bold_lines(
    lines: Sequence[dict], running_keys: set[tuple[Optional[str], str]], bold_sizes: Sequence[int]
) -> dict[int, list[BoldLine]]:
    """Return standalone bold heading rows per page, without rows repeated on ``BOLD_REPEAT_MIN_PAGES`` pages."""
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
            # FILL IN: standalone = one row, or row_index == 0 and no other row is _row_all_bold; skip otherwise.
            #   text = " ".join(non-empty line texts).strip(); bbox = union (min x0, min y0, max x1, max y1) of the
            #   row's line bboxes as floats; append (page_no, running_key(text),
            #   BoldLine(text=normalize_title(text), bbox=bbox, size=size)) — bounded by spec §2 Overview (M2)
    pages_by_key: dict[str, set[int]] = {}
    for page_no, key, _ in candidates:
        pages_by_key.setdefault(key, set()).add(page_no)
    bold_lines: dict[int, list[BoldLine]] = {}
    for page_no, key, bold_line in candidates:
        if len(pages_by_key[key]) < BOLD_REPEAT_MIN_PAGES:
            bold_lines.setdefault(page_no, []).append(bold_line)
    return bold_lines
```
**Why**: blocks are visited in document order (dict insertion order follows `lines`), so per-page order matches
today's; the repeat filter runs after all pages are seen.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — `analyze_layout`)
```python
# occurrences: 1 (verified: grep -c '    bold_lines: dict[int, list[BoldLine]] = {}' layout.py)
# REPLACE `    bold_lines: dict[int, list[BoldLine]] = {}` (verified: layout.py:221) and the loop below it through
# line 243 (the `bold_lines.setdefault(...).append(BoldLine(...))` call) with:
    bold_sizes = _bold_sizes(size_counts, body_size, heading_sizes)
    bold_lines = _collect_bold_lines(lines, running_keys, bold_sizes)
# and in the `return LayoutProfile(...)` call add `bold_sizes=bold_sizes,` after `bold_lines=bold_lines,`
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — `LayoutHeaders`)
```python
# occurrences: 1 (verified: grep -c '        self._body_bold_prefix = "#" * (len(profile.heading_sizes) + 1) + " "' layout.py)
# AFTER — insert below that line (verified: layout.py:268)
        bold_sizes = profile.bold_sizes or ([profile.body_size] if profile.body_size is not None else [])
        base = len(profile.heading_sizes) + 1
        self._bold_prefixes: dict[int, str] = {
            size: "#" * min(6, base + rank) + " " for rank, size in enumerate(bold_sizes)
        }
# occurrences: 1 (verified: grep -c '        if page_no is not None and bbox is not None and bold and body is not None and size == body:' layout.py)
# REPLACE that line and the return two lines below it (verified: layout.py:291-293) with:
        if page_no is not None and bbox is not None and bold and size in self._bold_prefixes:
            if self._inside_bold_line(page_no, bbox):
                return self._bold_prefixes[size]
```
**Why**: rank 0 is the largest bold size, so a body-text size above body ranks one level above the body size, and
both stay below every size-ranked heading. `body` is still used by rule 5 (TASK-5410 edits that line).

### FILL IN checklist
- [ ] `_bold_row_size` — size, word, punctuation, list and lowercase checks
- [ ] `_collect_bold_lines` — standalone test, text, union bbox, candidate tuple
- [ ] tests below — bodies

---

## Acceptance Criteria

- [ ] `_visual_rows` puts two same-baseline lines in one row and a lower line in the next.
- [ ] Synthetic PDF with 10 pt body, 12 pt prose above 10 % of characters and a standalone 12 pt bold line →
      `bold_sizes == [12, 10]` and a `BoldLine` with `size == 12`.
- [ ] `AC-2` + `ACCOUNT MANAGEMENT` bold at one size on one baseline → one bold line `ac-2 account management`, and
      `pymupdf4llm.to_markdown(..., hdr_info=LayoutHeaders(profile))` emits one heading line containing both words.
- [ ] Bold `(a) Have expired;`, a bold row ending `; and`, a lowercase bold term and a bold label printed on 3 pages
      are not bold lines; `Important Notes` still is.
- [ ] heading_sizes `[16, 14]`, bold_sizes `[12, 10]`: a 12 pt bold span inside a recorded row → `"### "`, a 10 pt one
      → `"#### "`.
- [ ] Existing `test_layout.py` tests pass unchanged (besides TASK-5408's unpacking update); `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py -q`

---

## Test Specification

```python
# test_layout.py — reuse _write_pdf, _body, FILLER, _span, _page
def test_visual_rows_groups_same_baseline_lines() -> None:
    lines = [
        {"bbox": (72, 100, 100, 112), "spans": [], "text": "AC-2"},
        {"bbox": (108, 100, 250, 112), "spans": [], "text": "ACCOUNT MANAGEMENT"},
        {"bbox": (72, 120, 250, 132), "spans": [], "text": "Control:"},
    ]
    assert [[line["text"] for line in row] for row in _visual_rows(lines)] == [["AC-2", "ACCOUNT MANAGEMENT"], ["Control:"]]


def test_secondary_text_size_bold_rows(tmp_path: Path) -> None:
    # FILL IN: one page: _body(200, 30) at 10 pt + 8 lines of FILLER at 12 pt "helv" + (72, 100, "Revisions In This
    #   Version", 12, "hebo"); assert profile.bold_sizes == [12, 10] and a bold line with size 12 and that text
    ...


def test_split_row_heading(tmp_path: Path) -> None:
    # FILL IN: insert "AC-2" at (72, 100) and "ACCOUNT MANAGEMENT" at (108, 100), both 10 pt "hebo", plus body text;
    #   assert "ac-2 account management" in [l.text for l in profile.bold_lines[1]]; render with pymupdf4llm and
    #   assert exactly one heading line contains both "AC-2" and "ACCOUNT MANAGEMENT"
    ...


def test_bold_row_guards(tmp_path: Path) -> None:
    # FILL IN: 3 pages; page 1 bold rows "(a) Have expired;", "Monitor changes to roles; and", "adequate security",
    #   "Important Notes"; "DATE TYPE REVISION" bold on all 3 pages; assert only "important notes" survives
    ...


def test_header_prefix_levels_with_secondary_size() -> None:
    # FILL IN: LayoutProfile(page_count=1, body_size=10, heading_sizes=[16, 14], bold_sizes=[12, 10],
    #   bold_lines={1: [BoldLine(text="a", bbox=(72, 90, 200, 104), size=12),
    #                   BoldLine(text="b", bbox=(72, 190, 200, 204), size=10)]}); spans inside each → "### " / "#### "
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-structure-fixes --feature-id FEAT-855`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5408 must be `"done"` in `sdd/tasks/index/pageindex-layout-structure-fixes.json`
4. **Verify the Codebase Contract** before writing any code (TASK-5408 shifted line numbers in `layout.py`)
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5409 pageindex-layout-structure-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
