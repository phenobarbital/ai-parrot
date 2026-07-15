---
type: Wiki Entity
title: NotificationMixin
id: class:parrot.notifications.NotificationMixin
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mixin to provide notification capabilities to agents.
---

# NotificationMixin

Defined in [`parrot.notifications`](../summaries/mod:parrot.notifications.md).

```python
class NotificationMixin
```

Mixin to provide notification capabilities to agents.

This mixin integrates async-notify library to send messages
through various channels (email, slack, telegram, teams) with
smart file handling.

## Methods

- `async def send_notification(self, message: Union[str, Any], recipients: Union[List[Actor], Actor, Channel, Chat, str, List[str]], provider: Union[str, NotificationProvider]=NotificationProvider.EMAIL, subject: Optional[str]=None, report: Optional[Any]=None, template: Optional[str]=None, with_attachments: bool=True, provider_options: Optional[Dict[str, Any]]=None, **kwargs) -> Dict[str, Any]` — Send notification to users through various channels.
- `async def send_email(self, message: str, recipients: Union[List[str], str], subject: str, report: Optional[Any]=None, template: Optional[str]=None, **kwargs) -> Dict[str, Any]` — Convenience method for sending emails.
- `async def send_slack_message(self, message: str, channel: Union[Channel, str], report: Optional[Any]=None, **kwargs) -> Dict[str, Any]` — Convenience method for sending Slack messages.
- `async def send_telegram_message(self, message: str, chat: Union[Chat, str], report: Optional[Any]=None, disable_notification: bool=False, **kwargs) -> Dict[str, Any]` — Convenience method for sending Telegram messages.
- `async def send_teams_message(self, message: str, recipient: Union[Actor, TeamsChannel, TeamsWebhook], report: Optional[Any]=None, **kwargs) -> Dict[str, Any]` — Convenience method for sending Teams messages.
