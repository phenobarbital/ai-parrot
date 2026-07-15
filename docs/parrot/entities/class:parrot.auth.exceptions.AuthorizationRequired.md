---
type: Wiki Entity
title: AuthorizationRequired
id: class:parrot.auth.exceptions.AuthorizationRequired
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when a toolkit needs user authorization before operating.
---

# AuthorizationRequired

Defined in [`parrot.auth.exceptions`](../summaries/mod:parrot.auth.exceptions.md).

```python
class AuthorizationRequired(Exception)
```

Raised when a toolkit needs user authorization before operating.

``ToolManager.execute_tool`` catches this exception and converts it into
a :class:`parrot.tools.abstract.ToolResult` with
``status='authorization_required'``.  The metadata carries the
``auth_url`` and ``provider`` so the agent/LLM can present an actionable
link to the end user.

Typical producer: a toolkit's :meth:`_pre_execute` hook that resolves
per-user OAuth 2.0 tokens from Redis and discovers none are on file.

Attributes:
    tool_name: Name of the tool that failed the authorization check.
    message: Human-readable description for logs and the LLM.
    auth_url: URL that the user should open to complete the authorization
        flow. ``None`` when no URL is available yet.
    provider: Identifier of the external provider (``"jira"``,
        ``"github"``, ``"o365"``, …). Defaults to ``"unknown"``.
    scopes: Scopes that the provider should grant during consent.
