---
type: Concept
title: render_text()
id: func:parrot.integrations.msagentsdk.cards.render_text
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Render a `SemanticUIResult` as plain/markdown text.
---

# render_text

```python
def render_text(result: SemanticUIResult) -> str
```

Render a `SemanticUIResult` as plain/markdown text.

Total fallback: handles every payload shape (including empty lists and
`None` fields) and never raises.

Args:
    result: The semantic UI result to render.

Returns:
    A readable plain/markdown text rendering of `result`.
