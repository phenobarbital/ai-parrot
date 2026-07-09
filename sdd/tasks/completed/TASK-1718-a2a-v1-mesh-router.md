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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-09
**Notes**:
- **Fixed the temporary gap flagged in TASK-1713's own Completion Note**:
  `A2AProxyRouter.get_agent_card()` constructed `AgentCard(url=None, ...)`,
  which raised `TypeError` after TASK-1713 removed `url` from `AgentCard`'s
  constructor. Changed to `supported_interfaces=[]` (the URL is genuinely
  unknown until the router is mounted/a request arrives) — `_handle_discovery`
  already does `card.url = f"{scheme}://{host}"`, which now correctly writes
  through the `AgentCard.url` property setter (TASK-1713) to populate
  `supported_interfaces` in place.
- `RegisteredAgent` (models.py) gained `protocol_version: str = "0.3"`.
  `A2AMeshDiscovery._discover_endpoint()` now captures
  `client._server_version` INSIDE the `async with A2AClient(...) as client:`
  block (right after `discover()`, before `disconnect()` runs) and passes it
  as `protocol_version=` when constructing the `RegisteredAgent` — read
  after the context manager exits, `_server_version` would still be
  set, but capturing while still connected is more defensive against future
  `disconnect()` changes.
- Verified via `grep` that neither `mesh.py` nor the rest of `router.py`
  ever read `card.url`/`card.preferred_transport`/`card.protocol_version`
  directly — all existing code paths use `RegisteredAgent.url` /
  `endpoint.url` (a plain str field unrelated to `AgentCard.url`), so the
  `AgentCard.url` property (TASK-1713) already makes those call sites work
  transparently. No other mesh.py changes were needed.
- `A2AProxyRouter`: added `_get_request_version()` (mirrors
  `A2AServer._get_request_version()` from TASK-1714, but falls back to v0.3
  for unrecognized values instead of raising — the router is a best-effort
  aggregator across potentially many differently-versioned agents, not the
  authoritative endpoint for any single one, so a hard 400 felt wrong here;
  flagging this as a deliberate, documented divergence from the server's
  stricter negotiation). `_handle_discovery` now emits
  `card.to_dict(version=version)` — v1.0.0 callers get the aggregated
  `supportedInterfaces` card format.
- Added `_apply_version_header(client, version_header)`: forwards an
  incoming `A2A-Version` header onto a downstream `A2AClient`'s live
  session headers. `route_message()` / `route_message_stream()` both gained
  an optional `version_header` kwarg; `_handle_message` / `_handle_stream`
  read `request.headers.get("A2A-Version")` and pass it through — satisfies
  the task's Key Approach #2 ("at minimum, forward the version header so
  each agent handles its own negotiation") without requiring per-request
  client instances (the existing per-agent client cache in `_get_client()`
  is preserved; only the live session's header is mutated per call).
- `_handle_message`'s `task.to_dict()` call also became version-aware
  (`task.to_dict(version=version)`), matching the caller's own negotiated
  version for the router's own response (separate from what was forwarded
  to the downstream agent).
- Did NOT add a `/.well-known/agent-card.json` route to the router's own
  `setup()` — not explicitly requested by this task's Scope (that was
  TASK-1714's ask for `A2AServer` specifically), and the existing single
  `/.well-known/agent.json` route already negotiates format via the
  `A2A-Version` header regardless of URL path, consistent with how
  `A2AServer` itself handles the SAME header-based negotiation on both its
  routes. Flagging this as a scope boundary decision, not an oversight.
- New test file `packages/ai-parrot/tests/test_a2a_v1_mesh_router.py`
  (10 tests): `RegisteredAgent.protocol_version` (default + explicit),
  `A2AMeshDiscovery` still instantiates, `get_agent_card()` builds without
  the removed `url` kwarg + the setter works once "mounted",
  `_get_request_version()`, `_apply_version_header()`, and an end-to-end
  discovery-handler test for both v1.0 and v0.3 formats via a live aiohttp
  `TestClient`.
- Regression: full TASK-1712-1717 test suites (166 tests total across both
  packages) still pass. `ruff check` clean on all touched files (one
  pre-existing `F841` on an unrelated line in `router.py`, confirmed via
  `ruff check` against `dev` directly, left untouched).
**Deviations from spec**: `_get_request_version()`'s fallback-to-v0.3 (vs.
`A2AServer`'s hard 400) for unrecognized versions, and not adding a second
well-known route to the router — both documented above as deliberate,
narrow scope decisions with no test/AC pinning the alternative.
