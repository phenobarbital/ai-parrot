---
type: Wiki Entity
title: ShellTool
id: class:parrot_tools.shell_tool.tool.ShellTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Interactive Shell tool with optional PTY support.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
- concept: class:parrot_tools.shell_tool.security.SecureShellMixin
  rel: extends
---

# ShellTool

Defined in [`parrot_tools.shell_tool.tool`](../summaries/mod:parrot_tools.shell_tool.tool.md).

```python
class ShellTool(SecureShellMixin, AbstractTool)
```

Interactive Shell tool with optional PTY support.

Features:
    - Accepts single string, list of strings, or list of command objects
    - Plan-mode (tiny sequential DAG) with `uses` and templating
    - Sequential or parallel execution
    - Per-command and global timeouts
    - Global and per-command work_dir, env
    - Optional PTY mode for interactive programs (merged stdout/stderr)
    - Live output callback hook
