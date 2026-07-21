---
type: Concept
title: run_odoo_subprocess()
id: func:parrot_tools.odoo.shell.run_odoo_subprocess
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Run an odoo-bin / odoo-cli subprocess and capture output.
---

# run_odoo_subprocess

```python
async def run_odoo_subprocess(argv: list[str], timeout: int=DEFAULT_SHELL_TIMEOUT) -> ShellResult
```

Run an odoo-bin / odoo-cli subprocess and capture output.

Uses :func:`asyncio.create_subprocess_exec` with an explicit argv list
(never ``shell=True``).  On timeout, the process is killed and a bounded
drain ensures pipe buffers are flushed without deadlocking.

Args:
    argv: The argv list.  The first element must be the binary path.
    timeout: Maximum seconds to wait before killing the process.

Returns:
    A :class:`ShellResult` with captured stdout, stderr, returncode.

Raises:
    asyncio.CancelledError: Re-raised immediately so task cancellation
        is never swallowed.
