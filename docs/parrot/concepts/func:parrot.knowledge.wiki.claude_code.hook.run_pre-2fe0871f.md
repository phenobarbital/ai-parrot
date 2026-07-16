---
type: Concept
title: run_pre_tool_use_hook()
id: func:parrot.knowledge.wiki.claude_code.hook.run_pre_tool_use_hook
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Entry point for ``wikitoolkit claude-hook`` / ``parrot claude hook``.
---

# run_pre_tool_use_hook

```python
def run_pre_tool_use_hook(stdin: Optional[TextIO]=None, stdout: Optional[TextIO]=None) -> int
```

Entry point for ``wikitoolkit claude-hook`` / ``parrot claude hook``.

Reads the hook payload from stdin, prints the nudge JSON (if any)
to stdout, and always returns 0 so a misconfigured hook can never
block the assistant.

Args:
    stdin: Input stream override for tests.
    stdout: Output stream override for tests.

Returns:
    Process exit code (always 0).
