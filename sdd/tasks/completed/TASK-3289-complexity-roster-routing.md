# TASK-3289: Constrain chunk assignment and retries by measured eligibility

**Feature**: FEAT-561 - Deterministic complexity routing for SDD tasks
**Spec**: `sdd/specs/complex-sdd-tasks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3287
**Assigned-to**: unassigned

## Context

Implements FEAT-561 §2–§4; feature acceptance coverage: AC7, AC8, AC9, AC11, AC14.
Measured evidence must determine routing before dispatch. This task owns the
bounded deliverable below; decisions are fixed by the approved spec and this packet.

## Scope

- Add pure exact-model eligibility filtering and eligibility-aware chunk construction while preserving standard rotation and FEAT-560 partition_wave.
- Accept only the available seats supplied by the caller; do not reconstruct candidates from the original roster or override suspension exclusions.

**NOT in scope**: unrelated refactors, provider/client changes, new dependencies,
FEAT-559 suspension implementation, edits outside the file table, or changing
approved scoring thresholds through LLM judgment.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py` | MODIFY | Scoped implementation/documentation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py` | MODIFY | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified from source at `3ba22952c307435fba30704081f1af72658c568f`. Source-verified signatures below are not
claims of runtime import smoke testing. Recheck after upstream task merges.

### Verified Imports / Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py:133` — `def available_seats(roster: RosterConfig, results: List[SeatProbeResult]) -> List[RosterSeat]`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py:152` — `def assign(self, wave: List[TaskRef], task_files: Dict[str, str]) -> List[PlanChunk]`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py:189` — `def retry_seat(self, failed_label: str, exclude: Set[str]) -> Optional[RosterSeat]`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:65` — `def partition_wave(wave: Sequence[TaskRef]) -> List[List[TaskRef]]`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:45` — `class RosterSeat(BaseModel):`.

### Exact existing symbol IDs

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterSeat` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#ChunkAssigner.assign` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#ChunkAssigner.retry_seat` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#available_seats` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#partition_wave` — source-verified symbol identity for the references above.

### Touched-file freshness

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py:1` — existing file read; baseline SHA-256 `e4f7b584f6e3c09b9ea81df867421ba07024f7e969d217236c88366411ff2aa3`. Hash is freshness evidence, not a Delegation Contract.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py:1` — existing file read; baseline SHA-256 `94db0c71d5d15dc91b2078bacbde695ade44aec4034ffeb97cae50bc188c6989`. Hash is freshness evidence, not a Delegation Contract.

### Dependency-provided contracts

- `TASK-3287` creates/changes: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity.py`, `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity.py`. These outputs are future contracts at authoring time; verify after the dependency lands.

### Integration reconciliation

FEAT-559 is in progress in its own per-spec index and is not implemented in this
baseline: there is no landed execution-pool API to import. Freeze this task's
interfaces against current dev. If FEAT-559 lands before execution/merge, reverify
contracts and preserve its available-seat/suspension intersection and execution
identity; never restore a suspended seat or discard its API parameters. Do not
add external TASK IDs to this feature's depends_on DAG. FEAT-560 has already
landed `partition_wave` in `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py`; roster changes must preserve it.
This resolves spec §8's code-research prerequisite; no guessed pool APIs are used.

### Does NOT Exist

- `sdd_coder/orchestrator.py` — use the verified engine module.
- An existing complexity classifier or graph revision token at this baseline.
- Guaranteed equivalence between `sonnet` and `sonnet-5`.
- Dependency-created complexity symbols before their owning tasks complete.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterSeat",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#ChunkAssigner.assign",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#ChunkAssigner.retry_seat",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#available_seats",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#partition_wave"
  ]
}
```

This declares existing references verified above, not a precomputed score.
When dependency-created symbols become existing imports, the executor must verify
and add them to this contract before admission; absence from today's graph is
not evidence of zero impact. Collector snapshots and scores remain server-owned.

## Implementation Notes

Use existing Pydantic v2 and async subprocess patterns. No new library installation.
Maintain 120-column Python, strict type hints, Google-style docstrings and logging.
Keep architecture decisions in this task/spec; do not ask the coder to decide
whether a task feels complex. No Delegation Contract is emitted: this packet
fixes interfaces and behavior but does not contain complete writer-ready source.

**Parallelism**: true. Depends on TASK-3287 classification semantics and upstream models. Parallel with TASK-3288 and TASK-3293; only owns roster.py/test_roster.py.

## Implementation Blueprint

### Fixed interfaces and behavior

New in roster.py: eligible_seats(assessment: ComplexityAssessment, seats: list[RosterSeat], policy: ComplexityPolicy) -> list[RosterSeat]. Standard returns the supplied ordered subset; complex/unknown matches exact backend (or native) + effective seat.model against configured StrongModelIdentity entries. Empty/unrecognized/ambiguous model is ineligible for restricted tasks. Preserve input order and probe-resolved model_used; do not match seat nicknames or inferred aliases.
Extend existing methods using keyword-only arguments, preserving old positional forms:
- ChunkAssigner.assign(self, wave: List[TaskRef], task_files: Dict[str,str], *, eligible_labels: dict[str,set[str]] | None = None) -> List[PlanChunk]. None keeps the legacy standard-only algorithm; with a map every wave task must have a nonempty entry (missing/empty is ValueError; engine prefilters blocked tasks). Use partition_wave, preserving exclusive singleton batches. Select distinct eligible seats in current cyclic order; when none is unused in a chunk, close the chunk and continue. Never silently drop or duplicate a task. Advance rotation once for each emitted chunk as before.
- ChunkAssigner.retry_seat(self, failed_label: str, exclude: Set[str], *, eligible_labels: set[str] | None = None) -> Optional[RosterSeat]. Apply old excluded/native rules and intersect labels when present.
The engine, not this helper, creates per-task complex_model_unavailable diagnostics. Restrict by probed effective models after probe fallback. Preserve future FEAT-559 exclusion arguments if they land; eligibility is an additional intersection, never an override.

### Steps (in order)

1. Add the pure identity filter using upstream types.
2. Extend assign/retry with keyword-only eligibility inputs and preserve the partition_wave import.
3. Test standard assignments unchanged and scarce strong seats across multiple chunks.

Blueprints are implementation instructions, not stub source files. Implement the
complete behavior and edge cases; do not leave placeholders in executable code.

## Acceptance Criteria

- [ ] Standard-only calls reproduce existing assignments and rotation.
- [ ] Complex/unknown tasks receive only exact configured effective identities.
- [ ] Multiple restricted tasks with one eligible seat become separate chunks; each task appears exactly once.
- [ ] Exclusive tasks remain isolated; retry never chooses native, excluded or ineligible seats.
- [ ] A probe fallback to a weak model removes that seat only from the restricted set.

## Test Specification

- Extend existing test_roster.py with mixed task eligibility, unavailable labels, duplicate-seat prevention and alias rejection.
- Assert eligibility filters preserve an already restricted availability subset (FEAT-559 integration seam).
- Run pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py -q.

Store command output in `artifacts/logs/TASK-3289-complexity.log`. Use the activated
main environment; worktrees share it and must not create/install a new environment.
No live model call is needed for these checks.

## Agent Instructions

1. Read the approved spec and verify every dependency is completed in this feature index.
2. Re-read exact source contracts and dependency outputs; update this packet if references moved.
3. Mark only this task in progress in `sdd/tasks/index/complex-sdd-tasks.json` in the feature worktree.
4. Implement only the declared scope and run its focused validation.
5. Commit code and this task's SDD state together; preserve other agents' edits.
6. On verified completion move the task to completed, update its index entry/path and fill the Completion Note.

## Completion Note

Implemented directly by the worker (not merged from a coder delivery):
`eligible_seats(assessment, seats, policy)` added to `roster.py`
(standard -> unchanged seat list; complex/unknown -> exact `(backend,
model)` match against `policy.strong_models`, `backend="native"` for
`kind="native"` seats); `ChunkAssigner.assign(..., eligible_labels=...)`
now requires a non-empty eligible-label set per wave task (raises
`ValueError` otherwise) and closes a chunk early rather than filling a gap
with an ineligible seat; `ChunkAssigner.retry_seat(..., eligible_labels=...)`
applies the same restriction to retries.

Two dispatched attempts, neither merged:
- mistral (attempt_uid 3c36a0f1e6fe42629eab8c75f792a9b6) failed with
  `dirty_task_worktree` (an uncommitted `test_implementation.py` scratch
  file) before reaching the merge/fidelity gate; its code was not reviewed.
- gemini (attempt_uid d2df4f50661c45178dc5aeea0c655847) completed and its
  `roster.py`/`test_roster.py` changes were substantively correct, but it
  also modified `sdd_coder/__init__.py` to export `eligible_seats` from
  the package root -- a real edit outside this task's 2-file declared
  scope -- so the engine's fidelity gate rejected the whole delivery as
  `fidelity_violation` and it was never merged. Recorded as model feedback
  (`coder-feedback:2891011a7e2c0258f220ef53`) and review outcome
  (`coder-review:6b1891b338e6fcc8e11057f9`).

Reimplemented from scratch in this worktree (commit
`865a58e5fa19daf6839eb84b2d9fe958f0bafbd1`), touching only the 2 declared
files: tests import `eligible_seats` directly from the `.roster` submodule
instead of the package root, so no `__init__.py` change was needed.

Acceptance criteria: satisfied — `eligible_seats` never overrides
availability/suspension (operates only on the `seats` list the caller
supplies); `ChunkAssigner.assign`/`retry_seat` preserve standard rotation,
exclusive-task-alone-first ordering and one-seat-per-chunk when
`eligible_labels` is omitted (existing tests unchanged and still passing);
eligibility restriction is exact-match only, no alias/nickname matching
(`test_eligible_seats_no_alias_match`).

Tests: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ -q` ->
286 passed (0 failed), from the feature worktree with
`PYTHONPATH=packages/ai-parrot/src`. `ruff check --select E9,F63,F7,F82`
clean.

Limitations: none beyond this task's declared scope; engine-level
integration (TASK-3290/3291) still needs to call `eligible_seats` and pass
`eligible_labels` through `assign`/`retry_seat`.

Seat: worker (self-implementation, after gemini's fidelity_violation) ·
Backend: n/a · Model: n/a · Attempts: 2 dispatched (both rejected) + 1
worker implementation · Duration: n/a (worker-authored) · Tokens: n/a.
