---
type: Wiki Entity
title: ThemeConfig
id: class:parrot.models.infographic.ThemeConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: CSS variable configuration for infographic HTML themes.
---

# ThemeConfig

Defined in [`parrot.models.infographic`](../summaries/mod:parrot.models.infographic.md).

```python
class ThemeConfig(BaseModel)
```

CSS variable configuration for infographic HTML themes.

Each theme defines color tokens and font settings that map to
CSS custom properties on :root. The ``to_css_variables()`` method
generates the CSS block consumed by ``InfographicHTMLRenderer``.

## Methods

- `def to_css_variables(self) -> str` — Generate a CSS ``:root`` block with custom properties.
