---
type: Wiki Summary
title: parrot_tools.o365.sharepoint
id: mod:parrot_tools.o365.sharepoint
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SharePoint Tools for AI-Parrot.
relates_to:
- concept: class:parrot_tools.o365.sharepoint.DownloadSharePointFileArgs
  rel: defines
- concept: class:parrot_tools.o365.sharepoint.DownloadSharePointFileTool
  rel: defines
- concept: class:parrot_tools.o365.sharepoint.ListSharePointFilesArgs
  rel: defines
- concept: class:parrot_tools.o365.sharepoint.ListSharePointFilesTool
  rel: defines
- concept: class:parrot_tools.o365.sharepoint.SearchSharePointFilesArgs
  rel: defines
- concept: class:parrot_tools.o365.sharepoint.SearchSharePointFilesTool
  rel: defines
- concept: class:parrot_tools.o365.sharepoint.UploadSharePointFileArgs
  rel: defines
- concept: class:parrot_tools.o365.sharepoint.UploadSharePointFileTool
  rel: defines
- concept: mod:parrot.interfaces.sharepoint
  rel: references
- concept: mod:parrot_tools.o365.base
  rel: references
---

# `parrot_tools.o365.sharepoint`

SharePoint Tools for AI-Parrot.

Tools for interacting with SharePoint document libraries:
- List files in folders
- Search for files
- Download files
- Upload files

## Classes

- **`ListSharePointFilesArgs(O365ToolArgsSchema)`** — Arguments for listing SharePoint files.
- **`ListSharePointFilesTool(O365Tool)`** — Tool for listing files in SharePoint document libraries.
- **`SearchSharePointFilesArgs(O365ToolArgsSchema)`** — Arguments for searching SharePoint files.
- **`SearchSharePointFilesTool(O365Tool)`** — Tool for searching files in SharePoint.
- **`DownloadSharePointFileArgs(O365ToolArgsSchema)`** — Arguments for downloading SharePoint files.
- **`DownloadSharePointFileTool(O365Tool)`** — Tool for downloading files from SharePoint.
- **`UploadSharePointFileArgs(O365ToolArgsSchema)`** — Arguments for uploading files to SharePoint.
- **`UploadSharePointFileTool(O365Tool)`** — Tool for uploading files to SharePoint.
