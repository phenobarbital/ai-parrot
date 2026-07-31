---
type: Concept
title: claude_hook()
id: func:parrot.knowledge.wiki.cli.claude_hook
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Claude Code PreToolUse hook runtime (reads stdin JSON).
---

# claude_hook

```python
def claude_hook() -> None
```

Claude Code PreToolUse hook runtime (reads stdin JSON).

Configured by `parrot claude install` in .claude/settings.json;
emits a non-blocking nudge toward `wikitoolkit query` before
search-style tool calls. Always exits 0.
