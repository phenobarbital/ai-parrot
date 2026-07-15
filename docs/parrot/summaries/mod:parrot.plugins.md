---
type: Wiki Summary
title: parrot.plugins
id: mod:parrot.plugins
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.plugins
relates_to:
- concept: func:parrot.plugins.dynamic_import_helper
  rel: defines
- concept: func:parrot.plugins.setup_plugin_importer
  rel: defines
- concept: mod:parrot
  rel: references
- concept: mod:parrot.conf
  rel: references
---

# `parrot.plugins`

## Functions

- `def setup_plugin_importer(package_name: str, plugin_subdir: str)` — Configures a PluginImporter for any package to extend its search path.
- `def dynamic_import_helper(package_name: str, attr_name: str)` — Helper for __getattr__ to dynamically import plugin modules.
