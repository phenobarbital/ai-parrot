---
type: Concept
title: register_theme()
id: func:parrot.helpers.infographics.register_theme
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register a custom infographic theme.
---

# register_theme

```python
def register_theme(theme: Union[ThemeConfig, dict]) -> ThemeConfig
```

Register a custom infographic theme.

Accepts either a ThemeConfig instance or a raw dict that will be
validated via ThemeConfig.model_validate. Returns the validated
theme instance.

Args:
    theme: ThemeConfig instance or a dict conforming to the
        ThemeConfig schema.

Returns:
    The registered ThemeConfig instance.

Raises:
    TypeError: If ``theme`` is neither a dict nor a ``ThemeConfig``
        instance.
    pydantic.ValidationError: If the dict payload is malformed.
