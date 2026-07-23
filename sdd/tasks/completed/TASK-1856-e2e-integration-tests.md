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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-22
**Notes**: Created `test_session_state_e2e.py` (marked `pytest.mark.live`
per this directory's convention, but — mirroring `test_websocket_replay.py`/
`test_concurrency.py` — needs NO live services: in-process fake Redis
Streams stub + stub dispatcher + fake Jira toolkit + neutralized git
push/PR). Reused `test_runner.py`'s exact stub-dispatcher/mock-Jira
fixture shapes (had to add `jira_get_issue`/`jira_search_issues`/
`jira_assign_issue`/`jira_find_user` AsyncMocks that my first draft
missed — `ResearchNode._find_existing_issue` calls them and a bare
`MagicMock()` auto-attribute isn't awaitable, surfaced as "object
MagicMock can't be used in 'await' expression").
- `test_e2e_run_with_blocking_gates`: real 8-node flow via
  `build_dev_loop_flow`, one blocking `ManualCriterion`; QA's
  `manual_criterion` gate and the `deployment_approval` gate BOTH
  resolved via the real `commands.py` REST endpoints
  (`aiohttp_client` + `register_command_routes`); asserts Jira
  "Ready to Deploy" transition fires only after both approvals, final
  phase `succeeded`, both gates carry resolver identity, and
  `flow:{run_id}:actions` folds to exactly `host.state`.
- `test_ws_state_view_reconnect`: real `FlowStreamMultiplexer(view="state")`
  against the SAME run's actions stream — snapshot mid-run, resolve both
  gates, then reconnect with `?last_seen=<snapshot's from_seq>` and assert
  strictly-increasing, gap-free, duplicate-free `server_seq`s reaching the
  final action, with the reconnect-replayed fold matching the finished
  host's state exactly.
- `test_crash_rebuild_from_actions_stream`: folds a PREFIX of the actions
  stream captured while a gate was still pending → asserts
  `phase == "awaiting_gate"` (pending-gate survival); after the run
  completes and the runner has ALREADY discarded the host
  (`_close_host`, TASK-1851), folds the FULL stream from seq 0 with zero
  reference to the original host object and asserts it matches both the
  live host's final state AND the persisted terminal-snapshot JSON
  artifact byte-for-byte (`model_dump(mode="json")` equality).
Full dev_loop suite: 507 passed (504 + these 3), same 4 pre-existing
unrelated failures as every prior task in this feature, no hangs, no
`outputs/` pollution (protected by TASK-1851's `conftest.py` autouse
fixture, which cascades to this `integration/` subdirectory).

**Deviations from spec**:
1. **`require_deployment_approval` flipped via `object.__setattr__` on the
   already-constructed `DeploymentHandoffNode` instance, from within the
   test** (`flow._nodes["deployment_handoff"]`), rather than via a new
   parameter threaded through `build_dev_loop_flow`/
   `build_dev_loop_node_factories`. Neither of those two production
   files is in this task's file list (test-file only), and TASK-1853
   already flagged that no task wires the opt-in flag through the
   factory pipeline. This is the same attribute-setting convention
   `DeploymentHandoffNode.__init__` itself uses, confirmed safe because
   `AgentsFlow._materialize_nodes()` copies the node instance (including
   non-field private attributes) fresh per run — verified working end to
   end (both gates genuinely activated in the real flow). Zero production
   code touched for this task.
2. **Fake in-process Redis** (not a live Redis instance) backs
   `flow:{run_id}:actions`, injected via
   `runner._ensure_actions_redis = AsyncMock(return_value=fake_redis)`
   (same pattern as `test_runner_host.py`'s sink-failure test). This
   keeps the suite CI-safe and fast (~10s for all 3 scenarios) per the
   task's own "<~60s" constraint and the directory's established
   "in-process stream stub — no live Redis needed" precedent
   (`test_websocket_replay.py`), while still genuinely exercising the
   real XADD/XRANGE/XREAD code paths in `runner.py` and `streaming.py`.
