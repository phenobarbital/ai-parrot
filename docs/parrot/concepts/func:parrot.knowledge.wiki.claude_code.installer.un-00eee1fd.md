---
type: Concept
title: uninstall_claude_integration()
id: func:parrot.knowledge.wiki.claude_code.installer.uninstall_claude_integration
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Remove every managed artifact written by the installer.
---

# uninstall_claude_integration

```python
def uninstall_claude_integration(root: Path) -> list[str]
```

Remove every managed artifact written by the installer.

Leaves ``.parrot/wiki.json`` and the wiki plane itself in place —
only the Claude Code wiring is removed.

Args:
    root: Repository root.

Returns:
    Human-readable list of actions performed.
