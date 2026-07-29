---
type: Wiki Entity
title: SearchSharePointFilesTool
id: class:parrot_tools.o365.sharepoint.SearchSharePointFilesTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for searching files in SharePoint.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# SearchSharePointFilesTool

Defined in [`parrot_tools.o365.sharepoint`](../summaries/mod:parrot_tools.o365.sharepoint.md).

```python
class SearchSharePointFilesTool(O365Tool)
```

Tool for searching files in SharePoint.

This tool searches for files in SharePoint by name, content, or metadata.
Supports filtering by file type and location.

Examples:
    # Search by filename
    result = await tool.run(
        site="TeamSite",
        query="quarterly report"
    )

    # Search for PDFs only
    result = await tool.run(
        site="ProjectSite",
        query="invoice",
        file_extension="pdf"
    )

    # Search in specific folder
    result = await tool.run(
        site="TeamSite",
        query="meeting notes",
        folder_path="Project/Meetings"
    )
