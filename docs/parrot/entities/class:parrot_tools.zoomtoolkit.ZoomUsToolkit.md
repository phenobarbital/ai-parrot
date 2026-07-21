---
type: Wiki Entity
title: ZoomUsToolkit
id: class:parrot_tools.zoomtoolkit.ZoomUsToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit for interacting with Zoom.us API.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# ZoomUsToolkit

Defined in [`parrot_tools.zoomtoolkit`](../summaries/mod:parrot_tools.zoomtoolkit.md).

```python
class ZoomUsToolkit(AbstractToolkit)
```

Toolkit for interacting with Zoom.us API.
Wraps ZoomUsInterface to provide tools for AI agents.

## Methods

- `async def start(self)` — Start the toolkit resources.
- `async def stop(self)` — Stop the toolkit resources.
- `async def cleanup(self)` — Cleanup resources.
- `async def get_account_settings(self, option: Optional[str]=None) -> Dict[str, Any]` — Get Zoom Phone Account Settings.
