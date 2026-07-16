---
type: Wiki Summary
title: parrot.clients.anthropic_backends
id: mod:parrot.clients.anthropic_backends
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Composable backend strategy objects for AnthropicClient (FEAT-232).
relates_to:
- concept: class:parrot.clients.anthropic_backends.AWSWorkspaceBackend
  rel: defines
- concept: class:parrot.clients.anthropic_backends.AnthropicBackendProtocol
  rel: defines
- concept: class:parrot.clients.anthropic_backends.BedrockBackend
  rel: defines
- concept: class:parrot.clients.anthropic_backends.DirectBackend
  rel: defines
- concept: mod:parrot.models.bedrock_models
  rel: references
---

# `parrot.clients.anthropic_backends`

Composable backend strategy objects for AnthropicClient (FEAT-232).

Each backend encapsulates the SDK-client construction and model-ID
translation for one Anthropic transport:

- ``DirectBackend``       — direct Anthropic API (``AsyncAnthropic``).
- ``BedrockBackend``      — AWS Bedrock (``AsyncAnthropicBedrock``).
- ``AWSWorkspaceBackend`` — Claude-on-AWS workspace (``AsyncAnthropicAWS``).

``AnthropicClient.__init__`` resolves credentials from parrot.conf → env →
``None`` (SDK chain) and passes the resolved values to the chosen backend
via ``__init__``.  ``AnthropicClient.get_client()`` delegates to
``backend.build_client()``.

Usage::

    backend = BedrockBackend(
        aws_region="us-east-1",
        aws_access_key="AKIA...",
        aws_secret_key="...",
        aws_session_token=None,
        region_prefix="us",
    )
    sdk_client = await backend.build_client()
    translated = backend.translate_model("claude-sonnet-4-6")

## Classes

- **`AnthropicBackendProtocol(Protocol)`** — Structural protocol for Anthropic backend strategies.
- **`DirectBackend`** — Backend strategy for the direct Anthropic API (``AsyncAnthropic``).
- **`BedrockBackend`** — Backend strategy for AWS Bedrock (``AsyncAnthropicBedrock``).
- **`AWSWorkspaceBackend`** — Backend strategy for Claude-on-AWS (``AsyncAnthropicAWS``).
