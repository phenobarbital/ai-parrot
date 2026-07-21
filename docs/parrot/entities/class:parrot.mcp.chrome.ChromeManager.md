---
type: Wiki Entity
title: ChromeManager
id: class:parrot.mcp.chrome.ChromeManager
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Manages a headless Chrome instance for MCP tools.
---

# ChromeManager

Defined in [`parrot.mcp.chrome`](../summaries/mod:parrot.mcp.chrome.md).

```python
class ChromeManager
```

Manages a headless Chrome instance for MCP tools.

## Methods

- `def is_port_open(self, host: str, port: int) -> bool` — Check if a port is open.
- `def is_chrome_running(self) -> bool` — Check if Chrome is running and responding on the debugging port.
- `def start(self) -> bool` — Start headless Chrome if not already running.
- `def stop(self)` — Stop the managed Chrome process.
