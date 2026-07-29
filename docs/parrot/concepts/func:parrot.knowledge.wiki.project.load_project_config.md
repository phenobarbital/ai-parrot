---
type: Concept
title: load_project_config()
id: func:parrot.knowledge.wiki.project.load_project_config
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Load the repo's wiki config.
---

# load_project_config

```python
def load_project_config(root: Path) -> WikiProjectConfig
```

Load the repo's wiki config.

Args:
    root: Repository root.

Returns:
    Parsed config; defaults (with ``wiki_name`` set to the repo
    directory name) when no config file exists.

Raises:
    WikiConfigError: When a config file exists but is invalid —
        silently substituting defaults would let the next
        ``save_project_config`` clobber the user's settings.
