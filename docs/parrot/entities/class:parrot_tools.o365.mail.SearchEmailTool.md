---
type: Wiki Entity
title: SearchEmailTool
id: class:parrot_tools.o365.mail.SearchEmailTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for searching emails in Office365.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# SearchEmailTool

Defined in [`parrot_tools.o365.mail`](../summaries/mod:parrot_tools.o365.mail.md).

```python
class SearchEmailTool(O365Tool)
```

Tool for searching emails in Office365.

This tool searches through emails with support for:
- Advanced search queries
- Folder-specific searches
- Sorting and limiting results
- Attachment information

Search query examples:
    - "project update" - Keywords in subject or body
    - "from:john@company.com" - Emails from specific sender
    - "subject:invoice" - Search in subject only
    - "hasAttachments:true" - Only emails with attachments
    - "received>=2025-01-01" - Emails received after date

Examples:
    # Search for recent emails
    result = await tool.run(
        query="project deadline",
        max_results=5
    )

    # Search sent items
    result = await tool.run(
        query="from:me to:client@company.com",
        folder="sentitems",
        max_results=10
    )

    # Search with attachments
    result = await tool.run(
        query="invoice hasAttachments:true",
        include_attachments=True
    )
