---
type: Concept
title: integration_status()
id: func:parrot.knowledge.wiki.claude_code.installer.integration_status
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Report which integration pieces are currently installed.
---

# integration_status

```python
def integration_status(root: Path) -> dict[str, Any]
```

Report which integration pieces are currently installed.

Args:
    root: Repository root.

Returns:
    Mapping of artifact name → bool (or detail string).
