---
type: Wiki Entity
title: GetMessageTool
id: class:parrot_tools.o365.mail.GetMessageTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for retrieving a specific email message by its ID.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# GetMessageTool

Defined in [`parrot_tools.o365.mail`](../summaries/mod:parrot_tools.o365.mail.md).

```python
class GetMessageTool(O365Tool)
```

Tool for retrieving a specific email message by its ID.

This tool retrieves complete information about a single message, including:
- Full message headers (subject, sender, recipients, dates)
- Message body content (if include_body=True)
- Attachment information
- Message metadata (read status, importance, conversation ID)

Use this tool when you need detailed information about a specific message,
such as reading the full content or checking for attachments.

Examples:
    # Get message with body
    result = await tool.run(
        message_id="AAMkAGI...",
        include_body=True
    )

    # Get message metadata only (faster)
    result = await tool.run(
        message_id="AAMkAGI...",
        include_body=False
    )
