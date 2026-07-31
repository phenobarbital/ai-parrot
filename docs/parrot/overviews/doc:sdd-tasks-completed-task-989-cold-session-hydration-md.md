---
type: Wiki Overview
title: 'TASK-989: UserObjectsHandler Cold-Session Hydration'
id: doc:sdd-tasks-completed-task-989-cold-session-hydration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When a user starts a new session (Redis cache miss), the agent's `ToolManager`
relates_to:
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
---

# TASK-989: UserObjectsHandler Cold-Session Hydration

**Feature**: FEAT-144 — Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)
**Spec**: `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-983, TASK-984
**Assigned-to**: unassigned

---

## Context

When a user starts a new session (Redis cache miss), the agent's `ToolManager`
is empty. This task extends `UserObjectsHandler.configure_tool_manager` with a
"cold-session hydration" step that reads `user_agent_toolkits` from DocumentDB
and re-registers each enabled toolkit via `provider.toolkit_factory(resolver)`.

Implements spec Module 9.

---

## Scope

- Modify `UserObjectsHandler.configure_tool_manager` (user_objects.py:96) to
  add a hydration step after the existing session-based load.
- The step queries `user_agent_toolkits` for `(user_id, agent_id)`.
- For each row, look up the provider via `OAuth2ProviderRegistry.get(provider_id)`.
- Instantiate the toolkit via `provider.toolkit_factory(OAuthCredentialResolver(provider.manager))`.
- Add to `tool_manager` via `tool_manager.add_tool(toolkit)` if not already present.
- Persist the updated tool_manager back to the session under the existing key.
- Write unit tests.

**NOT in scope**: Modifying `ToolManager` itself, creating new session keys,
fixing the `agent.name` vs `agent_id` session key inconsistency (known risk —
see spec §7).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/user_objects.py` | MODIFY | Add hydration step in `configure_tool_manager` |
| `tests/unit/integrations/oauth2/test_hydration.py` | CREATE | Hydration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Existing in user_objects.py or nearby:
from parrot.tools.manager import ToolManager  # manager.py:203

# New imports to add:
from parrot.integrations.oauth2.registry import OAuth2ProviderRegistry  # TASK-983
from parrot.integrations.oauth2.persistence import list_user_agent_toolkits  # TASK-984
from parrot.auth.credentials import OAuthCredentialResolver  # credentials.py:49
```

### Existing Signatures to Use
```python
# parrot/handlers/user_objects.py:96
class UserObjectsHandler:
    async def configure_tool_manager(
        self, data: Dict[str, Any], request_session: Any,
        agent_name: str = None,
    ) -> tuple[Union[ToolManager, None], List[Dict[str, Any]]]: ...
    # Uses session_key = self.get_session_key(agent_name, "tool_manager")  (line 123)

# parrot/tools/manager.py:381
class ToolManager:
    def add_tool(self, tool: Union[ToolDefinition, AbstractTool],
                 name: Optional[str] = None) -> None: ...
    def get_tool(self, tool_name: str) -> Optional[Any]: ...  # line 822

# parrot/auth/credentials.py:49
class OAuthCredentialResolver(CredentialResolver):
    def __init__(self, manager: "JiraOAuthManager"): ...  # verify exact __init__ signature

# parrot/integrations/oauth2/registry.py (TASK-983):
class OAuth2ProviderRegistry:
    def get(self, provider_id: str) -> Optional[OAuth2Provider]: ...

# parrot/integrations/oauth2/persistence.py (TASK-984):
async def list_user_agent_toolkits(user_id: str, agent_id: str) -> List[UserAgentToolkitRow]: ...
```

### Does NOT Exist
- ~~`UserObjectsHandler._hydrate_oauth_toolkits()`~~ — does not exist; this task may
  add it as a private helper method, or inline the logic.
- ~~`ToolManager.has_tool(name)` method~~ — may not exist. Use `get_tool(name)` and
  check for `None` to determine if already present.
- ~~`tool_manager.toolkits` attribute~~ — verify how to check if a toolkit is already
  registered. May need to check by tool names the toolkit would register.

---

## Implementation Notes

### Hydration Pattern
```python
# Inside configure_tool_manager, after existing session-based load:

# Cold-session hydration from DocumentDB
if user_id and agent_name:
    try:
        enablements = await list_user_agent_toolkits(user_id, agent_id)
        registry = OAuth2ProviderRegistry()
        for row in enablements:
            provider = registry.get(row.provider)
            if provider is None:
                self.logger.warning("Unknown provider %s in user_agent_toolkits", row.provider)
                continue
            # Skip if toolkit already present
            # (check by provider_id or toolkit tool names)
            resolver = OAuthCredentialResolver(provider.manager)
            toolkit = provider.toolkit_factory(resolver)
            tool_manager.add_tool(toolkit)
    except Exception:
        self.logger.exception("Failed to hydrate OAuth toolkits for user=%s agent=%s", user_id, agent_name)
```

### Key Constraints
- **Session key**: use `agent.name`, NOT `agent_id` (spec §7 Known Risks).
  `UserObjectsHandler` uses `get_session_key(agent_name, "tool_manager")` at
  line 123. Follow the same convention.
- **Idempotency**: if the toolkit is already in the `ToolManager` (e.g., from
  a warm session), hydration is a no-op. Check before adding.
- **Fail gracefully**: if DocumentDB is unreachable, log the error and continue.
  The user will get `AuthorizationRequired` on the first tool call and can
  reconnect via the inline pill.
- **Do NOT write to `users_integrations`** from here — only read
  `user_agent_toolkits`.
- **agent_id vs agent_name**: `configure_tool_manager` receives `agent_name`.
  The `user_agent_toolkits` rows store `agent_id`. Verify whether these are
  the same value or different. The implementation may need to accept both.

---

## Acceptance Criteria

- [ ] A `UserAgentToolkitRow` for `(user, agent, "jira")` causes `configure_tool_manager`
      to add a `JiraToolkit` to the `ToolManager` on cold session.
- [ ] If the toolkit is already present, hydration is a no-op (no duplicate).
- [ ] Unknown provider in `user_agent_toolkits` is logged and skipped.
- [ ] DocumentDB failure during hydration is caught and logged; session proceeds.
- [ ] Existing `configure_tool_manager` behaviour is unchanged for non-OAuth toolkits.
- [ ] All tests pass: `pytest tests/unit/integrations/oauth2/test_hydration.py -v`
- [ ] No lint errors.

---

## Test Specification

```python
# tests/unit/integrations/oauth2/test_hydration.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.integrations.oauth2.models import UserAgentToolkitRow
from datetime import datetime


class TestColdSessionHydration:
    @pytest.fixture
    def toolkit_row(self):
        return UserAgentToolkitRow(
            user_id="u1", agent_id="agent1", toolkit_id="jira",
            provider="jira", enabled_at=datetime.now(),
        )

    @pytest.mark.asyncio
    async def test_hydration_adds_persisted_toolkit(self, toolkit_row):
        """Cold session with user_agent_toolkits row → JiraToolkit added."""
        ...

    @pytest.mark.asyncio
    async def test_hydration_skips_already_present(self, toolkit_row):
        """If toolkit already in ToolManager, hydration is a no-op."""
        ...

    @pytest.mark.asyncio
    async def test_hydration_unknown_provider_logged(self, toolkit_row):
        """Unknown provider_id → warning logged, no crash."""
        ...

    @pytest.mark.asyncio
    async def test_hydration_db_failure_graceful(self, toolkit_row):
        """DocumentDB unreachable → exception logged, session continues."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/handlers/user_objects.py` in full (especially lines 96-170).
2. **Check dependencies** — verify TASK-983 and TASK-984 are complete.
3. **Verify**: how `OAuthCredentialResolver.__init__` is called (what args).
4. **Verify**: whether `agent_name` == `agent_id` in the flow that calls
   `configure_tool_manager` (check `agent.py:_configure_tool_manager` at L680).
5. **Implement** the minimal hydration step.
6. **Verify** all acceptance criteria.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
