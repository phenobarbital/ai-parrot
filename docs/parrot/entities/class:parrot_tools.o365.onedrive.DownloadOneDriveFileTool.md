---
type: Wiki Entity
title: DownloadOneDriveFileTool
id: class:parrot_tools.o365.onedrive.DownloadOneDriveFileTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for downloading files from OneDrive.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# DownloadOneDriveFileTool

Defined in [`parrot_tools.o365.onedrive`](../summaries/mod:parrot_tools.o365.onedrive.md).

```python
class DownloadOneDriveFileTool(O365Tool)
```

Tool for downloading files from OneDrive.

This tool downloads a specific file from OneDrive to the local filesystem.
Can identify files by path or ID.

Examples:
    # Download by path
    result = await tool.run(
        file_path="Documents/report.pdf"
    )

    # Download by ID
    result = await tool.run(
        file_id="01ABCDEF1234567890"
    )

    # Download and rename
    result = await tool.run(
        file_path="Contracts/agreement.docx",
        rename_as="Client_Agreement.docx"
    )

    # Download to specific location
    result = await tool.run(
        file_path="Data/export.xlsx",
        local_destination="/tmp/downloads"
    )
