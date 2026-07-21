---
type: Wiki Summary
title: parrot_tools.o365.onedrive
id: mod:parrot_tools.o365.onedrive
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: OneDrive Tools for AI-Parrot.
relates_to:
- concept: class:parrot_tools.o365.onedrive.DownloadOneDriveFileArgs
  rel: defines
- concept: class:parrot_tools.o365.onedrive.DownloadOneDriveFileTool
  rel: defines
- concept: class:parrot_tools.o365.onedrive.ListOneDriveFilesArgs
  rel: defines
- concept: class:parrot_tools.o365.onedrive.ListOneDriveFilesTool
  rel: defines
- concept: class:parrot_tools.o365.onedrive.SearchOneDriveFilesArgs
  rel: defines
- concept: class:parrot_tools.o365.onedrive.SearchOneDriveFilesTool
  rel: defines
- concept: class:parrot_tools.o365.onedrive.UploadOneDriveFileArgs
  rel: defines
- concept: class:parrot_tools.o365.onedrive.UploadOneDriveFileTool
  rel: defines
- concept: mod:parrot.interfaces.onedrive
  rel: references
- concept: mod:parrot_tools.o365.base
  rel: references
---

# `parrot_tools.o365.onedrive`

OneDrive Tools for AI-Parrot.

Tools for interacting with OneDrive:
- List files in folders
- Search for files
- Download files
- Upload files

## Classes

- **`ListOneDriveFilesArgs(O365ToolArgsSchema)`** — Arguments for listing OneDrive files.
- **`ListOneDriveFilesTool(O365Tool)`** — Tool for listing files in OneDrive.
- **`SearchOneDriveFilesArgs(O365ToolArgsSchema)`** — Arguments for searching OneDrive files.
- **`SearchOneDriveFilesTool(O365Tool)`** — Tool for searching files in OneDrive.
- **`DownloadOneDriveFileArgs(O365ToolArgsSchema)`** — Arguments for downloading OneDrive files.
- **`DownloadOneDriveFileTool(O365Tool)`** — Tool for downloading files from OneDrive.
- **`UploadOneDriveFileArgs(O365ToolArgsSchema)`** — Arguments for uploading files to OneDrive.
- **`UploadOneDriveFileTool(O365Tool)`** — Tool for uploading files to OneDrive.
