---
type: Wiki Entity
title: MarkdownRenderer
id: class:parrot.outputs.formats.markdown.MarkdownRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renderer for Markdown output.
relates_to:
- concept: class:parrot.outputs.formats.base.BaseRenderer
  rel: extends
---

# MarkdownRenderer

Defined in [`parrot.outputs.formats.markdown`](../summaries/mod:parrot.outputs.formats.markdown.md).

```python
class MarkdownRenderer(BaseRenderer)
```

Renderer for Markdown output.
Handles PandasAgentResponse (explanation), AIMessage, and generic text.
Adapts output format to Terminal (Rich), HTML, Jupyter, and Panel.

## Methods

- `async def render(self, response: Any, environment: str='default', **kwargs) -> Tuple[str, Any]` — Render markdown content.
