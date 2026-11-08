# TASK-5320: PageIndex read ledger (`ReadLedger`, `LedgerEntry`, `BudgetExhausted`)

**Feature**: FEAT-843 — PageIndex Agentic Retrieval and Citations
**Spec**: `sdd/specs/pageindex-agentic-retrieval.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Ledger (M1)", "Exact character budget (M1/M3)" and §3 Module 1. The ledger is the
request-local record of which half-open character ranges of which `(doc_id, revision, seq)`
the read tools actually returned. Citations (TASK-5322) are validated against it; the
agentic retriever (TASK-5324) charges it before every segment read. Cursors are NOT a ledger.

---

## Scope

- Create `knowledge/pageindex/read_ledger.py` with `Range`, `BudgetExhausted`, `LedgerEntry`, `ReadLedger`.
- `record(result)` merges each `SegmentRead`'s `[start, end)` into its `(doc_id, revision, seq)` entry;
  touching (`a.end == b.start`) or overlapping ranges merge; another revision is a separate key.
- `charge(requested_chars)` grants `min(requested, remaining)` — including grants below 500 —
  and raises `BudgetExhausted` when `reads >= max_reads` or remaining `<= 0`.
- `chars_read` counts DELIVERED characters (repeated reads count again); `LedgerEntry.chars` counts unique covered chars.
- Write `test_read_ledger.py`.

**NOT in scope**: clipping a `ReadResult` (TASK-5323), the read lock (TASK-5324), citations (TASK-5322).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/read_ledger.py` | CREATE | Ledger models and merge logic |
| `packages/ai-parrot/tests/knowledge/pageindex/test_read_ledger.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.segments import ReadResult, SegmentRead   # verified: segments.py:110, :97
from pydantic import BaseModel
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class SegmentAddress(BaseModel): doc_id, revision, seq, page=None, ordinal, section=None   # :71
class SegmentRead(BaseModel): address: SegmentAddress, seq, kind, text, start, end, truncated=False, flags  # :97
class ReadResult(BaseModel): tree_name, doc_id, revision, generation=None, segments: list[SegmentRead], truncated, next_cursor, framed  # :110
```
`SegmentRead.start/end` are offsets over the STORED segment text (set in `toolkit._read`).
Key a read by `(read.address.doc_id, read.address.revision, read.seq)`.

### Does NOT Exist
- ~~`parrot.knowledge.pageindex.read_ledger`~~ — you create it.
- ~~`ReadResult.ledger`~~, ~~cursor-as-ledger~~ — cursors carry no coverage.
- ~~a shared interval-merge utility in `parrot.knowledge.pageindex.utils`~~ — write the merge here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/read_ledger.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_read_ledger.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#ReadResult",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#SegmentRead"
  ]
}
```

---

## Implementation Notes

- Merge on `record`, not on query, so `covered()` is always a sorted disjoint list —
  because the validator tests containment against ONE interval ("adjacent reads jointly cover").
- `generation` is set from the first recorded `ReadResult.generation` and never changed.
- `entries()` sorted by `(doc_id, revision, seq)`.
- Pure Python, no I/O, no locking (the caller holds the lock).

---

## Implementation Blueprint

### Steps (in order)
1. Create `read_ledger.py` from the block below — because TASK-5322/5323 import these exact names.
2. Fill the merge and `charge` logic (FILL IN markers).
3. Write the tests, run them.

### `read_ledger.py` (CREATE)
```python
"""Request-local read ledger for PageIndex agentic retrieval (FEAT-843).

Records the half-open character ranges of stored segment text that read tools actually
returned. Cursors are not a ledger; only ranges recorded here are citable.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from parrot.knowledge.pageindex.segments import ReadResult, SegmentRead

Range = tuple[int, int]
_Key = tuple[str, str, int]

__all__ = ["Range", "BudgetExhausted", "LedgerEntry", "ReadLedger"]


class BudgetExhausted(RuntimeError):
    """Internal read-budget signal, caught by the wrapper; never a provider-loop stop mechanism."""


class LedgerEntry(BaseModel):
    """Merged coverage of one segment of one document revision."""

    doc_id: str
    revision: str
    seq: int
    ranges: list[Range]
    chars: int


def _merge(ranges: list[Range], new: Range) -> list[Range]:
    """Insert ``new`` into sorted disjoint ``ranges``; touching or overlapping ranges merge."""
    # FILL IN: sort + sweep merge where a.end >= b.start merges — bounded by AC-1
    raise NotImplementedError


class ReadLedger:
    """Ranges delivered to the model in one request, plus its read budget."""

    def __init__(self, *, budget_chars: int, max_reads: int) -> None:
        self._budget_chars = int(budget_chars)
        self._max_reads = int(max_reads)
        self._ranges: dict[_Key, list[Range]] = {}
        self._chars_read = 0
        self._reads = 0
        self._generation: Optional[int] = None

    def charge(self, requested_chars: int) -> int:
        """Grant at most the remaining characters, including allowances below 500.

        Raise ``BudgetExhausted`` when ``reads >= max_reads`` or nothing is left.
        Caller holds the read lock through charge, read, clipping and record."""
        # FILL IN: raise when reads >= max_reads or remaining <= 0; else return min(requested, remaining) — AC-2, AC-18
        raise NotImplementedError

    def record(self, result: ReadResult) -> None:
        """Merge every ``SegmentRead.start/end`` of ``result`` into the entry of its ``(doc_id, revision, seq)``.

        Touching or overlapping ranges merge; a read from another revision is a separate entry.
        Records ``result.generation`` on first use and counts delivered ``chars`` and ``reads``.
        Counts repeated characters again for budget accounting, independently of merged coverage."""
        if self._generation is None and result.generation is not None:
            self._generation = result.generation
        self._reads += 1
        for read in result.segments:
            self._add(read)

    def _add(self, read: SegmentRead) -> None:
        # FILL IN: skip empty ranges; key = (address.doc_id, address.revision, seq); merge; chars_read += end-start
        raise NotImplementedError

    def covered(self, doc_id: str, revision: str, seq: int) -> list[Range]:
        return list(self._ranges.get((doc_id, revision, seq), []))

    def has_revision(self, doc_id: str, revision: str) -> bool:
        return any(k[0] == doc_id and k[1] == revision for k in self._ranges)

    def entries(self) -> list[LedgerEntry]:
        return [
            LedgerEntry(doc_id=k[0], revision=k[1], seq=k[2], ranges=list(r), chars=sum(e - s for s, e in r))
            for k, r in sorted(self._ranges.items())
        ]

    @property
    def chars_read(self) -> int:
        return self._chars_read

    @property
    def reads(self) -> int:
        return self._reads

    @property
    def generation(self) -> Optional[int]:
        return self._generation
```
**Why**: `has_revision` is added (beyond the spec skeleton) because the validator needs to tell
`revision_unread` from `segment_unread`; it is a read-only helper with no new semantics.
Whether `charge` increments `reads` or `record` does: `record` does — so a refused charge
never consumes a read.

### `test_read_ledger.py` (CREATE)
```python
"""FEAT-843 M1 — ReadLedger."""
import pytest

from parrot.knowledge.pageindex.read_ledger import BudgetExhausted, ReadLedger
from parrot.knowledge.pageindex.segments import ReadResult, SegmentAddress, SegmentRead

REV_A = "a" * 16
REV_B = "b" * 16


def _result(doc: str, rev: str, seq: int, start: int, end: int, generation=1) -> ReadResult:
    addr = SegmentAddress(doc_id=doc, revision=rev, seq=seq, page=1, ordinal=1)
    read = SegmentRead(address=addr, seq=seq, kind="paragraph", text="x" * (end - start), start=start, end=end)
    return ReadResult(tree_name="t", doc_id=doc, revision=rev, generation=generation, segments=[read],
                      truncated=False, next_cursor=None, framed="")

# FILL IN: test_touching_ranges_merge ([0,500)+[500,900) -> [(0,900)]) — AC-1
# FILL IN: test_gap_kept_separate ([0,500)+[600,900)) — AC-1
# FILL IN: test_other_revision_separate_key — AC-1
# FILL IN: test_charge_grants_below_500 (budget 100 -> charge(12000) == 100) — AC-18
# FILL IN: test_charge_raises_on_max_reads and on chars exhausted — AC-2
# FILL IN: test_repeated_reads_count_chars_again_but_coverage_unique
# FILL IN: test_generation_pinned_on_first_record; test_entries_sorted
```
Verify `SegmentRead`/`ReadResult` required fields against `segments.py:97-120` before running (e.g. `kind`'s allowed values).

### FILL IN checklist
- [ ] `_merge`
- [ ] `charge`
- [ ] `_add`
- [ ] all test stubs

---

## Acceptance Criteria

- [ ] AC-1 merge/separate/other-revision behaviour.
- [ ] AC-2 `charge` raises `BudgetExhausted` at `max_reads` or when budget spent.
- [ ] AC-18 (ledger part) grants below 500 work; repeated reads re-count `chars_read`.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_read_ledger.py -q`

---

## Test Specification

See blueprint test stubs; spec §4 row `test_read_ledger.py`.

---

## Agent Instructions

1. Verify the Codebase Contract against `segments.py`.
2. Implement only the two files above.
3. `ruff check --fix` both files; run the validation command with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit: `feat(pageindex-agentic-retrieval): TASK-5320 — read ledger`.

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 147s. Merged (lint 0402212b83).

Validation: chunk merge-tier run on the host (engine background validation is capped at ~60s and timed out three times): `parrot sdd tests select --tier merge --run` → 131 passed, 1 xfailed at HEAD 33b0e0fe86 (log: /tmp/claude-1000/sdd-logs/FEAT-843/merge-chunk1.log). `test_pageindex_serves_over_stdio` is xfail (non-strict) pending FEAT-844 / issue:70f18da2a8d5. Closed via `parrot sdd task close`, not `task finalize` (no engine validation ref).
