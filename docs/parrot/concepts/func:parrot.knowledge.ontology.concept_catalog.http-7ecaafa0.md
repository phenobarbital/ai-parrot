---
type: Concept
title: register_routes()
id: func:parrot.knowledge.ontology.concept_catalog.http.register_routes
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register all concept catalog routes on *app*.
---

# register_routes

```python
def register_routes(app: web.Application, prefix: str='/api/ontology') -> None
```

Register all concept catalog routes on *app*.

Args:
    app: aiohttp Application instance.
    prefix: URL prefix for the routes (default ``/api/ontology``).
