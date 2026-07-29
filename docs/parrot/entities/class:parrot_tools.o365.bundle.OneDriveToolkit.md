---
type: Wiki Entity
title: OneDriveToolkit
id: class:parrot_tools.o365.bundle.OneDriveToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: OneDrive file management toolkit for AI-Parrot agents.
---

# OneDriveToolkit

Defined in [`parrot_tools.o365.bundle`](../summaries/mod:parrot_tools.o365.bundle.md).

```python
class OneDriveToolkit
```

OneDrive file management toolkit for AI-Parrot agents.

This toolkit provides comprehensive OneDrive integration:
- List files in folders
- Search for files
- Download files
- Upload files

Usage:
    toolkit = OneDriveToolkit(
        client_id='your-client-id',
        client_secret='your-client-secret',
        tenant_id='your-tenant-id'
    )

    # Add to agent
    agent = BasicAgent(
        name="OneDriveAgent",
        tools=toolkit.get_tools()
    )

## Methods

- `def get_tools(self) -> List[Any]` — Get all toolkit tools.
- `def get_tool_by_name(self, name: str) -> Optional[Any]` — Get a specific tool by name.
- `async def cleanup(self)` — Clean up all tool resources.
