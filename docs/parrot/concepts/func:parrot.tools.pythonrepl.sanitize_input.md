---
type: Concept
title: sanitize_input()
id: func:parrot.tools.pythonrepl.sanitize_input
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Sanitize input to the python REPL.
---

# sanitize_input

```python
def sanitize_input(query: str) -> str
```

Sanitize input to the python REPL.
Remove whitespace, backtick & python (if llm mistakes python console as terminal)

Args:
    query: The query to sanitize

Returns:
    The sanitized query
