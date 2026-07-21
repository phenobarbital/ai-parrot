---
type: Wiki Summary
title: parrot.plugins.importer
id: mod:parrot.plugins.importer
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.plugins.importer
relates_to:
- concept: class:parrot.plugins.importer.PluginImporter
  rel: defines
- concept: func:parrot.plugins.importer.list_plugins
  rel: defines
- concept: mod:parrot.conf
  rel: references
---

# `parrot.plugins.importer`

## Classes

- **`PluginImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader)`** — A custom importer to load plugins from a specified directory.

## Functions

- `def list_plugins(plugin_subdir: str) -> list[str]` — List all available plugins in a subdirectory.
