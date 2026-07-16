---
type: Wiki Summary
title: parrot.tools.databasequery.sources
id: mod:parrot.tools.databasequery.sources
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: DatabaseToolkit — Source Registry & Driver Alias Resolution.
relates_to:
- concept: func:parrot.tools.databasequery.sources.get_source_class
  rel: defines
- concept: func:parrot.tools.databasequery.sources.normalize_driver
  rel: defines
- concept: func:parrot.tools.databasequery.sources.register_source
  rel: defines
- concept: mod:parrot.tools.databasequery.base
  rel: references
---

# `parrot.tools.databasequery.sources`

DatabaseToolkit — Source Registry & Driver Alias Resolution.

Provides a pluggable registry for database source implementations.
Sources self-register via the ``@register_source(driver)`` decorator.
The ``normalize_driver()`` function maps all known aliases to their
canonical driver names before registry lookup.

Part of FEAT-062 — DatabaseToolkit.

## Functions

- `def normalize_driver(driver: str) -> str` — Map driver aliases to their canonical names.
- `def register_source(driver: str) -> Callable[[type], type]` — Decorator that registers a database source class in the registry.
- `def get_source_class(driver: str) -> type[AbstractDatabaseSource]` — Look up a registered database source class by driver name.
