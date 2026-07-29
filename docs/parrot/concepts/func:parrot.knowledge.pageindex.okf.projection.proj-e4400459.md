---
type: Concept
title: project_sidecar()
id: func:parrot.knowledge.pageindex.okf.projection.project_sidecar
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Combine projected frontmatter and existing body into a sidecar string.
---

# project_sidecar

```python
def project_sidecar(node: dict, tree_name: str, body: str) -> str
```

Combine projected frontmatter and existing body into a sidecar string.

Args:
    node: OKF-enriched PageIndex node dict (must have ``concept_id``).
    tree_name: PageIndex tree name (used in resource URI).
    body: Existing sidecar body content (preserved verbatim).

Returns:
    Complete sidecar string: frontmatter + blank line + body.
