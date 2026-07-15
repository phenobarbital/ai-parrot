---
type: Wiki Summary
title: parrot.tools.openapitoolkit
id: mod:parrot.tools.openapitoolkit
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: OpenAPIToolkit - Dynamic toolkit that exposes OpenAPI services as tools.
relates_to:
- concept: class:parrot.tools.openapitoolkit.OpenAPIToolkit
  rel: defines
- concept: mod:parrot.interfaces.http
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.tools.openapitoolkit`

OpenAPIToolkit - Dynamic toolkit that exposes OpenAPI services as tools.

IMPROVEMENTS IN THIS VERSION:
- Uses prance for robust OpenAPI parsing and reference resolution
- Inline schema refs via prance (no manual recursion)
- Support for application/x-www-form-urlencoded
- Optimized schemas for single-operation specs (cleaner LLM experience)

This toolkit automatically converts OpenAPI specifications into callable tools,
allowing LLMs to interact with REST APIs without manual tool definition.

Example:
    toolkit = OpenAPIToolkit(
        spec="https://petstore3.swagger.io/api/v3/openapi.json",
        service="petstore"
    )
    tools = toolkit.get_tools()
    # Creates tools like: petstore_get_pet, petstore_post_pet, etc.

## Classes

- **`OpenAPIToolkit(AbstractToolkit)`** — Toolkit that dynamically generates tools from OpenAPI specifications.
