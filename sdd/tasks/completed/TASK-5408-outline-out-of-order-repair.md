# TASK-5408: Outline repair — drop out-of-order bookmarks and report the count

**Feature**: FEAT-855 — PageIndex Layout Structure Fixes
**Spec**: `sdd/specs/pageindex-layout-structure-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:a3d282c67ed0`

---

## Context

Spec §1 cause 1 and §3 Module 1. NIST SP 800-53 r5 has 358 bookmarks (every family and control). One entry,
`PS-1 POLICY AND PROCEDURES` (entry 223), is filed under §3.15 PT but points back to page 249, and
`_read_bookmarks` rejects the whole outline as `non-monotonic: page decreases at entry 223`. This task keeps an
outline whose out-of-order entries are a small minority (≤ `floor(5 % × valid entries)`), drops the fewest entries
that restore page order, and makes the drop count visible in `LayoutProfile.bookmarks_dropped` and on the bookmarks
`CandidateScore.dropped`. Outlines under 20 entries tolerate nothing, so today's small-outline behaviour (and the
existing `test_bookmarks_rejected_non_monotonic`) is unchanged.

---

## Scope

- Add `BOOKMARK_MAX_DROPPED_SHARE`, `_keep_page_order` and the 3-tuple `_read_bookmarks` to `layout.py`.
- Add `LayoutProfile.bookmarks_dropped`; wire it in `analyze_layout` and log a drop at INFO.
- Add `CandidateScore.dropped` to `layout_structure.py` and populate it in both `score_bookmarks` returns.
- Update the one test that unpacks `_read_bookmarks`; add tests for the new behaviour.

**NOT in scope**: bold rows / `bold_sizes` (TASK-5409), the bookmark-match rule in `LayoutHeaders` (TASK-5410),
`layout_eval` output, `builder.py`, the wiki page (TASK-5411).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | constant, `_keep_page_order`, 3-tuple `_read_bookmarks`, `bookmarks_dropped` |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` | MODIFY | `CandidateScore.dropped`, `score_bookmarks` |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` | MODIFY | update unpacking; new outline tests |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py` | MODIFY | `dropped` propagation test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# layout.py today
import logging                                   # verified: layout.py:5
import math                                      # verified: layout.py:6
import re                                        # verified: layout.py:7
from collections import Counter                  # verified: layout.py:8
from typing import Any, Literal, Optional        # verified: layout.py:10
from pydantic import BaseModel, Field            # verified: layout.py:12
# ADD in this task (stdlib): `import bisect` and `Sequence` in the typing import
# layout_structure.py today
from parrot.knowledge.pageindex.layout import LayoutProfile, StructureMode, StructureSource, running_key  # verified: layout_structure.py:17
# tests today
from parrot.knowledge.pageindex.layout import (Bookmark, BoldLine, LayoutHeaders, LayoutProfile, RunningLine,
    UnreadablePDFError, _read_bookmarks, analyze_layout)   # verified: test_layout.py:13-22
from parrot.knowledge.pageindex.layout_structure import score_bookmarks   # verified: layout_structure.py:96
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py
_MAX_BOLD_WORDS: int = 12                                    # line 31
_ENUM_TITLE_RE = re.compile(r"^(page|p\.?)?\s*\d+$", re.IGNORECASE)   # line 32
class Bookmark(BaseModel): level: int; title: str; page: int # line 48
class LayoutProfile(BaseModel):                              # line 71
    bookmarks: list[Bookmark] = Field(default_factory=list)  # line 79
    bookmark_rejection: Optional[str] = None                 # line 80
def _read_bookmarks(raw_toc: list[list], page_count: int) -> tuple[list[Bookmark], Optional[str]]:  # line 104
    # today: collects valid entries and normalizes levels inline (lines 109-125), "fewer than 2 usable entries"
    # (127-128), first decrease → "non-monotonic: page decreases at entry {index}" (130-132, index starts at 2),
    # per-page enumeration (134-143)
def analyze_layout(pdf_path: str) -> LayoutProfile:          # line 147
    bookmarks, rejection = _read_bookmarks(raw_toc, page_count)   # line 245
    logger.debug("analyze_layout %s: %d pages, %d bookmarks, rejection=%s", ...)   # lines 246-248
    return LayoutProfile(..., bookmarks=bookmarks, bookmark_rejection=rejection)   # lines 249-257 (rejection at 256)

# packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py
class CandidateScore(BaseModel):                             # line 28
    source: Literal["bookmarks", "layout"]; confidence: float; entries: int; anchored: int
    rejected: Optional[str] = None                           # line 35
def score_bookmarks(profile: LayoutProfile, segments: Sequence[Segment]) -> tuple[CandidateScore, list[dict]]:  # line 96
    # rejection return at line 101, success return at line 130

# packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py
def _profile(page_count: int, bookmarks=(), rejection=None, running=()) -> LayoutProfile:   # line 22
def _segs(*pages: str)                                       # line 17
def test_score_bookmarks_found_and_anchored():               # line 49
```

### Does NOT Exist
- ~~`LayoutProfile.bookmarks_dropped`~~, ~~`CandidateScore.dropped`~~, ~~`_keep_page_order`~~,
  ~~`BOOKMARK_MAX_DROPPED_SHARE`~~ — created by this task.
- ~~`StructureReport.dropped`~~ — the count lives on the bookmarks `CandidateScore` only.
- ~~a `bisect` import in layout.py~~ — not there today; add it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_layout.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#_read_bookmarks",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#analyze_layout",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#LayoutProfile",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#CandidateScore",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#score_bookmarks"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep the three rejection messages verbatim — the tests and the wiki quote them.
- The tolerance is `math.floor(BOOKMARK_MAX_DROPPED_SHARE * len(entries))` over the **valid** entries (after title /
  page filtering), with no `max(1, …)`: a 2-entry outline must still be rejected.
- When the outline is rejected as non-monotonic, return the un-dropped normalized list (diagnostic, as today) and
  `dropped = 0`.
- `_keep_page_order` must be deterministic (patience sort with `bisect.bisect_right` so equal pages stay
  non-decreasing, predecessor links for reconstruction).

### References in Codebase
- `layout.py:104-144` — the function being restructured.
- `layout_structure.py:96-130` — `score_bookmarks`.

---

## Implementation Blueprint

### Steps (in order)
1. Add `import bisect` and `Sequence` to `layout.py`'s imports — *why*: the patience sort and the helper signature.
2. Add the constant below `_MAX_BOLD_WORDS` and the field below `bookmark_rejection` — *why*: spec §2 Data Models.
3. Add `_keep_page_order` above `_read_bookmarks` and restructure `_read_bookmarks` into collect → drop → normalize →
   check — *why*: levels must be normalized after the removal so a dropped entry cannot leave a level jump.
4. Unpack the 3-tuple in `analyze_layout`, log drops at INFO, pass `bookmarks_dropped` — *why*: a repair must be
   visible in logs and in the profile.
5. Add `dropped` to `CandidateScore` and pass `dropped=profile.bookmarks_dropped` in both returns — *why*: the
   `StructureReport.candidates` list is the user-visible record.
6. Update `test_bookmarks_usable_and_levels_normalized` to unpack three values; add the new tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — constant)
```python
# occurrences: 1 (verified: grep -c '_MAX_BOLD_WORDS: int = 12' layout.py)
# AFTER — insert below `_MAX_BOLD_WORDS: int = 12` (verified: layout.py:31)
BOOKMARK_MAX_DROPPED_SHARE: float = 0.05
"""Out-of-order entries an outline may lose (share of its valid entries, rounded down) and still be used."""
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — profile field)
```python
# occurrences: 1 (verified: grep -c '    bookmark_rejection: Optional[str] = None' layout.py)
# AFTER — insert below `    bookmark_rejection: Optional[str] = None` (verified: layout.py:80)
    bookmarks_dropped: int = 0
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — `_read_bookmarks`)
```python
# occurrences: 1 (verified: grep -c 'def _read_bookmarks(raw_toc: list[list], page_count: int) -> tuple[list[Bookmark], Optional[str]]:' layout.py)
# REPLACE the function starting at that line (verified: layout.py:104, ends at :144) with:
def _keep_page_order(pages: Sequence[int]) -> list[int]:
    """Return the indices of one longest non-decreasing subsequence of ``pages``, in order.

    Deterministic patience sort (``bisect.bisect_right`` over the tails, predecessor links); empty input
    returns ``[]``.
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
    """
    entries: list[tuple[int, str, int]] = []
    # FILL IN: the validation loop from today's lines 111-122 (skip non-list entries, int() level/page with
    #   TypeError/ValueError → continue, empty title or page outside 1..page_count → continue), appending
    #   (level, title, page) WITHOUT normalizing the level — bounded by spec §3 M1 docstring
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
    # FILL IN: today's three checks (lines 127-143) on `usable`, returning a 3-tuple: "fewer than 2 usable entries"
    #   → (usable, msg, dropped); first decrease → (usable, f"non-monotonic: page decreases at entry {index}", 0);
    #   per-page enumeration → (usable, "per-page enumeration", dropped); else (usable, None, dropped)
```
**Why**: collect-then-drop keeps today's validation and messages intact while making the drop explicit and
bounded; `bisect_right` keeps equal pages (several entries on one page) in the subsequence.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — wiring)
```python
# occurrences: 1 (verified: grep -c '    bookmarks, rejection = _read_bookmarks(raw_toc, page_count)' layout.py)
# REPLACE `    bookmarks, rejection = _read_bookmarks(raw_toc, page_count)` (verified: layout.py:245) with:
    bookmarks, rejection, dropped = _read_bookmarks(raw_toc, page_count)
    if dropped:
        logger.info("analyze_layout %s: dropped %d out-of-order bookmark(s) of %d", pdf_path, dropped, len(bookmarks) + dropped)
# occurrences: 1 (verified: grep -c '        bookmark_rejection=rejection,' layout.py)
# AFTER — insert below `        bookmark_rejection=rejection,` (verified: layout.py:256)
        bookmarks_dropped=dropped,
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    rejected: Optional[str] = None' layout_structure.py)
# AFTER — insert below `    rejected: Optional[str] = None` (verified: layout_structure.py:35)
    dropped: int = 0
# occurrences: 1 each (verified: grep -c on both return lines, layout_structure.py:101 and :130)
# In both `return CandidateScore(source="bookmarks", ...)` lines add the keyword `dropped=profile.bookmarks_dropped`
```
**Why**: the field defaults to 0 so layout candidates, old JSON reports and `layout_eval`'s `model_validate` keep working.

### `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    bookmarks, rejection = _read_bookmarks([[1, "A", 1], [3, "B", 2], [1, "C", 9], [1, "  ", 2], [2, "D", 3]], 4)' test_layout.py)
# REPLACE that line (verified: test_layout.py:119) with:
    bookmarks, rejection, dropped = _read_bookmarks([[1, "A", 1], [3, "B", 2], [1, "C", 9], [1, "  ", 2], [2, "D", 3]], 4)
# and add `assert dropped == 0` after the existing asserts.
# Add `_keep_page_order` to the import list (test_layout.py:13-22) and append the new tests at the end of the file.
```

### FILL IN checklist
- [ ] `layout.py::_read_bookmarks` validation loop — today's filters, no inline level normalization
- [ ] `layout.py::_read_bookmarks` checks — three messages verbatim, non-monotonic returns `dropped=0`
- [ ] tests below — bodies

---

## Acceptance Criteria

- [ ] `_keep_page_order([1, 5, 2, 3, 4]) == [0, 2, 3, 4]`, `_keep_page_order([]) == []`, sorted input keeps every index.
- [ ] A 41-entry outline (page_count 200) with one backward entry → 40 usable, rejection `None`, dropped 1.
- [ ] 22 entries with 2 backward entries → rejection contains `non-monotonic`, 22 entries returned, dropped 0.
- [ ] `test_bookmarks_rejected_non_monotonic` and `test_bookmarks_rejected_per_page_enumeration` pass unchanged.
- [ ] `score_bookmarks` on a profile with `bookmarks_dropped=1` returns `CandidateScore.dropped == 1`.
- [ ] `ruff check` clean on the four files.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_eval.py -q`

---

## Test Specification

```python
# test_layout.py
def test_keep_page_order_longest_subsequence() -> None:
    assert _keep_page_order([1, 5, 2, 3, 4]) == [0, 2, 3, 4]
    assert _keep_page_order([]) == []
    assert _keep_page_order([1, 1, 2, 3]) == [0, 1, 2, 3]


def test_bookmarks_out_of_order_entry_dropped() -> None:
    toc = [[1 if n % 5 == 1 else 2, f"Section {n}", n] for n in range(1, 41)]
    toc.insert(30, [2, "Stray", 3])
    bookmarks, rejection, dropped = _read_bookmarks(toc, 200)
    assert rejection is None and dropped == 1 and len(bookmarks) == 40
    assert "Stray" not in [b.title for b in bookmarks]


def test_bookmarks_too_many_out_of_order_rejected() -> None:
    # FILL IN: 20 ordered entries plus 2 backward ones (22 total; floor(0.05 * 22) == 1 < 2)
    ...

# test_layout_structure.py
def test_score_bookmarks_reports_dropped():
    # FILL IN: _profile(...) with two bookmarks, then .model_copy(update={"bookmarks_dropped": 1}); score it
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-structure-fixes --feature-id FEAT-855`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/pageindex-layout-structure-fixes.json`
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5408 pageindex-layout-structure-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude (Opus 5.5) — /sdd-fix session agent:sdd-fix:cdd27bba
**Date**: 2026-11-09
**Notes**: Implemented as blueprinted: `BOOKMARK_MAX_DROPPED_SHARE`, `_keep_page_order` (patience sort), 3-tuple
`_read_bookmarks` (collect → drop → normalize → check; messages unchanged), `LayoutProfile.bookmarks_dropped` with an
INFO log, `CandidateScore.dropped` set in both `score_bookmarks` returns. Tests: `test_keep_page_order_longest_subsequence`,
`test_bookmarks_out_of_order_entry_dropped`, `test_bookmarks_too_many_out_of_order_rejected`,
`test_bookmarks_dropped_recorded_in_profile` (synthetic PDF), `test_score_bookmarks_reports_dropped`; the unpacking
test updated. Validation: test_layout.py + test_layout_structure.py + test_layout_eval.py → 31 passed; ruff clean.
The first draft of the profile test used 20 level-1 one-per-page entries, which the existing per-page-enumeration
rule (correctly) rejects; the test now mixes levels on 30 pages.

**Deviations from spec**: none
