---
type: Wiki Entity
title: ListMessagesTool
id: class:parrot_tools.o365.mail.ListMessagesTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for listing email messages from a specified folder.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# ListMessagesTool

Defined in [`parrot_tools.o365.mail`](../summaries/mod:parrot_tools.o365.mail.md).

```python
class ListMessagesTool(O365Tool)
```

Tool for listing email messages from a specified folder.

This tool allows you to:
- List messages from any mail folder (Inbox, Sent Items, etc.)
- Filter messages by various criteria (read status, sender, date, etc.)
- Limit the number of results
- Order results by different fields
- Select specific fields to retrieve

Filter query examples:
    - "isRead eq false" - Unread messages
    - "hasAttachments eq true" - Messages with attachments
    - "from/emailAddress/address eq 'user@example.com'" - From specific sender
    - "receivedDateTime ge 2025-10-16T00:00:00Z" - Received after date
    - "importance eq 'high'" - High importance messages

Examples:
    # List recent messages
    result = await tool.run(
        folder="inbox",
        top=20
    )

    # List unread messages
    result = await tool.run(
        folder="inbox",
        filter_query="isRead eq false"
    )

    # List messages from specific sender
    result = await tool.run(
        folder="inbox",
        filter_query="from/emailAddress/address eq 'boss@company.com'",
        top=10
    )
