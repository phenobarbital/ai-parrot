---
type: Wiki Entity
title: Office365FileManagementToolkit
id: class:parrot_tools.o365.bundle.Office365FileManagementToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Complete Office365 file management toolkit (SharePoint + OneDrive).
---

# Office365FileManagementToolkit

Defined in [`parrot_tools.o365.bundle`](../summaries/mod:parrot_tools.o365.bundle.md).

```python
class Office365FileManagementToolkit
```

Complete Office365 file management toolkit (SharePoint + OneDrive).

This toolkit bundles both SharePoint and OneDrive tools for
comprehensive file management across Office365.

Usage:
    toolkit = Office365FileManagementToolkit(
        client_id='your-client-id',
        client_secret='your-client-secret',
        tenant_id='your-tenant-id'
    )

    agent = BasicAgent(
        name="FileAgent",
        tools=toolkit.get_tools()
    )

## Methods

- `def get_tools(self) -> List[Any]` — Get all toolkit tools.
- `def get_tool_by_name(self, name: str) -> Optional[Any]` — Get a specific tool by name.
- `def get_sharepoint_tools(self) -> List[Any]` — Get only SharePoint tools.
- `def get_onedrive_tools(self) -> List[Any]` — Get only OneDrive tools.
- `async def cleanup(self)` — Clean up all tool resources.
