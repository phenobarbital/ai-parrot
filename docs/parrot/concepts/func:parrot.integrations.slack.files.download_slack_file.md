---
type: Concept
title: download_slack_file()
id: func:parrot.integrations.slack.files.download_slack_file
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Download a file from Slack using bot token authentication.
---

# download_slack_file

```python
async def download_slack_file(file_info: Dict[str, Any], bot_token: str, download_dir: Optional[str]=None, allowed_types: Optional[set]=None) -> Optional[Path]
```

Download a file from Slack using bot token authentication.

Slack files require authentication via the bot token in the
Authorization header. This function downloads supported file
types to a local directory.

Args:
    file_info: File metadata from Slack event containing
        url_private_download or url_private, mimetype, name.
    bot_token: Slack bot OAuth token (xoxb-...).
    download_dir: Directory to save file. If None, uses temp dir.
    allowed_types: Set of allowed MIME types. Defaults to
        PROCESSABLE_MIME_TYPES if None.

Returns:
    Path to downloaded file, or None if download failed or
    MIME type is not supported.

Example::

    file_info = event["files"][0]
    path = await download_slack_file(file_info, bot_token)
    if path:
        content = await process_file(path)
