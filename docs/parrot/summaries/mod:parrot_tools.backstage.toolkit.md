---
type: Wiki Summary
title: parrot_tools.backstage.toolkit
id: mod:parrot_tools.backstage.toolkit
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: BackstageCatalogToolkit — Read entries from a Backstage.io software catalog.
relates_to:
- concept: class:parrot_tools.backstage.toolkit.BackstageCatalogToolkit
  rel: defines
- concept: mod:parrot.interfaces.http
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
- concept: mod:parrot_tools.backstage.models
  rel: references
---

# `parrot_tools.backstage.toolkit`

BackstageCatalogToolkit — Read entries from a Backstage.io software catalog.

Extends OpenAPIToolkit to auto-generate tools from the official Backstage
Catalog Backend OpenAPI spec, and adds curated convenience methods for the
most frequent catalog operations.

Usage:
    toolkit = BackstageCatalogToolkit(
        base_url="https://backstage.example.com/api/catalog",
        api_key="<backstage-token>",
    )
    tools = toolkit.get_tools()

Environment variables:
    BACKSTAGE_BASE_URL  — Base URL of the Backstage catalog API
    BACKSTAGE_API_KEY   — Bearer token for authentication

## Classes

- **`BackstageCatalogToolkit(AbstractToolkit)`** — Toolkit for reading entries from a Backstage.io software catalog.
