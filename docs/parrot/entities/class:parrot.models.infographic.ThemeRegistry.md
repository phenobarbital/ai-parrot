---
type: Wiki Entity
title: ThemeRegistry
id: class:parrot.models.infographic.ThemeRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Registry for infographic HTML themes.
---

# ThemeRegistry

Defined in [`parrot.models.infographic`](../summaries/mod:parrot.models.infographic.md).

```python
class ThemeRegistry
```

Registry for infographic HTML themes.

Provides ``register``, ``get``, and ``list_themes`` following the
same pattern as ``InfographicTemplateRegistry``.

## Methods

- `def register(self, theme: ThemeConfig) -> None` — Register a theme configuration.
- `def get(self, name: str) -> ThemeConfig` — Retrieve a theme by name.
- `def list_themes(self) -> List[str]` — Return names of all registered themes.
- `def list_themes_detailed(self) -> List[Dict[str, str]]` — Return theme summaries with key colour tokens.
