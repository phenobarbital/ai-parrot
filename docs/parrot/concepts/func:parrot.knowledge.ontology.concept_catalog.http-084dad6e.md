---
type: Concept
title: list_concepts()
id: func:parrot.knowledge.ontology.concept_catalog.http.list_concepts
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: GET /api/ontology/concepts — list concepts for a tenant.
---

# list_concepts

```python
async def list_concepts(request: web.Request) -> web.Response
```

GET /api/ontology/concepts — list concepts for a tenant.

Query params: ``tenant`` (required if not in session), ``state``, ``domain``,
``limit`` (default 50, max 200), ``offset`` (default 0).
