---
type: Wiki Entity
title: BedrockBackend
id: class:parrot.clients.anthropic_backends.BedrockBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Backend strategy for AWS Bedrock (``AsyncAnthropicBedrock``).
---

# BedrockBackend

Defined in [`parrot.clients.anthropic_backends`](../summaries/mod:parrot.clients.anthropic_backends.md).

```python
class BedrockBackend
```

Backend strategy for AWS Bedrock (``AsyncAnthropicBedrock``).

Translates public model IDs to Bedrock IDs via
:func:`parrot.models.bedrock_models.translate` before every SDK call.
AWS credentials are optional — pass ``None`` to fall through to the
standard AWS credential chain (``~/.aws/credentials`` / IAM role / IMDS).

Args:
    aws_region: AWS region (e.g. ``"us-east-1"``).
    aws_access_key: AWS access key ID.  ``None`` → SDK chain.
    aws_secret_key: AWS secret access key.  ``None`` → SDK chain.
    aws_session_token: Optional STS session token.  ``None`` → omitted.
    region_prefix: Cross-region inference-profile prefix (``"us"``,
        ``"eu"``, ``"apac"``).  ``None`` → no prefix.

## Methods

- `async def build_client(self) -> 'AsyncAnthropicBedrock'` — Build and return an ``AsyncAnthropicBedrock`` SDK client.
- `def translate_model(self, model: str) -> str` — Translate *model* to its AWS Bedrock ID.
