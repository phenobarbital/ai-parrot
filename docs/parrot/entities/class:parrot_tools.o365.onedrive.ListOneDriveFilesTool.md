---
type: Wiki Entity
title: ListOneDriveFilesTool
id: class:parrot_tools.o365.onedrive.ListOneDriveFilesTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for listing files in OneDrive.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# ListOneDriveFilesTool

Defined in [`parrot_tools.o365.onedrive`](../summaries/mod:parrot_tools.o365.onedrive.md).

```python
class ListOneDriveFilesTool(O365Tool)
```

Tool for listing files in OneDrive.

This tool lists all files in a specified OneDrive location, with options
for recursive listing and filtering.

Examples:
    # List files in root
    result = await tool.run()

    # List files in specific folder
    result = await tool.run(
        folder_path="Documents/Projects"
    )

    # Recursive listing
    result = await tool.run(
        folder_path="Work",
        recursive=True
    )
