# TASK-5711: Isolate corrupt SQLite vector candidates

**Feature**: FEAT-892 — Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5710
**Assigned-to**: unassigned
**Discovered-from**: `issue:fafca9236933`

## Context

The ledger group includes event-loop vector scoring and corrupt-row failure. TASK-5706 already added NumPy scoring
outside the event loop. Its deliberate preservation of corrupt-vector exceptions leaves the second issue unresolved.
This task supersedes that earlier error behavior only for corrupt stored candidates. The owner approved appending
these scoped repairs to the review-status spec on 2026-11-16.

## Scope

Skip malformed and non-finite stored vectors, emitting a diagnostic without vector content or scope values.
Retain existing off-loop scoring, valid-vector scores/order, dimension-mismatch and zero-norm behavior, and ceiling.
Do not add a new execution mechanism, dependency or storage migration.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` | MODIFY | Reject individual corrupt candidates without aborting scoped recall |
| `packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py` | MODIFY | Corruption regressions and retained off-loop/scoring contracts |

## Codebase Contract

Verified in the feature worktree at `983470d620b8ffa27527d11169abbbc4be31f95b`.

### Verified Imports

- `numpy as np`, `math`, `struct`, `logging`, `asyncio` already occur in the backend/test modules.
- `from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend` exists in the test module.
- `pytest`, `pathlib.Path` are existing test dependencies/stdlib.

### Existing Signatures to Use

- `_rank_candidates(embedding: list[float], candidates: list[tuple[bytes, int]], score_threshold: float, top_k: int) -> list[tuple[int, float]]` at sqlite.py:117.
- `SQLiteEpisodeBackend.search_similar` selects ids/blobs/dimensions and dispatches `_rank_candidates` off-loop.
- `_pack_embedding` uses little-endian float32; `_SCORE_BLOCK_ROWS = 1024` bounds NumPy matrices.
- `_episode` and `_SCOPE` in test_sqlite_backend.py build local isolated fixtures.

### Does NOT Exist

- There is no separate vector table or vector extension.
- There is no remaining `_cosine` or `_unpack_embedding` helper after TASK-5706.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py", "action": "MODIFY"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#_rank_candidates", "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend.search_similar"]
}
```

## Implementation Blueprint

### Steps (in order)

1. Validate dimensions and blob types/shapes before scoring, skipping invalid candidates rather than raising.
2. Exclude non-finite vectors from results even at a zero threshold; keep valid zero/mismatched vectors at zero.
3. Remove eager integer coercion in search_similar so corrupt dimension values reach candidate validation.
4. Log an aggregate skipped count without data, then test valid neighbors and all-invalid scopes.

### Backend (MODIFY)

```python
# REPLACE validation inside `def _rank_candidates(`; occurrences: 1, sqlite.py:117.
# Keep the existing signature and off-loop caller.
# FILL IN: shape/type checks and non-finite score masking, bounded by AC1–AC3.
# Use np.nan for excluded scores so they never qualify at score_threshold=0.
```

**Why:** corruption belongs to one persisted row and must not make otherwise valid scoped recall unavailable.

### Tests (MODIFY)

```python
# REPLACE `async def test_vector_scoring_rejects_malformed_and_non_finite_vectors(tmp_path) -> None:`
# occurrences: 1, test_sqlite_backend.py:510.
# FILL IN: parameterized corruption fixtures and valid-neighbor assertions, bounded by AC1–AC3.
```

**Why:** the old test explicitly required the failure now being repaired; valid-vector and dispatch tests stay.

### FILL IN checklist

- [ ] Invalid shape/type/dimension handling, finite masks and diagnostic.
- [ ] Valid-neighbor, zero-query/threshold and all-corrupt regressions.

## Acceptance Criteria

- [ ] AC1: malformed blob, NULL/non-integer/non-positive dimension, NaN and infinity never abort vector recall.
- [ ] AC2: bad candidates never qualify, including at threshold zero and with a zero query; valid neighbors retain scores/order.
- [ ] AC3: invalid input queries still fail; existing off-loop dispatch and latency contract pass; skipped count is logged.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py -q`

## Test Specification

Parameterize stored corruptions against a healthy neighbor, test an all-corrupt scope, and retain reference scoring,
targeted payload fetch and ceiling latency coverage. Use temporary databases; do not mutate shared data.

## Agent Instructions

Wait for TASK-5710, which modifies sqlite.py. Reverify anchors. Implement only declared files in the feature worktree.
Use its package source on PYTHONPATH, store logs under artifacts/logs, run Black and Ruff, commit scoped code and
finalize through `parrot sdd task finalize` with real validation and review evidence.

## Completion Note

- Task: TASK-5711
- Feature: agent-memory-mixin
- Implementation SHA: 494e305ee660806b5a946b3d3a68132e6e7aef6b
- Closed at (UTC): 2026-11-16T11:10:20+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 282.6s · Tokens: n/a |
