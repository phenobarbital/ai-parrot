# TASK-119: UserObjectsHandler Class

**Feature**: DatasetManager Support for AgentTalk Handler
**Spec**: `sdd/specs/dataset-support-agenttalk.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: claude-opus-session

---

## Context

> This task implements Module 1 from the spec: UserObjectsHandler Class.

Extract the session-scoped ToolManager and DatasetManager configuration logic from AgentTalk into a dedicated `UserObjectsHandler` class. This reduces AgentTalk complexity and centralizes user object management.

---

## Scope

- Create `UserObjectsHandler` class at `parrot/handlers/user_objects.py`
- Move `_configure_tool_manager()` logic from AgentTalk to this class
- Add `configure_dataset_manager()` method that:
  - Gets or creates a session-scoped DatasetManager for the user
  - If agent has existing DatasetManager, copies all datasets to user's instance
  - Saves to session with key `{agent_name}_dataset_manager`
- Add helper method `get_session_key(agent_name, manager_type)`

**NOT in scope**:
- Modifying AgentTalk (that's TASK-120)
- Creating HTTP endpoints (that's TASK-122)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/user_objects.py` | CREATE | New UserObjectsHandler class |

---

## Implementation Notes

### Class Structure
```python
from typing import Dict, Any, List, Union, TYPE_CHECKING
from navconfig.logging import logging
from ..tools.manager import ToolManager
from ..tools.dataset_manager import DatasetManager

if TYPE_CHECKING:
    from ..bots.data import PandasAgent


class UserObjectsHandler:
    """
    Manages session-scoped ToolManager and DatasetManager instances.

    Extracted from AgentTalk to reduce complexity and centralize
    user object configuration logic.
    """

    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger(__name__)

    def get_session_key(self, agent_name: str, manager_type: str) -> str:
        """Generate session key for a manager type."""
        prefix = f"{agent_name}_" if agent_name else ""
        return f"{prefix}{manager_type}"

    async def configure_tool_manager(
        self,
        data: Dict[str, Any],
        request_session: Any,
        agent_name: str = None
    ) -> tuple[Union[ToolManager, None], List[Dict[str, Any]]]:
        """
        Configure a ToolManager from request payload or session.

        Moved from AgentTalk._configure_tool_manager().
        """
        # Copy existing implementation from AgentTalk
        ...

    async def configure_dataset_manager(
        self,
        request_session: Any,
        agent: "PandasAgent",
        agent_name: str = None
    ) -> DatasetManager:
        """
        Get or create a session-scoped DatasetManager for the user.

        If the agent has an existing DatasetManager, copies all datasets
        to a new user-specific instance. Saves to session and returns.
        """
        session_key = self.get_session_key(agent_name or agent.name, "dataset_manager")

        # Check for existing in session
        if request_session is not None:
            existing_dm = request_session.get(session_key)
            if existing_dm and isinstance(existing_dm, DatasetManager):
                return existing_dm

        # Create new DatasetManager
        user_dm = DatasetManager()

        # Copy datasets from agent's DatasetManager
        if hasattr(agent, '_dataset_manager') and agent._dataset_manager:
            agent_dm = agent._dataset_manager
            for name, info in agent_dm.list_datasets().items():
                if info.get('loaded'):
                    df = agent_dm.get_dataframe(name)
                    if df is not None:
                        user_dm.add_dataset(
                            name=name,
                            data=df,
                            description=info.get('description', '')
                        )

        # Save to session
        if request_session is not None:
            request_session[session_key] = user_dm

        return user_dm
```

### References in Codebase
- `parrot/handlers/agent.py` — existing `_configure_tool_manager()` implementation
- `parrot/tools/dataset_manager.py` — DatasetManager API
- `parrot/bots/data.py` — PandasAgent with `_dataset_manager` attribute

---

## Acceptance Criteria

- [ ] `UserObjectsHandler` class created at `parrot/handlers/user_objects.py`
- [ ] `get_session_key()` method generates correct keys
- [ ] `configure_tool_manager()` method matches existing AgentTalk behavior
- [ ] `configure_dataset_manager()` creates new DatasetManager if not in session
- [ ] `configure_dataset_manager()` returns existing DatasetManager from session
- [ ] `configure_dataset_manager()` copies datasets from agent's DatasetManager
- [ ] Unit tests pass: `pytest tests/handlers/test_user_objects_handler.py -v`

---

## Test Specification

```python
# tests/handlers/test_user_objects_handler.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from parrot.handlers.user_objects import UserObjectsHandler
from parrot.tools.dataset_manager import DatasetManager


class TestSessionKeyGeneration:
    def test_with_agent_name(self):
        handler = UserObjectsHandler()
        key = handler.get_session_key("my-agent", "dataset_manager")
        assert key == "my-agent_dataset_manager"

    def test_without_agent_name(self):
        handler = UserObjectsHandler()
        key = handler.get_session_key(None, "tool_manager")
        assert key == "tool_manager"


class TestConfigureDatasetManager:
    @pytest.mark.asyncio
    async def test_creates_new_dm_if_not_in_session(self):
        handler = UserObjectsHandler()
        session = {}
        agent = MagicMock()
        agent.name = "test-agent"
        agent._dataset_manager = None

        dm = await handler.configure_dataset_manager(session, agent)

        assert isinstance(dm, DatasetManager)
        assert "test-agent_dataset_manager" in session

    @pytest.mark.asyncio
    async def test_returns_existing_dm_from_session(self):
        handler = UserObjectsHandler()
        existing_dm = DatasetManager()
        session = {"test-agent_dataset_manager": existing_dm}
        agent = MagicMock()
        agent.name = "test-agent"

        dm = await handler.configure_dataset_manager(session, agent)

        assert dm is existing_dm

    @pytest.mark.asyncio
    async def test_copies_datasets_from_agent_dm(self):
        handler = UserObjectsHandler()
        session = {}

        # Create agent with DatasetManager containing a dataset
        agent_dm = DatasetManager()
        import pandas as pd
        df = pd.DataFrame({'a': [1, 2, 3]})
        agent_dm.add_dataset("test_df", df, description="Test dataset")

        agent = MagicMock()
        agent.name = "test-agent"
        agent._dataset_manager = agent_dm

        dm = await handler.configure_dataset_manager(session, agent)

        assert "test_df" in dm.list_datasets()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-119-user-objects-handler.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-03
**Notes**:
- Created `parrot/handlers/user_objects.py` with `UserObjectsHandler` class
- Implemented `get_session_key()` for generating namespaced session keys
- Implemented `configure_tool_manager()` moved from AgentTalk
- Implemented `configure_dataset_manager()` for session-scoped DatasetManager
- Fixed edge case: ToolManager.__bool__ returns False when empty, so use `is not None` check
- Created `tests/handlers/test_user_objects_handler.py` with 25 comprehensive tests
- All tests passing, linting clean
