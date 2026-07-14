---
type: Wiki Entity
title: SlackAgentConfig
id: class:parrot.integrations.slack.models.SlackAgentConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for a single agent exposed via Slack.
---

# SlackAgentConfig

Defined in [`parrot.integrations.slack.models`](../summaries/mod:parrot.integrations.slack.models.md).

```python
class SlackAgentConfig
```

Configuration for a single agent exposed via Slack.

Attributes:
    name: Unique identifier for this bot configuration.
    chatbot_id: ID of the AI-Parrot chatbot to use.
    bot_token: Slack bot token (xoxb-...). Falls back to {NAME}_SLACK_BOT_TOKEN env var.
    signing_secret: Slack signing secret for request verification.
        Falls back to {NAME}_SLACK_SIGNING_SECRET env var.
    kind: Integration type, always "slack".
    welcome_message: Message sent when a user starts a conversation.
    commands: Mapping of slash command names to descriptions.
    allowed_channel_ids: If set, only respond in these channels.
    webhook_path: Custom webhook path (default: /api/slack/{chatbot_id}/events).
    app_token: Slack app-level token (xapp-...) for Socket Mode.
        Falls back to {NAME}_SLACK_APP_TOKEN env var.
    connection_mode: Connection method - "webhook" (HTTP) or "socket" (WebSocket).
    enable_assistant: Enable Slack Agents & AI Apps feature.
    suggested_prompts: Suggested prompts shown in assistant container.
        Each dict should have "title" and "message" keys.
    max_concurrent_requests: Maximum concurrent agent requests (default: 10).

## Methods

- `def from_dict(cls, name: str, data: Dict[str, Any]) -> 'SlackAgentConfig'` — Create a SlackAgentConfig from a dictionary.
