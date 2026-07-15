---
type: Wiki Entity
title: UploadSharePointFileTool
id: class:parrot_tools.o365.sharepoint.UploadSharePointFileTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for uploading files to SharePoint.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# UploadSharePointFileTool

Defined in [`parrot_tools.o365.sharepoint`](../summaries/mod:parrot_tools.o365.sharepoint.md).

```python
class UploadSharePointFileTool(O365Tool)
```

Tool for uploading files to SharePoint.

This tool uploads a local file to a SharePoint document library.
Supports folder creation and file renaming.

Examples:
    # Upload to library root
    result = await tool.run(
        site="TeamSite",
        local_file_path="/tmp/report.pdf"
    )

    # Upload to specific folder
    result = await tool.run(
        site="ProjectSite",
        local_file_path="/data/export.xlsx",
        folder_path="Reports/2025"
    )

    # Upload and rename
    result = await tool.run(
        site="TeamSite",
        local_file_path="/tmp/draft.docx",
        folder_path="Contracts",
        rename_as="Final_Agreement.docx"
    )
