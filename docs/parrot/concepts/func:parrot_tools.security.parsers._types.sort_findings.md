---
type: Concept
title: sort_findings()
id: func:parrot_tools.security.parsers._types.sort_findings
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Sort findings by severity desc, then finding_id asc (deterministic).
---

# sort_findings

```python
def sort_findings(findings: list[EmbeddedFinding]) -> list[EmbeddedFinding]
```

Sort findings by severity desc, then finding_id asc (deterministic).

Args:
    findings: Unsorted list of EmbeddedFinding objects.

Returns:
    Sorted list (mutates a copy, not in-place).
