# TASK-1848: Session-state core — frozen state trees, action unions, pure reducers

**Feature**: FEAT-322 — AHP-style Session State, Host & HITL Approval Gates for dev-loop
**Spec**: `sdd/specs/agent-host-protocol-session-state.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (first half). Creates the protocol-agnostic core of the
feature: the state models, the closed action unions, and the pure reducers
for both channels (session + root). The user-provided design sketch
`sdd/artifacts/devloop_session_state.py` is the authoritative blueprint —
this task lands it as a real module with the spec's §2 deltas. `SessionHost`
and the migration shims are TASK-1849 (same file, second pass).

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`
  starting from `sdd/artifacts/devloop_session_state.py` (copy structure,
  keep docstrings' intent):
  - `_Frozen` base (`frozen=True, extra="forbid"`), channel helpers
    (`ROOT_CHANNEL`, `session_channel`, `terminal_channel`,
    `changeset_channel` — neutral `parrot-*` scheme).
  - Literals: `NodeId` (9 ids, == definition.py roster), `NodeStatus`,
    `DispatchStatus`, `RunPhase`, `GateKind`, `GateStatus`.
  - State models: `DispatchState`, `NodeState`, `ApprovalGate`
    (with `on_expiry: Literal["fail","approve"] = "fail"`),
    `DevLoopSessionState`.
  - The 20-action `DevLoopAction` discriminated union (discriminator
    `"type"`), exactly the sketch's variants.
  - **Delta vs sketch (spec §2)**: `ActionOrigin` model
    (`client_id: str`, `client_seq: int`); `ActionEnvelope` gains
    `origin: Optional[ActionOrigin] = None` and
    `rejection_reason: str = ""`; `Snapshot` unchanged.
  - **Delta vs sketch (root channel, spec §2)**: `RunSummary`,
    `RunRegistryState` (`channel` defaults to `ROOT_CHANNEL`), root actions
    `RunAdded` / `RunSummaryChanged` / `RunRemoved`
    (`type: Literal["root/runAdded"| "root/runSummaryChanged" | "root/runRemoved"]`),
    `RootAction` union, and pure `reduce_root(state, action)`.
  - Pure `reduce()` exactly per sketch (helpers `_with_node`,
    `_with_dispatch`, `_recompute_phase`, `_TERMINAL_PHASES`; terminal
    phases sticky; unknown/late actions → no-op).
  - Exceptions: `GateNotFoundError(KeyError)`,
    `GateAlreadyResolvedError(RuntimeError)`.
  - `__all__` per sketch plus the new names.
- Basic unit tests (NOT the hypothesis suite — that is TASK-1850):
  construction, one reduce step per action type, root reducer steps,
  envelope round-trip with origin/rejection_reason.

**NOT in scope**: `SessionHost`, `wait_gate`, shims (TASK-1849);
hypothesis property tests (TASK-1850); any runner/flow/node/streaming edits.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` | CREATE | models + actions + reducers (host added by TASK-1849) |
| `packages/ai-parrot/tests/flows/dev_loop/test_session_state.py` | CREATE | basic unit tests (extended by later tasks) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field   # pydantic v2, core dep
# session_state.py imports ONLY pydantic + stdlib (typing, time, uuid).
# NO aiohttp / redis / jsonrpc imports — enforced by test in TASK-1850.
```

### Existing Signatures to Use
```python
# sdd/artifacts/devloop_session_state.py — the complete blueprint (735 lines).
# READ IT FIRST and transcribe; do not re-design. Key contracts:
def reduce(state: DevLoopSessionState, action: DevLoopAction) -> DevLoopSessionState: ...
class ActionEnvelope(_Frozen):   # sketch: channel, server_seq, action
class Snapshot(_Frozen):         # channel, state: DevLoopSessionState, from_seq: int

# packages/ai-parrot/src/parrot/flows/dev_loop/definition.py:36-44 —
# the node roster the NodeId Literal MUST match:
# intent_classifier bug_intake research development qa deployment_handoff
# failure_handler close revision_handoff

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:698 —
class DispatchEvent(BaseModel):
    kind: Literal["dispatch.queued","dispatch.started","dispatch.message",
        "dispatch.tool_use","dispatch.tool_result","dispatch.output_invalid",
        "dispatch.failed","dispatch.completed"]
    ts: float; run_id: str; node_id: str; payload: Dict[str, Any]
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop.session_state`~~ — this task creates it
- ~~`SessionHost` / `ActionOrigin` / `RunRegistryState` in-tree~~ — nowhere yet
- ~~any `ahp`/`a2a` package or import~~ — none in-tree; channel scheme is `parrot-*`
- ~~`server_seq` anywhere in-tree~~ — this module introduces the concept

---

## Implementation Notes

### Pattern to Follow
The sketch IS the pattern. House style: `model_copy(update=...)` for state
evolution; closed unions via `Annotated[Union[...], Field(discriminator="type")]`.
`reduce_root` mirrors `reduce`: total, non-raising, unknown → no-op;
`RunRemoved` of an unknown run_id → no-op.

### Key Constraints
- All models `frozen=True, extra="forbid"`.
- Reducers pure and total: never raise, never mutate, terminal phases sticky.
- Google-style docstrings + strict type hints on every public symbol.
- `model_json_schema()` on the action union must emit `oneOf` + `discriminator`
  (pydantic v2 does this for discriminated unions — do not customize).

---

## Acceptance Criteria

- [ ] Module imports cleanly: `from parrot.flows.dev_loop.session_state import reduce, DevLoopSessionState, ActionEnvelope, RunRegistryState, reduce_root`
- [ ] `NodeId` Literal matches definition.py roster exactly (9 ids)
- [ ] `ActionEnvelope` carries `origin` (default None) + `rejection_reason` (default "")
- [ ] One reduce step per action type verified by tests; terminal stickiness test passes
- [ ] `reduce_root` folds RunAdded/RunSummaryChanged/RunRemoved; unknown removal is a no-op
- [ ] Module imports only pydantic + stdlib
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_session_state.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_session_state.py
from parrot.flows.dev_loop.session_state import (
    ApprovalGate, DevLoopSessionState, GateOpened, GateResolved,
    NodeStarted, RunAdded, RunRegistryState, RunSummary,
    reduce, reduce_root, session_channel,
)

def test_reduce_node_started_sets_running(): ...
def test_reduce_gate_opened_sets_awaiting_gate(): ...
def test_reduce_conflicting_gate_resolve_is_noop(): ...
def test_terminal_phase_sticky_after_cancel(): ...
def test_root_run_added_and_removed(): ...
def test_envelope_origin_rejection_roundtrip(): ...
```

---

## Agent Instructions

1. **Read the spec** §2 (Data Models, New Public Interfaces) and §6.
2. **Read the sketch** `sdd/artifacts/devloop_session_state.py` end-to-end.
3. Verify the Codebase Contract anchors (definition.py roster, models.py:698).
4. Update index → `"in-progress"`; implement; verify criteria; move this file
   to `sdd/tasks/completed/`; index → `"done"`; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-22
**Notes**: Created `session_state.py` transcribing the design sketch's
state models, 20-action `DevLoopAction` union, `reduce()` (+ helpers),
and added the spec §2 deltas: `ActionOrigin`, `ActionEnvelope.origin`/
`.rejection_reason`, and the root channel (`RunSummary`,
`RunRegistryState` defaulting `channel=ROOT_CHANNEL`, `RunAdded`/
`RunSummaryChanged`/`RunRemoved`, `RootAction`, `reduce_root`).
`GateNotFoundError`/`GateAlreadyResolvedError` defined now (unused until
`SessionHost` lands in TASK-1849). `SessionHost`, `wait_gate`, and the
migration shims are intentionally NOT in this file yet — TASK-1849 is a
second pass on the same module per the task scope. 30 unit tests pass;
`ruff check` clean; verified the module imports only pydantic + stdlib.
`NodeId` Literal matches `definition.py`'s 9-id roster exactly.

Note for later tasks: the repo's local venv is shared across worktrees
via an editable install pointing at the main repo path; two Cython
`.so` build artifacts (`parrot/utils/types`, `parrot/utils/parsers/toml`)
are gitignored and therefore absent from a fresh worktree checkout,
which breaks `import parrot...` until copied over. Copied them manually
for this worktree; flagging in case later tasks in this feature (or
other worktrees) hit the same `ModuleNotFoundError: parrot.utils.types`.

**Deviations from spec**: none
