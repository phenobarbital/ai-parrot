---
id: F006
query: "G6 — Checkpoint/resume for gated runs"
type: code_review
verdict: CONFIRMED
---

## G6: Gated runs hold concurrency slot; checkpoint/resume deferred

**Verdict: CONFIRMED**

### Evidence

1. **`runner.py:573-586`** — entire flow runs inside `async with self._semaphore`.
   Gate waits happen inside nodes → semaphore slot held for entire gate duration.

2. **`session_state.py:932-957`** — gate waiting via `await event.wait()`.
   No mechanism to release/reacquire semaphore slot.

3. **`runner.py:182`** — semaphore initialized with `max_concurrent_runs`,
   never released mid-run.

4. **`sdd/specs/dev-loop-orchestration.spec.md:994-997`** (Risk R8) —
   explicit deferral: "no resume in v1 [...] v2 may add resume on top of
   claude-agent-sdk's session resume."

### Impact

Long-TTL blocking gates (manual_criterion, plan_approval if opened)
would exhaust the concurrency pool. Prerequisite for G5 plan_approval
with meaningful TTLs.
