---
type: Concept
title: add_mcp_handler()
id: func:parrot.integrations.telegram.mcp_commands.add_mcp_handler
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handle ``/add_mcp <json>``.
---

# add_mcp_handler

```python
async def add_mcp_handler(message: Message, tool_manager_resolver: ToolManagerResolver) -> None
```

Handle ``/add_mcp <json>``.

Operation order (with rollback):
1. Persist public config in DocumentDB.
2. Store secrets in the Vault (if any).
3. Register live tools with ToolManager.

On failure at step 2, step 1 is rolled back.
On failure at step 3, steps 1 and 2 are rolled back.
