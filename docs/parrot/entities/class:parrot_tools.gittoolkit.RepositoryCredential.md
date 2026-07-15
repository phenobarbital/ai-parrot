---
type: Wiki Entity
title: RepositoryCredential
id: class:parrot_tools.gittoolkit.RepositoryCredential
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Credentials + defaults for a single named repository in a registry.
---

# RepositoryCredential

Defined in [`parrot_tools.gittoolkit`](../summaries/mod:parrot_tools.gittoolkit.md).

```python
class RepositoryCredential(BaseModel)
```

Credentials + defaults for a single named repository in a registry.

Each entry in :attr:`GitToolkit.repositories` is one of these. The alias
(the dict key) is how tools reference the repository by name; the
``repository`` field is the underlying ``owner/name`` slug used to build
GitHub API URLs.
