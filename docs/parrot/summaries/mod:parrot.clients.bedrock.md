---
type: Wiki Summary
title: parrot.clients.bedrock
id: mod:parrot.clients.bedrock
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Native AWS Bedrock Converse API client for AI-Parrot (FEAT-302).
relates_to:
- concept: class:parrot.clients.bedrock.BedrockConverseClient
  rel: defines
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.core.exceptions
  rel: references
- concept: mod:parrot.exceptions
  rel: references
- concept: mod:parrot.models.basic
  rel: references
- concept: mod:parrot.models.bedrock_models
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.clients.bedrock`

Native AWS Bedrock Converse API client for AI-Parrot (FEAT-302).

Implements :class:`BedrockConverseClient`, an async-first
:class:`~parrot.clients.base.AbstractClient` subclass that talks to the AWS
Bedrock Runtime *Converse* API directly via ``aioboto3`` — as opposed to
:class:`~parrot.clients.claude.AnthropicClient`'s ``backend="bedrock"``,
which routes through the Anthropic SDK's ``AsyncAnthropicBedrock`` transport
(FEAT-232) and is therefore limited to Claude models.

This module implements Spec Module 4 ("BedrockConverseClient — Core"):
session/client management, the Converse API tool-use loop, streaming,
``resume()``, and a lightweight ``invoke()``. Module 5 ("Advanced
Features", TASK-1746) adds extended thinking, prompt caching, schema-based
structured output, guardrails (``apply_guardrail_text()``), and the
``_invoke_native()`` fallback for models without ARN-versioned IDs.
Factory registration is Module 6 (TASK-1747).

See ``sdd/specs/bedrock-client-llm.spec.md`` for the full design.

## Classes

- **`BedrockConverseClient(AbstractClient)`** — Client for AWS Bedrock's native Converse API.
