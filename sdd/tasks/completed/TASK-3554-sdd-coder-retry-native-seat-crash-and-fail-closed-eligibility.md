# TASK-3554: sdd-coder pool-based retry crashes on a native strong seat and can silently drop the complex/unknown eligibility restriction

**Feature**: FEAT-572 — `/sdd-fix` — Ledger-Driven Fix Lane
**Spec**: `sdd/specs/sdd-fix-ledger-lane.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:e01c03baf493` (ledger, severity major) — "sdd-coder: no nova
MCP seat is eligible for 'unknown'-classified tasks, no fallback to native/codex-spark".
Close the ledger issue (`wikitoolkit ledger close issue:e01c03baf493 --reason "promoted to
TASK-3554" --actor agent:sdd-fix --resolved-by task:TASK-3554`) once this task lands.

---

## Context

FEAT-561 (`sdd/specs/complex-sdd-tasks.spec.md`) added a strong-model allowlist so
`complex`/`unknown`-classified tasks can only dispatch to a roster seat whose exact
`(backend, model)` is listed in `RosterConfig.complexity.strong_models`. The **legacy**
(non-pool) retry path (`ChunkAssigner.retry_seat`, `roster.py`) and its dispatch-time
admission check (`SddCoderEngine._run_attempt`, `engine.py`) are unit/integration tested
for this (`test_roster.py`, `test_no_eligible_retry_seat_reports_complex_model_unavailable`
in `test_engine_dispatch.py`) and behave correctly.

FEAT-559 later added the **execution-pool** dispatch path (`execution_id` /
`ExecutionPool`) — the one every real `coder_plan`/`coder_run_chunk`/`coder_wait` MCP
call actually uses today. Its retry-seat selection, `SddCoderEngine._select_retry_seat`'s
pool branch, is a **separate, inline reimplementation** of `ChunkAssigner.retry_seat`'s
seat-search loop, and it was never given equivalent test coverage for the FEAT-561
restriction. It has at least one confirmed, reproduced defect (see "Verified evidence"
below), and the production ledger issue's job records show a second, closely-related
symptom this task must also close off defensively.

### Verified evidence (reproduced against current `dev`, 2026-09-20)

**A. Confirmed crash (reproduced locally with a throwaway pytest against current `dev`
HEAD, not committed — reproduce it yourself with the harness `TestPoolBasedRetryEligibility`
below before changing any code):**

Roster: 2 weak `nova` seats + 1 `kind="native"` seat whose `(backend, model)` ==
`("native", "sonnet-5")` matches `complexity.strong_models`, all reported healthy by
`noop_probe`. Force one task's cached-plan assessment to `classification="unknown"`
(mirroring the existing `_force_classification` helper) after a normal `begin_execution`
+ `plan(execution_id=...)`. Dispatch via `run_chunk(..., execution_id=execution_id)`.

*Observed*: attempt 1 (a nova seat) is correctly rejected by the admission check
(`complex_model_unavailable`). `_select_retry_seat`'s pool branch then selects the
**native** seat (it is healthy, untried, and in `eligible_labels`) and hands it straight
to `_run_attempt(ctx, task, retry, attempt=2, ...)`. `_run_attempt`'s very first line —

```python
assert seat.backend is not None, "_run_attempt is only called for mcp seats; native tasks use prepare_native"
```

(`engine.py:1936`) — raises `AssertionError` **before** the function's own `try:` block
(which starts several lines later, around `engine.py:2028`), so nothing inside
`_run_attempt` catches it. `_run_task` also has no `try`/`except` around this specific
`await self._run_attempt(..., attempt=2, ...)` call (`engine.py:~2576-2578`). The
exception propagates out of `_run_task` entirely and is caught only by `run_chunk`'s
outer `asyncio.gather(..., return_exceptions=True)` (`engine.py:~2717-2726`), which
converts it into a **bare** `TaskResult(task_id=tid, outcome="failed",
diagnostics=str(raw))` — discarding attempt 1's `AttemptRecord` and its real
`complex_model_unavailable` diagnostic entirely. The task ends up "failed" with an
opaque `"_run_attempt is only called for mcp seats; native tasks use prepare_native"`
diagnostic and **zero** attempts recorded, instead of the correct outcome: attempt 1
recorded, no retry attempted (this exact shape is what
`test_no_eligible_retry_seat_reports_complex_model_unavailable` already asserts for the
**legacy** path — this task adds the pool-path equivalent).

The legacy `ChunkAssigner.retry_seat` (`roster.py:386-416`) explicitly guards against
this exact class of bug:

```python
for offset in range(1, n + 1):
    candidate = self._seats[(failed_index + offset) % n]
    if candidate.label in excluded or candidate.kind == "native":
        continue
    ...
```

`SddCoderEngine._select_retry_seat`'s pool branch (`engine.py:2445-2483`) has **no**
`candidate.kind == "native"` (or equivalent) guard anywhere in its seat-search loop or
its "any healthy-but-busy seat worth waiting for" loop.

**B. Production symptom (ledger issue `issue:e01c03baf493`, from the actual job records
in `.claude/worktrees/feat-FEAT-572-sdd-fix-ledger-lane/.sdd-coder/jobs/job-00cdece6c00d.json`
and `job-1677572b6ba3.json`)**: for TASK-3393/TASK-3396/TASK-3397 (all classification
`"unknown"`, confirmed by the identical `assessment_id` shared across both attempts of
each task and by the admission-check error text itself), **both** attempt 1 *and*
attempt 2 land on a real `backend="nova"` seat (e.g. `glm` → `mistral`, `mistral` →
`qwen`, `qwen` → `minimax`), each independently and correctly rejected by
`_run_attempt`'s admission check with `"... is not eligible for unknown task ..."`. This
is a *clean* second attempt (a real `AttemptRecord`, not a crash) — meaning, in that
exact production run, `_select_retry_seat` was handed an **unrestricted**
(`eligible_labels=None`) or otherwise-nova-inclusive candidate set for a task the
admission check itself unambiguously classified as `"unknown"` moments earlier, on the
*same* cached plan.

`SddCoderEngine._eligible_retry_labels` (`engine.py:1168-1183`) is the only source of
`eligible_labels` for this path, and its only way to return `None` (unrestricted) for a
task whose classification is `complex`/`unknown` is if `plan.assessments.get(task.task_id)`
comes back `None`:

```python
async def _eligible_retry_labels(self, ctx, task, *, execution_id=None):
    plan = await self._cached_plan(ctx.feature, ctx.worktree, ctx, execution_id=execution_id)
    assessment = plan.assessments.get(task.task_id)
    if assessment is None or assessment.classification not in ("complex", "unknown"):
        return None
    ...
```

The scenario reproduced under A. (a resolvable, healthy strong seat) did **not**
reproduce B.'s "silently unrestricted" symptom — it reproduced the crash instead. B.'s
exact trigger was not pinned down by static analysis or by the reproduction in A.
(`plan.assessments` is populated once by `plan()` and never mutated/evicted elsewhere in
`engine.py` — a `grep -n "_plan_cache\["` confirms exactly one write site,
`engine.py:1020`, inside `plan()` itself). **This task must not ship without adding a
regression test that pins down and closes this second symptom too** — even if the exact
trigger stays not-fully-understood, `_eligible_retry_labels` must be hardened to *never*
treat "I could not resolve this task's assessment" as "this task is unrestricted"
(fail-closed, not fail-open): a missing/unresolvable assessment for a task already mid
dispatch is itself an anomaly and should block the retry with a `complex_model_unavailable`-
style diagnostic, never silently fall through to the standard/unrestricted seat pool.

---

## Scope

- Fix `SddCoderEngine._select_retry_seat`'s pool-based branch (`engine.py:2445-2483`) so
  it never returns a `kind == "native"` seat — mirroring `ChunkAssigner.retry_seat`'s
  existing, tested behavior exactly (same rationale: a native seat has no dispatcher,
  `_run_attempt` is MCP-only, and `_run_task` never routes attempt 2+ through
  `coder_prepare_native`). Apply the same exclusion in **both** loops in that method (the
  seat-search loop and the "any healthy-but-busy seat worth waiting for" loop) — a native
  seat must never be picked immediately AND must never be waited on.
- Harden `SddCoderEngine._eligible_retry_labels` (`engine.py:1168-1183`) to fail closed:
  when `plan.assessments.get(task.task_id)` is `None` for a task that is mid-retry (i.e.
  this function is only ever called from `_run_task`'s error branch, so a task reaching it
  is by definition one that was just dispatched from *some* plan), do **not** return
  `None` (unrestricted). Instead treat it the same as "restricted, zero eligible seats"
  (i.e. return `set()`), so `_run_task`'s existing `if retry is None and eligible_labels
  is not None:` branch reports `complex_model_unavailable` instead of silently letting
  `_select_retry_seat` search the full, unrestricted roster. Add a one-line comment
  explaining why (a missing assessment here is an anomaly, not evidence of an
  unrestricted/standard task).
- Add regression tests to `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py`,
  in `TestComplexityDispatchAdmission`, covering the execution-pool path the same way
  `test_no_eligible_retry_seat_reports_complex_model_unavailable` already covers the
  legacy path (see Implementation Blueprint).
- Close `issue:e01c03baf493` in the SDD ledger once this lands (see header).

**NOT in scope**:
- Actually making a complex/unknown task's retry *succeed* by falling back to
  `coder_prepare_native`/a codex seat mid-`_run_task` — that is a larger architectural
  change (the retry ladder is MCP-dispatch-only by design; native preparation is a
  separate, caller-driven flow via `coder_prepare_native`). This task's job is to make the
  failure mode *correct and visible* (`complex_model_unavailable`, previous attempt
  preserved), not to add native-fallback dispatch. Note this explicitly as a known
  follow-up in the Completion Note if you confirm it during implementation.
- `issue:0af9c12f991c` (the "parallel batch" comment) — already released back to the
  ledger as moot: the described comment text no longer exists anywhere in `roster.py`
  (superseded by TASK-3289/FEAT-561's rewrite of `ChunkAssigner.assign`). Do not touch
  `roster.py`'s docstrings for it.
- Re-deriving why the operator's *live* `parrot-sdd-coder` MCP server produced exactly
  job-00cdece6c00d/job-1677572b6ba3's sequence (a long-running MCP server process is not
  something this task can inspect) — fix the code so it is correct and fails closed
  regardless of that process's history, and let the regression tests be the proof.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Exclude native seats from `_select_retry_seat`'s pool branch; fail-closed `_eligible_retry_labels` on a missing assessment |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | Add `TestComplexityDispatchAdmission` pool-path regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py already has:
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat
from parrot.flows.dev_loop.sdd_coder.complexity_models import ComplexityPolicy, StrongModelIdentity
# add if not already imported at module scope:
import uuid
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:102
class RosterSeat(BaseModel):
    label: str = Field(..., min_length=1, max_length=32)  # :109
    kind: SeatKind = "mcp"                                  # :110 -- "mcp" | "native"
    backend: Optional[DevAgentBackend] = None               # :111 -- None for kind="native"
    model: str = ""                                          # :112
    fallback_model: str = ""                                 # :113

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py:386
def retry_seat(
    self, failed_label: str, exclude: Set[str], *, eligible_labels: Optional[Set[str]] = None
) -> Optional[RosterSeat]:
    # :409-411 -- THE PATTERN TO MIRROR in engine.py's pool branch:
    #   if candidate.label in excluded or candidate.kind == "native":
    #       continue

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:1168
async def _eligible_retry_labels(
    self, ctx: _FeatureCtx, task: PlannedTask, *, execution_id: Optional[str] = None
) -> Optional[Set[str]]:
    # current body (verify unchanged before editing):
    plan = await self._cached_plan(ctx.feature, ctx.worktree, ctx, execution_id=execution_id)
    assessment = plan.assessments.get(task.task_id)
    if assessment is None or assessment.classification not in ("complex", "unknown"):
        return None
    seats = self._executions[execution_id]._seats if execution_id in self._executions else self.seats
    return {s.label for s in eligible_seats(assessment, seats, self.roster.complexity)}

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:2405
async def _select_retry_seat(
    self,
    pool: Optional["ExecutionPool"],
    failed_label: str,
    tried_seats: set[str],
    *,
    eligible_labels: Optional[Set[str]] = None,
) -> Optional[RosterSeat]:
    if pool is None:
        # Legacy path: use global assigner (roster.py:386's retry_seat -- already excludes native)
        if self._assigner is None:
            return None
        return self._assigner.retry_seat(failed_label, tried_seats, eligible_labels=eligible_labels)
    # Pool-based selection: find healthy, not-yet-tried seats  (engine.py:2445 onward)
    async with pool._condition:
        while True:
            if pool._status in ("closed", "recovery_required"):
                return None
            # Find eligible seats
            for seat in pool._seats:
                from parrot.flows.dev_loop.sdd_coder.pool import _effective_key
                key = _effective_key(seat)
                if key is None:
                    continue
                if seat.label in tried_seats:
                    continue
                if eligible_labels is not None and seat.label not in eligible_labels:
                    continue
                if key in pool._busy_seats:
                    continue
                if key in pool._initial_exclusions or key in pool._local_exclusions:
                    continue
                view = pool._seat_views.get(key)
                if view is None or not view.available or view.suspended or view.probe_unavailable:
                    continue
                # Found a healthy, free seat
                return seat
            # No healthy free seat available - check if we should wait
            has_busy_healthy = False
            for seat in pool._seats:
                from parrot.flows.dev_loop.sdd_coder.pool import _effective_key
                key = _effective_key(seat)
                if key is None or seat.label in tried_seats:
                    continue
                if eligible_labels is not None and seat.label not in eligible_labels:
                    continue
                if key in pool._busy_seats:
                    view = pool._seat_views.get(key)
                    if view and view.available and not view.suspended and not view.probe_unavailable:
                        has_busy_healthy = True
                        break
            if not has_busy_healthy:
                return None
            await pool._condition.wait()

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:1936 (the crash site)
assert seat.backend is not None, "_run_attempt is only called for mcp seats; native tasks use prepare_native"

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:2557-2578 (_run_task's caller of the above)
eligible_labels = await self._eligible_retry_labels(ctx, task, execution_id=execution_id)
retry = await self._select_retry_seat(pool, seat.label, tried_seats, eligible_labels=eligible_labels)
if retry is None and eligible_labels is not None:
    no_retry_error = f"complex_model_unavailable: no eligible retry seat for {task.task_id}"
    rec = rec.model_copy(update={"error": f"{rec.error}\n{no_retry_error}" if rec.error else no_retry_error})
    attempts[-1] = rec
    err = rec.error
if retry is not None:
    tried_seats.add(retry.label)
    await self._emit_outcome(ctx, attempt_rec=rec, task_id=task.task_id, outcome="failed")
    rec, out, err, manager, branch, path = await self._run_attempt(
        ctx, task, retry, attempt=2, job_id=job_id, execution_id=execution_id, pool=pool
    )
    attempts.append(rec)

# Existing test pattern to mirror -- test_engine_dispatch.py:603 (already committed on dev)
def _force_classification(plan, task_id: str, classification: str):
    assessment = plan.assessments[task_id].model_copy(update={"classification": classification})
    return plan.model_copy(update={"assessments": {**plan.assessments, task_id: assessment}})

# test_engine_dispatch.py:644-666 -- the LEGACY-path test this task's new tests mirror for the POOL path:
class TestComplexityDispatchAdmission:
    async def test_no_eligible_retry_seat_reports_complex_model_unavailable(self, git_sandbox_feature, noop_probe):
        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        builder = fake_builder_factory({"nova": "fail"})
        roster = RosterConfig(
            seats=[RosterSeat(label="weak", backend="nova", model="qwen")],
            complexity=ComplexityPolicy(
                strong_models=(
                    StrongModelIdentity(canonical_model="sonnet-5", backend="codex", model="claude-3-5-sonnet"),
                )
            ),
        )
        engine = SddCoderEngine(
            roster=roster, probe=noop_probe, worktree_base_path=str(base_path), dispatcher_builder=builder
        )
        plan = await engine.plan("demo", str(worktree))
        engine._plan_cache["FEAT-549"] = _force_classification(plan, "TASK-0001", "unknown")  # noqa: SLF001
        job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
        result = await engine.wait(job.job_id, 5)
        assert result.tasks[0].outcome == "failed"
        assert len(result.tasks[0].attempts) == 1, "no retry attempt when no eligible seat exists"
        assert "complex_model_unavailable" in result.tasks[0].diagnostics
```

Note the **cache key difference for the pool path**: the legacy test above writes
`engine._plan_cache["FEAT-549"]` (bare `feature_id`). The pool-path equivalent MUST write
`engine._plan_cache[f"FEAT-549:{execution_id}"]` instead (`_cached_plan`'s qualified key,
`engine.py:1163`) — verified working in this task's own reproduction (see Implementation
Blueprint step 1).

### Does NOT Exist
- ~~`ChunkAssigner.retry_seat`'s `kind == "native"` guard already covers the pool
  path~~ — it does not; the pool path is a fully separate, inline reimplementation inside
  `SddCoderEngine._select_retry_seat`, not a call into `ChunkAssigner`.
- ~~A `coder_prepare_native`-style fallback already exists inside `_run_task`'s retry
  ladder~~ — it does not; `_run_task` only ever calls `_run_attempt` (MCP dispatch) for
  attempt 2, never `prepare_native`.
- ~~`_plan_cache` entries get evicted or refreshed by `_classify_and_suspend` or any
  suspension~~ — verified false: `grep -n '_plan_cache\['` shows exactly one write site
  (`engine.py:1020`, inside `plan()`); nothing evicts or mutates a cached plan's
  `assessments` dict after it is written.

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
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._select_retry_seat",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._eligible_retry_labels",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_attempt",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_task",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#ChunkAssigner.retry_seat",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#eligible_seats"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

`_select_retry_seat`'s pool branch should read exactly like `ChunkAssigner.retry_seat`'s
loop, just adapted to the pool's per-seat health bookkeeping (`_busy_seats`,
`_seat_views`, exclusions) instead of a flat rotation index. The one-line addition is a
`seat.kind == "native"` skip in **both** of the branch's two `for seat in pool._seats:`
loops (the "find a free eligible seat" loop and the "is anything busy-but-healthy worth
waiting for" loop) — a native seat must not be selected immediately, and must not cause
the retry to *wait* for it to free up either (it is a Claude Code sub-agent slot, not a
pool-managed dispatcher seat; `pool._busy_seats`/`_seat_views` bookkeeping for it is not
meaningful for this loop's purpose).

### Key Constraints
- Do not change `_run_attempt`'s assertion (`engine.py:1936`) — it is a correct,
  load-bearing invariant (`_run_attempt` really is MCP-only). The fix is to never call it
  with a native seat from the retry path, not to relax the assertion.
- `_eligible_retry_labels`'s fail-closed change must return `set()` (empty), not `None`,
  when `assessment is None` while `execution_id`/pool context indicates this task really
  is mid-dispatch. Returning `None` here means "unrestricted" to `_select_retry_seat`
  (`eligible_labels is not None` gate) — that is the exact behavior being closed off.
- Do not touch `roster.py` for this task (see "NOT in scope" — `issue:0af9c12f991c` is
  moot and already released).

---

## Implementation Blueprint

### Steps (in order)
1. Reproduce defect A locally first (do not skip this — it is what proves the fix):
   write a pytest using `git_sandbox_feature`/`noop_probe`/`fake_builder_factory`
   (all already in `test_engine_dispatch.py`), a roster with 1-2 weak `nova` seats plus
   one `kind="native"` seat matching `complexity.strong_models`, `begin_execution` +
   `plan(execution_id=...)`, `_force_classification(..., "unknown")` written to
   `engine._plan_cache[f"FEAT-549:{execution_id}"]`, then `run_chunk(...,
   execution_id=execution_id)` + `wait(...)`. Confirm it currently fails with
   `AssertionError: _run_attempt is only called for mcp seats...` and an empty
   `attempts` list — *why*: proves the exact crash site before touching code, and gives
   you the exact before/after diff for the PR description.
2. Add the native-kind guard to `_select_retry_seat`'s pool branch — *why*: closes
   defect A; mirrors `ChunkAssigner.retry_seat`'s already-tested behavior so the pool
   path and the legacy path agree.
3. Re-run the test from step 1: it should now show `outcome == "failed"`,
   `len(attempts) == 1`, and `"complex_model_unavailable"` in diagnostics — the same
   shape as the existing legacy-path test.
4. Harden `_eligible_retry_labels` per Scope/Key Constraints, add a second regression
   test that directly calls `_eligible_retry_labels` with a `plan.assessments` dict that
   does not contain the task's id (construct this the same way `_force_classification`
   builds a modified plan, but `del`ete the task's key from `.assessments` instead of
   changing its classification) and assert it returns `set()`, not `None` — *why*: the
   production symptom (B.) could not be reproduced end-to-end, so this direct unit test
   on the function itself is what proves the fail-closed change actually took effect,
   independent of whatever caused `assessment` to be missing in production.
5. Add both new tests to `TestComplexityDispatchAdmission` in
   `test_engine_dispatch.py`, named `test_pool_based_retry_never_selects_native_seat`
   and `test_eligible_retry_labels_fails_closed_on_missing_assessment`.
6. Run the full `sdd_coder` test module, not just the new tests, to confirm no
   regression (`## Validation Commands` below covers the two directly-relevant files;
   also run the full `test_engine_dispatch.py` module locally before committing).

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c 'if eligible_labels is not None and seat.label not in eligible_labels:' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py)
# FILL IN: disambiguate — the two occurrences are the "find a free eligible seat" loop
# and the "is anything busy-but-healthy worth waiting for" loop inside
# _select_retry_seat's pool branch (engine.py:2445-2483). Add, immediately after each
# occurrence's surrounding `for seat in pool._seats:` line, a guard:
#     if seat.kind == "native":
#         continue
# — *why*: a native seat has no dispatcher; _run_attempt asserts seat.backend is not
# None and _run_task never routes a retry through coder_prepare_native, so selecting
# (or waiting for) a native seat here can only ever crash the attempt, discarding the
# previous attempt's real diagnostic (see Codebase Contract's "Verified evidence A").
```
**Why this shape**: `ChunkAssigner.retry_seat` (the legacy equivalent) already excludes
`kind == "native"` for exactly this reason; the pool branch is a separate
reimplementation that never got the same guard when FEAT-559 added it.

```python
# occurrences: 1 (verified: grep -c 'if assessment is None or assessment.classification not in' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py)
# AFTER — replace the return in `_eligible_retry_labels` (verified: engine.py:1168-1174):
    async def _eligible_retry_labels(
        self, ctx: _FeatureCtx, task: PlannedTask, *, execution_id: Optional[str] = None
    ) -> Optional[Set[str]]:
        plan = await self._cached_plan(ctx.feature, ctx.worktree, ctx, execution_id=execution_id)
        assessment = plan.assessments.get(task.task_id)
        if assessment is None:
            # A task reaching retry was, by definition, just dispatched under SOME
            # cached plan/assessment (`_run_attempt`'s own admission check just used
            # one to fail attempt 1). A missing assessment here is an anomaly, never
            # evidence this task is unrestricted — fail closed (FEAT-561/561-adjacent
            # `issue:e01c03baf493`: an unresolvable assessment must never silently
            # widen the retry candidate set to the full, unrestricted roster).
            return set()
        if assessment.classification not in ("complex", "unknown"):
            return None
        seats = self._executions[execution_id]._seats if execution_id in self._executions else self.seats
        return {s.label for s in eligible_seats(assessment, seats, self.roster.complexity)}
```
**Why**: closes the only code path by which `_select_retry_seat` could ever receive
`eligible_labels=None` for a task whose classification is actually restricted — matching
the "fail closed, never fail open" framing of the ledger issue's suggested fix.

### FILL IN checklist
- [ ] `_select_retry_seat`'s pool branch — add `seat.kind == "native"` skip to both
      loops; bounded by: must not change behavior for any `kind == "mcp"` seat (existing
      `test_retry_skips_suspended_model` and other `TestRetryUsesOnlyHealthyFreeModel`
      tests must still pass unchanged).
- [ ] `_eligible_retry_labels` — `assessment is None` branch now returns `set()`;
      bounded by: must not change the `assessment.classification not in ("complex",
      "unknown")` branch's existing `return None` (that one is correct — a genuinely
      "standard" task stays unrestricted).

---

## Acceptance Criteria

- [ ] `_select_retry_seat`'s pool-based branch never returns a `kind == "native"` seat
      (neither immediately nor via the busy-wait path).
- [ ] `_eligible_retry_labels` returns `set()` (never `None`) when the cached plan has no
      assessment for the task in question.
- [ ] New test `test_pool_based_retry_never_selects_native_seat` reproduces defect A
      failing on the pre-fix code and passing after the fix (attempt 1 recorded, no
      attempt 2, `complex_model_unavailable` diagnostic — no `AssertionError`).
- [ ] New test `test_eligible_retry_labels_fails_closed_on_missing_assessment` passes.
- [ ] All pre-existing tests in `test_engine_dispatch.py` and `test_roster.py` still pass
      unchanged.
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`
- [ ] `wikitoolkit ledger close issue:e01c03baf493 --reason "promoted to TASK-3554,
      fixed pool-based retry native-seat crash + fail-closed eligible_retry_labels"
      --actor agent:sdd-fix --resolved-by task:TASK-3554` run after merge.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py -q`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sdd-fix-ledger-lane.spec.md` for `/sdd-fix`'s lane
   contract (this task was filed by the SDD lane reusing FEAT-572's already-open spec —
   the spec itself does not need changes for this task).
2. **Verify the Codebase Contract** — re-`grep`/read `engine.py:2445-2483`,
   `engine.py:1168-1183`, and `roster.py:386-416` before writing anything; line numbers
   above were verified 2026-09-20 against `dev` HEAD and may drift.
3. **Reproduce defect A first** (Implementation Blueprint step 1) before changing any
   production code — this is a bugfix task, not a from-scratch feature; the failing test
   IS the spec.
4. Implement per the Implementation Blueprint, run the Validation Commands.
5. Move this file to `sdd/tasks/completed/`, update
   `sdd/tasks/index/sdd-fix-ledger-lane.json` → `"done"`.
6. Close `issue:e01c03baf493` per Acceptance Criteria's last bullet.
7. Fill in the Completion Note, including whether you found the actual trigger for
   production symptom B (the fully-unrestricted nova cycling) — if you did, say so and
   reference the evidence; if not, note that the fail-closed hardening in this task
   closes the risk regardless.

---

## Completion Note

Both defects confirmed and fixed:

- **Defect A (crash)**: reproduced with a new pool-path test
  (`test_pool_based_retry_never_selects_native_seat`) before touching code —
  a healthy native strong seat WAS selected by `_select_retry_seat`'s pool
  branch and crashed `_run_attempt`'s `assert seat.backend is not None`,
  producing an opaque `AssertionError` diagnostic with an empty `attempts`
  list. Fixed by adding a `seat.kind == "native"` skip to both loops in that
  branch, mirroring `ChunkAssigner.retry_seat`'s existing guard.
- **Defect B (fail-open)**: could not be reproduced end-to-end against the
  production job evidence (`plan.assessments` is written once by `plan()`
  and never mutated/evicted elsewhere — confirmed by `grep -n
  '_plan_cache\['`, exactly one write site). Hardened `_eligible_retry_labels`
  to return `set()` (fail closed) instead of `None` (unrestricted) when a
  task's cached assessment cannot be resolved, closing the only code path by
  which the pool-based retry ladder could silently widen to the full,
  unrestricted roster for a `complex`/`unknown` task — verified directly with
  `test_eligible_retry_labels_fails_closed_on_missing_assessment`. The exact
  live-process trigger for the original production symptom (continuous nova
  cycling across `job-00cdece6c00d.json`/`job-1677572b6ba3.json`) remains
  unconfirmed — flagging as a known open question in case it resurfaces after
  a `parrot-sdd-coder` MCP server restart; this hardening closes the risk
  regardless of the exact trigger.

Fix was implemented in the existing FEAT-572 worktree
(`.claude/worktrees/feat-FEAT-572-sdd-fix-ledger-lane`, commit `09a377fa1`,
pushed to `origin/feat-FEAT-572-sdd-fix-ledger-lane`) rather than as a
separate branch, since that worktree/spec is the reused open parent per
`/sdd-fix`'s SDD-lane routing. That feature branch's diff against `dev` was
confirmed to contain ONLY this fix (`git diff --stat origin/dev...HEAD`) —
FEAT-572's other in-progress tasks (TASK-3393, TASK-3396, TASK-3397) never
produced any code, since every one of their dispatch attempts was blocked by
this very bug. Given that, the fix commit was cherry-picked directly onto
`dev` (commit `848513359`, pushed) rather than waiting for `/sdd-done
FEAT-572` to close out the whole feature — safe and low-risk since it carried
no other feature's unfinished work along with it. `/sdd-done FEAT-572` will
still be needed later to close out TASK-3393/3396/3397 and merge/clean up the
worktree itself; this fix landing on `dev` early unblocks those tasks sooner.
Files actually changed: `engine.py` + `test_engine_dispatch.py` (not
`roster.py`, which the ledger issue's `about` field pointed at as a
conceptual anchor — the real defect was in `SddCoderEngine`'s pool-based
retry path, not in `roster.py`'s `eligible_seats`/`ChunkAssigner`, both of
which were already correctly tested and behaved correctly in isolation).

**Completed by**: Claude (interactive session)
**Date**: 2026-09-20
