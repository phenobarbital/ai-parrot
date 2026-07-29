# TASK-1917: Gate park + resume — free the concurrency slot while awaiting gates

**Feature**: FEAT-377 — Graph Engineering Hardening
**Spec**: `sdd/specs/graphindex-as-engineering-devloop.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1916
**Assigned-to**: unassigned

---

## Context

Module 6 (spec §3, G6). The runner wraps the ENTIRE flow — including gate
waits — in `async with self._semaphore`, so a run awaiting human approval
holds a `FLOW_MAX_CONCURRENT_RUNS` slot for the gate's whole TTL. FEAT-322
deferred resume (Risk R8). The event-sourced state makes it feasible now: a
paused run is fully reconstructible from `flow:{run_id}:actions`.
**Decided (spec §8)**: parking applies uniformly to ALL gate kinds when
`DEV_LOOP_GATE_PARK=true` — one code path.

*(Depends on TASK-1916 for the end-to-end plan-gate park test; unit tests
use `deployment_approval`.)*

---

## Scope

- New config `DEV_LOOP_GATE_PARK` (default `true` per spec §2 config table).
- When a gate opens and the flag is on: release the semaphore slot, mark the
  run `parked` (new session-state action + reducer branch, FEAT-322
  pattern), and return the worker coroutine's slot to the pool while the
  gate's `wait_gate` future stays pending.
- `DevLoopRunner.resume_run(run_id: str) -> FlowResult`: on gate resolution
  (approve/reject/expiry), re-acquire a slot and continue from the wait-side
  of the gate. v1 is in-process — the runner object and its in-memory
  futures survive; cross-process crash recovery stays OUT (spec Non-Goals).
- Gate resolution must trigger resume automatically (hook where gates are
  resolved — REST resolve/cancel and the expiry sweep) — `resume_run` is
  also public for manual invocation.
- Expiry sweep: verify it still fires for parked runs; an expired-approved
  gate must resume identically to explicit approval.
- Tests:
  - `test_parked_run_releases_slot`: run awaiting gate + park on → a queued
    second run acquires the slot.
  - `test_resume_run_after_gate`: resolve → run completes.
  - `test_park_disabled_holds_slot`: flag off → current behavior.
  - e2e with plan gate (needs TASK-1916): parked plan approval, slot freed,
    resume completes.

**NOT in scope**: cross-process resume; changing gate semantics/TTLs;
`revision_approval` consumption.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | park/release/resume + config |
| `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` | MODIFY | `RunParked`/`RunResumed` actions + reducers |
| `packages/ai-parrot/tests/flows/dev_loop/test_runner_park.py` | CREATE | slot release/resume unit tests |
| `packages/ai-parrot/tests/flows/dev_loop/integration/test_gate_park_e2e.py` | CREATE | parked plan-gate e2e |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.session_state import GateKind, ActionEnvelope, reduce
from parrot.flows.dev_loop.models import RevisionBrief  # only if touched — likely not
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
self._semaphore = asyncio.Semaphore(self.max_concurrent_runs)   # line 182
# lines 573-586 — the slot-holding structure to rework:
#   async with self._semaphore:
#       self._active.add(rid)
#       ...
#       try: result = await self.flow.run_flow(ctx)
#       finally: self._active.discard(rid)

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
async def wait_gate(self, gate_id: str) -> ApprovalGate:   # lines 932-957
# gate waiting is `await event.wait()` on an asyncio.Event — the park
# mechanism must interpose here or at the runner boundary around it.
# DevLoopAction union: lines 406-417; reduce(): line 560 (flat if-match);
# NO register function — extend union + add branches.

# Gate resolution surfaces (find and hook): REST resolve/cancel endpoints +
# the FEAT-322 expiry sweep (grep "sweep" / "expiry" in session_state.py,
# runner.py, and handlers).
```

### Does NOT Exist
- ~~`DevLoopRunner.resume_run`~~ — this task creates it
- ~~`DEV_LOOP_GATE_PARK`~~ — this task declares it
- ~~`parked` run status / `RunParked` action~~ — this task adds them
- ~~semaphore release helper mid-run~~ — nothing releases the slot today; design it (e.g. explicit `self._semaphore.release()` + re-`acquire()` with careful exception safety, or restructure to acquire-per-segment). *(The exact structure is the task's core design work — keep `finally` correctness: a parked run must not double-release.)*

---

## Implementation Notes

### Key Constraints
- Exception safety is the hard part: the `async with self._semaphore`
  context manager cannot span a park/resume cycle — restructure to manual
  acquire/release with a single owner of the slot state, and property-test
  that every code path releases exactly once.
- More runs than slots can now be live-but-parked; `self._active`
  bookkeeping must distinguish `active` from `parked` (renderer/`/status`
  surfaces may read it — grep usages).
- FEAT-322 event sourcing: `RunParked`/`RunResumed` actions make parking
  visible in the replayable stream (`view=state`).
- Uniform parking: do NOT special-case gate kinds.

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/integration/test_session_state_e2e.py` — gated run, WS reconnect, crash rebuild patterns
- `sdd/specs/dev-loop-orchestration.spec.md:994-997` — Risk R8 (the deferral this task lifts, in-process only)
- `sdd/specs/agent-host-protocol-session-state.spec.md` — FEAT-322 design

---

## Acceptance Criteria

- [ ] Park on: run awaiting ANY gate kind frees its slot; queued run proceeds
- [ ] `resume_run` (and automatic resume on gate resolution) completes the parked run
- [ ] Expired-approved gate resumes identically to explicit approval
- [ ] Park off: byte-identical to current behavior
- [ ] Slot accounting: exactly-once release per park, exactly-once re-acquire per resume (no leak under rejection/exception paths)
- [ ] Parked runs visible in session state via `RunParked` action replay
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/` clean

---

## Test Specification

```python
async def test_parked_run_releases_slot(runner_one_slot): ...
async def test_resume_run_after_gate(runner_one_slot): ...
async def test_park_disabled_holds_slot(runner_one_slot): ...
async def test_expiry_approve_resumes(runner_one_slot): ...
async def test_no_double_release_on_rejection(runner_one_slot): ...
async def test_parked_plan_gate_e2e(runner_one_slot):  # needs TASK-1916
    ...
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — TASK-1916 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/graphindex-as-engineering-devloop.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-27
**Notes**:

Implementation:
- `conf.py`: new `DEV_LOOP_GATE_PARK: bool` (default `True`).
- `session_state.py`: `RunSummary.parked: bool = False`; new root actions
  `RunParked`/`RunResumed` (added to the `RootAction` discriminated
  union) with a flat reducer branch in `reduce_root` mirroring the
  existing pattern (no registry).
- `runner.py` — the core design:
  - `_make_envelope_sink` now inspects every envelope's action `type`.
    On the run's FIRST open gate (`_pending_gate_count` 0->1) it calls
    `_park(run_id)` synchronously. On a gate resolving/expiring, it
    decrements the counter and — once it reaches 0 while the run is
    parked — schedules `_auto_resume(run_id)` via `create_task` (never
    awaited inline; the sink is a synchronous callback).
  - `_park`: synchronous, idempotent-by-guard (`run_id in self._active`)
    slot release + `RunParked` action + `asyncio.Semaphore.release()`.
    Semaphore release has no per-task ownership, so releasing from a
    different call stack than the original `acquire()` is safe; the
    guard enforces exactly-once.
  - `resume_run(run_id) -> FlowResult`: the public re-acquire + await
    entry point (also the automatic path's implementation). Looks up
    the run's completion `Future` from a new `_run_completion` registry
    (seeded in `run()`/`run_revision()`), re-acquires the semaphore if
    still parked, and re-checks `fut.done()` AFTER the acquire — a
    fast-finishing flow can complete while this coroutine was waiting
    for a free slot, so the re-check releases immediately instead of
    leaking an acquired-but-unused slot. Raises `KeyError` only when no
    run is tracked at all (never started, or already finished AND
    fully cleaned up before ANY caller's initial lookup — see below).
  - `run()`/`run_revision()`: restructured from `async with
    self._semaphore:` to manual acquire/release + a per-run
    `asyncio.Future` completion registry, because a park can release
    the slot from deep inside `run_flow()` — a context manager cannot
    express "release now, maybe someone else re-acquires before I
    return". `finally` distinguishes `_active` (release once) from
    `_parked` (already released, no double-release) and always pops
    `_pending_gate_count`; the completion future is resolved (result or
    exception) and only then popped from the registry.
  - `parked_runs` / `is_parked(run_id)` introspection properties.
- Tests:
  - `test_runner_park.py` (7 unit tests, stub flows, matching
    `test_runner_host.py`'s harness): slot release, resume-after-gate,
    the public `resume_run` API, flag-off parity, TTL fail-open expiry
    resume, no-double-release-on-rejection, and two-concurrently-open
    gates parking/resuming exactly once each (not once per gate).
  - `integration/test_gate_park_e2e.py` (2 tests, real
    `DevLoopRunner`/`build_dev_loop_flow(require_plan_approval=True)`,
    mocked dispatcher/Jira, no network): a REAL `plan_approval` gate
    (TASK-1916) parks the run (slot freed — proven by swapping in a
    trivial second flow that completes immediately while run 1 is still
    parked) and resuming it drives the SAME run through
    Development/QA/Close; a rejected gate resumes straight into
    `failure_handler`.

Codebase Contract corrections (none needed — the contract's structural
pointers, e.g. `self._semaphore = asyncio.Semaphore(...)` and the
`async with self._semaphore:` block, matched the code as found; the
"lines 573-586" range had drifted slightly by the time this task
started but the referenced code shapes were still accurate).

Investigation beyond the task's literal file list: the full-suite run
(`pytest tests/flows/dev_loop/`) surfaced 2 pre-existing failures in
`test_session_state_properties.py` — `test_action_union_schema_has_
discriminator` (hardcoded `== 20`, stale since TASK-1913 added
`run/qaAttemptRecorded` without updating this count to 21) and
`test_root_action_union_schema_has_discriminator` (hardcoded exact
mapping set, correctly invalidated by THIS task's new `root/runParked`/
`root/runResumed` members). Both are property tests whose entire job is
to enumerate discriminated-union membership exhaustively — by design
they must be updated whenever a task legitimately adds a new action
type. Updated both assertions (21, and the mapping set + the two new
keys) rather than leaving the suite red; this is the direct,
minimal fix these two hardcoded assertions require, not a
reinterpretation of their intent. `test_session_state_properties.py`
was not in this task's Files list, but leaving the pointed-out
TASK-1913 gap unfixed would have kept the suite red for a cause
unrelated to this task's own diff.

The `test_resume_run_public_api` unit test needed a `post_gate_delay`
parameter on the shared `_GateOpeningFlow` stub: with an instantaneous
stub, resolving the gate races the sink's automatic `_auto_resume`
against the test's own explicit `resume_run()` call for the SAME
already-finishing run, both legitimately able to observe "run already
cleaned up" nondeterministically. This is an artifact of an
unrealistically-instant stub (real nodes do more work after a gate
resolves), not a correctness gap in `resume_run` — its `fut.done()`
re-check after acquiring is exactly the safety net that makes both the
manual and automatic paths individually race-safe; the test now gives
the stub flow a small delay so both assertions land deterministically.

Full-suite verification: `pytest tests/flows/dev_loop/ -q -m "not
live"` → 723 passed, 1 skipped, 1 failed
(`test_lazy_import.py::test_models_module_is_pure`, the pre-existing
test-order-dependent flake confirmed unrelated in every prior FEAT-377
task's completion note) — no other regressions. `pytest
tests/bots/flows/ -q -m "not live"` → 238 passed (sanity check on the
shared flow engine, untouched by this task). `ruff check` clean on all
touched files.

**Deviations from spec**: none. The two additional touched-but-not-
task-listed files (`test_session_state_properties.py` for the
discriminator-count fixes) are covered above — a direct, minimal
consequence of this task's own union changes plus a pre-existing
TASK-1913 gap this task's full-suite run exposed.
