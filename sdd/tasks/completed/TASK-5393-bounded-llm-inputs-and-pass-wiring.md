# TASK-5393: Bounded LLM inputs and pass wiring

**Feature**: FEAT-853 — PageIndex Optimizer Fixes
**Spec**: `sdd/specs/pageindex-optimizer-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5391, TASK-5392
**Assigned-to**: unassigned
**Discovered-from**: `issue:ab5235978ad7`, `issue:66f376157327`

---

## Context

Spec §2 D (plus the B and C wiring), Module 3.

`propose_headings`, `propose_key_items`, `summarize_leaf` and `compose_parent` frame every owned
segment of a node in one prompt. The Kant PDF is one 157k-token leaf, and its heading request
(~299k tokens) is rejected 3/3 (`issue:ab5235978ad7`). Any pass error lands in `report.errors`
and fails the apply (`toolkit.py:1587`), so every pass, summaries included, must be bounded.

This task also:
- tightens `heading_like` through TASK-5392's `is_heading_text` (`issue:66f376157327` item 3:
  the NIST `…; and` fragment);
- calls TASK-5391's `reconcile_key_items` inside `run_llm_passes` before summaries
  (`issue:66f376157327` item 1).

It closes both issues.

---

## Scope

- Add `LLM_INPUT_BUDGET_TOKENS = 20_000` and `_FRAME_OVERHEAD_TOKENS = 24` after `PROMPT_VERSION`.
  Do **not** change `PROMPT_VERSION`.
- Add `window_reads(reads, revision, *, budget=LLM_INPUT_BUDGET_TOKENS)` and a private
  `_clip_text(text, budget) -> str` (proportional clipping by `count_tokens`).
- `heading_like`: keep the structural checks; replace the text test with
  `is_heading_text(heading_title(text))`.
- `propose_headings`:
  - frame only `heading_like` candidates, one call per window;
  - no candidate → return `[]` without calling the adapter;
  - validate proposals exactly as today;
  - `report.llm_calls_made += 1` per call.
- `propose_key_items`:
  - one call per window of the node's reads;
  - ask each window for up to `quota = max(1, ceil(max_key_items / len(windows)))`;
  - accept at most `max_key_items` in total, validating against the **node's** owned segments;
  - count calls.
- `summarize_leaf` (new keyword `report`):
  - one window → one call, exactly as today;
  - more than one → one call per window, then one reduce call over the framed partial
    summaries (`frame_text`);
  - count calls.
- `compose_parent` (new keyword `report`): clip joined child summaries and key items to
  `budget // 2` each part combined; frame the first window of own reads within the remaining
  budget; count calls.
- `run_llm_passes`:
  - pass `report=plan.report` to the summary functions as well;
  - remove the three `plan.report.llm_calls_made += 1` lines;
  - call `reconcile_key_items(root, revision, plan.mutable, plan.report)` immediately before
    `if not with_summaries:` (outside `if live:`).
- `_estimate_llm_calls`: count windows (headings: candidate windows; key items: leaf windows;
  leaf summary: windows, plus 1 when more than 1; parent summary: 1).
- Tests in `test_optimizer_llm.py`, plus `test_optimize_apply_reconciles_key_items` in
  `test_optimizer_toolkit.py`.

**NOT in scope**:
- `optimizer.py` (TASK-5391/5392 own it); `toolkit.py`; `segments.py`; `framing.py`.
- New `OptimizerSettings` fields: changing `settings_hash` would invalidate every stamp.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` | MODIFY | budget, `window_reads`, bounded passes, `heading_like`, call counting, reconcile call, estimate |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py` | MODIFY | unit tests for AC-6 (heading_like), AC-7, AC-8, AC-9 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py` | MODIFY | `test_optimize_apply_reconciles_key_items` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# optimizer_llm.py already imports (verified: optimizer_llm.py:3-31):
import asyncio, hashlib, json, re
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments, frame_text  # line 15
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS                             # line 16
from parrot.knowledge.pageindex.optimizer import (KeyItem, OptimizePlan, OptimizerSettings, PassStamp,
    Revisions, is_stamped, owned_tokens, pass_cache_key, pass_input, refresh_after_counts, split_at)   # lines 17-29
from parrot.knowledge.pageindex.segments import DocumentRevision, Segment, SegmentAddress, SegmentRead  # line 30
# ADD in this task:
import math                                                                        # stdlib
from parrot.knowledge.pageindex import utils as _utils                             # count_tokens (utils.py:66)
from parrot.knowledge.pageindex.layout_structure import heading_title              # layout_structure.py:61 (extend line 16)
# extend the optimizer import (line 17) with: is_heading_text (TASK-5392), reconcile_key_items (TASK-5391)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py
PROMPT_VERSION = "v1"                                               # line 33 — keep
def reads_for(node: dict, revision: DocumentRevision) -> list[SegmentRead]:  # line 77
def heading_like(segment: Segment) -> bool:                          # line 108
def _owned_segments(node, revision) -> dict[int, Segment]:           # line 123
def _record_rejection(report) -> None:                               # line 128
async def propose_headings(node, revision, adapter, settings, *, report=None) -> list[int]:   # line 134
async def propose_key_items(node, revision, adapter, settings, *, report=None) -> list[KeyItem]:  # line 167
def _summary_text(node, revision) -> str:                            # line 211
def _trim_summary(text: str, max_words: int) -> str:                 # line 218
async def summarize_leaf(node, revision, adapter, settings) -> tuple[str, str]:  # line 224
async def compose_parent(node, revision, adapter, settings) -> tuple[str, str]:  # line 245
def _estimate_llm_calls(plan, nodes, revision, adapter, settings, *, with_summaries) -> int:  # line 331
async def run_llm_passes(plan, revisions, adapter, settings, *, with_summaries=True) -> None:  # line 360
    # line 414 / 453 / 490: plan.report.llm_calls_made += 1   (3 occurrences)
    # line 458: `            if not with_summaries:`

# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class SegmentRead(BaseModel): address; seq; kind; text; start: int; end: int; truncated: bool = False; flags  # line 97
class Segment(BaseModel): tokens: int  # line 43 (required)

# packages/ai-parrot/src/parrot/knowledge/pageindex/framing.py
def frame_segments(reads: Sequence[SegmentRead], *, source: str) -> str:   # line 33
def frame_text(text: str, *, source: str, flagged: bool = False) -> str:   # line 39

# after TASK-5391 / TASK-5392 (packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py)
def reconcile_key_items(root: dict, revision: DocumentRevision, mutable: set[int], report: OptimizeReport) -> None
def is_heading_text(title: str) -> bool
```

### Does NOT Exist
- ~~`OptimizerSettings.llm_input_tokens`~~ — do not add (settings digest).
- ~~`adapter.count_tokens`~~ / ~~`adapter.max_context`~~ — not part of the adapter surface; use
  `_utils.count_tokens`.
- ~~`framing.frame_windows`~~ — not real; call `frame_segments` per window.
- ~~`SegmentRead.tokens`~~ — reads carry no token count; use `revision.segments[read.seq].tokens`
  for complete reads.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#reads_for",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#heading_like",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#propose_headings",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#propose_key_items",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#summarize_leaf",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#compose_parent",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#_estimate_llm_calls",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#run_llm_passes"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Single-window equivalence.** When a node fits one window, each prompt string and the number
  of adapter calls must be identical to today's, apart from `propose_headings` framing only
  candidates. Guards: `test_prompts_are_framed`, `test_first_run_executes_before_stamping`
  (3 calls), `test_summaries_inline_llm_composed` (2 calls).
- **Read the budget at call time.** Tests monkeypatch the module constant, so use
  `budget: int | None = None` → `budget or LLM_INPUT_BUDGET_TOKENS` inside the function body, or
  read the global at call time. Do not freeze it as a default-argument value.
- `window_reads` cost: complete read (`start == 0 and end == len(segment.text)`) →
  `revision.segments[read.seq].tokens`; otherwise `_utils.count_tokens(read.text)`. Add
  `_FRAME_OVERHEAD_TOKENS` either way.
- `_clip_text`: while `count_tokens(text) > budget`, cut to
  `int(len(text) * budget / tokens * 0.9)` characters (at least 1). Clipped reads get
  `model_copy(update={"text": clipped, "end": read.start + len(clipped), "truncated": True})`.
- Partial summaries are document-derived. Frame the reduce input with
  `frame_text(..., source=f"{revision.doc_id}@{revision.revision} partial summaries")`, and keep
  `system_prompt=DATA_FRAMING_INSTRUCTION` on every call.
- Counting: increment `report.llm_calls_made` right after each `await adapter.ask_structured(...)`
  returns, only when `report is not None`. Cache hits never reach the function, so they are
  not counted (AC-9).

---

## Implementation Blueprint

### Steps (in order)
1. Imports and constants — *why*: everything below uses them.
2. `window_reads` + `_clip_text` below `reads_for` — *why*: one shared bounding primitive (AC-7).
3. `heading_like` → `is_heading_text` — *why*: rejects the NIST fragment (AC-6).
4. Bound the four pass functions and move the call counting into them — *why*: AC-7, AC-8, AC-9.
5. `run_llm_passes`: remove the three `+= 1` lines, pass `report=`, add the reconcile call —
   *why*: issue 66f item 1 and AC-9.
6. `_estimate_llm_calls` counts windows.
7. Tests, then the Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` (MODIFY — head)
```python
# occurrences: 1 (verified: grep -c 'PROMPT_VERSION = "v1"' optimizer_llm.py)
# AFTER — insert below `PROMPT_VERSION = "v1"` (verified: optimizer_llm.py:33)
LLM_INPUT_BUDGET_TOKENS = 20_000
_FRAME_OVERHEAD_TOKENS = 24
```

### `optimizer_llm.py` (MODIFY — windowing, after `reads_for`, before `def heading_like`)
```python
# occurrences: 1 (verified: grep -c 'def heading_like(segment: Segment) -> bool:' optimizer_llm.py)
# BEFORE — insert above `def heading_like(segment: Segment) -> bool:` (verified: optimizer_llm.py:108)
def _clip_text(text: str, budget: int) -> str:
    """Return ``text`` cut proportionally until its token count fits ``budget``."""
    # FILL IN: loop per Key Constraints — bounded by AC-7


def window_reads(
    reads: list[SegmentRead], revision: DocumentRevision, *, budget: Optional[int] = None
) -> list[list[SegmentRead]]:
    """<docstring from the spec skeleton, Module 3>."""
    budget = budget or LLM_INPUT_BUDGET_TOKENS
    # FILL IN: greedy in-order packing; an oversized single read becomes its own clipped window — AC-7
```

### `optimizer_llm.py` (MODIFY — `heading_like` and `propose_headings`)
```python
def heading_like(segment: Segment) -> bool:
    """Return whether a segment can be accepted as a printed sub-heading."""
    text = (segment.text or "").strip()
    if not text or "\n" in text or segment.kind in _NON_HEADING_KINDS:
        return False
    return is_heading_text(heading_title(text))

# in propose_headings (verified: optimizer_llm.py:134), replace the single prompt/call (lines 146-154) with:
    candidates = [read for read in reads_for(node, revision) if heading_like(revision.segments[read.seq])]
    if not candidates:
        return []
    seqs: list[int] = []
    for window in window_reads(candidates, revision):
        prompt = (
            "Identify the segments that are printed sub-headings. Return only their sequence numbers.\n\n"
            f"{frame_segments(window, source=f'{revision.doc_id}@{revision.revision}')}"
        )
        proposals = await adapter.ask_structured(prompt, HeadingProposals, system_prompt=DATA_FRAMING_INSTRUCTION)
        if report is not None:
            report.llm_calls_made += 1
        seqs.extend(proposals.seqs)
    # keep the existing validation loop, iterating `seqs` instead of `proposals.seqs`
```

### `optimizer_llm.py` (MODIFY — `propose_key_items`, `summarize_leaf`, `compose_parent`)
```python
# propose_key_items (verified: optimizer_llm.py:167): loop over window_reads(reads_for(node, revision), revision);
#   the prompt text keeps its wording with "up to {quota}" instead of "up to {settings.max_key_items}";
#   count calls; validate each proposal against _owned_segments(node, revision) as today; stop accepting at
#   settings.max_key_items. FILL IN: per-window quota accounting — bounded by AC-8

# summarize_leaf (verified: optimizer_llm.py:224) — add `*, report: Optional[Any] = None`
#   windows = window_reads(reads_for(node, revision), revision)
#   one window: today's prompt with frame_segments(windows[0], ...) and one call
#   several:    one call per window (same prompt), then
#               "Combine these partial summaries into one summary of at most {N} words.\n\n" +
#               frame_text("\n".join(partials), source=f"{revision.doc_id}@{revision.revision} partial summaries")
#   FILL IN: the map/reduce calls and counting — bounded by AC-8, AC-9

# compose_parent (verified: optimizer_llm.py:245) — add `*, report: Optional[Any] = None`
#   clip "\n".join(child_summaries) and the key-item lines with _clip_text to LLM_INPUT_BUDGET_TOKENS // 4 each;
#   own reads: window_reads(reads_for(node, revision), revision, budget=<remaining>)[:1] (empty list if none)
#   FILL IN: remaining-budget arithmetic (never below LLM_INPUT_BUDGET_TOKENS // 4) — bounded by AC-8
```

### `optimizer_llm.py` (MODIFY — `run_llm_passes` and `_estimate_llm_calls`)
```python
# occurrences: 3 (verified: grep -c 'plan.report.llm_calls_made += 1' optimizer_llm.py) — delete all three:
#   line 414 (headings), line 453 (key items), line 490 (summary, inside `if live and not (...)`: delete the whole if).
# summarize call (lines 480-484): pass report=plan.report to summarize_leaf and compose_parent.
# occurrences: 1 (verified: grep -c '            if not with_summaries:' optimizer_llm.py)
# BEFORE — insert above `            if not with_summaries:` (verified: optimizer_llm.py:458), at the `for root` loop
#   indentation (outside `if live:`):
            reconcile_key_items(root, revision, plan.mutable, plan.report)
# _estimate_llm_calls (verified: optimizer_llm.py:331): replace each `estimate += 1` with the window count
#   for that pass. FILL IN — bounded by AC-9
```
**Why**: the reconcile call sits after both structural passes and before summaries. Summary
input digests include `key_items` (`optimizer.py:541`), so moving items after a summary would
orphan its stamp. It runs in deterministic mode too, because the toolkit always calls
`run_llm_passes`.

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py` (MODIFY)
```python
# APPEND at the end of the file
def test_window_reads_respects_budget(...) ...                       # FILL IN
async def test_propose_headings_frames_only_candidates(...) ...      # FILL IN (+ no-candidate → await_count 0)
def test_heading_like_rejects_fragments() ...                        # FILL IN (NIST "…; and", "(a) …")
async def test_propose_key_items_windows_and_caps(...) ...           # FILL IN
async def test_summarize_leaf_map_reduce(...) ...                    # FILL IN
async def test_compose_parent_bounded(...) ...                       # FILL IN
async def test_llm_calls_made_counts_issued_calls(...) ...           # FILL IN
async def test_run_llm_passes_reconciles_before_summaries(...) ...   # FILL IN
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py` (MODIFY)
```python
# APPEND at the end of the file (after TASK-5391's test_optimize_apply_with_empty_leaf)
@pytest.mark.asyncio
async def test_optimize_apply_reconciles_key_items(tmp_path: Path) -> None:
    """A published leaf carrying key items that the apply splits still publishes cleanly."""
    # FILL IN: build a tree whose leaf has persisted key_items spread over its range and printed headings,
    #   so optimize(apply=True, llm_passes=False) splits it; assert report["errors"] == [] and every key item
    #   in the published tree lies in its node's owned ranges — bounded by AC-3
```

### FILL IN checklist
- [ ] `_clip_text`, `window_reads` — AC-7
- [ ] key-item quota, summary map/reduce, compose budget — AC-8
- [ ] call counting + estimate — AC-9
- [ ] 8 unit tests + 1 toolkit test

---

## Acceptance Criteria

- [ ] AC-6 (`heading_like` half): fragments ending in `;`/`:`/conjunctions and list-marker lines
  are rejected; `test_heading_like_and_proposals` still passes.
- [ ] AC-7: no prompt frames more than the budget of segment tokens; `propose_headings` frames
  only candidates and makes no call when there is none.
- [ ] AC-8: key items and leaf summaries window an oversized leaf (reduce call for summaries);
  `compose_parent` is bounded.
- [ ] AC-9: `llm_calls_made` equals the adapter `await_count`; a cache-served rerun adds 0;
  `llm_calls_estimated` counts windows.
- [ ] AC-3 at toolkit level: the apply that splits a leaf with persisted key items publishes
  with `errors == []`.
- [ ] Every existing test in the three files still passes; `ruff check` and `black --check` are
  clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_eval.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_bookstore.py -q`

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_propose_headings_frames_only_candidates(revision, monkeypatch):
    adapter = MagicMock(client=MagicMock())
    adapter.ask_structured = AsyncMock(return_value=HeadingProposals(seqs=[0]))
    report = OptimizeReport()
    assert await propose_headings({"owned": [[0, 3]]}, revision, adapter, OptimizerSettings(), report=report) == [0]
    prompt = adapter.ask_structured.await_args.args[0]
    assert "Topic heading" in prompt and "Alpha concept" not in prompt
    assert report.llm_calls_made == 1
    adapter.ask_structured.reset_mock()
    assert await propose_headings({"owned": [[1, 2]]}, revision, adapter, OptimizerSettings()) == []
    assert adapter.ask_structured.await_count == 0
```

---

## Agent Instructions

1. Work in the feature worktree; TASK-5391 and TASK-5392 must be `done`.
2. Verify the Codebase Contract, including the TASK-5391/5392 symbols now in `optimizer.py`.
3. Mark `in-progress`; implement; run the Validation Commands with
   `PYTHONPATH=<worktree>/packages/ai-parrot/src`.
4. Commit only the three files; close with
   `parrot sdd task close TASK-5393 pageindex-optimizer-fixes verified`; fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude (Opus 5.5) — /sdd-fix session, actor agent:sdd-fix:5b4f798e
**Date**: 2026-11-09
**Notes**: Implemented in `optimizer_llm.py` (commit 225ffbb27f): `LLM_INPUT_BUDGET_TOKENS`, `_FRAME_OVERHEAD_TOKENS`,
`_clip_text`, `_read_cost`, `window_reads`, `_record_call`; `heading_like` → `is_heading_text(heading_title(text))`;
the four pass functions bounded as specified (single-window prompts and call counts identical to before — the
existing call-count tests pass unchanged); `run_llm_passes` lost its three `llm_calls_made += 1` lines, passes
`report=` to the summary functions and calls `reconcile_key_items` before the summary pass (outside `if live:`);
`_estimate_llm_calls` counts windows. The budget is read at call time, so tests monkeypatch the module constant.
Tests: 8 in `test_optimizer_llm.py` and `test_optimize_apply_reconciles_key_items` in `test_optimizer_toolkit.py`
(a published key item anchored in the sibling section is re-homed and the apply publishes).
Validation: the full Validation Contract (test_optimizer, test_optimizer_llm, test_optimizer_toolkit,
test_optimizer_integration, test_optimizer_eval, test_optimizer_bookstore, test_optimizer_docs) — 65 passed;
ruff and black clean.

**Deviations from spec**: one change outside the blueprint inside `run_llm_passes`: the headings/key-items lambdas
bind `revision=revision` and `summarize` takes `revision` as a default parameter — this clears the pre-existing ruff
B023 findings (6 on `dev`) in a changed file without changing behaviour (each closure was already awaited in the
same loop iteration).
