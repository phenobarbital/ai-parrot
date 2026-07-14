---
type: Wiki Entity
title: DownloadSharePointFileTool
id: class:parrot_tools.o365.sharepoint.DownloadSharePointFileTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for downloading files from SharePoint.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# DownloadSharePointFileTool

Defined in [`parrot_tools.o365.sharepoint`](../summaries/mod:parrot_tools.o365.sharepoint.md).

```python
class DownloadSharePointFileTool(O365Tool)
```

Tool for downloading files from SharePoint.

This tool downloads a specific file from SharePoint to the local filesystem.

Examples:
    # Download to current directory
    result = await tool.run(
        site="TeamSite",
        library="Documents",
        file_path="Reports/Q4_Report.pdf"
    )

    # Download and rename
    result = await tool.run(
        site="ProjectSite",
        file_path="Contracts/Agreement.docx",
        rename_as="Client_Agreement.docx"
    )

    # Download to specific location
    result = await tool.run(
        site="TeamSite",
        file_path="Data/export.xlsx",
        local_destination="/tmp/downloads"
    )
