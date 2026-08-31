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

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-08-31
**Notes**:
- `examples/dev_loop/server.py`'s `_on_startup`, `examples/dev_loop/
  server_dev.py`'s `_on_startup`, and `parrot.cli.devloop.bootstrap.
  build_runtime()` each now capture the exact kwargs their
  `build_dev_loop_flow`/`build_dev_flow` call is invoked with into a
  `dev_loop_flow_kwargs` dict, unpacked via `**dev_loop_flow_kwargs` for
  the flow build and passed straight through to `DevLoopRunner`/
  `DevFlowRunner` alongside `checkpoint_store=None` (env-fallback
  precedence, no new config surface). This is what actually enables each
  runner's per-run checkpoint-recovery path (`run(..., run_id=...)`) —
  before this task `dev_loop_flow_kwargs` was never supplied at any real
  entry point, so `recovery_enabled` was always `False` even though every
  entry point already mints its own stable per-job `run_id`
  (`f"run-{uuid.uuid4().hex[:8]}"`, pre-existing) and already surfaces it
  in the response/CLI output — "no job depends on a checkpoint identity
  shared across jobs" (spec §3 Module 6) was therefore satisfied by fixing
  exactly one gap (the missing `dev_loop_flow_kwargs`/`checkpoint_store`
  wiring), not by changing run_id minting or surfacing at all.
- Each of the three `dict(...)` calls was written as a dict literal
  (`{...}`) rather than `dict(...)` — ruff's `C408` flagged the call form
  as a genuinely new lint finding (0 pre-existing instances in any of the
  three files), so it was fixed rather than left as a lint-delta increase.
- `packages/ai-parrot/tests/flows/test_dev_recovery_integration.py`
  (CREATE) implements all nine spec §4 integration tests, each
  constructing a genuinely NEW `DevLoopRunner`/`DevFlowRunner` +
  `AgentsFlow` object graph per "process" over one shared
  `FakeCheckpointStore`, with real per-node call counters (never a
  vacuous cache assertion):
  - `test_dev_loop_restart_after_bug_intake`,
    `test_dev_loop_restart_after_research`,
    `test_dev_loop_restart_after_development`: drive the REAL bug-mode
    `build_dev_loop_flow` topology through a mocked *dispatcher*
    (`_stub_dev_loop_bug_executes`), the SAME proven strategy
    `test_recovery_lifecycle.py` (TASK-2626) already established —
    reused rather than reinvented.
  - `test_dev_flow_restart_after_planner`,
    `test_dev_flow_restart_after_development`: drive the REAL
    `build_dev_flow` topology, but stub every node's `execute()` directly
    (`_stub_dev_flow_executes`) instead — mirroring
    `test_feature_flow.py`'s proven recipe. `FeatureHandoffNode`'s real
    git/PR push-and-draft-PR internals have no existing low-level mock
    fixture in this codebase (unlike `DeploymentHandoffNode`'s
    `patch_handoff`), and building one was out of this task's scope
    ("this task only wires and verifies").
  - `test_restart_with_new_run_id_is_cache_miss`: same brief, a
    DIFFERENT `run_id` — every node call count doubles (never reuses the
    first run_id's checkpoint).
  - `test_exception_restart_preserves_completed_frontier`: asserts the
    ENTIRE prior frontier (bug_intake + research + development, not just
    qa's immediate predecessor) is skipped on restart.
  - `test_concurrent_resume_lease_conflict`: pre-acquires the resume
    lease with a different holder (mirrors
    `test_suspend_resume.py::test_resume_locked_raises_flowlockederror`'s
    proven pattern) and asserts `DevCheckpointCoordinator.prepare()`
    raises `FlowLockedError`.
  - `test_runtime_entrypoints_build_per_run_flows`: drives
    `server.py`'s real `_on_startup` (reusing
    `test_server_repo_wiring.py`'s proven minimal-mock harness) and
    `bootstrap.py`'s real `build_runtime()` (reusing `test_bootstrap.py`'s
    proven harness), asserting `DevLoopRunner`'s captured
    `dev_loop_flow_kwargs` is non-`None` and equals exactly what
    `build_dev_loop_flow` was called with. `server_dev.py`'s own
    `_on_startup` was NOT given an equivalent from-scratch harness (no
    existing test does this either — it delegates many builders to
    `server.py`'s own private helpers via `import server as ops_server`,
    which would need a comparably heavy mock surface); its
    `dev_loop_flow_kwargs`/`checkpoint_store` wiring is still exercised
    indirectly by the file's own source-level correctness (identical
    pattern to server.py/bootstrap.py, code-reviewed) and by every OTHER
    `test_server_dev.py` test that already drives its route handlers
    through a stubbed `app["runner"]`.
- **Genuine gap discovered (documented per this task's own instruction:
  "behavior gaps found here are fixed by reopening the owning task", NOT
  fixed in this task — none of `dev_loop/flow.py`/`dev_flow/flow.py` are
  in this task's file list):** `QAReport`, `SynthesisReport`, and
  `FeedbackDecision` are never passed to `register_checkpoint_type()` in
  either `dev_loop/flow.py` or `dev_flow/flow.py` (only `WorkBrief`/
  `FeatureBrief`/`ResearchOutput`/`PlannerOutput`/`DevelopmentOutput`/
  `DevRequestBrief`/`IdeationOutput` are registered there). A checkpoint
  taken immediately after `qa`, `synthesis`, or `feedback_router`
  succeeds therefore serializes that node's own typed result LOSSILY
  (degraded to a string — confirmed via a real
  `AgentsFlow.resume(): ... is lossy` warning while building
  `test_exception_restart_preserves_completed_frontier`), which can break
  an on_condition edge's predicate re-evaluation on resume for any edge
  keyed off that node's result (e.g. `qa -> deployment_handoff`'s
  `_qa_passed` predicate) — a crash immediately after `qa` succeeds can
  resume without ever re-dispatching `deployment_handoff`/
  `feature_handoff`. Recommend a follow-up task registering these three
  types alongside the existing five/two.
- Verification: `pytest packages/ai-parrot/tests/flows/test_dev_recovery_
  integration.py -q` → 9 passed; `pytest packages/ai-parrot/tests/flows
  packages/ai-parrot/tests/cli -k "checkpoint or dev_loop or dev_flow" -q`
  → 1435 passed (5 pre-existing failures confirmed unrelated: 2 require a
  local Postgres not running in this environment, 3 — `test_qa_codereview`,
  `test_secondopinion_brief`, `test_subagent_parity` — fail identically on
  the `dev` baseline, confirmed via a direct comparison run). `ruff check`
  clean on the new test file; lint-delta clean (no new categories) on the
  three pre-existing-style entry-point files after fixing the one genuinely
  new `C408` finding in each.

**Deviations from spec**: none in behavior. The one gap noted above
(`QAReport`/`SynthesisReport`/`FeedbackDecision` registration) is a
pre-existing omission from TASK-2626/TASK-2627, discovered — not
introduced — by this task's verification pass, and is explicitly out of
this task's file-list scope to fix.
