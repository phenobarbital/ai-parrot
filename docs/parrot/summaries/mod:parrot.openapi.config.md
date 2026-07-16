---
type: Wiki Summary
title: parrot.openapi.config
id: mod:parrot.openapi.config
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: OpenAPI Configuration for AI-Parrot
relates_to:
- concept: func:parrot.openapi.config.get_common_responses
  rel: defines
- concept: func:parrot.openapi.config.get_security_schemes
  rel: defines
- concept: func:parrot.openapi.config.setup_swagger
  rel: defines
---

# `parrot.openapi.config`

OpenAPI Configuration for AI-Parrot
====================================

Configure aiohttp-swagger3 with complete OpenAPI 3.0 schemas for all handlers.

## Functions

- `def setup_swagger(app: web.Application) -> web.Application` — Configure Swagger/OpenAPI documentation for AI-Parrot.
- `def get_common_responses()` — Common HTTP responses used across all endpoints.
- `def get_security_schemes()` — Security schemes for API authentication.
