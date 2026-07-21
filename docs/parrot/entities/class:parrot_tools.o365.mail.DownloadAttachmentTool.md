---
type: Wiki Entity
title: DownloadAttachmentTool
id: class:parrot_tools.o365.mail.DownloadAttachmentTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for downloading email attachments to local storage.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# DownloadAttachmentTool

Defined in [`parrot_tools.o365.mail`](../summaries/mod:parrot_tools.o365.mail.md).

```python
class DownloadAttachmentTool(O365Tool)
```

Tool for downloading email attachments to local storage.

This tool downloads a specific attachment from an email message and saves it
to a specified location on the local filesystem.

Before downloading, you should:
1. Use GetMessageTool to retrieve the message and check hasAttachments
2. List the attachments to get their IDs and names
3. Use this tool to download specific attachments

The tool will:
- Create parent directories if they don't exist
- Decode and save the attachment content
- Return the path where the file was saved

Examples:
    # Download attachment
    result = await tool.run(
        message_id="AAMkAGI...",
        attachment_id="AAMkAGI...Attach...",
        destination="/tmp/documents/report.pdf"
    )
