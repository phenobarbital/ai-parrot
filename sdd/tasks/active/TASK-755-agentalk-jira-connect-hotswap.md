# TASK-755: AgenTalk Integration — JiraConnectTool + Hot-Swap

**Feature**: FEAT-107 — Jira OAuth 2.0 (3LO) Per-User Authentication
**Spec**: `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-750, TASK-751, TASK-753
**Assigned-to**: unassigned

---

## Context

Module 9 of the spec. In AgenTalk (web chat via WebSocket), the agent session must detect whether a user has Jira tokens. If yes, register full `JiraToolkit(auth_type="oauth2_3lo")`. If not, register a lightweight `JiraConnectTool` placeholder that returns the auth URL. After successful OAuth callback, hot-swap: remove placeholder, register full toolkit, sync tools to the LLM.

---

## Scope

- Create `JiraConnectTool` — a simple tool that returns the OAuth auth URL when called.
- Modify `AgentTalk` (or its session setup) to:
  1. On session start, check if user has Jira tokens via `CredentialResolver`.
  2. If tokens exist: register `JiraToolkit(auth_type="oauth2_3lo")`.
  3. If no tokens: register `JiraConnectTool` placeholder.
- Implement hot-swap callback: after OAuth callback stores tokens, replace `JiraConnectTool` with full `JiraToolkit` mid-session.
- Write unit tests.

**NOT in scope**: Telegram commands (TASK-754), OAuth manager internals (TASK-751), callback routes (TASK-752).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/jira_connect_tool.py` | CREATE | JiraConnectTool placeholder |
| `packages/ai-parrot/src/parrot/handlers/agent.py` | MODIFY | Add Jira OAuth session setup logic |
| `packages/ai-parrot/tests/unit/test_agentalk_jira_connect.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.agent import AgentTalk  # verified: packages/ai-parrot/src/parrot/handlers/agent.py:47
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: packages/ai-parrot/src/parrot/tools/abstract.py:71,36
from parrot.tools.manager import ToolManager  # verified: packages/ai-parrot/src/parrot/tools/manager.py:202
from parrot.auth.credentials import CredentialResolver, OAuthCredentialResolver  # created by TASK-750
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/handlers/agent.py:47
class AgentTalk(BaseView):
    # WebSocket-based agent session handler
    # Has access to tool_manager for registering/removing tools

# packages/ai-parrot/src/parrot/tools/manager.py:202
class ToolManager:
    def add_tool(self, tool, name=None) -> None  # registers a tool
    def register_toolkit(self, toolkit) -> List[AbstractTool]  # registers all toolkit tools
    # _tools: Dict[str, Union[ToolDefinition, AbstractTool]]
```

### Does NOT Exist
- ~~`JiraConnectTool`~~ — does NOT exist yet (this task creates it)
- ~~`AgentTalk` Jira OAuth session setup~~ — does NOT exist yet (this task adds it)
- ~~`_sync_tools_to_llm()`~~ — referenced in spec but verify; seen in `examples/tool/o365.py:169` as an optional method

---

## Implementation Notes

### JiraConnectTool Design
```python
class JiraConnectTool(AbstractTool):
    """Placeholder tool that returns an auth URL when the user hasn't connected Jira."""

    name = "connect_jira"
    description = "Connect your Jira account to enable Jira tools. Returns an authorization link."

    def __init__(self, credential_resolver: CredentialResolver, channel: str, user_id: str):
        super().__init__(name=self.name, description=self.description)
        self._resolver = credential_resolver
        self._channel = channel
        self._user_id = user_id

    async def _execute(self, **kwargs) -> ToolResult:
        auth_url = await self._resolver.get_auth_url(self._channel, self._user_id)
        return ToolResult(
            success=True,
            status="authorization_required",
            result=f"Please authorize your Jira account: {auth_url}",
            metadata={"auth_url": auth_url, "provider": "jira"},
        )
```

### Hot-Swap Flow
After OAuth callback stores tokens in Redis:
1. The callback route (TASK-752) or a Redis pub/sub listener notifies the session.
2. The session removes `JiraConnectTool` from `tool_manager._tools`.
3. Registers full `JiraToolkit(auth_type="oauth2_3lo")`.
4. Calls `_sync_tools_to_llm()` if available (updates the LLM's tool list mid-conversation).

### Key Constraints
- The hot-swap must be thread-safe (WebSocket handler is async, callback is a separate HTTP request).
- If `_sync_tools_to_llm()` doesn't exist on the bot/agent, the new tools will be available on the next message exchange.
- The `JiraConnectTool` should look and behave like a regular tool from the LLM's perspective.

---

## Acceptance Criteria

- [ ] `JiraConnectTool` returns auth URL when called
- [ ] Session registers placeholder when user has no tokens
- [ ] Session registers full toolkit when user has tokens
- [ ] Hot-swap replaces placeholder with full toolkit after OAuth callback
- [ ] Tool list is updated mid-session (if `_sync_tools_to_llm` available)
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/test_agentalk_jira_connect.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_agentalk_jira_connect.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.tools.jira_connect_tool import JiraConnectTool


class TestJiraConnectTool:
    @pytest.mark.asyncio
    async def test_returns_auth_url(self):
        resolver = MagicMock()
        resolver.get_auth_url = AsyncMock(return_value="https://auth.atlassian.com/authorize?...")
        tool = JiraConnectTool(credential_resolver=resolver, channel="agentalk", user_id="u1")
        result = await tool._execute()
        assert result.status == "authorization_required"
        assert "auth.atlassian.com" in result.metadata["auth_url"]

    def test_tool_name_and_description(self):
        resolver = MagicMock()
        tool = JiraConnectTool(credential_resolver=resolver, channel="agentalk", user_id="u1")
        assert tool.name == "connect_jira"
        assert "Jira" in tool.description
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md` Module 9
2. **Check dependencies** — verify TASK-750, TASK-751, TASK-753 are in `tasks/completed/`
3. **Verify the Codebase Contract** — read `agent.py` for AgentTalk session setup patterns
4. **Check** if `_sync_tools_to_llm()` exists as a method on the bot/agent classes
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** following the scope and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-755-agentalk-jira-connect-hotswap.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
