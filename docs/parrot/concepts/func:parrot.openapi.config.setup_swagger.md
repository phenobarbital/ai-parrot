---
type: Concept
title: setup_swagger()
id: func:parrot.openapi.config.setup_swagger
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configure Swagger/OpenAPI documentation for AI-Parrot.
---

# setup_swagger

```python
def setup_swagger(app: web.Application) -> web.Application
```

Configure Swagger/OpenAPI documentation for AI-Parrot.

Enables three UI options:
- Swagger UI at /api/docs
- ReDoc at /api/docs/redoc
- RapiDoc at /api/docs/rapidoc

Args:
    app: aiohttp Application instance

Returns:
    Configured application with documentation endpoints
