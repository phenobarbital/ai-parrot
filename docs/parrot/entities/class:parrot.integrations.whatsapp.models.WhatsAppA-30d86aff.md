---
type: Wiki Entity
title: WhatsAppAgentConfig
id: class:parrot.integrations.whatsapp.models.WhatsAppAgentConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for a single agent exposed via WhatsApp Business API.
---

# WhatsAppAgentConfig

Defined in [`parrot.integrations.whatsapp.models`](../summaries/mod:parrot.integrations.whatsapp.models.md).

```python
class WhatsAppAgentConfig
```

Configuration for a single agent exposed via WhatsApp Business API.

Attributes:
    name: Agent name (used as key in YAML and for env var fallback).
    chatbot_id: ID/name of the bot in BotManager (used with get_bot()).
    phone_id: WhatsApp Phone Number ID from Meta (not the phone number itself).
    token: Permanent access token from Meta System User.
    verify_token: Webhook verification token (you define this).
    app_id: Meta App ID.
    app_secret: Meta App Secret (used for webhook signature validation).
    kind: Integration type (whatsapp).
    webhook_path: Optional custom webhook path override.
    welcome_message: Custom welcome message for new conversations.
    system_prompt_override: Override the agent's default system prompt.
    enable_group_mentions: Respond in groups only when mentioned.
    allowed_numbers: Optional phone number allowlist (without + prefix).
    commands: Custom commands map.
    max_message_length: Maximum message length before splitting (default 4096).

## Methods

- `def from_dict(cls, name: str, data: Dict[str, Any]) -> 'WhatsAppAgentConfig'` — Create config from dictionary (YAML parsed data).
