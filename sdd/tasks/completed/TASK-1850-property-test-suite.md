# TASK-1850: Hypothesis property suite — fold invariant, totality, arbitration, schema export

**Feature**: FEAT-322 — AHP-style Session State, Host & HITL Approval Gates for dev-loop
**Spec**: `sdd/specs/agent-host-protocol-session-state.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1849
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The determinism invariant `fold(log) == state` is the
foundation the Svelte client port and the crash-rebuild path both rely on
(spec §1 G1, §7 "Host crash mid-run"). This task encodes it (and the other
contract-level guarantees) as hypothesis property tests so any future
reducer change that breaks determinism fails CI, plus the transport-purity
and JSON-Schema export gates.

---

## Scope

- Create `packages/ai-parrot/tests/flows/dev_loop/test_session_state_properties.py`:
  - **Strategies**: composite hypothesis strategies generating arbitrary
    valid actions from the full `DevLoopAction` union (random node_ids from
    the NodeId Literal, random gate lifecycles where `gate/opened` precedes
    resolve/expire for *some* sequences but NOT always — invalid orderings
    must also be generated to prove totality) and root actions.
  - **P1 fold-replay equivalence**: for random action sequences applied via
    `host.apply`, `functools.reduce(reduce, [e.action for e in host.replay_since(0)], DevLoopSessionState(run_id=..., channel=...)) == host.state`.
  - **P2 reducer totality**: `reduce(state, action)` never raises for any
    generated (state, action), including terminal states and dangling
    gate/dispatch references.
  - **P3 terminal stickiness**: once phase ∈ {succeeded, failed, cancelled},
    no subsequent action changes `phase`.
  - **P4 arbitration**: for any sequence containing ≥2 resolves of one gate
    via `host.resolve_gate`, exactly one `gate/resolved` envelope exists and
    later calls raised `GateAlreadyResolvedError`.
  - **P5 expiry policies**: pending gates past `expires_at` swept with
    `on_expiry="fail"` end `expired`; `"approve"` end `approved` with
    `resolved_by == "system:ttl-auto-approve"`.
  - **P6 root reducer totality + fold** for `RootAction` sequences.
  - **Transport purity**: assert `parrot.flows.dev_loop.session_state`
    module namespace / `sys.modules` deps include no `aiohttp`, no `redis`,
    no `jsonrpc` (inspect `session_state.__dict__` imports or ast-parse the
    source for import statements — ast approach preferred, it is exact).
  - **Schema export**: `TypeAdapter(DevLoopAction).json_schema()` contains
    `oneOf` (or `anyOf` per pydantic version — assert discriminated mapping
    present via `"discriminator"` key) — the Svelte codegen hook (spec §5).

**NOT in scope**: integration tests with Redis/WS (later tasks); golden
fixtures for nav-admin (separate repo, non-goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/test_session_state_properties.py` | CREATE | hypothesis property suite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from hypothesis import given, settings, strategies as st   # dev-dep, already used in repo tests
from pydantic import TypeAdapter                            # pydantic v2
from parrot.flows.dev_loop.session_state import (           # created by TASK-1848/1849
    ActionEnvelope, ApprovalGate, DevLoopAction, DevLoopSessionState,
    GateAlreadyResolvedError, RootAction, RunRegistryState, SessionHost,
    reduce, reduce_root, session_channel,
)
import ast, functools, inspect
```

### Existing Signatures to Use
```python
# SessionHost (TASK-1849): apply/replay_since/resolve_gate/open_gate/
#   expire_due_gates — see spec §2 New Public Interfaces.
# Initial state construction: DevLoopSessionState(run_id=r, channel=session_channel(r))
#   (sketch SessionHost.__init__ does exactly this).
```

### Does NOT Exist
- ~~`session_state.fold(...)`~~ — there is no fold helper; the property IS
  `functools.reduce` over replayed actions (add a local helper in the test)
- ~~pytest markers `@pytest.mark.property`~~ — none defined in this repo;
  plain test functions
- ~~`hypothesis` strategies for pydantic models out of the box~~ — write
  explicit `st.builds(...)` strategies per action class

---

## Implementation Notes

### Key Constraints
- Keep `max_examples` moderate (e.g. `@settings(max_examples=200)`) so the
  suite stays under ~30s; deadline=None for the host-loop properties.
- Generate ts values with `st.floats(min_value=1e9, max_value=2e9, allow_nan=False)`.
- The invalid-ordering generation (resolve before open, duplicate expiry) is
  what proves totality — do not filter those out for P2.
- For P4 use `host.resolve_gate` (host path), for P2 feed raw `GateResolved`
  actions through `reduce` (reducer path) — the two layers are asserted
  separately (spec §7 "Late/duplicate GateResolved").

---

## Acceptance Criteria

- [ ] P1–P6 implemented and passing
- [ ] Transport-purity test parses session_state.py imports and rejects aiohttp/redis/jsonrpc
- [ ] Schema-export test asserts discriminator mapping on the action union
- [ ] Suite runs green: `pytest packages/ai-parrot/tests/flows/dev_loop/test_session_state_properties.py -v`
- [ ] Full dev-loop test dir still green: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] `ruff check` clean on the new test file

---

## Test Specification

```python
@given(actions=action_sequences())
def test_fold_replay_equals_state(actions): ...

@given(state=states(), action=any_action())
def test_reducer_total_never_raises(state, action): ...

@given(actions=action_sequences_with_terminal())
def test_terminal_phase_sticky(actions): ...

def test_no_transport_imports(): ...
def test_action_union_schema_has_discriminator(): ...
```

---

## Agent Instructions

1. Read spec §4 Test Specification + §5 Acceptance Criteria rows 1–3.
2. Verify TASK-1849 in `sdd/tasks/completed/`.
3. Implement; run the whole dev_loop test dir; move to completed; update index.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-22
**Notes**: Created `test_session_state_properties.py` with P1-P6 hypothesis
properties, an AST-based transport-purity gate, and JSON-Schema
discriminator-export tests for both `DevLoopAction` and `RootAction`.
13 property tests, `max_examples` 50-200 per property (deadline=None for
host-loop properties per the task's constraint), suite runs in ~3-8s.
Full `pytest packages/ai-parrot/tests/flows/dev_loop/` run: 444 passed +
66 in the two session_state files (510 total in-scope), 4 pre-existing
failures in `test_server_repo_wiring.py`/`test_webhook.py` verified
unrelated (reproduce identically with the new test files excluded —
a pre-existing test-isolation issue outside this feature's scope).

**Deviations from spec**:
1. **`hypothesis` dev-dependency added** (`packages/ai-parrot/pyproject.toml`,
   `dev` extra). The task's Codebase Contract claimed hypothesis was
   "already used in repo tests" — verified stale (grepped the full repo;
   not installed, not referenced anywhere). Added `hypothesis>=6.100` and
   installed it into the shared venv; this was necessary infrastructure,
   not a design change.
2. **Two-line reducer fix in `session_state.py`** (`reduce()`, `run/created`
   and `run/closed` branches): writing the P3 property test
   (`test_terminal_phase_sticky`, mandated by this task's own acceptance
   criteria and the spec's Test Specification table) surfaced that the
   design sketch's `run/created`/`run/closed` handlers unconditionally set
   `phase`, unlike `run/cancelled` which already guards
   `state.phase in _TERMINAL_PHASES`. Added the same guard to the other two
   run-lifecycle actions so a late/duplicate action replayed against an
   already-terminal state can never resurrect/flip `phase` — required for
   the universal "terminal phases sticky" invariant (spec §5 AC, §7). No
   other reducer behavior changed; this task's file list did not name
   `session_state.py`, but the fix is a minimal, same-pattern correction in
   the same feature's core module, directly required to pass a mandated
   acceptance criterion of this task.
