---
type: Concept
title: get_theme()
id: func:parrot.helpers.infographics.get_theme
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
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
