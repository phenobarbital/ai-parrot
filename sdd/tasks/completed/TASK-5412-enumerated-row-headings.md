# TASK-5412: Enumerated caps-row headings with wrapped-title continuations

**Feature**: FEAT-856 — PageIndex Layout Fixes — Enumerated Enhancement Headings
**Spec**: `sdd/specs/pageindex-layout-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:92245af971f3`

---

## Context

Spec §1 and §3 Module 1. NIST SP 800-53 prints each control enhancement as one row: a bold `(1)` (10 pt) followed by
`ACCOUNT MANAGEMENT | AUTOMATED SYSTEM ACCOUNT MANAGEMENT` in 9 pt non-bold small caps. No heading rule matches that
mixed-style row, so a control and all its enhancements stay one node. This task records such rows (with up to two
caps-only continuation rows when the title wraps) as `EnumeratedLine`s in the layout profile and makes
`LayoutHeaders` tag their spans one level below the bold rows. 868 rows qualify in 800-53, none in the other corpus
PDFs or the Bookstore books; 59 titles wrap (17 inside their block, 42 into the next block).

---

## Scope

- Add constants `ENUMERATED_SEPARATOR` and `MAX_CONTINUATION_ROWS`.
- Add the `EnumeratedLine` model and `LayoutProfile.enumerated_lines` (defaulted).
- Add helpers `_is_caps`, `_is_enumerated_row`, `_continues_title`, `_collect_enumerated_lines`.
- `analyze_layout` fills `enumerated_lines`.
- `LayoutHeaders`: `_enumerated_prefix`, `_inside_enumerated_line`, and the new rule in `get_header_id` (after the
  bold-row rule, before the bookmark rule).
- Tests in `test_layout.py`.

**NOT in scope**: the hybrid level map (`layout_structure.py`, TASK-5413); the bold-row rule, the bookmark rule,
`heading_sizes`; caps rows without `|` (spec Non-Goals); the wiki and the host evaluation (TASK-5414).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | constants, model, field, helpers, `analyze_layout` wiring, `LayoutHeaders` rule |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` | MODIFY | new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# layout.py — nothing new to import
import re                                                          # verified: layout.py:8
from typing import Any, Literal, Mapping, Optional, Sequence       # verified: layout.py:11
from pydantic import BaseModel, Field                              # verified: layout.py:13
from parrot.knowledge.pageindex.segments import normalize_title    # verified: layout.py:15
# test_layout.py — extend the existing import list (verified: test_layout.py:13-25) with:
#   EnumeratedLine, _collect_enumerated_lines, _is_enumerated_row
import pymupdf, pymupdf4llm   # via pytest.importorskip, verified: test_layout.py:10-11
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py
BOLD_REPEAT_MIN_PAGES: int = 3                                     # line 39 (docstring line 40)
_LIST_MARKER_RE = re.compile(r"^\(\s*[A-Za-z0-9]{1,4}\s*\)")       # line 41 — use .fullmatch(text)
class BoldLine(BaseModel): text: str; bbox: tuple[float, float, float, float]; size: Optional[int] = None  # 75-80
class LayoutProfile(BaseModel):                                    # line 83; last field `bold_sizes` at line 94
def running_key(text: str) -> str                                  # line 97
def _is_bold(span: dict) -> bool                                   # line 102
def _visual_rows(block_lines: Sequence[dict]) -> list[list[dict]]  # line 146
def _row_text(row: Sequence[dict]) -> str                          # line 177 — line texts joined by " ", stripped
def _collect_bold_lines(lines, running_keys: set[tuple[str, str]], bold_sizes) -> dict[int, list[BoldLine]]  # 215
def analyze_layout(pdf_path: str) -> LayoutProfile                 # line 360
    # line dicts: page, block, index, block_lines, spans (whitespace-only spans removed), text, bbox, band, key
    #   (lines 382-394); running_keys: set[(band, key)] at 411; `bold_lines = _collect_bold_lines(...)` at 435;
    #   `return LayoutProfile(... bookmarks_dropped=dropped,)` at 445-455
class LayoutHeaders:                                               # line 477
    TOLERANCE: float = 0.5                                         # line 480
    def __init__(self, profile):                                   # line 482 — locals `bold_sizes` (486), `base` (487);
                                                                   #   `self._bold_prefixes` 488-490; `self._running` 491
    def get_header_id(self, span: dict, page: Any = None) -> str   # line 499 — locals text, bbox, page_no, size, bold,
                                                                   #   body; bold-row rule 513-515; bookmark rule 516-518
    def _inside_bold_line(self, page_no: int, bbox: tuple[float, ...]) -> bool   # line 527 — the containment to mirror
    def _matches_bookmark(self, page_no: int, text: str) -> bool   # line 539

# test_layout.py helpers: _write_pdf (31), _body (47), FILLER (27), _span (205), _page (217), _all_bold_texts (304)
# pymupdf4llm 0.0.27 pymupdf_rag.py:425 max_header_id (line takes the shortest non-empty prefix of its spans);
#   :632-638 consecutive header lines with the same prefix are joined into one heading line.
```

### Does NOT Exist
- ~~`EnumeratedLine`~~, ~~`LayoutProfile.enumerated_lines`~~, ~~`ENUMERATED_SEPARATOR`~~, ~~`MAX_CONTINUATION_ROWS`~~,
  ~~`_is_caps`~~, ~~`_is_enumerated_row`~~, ~~`_continues_title`~~, ~~`_collect_enumerated_lines`~~,
  ~~`LayoutHeaders._enumerated_prefix`~~, ~~`LayoutHeaders._inside_enumerated_line`~~ — created by this task.
- ~~`EnumeratedLine.size` / `.level`~~ — the level comes from `LayoutHeaders`, never stored.
- ~~a small-caps / font-variant flag in `_is_bold` or the span dicts~~ — the small caps are plain 9 pt text.
- ~~a new regex for the enumerator~~ — reuse `_LIST_MARKER_RE.fullmatch`.

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
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#LayoutProfile",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#analyze_layout",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#LayoutHeaders",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#_is_bold",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#_visual_rows",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#_row_text",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#running_key"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Only a block's **first** visual row can open a title; the enumerator must be the row's **first** span, bold, and its
  stripped text a full match of `_LIST_MARKER_RE`.
- The rest of the row (spans 2..n joined by spaces, whitespace collapsed) must contain a letter, no lowercase letter
  and `ENUMERATED_SEPARATOR` — because mixed-case bold list items (`(a) Have expired;`) must stay body text.
- Continuation candidates: the block's later rows; only when the block has exactly one row, the first row of the
  **next block on the same page**. Take them in order, at most `MAX_CONTINUATION_ROWS`, stop at the first one
  `_continues_title` rejects.
- Repeat filter as for bold rows: drop a title whose `running_key(joined text)` occurs on `BOLD_REPEAT_MIN_PAGES` or
  more distinct pages.
- The prefix is `"#" * min(6, base + len(bold_sizes)) + " "` using the `base` and `bold_sizes` locals `__init__`
  already computes, so it is one level below the lowest bold prefix (capped at 6).
- The new `get_header_id` rule applies to bold and non-bold spans; it runs after the bold-row rule and before the
  bookmark rule. Profiles without `enumerated_lines` must give today's prefixes (`test_header_detector_rules`).

---

## Implementation Blueprint

### Steps (in order)
1. Add the two constants after the `BOLD_REPEAT_MIN_PAGES` docstring — *why*: spec §3 M1 skeleton.
2. Add `EnumeratedLine` above `LayoutProfile`, and `enumerated_lines` after `bold_sizes` — *why*: defaulted field keeps
   old profiles valid.
3. Add the four helpers above `_keep_page_order` — *why*: pure functions over line dicts unit-test without PDFs.
4. Wire `analyze_layout` — *why*: it is the only function that opens the PDF.
5. Add `_enumerated_prefix`, the rule and `_inside_enumerated_line` to `LayoutHeaders`.
6. Write the tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — constants and model)
```python
# occurrences: 1 (verified: grep -c '"""A bold row whose running_key text occurs on this many distinct pages is a label or table header."""' layout.py)
# AFTER — insert below that docstring line (verified: layout.py:40)
ENUMERATED_SEPARATOR: str = "|"
"""An enumerated title row names its control and enhancement around this separator."""
MAX_CONTINUATION_ROWS: int = 2
"""Caps-only rows that may continue a wrapped enumerated title."""

# occurrences: 1 (verified: grep -c 'class LayoutProfile(BaseModel):' layout.py)
# BEFORE — insert above `class LayoutProfile(BaseModel):` (verified: layout.py:83), two blank lines around it
class EnumeratedLine(BaseModel):
    """A standalone enumerated caps title row (with its continuation rows) and its page geometry."""

    text: str
    bbox: tuple[float, float, float, float]

# occurrences: 1 (verified: grep -c '    bold_sizes: list[int] = Field(default_factory=list)  # largest first, body last; [] means [body_size]' layout.py)
# AFTER — insert below that field (verified: layout.py:94)
    enumerated_lines: dict[int, list[EnumeratedLine]] = Field(default_factory=dict)  # by 1-based page
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — helpers, insert above `_keep_page_order`)
```python
# occurrences: 1 (verified: grep -c 'def _keep_page_order(pages: Sequence\[int\]) -> list\[int\]:' layout.py) — layout.py:264
def _is_caps(text: str) -> bool:
    """Return whether ``text`` has at least one letter and no lowercase letter."""
    letters = [char for char in text if char.isalpha()]
    return bool(letters) and not any(char.islower() for char in letters)


def _is_enumerated_row(row: Sequence[dict]) -> bool:
    """Return whether a visual row opens an enumerated caps title (spec §3 M1)."""
    spans = [span for line in row for span in line["spans"]]
    if len(spans) < 2 or not _is_bold(spans[0]) or not _LIST_MARKER_RE.fullmatch(str(spans[0]["text"]).strip()):
        return False
    rest = " ".join(" ".join(str(span["text"]) for span in spans[1:]).split())
    return _is_caps(rest) and ENUMERATED_SEPARATOR in rest


def _continues_title(row: Sequence[dict], previous: Sequence[dict], running_keys: set[tuple[str, str]]) -> bool:
    """Return whether ``row`` continues the wrapped title whose last row is ``previous``."""
    if any((line["band"], line["key"]) in running_keys for line in row):
        return False
    spans = [span for line in row for span in line["spans"]]
    # FILL IN: return False when spans is empty, when spans[0]'s stripped text fully matches _LIST_MARKER_RE, or when
    #   _row_text(row) is not _is_caps; otherwise return whether the row's top (min line bbox[1]) is at most the
    #   previous row's bottom (max line bbox[3]) plus half of the previous row's height (bottom - min top)
    #   — bounded by spec §3 M1 `_continues_title` docstring
```
**Why**: the half-height window accepts the 800-53 continuations (their top sits 1.7 pt above the previous bottom)
and rejects a caps line further down the page.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — `_collect_enumerated_lines`, after `_continues_title`)
```python
def _collect_enumerated_lines(
    lines: Sequence[dict], running_keys: set[tuple[str, str]]
) -> dict[int, list[EnumeratedLine]]:
    """Return enumerated title rows per page, without titles repeated on ``BOLD_REPEAT_MIN_PAGES`` pages."""
    blocks: dict[tuple[int, int], list[dict]] = {}
    for line in lines:
        blocks.setdefault((line["page"], line["block"]), []).append(line)
    keys = list(blocks)
    candidates: list[tuple[int, str, EnumeratedLine]] = []
    for position, key in enumerate(keys):
        page_no = key[0]
        rows = _visual_rows(blocks[key])
        if not rows or any((line["band"], line["key"]) in running_keys for line in rows[0]):
            continue
        if not _is_enumerated_row(rows[0]):
            continue
        followers = rows[1:]
        if not followers and position + 1 < len(keys) and keys[position + 1][0] == page_no:
            followers = _visual_rows(blocks[keys[position + 1]])[:1]
        title_rows = [rows[0]]
        # FILL IN: for each follower in followers[:MAX_CONTINUATION_ROWS], break at the first one
        #   _continues_title(follower, title_rows[-1], running_keys) rejects, else append it to title_rows;
        #   text = " ".join(_row_text(row) for row in title_rows); bbox = union (min x0, min y0, max x1, max y1) of
        #   every line bbox of title_rows as floats; append (page_no, running_key(text),
        #   EnumeratedLine(text=normalize_title(text), bbox=bbox)) — bounded by spec §2 Overview (M1)
    pages_by_key: dict[str, set[int]] = {}
    for page_no, key, _ in candidates:
        pages_by_key.setdefault(key, set()).add(page_no)
    enumerated: dict[int, list[EnumeratedLine]] = {}
    for page_no, key, enumerated_line in candidates:
        if len(pages_by_key[key]) < BOLD_REPEAT_MIN_PAGES:
            enumerated.setdefault(page_no, []).append(enumerated_line)
    return enumerated
```
**Why**: dict insertion order follows `lines`, so blocks are visited in document order and "next block" is the next
key; the repeat filter runs after every page is seen, exactly as `_collect_bold_lines` does.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — `analyze_layout`)
```python
# occurrences: 1 (verified: grep -c '    bold_lines = _collect_bold_lines(lines, running_keys, bold_sizes)' layout.py)
# AFTER — insert below that line (verified: layout.py:435)
    enumerated_lines = _collect_enumerated_lines(lines, running_keys)
# occurrences: 1 (verified: grep -c '        bookmarks_dropped=dropped,' layout.py)
# AFTER — insert below that keyword argument (verified: layout.py:454)
        enumerated_lines=enumerated_lines,
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — `LayoutHeaders`)
```python
# occurrences: 1 (verified: grep -c '        self._running: dict\[str, list\[str\]\] = {}' layout.py)
# BEFORE — insert above that line (verified: layout.py:491)
        self._enumerated_prefix = "#" * min(6, base + len(bold_sizes)) + " "
# occurrences: 1 (verified: grep -c '        if page_no is not None and (bold or (body is not None and size > body and size not in self._bold_prefixes)):' layout.py)
# BEFORE — insert above that line (verified: layout.py:516)
        if page_no is not None and bbox is not None and self._inside_enumerated_line(page_no, bbox):
            return self._enumerated_prefix
# occurrences: 1 (verified: grep -c '    def _matches_bookmark(self, page_no: int, text: str) -> bool:' layout.py)
# BEFORE — insert above that method (verified: layout.py:539)
    def _inside_enumerated_line(self, page_no: int, bbox: tuple[float, ...]) -> bool:
        """Return whether ``bbox`` is inside a recorded enumerated line on ``page_no``."""
        # FILL IN: same containment as _inside_bold_line (layout.py:527-537, TOLERANCE on every side) over
        #   self.profile.enumerated_lines.get(page_no, []) — bounded by spec §3 M1
```
**Why**: the rule sits after the bold-row rule so a bold heading row keeps its own level, and before the bookmark
rule so a bold `(1)` that happens to prefix a bookmark title still gets the enumerated level.

### FILL IN checklist
- [ ] `_continues_title` — marker, caps and proximity checks
- [ ] `_collect_enumerated_lines` — continuation loop, text, union bbox, candidate tuple
- [ ] `_inside_enumerated_line` — containment
- [ ] tests below — bodies

---

## Acceptance Criteria

- [ ] `_is_enumerated_row`: bold `(1)` + `ACCOUNT MANAGEMENT | DISABLE ACCOUNTS` → True; the same without `|`, with
      mixed case, with a non-bold `(1)`, or as one span → False.
- [ ] A synthetic PDF with a 10 pt body, a bold 10 pt `(1)` and 9 pt caps `ACCOUNT MANAGEMENT | DISABLE ACCOUNTS` on one
      baseline → one `EnumeratedLine` on page 1 with text `(1) account management | disable accounts` (normalized);
      bold `(a) Have expired;` and `(2)` + `PLAIN CAPS TITLE` (no `|`) → none.
- [ ] Hand-built line dicts: a title continued by a later row of its block and a title continued by the next block's
      first row each give one `EnumeratedLine` whose text ends with the continuation; a mixed-case row and a caps row
      far below are not joined; a title on 3 pages is dropped.
- [ ] heading_sizes `[16, 14]`, bold_sizes `[12, 10]` → a span inside an enumerated line gets `"##### "`; heading_sizes
      `[26, 16, 14, 13]`, bold_sizes `[11, 10]` → `"###### "` (capped); a span outside → `""`.
- [ ] Through `pymupdf4llm.to_markdown(..., hdr_info=LayoutHeaders(profile))` the synthetic enumerated row is exactly
      one heading line containing `(1)`, `ACCOUNT MANAGEMENT` and `DISABLE ACCOUNTS`.
- [ ] Existing `test_layout.py` tests pass unchanged; `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py -q`

---

## Test Specification

```python
# test_layout.py — reuse _write_pdf, _body, FILLER, _span, _page
def _line(page: int, block: int, y: float, *spans: tuple[str, float, bool], x: float = 72.0) -> dict:
    """Build an analyze_layout-shaped line dict from (text, size, bold) spans."""
    # FILL IN: span dicts {"text", "size", "flags": 16 if bold else 0, "font"}; text = joined span texts stripped;
    #   bbox = (x, y, x + 300, y + 10); band None; key running_key(text); page, block, index 0, block_lines 1
    ...


def test_enumerated_row_detection() -> None:
    # FILL IN: rows built from _line(...) with the shapes in the first acceptance criterion
    ...


def test_enumerated_lines_in_profile(tmp_path: Path) -> None:
    # FILL IN: "(1)" 10 pt "hebo" at (72, 100) + caps 9 pt "helv" right after it on the same baseline; "(a) Have
    #   expired;" 10 pt "hebo" at (72, 140); "(2)" + "PLAIN CAPS TITLE" at y 180; _body(220, 30)
    ...


def test_enumerated_title_continuations() -> None:
    # FILL IN: _collect_enumerated_lines over hand-built lines: block 0 = title row + continuation row 11 pt below;
    #   block 1 = one-row title, block 2 = its continuation 11 pt below; block 3 = mixed-case row; a caps row 200 pt
    #   below a title in another block is not joined
    ...


def test_enumerated_repeat_filter() -> None:
    # FILL IN: the same title line dict on pages 1, 2 and 3 → {}
    ...


def test_enumerated_prefix_level() -> None:
    # FILL IN: LayoutProfile(..., enumerated_lines={1: [EnumeratedLine(text="t", bbox=(72, 90, 400, 104))]})
    ...


def test_enumerated_heading_markdown(tmp_path: Path) -> None:
    # FILL IN: same PDF shape as test_enumerated_lines_in_profile; exactly one heading line with the three parts
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-fixes --feature-id FEAT-856`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5412 pageindex-layout-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude (Opus 5.5) — /sdd-fix session agent:sdd-fix:087cd628
**Date**: 2026-11-09
**Notes**: Implemented as blueprinted: `ENUMERATED_SEPARATOR`, `MAX_CONTINUATION_ROWS`, `EnumeratedLine`,
`LayoutProfile.enumerated_lines`, helpers `_is_caps`, `_is_enumerated_row`, `_continues_title`,
`_collect_enumerated_lines`; `analyze_layout` fills the field; `LayoutHeaders._enumerated_prefix` /
`_inside_enumerated_line` and the new rule between the bold-row and bookmark rules. Tests:
`test_enumerated_row_detection`, `test_enumerated_lines_in_profile`, `test_enumerated_title_continuations` (hand-built
lines: same-block and next-block continuations, mixed-case and far-below rows not joined),
`test_enumerated_repeat_filter`, `test_enumerated_prefix_level` (`#####`, capped `######`),
`test_enumerated_heading_markdown`, plus `test_enumerated_wrapped_heading_markdown` (a wrapped title renders as one
heading line through pymupdf4llm's same-prefix line join). Validation: test_layout.py 36 passed; ruff clean;
test_builder_layout.py + test_layout_integration.py 15 passed, 1 failed — `test_fixture_import_is_hybrid_and_anchored`,
which fails identically on the untouched base commit 252c96ee0e (optimizer-expanded nodes without start_index; filed
as `issue:5396799daf67`, not caused by this task).

**Deviations from spec**: `EnumeratedLine.text` is built from the title's spans joined by single spaces (whitespace
collapsed) instead of `_row_text`, because the marker and the title are separate spans of one PyMuPDF line
(`(1)` + `ACCOUNT MANAGEMENT …`) and `_row_text` would record `(1)account management …`. It matches the heading text
pymupdf4llm renders. One extra test, `test_enumerated_wrapped_heading_markdown` (spec §4's markdown row mentions the
continuation).
