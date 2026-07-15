---
type: Concept
title: setup_plugin_importer()
id: func:parrot.plugins.setup_plugin_importer
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configures a PluginImporter for any package to extend its search path.
---

# setup_plugin_importer

```python
def setup_plugin_importer(package_name: str, plugin_subdir: str)
```

Configures a PluginImporter for any package to extend its search path.

This allows modules in both core package and plugins folder to be imported
with the same syntax.

Args:
    package_name: Full package name (e.g., 'parrot.agents', 'parrot.tools')
    plugin_subdir: Subdirectory name in plugins folder (e.g., 'agents', 'tools')

Example:
    # In parrot/agents/__init__.py:
    from parrot.plugins import setup_plugin_importer
    setup_plugin_importer('parrot.agents', 'agents')

    # Now you can do:
    from parrot.agents import MyPluginAgent  # Works for both core and plugin agents
