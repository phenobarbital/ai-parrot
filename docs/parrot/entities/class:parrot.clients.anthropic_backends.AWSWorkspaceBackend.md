---
type: Wiki Entity
title: AWSWorkspaceBackend
id: class:parrot.clients.anthropic_backends.AWSWorkspaceBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Backend strategy for Claude-on-AWS (``AsyncAnthropicAWS``).
---

# AWSWorkspaceBackend

Defined in [`parrot.clients.anthropic_backends`](../summaries/mod:parrot.clients.anthropic_backends.md).

```python
class AWSWorkspaceBackend
```

Backend strategy for Claude-on-AWS (``AsyncAnthropicAWS``).

Both ``aws_region`` **and** ``workspace_id`` are mandatory — the SDK
raises at construction time if either is missing with no fallback.
This backend validates them eagerly in ``build_client()`` and raises a
clear ``ValueError`` naming the env var to set.

The SDK parameter is ``workspace_id`` (NOT ``aws_workspace_id``); the
conf/env constant is ``ANTHROPIC_AWS_WORKSPACE_ID``, which is mapped
to ``workspace_id`` at the call site.

AWS credentials are optional (``aws_access_key`` / ``aws_secret_key``
/ ``aws_session_token`` / ``aws_profile``); pass ``None`` to let the
SDK use the standard AWS chain.

Args:
    aws_region: AWS region — **mandatory**.
    workspace_id: Claude-on-AWS workspace ID — **mandatory**.
    aws_access_key: AWS access key ID.  ``None`` → SDK chain.
    aws_secret_key: AWS secret access key.  ``None`` → SDK chain.
    aws_session_token: Optional STS session token.  ``None`` → omitted.
    aws_profile: Optional AWS profile name.  ``None`` → omitted.

## Methods

- `async def build_client(self) -> 'AsyncAnthropicAWS'` — Build and return an ``AsyncAnthropicAWS`` SDK client.
- `def translate_model(self, model: str) -> str` — Identity — AWS-workspace uses public model IDs unchanged.
