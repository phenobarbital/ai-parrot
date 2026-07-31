# TASK-1849: SessionHost — sequencing, gate arbitration, expiry sweep & migration shims

**Feature**: FEAT-322 — AHP-style Session State, Host & HITL Approval Gates for dev-loop
**Spec**: `sdd/specs/agent-host-protocol-session-state.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1848
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (second half). Adds the authoritative host object to
`session_state.py`: single-writer sequencing (`server_seq`), snapshot/replay,
first-writer-wins gate arbitration (validated BEFORE sequencing), the expiry
sweep, the `wait_gate` awaitable used by gate-opening nodes, and the two
migration shims that map today's ad-hoc events 1:1 into actions.

---

## Scope

- Extend `session_state.py` with `SessionHost` per the sketch, plus spec §2 deltas:
  - `__init__(self, run_id: str, *, on_envelope: Optional[Callable[[ActionEnvelope], None]] = None)`
    — the sink is how the runner XADDs envelopes; the host itself NEVER
    imports redis. Sink exceptions must be swallowed (never break apply).
  - `state` property, `snapshot()`, `replay_since(last_seen_server_seq)`.
  - `apply(action, origin: Optional[ActionOrigin] = None) -> ActionEnvelope`
    — sequence, fold via `reduce`, retain in `_log`, invoke `on_envelope`.
  - `resolve_gate(gate_id, resolution, resolved_by, comment="") -> ActionEnvelope`
    — validate `status == "pending"` BEFORE sequencing; raise
    `GateNotFoundError` / `GateAlreadyResolvedError` (message includes who
    resolved + status); on success `apply(GateResolved(...))`.
  - `open_gate(*, kind, node_id, title, instructions="", payload_ref="",
    ttl_seconds=None, on_expiry="fail") -> Tuple[str, ActionEnvelope]`.
  - `expire_due_gates(now=None) -> List[ActionEnvelope]` — per-gate
    `on_expiry` policy: `"fail"` → `GateExpired`; `"approve"` →
    `GateResolved(resolved_by="system:ttl-auto-approve", comment="TTL expired; fail-open policy.")`.
  - **Delta vs sketch**: `wait_gate(gate_id) -> Awaitable[ApprovalGate]` —
    asyncio.Event-backed; the event is set inside `apply` whenever a
    `gate/resolved` or `gate/expired` action for that gate folds; returns the
    resolved gate from state. Must work when called before OR after
    resolution (already-resolved gate → return immediately).
- Add migration shims (sketch verbatim): `_FLOW_EVENT_MAP`,
  `_DISPATCH_KIND_MAP`, `action_from_flow_event(event, node_id, ts, error="")`,
  `action_from_dispatch_event(kind, node_id, ts, payload=None)` — unknown
  input → `None`; error strings truncated to 500 chars.
- Unit tests: sequencing monotonic from 1, replay_since filtering,
  first-writer-wins (second resolve raises, log has exactly one
  `gate/resolved`), expiry both policies, `wait_gate` pre/post resolution,
  `on_envelope` sink invoked and its exceptions swallowed, shim 1:1 mappings.

**NOT in scope**: hypothesis property suite (TASK-1850); runner wiring
(TASK-1851); touching any existing file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` | MODIFY | add SessionHost + shims (from TASK-1848 base) |
| `packages/ai-parrot/tests/flows/dev_loop/test_session_state.py` | MODIFY | add host/arbitration/shim tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From TASK-1848 (same module — internal references, no imports needed):
# DevLoopAction, DevLoopSessionState, ActionEnvelope, ActionOrigin, Snapshot,
# ApprovalGate, GateResolved, GateExpired, GateOpened, reduce,
# GateNotFoundError, GateAlreadyResolvedError, session_channel
import asyncio, time, uuid                      # stdlib only
```

### Existing Signatures to Use
```python
# sdd/artifacts/devloop_session_state.py:550-669 — SessionHost blueprint
#   (apply/snapshot/replay_since/resolve_gate/open_gate/expire_due_gates).
# sdd/artifacts/devloop_session_state.py:676-725 — shim maps + functions.

# Event names the flow shim MUST map (flow.py, emitted prefixed "flow."):
#   node_started → NodeStarted · node_completed → NodeCompleted
#   node_failed → NodeFailed · node_skipped → NodeSkipped
# DispatchEvent.kind values the dispatch shim MUST map (models.py:698):
#   dispatch.queued/.started/.message/.tool_use/.tool_result/
#   .output_invalid/.failed/.completed
```

### Does NOT Exist
- ~~redis / aiohttp imports in session_state.py~~ — FORBIDDEN; envelope
  persistence goes through the `on_envelope` callable only
- ~~`SessionHost.resolve_gate` retrying or force flags~~ — first writer wins, period
- ~~thread-safety machinery (locks)~~ — single-writer by design, one host per
  run driven from the runner's event loop (document in the class docstring)

---

## Implementation Notes

### Key Constraints
- `apply` order: seq++ → build envelope → fold state → append log → set any
  matching gate waiter events → call `on_envelope` inside try/except.
- Arbitration is HOST-side (raise before sequencing); the REDUCER stays
  total (conflicting resolve = no-op) — both layers required (spec §7).
- `wait_gate` must not leak events: one `asyncio.Event` per gate_id, created
  lazily, discarded once resolved.
- Expiry sweep does not touch the reducer; it only emits actions.

---

## Acceptance Criteria

- [ ] `server_seq` starts at 1 and is monotonic; `replay_since(n)` returns only `> n`
- [ ] Second `resolve_gate` raises `GateAlreadyResolvedError` naming the first resolver; exactly one `gate/resolved` envelope in the log
- [ ] `expire_due_gates`: fail-closed → `GateExpired`; fail-open → `GateResolved` by `system:ttl-auto-approve` (audited in-state)
- [ ] `wait_gate` resolves for both orderings (await-then-resolve, resolve-then-await)
- [ ] `on_envelope` sink called per envelope; sink exceptions swallowed
- [ ] Shims map every documented event/kind 1:1; unknown → None
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_session_state.py -v`
- [ ] `ruff check` clean; module still imports only pydantic + stdlib

---

## Test Specification

```python
async def test_wait_gate_await_then_resolve(host): ...
async def test_wait_gate_already_resolved_returns_immediately(host): ...
def test_first_writer_wins_second_raises(host): ...
def test_expiry_fail_open_auto_approve_audited(host): ...
def test_on_envelope_sink_exception_swallowed(): ...
def test_shim_unknown_kind_returns_none(): ...
```

---

## Agent Instructions

1. Read spec §2 New Public Interfaces + §7; read the sketch's SessionHost.
2. Verify TASK-1848 is in `sdd/tasks/completed/`.
3. Implement; verify criteria; move to completed; update index; Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-22
**Notes**: Extended `session_state.py` with `SessionHost` (apply/snapshot/
replay_since/resolve_gate/open_gate/expire_due_gates/wait_gate) and the
migration shims (`_FLOW_EVENT_MAP`, `_DISPATCH_KIND_MAP`,
`action_from_flow_event`, `action_from_dispatch_event`) per the sketch,
plus the `on_envelope` sink (exceptions swallowed) and `origin` passthrough
on `apply`. `wait_gate` is implemented as `async def` (idiomatic Python
equivalent of the spec's `Awaitable[ApprovalGate]` return type) backed by
one lazily-created `asyncio.Event` per gate_id, set inside `apply` when a
matching `gate/resolved`/`gate/expired` folds, and discarded after wakeup;
works for both await-then-resolve and already-resolved orderings. 23 new
tests added (53 total in the file now) covering sequencing monotonicity,
replay filtering, first-writer-wins arbitration, both expiry policies,
sink-exception swallowing, `wait_gate` in both orderings + on expiry, and
1:1 shim mappings (incl. unknown→None and 500-char truncation). `ruff
check` clean; module still imports only pydantic + stdlib (asyncio/time/
uuid/typing — all stdlib).

**Deviations from spec**: none
