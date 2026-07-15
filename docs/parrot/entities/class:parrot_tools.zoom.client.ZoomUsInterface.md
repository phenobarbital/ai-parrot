---
type: Wiki Entity
title: ZoomUsInterface
id: class:parrot_tools.zoom.client.ZoomUsInterface
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Interface for interacting with Zoom.us API via Server-to-Server OAuth.
---

# ZoomUsInterface

Defined in [`parrot_tools.zoom.client`](../summaries/mod:parrot_tools.zoom.client.md).

```python
class ZoomUsInterface
```

Interface for interacting with Zoom.us API via Server-to-Server OAuth.

## Methods

- `async def connect(self)` — Initialize the session.
- `async def close(self)` — Close the session.
- `async def request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]` — Make an authenticated request to the Zoom API.
- `async def get_account_settings(self, option: str=None, **kwargs) -> Dict[str, Any]` — Get Account Settings.
