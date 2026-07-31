---
type: Wiki Summary
title: parrot.tools.filemanager
id: mod:parrot.tools.filemanager
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: FileManagerTool and FileManagerToolkit — tools for AI agents to interact
  with file systems.
relates_to:
- concept: class:parrot.tools.filemanager.FileManagerFactory
  rel: defines
- concept: class:parrot.tools.filemanager.FileManagerTool
  rel: defines
- concept: class:parrot.tools.filemanager.FileManagerToolArgs
  rel: defines
- concept: class:parrot.tools.filemanager.FileManagerToolkit
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.interfaces.file
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.tools.filemanager`

FileManagerTool and FileManagerToolkit — tools for AI agents to interact with file systems.

Implementations live in parrot.interfaces.file:
- LocalFileManager / TempFileManager: always available (stdlib only)
- S3FileManager / GCSFileManager: lazy-loaded (require aioboto3 / google-cloud-storage)

Preferred API: ``FileManagerToolkit`` — each file operation is a separate, focused tool.
Legacy API: ``FileManagerTool`` — single tool with an ``operation`` dispatch field (deprecated).

## Classes

- **`FileManagerFactory`** — Factory for creating file managers.
- **`FileManagerToolArgs(AbstractToolArgsSchema)`** — Arguments schema for FileManagerTool.
- **`FileManagerTool(AbstractTool)`** — Tool for AI agents to interact with file systems.
- **`FileManagerToolkit(AbstractToolkit)`** — Toolkit for AI agents to interact with file systems — preferred API.
