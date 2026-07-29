---
type: Wiki Summary
title: parrot.integrations.whatsapp.utils
id: mod:parrot.integrations.whatsapp.utils
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Utilities for WhatsApp integration.
relates_to:
- concept: func:parrot.integrations.whatsapp.utils.convert_markdown_to_whatsapp
  rel: defines
- concept: func:parrot.integrations.whatsapp.utils.sanitize_phone_number
  rel: defines
- concept: func:parrot.integrations.whatsapp.utils.split_message
  rel: defines
---

# `parrot.integrations.whatsapp.utils`

Utilities for WhatsApp integration.

Provides markdown conversion, message splitting, and phone number sanitization.

## Functions

- `def convert_markdown_to_whatsapp(text: str) -> str` — Convert standard Markdown to WhatsApp-compatible formatting.
- `def split_message(text: str, max_length: int=4096) -> List[str]` — Split a long message into chunks that fit WhatsApp's message size limit.
- `def sanitize_phone_number(number: str) -> str` — Normalize a phone number by stripping non-digit characters.
