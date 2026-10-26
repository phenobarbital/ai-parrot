# Roost — local inter-agent sub-protocol

**Roost** (FEAT-747) is the local sub-protocol agents in the same deployment use to talk to each other: typed
speech acts, per-conversation protocols, reply obligations, a capability directory and a shared blackboard.
Spec: `sdd/specs/local-inter-agent.spec.md`. Code: `packages/ai-parrot/src/parrot/roost/`.

## Roost vs Squawk

| | Squawk (FEAT-746) | Roost (FEAT-747) |
|---|---|---|
| Scope | Wire protocol, envelope, Cap'n Proto codec, catalog tools, Biscuit tokens | Agent-level semantics on top of an envelope |
| Package | `ai-parrot-squawk` satellite (`parrot.squawk`) | core `parrot.roost` |
| Dependency | none on Roost | optional runtime dependency on Squawk |

Roost never imports `parrot.squawk` at module level: only `parrot/roost/squawk_bridge.py` names it, probing it lazily
(`squawk_available()`). Without the satellite Roost **degrades, it does not fail**: messages ride Roost's own
`LocalEnvelope`, the bus uses `JsonEnvelopeCodec`, and `find_and_mount` returns `[]` with one warning per process.

## Building blocks

- **Performatives and protocols** — see [performatives.md](performatives.md).
- **Gating** — grants and policy gates decide who may message whom and which capabilities may be mounted; the
  serving endpoint resolves authority from `auth_token` when present, else from the serialized `PermissionContext`;
  with neither, PBAC fails closed.
- **Directory** — agents register capabilities; `find_agents` / `find_and_mount` search it (grant-filtered).
- **Blackboard** — shared keyed state with one writer per key and compare-and-set versions. In process it is a
  dict; on Matrix it is room state (`m.parrot.blackboard`), replaced on every write, never appended.
- **Carriers** — four ways to move messages, see [carriers.md](carriers.md).

## Quick start

```python
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import InteractionProtocol, Performative

msg = RoostMessage(
    performative=Performative.QUERY,
    protocol=InteractionProtocol.QUERY,
    conversation_id="c-1",
    sender=AgentAddress(name="planner"),
    receivers=[AgentAddress(name="analyst")],
    content={"question": "latest revenue?"},
)
```

Send it through the agent's `RoostEndpoint` (`send`, `inform`, `request`, `query`, `cfp`, `subscribe`, `cancel`).
