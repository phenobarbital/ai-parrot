---
type: Wiki Summary
title: parrot.integrations.telegram.crew.mention
id: mod:parrot.integrations.telegram.crew.mention
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MentionBuilder — utilities for constructing @mention strings.
relates_to:
- concept: func:parrot.integrations.telegram.crew.mention.format_reply
  rel: defines
- concept: func:parrot.integrations.telegram.crew.mention.mention_from_card
  rel: defines
- concept: func:parrot.integrations.telegram.crew.mention.mention_from_user_id
  rel: defines
- concept: func:parrot.integrations.telegram.crew.mention.mention_from_username
  rel: defines
- concept: mod:parrot.integrations.telegram.crew.agent_card
  rel: references
---

# `parrot.integrations.telegram.crew.mention`

MentionBuilder — utilities for constructing @mention strings.

Provides helper functions for building Telegram @mentions from
usernames, user IDs, and AgentCard instances. Used throughout
the crew transport for message addressing.

## Functions

- `def mention_from_username(username: str) -> str` — Build an @mention string from a Telegram username.
- `def mention_from_user_id(user_id: int, display_name: str) -> str` — Build a Telegram HTML deep-link mention from a user ID.
- `def mention_from_card(card: AgentCard) -> str` — Build an @mention string from an AgentCard.
- `def format_reply(mention: str, text: str) -> str` — Format a response by prepending a mention to the text.
