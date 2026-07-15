---
type: Wiki Entity
title: ListSharePointFilesTool
id: class:parrot_tools.o365.sharepoint.ListSharePointFilesTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for listing files in SharePoint document libraries.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# ListSharePointFilesTool

Defined in [`parrot_tools.o365.sharepoint`](../summaries/mod:parrot_tools.o365.sharepoint.md).

```python
class ListSharePointFilesTool(O365Tool)
```

Tool for listing files in SharePoint document libraries.

This tool lists all files in a specified SharePoint location, with options
for recursive listing and filtering by file type.

Examples:
    # List files in root of Documents library
    result = await tool.run(
        site="TeamSite",
        library="Documents"
    )

    # List files in specific folder
    result = await tool.run(
        site="ProjectSite",
        library="Documents",
        folder_path="Reports/2025"
    )

    # Recursive listing
    result = await tool.run(
        site="TeamSite",
        folder_path="Project Management",
        recursive=True
    )
