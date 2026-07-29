---
type: Wiki Entity
title: MessageHandler
id: class:parrot.integrations.msteams.handler.MessageHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Interface for handling messages sent by Bot.
---

# MessageHandler

Defined in [`parrot.integrations.msteams.handler`](../summaries/mod:parrot.integrations.msteams.handler.md).

```python
class MessageHandler
```

Interface for handling messages sent by Bot.

Supports text, images, documents, and Adaptive Cards.

## Methods

- `async def send_image(self, url: str, turn_context: TurnContext, mimetype: str='image/png')` — Send an image to the user.
- `async def send_text(self, text: str, turn_context: TurnContext)` — Send a text message to the user.
- `def text_message(self, message_data: str) -> MessageFactory`
- `async def send_message(self, message: Activity, turn_context: TurnContext)` — Send a message to the user.
- `def get_card(self, card_data: str) -> CardFactory`
- `def create_card(self, card_data) -> Attachment`
- `async def send_card(self, card_data: Dict[str, Any], turn_context: TurnContext) -> None` — Send an Adaptive Card to the user.
- `async def send_document(self, file_path: Path, turn_context: TurnContext, filename: Optional[str]=None) -> None` — Send a document as an attachment.
- `async def send_file_attachment(self, file_path: Path, turn_context: TurnContext, caption: Optional[str]=None) -> None` — Send a file attachment with optional caption.
