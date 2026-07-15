---
type: Wiki Entity
title: UserObjectsHandler
id: class:parrot.handlers.user_objects.UserObjectsHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manages session-scoped ToolManager and DatasetManager instances.
---

# UserObjectsHandler

Defined in [`parrot.handlers.user_objects`](../summaries/mod:parrot.handlers.user_objects.md).

```python
class UserObjectsHandler
```

Manages session-scoped ToolManager and DatasetManager instances.

Provides centralized logic for:
- Creating and retrieving session-scoped ToolManager instances
- Creating and retrieving session-scoped DatasetManager instances
- Copying agent configurations to user-specific instances

Usage:
    handler = UserObjectsHandler(logger=my_logger)
    tool_manager, mcp_servers = await handler.configure_tool_manager(
        data, request_session, agent_name="my-agent"
    )
    dataset_manager = await handler.configure_dataset_manager(
        request_session, agent, agent_name="my-agent"
    )

## Methods

- `def get_session_key(self, agent_name: str, manager_type: str) -> str` — Generate session key for a manager type.
- `async def configure_tool_manager(self, data: Dict[str, Any], request_session: Any, agent_name: str=None, user_id: Optional[str]=None, agent_id: Optional[str]=None) -> tuple[Union[ToolManager, None], List[Dict[str, Any]]]` — Configure a ToolManager from request payload or session.
- `async def configure_dataset_manager(self, request_session: Any, agent: 'PandasAgent', agent_name: str=None) -> DatasetManager` — Get or create a session-scoped DatasetManager for the user.
