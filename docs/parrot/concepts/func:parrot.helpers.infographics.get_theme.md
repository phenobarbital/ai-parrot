---
type: Concept
title: get_theme()
id: func:parrot.helpers.infographics.get_theme
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Retrieve a theme by name.
---

# get_theme

```python
def get_theme(name: str) -> ThemeConfig
```

Retrieve a theme by name.

Args:
    name: Theme identifier.

Returns:
    The matching ThemeConfig instance.

Raises:
    KeyError: If the theme name is not registered.
