# TASK-5338: Anchored attach (M4)

**Feature**: FEAT-845 — PageIndex Layout Structure Builder
**Spec**: `sdd/specs/pageindex-layout-structure.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 4. Bookmark, layout and hybrid structure nodes (TASK-5336/5337) carry a transient
`anchor: {"page": int, "ordinal": int}` naming the exact heading segment they start at. Today
`attach_pdf_document` (`segments.py:358`) starts a node's span at "the heading segment on its start page
whose title matches, else the first segment of the page" — ambiguous when similar titles share a page
(`_titles_match` accepts containment): a node titled `Scope` grabs a preceding `Scope Notes` heading. This
task makes `attach_pdf_document` resolve `anchor` to that segment's `seq` **before** the title match, and
remove the `anchor` key from every node so anchors never reach a stored tree (AC-10).

Spec sections: §2 "Anchors", §3 Module 4, §4 `test_segments.py::test_attach_prefers_anchor`, AC-2
(attach half: nodes start at their heading segment), AC-10.

---

## Scope

- In `attach_pdf_document` build `anchor_seq: dict[tuple[int, int], int]` mapping `(seg.page, seg.ordinal)`
  to the segment's index (pages not `None`).
- In the nested `start_of(node)`, look the node's `anchor` up first and return that `seq` when it exists;
  otherwise keep today's logic unchanged (title match on the start page, else the page's first segment).
- After `attach_level(structure, 0, total, True)`, walk the whole structure and pop `"anchor"` from every
  node — including nodes under a cleared subtree, which `start_of` never sees.
- Add the spec's docstring sentence.
- Append `test_attach_prefers_anchor` (and its fallback/strip checks) to `test_segments.py`.

**NOT in scope**: producing anchors (TASK-5336/5337); stripping anchors on the toolkit's no-revision path
(`PageIndexToolkit._strip_anchors`, TASK-5341); `attach_section_document` (markdown/ebook — no anchors);
any change to span-end, ownership or partition logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py` | MODIFY | Anchor lookup before the title match; strip `anchor` from every node |
| `packages/ai-parrot/tests/knowledge/pageindex/test_segments.py` | MODIFY | Append `test_attach_prefers_anchor` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# test_segments.py already imports (verified: test_segments.py:3-6, :85-88):
from parrot.knowledge.pageindex.segments import (
    SegmentAddress, derive_doc_id, format_cursor, parse_cursor, parse_page_spec,
    revision_id, segment_pages, segment_text, split_blocks,
)
from parrot.knowledge.pageindex.segments import (  # noqa: E402
    DocumentRevision, SourceInfo, attach_pdf_document, attach_section_document, render_body, validate_ownership,
)
from parrot.knowledge.pageindex.utils import structure_to_list  # noqa: E402
# segments.py needs no new import (Optional/Sequence already imported at :7)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class Segment(BaseModel):            # :33 — seq: int; kind: SegmentKind; page: Optional[int] (:38); ordinal: int (:39); text: str
def segment_pages(pages: list[tuple[int, str]]) -> list[Segment]   # :231 — seq global, ordinal restarts per page
def _titles_match(a: str, b: str) -> bool                          # :312
def _heading_text(text: str) -> str                                # :340
def attach_pdf_document(structure: list[dict], revision: DocumentRevision) -> None:   # :358
    """…  A node whose pages hold no segment
    owns nothing.                                                  # :365 (docstring last sentence; occurrences 1)
    """
    from bisect import bisect_left, bisect_right                   # :367
    segments = revision.segments                                   # :369
    total = len(segments)
    pages = [s.page if s.page is not None else 0 for s in segments]  # :371 (anchor; occurrences 1)
    def start_of(node: dict) -> Optional[int]:                     # :373 (anchor; occurrences 1)
        page = node.get("start_index")                             # :374
        # :375-385 bisect the page range; first heading whose title matches, else `first`
    def attach_level(nodes, lo, hi, top) -> None:                  # :387 — calls start_of(node) once per node;
        # nodes whose start is None, and children of a node whose span collapses, go through
        # _clear_subtree (:350) and are NEVER passed to start_of
    attach_level(structure, 0, total, True)                        # :427 (anchor; occurrences 1, last line of the function)

# packages/ai-parrot/tests/knowledge/pageindex/test_segments.py
def _rev(pages):                                                   # :91-94 — DocumentRevision over segment_pages(pages)
# autouse fixture _stub_tiktoken (:9-11) stubs utils.count_tokens — new tests inherit it
# Verified this session on the current code: _rev([(1, "# Scope Notes\n\nNotes text.\n\n# Scope\n\nScope text."), (2, "More.")])
#   segments (seq, kind, page, ordinal): (0 heading 1 0 "# Scope Notes"), (1 paragraph 1 1), (2 heading 1 2 "# Scope"),
#   (3 paragraph 1 3), (4 paragraph 2 0); attaching [Scope Notes p1-1, Scope p1-2] WITHOUT anchors gives
#   spans [None, [0, 5]] — "Scope" title-matches the "Scope Notes" heading (containment).
```

### Does NOT Exist
- ~~`anchor` on nodes~~ — no code produces or reads it today; this task is the only reader
- ~~`Segment.anchor` / `Segment.address` as a lookup key~~ — resolve by `(page, ordinal)` from `Segment.page` / `Segment.ordinal`
- ~~a module-level `_strip_anchors` in `segments.py`~~ — strip inline at the end of `attach_pdf_document`; the toolkit's `_strip_anchors` is TASK-5341's
- ~~anchors in `attach_section_document`~~ — markdown/ebook nodes carry no anchors; leave it unchanged

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_segments.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#attach_pdf_document",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#Segment",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#segment_pages"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
The function already precomputes `pages` for bisecting; precompute `anchor_seq` next to it the same way.

### Key Constraints
- Read the anchor with `node.get("anchor")` inside `start_of` and strip all anchors in one final walk —
  *because* the final walk is what guarantees AC-10 for nodes `start_of` never visits (cleared subtrees,
  nodes whose start page has no segment), and reading without popping keeps `start_of` side-effect free.
- An anchor that does not resolve (unknown `(page, ordinal)`, malformed dict) falls back to today's title
  match — never raise.
- The returned seq still goes through `attach_level`'s clamping (`min(max(s, previous, lo), hi)`, :393) —
  do not bypass it.
- Use the list index of `revision.segments` as the seq (the existing code bisects list indexes; in a
  revision they equal `Segment.seq`).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py:351-427`
- `packages/ai-parrot/tests/knowledge/pageindex/test_segments.py:91-118` — `_rev` and the attach tests to imitate

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the docstring sentence — *why*: spec M4's skeleton states the contract.
2. Add `anchor_seq` below the `pages = …` line — *why*: O(1) resolution, computed once.
3. Add the anchor lookup at the top of `start_of` — *why*: the anchor must win before any title match (spec §2 "Anchors").
4. Add the final strip walk after `attach_level(structure, 0, total, True)` — *why*: AC-10 for every node, visited or not.
5. Append the test and run the three Validation Commands — *why*: existing attach behaviour must not change for anchor-less trees (FEAT-840 tests).

### `packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    owns nothing.' packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py)
# REPLACE the docstring line `    owns nothing.` (verified: segments.py:365) WITH:
    owns nothing. A node carrying ``anchor = {"page": p, "ordinal": o}`` starts at the segment with that page and
    ordinal when one exists (before the title match); ``anchor`` is removed from every node visited, attached or not.

# occurrences: 1 (verified: grep -c '    pages = \[s.page if s.page is not None else 0 for s in segments\]' packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py)
# AFTER — insert below `    pages = [s.page if s.page is not None else 0 for s in segments]` (verified: segments.py:371)
    anchor_seq: dict[tuple[int, int], int] = {
        (seg.page, seg.ordinal): idx for idx, seg in enumerate(segments) if seg.page is not None
    }

# occurrences: 1 (verified: grep -c '    def start_of(node: dict) -> Optional\[int\]:' packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py)
# AFTER — insert below `    def start_of(node: dict) -> Optional[int]:` (verified: segments.py:373), before `page = node.get("start_index")`
        anchor = node.get("anchor")
        if isinstance(anchor, dict):
            # FILL IN: seq = anchor_seq.get((anchor.get("page"), anchor.get("ordinal"))); return it when not None,
            #   otherwise fall through to the title match — bounded by spec §2 "Anchors" (never raise)
            raise NotImplementedError

# occurrences: 1 (verified: grep -c '    attach_level(structure, 0, total, True)' packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py)
# AFTER — insert below `    attach_level(structure, 0, total, True)` (verified: segments.py:427)
    pending = list(structure)
    while pending:
        node = pending.pop()
        node.pop("anchor", None)
        pending.extend(node.get("nodes") or [])
```
**Why**: the lookup sits before the existing page bisect so an anchor always wins; the strip walk runs after
attachment so `attach_level` still sees the anchors, and it covers every node of the tree (AC-10).

### `packages/ai-parrot/tests/knowledge/pageindex/test_segments.py` (MODIFY)
```python
# APPEND at the end of the file (after test_validate_ownership_reports_gap_and_overlap).


def test_attach_prefers_anchor():
    """Anchored nodes start at their own heading despite similar titles; no node keeps 'anchor' (AC-2, AC-10)."""
    pages = [(1, "# Scope Notes\n\nNotes text.\n\n# Scope\n\nScope text."), (2, "More.")]
    plain = [{"title": "Scope Notes", "start_index": 1, "end_index": 1},
             {"title": "Scope", "start_index": 1, "end_index": 2}]
    attach_pdf_document(plain, _rev(pages))
    assert [n["span"] for n in plain] == [None, [0, 5]]      # the ambiguity anchors remove (verified on current code)

    anchored = [{"title": "Scope Notes", "start_index": 1, "end_index": 1, "anchor": {"page": 1, "ordinal": 0}},
                {"title": "Scope", "start_index": 1, "end_index": 2, "anchor": {"page": 1, "ordinal": 2}}]
    rev = _rev(pages)
    attach_pdf_document(anchored, rev)
    # FILL IN: assert spans == [[0, 2], [2, 5]]; validate_ownership(structure_to_list(anchored), rev) == [];
    #   "anchor" not in any node of structure_to_list(anchored)


def test_attach_unresolved_anchor_and_cleared_subtree():
    """An unknown (page, ordinal) falls back to the title match; anchors under cleared subtrees are removed."""
    # FILL IN: tree = [{"title": "Scope Notes", start 1, end 1, "anchor": {"page": 1, "ordinal": 99}},
    #   {"title": "Ghost", start 5, end 5, "anchor": {"page": 5, "ordinal": 0},
    #    "nodes": [{"title": "Ghost child", start 5, end 5, "anchor": {"page": 5, "ordinal": 1}}]}]
    #   over the same pages; assert tree[0]["span"][0] == 0 (title match), tree[1]["span"] is None,
    #   and no node anywhere (structure_to_list) carries "anchor"
```
**Why**: the first assertion pins today's ambiguous behaviour (verified) so the anchored result is clearly the
anchor's doing; the second test covers the two paths `start_of` never or only partly handles.

### FILL IN checklist
- [ ] `segments.py::attach_pdf_document.start_of` — resolve the anchor, else fall through; bounded by spec §2 "Anchors"
- [ ] `test_segments.py::test_attach_prefers_anchor` — spans, ownership, no anchor; bounded by AC-2, AC-10
- [ ] `test_segments.py::test_attach_unresolved_anchor_and_cleared_subtree` — fallback + strip; bounded by AC-10

---

## Acceptance Criteria

- [ ] A node with a resolvable `anchor` starts at that segment, before any title match (AC-2, attach half)
- [ ] An unresolvable anchor falls back to the existing title match without raising
- [ ] AC-10: after `attach_pdf_document`, no node of the structure — attached, cleared or never visited — has an `anchor` key
- [ ] Anchor-less trees attach exactly as before (`test_segment_import.py`, `test_segment_integration.py` unchanged and passing)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segments.py -q`, `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py -q`, `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_integration.py -q`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py packages/ai-parrot/tests/knowledge/pageindex/test_segments.py` is clean (AC-18)

---

## Validation Commands

> Commands a registered test runner recognises — `pytest`, `vitest`, `cargo test`, `parrot e2e` or an
> `[extensions]` entry in `.parrot/test_runners.toml`. pytest: file-level only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segments.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_integration.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.
> Add more tests as needed.

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_segments.py — appended, see the blueprint block.
#   test_attach_prefers_anchor                        -> plain [None, [0, 5]]; anchored [[0, 2], [2, 5]]; no "anchor" left
#   test_attach_unresolved_anchor_and_cleared_subtree -> fallback to title match; Ghost span None; no "anchor" left
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
9. **Close the task** with `parrot sdd task close TASK-5338 pageindex-layout-structure verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
