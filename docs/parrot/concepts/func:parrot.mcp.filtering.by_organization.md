---
type: Concept
title: by_organization()
id: func:parrot.mcp.filtering.by_organization
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create predicate that restricts to specific organizations (multi-tenancy).
---

# by_organization

```python
def by_organization(allowed_org_ids: List[str]) -> ToolPredicate
```

Create predicate that restricts to specific organizations (multi-tenancy).

Args:
    allowed_org_ids: List of organization IDs that can access tools

Returns:
    ToolPredicate that checks organization via context

Example:
    >>> predicate = by_organization(['acme-corp', 'widgets-inc'])
    >>> # Only these organizations can use the tools
