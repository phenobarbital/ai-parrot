---
type: Wiki Summary
title: parrot.mcp.oauth_server
id: mod:parrot.mcp.oauth_server
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: OAuth server-side classes for MCP — extracted from parrot.mcp.oauth in FEAT-203.
relates_to:
- concept: class:parrot.mcp.oauth_server.APIKeyRecord
  rel: defines
- concept: class:parrot.mcp.oauth_server.APIKeyStore
  rel: defines
- concept: class:parrot.mcp.oauth_server.ClientRegistry
  rel: defines
- concept: class:parrot.mcp.oauth_server.ExternalOAuthValidator
  rel: defines
- concept: class:parrot.mcp.oauth_server.OAuthAuthorizationServer
  rel: defines
- concept: class:parrot.mcp.oauth_server.OAuthClient
  rel: defines
- concept: class:parrot.mcp.oauth_server.OAuthRoutesMixin
  rel: defines
- concept: mod:parrot.mcp.oauth
  rel: references
---

# `parrot.mcp.oauth_server`

OAuth server-side classes for MCP — extracted from parrot.mcp.oauth in FEAT-203.

These classes require ai-parrot-server to be installed. They provide the
full OAuth2 Authorization Server implementation, API key management,
external OAuth validator, and OAuth routes mixin for MCP server transports.

## Classes

- **`APIKeyRecord`** — Record for an issued API key.
- **`APIKeyStore`** — In-memory API key store with session logging.
- **`ExternalOAuthValidator`** — Validates tokens against external OAuth2 servers using RFC 7662 introspection.
- **`OAuthClient`**
- **`ClientRegistry`** — Minimal in-memory Dynamic Client Registration (RFC 7591) registry.
- **`OAuthAuthorizationServer`** — In-memory OAuth 2.0 authorization server for MCP transports.
- **`OAuthRoutesMixin`** — Shared OAuth/DCR utilities for HTTP and SSE transports.
