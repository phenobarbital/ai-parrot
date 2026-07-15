---
type: Wiki Entity
title: UploadOneDriveFileTool
id: class:parrot_tools.o365.onedrive.UploadOneDriveFileTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for uploading files to OneDrive.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# UploadOneDriveFileTool

Defined in [`parrot_tools.o365.onedrive`](../summaries/mod:parrot_tools.o365.onedrive.md).

```python
class UploadOneDriveFileTool(O365Tool)
```

Tool for uploading files to OneDrive.

This tool uploads a local file to OneDrive.
Supports folder creation and file renaming.

Examples:
    # Upload to root
    result = await tool.run(
        local_file_path="/tmp/report.pdf"
    )

    # Upload to specific folder
    result = await tool.run(
        local_file_path="/data/export.xlsx",
        folder_path="Documents/Reports"
    )

    # Upload and rename
    result = await tool.run(
        local_file_path="/tmp/draft.docx",
        folder_path="Work",
        rename_as="Final_Document.docx"
    )
