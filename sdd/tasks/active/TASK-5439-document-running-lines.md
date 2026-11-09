# TASK-5439: Document-wide running lines in the pseudo-heading fallback

**Feature**: FEAT-859 — PageIndex Optimizer Fixes 3 — Document-Wide Running Lines for Pseudo-Headings
**Spec**: `sdd/specs/pageindex-optimizer-fixes-3.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:5a605ae51f61`

---

## Context

Spec §3 Module 1. `pseudo_heading_segments` (`optimizer.py:486`) drops a running header/footer only when its
`running_key` repeats more than `PSEUDO_HEADING_MAX_REPEATS` (2) times **inside the leaf being split**. After
`expand_at_headings` cuts NIST 800-53's `CONTROL SUMMARIES` at its table titles, the two- or three-page table pieces hold
their footer once or twice, so `APPENDIX C PAGE 434/437/441` become split points and piece titles
(`issue:5a605ae51f61`). The fix adds a document-wide running-line set based on page evidence (spec §1 evidence
table, §2 Overview A–C).

---

## Scope

- Add `RUNNING_LINE_MIN_DENSITY = 0.8` and `document_running_keys(revision) -> frozenset[str]`.
- `pseudo_heading_segments(node, revision, *, running_keys=None)`: skip candidates whose key is in the set (computed
  from the revision when `None`), inside the existing loop, before the first-candidate title rule.
- `expand_at_headings(..., *, depth, running_keys=None)`: compute the set once when `None`, pass it to every recursive
  call and to `pseudo_heading_segments`.
- Six unit tests (names fixed by spec §4).

**NOT in scope**: `layout.py`, `layout_structure.py`, `segments.py`, `OptimizerSettings`, `PSEUDO_HEADING_MAX_REPEATS`,
`OPTIMIZER_VERSION`, splitting tables, the wiki pages and the host evaluation (TASK-5440).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | constant, `document_running_keys`, two signatures |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` | MODIFY | six new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import Any, Literal, Optional  # verified: optimizer.py:9 (Optional already imported)
from parrot.knowledge.pageindex.layout import running_key  # verified: optimizer.py:14 (already imported)
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS, heading_title  # verified: optimizer.py:15
from parrot.knowledge.pageindex.segments import DocumentRevision, Segment  # verified: optimizer.py:16-24
# tests
from parrot.knowledge.pageindex.segments import segment_pages  # verified: segments.py:231 (imported inside _paged_tree, test_optimizer.py:501)
from parrot.knowledge.pageindex.optimizer import plan_deterministic, OptimizerSettings  # verified: test_optimizer.py:5-22
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py
PSEUDO_HEADING_MAX_REPEATS = 2  # :30
def pseudo_heading_segments(node: dict, revision: DocumentRevision) -> list[Segment]  # :486
    #   :502-507 paragraphs = owned paragraph segments ; :508-511 per-leaf counts by running_key(heading_title(...))
    #   :517 title = heading_title(text) ; :520 if counts.get(running_key(title), 0) > PSEUDO_HEADING_MAX_REPEATS:
    #   :523-527 first candidate dropped when it matches the node title
def expand_at_headings(node, revision, settings, report, *, depth) -> None  # :717
    #   :726 locked/max_depth return ; :731 recurse into children ; :746 pseudo fallback ; :752 recurse into pieces
def plan_deterministic(tree, revisions, settings, *, tree_name, node_id=None) -> OptimizePlan  # :876 ; calls :896
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class Segment(BaseModel): seq: int; kind: SegmentKind; page: Optional[int] = None; text: str  # :33-43
def segment_pages(pages: list[tuple[int, str]]) -> list[Segment]  # :231 — seq global, one segment per block
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py
def running_key(text: str) -> str  # :109 casefold, collapse whitespace, digit runs -> '#'
# tests: test_optimizer.py
_stub_tokens (autouse, :28: count_tokens = len(text) // 4) ; _PROSE (:400, ~712 tokens)
def _markdown_tree(text: str, title: str = "Libro") -> tuple[dict, dict]  # :403 (unpaged)
def _paged_tree(pages: list[tuple[int, str]], title: str = "Libro") -> tuple[dict, dict]  # :499 (one leaf, doc_id "libro")
def test_pseudo_headings_drop_numbered_footers() -> None  # :555 (last function in the file; file ends at :564)
```

### Does NOT Exist
- ~~a document-wide repeat count or a cache of running keys~~ — `counts` in `pseudo_heading_segments` is per leaf.
- ~~`DocumentRevision.layout` / `revision.running`~~ — a revision has no layout profile (`segments.py:59-68`).
- ~~`RUNNING_LINE_MIN_DENSITY` / `document_running_keys`~~ — created by this task.
- ~~other callers of `pseudo_heading_segments` / `expand_at_headings`~~ — only `optimizer.py` and `test_optimizer.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#pseudo_heading_segments",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#expand_at_headings",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#plan_deterministic"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep the per-leaf rule and the first-candidate title rule exactly as they are — the document rule is one extra
  `continue` in the same loop.
- No caching keyed on object identity or `(doc_id, revision)` strings — tests reuse `"libro"` / revision ids with
  different segments. The once-per-call-tree computation in `expand_at_headings` is the only reuse.
- Unpaged segments (`page is None`) never count, so markdown/ebook revisions behave exactly as today.

---

## Implementation Blueprint

### Steps (in order)
1. Add the constant below `PSEUDO_HEADING_MAX_REPEATS` — because the helper and the docs name it.
2. Add `document_running_keys` directly above `pseudo_heading_segments` — because that is its main consumer.
3. Extend `pseudo_heading_segments` — because every split path goes through it.
4. Extend `expand_at_headings` — so the set is computed once per document root, not once per leaf (the prototype
   recomputed it per call and added ≈0.6 s on 800-53).
5. Write the six tests; run the validation commands; `ruff check` the two files.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'PSEUDO_HEADING_MAX_REPEATS = 2' optimizer.py)
# AFTER — insert below `PSEUDO_HEADING_MAX_REPEATS = 2` (verified: optimizer.py:30)
RUNNING_LINE_MIN_DENSITY = 0.8
"""Share of its page range a repeated paragraph title must cover to count as a running header or footer."""

# occurrences: 1 (verified: grep -c 'def pseudo_heading_segments(node: dict, revision: DocumentRevision) -> list\[Segment\]:' optimizer.py)
# BEFORE — insert above `def pseudo_heading_segments(` (verified: optimizer.py:486)
def document_running_keys(revision: DocumentRevision) -> frozenset[str]:
    """Return the ``running_key`` of every paragraph title that runs through the revision as a header or footer.

    A key qualifies when its paged ``paragraph`` segments sit on more than ``PSEUDO_HEADING_MAX_REPEATS`` distinct
    pages, never twice on one page, and those pages cover at least ``RUNNING_LINE_MIN_DENSITY`` of the page range they
    span. Segments without a page are ignored, so an unpaged revision returns an empty set.

    Args:
        revision: The document revision whose paragraphs are scanned.

    Returns:
        The running keys of the revision's running headers and footers.
    """
    pages_by_key: dict[str, list[int]] = {}
    for segment in revision.segments:
        if segment.kind == "paragraph" and segment.page is not None:
            pages_by_key.setdefault(running_key(heading_title(segment.text)), []).append(int(segment.page))
    keys: set[str] = set()
    for key, pages in pages_by_key.items():
        distinct = set(pages)
        if len(distinct) <= PSEUDO_HEADING_MAX_REPEATS or len(distinct) != len(pages):
            continue
        if len(distinct) / (max(distinct) - min(distinct) + 1) >= RUNNING_LINE_MIN_DENSITY:
            keys.add(key)
    return frozenset(keys)

# REPLACE the signature line `def pseudo_heading_segments(node: dict, revision: DocumentRevision) -> list[Segment]:` (:486) WITH
def pseudo_heading_segments(
    node: dict, revision: DocumentRevision, *, running_keys: Optional[frozenset[str]] = None
) -> list[Segment]:
    # FILL IN: docstring — add one sentence: titles whose running_key is in ``running_keys`` (default
    #   ``document_running_keys(revision)``) are dropped as running headers/footers of the whole document; add the
    #   ``running_keys`` Args entry.
    # FILL IN: right after the docstring: `running = document_running_keys(revision) if running_keys is None else running_keys`

# occurrences: 1 (verified: grep -c '        if counts.get(running_key(title), 0) > PSEUDO_HEADING_MAX_REPEATS:' optimizer.py)
# REPLACE `        if counts.get(running_key(title), 0) > PSEUDO_HEADING_MAX_REPEATS:` (:520) WITH
        key = running_key(title)
        if counts.get(key, 0) > PSEUDO_HEADING_MAX_REPEATS or key in running:

# occurrences: 1 each (verified: grep -c on each line below)
# expand_at_headings signature (:717-719): add `running_keys: Optional[frozenset[str]] = None` after `depth: int`
# FILL IN: docstring — one sentence: computes ``document_running_keys`` once when ``running_keys`` is ``None`` and
#   passes it down the recursion.
# AFTER the `if is_locked(node) or depth >= settings.max_depth: return` block (:726-727):
    if running_keys is None:
        running_keys = document_running_keys(revision)
# :731  expand_at_headings(child, revision, settings, report, depth=depth + 1, running_keys=running_keys)
# :746  node, revision, [segment.seq for segment in pseudo_heading_segments(node, revision, running_keys=running_keys)], settings
#       (wrap to 120 columns)
# :752  expand_at_headings(piece, revision, settings, report, depth=depth + 1, running_keys=running_keys)
```
**Why**: footers cover every page of their range once (800-53: 1.00, constant page-number offset), while repeated
real headings are spread out (Kant 0.03, Analectas 0.30) and reference labels stack on one page (spec §1) — so density
plus once-per-page separates them; a plain document count would also drop Kant's section titles.

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` (MODIFY)
```python
# AFTER — append at the end of the file (after test_pseudo_headings_drop_numbered_footers, :555-564)
# --- FEAT-859: document-wide running lines --------------------------------------------------------------------


def _footer_pages(count: int = 6, extra: Optional[dict[int, str]] = None) -> list[tuple[int, str]]:
    """Pages 1..count, each prose plus an `APPENDIX C PAGE <427+n>` footer; `extra` prepends text to a page."""
    # FILL IN: build [(n, f"{extra.get(n, '')}{_PROSE}\n\nAPPENDIX C PAGE {427 + n}") ...]; import Optional from typing


def test_document_running_keys_finds_page_footers() -> None:
    # FILL IN: _paged_tree(_footer_pages()); assert running_key("APPENDIX C PAGE 428") in document_running_keys(rev)


def test_document_running_keys_ignores_spread_stacked_and_unpaged() -> None:
    # FILL IN: (a) 15 pages of prose, `PRIMERA SECCIÓN` paragraph on pages 1, 8, 15 → key absent (density 0.2);
    #   (b) `[SP 800-39]` twice on page 2 and once on pages 3, 4 → key absent (twice on one page);
    #   (c) _markdown_tree with the footer text repeated 4 times → document_running_keys(rev) == frozenset()


def test_pseudo_headings_drop_document_footer_in_short_leaf() -> None:
    # FILL IN: _paged_tree(_footer_pages(extra={5: "**Real Title**\n\n"})); leaf = {"title": "TABLE C-3",
    #   "owned": [[first seq on page 5, len(segments)]]}; titles of pseudo_heading_segments(leaf, rev) == ["Real Title"]
    #   (on dev the two footers in the leaf pass the per-leaf rule — this test fails there; AC-2)


def test_pseudo_headings_explicit_running_keys_override() -> None:
    # FILL IN: same leaf, running_keys=frozenset() → both footers are offered again (per-leaf rule only)


def test_expand_does_not_split_short_leaf_at_document_footer() -> None:
    # FILL IN: one imported root node (doc_id/revision of the paged revision, span over all segments) with two leaves:
    #   "Tables" (pages 1-4) and "TABLE C-3" (pages 5-6, no real title); plan_deterministic with
    #   OptimizerSettings(target_leaf_tokens=100, min_leaf_tokens=20); assert no node title matches r"PAGE \d+$"
    #   (fails on dev — AC-2)


def test_expand_computes_running_keys_once(monkeypatch) -> None:
    # FILL IN: wrap optimizer.document_running_keys with a counter via monkeypatch.setattr on the module; run the
    #   previous test's plan; assert the counter == 1 (one document root) — AC-4
```

### FILL IN checklist
- [ ] the two docstring sentences and the `running` local in `pseudo_heading_segments`
- [ ] the six test bodies and the `_footer_pages` helper (import `document_running_keys`, `pseudo_heading_segments`,
      `running_key`, `heading_title` inside the tests as the FEAT-857 tests do)

---

## Acceptance Criteria

- [ ] AC-1: `document_running_keys` returns exactly the keys whose paged paragraphs sit on more than
      `PSEUDO_HEADING_MAX_REPEATS` distinct pages, at most once per page, covering ≥ `RUNNING_LINE_MIN_DENSITY` of their
      page range; an unpaged revision returns an empty set.
- [ ] AC-2: `pseudo_heading_segments` never returns a candidate whose key is a document running line, in any leaf;
      `test_pseudo_headings_drop_document_footer_in_short_leaf` and `test_expand_does_not_split_short_leaf_at_document_footer`
      fail on `dev` and pass here.
- [ ] AC-3: the per-leaf repeat rule and the first-candidate title rule are unchanged (existing tests pass).
- [ ] AC-4: `document_running_keys` runs once per document root during `plan_deterministic`.
- [ ] `ruff check` is clean on both files.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_integration.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py -q`

---

## Test Specification

Names and intent fixed by spec §4 (Unit Tests table); bodies per the blueprint stubs.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-optimizer-fixes-3 --feature-id FEAT-859`)
2. **Read the spec** at the path listed above
3. **Verify the Codebase Contract** before writing anything
4. **Update status** in `sdd/tasks/index/pageindex-optimizer-fixes-3.json` → `"in-progress"`; commit only that file
5. **Implement**, completing every `FILL IN`
6. **Verify** acceptance criteria with `PYTHONPATH=packages/ai-parrot/src`; prove AC-2 by running the two new
   regression tests against the base commit
7. **Commit** only the files this task lists
8. **Close** with `parrot sdd task close TASK-5439 pageindex-optimizer-fixes-3 verified`
9. Fill in the Completion Note, commit the SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
