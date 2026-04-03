# TASK-540: MCP Server Filtering Integration

**Feature**: policy-based-access-control
**Spec**: `sdd/specs/policy-based-access-control.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-535, TASK-538
**Assigned-to**: unassigned

---

## Context

> Extends the PBAC filtering pattern to MCP server access. Before registering external
> MCP server tools into the ToolManager, policies are checked. Denied MCP servers' tools
> are never registered — they're invisible to the agent.
>
> Implements Spec Module 7.

---

## Scope

- Before MCP server tools are registered into the session-scoped ToolManager:
  1. Get Guardian from `request.app['security']`
  2. Call `guardian.filter_resources(resources=mcp_server_names, request=request,
     resource_type=ResourceType.MCP, action="tool:execute")`
  3. Skip tool registration for denied MCP servers
- This happens in the handler (AgentTalk PATCH or where MCP servers are configured),
  NOT in the MCP integration module itself
- Follow the same pattern as TASK-538 (tool filtering)

**NOT in scope**:
- MCP server acting as server (only client/consumer side)
- Tool-level filtering within an allowed MCP server (TASK-538 handles that)
- MCP server authentication (separate concern)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/agent.py` | MODIFY | Add Guardian MCP filtering in PATCH handler |
| `tests/auth/test_mcp_filtering.py` | CREATE | Tests for MCP filtering |

---

## Implementation Notes

### Pattern to Follow
```python
# In AgentTalk PATCH handler, where MCP servers are configured:
async def _filter_mcp_servers_for_user(self, mcp_server_configs):
    """Filter MCP servers based on PBAC policies."""
    guardian = self.request.app.get('security')
    if guardian is None:
        return mcp_server_configs

    server_names = [cfg.name for cfg in mcp_server_configs]
    filtered = await guardian.filter_resources(
        resources=server_names,
        request=self.request,
        resource_type=ResourceType.MCP,
        action="tool:execute",
    )
    if filtered.denied:
        self.logger.info(
            "PBAC filtered %d MCP servers for user: %s",
            len(filtered.denied), filtered.denied,
        )
    return [cfg for cfg in mcp_server_configs if cfg.name in filtered.allowed]
```

### Key Constraints
- Filtering happens at handler level before MCP tools are registered
- Uses `ResourceType.MCP` (already defined in navigator-auth)
- Action: `tool:execute` (executing MCP server tools)
- MCP server names must match policy resource patterns (e.g., `mcp:github_*`)
- If MCP server is denied, ALL its tools are excluded (server-level granularity)

### References in Codebase
- `parrot/handlers/agent.py` — PATCH handler where MCP servers are configured
- `parrot/mcp/integration.py` — MCPToolProxy, MCP server registration
- `parrot/mcp/config.py` — MCPServerConfig

---

## Acceptance Criteria

- [ ] Denied MCP servers' tools not registered in ToolManager
- [ ] `mcp:*` policy matches all MCP servers
- [ ] `mcp:github_*` pattern matches github MCP server
- [ ] No PBAC → all MCP servers accessible (backward compatible)
- [ ] Tests pass: `pytest tests/auth/test_mcp_filtering.py -v`

---

## Test Specification

```python
import pytest


class TestMCPFiltering:
    async def test_denied_mcp_not_registered(self, handler, mock_request_restricted):
        """Restricted user cannot access admin MCP server."""
        configs = [mock_github_config, mock_admin_config]
        filtered = await handler._filter_mcp_servers_for_user(configs)
        names = [c.name for c in filtered]
        assert "github" in names
        assert "admin_server" not in names

    async def test_no_pbac_all_accessible(self, handler_no_pbac, mock_request):
        """Without PBAC, all MCP servers accessible."""
        configs = [mock_github_config, mock_admin_config]
        filtered = await handler_no_pbac._filter_mcp_servers_for_user(configs)
        assert len(filtered) == 2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-540-mcp-filtering.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: Added _filter_mcp_servers_for_user() to AgentTalk. Called in _setup_agent_tools()
before _add_mcp_servers(). Uses ResourceType.MCP for server-level filtering. Returns
all configs when no PBAC configured (backward compatible). Fails open on errors.

**Deviations from spec**: none
