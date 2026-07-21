# TASK-1856: End-to-end integration tests — gated run, reconnect, crash rebuild

**Feature**: FEAT-322 — AHP-style Session State, Host & HITL Approval Gates for dev-loop
**Spec**: `sdd/specs/agent-host-protocol-session-state.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1852, TASK-1853, TASK-1854, TASK-1855
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests — the three cross-module scenarios that prove the
feature end-to-end: a full run blocking on gates and resolved via the
command surface; WS state-view reconnect without gaps; and state rebuild by
folding the actions stream after a simulated host loss.

---

## Scope

Create `packages/ai-parrot/tests/flows/dev_loop/integration/test_session_state_e2e.py`
following the existing integration-suite conventions (see the directory's
README and `test_websocket_replay.py` for the harness/markers used):

- **`test_e2e_run_with_blocking_gates`**: stub dispatcher + fake toolkits
  drive a full initial-graph run whose brief carries one
  `ManualCriterion(blocking=True)`; while QA awaits, resolve the gate via
  the REST endpoint (approve); then approve the `deployment_approval` gate
  the same way; assert: final `Snapshot` phase `succeeded`, both gates
  `approved` with audit fields, `flow:{run_id}:actions` fold equals the
  final host state, legacy streams also populated (dual-publish), Jira
  transition stub called exactly once and only after approval.
- **`test_ws_state_view_reconnect`**: connect `view="state"` mid-run,
  record `server_seq`s, disconnect, reconnect with `?last_seen=`; assert no
  gaps/duplicates and eventual consistency with the final snapshot.
- **`test_crash_rebuild_from_actions_stream`**: after a completed gated run,
  discard the host (simulate crash), fold the actions stream from 0 and
  assert equality with the persisted terminal snapshot, pending-gate
  survival semantics covered by rebuilding mid-run too (cut the stream at a
  point where a gate is pending → rebuilt state is `awaiting_gate`).

Reuse/extend existing fakes: the repo's fake-redis stream stub pattern
(unit suites) or a real Redis behind the integration markers — match
whatever `integration/README.md` prescribes.

**NOT in scope**: live-LLM dispatch (`@pytest.mark.live` suites); nav-admin
golden fixtures (separate repo); performance/load assertions.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/integration/test_session_state_e2e.py` | CREATE | 3 e2e scenarios |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop import DevLoopRunner                      # __init__.py:26
from parrot.flows.dev_loop.session_state import (                    # TASK-1848/1849
    ActionEnvelope, Snapshot, reduce, DevLoopSessionState, session_channel,
)
from parrot.flows.dev_loop.commands import register_command_routes   # TASK-1855
from parrot.flows.dev_loop.models import ManualCriterion, WorkBrief  # models.py:70/:118
```

### Existing Signatures to Use
```python
# Integration harness precedents (READ THESE FIRST):
#   packages/ai-parrot/tests/flows/dev_loop/integration/README.md
#   packages/ai-parrot/tests/flows/dev_loop/integration/test_websocket_replay.py
#   packages/ai-parrot/tests/flows/dev_loop/test_runner.py (stub-flow pattern)
# Runner surface: run(brief, run_id=...) :153; resolve_gate/cancel_run (TASK-1851)
# WS: flow_stream_ws (streaming.py:298) + view=state/last_seen (TASK-1854)
# REST: register_command_routes (TASK-1855)
# WorkBrief requires: kind, summary, description, affected_component,
#   acceptance_criteria, escalation_assignee, reporter (see runner.py:271-283
#   for a minimal construction example)
```

### Does NOT Exist
- ~~a ready-made stub dispatcher fixture for gated runs~~ — build a minimal
  stub implementing `DevLoopCodeDispatcher.dispatch` (dispatcher.py:129-143
  Protocol) returning canned outputs per node
- ~~fixtures named `fake_redis_with_actions` outside this feature's new
  tests~~ — reuse the actual fixture names found in the existing suites

---

## Implementation Notes

### Key Constraints
- Deterministic timing: drive gate resolution from the test task after
  observing `awaiting_gate` in the snapshot/registry — no sleeps as
  synchronization (poll with timeout helper if the suite has one).
- The Jira/git toolkits are fakes recording calls — assert call ORDER for
  the transition-after-approval guarantee.
- Keep total runtime < ~60s so the suite stays CI-friendly.

---

## Acceptance Criteria

- [ ] All three scenarios implemented and green
- [ ] Fold-equals-snapshot asserted in both e2e and crash tests
- [ ] Jira transition ordering asserted (only after deployment approval)
- [ ] Suite passes: `pytest packages/ai-parrot/tests/flows/dev_loop/integration/test_session_state_e2e.py -v`
- [ ] Full dev-loop suite green: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`

---

## Test Specification

```python
async def test_e2e_run_with_blocking_gates(...): ...
async def test_ws_state_view_reconnect(...): ...
async def test_crash_rebuild_from_actions_stream(...): ...
```

---

## Agent Instructions

1. Verify TASK-1852/1853/1854/1855 are ALL in `sdd/tasks/completed/`.
2. Read the integration README + existing harness before writing fixtures.
3. Implement; run full suite; move to completed; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
