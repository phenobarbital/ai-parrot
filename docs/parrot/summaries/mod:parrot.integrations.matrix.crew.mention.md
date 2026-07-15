---
type: Wiki Summary
title: parrot.integrations.matrix.crew.mention
id: mod:parrot.integrations.matrix.crew.mention
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Matrix mention parsing and formatting utilities.
relates_to:
- concept: func:parrot.integrations.matrix.crew.mention.build_pill
  rel: defines
- concept: func:parrot.integrations.matrix.crew.mention.build_reply_content
  rel: defines
- concept: func:parrot.integrations.matrix.crew.mention.format_reply
  rel: defines
- concept: func:parrot.integrations.matrix.crew.mention.parse_mention
  rel: defines
---

# `parrot.integrations.matrix.crew.mention`

Matrix mention parsing and formatting utilities.

Handles both plain-text ``@localpart`` mentions and Matrix HTML pill mentions
(``<a href="https://matrix.to/#/@user:server">name</a>``).

## Functions

- `def parse_mention(body: str, server_name: str) -> Optional[str]` — Extract the agent localpart from a Matrix message body.
- `def format_reply(agent_mxid: str, display_name: str, text: str) -> str` — Format a reply with the agent's identity prepended.
- `def build_pill(mxid: str, display_name: str) -> str` — Build a Matrix "pill" HTML mention link.
- `def build_reply_content(text: str, reply_to_event_id: str) -> dict` — Build the ``m.relates_to`` content dict for a reply-to message.
