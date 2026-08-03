---
kind: inline
jira_key: null
fetched_at: 2026-08-03T00:00:00Z
summary_oneline: Extend FEAT-397 per-round token usage observability to BedrockClient and NovaClient
---

# Source (inline)

Slug requested: `bedrock-per-round-token`

> At FEAT-397 we implement per-round token usage observability and several
> clients as OpenAI, Gemini, Claude or Grok were implemented, this proposal
> is for including BedrockClient and NovaClient into the per-round token
> observability.

## Interpretation

FEAT-397 (`sdd/specs/tokens-observability.spec.md`) delivered per-round
token-usage accumulation across an agent's tool-calling loop for five
clients: `AnthropicClient`, `OpenAIClient`, `GoogleGenAIClient`,
`GroqClient` and `GrokClient`. AWS-backed clients (`BedrockClient`,
and the Nova family) were an explicit non-goal of that spec, with a
follow-up deferred.

This proposal covers that follow-up: bringing the AWS Bedrock / Nova
clients up to the same per-round observability contract.
