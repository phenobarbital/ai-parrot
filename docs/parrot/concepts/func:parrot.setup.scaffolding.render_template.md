---
type: Concept
title: render_template()
id: func:parrot.setup.scaffolding.render_template
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Render a ``string.Template`` file from ``parrot/templates/``.
---

# render_template

```python
def render_template(template_name: str, context: Dict[str, str]) -> str
```

Render a ``string.Template`` file from ``parrot/templates/``.

Uses ``safe_substitute`` so unrecognised ``$variables`` are left
intact rather than raising ``KeyError``.

Args:
    template_name: Filename inside ``parrot/templates/``
        (e.g. ``"agent.py.tpl"``).
    context: Mapping of variable name → replacement string.

Returns:
    Rendered content with all ``$variables`` substituted.

Raises:
    FileNotFoundError: If the requested template file does not exist.
