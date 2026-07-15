---
type: Concept
title: parse_mention()
id: func:parrot.integrations.matrix.crew.mention.parse_mention
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract the agent localpart from a Matrix message body.
---

# parse_mention

```python
def parse_mention(body: str, server_name: str) -> Optional[str]
```

Extract the agent localpart from a Matrix message body.

Handles two formats:
- Plain text: ``"@analyst what is AAPL?"`` → ``"analyst"``
- Matrix pill HTML:
  ``<a href="https://matrix.to/#/@analyst:server">analyst</a>``
  → ``"analyst"``

Args:
    body: Message body (may be plain text or contain HTML pill markup).
    server_name: Server domain name used to validate pill mentions.

Returns:
    The localpart (e.g. ``"analyst"``) or ``None`` if no valid mention
    was found.
