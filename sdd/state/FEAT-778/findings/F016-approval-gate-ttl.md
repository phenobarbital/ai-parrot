---
id: F016
query_id: Q036
type: grep
intent: "Find the AHP session gate implementation (TTL fail-closed/fail-open) referenced by the source."
executed_at: 2026-10-30T16:44:46Z
duration_ms: 500
parent_id: null
depth: 0
merged_from: [FC-017-approval-gate-ttl, FW-010-ahp-session-gates]
---

# F016 — `ApprovalGate` in `flows/dev_loop/session_state.py`: kinds (manual_criterion, deployment_approval, revision_approval, plan_approval), `on_expiry: fail|approve`, `open_gate(ttl_seconds)` / `wait_gate`, TTL sweep emits GateExpired or auto-approve

## Summary

*[FC-017-approval-gate-ttl]* The AHP gate machinery is real and already encodes the source's semantics: `on_expiry="fail"` is fail-closed (mandatory for irreversible effects; "silence ≠ consent"), `"approve"` is fail-open by `system:ttl-auto-approve` for advisory gates. Session status `awaiting_gate`; actions `GateOpened`/`GateResolved`/`GateExpired`; errors `GateNotFoundError`/`GateAlreadyResolvedError`. A stage's approve_or_request_changes gate would be a new `GateKind` with `payload_ref` pointing at contributions.

*[FW-010-ahp-session-gates]* Spec FEAT-322 (approved, implemented in `flows/dev_loop/session_state.py`) defines frozen `DevLoopSessionState`, a closed action union folded by a pure `reduce()`, and `SessionHost` with `open_gate(kind, node_id, title, instructions, payload_ref, ttl_seconds, on_expiry)`, `wait_gate(gate_id)` (asyncio.Event-backed), `resolve_gate(...)` (first-writer-wins, validated before sequencing), `expire_due_gates()`. `ApprovalGate` (session_state.py:297, `on_expiry` :309) is per-kind fail-closed/fail-open with conf-overridable TTL defaults (deployment 24h fail, manual_criterion 72h fail, plan_approval 4h approve). `GateKind = Literal["manual_criterion","deployment_approval","revision_approval","plan_approval"]` and `NodeId` are closed Literals tied to the dev-loop roster. Commands arrive via REST `POST /runs/{run_id}/gates/{gate_id}/resolve`.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`
  lines: 297-322
  symbol: `ApprovalGate`
  excerpt: |
    class ApprovalGate(_Frozen):
        gate_id: str; kind: GateKind; node_id: NodeId; status: GateStatus = "pending"
        on_expiry: Literal["fail", "approve"] = "fail"
        # "fail" → fail-closed ... "approve" → fail-open: GateResolved by "system:ttl-auto-approve"
        title: str; instructions: str; payload_ref: str; opened_at: float; expires_at: Optional[float]

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`
  lines: 168-178
  symbol: `session status / gate kinds`
  excerpt: |
    "awaiting_gate",  # blocked on a pending ApprovalGate (HITL)
    "deployment_approval", "revision_approval", "plan_approval"

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`
  lines: 655-680
  symbol: `GateOpened / GateResolved / GateExpired`
  excerpt: |
    class GateOpened(_ActionBase): gate: ApprovalGate  # status MUST be "pending"
    class GateResolved(_ActionBase): ...
    class GateExpired(_ActionBase): ...

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`
  lines: 1510-1598
  symbol: `open_gate / wait_gate`
  excerpt: |
    ttl_seconds: Optional[int] = None, ... expires_at=(now + ttl_seconds) if ttl_seconds else None
    resolved_by="system:ttl-auto-approve", comment="TTL expired; fail-open policy."
    async def wait_gate(self, gate_id: str) -> ApprovalGate:

- path: `sdd/specs/agent-host-protocol-session-state.spec.md`
  symbol: `FEAT-322 ApprovalGate / SessionHost`
  wiki_page_id: file:sdd/specs/agent-host-protocol-session-state.spec.md
  score: 1.00
  excerpt: |
    GateKind = Literal["manual_criterion","deployment_approval","revision_approval","plan_approval"]
    class ApprovalGate(_Frozen):
        gate_id: str; kind: GateKind; node_id: NodeId; status: GateStatus
        on_expiry: Literal["fail", "approve"] = "fail"
    class SessionHost:
        def open_gate(self, *, kind, node_id, title, instructions="", payload_ref="", ttl_seconds=None, on_expiry="fail")
        def wait_gate(self, gate_id: str) -> Awaitable[ApprovalGate]
        def resolve_gate(self, gate_id, resolution, resolved_by, comment="") -> ActionEnvelope

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`
  lines: 297-309
  symbol: `ApprovalGate`
  excerpt: |
    class ApprovalGate(_Frozen):      # :297
        on_expiry: Literal["fail", "approve"] = "fail"   # :309

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`
  lines: 1502-1571
  symbol: `SessionHost.open_gate`
  excerpt: |
    def open_gate(self, ..., on_expiry: Literal["fail", "approve"] = "fail", ...)   # :1502-1511
        # :1553 ``on_expiry`` policy: "fail" -> GateExpired (fail-closed; ...
        if gate.on_expiry == "approve":   # :1571

## Notes

*[FC-017-approval-gate-ttl]* Gates are session-state actions of the dev_loop, not a generic flows/core primitive — reuse implies depending on dev_loop session state or lifting the gate into core.

*[FW-010-ahp-session-gates]* Reusing AHP gates for an expert stage's `approve_or_request_changes` requires widening the closed `GateKind`/`NodeId` Literals (or a parallel generic host): the current host is dev-loop-specific by type. `payload_ref` is a by-reference field — fits "contributions as evidence" where the gate payload is a path, not a body.
