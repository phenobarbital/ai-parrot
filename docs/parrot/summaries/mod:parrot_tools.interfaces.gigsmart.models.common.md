---
type: Wiki Summary
title: parrot_tools.interfaces.gigsmart.models.common
id: mod:parrot_tools.interfaces.gigsmart.models.common
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Common / shared models — Relay pagination generics and OAuth token.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.models.common.OAuthToken
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.models.common.RelayConnection
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.models.common.RelayEdge
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.models.common.RelayPageInfo
  rel: defines
---

# `parrot_tools.interfaces.gigsmart.models.common`

Common / shared models — Relay pagination generics and OAuth token.

All models in this module are pure Pydantic v2 data classes with no
dependencies on GigSmart-specific types. They are reused across every
API surface.

## Classes

- **`RelayPageInfo(BaseModel)`** — GraphQL Relay PageInfo fragment.
- **`RelayEdge(BaseModel, Generic[T])`** — A single edge in a Relay connection.
- **`RelayConnection(BaseModel, Generic[T])`** — A Relay pagination connection wrapping a list of typed edges.
- **`OAuthToken(BaseModel)`** — Parsed OAuth 2.1 token response from the GigSmart token endpoint.
