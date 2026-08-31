# TASK-2610: Integration tests, SDK interop and documentation

**Feature**: FEAT-477 — Expose an AI-Parrot Agent as an MCP Server
**Spec**: `sdd/specs/mcp-as-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2603, TASK-2605, TASK-2606, TASK-2607, TASK-2608, TASK-2609
**Assigned-to**: unassigned

---

## Context

Closes spec §4 **Integration Tests** and the documentation acceptance criteria in §5.

Per spec §5 "Deferred evidence", the **API-key path is the first vertical slice** — it has
no navigator-auth dependency and must be demonstrated end-to-end at merge time. The OAuth
path is tested with the introspection and PRM legs **mocked**; one live conformance run is
a post-release gate, not a merge blocker.

---

## Scope

- `test_api_key_end_to_end` — Claude Code path: API key → `initialize` → `tools/list` →
  `tools/call` → audited result. No navigator-auth dependency.
- `test_oauth_end_to_end_mocked` — discovery → 401 challenge → token → filtered list →
  call, with introspection and PRM mocked.
- `test_agent_isolation_across_mounts` — a token for agent A cannot call agent B (G3).
- `test_no_regression_tool_level_server` — **G11**: the existing tool-level MCP server and
  its transports behave unchanged.
- `test_a2a_agent_card_includes_decorated_methods` — the reification side effect: decorated
  methods appear as `AgentCard` skills.
- `test_mcp_sdk_interop` — drive the agent endpoint with the reference MCP SDK client,
  gated by the **existing** `requires_mcp_sdk` marker.
- Documentation: an agent-author guide (how to declare an MCP surface with `@mcp_tool`) and
  a platform-engineer guide (how to mount agents, configure audience, Redis requirement).

**NOT in scope**: changing implementation behavior. If an integration test fails, fix the
owning task's module — do not weaken the test.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/mcp/test_agent_mcp_integration.py` | CREATE | Integration suite |
| `packages/ai-parrot-server/tests/mcp/test_agent_mcp_interop.py` | CREATE | MCP SDK interop, `requires_mcp_sdk`-gated |
| `docs/mcp/agent-as-mcp-server.md` | CREATE | Agent-author + platform-engineer guides |

---

## Codebase Contract (Anti-Hallucination)

> VERIFIED against `dev` on 2026-08-31.

### Verified Imports
```python
from parrot.mcp.agent_tools import mcp_tool, AgentMethodTool          # TASK-2599/2600
from parrot.mcp.agent_mount import AgentMCPMount                      # TASK-2602
from parrot.mcp.config import AuthMethod, MCPServerConfig, AgentMCPMountConfig
from parrot.mcp.oauth_server import APIKeyStore, ExternalOAuthValidator
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/mcp/oauth_server.py
class APIKeyStore:                     # :41
    def issue_key(...)                 # :53
    def validate_key(self, key: str) -> Optional[APIKeyRecord]    # :119
    def revoke_key(self, key: str) -> bool                        # :142
class ExternalOAuthValidator:          # :211
    async def validate_token(self, token) -> Optional[Dict[str, Any]]   # :244
    def clear_cache(self) -> None      # :322   <-- use between tests to avoid cache bleed

# packages/ai-parrot-server/src/parrot/a2a/server.py
def get_agent_card(self) -> AgentCard                    # :334
def _build_skills_from_tools(self) -> List[AgentSkill]   # :400
```

### Test Marker (already exists — do NOT re-add)
```toml
# packages/ai-parrot-server/pyproject.toml — added by PR #1274
requires_mcp_sdk   # gate the reference-client interop test on this
```

### Does NOT Exist
- ~~A live navigator-auth AS reachable from CI~~ — FEAT-095 is unreleased and its code is
  **not on navigator-auth `dev`** (3 unmerged commits). Mock the introspection and PRM legs.
- ~~`mcp` (official SDK) as a runtime dependency~~ — it is **test-only**, behind
  `requires_mcp_sdk`. Do not add it to runtime deps.
- ~~An existing `tests/mcp/test_agent_mcp_integration.py`~~ — you are creating it.

---

## Implementation Notes

### Key Constraints
- The API-key slice must pass with **no** navigator-auth involvement at all — that is what
  makes it the merge-time evidence.
- Call `ExternalOAuthValidator.clear_cache()` (`:322`) between OAuth tests; the 5-minute
  introspection cache will otherwise leak state across cases.
- The regression test (G11) must exercise the **pre-existing** tool-level server, not the
  agent mount.
- Docs must state the two operational facts an operator cannot guess: the endpoint must be
  publicly routable for Claude Web, and **Redis is a hard requirement** for agent MCP
  endpoints (sessions + job handles).
- Docs must also record the current tenancy limitation: one mount serves one tenant until
  navigator-auth emits a tenant claim (spec §8 blocking request).

### References in Codebase
- `packages/ai-parrot-server/tests/mcp/test_streamable_http.py` — existing transport test style
- `packages/ai-parrot-server/tests/mcp/test_streamable_http_interop.py` — existing SDK-gated interop test

---

## Acceptance Criteria

- [ ] `test_api_key_end_to_end` passes with no navigator-auth dependency
- [ ] `test_oauth_end_to_end_mocked` covers discovery → 401 → token → filtered list → call
- [ ] `test_agent_isolation_across_mounts` proves a token for A cannot call B
- [ ] `test_no_regression_tool_level_server` passes (G11)
- [ ] `test_a2a_agent_card_includes_decorated_methods` passes
- [ ] `test_mcp_sdk_interop` is gated by `requires_mcp_sdk` and passes when the SDK is present
- [ ] `docs/mcp/agent-as-mcp-server.md` covers both audiences and states the Redis
      requirement, the public-routability requirement, and the tenancy limitation
- [ ] Full suite passes: `pytest packages/ai-parrot-server/tests/mcp/ -v`
- [ ] No linting errors

---

## Test Specification

```python
class TestAgentMCPIntegration:
    async def test_api_key_end_to_end(self, client, api_key):
        h = {"Authorization": f"Bearer {api_key}"}
        assert (await client.post("/mcp/agents/finance", json=init_req, headers=h)).status == 200
        listed = await (await client.post("/mcp/agents/finance", json=list_req, headers=h)).json()
        assert "forecast" in [t["name"] for t in listed["result"]["tools"]]
        called = await (await client.post("/mcp/agents/finance", json=call_req, headers=h)).json()
        assert called["result"]["isError"] is False

    async def test_oauth_end_to_end_mocked(self, client, mock_introspection):
        r = await client.post("/mcp/agents/finance", json=init_req)
        assert r.status == 401 and "resource_metadata=" in r.headers["WWW-Authenticate"]
        # ... token -> filtered list -> call

    async def test_agent_isolation_across_mounts(self, client, token_for_finance):
        h = {"Authorization": f"Bearer {token_for_finance}"}
        assert (await client.post("/mcp/agents/hr", json=call_req, headers=h)).status == 401

    async def test_no_regression_tool_level_server(self, tool_level_client):
        assert (await tool_level_client.post("/mcp", json=init_req)).status == 200

    def test_a2a_agent_card_includes_decorated_methods(self, a2a_server):
        assert "forecast" in [s.name for s in a2a_server.get_agent_card().skills]

@pytest.mark.requires_mcp_sdk
async def test_mcp_sdk_interop(agent_endpoint_url):
    """Drive the agent endpoint with the reference MCP client."""
```

---

## Agent Instructions

1. **Read the spec** — §4 Integration Tests, §5 Acceptance Criteria and its deferred-evidence notes.
2. **Check dependencies** — TASK-2603, 2605, 2606, 2607, 2608, 2609 all completed.
3. **Verify the Codebase Contract**. 4. **Update status** → `"in-progress"`.
5. **Implement** — if a test fails, fix the owning module, never the assertion.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`. 8. **Update index** → `"done"`. 9. **Completion Note**.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
