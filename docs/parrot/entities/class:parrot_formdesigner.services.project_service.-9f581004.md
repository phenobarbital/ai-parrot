---
type: Wiki Entity
title: ProjectNotFoundError
id: class:parrot_formdesigner.services.project_service.ProjectNotFoundError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when a project lookup returns no row.
---

# ProjectNotFoundError

Defined in [`parrot_formdesigner.services.project_service`](../summaries/mod:parrot_formdesigner.services.project_service.md).

```python
class ProjectNotFoundError(Exception)
```

Raised when a project lookup returns no row.

Attributes:
    project_id: The missing project identifier.
