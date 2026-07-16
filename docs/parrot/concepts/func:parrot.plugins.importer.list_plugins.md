---
type: Concept
title: list_plugins()
id: func:parrot.plugins.importer.list_plugins
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: List all available plugins in a subdirectory.
---

# list_plugins

```python
def list_plugins(plugin_subdir: str) -> list[str]
```

List all available plugins in a subdirectory.

Args:
    plugin_subdir: Subdirectory name (e.g., 'agents', 'tools')

Returns:
    List of plugin module names (without .py extension)
