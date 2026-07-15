---
type: Wiki Entity
title: TelegramAgentConfig
id: class:parrot.integrations.telegram.models.TelegramAgentConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for a single agent exposed via Telegram.
---

# TelegramAgentConfig

Defined in [`parrot.integrations.telegram.models`](../summaries/mod:parrot.integrations.telegram.models.md).

```python
class TelegramAgentConfig
```

Configuration for a single agent exposed via Telegram.

Attributes:
    name: Agent name (used as key in YAML and for env var fallback).
    chatbot_id: ID/name of the bot in BotManager (used with get_bot()).
    bot_token: Telegram bot token. If not provided, reads from
               {NAME}_TELEGRAM_TOKEN environment variable.
    allowed_chat_ids: Optional list of chat IDs that can use this bot.
                      If None, the bot is accessible to all chats.
    welcome_message: Custom message sent when user issues /start command.
    system_prompt_override: Override the agent's default system prompt.
    commands: Custom commands that map to agent methods.
              Format: {"command_name": "agent_method_name"}
              E.g.:   {"report": "generate_report"}
    enable_group_mentions: Allow bot to respond to @mentions in groups.
    enable_group_commands: Allow bot to respond to /ask command in groups.
    reply_in_thread: Reply as thread to original message in groups.
    enable_channel_posts: Allow bot to process channel posts with @mentions.
    operator_chat_ids: Allowlist of chat IDs permitted to run operator commands.
        Fail-closed: ``None`` (or empty) means NO chat is an operator.
        YAML values are coerced to ``int`` so quoted IDs work correctly.
    enable_operator_commands: Feature toggle — set ``False`` to skip
        registering all operator command handlers entirely.

## Methods

- `def voice_enabled(self) -> bool` — Return True if voice transcription is configured and enabled.
- `def from_dict(cls, name: str, data: Dict[str, Any]) -> 'TelegramAgentConfig'` — Create config from dictionary (YAML parsed data).
