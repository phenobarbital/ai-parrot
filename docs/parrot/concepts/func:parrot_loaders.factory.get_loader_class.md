---
type: Concept
title: get_loader_class()
id: func:parrot_loaders.factory.get_loader_class
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Get the loader class for the given extension.
---

# get_loader_class

```python
def get_loader_class(extension: str)
```

Get the loader class for the given extension.
Lazy loads the module to avoid eager dependency loading.
