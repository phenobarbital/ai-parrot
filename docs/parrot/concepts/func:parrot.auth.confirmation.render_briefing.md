---
type: Concept
title: render_briefing()
id: func:parrot.auth.confirmation.render_briefing
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Render a confirmation briefing string for the tool call.
---

# render_briefing

```python
def render_briefing(tool: 'AbstractTool', parameters: dict) -> str
```

Render a confirmation briefing string for the tool call.

Tries to format ``tool.routing_meta.get("confirm_template")`` against a
context dict ``{tool, params, **parameters}`` using safe string
formatting.  Falls back to a raw ``"<tool.name> with: k=v, …"``
listing on any template error (missing key, bad format, etc.).

Never uses ``eval`` or ``format_map`` with untrusted attribute access.

Args:
    tool: The tool being confirmed.
    parameters: The call parameters.

Returns:
    A human-readable briefing string.
