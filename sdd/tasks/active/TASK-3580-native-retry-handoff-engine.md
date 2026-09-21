# TASK-3580: Engine — native retry handoff via `retry_native`, plus an honest all-native diagnostic

**Feature**: FEAT-588 — Make the sdd-coder retry ladder reachable for complex/unknown tasks
**Spec**: `sdd/specs/fixgroup-47eb801095a6.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:569e81756247` (ledger, severity major)

---

## Context

Implements spec §3 **Module 1** (native retry handoff) and **Module 2** (honest
diagnostics). This is the core of FEAT-588.

A `complex`/`unknown` task that fails attempt 1 computes its retry set as
`eligible(strong_models) − tried{attempt-1 seat} − {native seats}`. With the
shipped roster that is `{terra, sonnet} − {terra} − {sonnet} = ∅`, so the task
is blocked with `complex_model_unavailable` and never retries. The native seat
is dispatch-capable for attempt 1 (via `prepare_native`) but invisible to
attempt 2.

TASK-3554 added the two `kind == "native"` guards that cause this, and named
closing the asymmetry as explicitly out of its scope and "a known follow-up".
This task is that follow-up.

---

## Scope

- Add a helper on `SddCoderEngine` that answers **only** "is there an untried,
  healthy, eligible seat with `kind == "native"` for this task?", returning the
  seat (or `None`). It must apply the same health/exclusion checks
  `_select_retry_seat`'s pool branch applies (`_effective_key`, `tried_seats`,
  `eligible_labels`, `pool._busy_seats`, `pool._initial_exclusions`,
  `pool._local_exclusions`, `pool._seat_views` availability/suspension/probe).
- Add a native **reservation for attempt 2**: allocate the sub-worktree, branch
  and `attempt_uid` for a native retry, and admit the native seat's identity
  through the execution pool BEFORE the worktree is created. Reuse an existing
  reservation for the same `(execution, task)` rather than admitting twice —
  mirror `prepare_native`'s duplicate-call behaviour.
- Wire it into `_run_task`'s retry branch: only after `_select_retry_seat`
  returned `None` and `eligible_labels is not None`, and only when the helper
  finds a seat. Return a `TaskResult` with `outcome="retry_native"` carrying the
  reservation, with attempt 1's `AttemptRecord` preserved and its `failed`
  outcome emitted exactly once — the same single-emission discipline the
  existing MCP retry path uses.
- Add the reservation field to `TaskResult`.
- Module 2: when the remaining eligible-untried set is non-empty but all-native
  **and** no handoff could be offered, replace the generic "no eligible retry
  seat" text with one naming the MCP-only retry ladder. Keep the
  `complex_model_unavailable` code and keep appending attempt 1's own error.
- Regression tests in `TestComplexityDispatchAdmission`.

**NOT in scope**:
- Deleting either `kind == "native"` guard (spec NG1). `_select_retry_seat` and
  `ChunkAssigner.retry_seat` must keep returning MCP seats only; the handoff is
  a *separate* return path. Re-introducing the TASK-3554 crash is this task's
  single biggest risk.
- The legacy `pool is None` path (spec NG2).
- `sdd-worker`'s routing of the new outcome — TASK-3581.
- The `begin_execution` roster warning — TASK-3582.
- The shipped template roster — TASK-3583.
- Changing `eligible_seats()` or `_eligible_retry_labels` (spec NG3).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Native-retry helper, attempt-2 reservation, `_run_task` wiring, all-native diagnostic |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | `TaskResult.native_retry` field |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | Regression tests in `TestComplexityDispatchAdmission` |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `b366bd774` on 2026-09-21. **The line numbers in
> `issue:569e81756247` are stale** — `engine.py` grew ~600 lines after it was
> filed. Use the numbers below.

### Verified Imports
```python
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py already has:
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat
from parrot.flows.dev_loop.sdd_coder.complexity_models import ComplexityPolicy, StrongModelIdentity
```

### Existing Signatures to Use

```python
# models.py:30-39 — "retry_native" is ALREADY declared. Do not add it, do not rename it.
TaskOutcome = Literal[
    "queued", "running", "merged", "merge_conflict", "failed",
    "fidelity_violation", "retry_native", "not_dispatched",
]

# models.py:344
class TaskResult(BaseModel):
    task_id: str
    outcome: TaskOutcome
    branch: str = ""
    worktree_path: str = ""
    attempts: List[AttemptRecord] = Field(default_factory=list)
    conflict_files: List[str] = Field(default_factory=list)
    unexpected_files: List[str] = Field(default_factory=list)
    diagnostics: str = ""
    development_output: Optional[DevelopmentOutput] = None   # :355
    lint: Optional[LintReport] = None                         # :356

# models.py:360
class NativePrep(BaseModel):
    task_id: str
    task_file: str
    branch: str
    worktree_path: str
    seat_label: str
    model: str = "haiku"
    attempt_uid: str = ""
    coder_feedback: str = ""
    assessment_id: str = ""
    execution_id: str = ""
    bg_handle: Optional[str] = None

# engine.py:3059 — returns MCP seats ONLY; native guard at :3105-3110 (search loop)
#                  and :3136 (busy-wait loop). BOTH STAY.
async def _select_retry_seat(
    self, pool: Optional["ExecutionPool"], failed_label: str, tried_seats: set[str],
    *, eligible_labels: Optional[Set[str]] = None,
) -> Optional[RosterSeat]: ...

# engine.py:1659 — fail-closed on a missing assessment (TASK-3554). DO NOT CHANGE.
async def _eligible_retry_labels(
    self, ctx: _FeatureCtx, task: PlannedTask, *, execution_id: Optional[str] = None
) -> Optional[Set[str]]: ...

# engine.py:1745 — the attempt-1 native path. Raises task_not_in_plan when
# `not planned.native` (:1762-1764) — a retried task was planned onto an MCP
# seat, so this method CANNOT be called as-is for attempt 2.
async def prepare_native(
    self, feature: str, worktree: str, task_id: str, execution_id: Optional[str] = None
) -> NativePrep: ...

# engine.py:2590 — the crash site TASK-3554 fixed. A native seat must NEVER reach it.
assert seat.backend is not None, "_run_attempt is only called for mcp seats; native tasks use prepare_native"

# roster.py:241 — strong-model filter; backend is "native" for kind="native" seats (:277)
def eligible_seats(
    assessment: ComplexityAssessment, seats: List[RosterSeat], policy: ComplexityPolicy
) -> List[RosterSeat]: ...
```

### `_run_task`'s retry branch as it stands (engine.py:3217-3253)
```python
eligible_labels = await self._eligible_retry_labels(ctx, task, execution_id=execution_id)   # :3221
retry = await self._select_retry_seat(pool, seat.label, tried_seats, eligible_labels=eligible_labels)  # :3225
if retry is None and eligible_labels is not None:                                            # :3226
    no_retry_error = f"complex_model_unavailable: no eligible retry seat for {task.task_id}"  # :3233
    rec = rec.model_copy(update={"error": f"{rec.error}\n{no_retry_error}" if rec.error else no_retry_error})
    attempts[-1] = rec
    err = rec.error
if retry is not None:                                                                        # :3237
    tried_seats.add(retry.label)
    await self._emit_outcome(ctx, attempt_rec=rec, task_id=task.task_id, outcome="failed")
    rec, out, err, manager, branch, path = await self._run_attempt(
        ctx, task, retry, attempt=2, job_id=job_id, execution_id=execution_id, pool=pool
    )
    attempts.append(rec)
```

### Does NOT Exist
- ~~`TaskOutcome.retry_native` as a *new* member~~ — it is already at `models.py:37`. Adding it again is a bug.
- ~~a producer, consumer or test for `retry_native`~~ — `models.py:37` is its ONLY occurrence under `packages/`. There is no prior art to copy; this task creates the first one.
- ~~`TaskResult.native_prep`~~ / ~~`TaskResult.handoff`~~ — no such field today; you are adding it (name it `native_retry`).
- ~~`ExecutionPool.reserve_native()`~~ — no such method. Reservation logic lives in `prepare_native` (`engine.py:1745`) and must be factored or parameterized, not invented.
- ~~`prepare_native(..., attempt=2)`~~ — the parameter does not exist today.
- ~~`packages/ai-parrot/build/...`~~ — a stale pre-FEAT-587 copy of `engine.py`. Never read or edit it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._select_retry_seat",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_task",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.prepare_native",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._eligible_retry_labels",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#TaskResult",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#NativePrep",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#eligible_seats"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Never hand a `kind == "native"` seat to `_run_attempt`.** Its first line is
  an `assert seat.backend is not None` that raises *outside* the function's own
  `try:`, so nothing catches it; `run_chunk`'s outer
  `asyncio.gather(..., return_exceptions=True)` then converts it into a bare
  `TaskResult` that discards attempt 1's record entirely. That is the exact
  TASK-3554 crash.
- `_run_task` returns **exactly one** `TaskResult`. The existing code emits
  attempt 1's `failed` outcome before running an MCP retry precisely so both
  attempts get an outcome row. The native path must emit attempt 1's outcome
  the same way, exactly once, and must not also fall through to the
  single-emission at the end.
- Async throughout; `self.logger`, never `print`.
- Pool bookkeeping: admit before creating the worktree, and reuse an existing
  reservation for a repeated `(execution, task)` rather than admitting twice.

### References in Codebase
- `engine.py:1745` `prepare_native` — the reservation/admission pattern to mirror.
- `roster.py:386` `ChunkAssigner.retry_seat` — the guard whose rationale must stay true.
- `test_engine_dispatch.py::TestComplexityDispatchAdmission::test_no_eligible_retry_seat_reports_complex_model_unavailable` — the sibling test to model the new ones on.

---

## Implementation Blueprint

### Steps (in order)
1. Add `TaskResult.native_retry` to `models.py` — *why*: the engine needs a
   typed channel for the reservation; `retry_native` already exists as the
   outcome, only the payload is missing.
2. Add `_select_native_retry_seat()` to `engine.py` — *why*: keeping it separate
   from `_select_retry_seat` is what preserves NG1; the MCP selector's contract
   (returns only dispatchable seats) stays exactly as TASK-3554 left it.
3. Add the attempt-2 native reservation — *why*: `prepare_native` refuses a task
   whose `planned.native` is `False`, which is every retried task, so its
   worktree/branch/attempt-uid allocation must be reachable without that
   precondition.
4. Wire both into `_run_task`'s retry branch, after `_select_retry_seat`
   returned `None` — *why*: the native handoff is the *last* resort, never
   preferred over a real MCP retry.
5. Replace the generic no-retry message when the remainder is all-native —
   *why*: today's text sends operators hunting a scheduling race that cannot
   happen (the busy-wait loop applies the same native filter, so it never waits).
6. Write the regression tests — *why*: AC-4 must fail loudly if anyone later
   "simplifies" the guards away.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'lint: Optional[LintReport] = None' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py)
# AFTER — insert below `    lint: Optional[LintReport] = None` (verified: models.py:356)
    native_retry: Optional["NativePrep"] = None
    """FEAT-588: set only with `outcome="retry_native"` — the attempt-2 reservation
    `sdd-worker` must run on a native seat itself (the engine has no dispatcher for
    one). `None` for every other outcome."""
```
**Why**: `TaskResult` is the only channel from `_run_task` back to the
orchestrator, and `NativePrep` already carries exactly the fields a native
attempt needs (branch, worktree, `attempt_uid`, `assessment_id`,
`execution_id`). `NativePrep` is declared *after* `TaskResult` in this module,
hence the forward reference in quotes — do not reorder the classes.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY — helper)
```python
# occurrences: 1 (verified: grep -c -F 'async def _select_retry_seat(' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py)
# BEFORE — insert above `    async def _select_retry_seat(` (verified: engine.py:3059)
    async def _select_native_retry_seat(
        self,
        pool: Optional["ExecutionPool"],
        tried_seats: set[str],
        *,
        eligible_labels: Optional[Set[str]] = None,
    ) -> Optional[RosterSeat]:
        """An untried, healthy, eligible `kind == "native"` seat, or `None` (FEAT-588).

        Deliberately separate from `_select_retry_seat`, which returns MCP seats
        ONLY and must keep doing so: a native seat has no dispatcher, so handing
        one to `_run_attempt` hits its `assert seat.backend is not None`
        (engine.py:2590) instead of retrying — the TASK-3554 crash. The caller
        routes this seat to a `retry_native` handoff, never to `_run_attempt`.

        Args:
            pool: The execution pool; `None` (legacy path) always yields `None`.
            tried_seats: Seat labels already attempted for this task.
            eligible_labels: Strong-model restriction from `_eligible_retry_labels`.

        Returns:
            A healthy native `RosterSeat`, or `None` when there is none.
        """
        if pool is None:
            # Legacy path has no handoff channel (spec NG2).
            return None
        # FILL IN: mirror `_select_retry_seat`'s pool-branch filters, INVERTED on
        # kind (`seat.kind != "native"` -> continue) — bounded by AC-1/AC-4 and
        # by the filter list in this task's Scope. Do NOT wait on the pool
        # condition: a busy native seat is not worth blocking the chunk for.
        raise NotImplementedError
```
**Why this shape**: the inverted-kind twin of the MCP selector, with the same
health/exclusion filters, so a suspended or excluded native seat is never
offered. It never waits — the MCP selector's busy-wait exists because another
MCP attempt can free a seat; a native seat is run by `sdd-worker`, outside this
engine's scheduling.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY — `_run_task` wiring)
```python
# occurrences: 1 (verified: grep -c -F 'no_retry_error = f"complex_model_unavailable' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py)
# REPLACE the body of `if retry is None and eligible_labels is not None:` (verified: engine.py:3226-3236)
# NOTE: the anchor `if retry is not None:` appears TWICE (engine.py:3237 and a
# comment at :3257) — anchor on the `no_retry_error = ` line above instead.
            if retry is None and eligible_labels is not None:
                native_retry_seat = await self._select_native_retry_seat(
                    pool, tried_seats, eligible_labels=eligible_labels
                )
                if native_retry_seat is not None:
                    # FILL IN: build the attempt-2 native reservation, emit attempt 1's
                    # `failed` outcome EXACTLY ONCE (mirroring the MCP branch below),
                    # and return a TaskResult(outcome="retry_native", native_retry=<prep>)
                    # with `attempts` carrying attempt 1 — bounded by AC-1/AC-2/AC-3.
                    raise NotImplementedError
                # FILL IN: when the eligible-untried remainder is non-empty and
                # ALL native, use a message naming the MCP-only retry ladder;
                # otherwise keep today's text. Keep the `complex_model_unavailable:`
                # prefix either way — callers match on it — bounded by AC-6.
                no_retry_error = f"complex_model_unavailable: no eligible retry seat for {task.task_id}"
                rec = rec.model_copy(
                    update={"error": f"{rec.error}\n{no_retry_error}" if rec.error else no_retry_error}
                )
                attempts[-1] = rec
                err = rec.error
```
**Why**: the handoff is attempted only after the MCP selector came back empty,
so a real MCP retry is always preferred. Keeping the `complex_model_unavailable:`
prefix preserves every existing caller's matching while making the text honest.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'class TestComplexityDispatchAdmission' packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py)
# AFTER — add these methods inside `class TestComplexityDispatchAdmission`
    async def test_all_native_remainder_hands_off_instead_of_blocking(self) -> None:
        """FEAT-588 AC-1/AC-2/AC-3: the shipped roster shape retries onto native."""
        # FILL IN: roster = 1 MCP strong seat + 1 native strong seat, both in
        # complexity.strong_models; force classification "complex"; fail attempt 1
        # on the MCP seat. Assert outcome == "retry_native", native_retry is not
        # None and carries seat_label/assessment_id/execution_id, and
        # attempts[0] is attempt 1's record — bounded by AC-1/AC-2/AC-3.
        raise NotImplementedError

    async def test_run_attempt_never_receives_a_native_seat(self) -> None:
        """FEAT-588 AC-4 / TASK-3554 regression: the two guards must stay."""
        # FILL IN: assert `_select_retry_seat` and `ChunkAssigner.retry_seat` both
        # return None (never the native seat) for the roster above, and that no
        # `_run_attempt` call in the handoff scenario received a seat whose
        # kind == "native" — bounded by AC-4.
        raise NotImplementedError

    async def test_no_eligible_seat_of_any_kind_is_unchanged(self) -> None:
        """FEAT-588 AC-5: with no native seat either, behaviour is exactly as before."""
        # FILL IN: roster = 1 MCP strong seat only. Assert complex_model_unavailable,
        # attempt 1 preserved, no exception — bounded by AC-5.
        raise NotImplementedError
```
**Why**: AC-4's test is the guard on the guard — it must fail if a future change
lets a native seat reach `_run_attempt`. Model the fixtures on the existing
`test_no_eligible_retry_seat_reports_complex_model_unavailable` in this class.

### FILL IN checklist
- [ ] `_select_native_retry_seat` filter body (mirrors `_select_retry_seat`, inverted kind, no waiting)
- [ ] attempt-2 native reservation (admit → worktree → branch → `attempt_uid`; reuse on repeat)
- [ ] `retry_native` return path in `_run_task`, attempt 1 emitted exactly once
- [ ] all-native vs. genuinely-empty diagnostic branch
- [ ] three test bodies

---

## Acceptance Criteria

- [ ] AC-1 — complex/unknown task, MCP strong seat fails attempt 1, healthy untried native strong seat present → `outcome == "retry_native"`, not `complex_model_unavailable`.
- [ ] AC-2 — the handoff carries attempt-2 branch/worktree, `seat_label`, `assessment_id`, `execution_id`.
- [ ] AC-3 — attempt 1's `AttemptRecord` is in `TaskResult.attempts`; its `failed` outcome is emitted exactly once.
- [ ] AC-4 — `_run_attempt` never receives a `kind == "native"` seat; both existing guards still return MCP-only.
- [ ] AC-5 — no eligible untried seat of any kind → unchanged `complex_model_unavailable`, attempt 1 preserved, no crash.
- [ ] AC-6 — all-native remainder with no handoff → diagnostic names the MCP-only ladder; code stays `complex_model_unavailable`.
- [ ] AC-9 — the legacy (`pool is None`) path is unchanged.
- [ ] `ruff check` and `black --check` clean on all three files.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_integration_chunk.py -q`

---

## Output

### Completion Note
(Agent fills this in when done)
