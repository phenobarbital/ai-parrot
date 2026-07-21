---
type: Wiki Entity
title: NotificationTool
id: class:parrot_tools.notification.NotificationTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Unified notification tool for sending messages through multiple channels.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# NotificationTool

Defined in [`parrot_tools.notification`](../summaries/mod:parrot_tools.notification.md).

```python
class NotificationTool(AbstractTool)
```

Unified notification tool for sending messages through multiple channels.

Supports:
- Email: Send emails with attachments
- Telegram: Smart file handling (images as photos, docs as documents)
- Slack: Channel messages
- MS Teams: Team messages with file references

Examples:
    # Email with subject
    send(message="Report ready", type="email",
         recipients="user@example.com", subject="Daily Report")

    # Telegram with image
    send(message="Check this chart", type="telegram",
         recipients="123456789", files="/path/to/chart.png")

    # Slack channel
    send(message="Deployment complete", type="slack",
         recipients="C123456")
