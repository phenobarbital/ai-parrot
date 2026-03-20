# TASK-120: AgentTalk Refactor to Use UserObjectsHandler

**Feature**: DatasetManager Support for AgentTalk Handler
**Spec**: `sdd/specs/dataset-support-agenttalk.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-119
**Assigned-to**: claude-opus-session

---

## Context

> This task implements Module 2 from the spec: AgentTalk Refactor.

Refactor AgentTalk to use the new `UserObjectsHandler` for tool/dataset manager configuration. Add integration with `PandasAgent.attach_dm()` to attach user's DatasetManager.

---

## Scope

- Import and instantiate `UserObjectsHandler` in AgentTalk
- Replace `_configure_tool_manager()` method with call to `UserObjectsHandler.configure_tool_manager()`
- Add `_configure_dataset_manager()` call in `post()` method
- Call `agent.attach_dm()` when user has a session-scoped DatasetManager
- Only apply DatasetManager logic for agents that support it (PandasAgent and subclasses)

**NOT in scope**:
- Creating the UserObjectsHandler class (that's TASK-119)
- Creating HTTP endpoints for datasets (that's TASK-122)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/agent.py` | MODIFY | Use UserObjectsHandler, add dataset manager integration |

---

## Implementation Notes

### Changes to AgentTalk

```python
# At top of file
from .user_objects import UserObjectsHandler

# In __init__ or class body
_user_objects_handler: UserObjectsHandler = None

@property
def user_objects_handler(self) -> UserObjectsHandler:
    if self._user_objects_handler is None:
        self._user_objects_handler = UserObjectsHandler(logger=self.logger)
    return self._user_objects_handler
```

### In _configure_and_chat() or similar method

```python
# Check if agent supports DatasetManager
from ..bots.data import PandasAgent

if isinstance(agent, PandasAgent):
    # Configure dataset manager from session
    request_session = await get_session(self.request)
    dm = await self.user_objects_handler.configure_dataset_manager(
        request_session,
        agent,
        agent_name=agent.name
    )
    # Attach to agent for this request
    agent.attach_dm(dm)
```

### Removing old _configure_tool_manager

The old `_configure_tool_manager()` method should be replaced with a delegation:

```python
async def _configure_tool_manager(
    self,
    data: Dict[str, Any],
    request_session: Any,
    agent_name: str = None
) -> tuple[Union[ToolManager, None], List[Dict[str, Any]]]:
    """Delegate to UserObjectsHandler."""
    return await self.user_objects_handler.configure_tool_manager(
        data, request_session, agent_name
    )
```

Or remove entirely and replace all call sites with direct calls to `user_objects_handler.configure_tool_manager()`.

### References in Codebase
- `parrot/handlers/agent.py:347` — existing `_configure_tool_manager()` method
- `parrot/bots/data.py:476` — `PandasAgent.attach_dm()` method

---

## Acceptance Criteria

- [ ] `UserObjectsHandler` imported and used in AgentTalk
- [ ] `_configure_tool_manager()` delegated to or replaced by UserObjectsHandler
- [ ] DatasetManager configuration added for PandasAgent instances
- [ ] `agent.attach_dm()` called with user's DatasetManager
- [ ] Type checking for PandasAgent before applying DatasetManager logic
- [ ] No breaking changes to existing AgentTalk functionality
- [ ] Existing tests pass: `pytest tests/handlers/test_agent.py -v`

---

## Test Specification

```python
# tests/handlers/test_agent_dataset_integration.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from aiohttp import web
from parrot.handlers.agent import AgentTalk


class TestAgentTalkDatasetIntegration:
    @pytest.mark.asyncio
    async def test_attaches_dm_for_pandas_agent(self):
        """DatasetManager attached for PandasAgent."""
        # Mock request with session
        request = MagicMock()
        request.match_info = {'agent_id': 'pandas-agent'}

        # Mock PandasAgent
        with patch('parrot.handlers.agent.PandasAgent') as mock_cls:
            mock_agent = MagicMock()
            mock_agent.name = 'pandas-agent'
            mock_agent._dataset_manager = None
            mock_agent.attach_dm = MagicMock()

            # Verify attach_dm was called
            # (Full implementation would test the flow)

    @pytest.mark.asyncio
    async def test_skips_dm_for_non_pandas_agent(self):
        """DatasetManager not attached for regular Agent."""
        # Mock Agent (not PandasAgent)
        mock_agent = MagicMock()
        mock_agent.name = 'regular-agent'

        # Should not have attach_dm called
        # (Full implementation would verify)

    @pytest.mark.asyncio
    async def test_tool_manager_still_works(self):
        """Existing tool_manager functionality unchanged."""
        # Test that tool_manager configuration still works
        # after refactoring to use UserObjectsHandler
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-119 is in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-120-agenttalk-refactor.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-03
**Notes**:
- Added `UserObjectsHandler` import and lazy property to AgentTalk
- Replaced `_configure_tool_manager()` with delegation to `user_objects_handler.configure_tool_manager()`
- Added DatasetManager integration in `post()` method for PandasAgent instances
- Import PandasAgent at runtime to avoid circular imports
- DatasetManager is configured from session and attached via `agent.attach_dm()`
- Original DatasetManager is restored in finally block after request completes
- Removed unused imports: `ValidationError`, `ToolConfig`, TYPE_CHECKING `PandasAgent`
- Created integration tests in `tests/handlers/test_agent_dataset_integration.py` (8 tests)
- All 59 handler tests pass, linting clean
