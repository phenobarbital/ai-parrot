---
type: Wiki Entity
title: PluginImporter
id: class:parrot.plugins.importer.PluginImporter
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A custom importer to load plugins from a specified directory.
---

# PluginImporter

Defined in [`parrot.plugins.importer`](../summaries/mod:parrot.plugins.importer.md).

```python
class PluginImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader)
```

A custom importer to load plugins from a specified directory.

## Methods

- `def find_spec(self, fullname, path, target=None)`
- `def create_module(self, spec)`
- `def exec_module(self, module)`
