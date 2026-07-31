---
type: Concept
title: load_agent_context()
id: func:parrot.bots.prompts.agent_context.load_agent_context
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Load the per-agent context file for the given agent ID.
---

# load_agent_context

```python
def load_agent_context(agent_id: str) -> str
```

Load the per-agent context file for the given agent ID.

Reads ``<AGENT_CONTEXT_DIR>/<agent_id>.md`` and returns its content as a
string. Results are cached by ``(path, st_mtime)`` so file changes are
detected on the next call without restarting the process.

Missing files return an empty string (no error raised). This allows
agents without a dedicated context file to work silently.

The agent context directory is created lazily on first call to avoid
side effects at import time (read-only container filesystems, tests).

Args:
    agent_id: The agent's unique identifier (used as the filename stem).

Returns:
    File content as a string, or ``""`` if the file does not exist.
