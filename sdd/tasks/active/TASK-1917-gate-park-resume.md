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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
