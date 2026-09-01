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

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-01
**Notes**: `test_agent_mcp_integration.py` (6 tests, all against a real
`aiohttp.test_utils.TestClient`/`TestServer`): `test_api_key_end_to_end` +
`test_api_key_rejected_without_key` (no navigator-auth dependency —
the merge-time evidence per spec §5), `test_oauth_end_to_end_mocked`
(discovery 401 with `resource_metadata=` -> mocked
`ExternalOAuthValidator.get_token_info` -> filtered `tools/list` ->
successful `tools/call`), `test_agent_isolation_across_mounts` (two
independent `AgentMCPMount`s sharing an OAuth `auth_template`; a token
audienced to finance's `resource_server_url` gets a clean 401 against hr's
mount — G3), `test_no_regression_tool_level_server` (G11, exercises the
pre-existing tool-level `StreamableHttpMCPServer` directly, no
`AgentMCPMount` involved), `test_a2a_agent_card_includes_decorated_methods`.
`test_agent_mcp_interop.py`'s `test_mcp_sdk_interop` drives a live
agent-mounted endpoint (API-key auth) with the **real** `mcp` SDK client
(`streamablehttp_client` + `ClientSession`) — `initialize`, `list_tools`,
`call_tool` all pass against the actual reification/mount/guard stack, not
a mock. `docs/mcp/agent-as-mcp-server.md` covers both audiences and states
all three required operational facts explicitly (public routability for
Claude Web, Redis as a hard requirement, the one-tenant-per-mount
limitation). Full `packages/ai-parrot-server/tests/mcp/` suite: 172 tests,
green. `ruff check` clean on every new/touched file (confirmed zero new
findings in `agent_mount.py`/`a2a/server.py` via before/after `git stash`
diffs — 96 pre-existing findings in `a2a/server.py`, unchanged).

**Deviations from spec — this task changed production code, and the
"NOT in scope: changing implementation behavior" line needs an honest
account of why.** Writing the literal integration tests this task
specifies (`test_api_key_end_to_end`, `test_oauth_end_to_end_mocked`,
`test_agent_isolation_across_mounts`) immediately proved they **could not
pass against `dev` as it stood** — not because of a bug in one task's
module, but because **no task in the FEAT-477 decomposition (2599–2609)
ever wired principal resolution or PBAC into the live per-agent server**:

- TASK-2604 built `resolve_principal()`/`_pctx_var` publication as a
  standalone module (`principal_guard.py`), explicitly scoped away from
  wiring ("NOT in scope: PBAC decisions... TASK-2605, consume it").
- TASK-2605 built `PBACGuard` in the *same* standalone module, also never
  touching `agent_mount.py` (not in its file list).
- TASK-2602's `agent_mount.py` (`_AgentBoundMCPServer`) called
  `super().handle_tools_list/call(params)` directly — the CORE, unguarded
  implementation — with no authentication configured on its per-agent
  `MCPServerConfig` at all (`auth_method` defaulted to `NONE`) and no
  audience (`oauth2_resource_server_url`) ever set from the mount's own
  `AgentMCPMountConfig.resource_server_url` (flagged explicitly in
  TASK-2608's own Completion Note as a known gap).

Per this task's own instruction — *"If an integration test fails, fix the
owning task's module — do not weaken the test"* — I fixed the owning
modules rather than write hollow tests that don't exercise PBAC/identity
at all (which would satisfy the letter of "tests pass" while contradicting
the acceptance criteria's actual content: "filtered list", "token for A
cannot call B", "audited result"). Concretely, in `agent_mount.py`
(`_AgentBoundMCPServer`):
- `_guard()` is now overridden to resolve the caller via
  `resolve_principal()` and publish it on `_pctx_var` (the exact mechanism
  TASK-2604 built for this).
- `handle_tools_list`/`handle_tools_call` now delegate to a `PBACGuard`
  built once per mounted agent, reading `_pctx_var` instead of calling the
  core implementation directly.
- A `_CoreDispatchProxy` shim gives `PBACGuard` a `.tools`/
  `handle_tools_call` surface that bypasses `_AgentBoundMCPServer`'s own
  override — without it, `PBACGuard.tools_call()`'s internal call to
  `server.handle_tools_call()` would recurse into itself forever.
- `AgentMCPMount` gained `pbac_resolver`/`audit_sink` constructor params
  (mirroring TASK-2603's `policy_filter` seam) and an `auth_template:
  MCPServerConfig` whose auth fields are copied onto every per-agent
  config via `dataclasses.replace()`; `oauth2_resource_server_url` is
  always taken from the mount's own `resource_server_url` regardless of
  the template (RFC 8707 audience scoping is mount-level per the spec's
  data model, not template-level).
- `_pctx_var` is set but not reset in a `finally` inside `_guard()` —
  documented in its docstring: aiohttp handles each inbound request as a
  distinct task with its own copy of the app-level context (no shared
  mutable state to leak into), and `asyncio.create_task()` (used by
  `_track()` for JSON-RPC dispatch) copies the context at creation time,
  so the published `PermissionContext` correctly reaches
  `handle_tools_list`/`handle_tools_call` however many tasks deep.
- `a2a/server.py`'s `_build_skills_from_tools()` gained an additive-only
  scan of `build_exposure_set(agent)` (guarded against `AttributeError`
  for agents with no `tool_manager`) — required because OQ2 means a
  decorated method is *never* in `tool_manager`, so the pre-existing
  `tool_manager`-only scan could never surface it, contradicting the
  spec's own narrative that reification surfaces methods in the
  `AgentCard` "for free". `a2a/server.py` is outside every FEAT-477 task's
  file list, but is explicitly named in TASK-2610's own Codebase Contract
  ("Existing Signatures to Use: `_build_skills_from_tools`") — the task
  anticipates this exact touch point.
- `test_pbac_guard.py` (TASK-2605's own test file) needed its `server`
  fixture changed from `AgentMCPMount(...).setup(app); mount._servers[
  "finance"]` to a plain `StreamableHttpMCPServer` with tools registered
  directly — calling the now-guarded `_AgentBoundMCPServer` with a
  *second*, standalone `PBACGuard` (as the file did before this task)
  double-guards and requires `_pctx_var` to already be published, which
  is `_guard()`'s job, not that file's unit-test job. Fixed by decoupling
  `PBACGuard`'s own unit tests from the mount entirely, which is also
  better test isolation than before.

Verified no regression across the full `packages/ai-parrot-server/tests/mcp/`
suite (172 tests) plus 119 tests across every `a2a`-related test module
directly exercising `A2AServer`/`AgentCard` (`test_a2a_v1_server.py`,
`test_a2ui_e2e.py`, `test_a2a_a2ui_dispatch.py`, `test_a2a_output_mode.py`,
`test_a2a_credential_gate.py`, `test_a2a_identity.py`,
`test_a2a_push_notifications*.py`, `test_a2a_resume_trigger.py`,
`test_a2a_v1_jsonrpc.py`, `test_a2a_bridge_e2e.py`,
`test_a2a_v1_roundtrip.py`).

**What is still not wired, flagged rather than silently gapped:**
resources' (`agent_resources.py`) `policy_filter` remains `None` by
default at the mount level — I did not thread `pbac_resolver` through to
resource-level filtering, since resources are built once at mount-setup
time without per-request `PermissionContext` available, and doing so would
require a further signature change to `register_agent_resources`/
`handle_resources_read` beyond this task's already-expanded scope. The
tool *catalog* resource (distinct from `tools/list` itself) is therefore
unfiltered by real PBAC today — a concrete, scoped follow-up.
