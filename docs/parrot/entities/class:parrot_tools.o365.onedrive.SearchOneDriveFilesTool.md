---
type: Wiki Entity
title: SearchOneDriveFilesTool
id: class:parrot_tools.o365.onedrive.SearchOneDriveFilesTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for searching files in OneDrive.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# SearchOneDriveFilesTool

Defined in [`parrot_tools.o365.onedrive`](../summaries/mod:parrot_tools.o365.onedrive.md).

```python
class SearchOneDriveFilesTool(O365Tool)
```

Tool for searching files in OneDrive.

This tool searches for files in OneDrive by name or content.

Examples:
    # Search by filename
    result = await tool.run(
        query="budget spreadsheet"
    )

    # Search with limit
    result = await tool.run(
        query="meeting notes",
        max_results=10
    )
