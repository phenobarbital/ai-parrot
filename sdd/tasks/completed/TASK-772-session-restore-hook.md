# TASK-772: Session Restore Hook — Auto-Restore User MCP Servers on PATCH

**Feature**: FEAT-110 — MCP Mixin Helper Handler
**Spec**: `sdd/specs/mcp-mixin-helper-handler.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-769, TASK-770, TASK-771
**Assigned-to**: unassigned

---

## Context

This task closes the persistence loop. When a user starts a new conversation with
an agent (triggering the PATCH endpoint), any previously-configured MCP servers must
be automatically restored — credentials retrieved from Vault, factory functions called,
and tools re-registered on the session ToolManager.

This makes MCP server activation a one-time operation per user per agent, rather than
something the frontend must repeat on every session.

Implements spec Section 3, Module 4.

---

## Scope

- Add `_restore_user_mcp_servers()` async method to `AgentTalk` class in `parrot/handlers/agent.py`.
- Call `_restore_user_mcp_servers()` from within `_setup_agent_tools()` (after the
  existing MCP server configuration block, before the Jira OAuth bootstrap).
- The restore method must:
  1. Get `user_id` from the request session.
  2. Call `MCPPersistenceService.load_user_mcp_configs(user_id, agent_id)` to get saved configs.
  3. For each config:
     a. If `vault_credential_name` is set, retrieve and decrypt the credential from DocumentDB.
     b. Look up the `create_*` factory function via the registry slug.
     c. Merge decrypted secrets with non-secret params.
     d. Call the factory function to build `MCPClientConfig`.
     e. Call `tool_manager.add_mcp_server(config)` to register the tools.
  4. Log each restored server at INFO level.
  5. Gracefully handle failures (missing Vault cred, connection error) — log WARNING
     and continue with remaining servers. Never fail the entire PATCH.
- Write unit tests.

**NOT in scope**: Modifying the HTTP handler (TASK-771), route registration (TASK-773).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/agent.py` | MODIFY | Add `_restore_user_mcp_servers()` method, call from `_setup_agent_tools()` |
| `tests/unit/test_mcp_restore_hook.py` | CREATE | Unit tests for restore logic |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in agent.py:
from ..tools.manager import ToolManager  # verified: agent.py:39
from ..mcp.integration import MCPServerConfig  # verified: agent.py:36 (this is MCPClientConfig alias)
from ..interfaces.documentdb import DocumentDb  # verified: agent.py:38

# New imports to add to agent.py:
from ..mcp.registry import MCPServerRegistry  # created by TASK-769
from ..handlers.mcp_persistence import MCPPersistenceService  # created by TASK-770
from ..handlers.credentials_utils import decrypt_credential  # verified: parrot/handlers/credentials_utils.py:52
```

### Existing Signatures to Use
```python
# parrot/handlers/agent.py — _setup_agent_tools (line 934-981)
async def _setup_agent_tools(
    self,
    agent: AbstractBot,
    data: Dict[str, Any],
    request_session: Any
) -> Union[web.Response, None]:
    # ... existing tool/MCP setup logic ...
    # New restore hook should be called HERE, after line 968 (after _add_mcp_servers)
    # and before line 975 (before _bootstrap_jira_oauth_session)
    return tool_manager

# parrot/handlers/agent.py — user_id extraction from session (from _bootstrap_jira_oauth_session, line 1001-1005)
user_id = None
for attr in ("user_id", "id", "username"):
    if hasattr(request_session, attr):
        user_id = getattr(request_session, attr)
        break

# parrot/handlers/mcp_persistence.py (created by TASK-770)
class MCPPersistenceService:
    async def load_user_mcp_configs(self, user_id: str, agent_id: str) -> List[UserMCPServerConfig]: ...

# parrot/mcp/registry.py (created by TASK-769)
class MCPServerRegistry:
    def get_server(self, name: str) -> Optional[MCPServerDescriptor]: ...

# parrot/handlers/credentials_utils.py (line 52)
def decrypt_credential(encrypted: str, master_keys: dict[int, bytes]) -> dict: ...

# parrot/handlers/credentials.py — vault key loading pattern (line 49-66)
def _load_vault_keys() -> tuple[int, bytes, dict[int, bytes]]: ...

# parrot/tools/mcp_mixin.py — ToolManager.add_mcp_server (line 52)
async def add_mcp_server(self, config, context=None) -> List[str]: ...

# Factory function dispatch — same mapping as TASK-771
# from parrot.mcp.integration import create_perplexity_mcp_server, etc.
```

### Does NOT Exist
- ~~`AgentTalk._restore_user_mcp_servers()`~~ — does not exist yet; this task creates it
- ~~`AgentTalk.mcp_persistence`~~ — no such attribute; create `MCPPersistenceService()` inline
- ~~`request_session.user_id`~~ — not a direct attribute; iterate attrs as shown above
- ~~`ToolManager.restore_mcp_servers()`~~ — no such method; call `add_mcp_server` per config
- ~~`MCPServerRegistry.get_factory(name)`~~ — no such method; use a local factory map dict

---

## Implementation Notes

### Integration Point in _setup_agent_tools
Insert the restore call between the MCP servers block and the Jira OAuth bootstrap:

```python
# Line ~968: after _add_mcp_servers completes
# Line ~970: BEFORE the Jira OAuth bootstrap comment

# NEW: Restore user's previously-saved MCP servers
await self._restore_user_mcp_servers(
    tool_manager=tool_manager,
    request_session=request_session,
    agent_name=agent.name,
)

# Line ~975: existing _bootstrap_jira_oauth_session call
```

### Factory Function Dispatch
Reuse the same mapping defined in TASK-771. Consider importing it from `mcp_helper.py`
or defining a shared constant in `registry.py`.

### Error Handling Strategy
Each server restore is independent. Wrap each in try/except:
```python
for config in saved_configs:
    try:
        # ... restore logic ...
        self.logger.info("Restored MCP server '%s' with %d tools", config.server_name, len(tools))
    except Exception as exc:
        self.logger.warning(
            "Failed to restore MCP server '%s': %s", config.server_name, exc
        )
        # Continue with next server — never fail the entire PATCH
```

### Key Constraints
- The method MUST NOT raise exceptions — it must catch everything and log warnings
- Only restore configs where `active=True` (handled by persistence service)
- If the Vault credential is missing (user deleted it), log WARNING and skip that server
- If the MCP server connection fails (e.g., network error), log WARNING and skip
- If `tool_manager` is `None`, skip restore entirely (no ToolManager means no tools to add)

### References in Codebase
- `parrot/handlers/agent.py:934-981` — `_setup_agent_tools` method (modify this)
- `parrot/handlers/agent.py:983-1027` — `_bootstrap_jira_oauth_session` (pattern reference for session-scoped bootstrapping)
- `parrot/handlers/credentials.py:49-66` — `_load_vault_keys` pattern

---

## Acceptance Criteria

- [ ] `_restore_user_mcp_servers` method added to `AgentTalk`
- [ ] Method is called from `_setup_agent_tools` after MCP server config, before Jira OAuth
- [ ] Saved MCP servers are restored: factory called, tools registered on ToolManager
- [ ] Vault credentials are decrypted and passed to factory functions
- [ ] Missing Vault credentials logged as WARNING, server skipped (no crash)
- [ ] MCP connection failures logged as WARNING, server skipped (no crash)
- [ ] Null `tool_manager` or missing `user_id` handled gracefully (no-op)
- [ ] All tests pass: `pytest tests/unit/test_mcp_restore_hook.py -v`
- [ ] Existing PATCH behavior unaffected (no regression in `_setup_agent_tools`)

---

## Test Specification

```python
# tests/unit/test_mcp_restore_hook.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.handlers.agent import AgentTalk


class TestRestoreUserMCPServers:
    @pytest.mark.asyncio
    async def test_restores_saved_servers(self):
        """Saved MCP configs are loaded and restored to ToolManager."""
        pass

    @pytest.mark.asyncio
    async def test_skips_when_no_saved_configs(self):
        """No-op when user has no saved MCP configs."""
        pass

    @pytest.mark.asyncio
    async def test_skips_when_tool_manager_is_none(self):
        """No-op when tool_manager is None."""
        pass

    @pytest.mark.asyncio
    async def test_handles_missing_vault_credential(self):
        """Logs warning and continues when Vault cred is missing."""
        pass

    @pytest.mark.asyncio
    async def test_handles_connection_failure(self):
        """Logs warning and continues when MCP server connection fails."""
        pass

    @pytest.mark.asyncio
    async def test_handles_missing_user_id(self):
        """No-op when user_id cannot be extracted from session."""
        pass

    @pytest.mark.asyncio
    async def test_does_not_break_existing_patch(self):
        """_setup_agent_tools still works correctly with restore hook."""
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-769, TASK-770, TASK-771 are in `tasks/completed/`
3. **Verify the Codebase Contract** — read `agent.py` lines 934-981 to confirm `_setup_agent_tools` structure hasn't changed
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-772-session-restore-hook.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-04-19
**Notes**: Added _restore_user_mcp_servers() to AgentTalk, called from _setup_agent_tools() with enable_mcp_restore opt-in (follows same pattern as jira_credential_resolver). Method handles all error cases gracefully (Vault missing, connection failure, unknown factory) with warnings. All 9 functional unit tests pass.

**Deviations from spec**: Opt-in is via agent.enable_mcp_restore=True attribute (matching jira_credential_resolver pattern) rather than an unspecified mechanism. Factory map is defined inline in the method body using local imports to avoid circular imports.
