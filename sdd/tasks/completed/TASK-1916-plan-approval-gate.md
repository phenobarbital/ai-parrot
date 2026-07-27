# TASK-1916: plan_approval gate consumer — approve the plan before the fleet burns tokens

**Feature**: FEAT-377 — Graph Engineering Hardening
**Spec**: `sdd/specs/graphindex-as-engineering-devloop.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 5 (spec §3, G5). `GateKind` declares `plan_approval` with TTL config
(`DEV_LOOP_GATE_TTL_PLAN`) and documented fail-open semantics, but no node
ever opens it. The human-gate placement rule: approving the plan (Jira
ticket + spec + task decomposition) BEFORE an agent fleet implements it is
the cheap-to-approve / expensive-to-skip point. **Decided (spec §8)**:
wire it in the runner's post-research hook — no new flow node, no
`ResearchNode` change.

---

## Scope

- New config `DEV_LOOP_REQUIRE_PLAN_APPROVAL` (default `false`), declared
  alongside the FEAT-322 approval flags (grep `require_deployment_approval`
  for the mechanism and mirror it).
- In `runner.py`: when the flag is true, after `ResearchOutput` is available
  and BEFORE the development node dispatches, open
  `open_gate(kind="plan_approval", node_id=..., title=..., instructions=<plan
  summary: Jira key, spec path, task count>, ttl_seconds=<from
  gate_ttl_for("plan_approval")>, on_expiry="approve")` and
  `await wait_gate(gate_id)`.
  **First investigate how `require_deployment_approval` reaches its gate**
  (the `deployment_approval` gate is opened inside
  `deployment_handoff.py:262`) — if the established FEAT-322 pattern is
  node-side with a runner-owned flag, mirror that shape for the
  research→development boundary from the runner side as decided; if the
  runner genuinely cannot intercept between nodes, wire the gate at the
  earliest runner-visible post-research point and document the placement in
  the completion note.
- Fail-open: TTL expiry approves (that is what `on_expiry="approve"` does —
  verify against the expiry sweep behavior in session_state/runner tests).
- Rejection: a rejected gate must terminate the run the same way other
  rejected gates do (follow the deployment_approval rejection path).
- Unit tests: flag off → no gate opened; flag on → gate opened with
  `on_expiry="approve"`; rejection stops before development.

**NOT in scope**: `revision_approval` (stays unconsumed — not in this
feature's goals); parking behavior (TASK-1917); new flow nodes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | flag + post-research gate |
| `packages/ai-parrot/tests/flows/dev_loop/test_runner_gates.py` | MODIFY/CREATE | opt-in/off/reject tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.session_state import GateKind
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py:862-872
def open_gate(self, *, kind: GateKind, node_id: NodeId, title: str,
              instructions: str = "", payload_ref: str = "",
              ttl_seconds: Optional[int] = None,
              on_expiry: Literal["fail", "approve"] = "fail",
              ) -> Tuple[str, ActionEnvelope]:
async def wait_gate(self, gate_id: str) -> ApprovalGate:   # line 932

# GateKind includes "plan_approval" (session_state.py:166-172);
# documented as advisory/fail-open at session_state.py:222-228

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:71-76
# _GATE_TTL_CONF_ATTR already maps "plan_approval" → "DEV_LOOP_GATE_TTL_PLAN"
# gate_ttl_for at line 79

# Existing consumer to mirror (open_gate call shape):
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py:261-262
```

### Does NOT Exist
- ~~any `open_gate(kind="plan_approval")` call~~ — this task adds the first
- ~~`DEV_LOOP_REQUIRE_PLAN_APPROVAL`~~ — this task declares it
- ~~a dedicated plan-gate flow node~~ — rejected in spec §8; runner-side wiring only
- ~~a documented runner "post-research hook" API~~ — *(unverified — the exact interception point must be found by reading how the runner observes node completion; e.g. `on_node_event` listeners or shared-state polling. Verify before coding.)*

### MAJOR contract resolution — "runner's post-research hook" does not
### exist as a mechanism (found during implementation, 2026-07-26)

Verified by reading the engine's scheduler (`bots/flows/flow/flow.py`)
end to end:

1. `AgentsFlow._notify_node_event` (the `on_node_event`/
   `add_node_event_listener` hook) is explicitly **fire-and-forget** for
   coroutine callbacks: `"coroutines are scheduled as fire-and-forget
   tasks"` (its own docstring) — `asyncio.ensure_future(outcome)`, never
   awaited inline. A listener therefore CANNOT block/pause the
   scheduler's dispatch of the next node. This directly falsifies "runner
   observes node completion and pauses" as a viable mechanism.
2. `DevLoopRunner.run()` calls `await self.flow.run_flow(ctx)` exactly
   once, end to end — there is no node-by-node "step" API the runner
   could use to stop between `research` and `development`.
3. Every EXISTING gate (`manual_criterion` in `qa.py`,
   `deployment_approval` in `deployment_handoff.py`) is opened and
   awaited **from inside the node whose own dispatch it precedes** — the
   engine's `_spawn()` runs a node's `execute()` as an `asyncio.Task`
   and the scheduler simply awaits that task's completion via the
   completion queue; it has no idea (or need to know) that the task is
   internally blocked on `await host.wait_gate(...)`. This is
   MECHANISTICALLY how every gate-based pause in this engine works — not
   a documented "hook", but an emergent property of task-based node
   execution.

Conclusion: **"the runner's post-research hook" does not exist and
cannot be built without either a new flow node (explicitly rejected) or
a change to the flow engine's scheduler (far outside a single "S" task,
and not requested).** Per this task's own explicit fallback instruction
("if the runner genuinely cannot intercept between nodes, wire the gate
at the earliest runner-visible post-research point and document the
placement") — the earliest point where a pause-before-dispatch is
actually enforceable is the START of `DevelopmentNode.execute()` (the
node research's `on_success` edge target), mirroring
`DeploymentHandoffNode.require_deployment_approval`'s own node-side
shape exactly (gate lives in the node about to act, guarded by a
constructor flag threaded from the same `factories.py`/`flow.py` chain
`require_deployment_approval` uses). This is a deviation from this
task's literal Files list (`runner.py` only) — `nodes/development.py`,
`factories.py`, and `flow.py` needed the change instead; `runner.py`
itself needed NONE (`gate_ttl_for("plan_approval")` → `DEV_LOOP_GATE_TTL_PLAN`
already existed, confirmed unchanged from the Codebase Contract).

---

## Implementation Notes

### Key Constraints
- Follow FEAT-322's `require_deployment_approval` config + rejection
  semantics exactly — same failure shape, same event stream visibility.
- The gate instructions string should be human-scannable: one line each for
  Jira key, spec path, task count, estimated agents.
- Without TASK-1917, a waiting plan gate holds a concurrency slot — that is
  accepted v1 behavior; do not implement parking here.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py:204-262` — gate + candidates pattern
- `packages/ai-parrot/tests/flows/dev_loop/integration/test_session_state_e2e.py` — gated-run test patterns
- `sdd/specs/agent-host-protocol-session-state.spec.md` — FEAT-322 gate design

---

## Acceptance Criteria

- [ ] Flag default `false` → zero behavior change (test-asserted)
- [ ] Flag `true` → `plan_approval` gate opened post-research with `on_expiry="approve"` and the plan summary
- [ ] Approval (or TTL expiry) → development proceeds; rejection → run ends without development dispatch
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/` clean

---

## Test Specification

```python
async def test_plan_gate_off_by_default(stub_flow): ...
async def test_plan_gate_opened_when_enabled(stub_flow): ...
async def test_plan_gate_rejection_stops_run(stub_flow): ...
async def test_plan_gate_expiry_approves(stub_flow): ...
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code (especially the *(unverified)* interception point)
4. **Update status** in `sdd/tasks/index/graphindex-as-engineering-devloop.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-26
**Notes**:
- `conf.py`: `DEV_LOOP_REQUIRE_PLAN_APPROVAL: bool = config.getboolean(...,
  fallback=False)` — this task's own explicit design (unlike its
  `require_deployment_approval` precedent, which has NO conf-backing at
  all — confirmed by grep; only ever a constructor-param flag).
- `factories.py` / `flow.py`: `require_plan_approval: bool = False`
  threaded through `build_dev_loop_node_factories` /
  `build_dev_loop_flow` into `development_factory` — exactly mirroring
  `require_deployment_approval`'s existing plumbing shape.
- `nodes/development.py`: `require_plan_approval` ctor param;
  `_check_plan_approval(shared, research)` called at the very top of
  `execute()` (before `_with_repair_feedback`). No-ops when the flag is
  off, when `shared["_plan_gate_checked"]` is already set (so a
  QA-repair-loop re-entry — TASK-1910/1911 — never re-opens an
  already-approved plan gate), or (fail-open, matching
  `deployment_handoff`'s own legacy fallback) when no `session_host` is
  present, logging a warning. Otherwise opens
  `kind="plan_approval"` with `on_expiry="approve"` and instructions
  listing the Jira key, spec path, and a best-effort task count (via a
  new `_count_tasks` helper that reuses TASK-1913's `_build_scheduler`
  — `None`/"not yet decomposed" when no per-spec index is readable
  yet). A non-"approved" resolution (only reachable via an explicit
  human rejection, since TTL expiry auto-approves) raises `RuntimeError`
  — routes to `failure_handler` via the existing `on_error` fan-in edge,
  the same "terminate the run" effect a rejected `deployment_approval`
  gate has (that one returns a `"blocked"` dict instead, since
  `DeploymentHandoffNode`'s return type is a loose dict; `DevelopmentNode`
  must return a strict `DevelopmentOutput`, so raising — not returning —
  is the only type-safe way to signal failure here).
- `runner.py`: **no changes** — see the Codebase Contract's "MAJOR
  contract resolution" above for the full investigation. `gate_ttl_for`
  already mapped `"plan_approval"` correctly (verified unchanged).
- Test file: the stated `test_runner_gates.py` doesn't exist (same
  naming-guess pattern already seen in TASK-1907/1912's completion
  notes) — the real gate-integration coverage lives in
  `test_gate_integration.py` (`DeploymentHandoffNode`'s
  `deployment_approval` tests are the exact template mirrored here: real
  `SessionHost` construction, `host.resolve_gate(...)` driven
  concurrently via `asyncio.ensure_future`). Added 6 tests: the critical
  default-off regression guard (mirroring the existing
  `test_handoff_default_skips_gate_even_with_host_present` — a
  `SessionHost` is ALWAYS present in a real `DevLoopRunner.run()`, so
  "off by default" is the only thing preventing every legacy run from
  blocking forever), approved-proceeds, rejected-raises, TTL-expiry-
  approves (driven via `host.expire_due_gates(now=...)`, the same sweep
  the runner's periodic loop calls), no-host-fallback-with-warning, and
  checked-only-once-across-a-simulated-repair-loop-retry.
- `pytest packages/ai-parrot/tests/flows/dev_loop/ -m "not live"` (minus
  the pre-existing `hypothesis`-missing file): 701 passed, 1 skipped,
  same one pre-existing unrelated failure noted in every prior task this
  session.
- `ruff check` clean on every touched file (the one `conf.py` finding is
  the same pre-existing, unrelated `E402` noted repeatedly this session).

**Deviations from spec**: the Files list named `runner.py` as the
implementation surface; the actual change landed in
`nodes/development.py` + `factories.py` + `flow.py` instead, because —
proven by reading the engine's scheduler, not assumed — there is no
mechanism by which `runner.py` (or any external caller of
`run_flow()`) can pause the engine between two specific nodes. Every
gate in this codebase, including this new one, is opened and awaited
from inside the node whose dispatch it precedes; that IS the "runner's
post-research hook" in the only form the engine actually supports.
