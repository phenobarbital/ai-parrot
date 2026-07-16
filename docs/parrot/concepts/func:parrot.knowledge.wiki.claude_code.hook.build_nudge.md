---
type: Concept
title: build_nudge()
id: func:parrot.knowledge.wiki.claude_code.hook.build_nudge
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decide whether the hook payload deserves a wiki nudge.
---

# build_nudge

```python
def build_nudge(payload: dict[str, Any], root: Optional[Path]=None, config: Optional[WikiProjectConfig]=None, now: Optional[float]=None) -> Optional[dict[str, Any]]
```

Decide whether the hook payload deserves a wiki nudge.

Args:
    payload: Parsed PreToolUse hook payload (``tool_name``,
        ``tool_input``, ``cwd``...).
    root: Repository root override (resolved from ``cwd`` when
        omitted).
    config: Project config override (loaded from ``root`` when
        omitted).
    now: Clock override for tests.

Returns:
    The hook response JSON object, or ``None`` when no nudge
    should be emitted.
