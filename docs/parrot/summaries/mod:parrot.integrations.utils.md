---
type: Wiki Summary
title: parrot.integrations.utils
id: mod:parrot.integrations.utils
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Shared utilities for integration wrappers (Telegram, MS Teams, etc.).
relates_to:
- concept: func:parrot.integrations.utils.parse_kwargs
  rel: defines
---

# `parrot.integrations.utils`

Shared utilities for integration wrappers (Telegram, MS Teams, etc.).

## Functions

- `def parse_kwargs(text: str) -> dict` — Parse 'key=val key2="quoted val"' into a kwargs dict.
