# TASK-5392: Heading-text rule and pseudo-heading fallback

**Feature**: FEAT-853 — PageIndex Optimizer Fixes
**Spec**: `sdd/specs/pageindex-optimizer-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5391
**Assigned-to**: unassigned
**Discovered-from**: `issue:0a693a57b138`

---

## Context

Spec §2 C and E, Module 2.

Ebook and markdown imports carry chapter titles as standalone bold or upper-case paragraphs
(`**P****ROLOGO**`, `SEGUNDA PARTE`), not `#` headings. `expand_at_headings`
(`optimizer.py:487`) splits only at `kind == "heading"` segments, so *Don Quijote* stays one
282k-token leaf (`issue:0a693a57b138`).

The fix is an optimizer-side fallback. The segmenter is not changed (spec Decisions
`pseudo-headings-in-optimizer`), because `split_blocks` also segments PDF pages.

This task also creates the shared `is_heading_text` predicate. TASK-5393 uses it to tighten
`heading_like` (`issue:66f376157327` item 3).

---

## Scope

- Add `import re` and `PSEUDO_HEADING_MAX_REPEATS = 2` to `optimizer.py`.
- Add `is_heading_text(title)` with the exact rules of the spec skeleton.
- Add `pseudo_heading_segments(node, revision)` per the skeleton.
- Add `_coalesce_split_points(node, revision, seqs, settings)` per the skeleton.
- In `expand_at_headings`, when the filtered real `headings` list is empty, fall back:
  `seqs = _coalesce_split_points(node, revision, [s.seq for s in pseudo_heading_segments(node, revision)], settings)`,
  then `split_at(..., source="layout")`, then recurse into the pieces exactly as the real-heading
  path does.
- Unit tests in `test_optimizer.py`.

**NOT in scope**:
- `heading_like` / `optimizer_llm.py` (TASK-5393).
- `segments.py` / `split_blocks`: no change to segment kinds (spec AC-11).
- The real-heading path: its filter, shallowest-level choice and cost model stay byte-for-byte
  the same.
- `split_at` signature.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | `is_heading_text`, `pseudo_heading_segments`, `_coalesce_split_points`, fallback in `expand_at_headings` |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` | MODIFY | unit tests for AC-6 (predicate) and AC-10 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already in optimizer.py (verified: optimizer.py:5-23)
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS, heading_title  # line 13
from parrot.knowledge.pageindex.segments import DocumentRevision, Segment, _heading_text, _titles_match, normalize_title  # lines 14-22
import re  # NEW (stdlib) — add next to `import json` (optimizer.py:6)

# tests
from parrot.knowledge.pageindex.optimizer import OptimizeReport, OptimizerSettings, expand_at_headings, plan_deterministic
from parrot.knowledge.pageindex.segments import DocumentRevision, revision_id, segment_text  # test_optimizer.py:24
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py
MAX_HEADING_WORDS = 20                 # line 23
def heading_title(text: str) -> str:   # line 61 — strips ATX markers and `**`/`__`/`~~`/backtick, collapses spaces
                                       #   heading_title("**P****ROLOGO**") == "PROLOGO"

# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class Segment(BaseModel): seq; kind: SegmentKind; level: Optional[int]; text: str; tokens: int  # line 33
SegmentKind = Literal["heading", "paragraph", "list", "table", "code", "caption", "other"]       # line 13
def segment_text(text: str, section: list[str], *, seq_start: int = 0) -> list[Segment]:        # line 240

# packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py
def owned_tokens(node: dict, revision: DocumentRevision) -> int:   # line 155
def heading_segments(node: dict, revision: DocumentRevision) -> list[Segment]:  # line 389 — title-match exclusion pattern to mirror
def should_expand(node_tokens, piece_tokens, cost, settings) -> bool:  # line 416 — all pieces must be >= min_leaf_tokens
def _owned_in_span(owned, start, end) -> list[list[int]]:          # line 423
def split_at(node, revision, seqs, *, source, settings, report) -> list[dict]:  # line 432
def expand_at_headings(node, revision, settings, report, *, depth) -> None:     # line 487
    # lines 501-508:
    #     headings = [ segment for segment in heading_segments(node, revision)
    #                  if segment.level is not None and len(heading_title(segment.text).split()) <= MAX_HEADING_WORDS ]
    #     if not headings:
    #         return
```

### Does NOT Exist
- ~~`SegmentKind` `"pseudo_heading"`~~ — kinds do not change; candidates stay `paragraph`.
- ~~`ExpandAction.source == "pseudo"`~~ — the Literal is `["layout", "llm"]`; use `"layout"`.
- ~~`parrot.knowledge.pageindex.optimizer.is_heading_text`~~ / ~~`pseudo_heading_segments`~~ — created here.
- ~~`layout_structure.is_heading_text`~~ — not there; the predicate lives in `optimizer.py`.

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
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#expand_at_headings",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#heading_segments",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py#split_at"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `is_heading_text` takes an already-cleaned title (the caller applies `heading_title`). Strip
  it, check emptiness, then apply the rules:
  - word count via `.split()`;
  - trailing `.`, `;`, `:` or `,`;
  - casefolded last word (trailing punctuation removed) in
    `{"and", "or", "nor", "y", "e", "o", "u", "ni"}`;
  - list-marker prefix regex `^(?:\(\w{1,4}\)|[a-z]\)|[-•*–])\s`.
  
  `1. Introduction` must stay valid: do not reject numeric prefixes.
- Upper-case test: collect `[c for c in title if c.isalpha() and c.lower() != c.upper()]` (cased
  letters). It needs `len >= 2` and every one `c.isupper()`.
- Emphasis test on the raw stripped text: starts with `**` and ends with `**`, or starts with
  `__` and ends with `__`, and is longer than 4 characters.
- Repeat filter: count `heading_title(text)` occurrences over **all** owned paragraph segments of
  the node (not only candidates). Drop a title seen more than `PSEUDO_HEADING_MAX_REPEATS` times.
- `_coalesce_split_points` piece tokens: `owned_tokens({"owned": _owned_in_span(owned, a, b)}, revision)`.
  The last piece ends at `max(end for _, end in owned)`, the same `final_end` that `split_at`
  uses.
- The fallback only runs when the real-heading list is empty. A leaf owning any usable heading
  segment behaves exactly as today.

---

## Implementation Blueprint

### Steps (in order)
1. Add `import re` and the constants — *why*: the list-marker rule is a regex.
2. Add `is_heading_text` above `heading_segments` — *why*: shared by the fallback here and by
   `heading_like` in TASK-5393 (AC-6).
3. Add `pseudo_heading_segments` and `_coalesce_split_points` below `heading_segments` — *why*:
   candidate selection and tiny-piece coalescing (AC-10).
4. Replace the early return in `expand_at_headings` with the fallback — *why*: the only call
   site.
5. Write the tests and run the Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` (MODIFY — module head)
```python
# occurrences: 1 (verified: grep -c '^import json$' optimizer.py)
# AFTER — insert below `import json` (verified: optimizer.py:6)
import re
# AFTER — insert below `Revisions = dict[tuple[str, str], DocumentRevision]` (verified: optimizer.py:26)
PSEUDO_HEADING_MAX_REPEATS = 2
_TRAILING_CONJUNCTIONS = frozenset({"and", "or", "nor", "y", "e", "o", "u", "ni"})
_LIST_MARKER_RE = re.compile(r"^(?:\(\w{1,4}\)|[a-z]\)|[-•*–])\s")
```

### `optimizer.py` (MODIFY — predicate and fallback helpers)
```python
# occurrences: 1 (verified: grep -c 'def heading_segments(node: dict, revision: DocumentRevision) -> list\[Segment\]:' optimizer.py)
# BEFORE — insert above `def heading_segments(...)` (verified: optimizer.py:389)
def is_heading_text(title: str) -> bool:
    """<docstring from the spec skeleton, Module 2>."""
    # FILL IN: rules from Key Constraints — bounded by AC-6

# AFTER `heading_segments` returns (insert before `def routing_cost(`, verified: optimizer.py:404)
def pseudo_heading_segments(node: dict, revision: DocumentRevision) -> list[Segment]:
    """<docstring from the spec skeleton, Module 2>."""
    # FILL IN: walk owned segments; keep single-line paragraph candidates (emphasis-wrapped or upper-case)
    #   whose heading_title passes is_heading_text; drop titles repeated > PSEUDO_HEADING_MAX_REPEATS times;
    #   drop a first candidate whose title matches the node title (normalize_title + _titles_match,
    #   as in heading_segments) — bounded by AC-10


def _coalesce_split_points(
    node: dict, revision: DocumentRevision, seqs: list[int], settings: OptimizerSettings
) -> list[int]:
    """<docstring from the spec skeleton, Module 2>."""
    # FILL IN: forward merge then trailing backward merge as documented — bounded by AC-10
```

### `optimizer.py` (MODIFY — `expand_at_headings` fallback)
```python
# occurrences: 1 (verified: grep -c '    if not headings:' optimizer.py)
# REPLACE (verified: optimizer.py:506-516):
#     if not headings:
#         return
#     shallowest = min(...)
#     pieces = split_at(node, revision, [...], source="layout", settings=settings, report=report)
# WITH:
    if headings:
        shallowest = min(segment.level for segment in headings if segment.level is not None)
        seqs = [segment.seq for segment in headings if segment.level == shallowest]
    else:
        seqs = _coalesce_split_points(
            node, revision, [segment.seq for segment in pseudo_heading_segments(node, revision)], settings
        )
        if not seqs:
            return
    pieces = split_at(node, revision, seqs, source="layout", settings=settings, report=report)
```
**Why**: the real-heading branch computes exactly what it computes today. The fallback reuses
`split_at`, so the cost model, piece titles (`heading_title` strips the emphasis) and TASK-5391's
key-item move all apply unchanged. Keep the existing `for piece in pieces: expand_at_headings(...)`
loop after it.

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` (MODIFY)
```python
# APPEND at the end of the file (after TASK-5391's tests)
def test_is_heading_text_rules() -> None: ...                                      # FILL IN
def test_pseudo_headings_expand_bold_and_caps_lines() -> None: ...                 # FILL IN
def test_pseudo_headings_ignore_running_lines_and_real_headings() -> None: ...     # FILL IN
def test_coalesce_split_points_merges_tiny_pieces() -> None: ...                   # FILL IN
```

### FILL IN checklist
- [ ] `is_heading_text` — AC-6 cases: rejects `"…; and"`, `"Scope:"`, `"(a) Policy"`,
  `"- item"`, `"Ends with y"`; accepts `"1. Introduction"`, `"Chapter 3"`, `"SEGUNDA PARTE"`,
  `"Topic heading"`
- [ ] `pseudo_heading_segments` — candidate, repeat and title rules; AC-10
- [ ] `_coalesce_split_points` — forward/backward merge; AC-10
- [ ] four tests

---

## Acceptance Criteria

- [ ] AC-6 (predicate half): `is_heading_text` accepts and rejects the listed cases.
- [ ] AC-10: a markdown revision with no `#` headings and bold/caps title lines is expanded by
  `plan_deterministic` (no LLM) with piece titles `PROLOGO`, `SEGUNDA PARTE`, `Capítulo I`.
  A caps line repeated 3× is not a split point, and no piece is under `min_leaf_tokens`.
- [ ] AC-11: a leaf owning `#` headings expands exactly as before; `segments.py` is untouched.
- [ ] All TASK-5391 tests still pass; `ruff check` and `black --check` are clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_integration.py -q`

---

## Test Specification

```python
def test_pseudo_headings_expand_bold_and_caps_lines() -> None:
    prose = "Una frase larga de prosa que ocupa espacio suficiente para el presupuesto. " * 30
    text = f"**P****ROLOGO**\n\n{prose}\n\nSEGUNDA PARTE\n\n{prose}\n\n**Capítulo I**\n\n{prose}"
    segments = segment_text(text, ["Libro"])
    revision = DocumentRevision(doc_id="libro", revision=revision_id(segments),
                                source={"name": "libro.md", "kind": "markdown"},
                                created_at="2026-01-01T00:00:00Z", segments=segments)
    tree = {"nodes": [{"doc_id": "libro", "revision": revision.revision, "title": "Libro",
                       "span": [0, len(segments)], "owned": [[0, len(segments)]], "nodes": []}]}
    settings = OptimizerSettings(target_leaf_tokens=100, min_leaf_tokens=20)
    plan = plan_deterministic(tree, {("libro", revision.revision): revision}, settings, tree_name="t")
    titles = [n["title"] for n in plan.candidate["nodes"][0]["nodes"]]
    assert titles == ["PROLOGO", "SEGUNDA PARTE", "Capítulo I"]
```
(The module's autouse `_stub_tokens` fixture makes tokens `len(text) // 4`.)

---

## Agent Instructions

1. Work in the feature worktree (`feat-FEAT-853-pageindex-optimizer-fixes`); TASK-5391 must be `done`.
2. Verify the Codebase Contract (`grep -c` every anchor; TASK-5391 shifted line numbers in
   `optimizer.py`, so re-locate anchors by text, not by number).
3. Mark `in-progress` in the per-spec index; implement; run the Validation Commands with
   `PYTHONPATH=<worktree>/packages/ai-parrot/src`.
4. Commit only the two files; close with
   `parrot sdd task close TASK-5392 pageindex-optimizer-fixes verified`; fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude (Opus 5.5) — /sdd-fix session, actor agent:sdd-fix:5b4f798e
**Date**: 2026-11-09
**Notes**: Implemented in `optimizer.py` (commit bb07896225): `is_heading_text`, `pseudo_heading_segments` (with
private `_is_emphasis_wrapped` / `_is_upper_case` helpers), `_coalesce_split_points`, and the fallback branch in
`expand_at_headings`. The real-heading branch computes exactly what it computed before. Four tests in
`test_optimizer.py`. `**P****ROLOGO**` becomes the piece title `PROLOGO` through `heading_title`; a caps line repeated
three times is ignored; a stray short `**Tres**` piece and a trailing `**FIN**` piece are coalesced away.
Validation: test_optimizer + test_optimizer_integration — 27 passed; test_optimizer_eval, test_optimizer_bookstore,
test_optimizer_toolkit, test_optimizer_llm, test_optimizer_docs — 29 passed (the PDF fixtures are unaffected);
ruff and black clean.

**Deviations from spec**: the trailing-conjunction rule rejects the last word only when it is **lower case**
(spec: "casefolded"). With a casefolded match, appendix labels such as `Appendix E` / `Anexo O` (Spanish `e`, `o`)
would be rejected; sentence fragments end in a lower-case conjunction (`…; and`, `Ends with y`), so the
lower-case rule keeps both behaviours. Covered by `test_is_heading_text_rules`.
