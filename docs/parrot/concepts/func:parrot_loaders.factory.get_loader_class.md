---
type: Concept
title: get_loader_class()
id: func:parrot_loaders.factory.get_loader_class
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Get the loader class for the given extension.
---

# get_loader_class

```python
def get_loader_class(extension: str)
```

Get the loader class for the given extension.
Lazy loads the module to avoid eager dependency loading.
