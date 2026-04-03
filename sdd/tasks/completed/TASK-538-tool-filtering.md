# TASK-538: Tool Filtering Integration

**Feature**: policy-based-access-control
**Spec**: `sdd/specs/policy-based-access-control.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-535, TASK-536
**Assigned-to**: unassigned

---

## Context

> Integrates PBAC-based tool filtering into `AgentTalk` handler. When the handler
> creates/clones a session-scoped ToolManager, it calls `Guardian.filter_resources()`
> to remove unauthorized tools BEFORE the agent sees them. Denied tools are invisible.
>
> Implements Spec Module 5.

---

## Scope

- In `AgentTalk`, after creating/cloning the session-scoped ToolManager:
  1. Get Guardian from `self.request.app['security']`
  2. Call `guardian.filter_resources(tools=tool_manager.tool_names, request=self.request,
     resource_type=ResourceType.TOOL, action="tool:execute")`
  3. Remove denied tools from the cloned ToolManager
- Handle edge case: Guardian not initialized (no PBAC) → skip filtering
- Handle edge case: Tools added mid-session via PATCH → re-evaluate on next request
- Ensure the original agent's ToolManager is NOT modified (only the session clone)

**NOT in scope**:
- Dataset filtering (TASK-539)
- MCP filtering (TASK-540)
- PBACPermissionResolver Layer 2 (already in TASK-536)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/agent.py` | MODIFY | Add Guardian.filter_resources() after ToolManager cloning |
| `tests/auth/test_tool_filtering.py` | CREATE | Tests for tool filtering integration |

---

## Implementation Notes

### Pattern to Follow
```python
# In AgentTalk, after cloning ToolManager for session:
async def _filter_tools_for_user(self, tool_manager):
    """Filter tools based on PBAC policies for current user."""
    guardian = self.request.app.get('security')
    if guardian is None:
        return  # PBAC not configured, skip filtering

    try:
        filtered = await guardian.filter_resources(
            resources=tool_manager.tool_names,
            request=self.request,
            resource_type=ResourceType.TOOL,
            action="tool:execute",
        )
        if filtered.denied:
            self.logger.info(
                "PBAC filtered %d tools for user: %s",
                len(filtered.denied), filtered.denied,
            )
            tool_manager.remove_tools(excluded=filtered.denied)
    except Exception as e:
        self.logger.error("PBAC tool filtering failed: %s", e)
        # Fail open or closed based on configuration
```

### Key Constraints
- Filtering happens at handler level, NEVER in middleware
- Only modify the cloned/session-scoped ToolManager, not the agent's original
- `tool_manager.tool_names` must return a list of string names for filtering
- Check if `remove_tools()` or equivalent method exists on ToolManager; if not,
  filter the tool list before setting it
- PolicyEvaluator LRU cache handles caching (30s TTL) — no manual caching needed
- Log filtered tools at INFO level for audit trail

### References in Codebase
- `parrot/handlers/agent.py` — AgentTalk POST method, session-scoped ToolManager swap
- `parrot/tools/manager.py` — ToolManager class, tool registration/removal methods
- `navigator_auth/abac/guardian.py` — Guardian.filter_resources()

---

## Acceptance Criteria

- [ ] Tools filtered via Guardian.filter_resources() at handler level
- [ ] Denied tools removed from session-scoped ToolManager clone
- [ ] Agent never sees denied tools (invisible, not error)
- [ ] Original agent ToolManager unmodified
- [ ] `tool:*` policy matches all tools
- [ ] `tool:jira_*` pattern matches jira_create, jira_search, etc.
- [ ] No PBAC configured → all tools visible (backward compatible)
- [ ] Guardian error → logged, tools remain visible (fail-open for safety)
- [ ] Tests pass: `pytest tests/auth/test_tool_filtering.py -v`

---

## Test Specification

```python
import pytest


class TestToolFiltering:
    async def test_denied_tools_invisible(self, agent_talk, mock_request_guest):
        """Guest user's ToolManager has restricted tools removed."""
        tool_manager = await agent_talk._get_session_tool_manager(mock_request_guest)
        tool_names = tool_manager.tool_names
        assert "admin_tool" not in tool_names
        assert "public_tool" in tool_names

    async def test_wildcard_policy_allows_all(self, agent_talk, mock_request_admin):
        """Admin with tool:* policy sees all tools."""
        tool_manager = await agent_talk._get_session_tool_manager(mock_request_admin)
        assert len(tool_manager.tool_names) > 0

    async def test_pattern_matching(self, agent_talk, mock_request_engineering):
        """Engineering user with tool:jira_* sees only jira tools."""
        tool_manager = await agent_talk._get_session_tool_manager(mock_request_engineering)
        tool_names = tool_manager.tool_names
        assert "jira_create" in tool_names
        assert "admin_delete" not in tool_names

    async def test_no_pbac_all_visible(self, agent_talk_no_pbac, mock_request):
        """Without PBAC configured, all tools visible."""
        tool_manager = await agent_talk_no_pbac._get_session_tool_manager(mock_request)
        # Should have all tools
        assert len(tool_manager.tool_names) > 0

    async def test_original_toolmanager_unmodified(self, agent_talk, mock_request_guest, agent):
        """Original agent ToolManager is not affected by filtering."""
        original_count = len(agent.tool_manager.tool_names)
        await agent_talk._get_session_tool_manager(mock_request_guest)
        assert len(agent.tool_manager.tool_names) == original_count
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-538-tool-filtering.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: Added _filter_tools_for_user() to AgentTalk. Called after session ToolManager
loaded in POST handler. Uses Guardian.filter_resources() when available (0.19.0+) or
PolicyEvaluator.filter_resources() as fallback. Calls remove_tool() for denied tools.
Fails open on any error.

**Deviations from spec**: none
