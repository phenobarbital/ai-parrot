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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
