---
id: FC-017
query_id: Q036
type: grep
intent: "Find the AHP session gate implementation (TTL fail-closed/fail-open) referenced by the source."
executed_at: 2026-10-30T16:44:46Z
duration_ms: 500
parent_id: null
depth: 0
---

# FC-017 — `ApprovalGate` in `flows/dev_loop/session_state.py`: kinds (manual_criterion, deployment_approval, revision_approval, plan_approval), `on_expiry: fail|approve`, `open_gate(ttl_seconds)` / `wait_gate`, TTL sweep emits GateExpired or auto-approve

## Summary

The AHP gate machinery is real and already encodes the source's semantics: `on_expiry="fail"` is fail-closed (mandatory for irreversible effects; "silence ≠ consent"), `"approve"` is fail-open by `system:ttl-auto-approve` for advisory gates. Session status `awaiting_gate`; actions `GateOpened`/`GateResolved`/`GateExpired`; errors `GateNotFoundError`/`GateAlreadyResolvedError`. A stage's approve_or_request_changes gate would be a new `GateKind` with `payload_ref` pointing at contributions.

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

## Notes

Gates are session-state actions of the dev_loop, not a generic flows/core primitive — reuse implies depending on dev_loop session state or lifting the gate into core.
