# TASK-2628: Runtime Wiring and Cross-Workflow Regression Coverage

**Feature**: FEAT-480 — Dev Flow Node Checkpoint Recovery
**Spec**: `sdd/specs/dev-flow-node-caching.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2627
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 6. Production entry points (example servers, CLI
bootstrap) still construct one shared flow instance per process; they must
pass per-run builders instead so each job gets its own checkpoint identity.
This task also delivers the spec §4 integration test matrix that exercises the
complete recovery protocol end-to-end across both workflows.

---

## Scope

- Rewire `examples/dev_loop/server.py`, `examples/dev_loop/server_dev.py`, and
  `parrot/cli/devloop/bootstrap.py` to supply per-run flow factories to the
  runners (no job depends on a checkpoint identity shared across jobs).
- Surface/propagate the effective `run_id` at these entry points so a caller
  or job system can persist it for later recovery.
- Implement the spec §4 integration suite:
  - `test_dev_loop_restart_after_bug_intake` / `_after_research` /
    `_after_development`
  - `test_dev_flow_restart_after_planner` / `_after_development`
  - `test_restart_with_new_run_id_is_cache_miss`
  - `test_concurrent_resume_lease_conflict`
  - `test_exception_restart_preserves_completed_frontier`
  - `test_runtime_entrypoints_build_per_run_flows`
- Verify the full acceptance-criteria checklist in spec §5 and record evidence
  under `artifacts/logs/` (per CLAUDE.md workflow).

**NOT in scope**: new engine or dev-flow behavior — this task only wires and
verifies; behavior gaps found here are fixed by reopening the owning task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/dev_loop/server.py` | MODIFY | Per-run factory wiring (anchor ~line 1559) |
| `examples/dev_loop/server_dev.py` | MODIFY | Per-run factory wiring (anchor ~line 490) |
| `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py` | MODIFY | Per-run factory wiring (anchor ~line 324) |
| `packages/ai-parrot/tests/flows/test_dev_recovery_integration.py` | CREATE | Spec §4 integration matrix |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All engine/coordinator/runner APIs come from TASK-2622..2627 — grep the
# merged code; do not rely on the spec's proposed signatures if they drifted.
from parrot.flows.dev_loop.checkpoint import DevCheckpointCoordinator  # TASK-2625
from parrot.flows.dev_loop.models import ResearchOutput, DevelopmentOutput
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/models/__init__.py:21
```

### Existing Signatures to Use
```python
# Entry-point anchors (verified at spec time; re-grep — these files change often):
#   examples/dev_loop/server.py:1559          — flow/runner construction
#   examples/dev_loop/server_dev.py:490       — flow/runner construction
#   packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py:324 — CLI wiring
```

### Does NOT Exist
- ~~A process-global "current run" registry~~ — run identity flows through
  arguments; do not add module-level mutable state to the servers.
- ~~Redis-optional required mode~~ — required mode needs a reachable
  checkpoint store; entry points must fail loudly if it is unavailable, not
  silently downgrade to best-effort.

---

## Implementation Notes

### Key Constraints
- Integration tests must cross a real process-like boundary: construct a NEW
  runner/flow object graph over the SAME store (the `restarted_runner` fixture
  pattern from spec §4) — never resume with the original in-memory objects.
- Use dispatcher/node execution counters and assert the pre-restart node
  actually ran; cache assertions must not pass vacuously.
- Unit-level tests stay service-independent with `FakeCheckpointStore`; only
  Redis-marked integration tests may use the existing Redis test fixture.
- Keep example-server behavior otherwise unchanged (routes, gate handling).

---

## Acceptance Criteria

- [ ] `test_runtime_entrypoints_build_per_run_flows` — server and CLI wiring
  no longer share one checkpoint identity across jobs
- [ ] All nine spec §4 integration tests pass
- [ ] Full spec §5 acceptance checklist verified; evidence saved to
  `artifacts/logs/feat-480-verification.md`
- [ ] Complete suites green: `pytest packages/ai-parrot/tests -k
  "checkpoint or dev_loop or dev_flow" -q`; `ruff check` clean on touched files

---

## Test Specification

```python
@pytest.fixture
def restarted_runner(flow_factory, checkpoint_store):
    """Distinct runner/flow object graph over the same store (process boundary)."""
    return DevLoopRunner(flow_factory=flow_factory, checkpoint_store=checkpoint_store)

async def test_dev_loop_restart_after_research(checkpoint_store, restarted_runner):
    """First runner completes intake+research then 'crashes'; restarted runner
    with same run_id: research dispatcher count unchanged, typed ResearchOutput
    restored, worktree validated, execution continues at development."""

async def test_concurrent_resume_lease_conflict(checkpoint_store):
    """Two prepare() calls for one workflow/run_id: exactly one acquires the lease."""
```

---

## Agent Instructions

1. Read spec §4, §5 in full — this task closes the feature's verification.
2. TASK-2622..2627 must be in `sdd/tasks/completed/`. 3. Re-grep every entry-
point anchor. 4. Index → `in-progress`; implement; move to completed; index →
`done`; set the index header's `completed_at` if all feature tasks are done.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
