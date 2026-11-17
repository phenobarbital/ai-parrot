---
id: FW-010
query_id: Q010
type: wiki_page
intent: "AHP session-state spec: gate semantics"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
---

# FW-010 — FEAT-322 `SessionHost.open_gate/wait_gate/resolve_gate` with `ApprovalGate(kind, on_expiry="fail"|"approve", ttl)` is the reusable gate primitive; `GateKind` is a closed Literal of four dev-loop kinds

## Summary

Spec FEAT-322 (approved, implemented in `flows/dev_loop/session_state.py`) defines frozen `DevLoopSessionState`, a closed action union folded by a pure `reduce()`, and `SessionHost` with `open_gate(kind, node_id, title, instructions, payload_ref, ttl_seconds, on_expiry)`, `wait_gate(gate_id)` (asyncio.Event-backed), `resolve_gate(...)` (first-writer-wins, validated before sequencing), `expire_due_gates()`. `ApprovalGate` (session_state.py:297, `on_expiry` :309) is per-kind fail-closed/fail-open with conf-overridable TTL defaults (deployment 24h fail, manual_criterion 72h fail, plan_approval 4h approve). `GateKind = Literal["manual_criterion","deployment_approval","revision_approval","plan_approval"]` and `NodeId` are closed Literals tied to the dev-loop roster. Commands arrive via REST `POST /runs/{run_id}/gates/{gate_id}/resolve`.

## Citations

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

Reusing AHP gates for an expert stage's `approve_or_request_changes` requires widening the closed `GateKind`/`NodeId` Literals (or a parallel generic host): the current host is dev-loop-specific by type. `payload_ref` is a by-reference field — fits "contributions as evidence" where the gate payload is a path, not a body.
