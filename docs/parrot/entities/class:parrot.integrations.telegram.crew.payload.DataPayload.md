---
type: Wiki Entity
title: DataPayload
id: class:parrot.integrations.telegram.crew.payload.DataPayload
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manages file exchange between agents in a Telegram crew.
---

# DataPayload

Defined in [`parrot.integrations.telegram.crew.payload`](../summaries/mod:parrot.integrations.telegram.crew.payload.md).

```python
class DataPayload
```

Manages file exchange between agents in a Telegram crew.

Args:
    temp_dir: Directory for temporary file storage.
    max_file_size_mb: Maximum allowed file size in megabytes.
    allowed_mime_types: List of allowed MIME types for document exchange.

## Methods

- `def validate_mime(self, mime_type: str) -> bool` — Check if a MIME type is in the allowed list.
- `async def download_document(self, bot: Bot, message: Message) -> Optional[str]` — Download a document from a Telegram message to the temp directory.
- `async def send_document(self, bot: Bot, chat_id: int, file_path: str, caption: str='', reply_to_message_id: Optional[int]=None) -> None` — Upload a file to the Telegram group as a document.
- `async def send_csv(self, bot: Bot, chat_id: int, dataframe, filename: str='data.csv', caption: str='', reply_to_message_id: Optional[int]=None) -> None` — Serialize a pandas DataFrame to CSV and send as a document.
- `def cleanup_file(self, file_path: str) -> None` — Remove a temporary file if it exists.
- `def cleanup_all(self) -> None` — Remove all files in the temp directory.
