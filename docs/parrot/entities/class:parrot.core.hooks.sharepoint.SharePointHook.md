---
type: Wiki Entity
title: SharePointHook
id: class:parrot.core.hooks.sharepoint.SharePointHook
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Subscribes to SharePoint changes via Microsoft Graph API.
relates_to:
- concept: class:parrot.core.hooks.base.BaseHook
  rel: extends
---

# SharePointHook

Defined in [`parrot.core.hooks.sharepoint`](../summaries/mod:parrot.core.hooks.sharepoint.md).

```python
class SharePointHook(BaseHook)
```

Subscribes to SharePoint changes via Microsoft Graph API.

Handles subscription creation, validation, renewal, and change
notifications.  Requires ``azure-identity`` and ``msgraph-sdk``.

## Methods

- `async def start(self) -> None`
- `async def stop(self) -> None`
- `def setup_routes(self, app: Any) -> None`
