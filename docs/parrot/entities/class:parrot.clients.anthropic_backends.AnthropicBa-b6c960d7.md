---
type: Wiki Entity
title: AnthropicBackendProtocol
id: class:parrot.clients.anthropic_backends.AnthropicBackendProtocol
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Structural protocol for Anthropic backend strategies.
---

# AnthropicBackendProtocol

Defined in [`parrot.clients.anthropic_backends`](../summaries/mod:parrot.clients.anthropic_backends.md).

```python
class AnthropicBackendProtocol(Protocol)
```

Structural protocol for Anthropic backend strategies.

All three concrete backends (``DirectBackend``, ``BedrockBackend``,
``AWSWorkspaceBackend``) satisfy this protocol.  Annotating
``AnthropicClient._backend`` against it gives type-checkers and IDEs
precise completion without requiring a shared ABC.

## Methods

- `async def build_client(self)`
- `def translate_model(self, model: str) -> str`
