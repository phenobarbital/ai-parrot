---
type: Concept
title: format_reply()
id: func:parrot.integrations.matrix.crew.mention.format_reply
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Format a reply with the agent's identity prepended.
---

# format_reply

```python
def format_reply(agent_mxid: str, display_name: str, text: str) -> str
```

Format a reply with the agent's identity prepended.

Args:
    agent_mxid: Full Matrix ID of the agent (e.g. ``"@analyst:server"``).
    display_name: Human-readable display name of the agent.
    text: Response text to format.

Returns:
    Formatted string with the display name header followed by the text.
