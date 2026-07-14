---
type: Concept
title: upload_file_to_slack()
id: func:parrot.integrations.slack.files.upload_file_to_slack
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Upload file to Slack using v2 async upload flow.
---

# upload_file_to_slack

```python
async def upload_file_to_slack(bot_token: str, channel: str, file_path: Path, title: Optional[str]=None, thread_ts: Optional[str]=None, initial_comment: Optional[str]=None) -> bool
```

Upload file to Slack using v2 async upload flow.

The v2 upload flow is a 3-step process:
1. Get upload URL via files.getUploadURLExternal
2. Upload file content to the provided URL
3. Complete upload via files.completeUploadExternal

This method is preferred over the deprecated files.upload API.

Args:
    bot_token: Slack bot OAuth token (xoxb-...).
    channel: Channel ID to share the file in.
    file_path: Path to the file to upload.
    title: Optional title for the file.
    thread_ts: Optional thread timestamp to reply to.
    initial_comment: Optional comment to add with the file.

Returns:
    True if upload succeeded, False otherwise.

Example::

    success = await upload_file_to_slack(
        bot_token="xoxb-...",
        channel="C123456",
        file_path=Path("report.pdf"),
        title="Monthly Report",
        initial_comment="Here's the report you requested!",
    )
