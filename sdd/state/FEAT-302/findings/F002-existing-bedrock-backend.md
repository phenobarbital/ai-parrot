---
id: F002
slug: existing-bedrock-backend
query: Read anthropic_backends.py and factory.py
type: read
---

## Finding: Existing Bedrock Integration (FEAT-232)

**Paths**:
- `packages/ai-parrot/src/parrot/clients/anthropic_backends.py` (line 98+)
- `packages/ai-parrot/src/parrot/clients/factory.py` (lines 48-80)

Current state: "bedrock" provider key maps to `AnthropicClient` with `backend="bedrock"`.
`BedrockBackend.build_client()` constructs `AsyncAnthropicBedrock` from the Anthropic SDK.
This uses the Anthropic Messages API over Bedrock transport — NOT the native Converse API.

`PROVIDER_BACKEND` dict: `{"bedrock": "bedrock", "anthropic-aws": "aws"}`.

**Limitation**: the Anthropic SDK Bedrock transport does NOT expose:
- Bedrock Guardrails (`guardrailConfig`)
- Multi-provider support (only Claude models)
- Nova Sonic or any non-Anthropic model
- Converse API features (uniform envelope, cachePoint, structured output via outputConfig)

A new native `BedrockClient` using `aioboto3` directly would coexist alongside the existing
`AnthropicClient` bedrock backend. Different provider keys needed (e.g. `bedrock-native` or `bedrock-converse`).
