# TASK-5387: Move the `agentic_retrieve` tree snapshot off-loop and under the deadline

**Feature**: FEAT-849 — PageIndex Toolkit Tech Debt
**Spec**: `sdd/specs/pageindex-toolkit-tech-debt.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5385
**Assigned-to**: unassigned

**Discovered-from**: `issue:2e4dfac0d686`

---

## Context

Implements spec §4 FR-3 and FR-5.2, and §3 decision D-4. Part of the work that closes
`issue:2e4dfac0d686` (items 2 and 5).

`PageIndexToolkit.agentic_retrieve` brackets every expensive step with a deadline check:
the lock acquisition (`toolkit.py:1290`), stage-1 search (`1301`), the outline (`1320`) and
the retriever (`1327`) are all wrapped in `asyncio.wait_for` against the remaining time,
falling back to `timeout_bundle()`.

One step is not: `tree = copy.deepcopy(self._load_tree(tree_name))` (`toolkit.py:1295`)
runs **synchronously on the event loop**, after the lock is acquired and outside every
`wait_for`. On a large tree it blocks the loop outright and can consume — or overrun — the
caller's whole timeout before the first downstream deadline check ever runs.

Item (5) of the same issue is documentation: the single `_agentic_lock` serialises every
concurrent agentic request per toolkit instance, so effective concurrency is one in flight
per instance. That goes in this task's docstring; the wiki side is TASK-5388.

**Depends on TASK-5385** for one reason only: both tasks modify `toolkit.py`, so they must
not run concurrently. There is no symbol dependency between them.

---

## Scope

- Perform the tree load + deepcopy in a worker thread, wrapped in `asyncio.wait_for`
  against the remaining deadline, with `timeout_bundle()` as the `TimeoutError` fallback.
- Document the per-instance serialisation limit in `agentic_retrieve`'s docstring.
- Write a test in `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_snapshot.py`.

**NOT in scope**:
- `agentic.py` — TASK-5386. **Do not touch it.**
- The re-import short-circuit — TASK-5385.
- `wiki/knowledge/pageindex-agentic-retrieval.md` — TASK-5388.
- Changing lock granularity. `_agentic_lock` stays one lock per toolkit instance; this task
  only documents the consequence (spec §1 Non-Goals).
- The second `tree = copy.deepcopy(self._load_tree(tree_name))` occurrence at
  `toolkit.py:1528` — a different method, outside this feature.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | Deadline-bound off-loop snapshot + docstring |
| `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_snapshot.py` | MODIFY | Test for AC-7 |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase at `dev`.
> Do NOT invent any import, attribute, or method not listed here.

### Verified Imports

Already present at the top of `toolkit.py` — add no new import:

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:21-22, 41 (verified)
import asyncio
import copy
from .generation import StaleGenerationError, WriteTransaction, generation_of
from .agentic import AgenticRetriever, EvidenceBundle, clone_for_tools  # toolkit.py:38
```

Test file, already present (verified `test_agentic_snapshot.py:3-11`):

```python
import copy
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
from parrot.knowledge.pageindex.segments import RevisionMismatchError
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:1233
async def agentic_retrieve(
    self,
    tree_name: str,
    query: str,
    top_k: int = 5,
    draft_answer: bool = True,
    budget_chars: Optional[int] = None,
    max_reads: Optional[int] = None,
    timeout_s: Optional[float] = None,
) -> dict[str, Any]:
    """Stage-1 search, then a bounded reading loop that returns cited evidence."""  # :1243-1248

# Inside agentic_retrieve, verified line numbers:
#   1273  def timeout_bundle(candidates=None, generation=None) -> dict[str, Any]   (closure)
#   1284  remaining = deadline - loop.time()
#   1290  await asyncio.wait_for(self._agentic_lock.acquire(), timeout=remaining)
#   1295  tree = copy.deepcopy(self._load_tree(tree_name))      <-- the line this task changes
#   1296  generation = generation_of(tree)
#   1301  candidates = await asyncio.wait_for(self._agentic_search(...).search(...), timeout=remaining)
#   1343  self._agentic_lock.release()  (in `finally`, guarded by `acquired`)

# toolkit.py:503
def _load_tree(self, tree_name: str) -> dict[str, Any]:

# toolkit.py:291  (set in __init__)
self._agentic_lock = asyncio.Lock()

# packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py
def generation_of(tree: dict[str, Any]) -> Optional[GenerationInfo]:
```

The `timeout_bundle` closure returns `EvidenceBundle(..., stopped="timeout").model_dump()`
and accepts `candidates` and `generation` keyword arguments only (verified
`toolkit.py:1273-1282`).

### Does NOT Exist

- ~~`PageIndexToolkit._load_tree_async` / `._aload_tree`~~ — `_load_tree` is sync only;
  the off-loop hop is `asyncio.to_thread`.
- ~~`JSONTreeStore.aload`~~ — no async load on the store.
- ~~`asyncio.to_thread(..., timeout=...)`~~ — `to_thread` takes no timeout; it must be
  wrapped in `asyncio.wait_for`.
- ~~`timeout_bundle(tree=...)`~~ — the closure takes only `candidates` and `generation`.
- ~~`copy.deepcopy` being thread-unsafe here~~ — it is called on a freshly loaded dict that
  no other task holds, so running it in a worker thread needs no extra lock (the
  `_agentic_lock` is already held at this point).
- ~~`asyncio.wait_for` cancelling the worker thread~~ — a `to_thread` call that times out
  leaves the thread running to completion; that is accepted here (the result is discarded).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_agentic_snapshot.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.agentic_retrieve",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._load_tree",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py#generation_of"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **The snapshot stays inside the lock.** Do not move it above the `await
  asyncio.wait_for(self._agentic_lock.acquire(), ...)` — the lock is what makes the
  snapshot consistent with the rest of the request.
- **`generation=None` on this timeout** (FR-3.2): the generation is read *from* the tree,
  so it is not known yet when the snapshot itself times out. Call `timeout_bundle()` with
  no arguments, consistent with the lock-acquisition timeout above it.
- **Recompute `remaining` immediately before the wait.** The existing code recomputes
  `remaining = deadline - loop.time()` before each step; follow that pattern rather than
  reusing the lock-acquisition value.
- **`TimeoutError` is the bare builtin here.** The surrounding code catches `TimeoutError`
  (not `asyncio.TimeoutError`) — on Python 3.11+ they are the same object; match the file.
- Async throughout; 120-col lines; Google-style docstrings.

### References in Codebase

- `toolkit.py:1298-1311` — the stage-1 search step: the exact
  `remaining` → `wait_for` → `except TimeoutError: return timeout_bundle(...)` shape to copy.
- `toolkit.py:2206-2211` — `_doc_ids_in`, the module's existing "read files off the event
  loop with `asyncio.to_thread`" precedent.

---

## Implementation Blueprint

### Steps (in order)

1. Replace the bare snapshot line with a deadline-bound `to_thread` call — *why*: FR-3.1;
   a large tree must not block the loop or silently eat the caller's timeout.
2. Extend `agentic_retrieve`'s docstring with the serialisation limit — *why*: FR-5.2.
3. Write the timeout test — *why*: AC-7 is the closing evidence for item 2.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY — snapshot)

```python
# occurrences: 2 (verified: grep -c 'tree = copy.deepcopy(self._load_tree(tree_name))' toolkit.py)
# FILL IN: disambiguate — the anchor appears twice (agentic_retrieve toolkit.py:1295 and a
# different method at toolkit.py:1528). Target ONLY the first, identified by the two lines
# that follow it:
#
#             tree = copy.deepcopy(self._load_tree(tree_name))
#             generation = generation_of(tree)
#             generation_id = generation.id if generation else None
#
# Replace that first line with:

            remaining = deadline - loop.time()
            if remaining <= 0:
                return timeout_bundle()
            try:
                tree = await asyncio.wait_for(
                    asyncio.to_thread(lambda: copy.deepcopy(self._load_tree(tree_name))),
                    timeout=remaining,
                )
            except TimeoutError:
                return timeout_bundle()
```

**Why**: spec D-4 / FR-3. The load and the deepcopy both become a single off-loop unit, so
neither blocks the event loop, and the whole unit is bounded by the caller's deadline like
every other step in this method. `timeout_bundle()` is called with no arguments because the
generation is read from the tree on the *next* line and is therefore still unknown
(FR-3.2) — exactly as the lock-acquisition timeout above does it. The `lambda` keeps load
and copy in the same thread hop; splitting them would ship the loaded tree across the
boundary twice for no benefit. The lock is already held here and must stay held.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY — docstring)

```python
# occurrences: 1 (verified: grep -c 'Stage-1 search, then a bounded reading loop that returns cited evidence.' toolkit.py)
# REPLACE the docstring of `agentic_retrieve` (verified: toolkit.py:1243-1248), keeping its
# first three paragraphs and appending the concurrency note:
        """Stage-1 search, then a bounded reading loop that returns cited evidence.

        Returns an evidence bundle: candidates, the exact ranges read, validated citations
        (``[Report.pdf, p. 12 ¶3]``), rejected ones with reasons, and optionally a drafted
        answer. ``grounded`` is false when no citation survived validation. Requires an LLM.

        **Serialised per toolkit instance.** A single ``_agentic_lock`` guards the whole
        request, so exactly one agentic retrieval runs at a time per ``PageIndexToolkit``.
        A second concurrent caller waits for the lock and, if its own ``timeout_s`` expires
        first, receives a ``stopped="timeout"`` bundle without ever having searched. Scale
        out with separate toolkit instances, not with concurrent calls on one.
        """
```

**Why**: FR-5.2 — the limit is stated where a caller sizing concurrency will read it,
together with the observable symptom (a `timeout` bundle with no candidates) and the remedy
(separate instances). The first three paragraphs are preserved verbatim so the public
contract of the method is unchanged.

### `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_snapshot.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'def test_agentic_search_not_cached' test_agentic_snapshot.py)
# AFTER — append below the end of `test_agentic_search_not_cached`
# (verified: test_agentic_snapshot.py:163, the module's last test). Reuse the existing
# `toolkit` / `paged_toolkit` fixtures (test_agentic_snapshot.py:45, :70).


@pytest.mark.asyncio
async def test_agentic_retrieve_times_out_on_snapshot(paged_toolkit: PageIndexToolkit, monkeypatch) -> None:
    """AC-7: a snapshot that cannot finish inside the deadline yields a timeout bundle."""
    # FILL IN: monkeypatch `PageIndexToolkit._load_tree` (bound on the instance, or via
    # monkeypatch.setattr on the class) with a slow sync stub that sleeps longer than the
    # timeout, then call
    #   bundle = await paged_toolkit.agentic_retrieve("<tree>", "q", timeout_s=<small>)
    # and assert bundle["stopped"] == "timeout", bundle["candidates"] == [] and
    # bundle["generation"] is None. Bounded by AC-7 and FR-3.2.
    #
    # Two constraints that decide whether this test is meaningful:
    #  * use a SYNC sleep (time.sleep) in the stub — an `async def` stub would not prove the
    #    load runs off-loop, which is the whole point of FR-3.1;
    #  * keep timeout_s small but non-trivial (e.g. 0.05-0.2s) against a stub sleep several
    #    times longer, so the assertion does not depend on machine speed.
    raise NotImplementedError
```

**Why**: `test_agentic_snapshot.py` already owns the snapshot semantics of
`agentic_retrieve` (including `test_reimport_does_not_change_snapshot`) and ships the
`toolkit` / `paged_toolkit` fixtures, so the test attaches there. The sync-sleep constraint
is what makes it a real regression test: before this task the sleep would block the loop and
the method would return *late* rather than returning a timeout bundle.

### FILL IN checklist

- [ ] `toolkit.py::agentic_retrieve` — disambiguate the 2-occurrence deepcopy anchor and
      edit only the one at `:1295`; bounded by "NOT in scope" (`:1528` is out).
- [ ] `test_agentic_snapshot.py::test_agentic_retrieve_times_out_on_snapshot` — sync-sleep
      stub, small `timeout_s`; bounded by AC-7 and FR-3.2.

---

## Acceptance Criteria

- [ ] AC-7 — `agentic_retrieve` against a tree whose load+deepcopy cannot finish inside the
      remaining deadline returns `stopped="timeout"` with `generation is None`, rather than
      overrunning the timeout.
- [ ] The snapshot runs off the event loop (`asyncio.to_thread`) and still inside `_agentic_lock`.
- [ ] `agentic_retrieve`'s docstring documents the per-instance serialisation limit.
- [ ] `test_reimport_does_not_change_snapshot` and the other existing snapshot tests pass.
- [ ] `ruff check` clean on both changed files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_agentic_snapshot.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_locks.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py -q`

---

## Test Specification

One test appended to
`packages/ai-parrot/tests/knowledge/pageindex/test_agentic_snapshot.py`:
`test_agentic_retrieve_times_out_on_snapshot` (AC-7), using the module's existing
`paged_toolkit` fixture and a sync-sleeping `_load_tree` stub.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-toolkit-tech-debt --feature-id FEAT-849`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5385 must be `"done"` in
   `sdd/tasks/index/pageindex-toolkit-tech-debt.json` (it edits the same file)
4. **Verify the Codebase Contract** — re-grep every anchor's occurrence count before
   editing; TASK-5385 touched this file, so line numbers above may have shifted. A count of
   0 means the anchor moved: stop and report the drift
5. **Update status** in `sdd/tasks/index/pageindex-toolkit-tech-debt.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint, completing every `# FILL IN:` marker
7. **Verify** by running the Validation Commands with
   `PYTHONPATH=<wt>/packages/ai-parrot/src`
8. **Commit the code** — stage only the two files this task lists; **never `agentic.py`**
9. **Close the task**: `parrot sdd task close TASK-5387 pageindex-toolkit-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Code session ai-parrot-b5 (/sdd-fix d34c567792ef)
**Date**: 2026-11-09
**Notes**: The snapshot in `agentic_retrieve` now runs as
`await asyncio.wait_for(asyncio.to_thread(lambda: copy.deepcopy(self._load_tree(tree_name))),
timeout=remaining)`, preceded by the usual `remaining = deadline - loop.time()` recompute and
falling back to `timeout_bundle()` (no arguments, so `generation=None` per FR-3.2). It stays
inside `_agentic_lock`. The second `copy.deepcopy(self._load_tree(...))` occurrence, in a
different method, was left alone as the task required.

`agentic_retrieve`'s docstring gained the per-instance serialisation paragraph; the three
original paragraphs are unchanged.

The regression test was verified non-vacuous: with the new block reverted to the original
one-liner, `test_agentic_retrieve_times_out_on_snapshot` fails with `assert 2 is None` — the
synchronous sleep blocks the loop, the slow load completes, and the method proceeds past its
deadline with a real generation instead of returning a timeout bundle. Restored afterwards.

6/6 pass in `test_agentic_snapshot.py`; 35/35 across `test_locks.py` and
`test_agentic_retrieval.py`.

**Deviations from spec**: none. One note: `ruff check` reports one B905 (`zip()` without
`strict=`) at `toolkit.py:2390`, verified pre-existing on `origin/dev` and outside this task's
scope, so left alone — same finding as TASK-5385.
