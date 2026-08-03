# Bedrock Mantle Client

**Audience**: Engineers who want to call Bedrock-hosted models through the
plain OpenAI SDK path, without SigV4 signing or the native Converse API.

**Related files**:

- `packages/ai-parrot/src/parrot/clients/nova/mantle.py` — `BedrockMantleClient`
- `packages/ai-parrot/src/parrot/clients/gpt.py` — inherited `OpenAIClient` machinery
- `packages/ai-parrot/src/parrot/clients/factory.py` — `LLMFactory` registration
- `packages/ai-parrot/tests/clients/test_bedrock_mantle.py` — unit tests
- `sdd/specs/bedrock-mantle-client.spec.md` — full design (FEAT-407)

---

## What This Is

Amazon Bedrock's **Project Mantle** exposes an OpenAI-compatible API for
Bedrock-hosted models (`openai.gpt-oss-120b`, `anthropic.claude-*`, …) at
`https://bedrock-mantle.<region>.api.aws/v1`, authenticated with a Bedrock
API key as a plain bearer token — no AWS SigV4 signing, no `aioboto3`.

`BedrockMantleClient` is a thin subclass of `OpenAIClient` (the same
gateway pattern as `NvidiaClient`, `OpenRouterClient`, `MoonshotClient`)
that only resolves the endpoint and API key before delegating every other
behavior — `ask`, `ask_stream`, `invoke`, tool-calling, structured output,
retry, fallback — to the inherited OpenAI machinery, unmodified.

This client coexists with, and does not replace:

- `BedrockConverseClient` (FEAT-302) — native Converse API, SigV4/boto.
- `NovaClient` (FEAT-315) — unified Amazon Nova client (text/voice/image/video), SigV4/boto.

Use Mantle when you want the plain OpenAI SDK call shape against
Bedrock-hosted models; use `BedrockConverseClient`/`NovaClient` when you
need the native Converse API or Nova's non-text modalities.

---

## Configuration

| Variable | Purpose | Fallback |
|---|---|---|
| `BEDROCK_MANTLE_API_KEY` | Dedicated Bedrock API key (bearer token) for Mantle | falls back to `AWS_NOVA_API_KEY` |
| `BEDROCK_MANTLE_BASE_URL` | Explicit endpoint override | falls back to the region-constructed URL |
| `BEDROCK_AWS_REGION` | Bedrock-specific region | falls back to `AWS_REGION_NAME`, then `"us-east-1"` |
| `AWS_REGION_NAME` | General AWS region | see above |
| `AWS_NOVA_API_KEY` | Existing Bedrock API key (shared with `NovaClient`/`BedrockConverseBase`) | final API-key fallback |

### Endpoint resolution (first match wins)

1. explicit `base_url` kwarg;
2. `BEDROCK_MANTLE_BASE_URL` conf var;
3. constructed: `https://bedrock-mantle.{region}.api.aws/v1`, where
   `region` = explicit `region` kwarg → `BEDROCK_AWS_REGION` →
   `AWS_REGION_NAME` → `"us-east-1"`.

### API-key resolution (first match wins)

1. explicit `api_key` kwarg;
2. `BEDROCK_MANTLE_API_KEY` conf var;
3. `AWS_NOVA_API_KEY` conf var.

A misconfigured region causes a DNS/connection failure, not an auth
error — Mantle is not available in every AWS region, so check the
resolved `base_url` first when debugging connectivity.

---

## Usage

### Direct construction

```python
from parrot.clients.nova import BedrockMantleClient

client = BedrockMantleClient(region="us-east-1")
async with client:
    response = await client.ask(
        "Explain quantum entanglement simply.",
        model="anthropic.claude-mythos-preview",
    )
    print(response.output)
```

### Via `LLMFactory` / an `llm=` string

Works anywhere an `llm` string is accepted (agents, crews, flows), using
either the full key or the `"mantle"` alias:

```python
from parrot.clients.factory import LLMFactory

client = LLMFactory.create("bedrock-mantle:openai.gpt-oss-120b")
# or the shorter alias:
client = LLMFactory.create("mantle:openai.gpt-oss-120b")
```

```python
from parrot.bots import Agent

agent = Agent(llm="bedrock-mantle:openai.gpt-oss-120b")
```

---

## Defaults

| Attribute | Value |
|---|---|
| `client_type` / `client_name` | `"bedrock-mantle"` |
| `_default_model` | `"openai.gpt-oss-120b"` |
| `_fallback_model` | `"google.gemma-4-26b-a4b"` (used for capacity-error retries) |

Model ids follow the `<vendor>.<model>` shape (e.g. `openai.gpt-oss-120b`,
`anthropic.claude-mythos-preview`) and are passed through as plain
strings — there is no `BedrockMantleModel` enum in v1.

---

## Out of Scope (v1)

- No SigV4/`aioboto3` code path — Mantle authenticates with a bearer key only.
- No Responses API (`client.responses.create`) — chat completions only.
- No voice/image/video modalities — text-only (use `NovaClient` for those).
- No `BedrockMantleModel` enum/catalog — the Mantle model list is fluid.
