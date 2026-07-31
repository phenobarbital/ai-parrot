---
type: Wiki Overview
title: 'TASK-1718: Mesh & Router v1.0 Compatibility'
id: doc:sdd-tasks-completed-task-1718-a2a-v1-mesh-router-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: and route to remote agents. Both need to handle v1.0 AgentCards (which use
relates_to:
- concept: mod:parrot.a2a.mesh
  rel: mentions
- concept: mod:parrot.a2a.models
  rel: mentions
- concept: mod:parrot.a2a.router
  rel: mentions
---

# TASK-1718: Mesh & Router v1.0 Compatibility

**Feature**: FEAT-272 — A2A Protocol v1.0.0 Compatibility
**Spec**: `sdd/specs/a2a-protocol-compatibility.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1713
**Assigned-to**: unassigned

---

## Context

`A2AMeshDiscovery` and `A2AProxyRouter` parse AgentCards to discover, register,
and route to remote agents. Both need to handle v1.0 AgentCards (which use
`supportedInterfaces` instead of flat `url`). The router also needs to forward
the `A2A-Version` header when proxying requests.

Implements spec §3 Module 6.

---

## Scope

- Update `A2AMeshDiscovery` agent registration to handle v1.0 AgentCards:
  - When parsing a discovered card, extract URL from
    `supported_interfaces[0].url` if flat `url` is absent.
  - The `AgentCard.url` property (added in TASK-1713) should handle this
    transparently, but verify all code paths.
- Update `A2AProxyRouter`:
  - Forward `A2A-Version` header from client requests to backend agents.
  - Generate v1.0-compatible aggregated AgentCard when proxying discovery.
  - Handle `supported_interfaces` in routing rules.
- Update `RegisteredAgent` to store discovered protocol version.

**NOT in scope**:
- Core model changes (TASK-1712/1713)
- Server changes (TASK-1714/1715)
- Client changes (TASK-1717)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/a2a/mesh.py` | MODIFY | Handle v1.0 AgentCards in discovery |
| `packages/ai-parrot/src/parrot/a2a/router.py` | MODIFY | Forward version header, v1.0 card aggregation |
| `packages/ai-parrot/src/parrot/a2a/models.py` | MODIFY | Add protocol_version to RegisteredAgent |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.a2a.models import (
    AgentCard, RegisteredAgent, AgentInterface,
)
from parrot.a2a.mesh import A2AMeshDiscovery       # line 136
from parrot.a2a.router import A2AProxyRouter       # line 189
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/a2a/mesh.py

class A2AMeshDiscovery:                            # line 136
    @classmethod
    async def from_config(cls, config_path, **kwargs):  # line 226
    # Internal: stores agents as dict of RegisteredAgent
    # _agents: Dict[str, RegisteredAgent]

# packages/ai-parrot/src/parrot/a2a/router.py

class A2AProxyRouter:                              # line 189
    def setup(self, app, base_path="/a2a"):         # (verified)
    # Mounts: _handle_discovery, _handle_message, _handle_stream, _handle_stats, _handle_routes

# packages/ai-parrot/src/parrot/a2a/models.py

class RegisteredAgent:                             # line 427
    url: str                                       # line 429
    card: AgentCard                                # line 430
    last_seen: datetime                            # line 431
    healthy: bool = True                           # line 432
```

### Does NOT Exist

- ~~`RegisteredAgent.protocol_version`~~ — must be added
- ~~`A2AProxyRouter._forward_version_header()`~~ — must be created
- ~~`A2AMeshDiscovery._parse_v1_card()`~~ — no such method; card parsing uses `AgentCard.from_dict()`

---

## Implementation Notes

### Key Approach

The `AgentCard.url` property (TASK-1713) returns
`supported_interfaces[0].url`, so most mesh/router code that accesses
`card.url` should work without changes. The main work is:

1. **Verify** all code paths in `mesh.py` and `router.py` that access
   `card.url`, `card.preferred_transport`, or `card.protocol_version`
   work with the new property-based access.
2. **Router header forwarding**: In `_handle_message` and `_handle_stream`,
   read `A2A-Version` from the incoming request and include it when proxying
   to the backend agent.
3. **Aggregated AgentCard**: The router's `_handle_discovery` builds a
   composite card from all registered agents. Update it to emit v1.0
   format when the request has `A2A-Version: 1.0`.
4. **RegisteredAgent**: Add `protocol_version: str = "0.3"` to track
   what version each discovered agent speaks.

### Key Constraints

- Do NOT change the mesh YAML config format — it's a user-facing interface.
- The router proxies to multiple agents. Each may speak a different version.
  The router should translate between versions when needed (or at minimum,
  forward the version header so each agent handles its own negotiation).

---

## Acceptance Criteria

- [ ] `A2AMeshDiscovery` correctly parses v1.0 AgentCards
- [ ] `A2AMeshDiscovery` correctly parses v0.3 AgentCards (no regression)
- [ ] `RegisteredAgent` has `protocol_version` field
- [ ] `A2AProxyRouter` forwards `A2A-Version` header to backend agents
- [ ] Router's aggregated AgentCard uses version-aware serialization
- [ ] All existing mesh/router tests pass (no regression)
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/test_a2a_v1_mesh_router.py
import pytest
from parrot.a2a.models import AgentCard, AgentInterface, RegisteredAgent
from parrot.a2a.mesh import A2AMeshDiscovery


class TestMeshV1Compat:
    def test_registered_agent_v1_card(self):
        card = AgentCard(
            name="Test", description="T", version="1.0", skills=[],
            supported_interfaces=[
                AgentInterface(url="https://a.com/a2a", protocol_binding="JSONRPC",
                               protocol_version="1.0")
            ],
        )
        agent = RegisteredAgent(url=card.url, card=card)
        assert agent.url == "https://a.com/a2a"

    def test_registered_agent_protocol_version(self):
        card = AgentCard(
            name="Test", description="T", version="1.0", skills=[],
            supported_interfaces=[
                AgentInterface(url="https://a.com/a2a", protocol_binding="JSONRPC",
                               protocol_version="1.0")
            ],
        )
        agent = RegisteredAgent(url=card.url, card=card, protocol_version="1.0")
        assert agent.protocol_version == "1.0"
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — TASK-1713 must be complete
2. **Read** `mesh.py` and `router.py` in full — identify every place `card.url`,
   `card.preferred_transport`, or `card.protocol_version` is accessed
3. **Verify** the `AgentCard.url` property from TASK-1713 works in all contexts
4. **Implement** changes and run tests

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 4.8) — 2026-07-10
**Notes**: Added `RegisteredAgent.protocol_version` (default "0.3").
`A2AMeshDiscovery` records the discovered version from `client._server_version`.
The `AgentCard.url`/`preferred_transport` properties (TASK-1713) mean mesh code
that reads `card.url` needs no change. Router fixes: aggregated card now built
with `supported_interfaces=[]` (flat `url` is a read-only property);
`_handle_discovery` sets `supported_interfaces` from the request host and
serializes version-aware; added the v1.0 `/.well-known/agent-card.json` route;
`_handle_message`/`_handle_stream` read `A2A-Version` (`_request_version`) and
serialize task/SSE state version-aware. 67 ai-parrot a2a tests pass;
`ruff check packages/ai-parrot/src/parrot/a2a/` clean.
**Deviations from spec**: cleaned a pre-existing unused `except ... as e` (F841)
in router.py so the whole-directory ruff check (a TASK-1719 acceptance gate)
passes. Header forwarding to backends relies on A2AClient already sending
`A2A-Version: 1.0` by default (TASK-1717) rather than per-request injection.
