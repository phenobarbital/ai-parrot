---
type: Concept
title: save_project_config()
id: func:parrot.knowledge.wiki.project.save_project_config
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Persist the wiki config to ``.parrot/wiki.json``.
---

# save_project_config

```python
def save_project_config(root: Path, config: WikiProjectConfig) -> Path
```

Persist the wiki config to ``.parrot/wiki.json``.

Args:
    root: Repository root.
    config: Config to write.

Returns:
    The path written.
