---
type: Concept
title: discover_all()
id: func:parrot.tools.discovery.discover_all
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Combined discovery: fast registry + walk for plugins.'
---

# discover_all

```python
def discover_all(sources: list[str] | None=None) -> Dict[str, Union[str, Type]]
```

Combined discovery: fast registry + walk for plugins.

Returns dict where values are either:
- str (dotted path, from registry — lazy, not yet imported)
- Type (class, from walk — already imported)
