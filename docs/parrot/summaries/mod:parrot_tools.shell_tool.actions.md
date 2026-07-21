---
type: Wiki Summary
title: parrot_tools.shell_tool.actions
id: mod:parrot_tools.shell_tool.actions
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot_tools.shell_tool.actions
relates_to:
- concept: class:parrot_tools.shell_tool.actions.CheckExists
  rel: defines
- concept: class:parrot_tools.shell_tool.actions.CopyFile
  rel: defines
- concept: class:parrot_tools.shell_tool.actions.DeleteFile
  rel: defines
- concept: class:parrot_tools.shell_tool.actions.ExecFile
  rel: defines
- concept: class:parrot_tools.shell_tool.actions.ListFiles
  rel: defines
- concept: class:parrot_tools.shell_tool.actions.MoveFile
  rel: defines
- concept: class:parrot_tools.shell_tool.actions.ReadFile
  rel: defines
- concept: class:parrot_tools.shell_tool.actions.RunCommand
  rel: defines
- concept: class:parrot_tools.shell_tool.actions.WriteFile
  rel: defines
- concept: mod:parrot_tools.shell_tool.models
  rel: references
---

# `parrot_tools.shell_tool.actions`

## Classes

- **`RunCommand(BaseAction)`** — Run a shell command via /bin/sh -lc 'command'.
- **`ExecFile(BaseAction)`** — Execute a file/script via /bin/sh {file_or_cmd}.
- **`ListFiles(BaseAction)`** — List files in a directory, optionally with flags/args.
- **`CheckExists(BaseAction)`** — Check if a file/directory exists.
- **`ReadFile(BaseAction)`** — Read a file's content, with optional max bytes and encoding.
- **`WriteFile(BaseAction)`** — Writes text content to a file relative to work_dir.
- **`DeleteFile(BaseAction)`** — Deletes a file or directory (with optional recursion).
- **`CopyFile(BaseAction)`** — Copy a file or directory.
- **`MoveFile(BaseAction)`** — Move/rename a file or directory.
