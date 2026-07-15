---
type: Wiki Entity
title: SlackRenderer
id: class:parrot.outputs.formats.slack.SlackRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renderer for Slack output — returns plain text / markdown.
relates_to:
- concept: class:parrot.outputs.formats.base.BaseRenderer
  rel: extends
---

# SlackRenderer

Defined in [`parrot.outputs.formats.slack`](../summaries/mod:parrot.outputs.formats.slack.md).

```python
class SlackRenderer(BaseRenderer)
```

Renderer for Slack output — returns plain text / markdown.

## Methods

- `async def render(self, response: Any, environment: str='default', export_format: str='html', include_code: bool=False, **kwargs) -> Tuple[str, Any]` — Render response as plain text for Slack.
