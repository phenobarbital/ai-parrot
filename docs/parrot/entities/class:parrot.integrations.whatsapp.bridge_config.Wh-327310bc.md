---
type: Wiki Entity
title: WhatsAppBridgeConfig
id: class:parrot.integrations.whatsapp.bridge_config.WhatsAppBridgeConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for WhatsApp Bridge wrapper (whatsmeow-based).
---

# WhatsAppBridgeConfig

Defined in [`parrot.integrations.whatsapp.bridge_config`](../summaries/mod:parrot.integrations.whatsapp.bridge_config.md).

```python
class WhatsAppBridgeConfig
```

Configuration for WhatsApp Bridge wrapper (whatsmeow-based).

Attributes:
    name: Wrapper name (used for logging and route generation).
    chatbot_id: Agent name in BotManager / agent registry.
    bridge_url: URL of the Go whatsmeow bridge.
    webhook_path: Path to register for incoming message callbacks.
    welcome_message: Greeting sent on first interaction.
    system_prompt_override: Override agent's default system prompt.
    allowed_numbers: Phone allowlist (digits only, no +). Empty = all.
    commands: Custom slash-command map.
    max_message_length: Max chars before splitting.

## Methods

- `def from_dict(cls, name: str, data: Dict[str, Any]) -> 'WhatsAppBridgeConfig'` — Create config from dictionary (YAML parsed data).
