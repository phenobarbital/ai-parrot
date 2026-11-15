---
title: "Generic Gate Host"
summary: "The flow-independent human-approval gate: GateSpec/GateRecord, the kind registry, GateHost, SQLite and Redis gate stores, expiry policy and the dev-loop adapter."
---

# Generic Gate Host

## Purpose

A **gate** pauses a workflow until a human approves or rejects it. The gate core lives in
`parrot.bots.flows.core.gates` and knows nothing about the dev-loop, so expert stages and the dev-loop
share one implementation.

## Data model

- `GateSpec` — `kind`, `title`, `instructions`, `questions`, `ttl_seconds`, `on_expiry` (`"fail"` or `"approve"`),
  `pre_review` (name of an advisory reviewer). Frozen, `extra="forbid"`.
- `GateRecord` — persisted state: `gate_id`, `kind`, `owner`, `status` (`pending|approved|rejected|expired`),
  `spec`, `payload_ref`, `opened_at`, `expires_at`, `resolved_by`, `resolved_at`, `comment`, `answers`, `pre_review`.
- `GateEvent` — `opened`, `resolved` or `expired`, carrying the record.
- `GateError` with a `GateErrorCode`: `UNKNOWN_KIND`, `GATE_KIND_CONFLICT`, `NOT_FOUND`, `NOT_PENDING`, `STORE_UNAVAILABLE`.

## Kinds

A gate kind is a string that must be registered first: `register_gate_kind(kind, description=...)`. Registration is
process-wide and idempotent for the same description; registering the same kind with a different description raises
`GATE_KIND_CONFLICT`. `is_registered` and `registered_kinds` inspect it.

## GateHost

```python
from parrot.bots.flows.core.gates import GateHost, GateSpec, register_gate_kind
from parrot.bots.flows.core.gates.stores import resolve_gate_store

register_gate_kind("approval", description="Human approval between expert stages")
host = GateHost(resolve_gate_store())            # SQLite by default
record = await host.open(GateSpec(kind="approval", title="Ship it?"), owner="run1:intake")
await host.resolve(record.gate_id, "approved", resolved_by="user:alice", comment="ok")
```

- `open` persists a pending gate, optionally runs the `pre_review` hook and notifies a human (best effort).
  The pre-review verdict is **advisory**: it never resolves a gate.
- `resolve` raises `NOT_FOUND` for an unknown gate and `NOT_PENDING` when it was already resolved (first writer wins).
- `recover(now=...)` applies expiry: an elapsed gate becomes `expired` (fail closed) unless `on_expiry="approve"`, in which
  case it is approved by `system:ttl-auto-approve` (`AUTO_APPROVER`).
- `subscribe` registers async listeners for `GateEvent`; a failing listener never breaks the gate.

## Stores

`resolve_gate_store(backend=None, redis_client=None, sqlite_path=None)`: an explicit backend, else Redis when a client is
given, else SQLite at `<parrot home>/gates.sqlite`. A HelixDB backend is not implemented and raises `STORE_UNAVAILABLE`.
Any object with `put`, `get` and `pending` satisfies the `GateStore` protocol.

## Dev-loop

The dev-loop `SessionHost` runs on these records through `DevLoopGateAdapter` (`to_record` / `from_record`); the legacy
`ApprovalGate` envelopes are unchanged, so gates opened before an upgrade resolve afterwards. The record's `owner` is
`<run_id>:<node_id>`. The runner mirrors opened gates into the generic store when Redis is configured, and the REST
layer maps `NOT_FOUND` to 404 `unknown_gate` and `NOT_PENDING` to 409 `already_resolved`.

## Related

- [Expert stages and the scope grid](../experts/expert-stages-and-scope-grid.md)
- [AgentCrew and AgentsFlow](agentcrew-and-agentsflow.md)
