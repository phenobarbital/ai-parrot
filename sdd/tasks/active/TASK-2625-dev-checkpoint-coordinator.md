# TASK-2625: Dev Workflow Recovery Adapter (DevCheckpointCoordinator)

**Feature**: FEAT-480 — Dev Flow Node Checkpoint Recovery
**Spec**: `sdd/specs/dev-flow-node-caching.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2624
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3. The engine now supports typed registration,
factory resume, fingerprint metadata, and a required barrier — this task adds
the dev-workflow-specific glue in a NEW module
`parrot/flows/dev_loop/checkpoint.py`: stable namespaced identity
(`"<workflow>/<run_id>"`), deterministic SHA-256 input fingerprints,
fresh/miss/resume selection, projection of typed node results back to the
shared keys downstream nodes read, recovered-artifact validation
(worktree/spec/task), and structured recovery events.

---

## Scope

- Implement `DevCheckpointCoordinator` with
  `async prepare(*, workflow, run_id, brief, live_context, flow_factory,
  execution_policy) -> tuple[AgentsFlow, Literal["fresh", "resumed"]]`
  (signature per spec §2 New Public Interfaces):
  - flow identity `f"{workflow}/{run_id}"` inside the existing
    `flowckpt:{flow_id}:*` key family (slash, never a colon);
  - `store.latest()` miss → build fresh via factory with checkpointing
    enabled, required mode, external declarative definition, and
    `CheckpointInputMetadata`;
  - hit → verify fingerprint (mismatch raises
    `CheckpointFingerprintMismatchError`), acquire the existing Redis lease
    (conflict is a hard error), then `AgentsFlow.resume(flow_factory=...,
    seed_context=live_context, expected_input=...)`.
- Implement the fingerprint: SHA-256 over deterministic JSON
  (`sort_keys=True`) of at least: workflow kind, topology version, normalized
  brief (`model_dump(mode="json")`), repository identity/base path,
  routing-relevant execution policy (QA/approval/pool settings), referenced
  SDD document identity. Exclude timestamps, hosts, trace IDs, live objects.
- Implement shared-state projection: registered typed results → shared keys
  `bug_brief`, `bug_findings`, `research_output`, `planner_output`,
  `development_output` (allowlist projector for `checkpoint_shared_data`).
- Implement recovered-artifact validation (extract/reuse the ResearchNode
  worktree guard): worktree registered (`git worktree list`), on the expected
  branch, referenced spec/task files exist. Invalid state fails explicitly.
- Emit structured events/logs: cache_miss, checkpoint_committed,
  resume_started, node_restored, node_rerun, artifact_validation_failure,
  fingerprint_mismatch, lease_conflict, checkpoint_persistence_failure.
- Unit tests: fingerprint determinism/mismatch, live-object exclusion,
  worktree validation failure modes.

**NOT in scope**: changes to `dev_loop/flow.py` / `runner.py` (TASK-2626),
`dev_flow` (TASK-2627).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/checkpoint.py` | CREATE | Coordinator, fingerprint, projection, validation, events |
| `packages/ai-parrot/tests/flows/dev_loop/test_checkpoint_coordinator.py` | CREATE | Unit tests (follow existing dev_loop test layout) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows import AgentsFlow, FlowContext
from parrot.bots.flows.core.checkpoint import (
    CheckpointStore, FlowCheckpoint, RedisCheckpointStore, get_checkpoint_store,
)
# verified: .../core/checkpoint/__init__.py:7

from parrot.flows.dev_loop.models import (
    DevelopmentOutput, PlannerOutput, ResearchOutput, WorkBrief,
)
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/models/__init__.py:21

# From TASK-2622..2624 (verify in completed code before use):
#   register_checkpoint_type, CheckpointPersistenceError,
#   CheckpointFingerprintMismatchError, CheckpointInputMetadata,
#   AgentsFlow.resume(flow_factory=..., seed_context=..., expected_input=...),
#   AgentsFlow(checkpoint_required=..., checkpoint_definition=...,
#              checkpoint_input=..., checkpoint_shared_data=...)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/base.py:17
class CheckpointStore(ABC):
    async def put(self, checkpoint) -> None: ...             # line 29
    async def latest(self, flow_id) -> FlowCheckpoint | None: ...  # line 37
    async def acquire_lease(self, flow_id, holder, ttl=60) -> bool: ...  # line 93

# Worktree/artifact validation source to extract from:
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py
#   ~line 257/334/472: research dispatch + worktree preparation
#   ~line 1228: existing worktree guard behavior (re-grep before extraction)

# Shared-key consumers (projection targets — verify names in node code):
#   nodes/bug_intake.py ~85/119   → bug_brief / bug_findings
#   nodes/development.py ~142/190 → research_output / development_output
```

### Does NOT Exist
- ~~`parrot/flows/dev_loop/checkpoint.py`~~ — created by THIS task.
- ~~`DevCheckpointCoordinator`~~ — created by THIS task.
- ~~A serialized `SessionHost` recovery API~~ — live hosts live in the runner
  registry and are recreated by the caller; the coordinator NEVER deserializes
  one.
- ~~`DevLoopRunner.resume_job()`~~ — `resume_run()` only resumes an in-memory
  parked gate; do not confuse it with process-restart recovery.

---

## Implementation Notes

### Key Constraints
- Fingerprint: `hashlib.sha256(json.dumps(payload, sort_keys=True,
  separators=(",", ":")).encode())` — never hash `repr()`, never pickle.
- Restore only registered types with explicit projection rules; reject lossy
  critical results.
- The coordinator receives the caller's fresh `FlowContext` — it must never
  overwrite live values (`SessionHost`, dispatchers, toolkits, trace context)
  with checkpoint content.
- Follow the module template of `parrot/flows/dev_loop/` (definition +
  factories + nodes + runner); async, Pydantic, `self.logger`.
- Events go through the existing node-event/telemetry channels used by the
  dev flows — grep `on_node_event` usage in `dev_loop/flow.py` for the shape.

---

## Acceptance Criteria

- [ ] `test_fingerprint_is_deterministic` — equivalent normalized inputs give
  one digest
- [ ] `test_same_run_id_different_input_rejected` — changed
  brief/topology/policy raises fingerprint mismatch
- [ ] `test_live_shared_objects_are_not_restored` — fresh `SessionHost` wins
- [ ] `test_recovered_worktree_requires_expected_branch` — missing,
  unregistered, or wrong-branch worktree fails explicitly
- [ ] Lease conflict on concurrent prepare raises (no double side effects)
- [ ] Structured events emitted for all nine recovery outcomes (spec §5)
- [ ] `pytest packages/ai-parrot/tests -k dev_loop -x -q` passes; `ruff check` clean

---

## Test Specification

```python
def test_fingerprint_is_deterministic():
    assert fp(brief_a, policy) == fp(brief_a_copy, policy)
    assert fp(brief_a, policy) != fp(brief_b, policy)

async def test_same_run_id_different_input_rejected(checkpoint_store):
    with pytest.raises(CheckpointFingerprintMismatchError):
        await coordinator.prepare(workflow="dev-loop", run_id="r1",
                                  brief=changed_brief, ...)

async def test_recovered_worktree_requires_expected_branch(tmp_repo):
    """Worktree removed / wrong branch / missing spec file -> explicit error."""
```

---

## Agent Instructions

1. Read spec §2 (Overview, Data Models, New Public Interfaces), §3 Module 3,
§7. 2. TASK-2622..2624 must be in `sdd/tasks/completed/`; grep their actual
merged signatures — do not trust this file's forward references blindly.
3. Index → `in-progress`; implement; move to completed; index → `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
