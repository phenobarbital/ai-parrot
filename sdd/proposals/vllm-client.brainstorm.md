# Brainstorm: vLLM Client Integration

**Date**: 2026-03-04
**Author**: Claude
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

The project needs a dedicated client for consuming **vLLM** (https://vllm.ai/) local LLM servers, supporting the standard `ask` and `ask_stream` methods compatible with `OpenAIClient` and `AnthropicClient`.

**Current State:**
The codebase already has `LocalLLMClient` (`parrot/clients/localllm.py`) which extends `OpenAIClient` and supports vLLM through its OpenAI-compatible `/v1` API. The default base URL is `http://localhost:8000/v1` (vLLM's default).

**Gap Analysis:**
1. **No explicit vLLM branding** — Users must know to use `LocalLLMClient` for vLLM
2. **Missing vLLM-specific features** — Guided/structured output via JSON schema, LoRA adapters, custom sampling, batching
3. **No vLLM model enumeration** — Model enum references Ollama models, not vLLM patterns
4. **Missing server management** — No helpers for vLLM server lifecycle, health checks specific to vLLM endpoints

**Users affected**: Developers deploying self-hosted LLMs via vLLM for production inference, ML engineers needing vLLM-specific features.

**Why now**: vLLM is the de-facto standard for high-throughput LLM serving. Having explicit vLLM support improves discoverability and enables vLLM-specific optimizations.

## Constraints & Requirements

- Must implement `ask()` and `ask_stream()` matching `AbstractClient` interface
- Must be compatible with existing agent patterns (tools, structured output, conversation history)
- Must work with vLLM's OpenAI-compatible API (`/v1/chat/completions`)
- Should expose vLLM-specific features when available
- Should maintain async-first patterns (all methods async)
- Should follow existing client conventions (`client_type`, `client_name`, model handling)
- Must support configurable `base_url` (vLLM can run on any host/port)

---

## Options Explored

### Option A: vLLMClient as Alias to LocalLLMClient

Create a simple alias/subclass that just renames `LocalLLMClient` to `vLLMClient` with vLLM-specific defaults.

```python
class vLLMClient(LocalLLMClient):
    """Alias for vLLM servers."""
    client_type: str = "vllm"
    client_name: str = "vllm"
```

**Pros:**
- Trivial implementation — essentially just a rename
- All existing `LocalLLMClient` functionality works immediately
- No new dependencies
- Zero maintenance overhead

**Cons:**
- Doesn't expose vLLM-specific features (guided output, LoRA, etc.)
- No vLLM-specific model handling
- Just a naming convenience, not a real improvement
- Users might expect vLLM-specific capabilities

**Effort:** Very Low (< 1 hour)

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `openai` | OpenAI Python SDK | Already in dependencies |

**Existing Code to Reuse:**
| Path | Description |
|---|---|
| `parrot/clients/localllm.py` | LocalLLMClient (inherit directly) |
| `parrot/clients/gpt.py` | OpenAIClient base implementation |

---

### Option B: vLLMClient with vLLM-Specific Features (Recommended)

Create a dedicated `vLLMClient` that extends `LocalLLMClient` but adds vLLM-specific capabilities:

1. **Guided/Structured Output** — vLLM supports JSON schema-constrained generation via `guided_json` parameter
2. **LoRA Adapter Support** — Ability to specify LoRA adapter names per request
3. **vLLM Sampling Parameters** — `top_k`, `min_p`, `repetition_penalty`, `length_penalty`
4. **Token-Level Metrics** — Parse vLLM's extended response metadata
5. **Server Info Endpoint** — Query `/health` and `/version` for diagnostics
6. **Model List Integration** — Better handling of `/v1/models` for vLLM-served models

**Implementation:**
```python
class vLLMClient(LocalLLMClient):
    client_type: str = "vllm"
    client_name: str = "vllm"

    async def ask(
        self,
        prompt: str,
        model: str = None,
        guided_json: Optional[Dict] = None,
        lora_adapter: Optional[str] = None,
        top_k: int = -1,
        min_p: float = 0.0,
        **kwargs
    ) -> AIMessage:
        # Add vLLM-specific extra_body parameters
        ...
```

**Pros:**
- Explicit vLLM client improves discoverability
- Exposes vLLM's unique features (guided output, LoRA)
- Maintains compatibility with existing agent patterns
- Can fall back to standard OpenAI-compatible behavior
- Enables vLLM-specific optimizations

**Cons:**
- More code to maintain than Option A
- Some features require vLLM 0.5.0+ (need to document version requirements)
- Users of basic vLLM functionality might not need the extra features

**Effort:** Medium (2-4 hours)

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `openai` | OpenAI Python SDK | Already in dependencies |
| `aiohttp` | Async HTTP for health endpoints | Already in dependencies |
| `pydantic` | Request/response models | Already in dependencies |

**Existing Code to Reuse:**
| Path | Description |
|---|---|
| `parrot/clients/localllm.py` | LocalLLMClient base |
| `parrot/clients/gpt.py` | OpenAIClient.ask() implementation |
| `parrot/models/basic.py` | StructuredOutputConfig |

---

### Option C: Native vLLM Python SDK Client

Use vLLM's native Python SDK (`vllm.LLM` or `vllm.AsyncLLMEngine`) for direct inference without going through the OpenAI API layer.

This approach embeds vLLM inference directly in the process, eliminating the HTTP layer but requiring vLLM to be installed as a library.

**Pros:**
- Lowest latency — no HTTP overhead
- Full access to vLLM internals (KV cache stats, scheduling)
- Direct tensor control for advanced use cases
- Supports offline batching with optimal GPU utilization

**Cons:**
- Requires `vllm` package installed (heavy dependency, GPU-specific)
- Process must own the GPU — conflicts with other applications
- Not compatible with remote vLLM servers
- Breaks the "client talks to server" model
- Much more complex implementation
- Different async patterns than other clients

**Effort:** High (8-16 hours)

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `vllm` | Native vLLM engine | Heavy dependency (~2GB with CUDA) |
| `torch` | PyTorch backend | Required by vLLM |
| `transformers` | Model loading | Required by vLLM |

**Existing Code to Reuse:**
| Path | Description |
|---|---|
| `parrot/clients/base.py` | AbstractClient interface (must implement) |

---

## Recommendation

**Option B: vLLMClient with vLLM-Specific Features**

**Rationale:**
1. **Discoverability** — Users looking for vLLM support will find `vLLMClient` immediately
2. **Progressive Enhancement** — Works as a standard OpenAI-compatible client, but unlocks vLLM features when needed
3. **Minimal Overhead** — Extends existing `LocalLLMClient`, reuses 90% of the code
4. **Future-Proof** — Easy to add more vLLM features as they become available

**Key Tradeoffs:**
- Accepting medium effort for better user experience over trivial alias (Option A)
- Avoiding heavy native SDK dependency that breaks remote server model (Option C)

---

## Feature Description

### User-Facing Behavior

Developers can instantiate `vLLMClient` to interact with local or remote vLLM servers:

```python
from parrot.clients.vllm import vLLMClient

# Basic usage (OpenAI-compatible)
client = vLLMClient(base_url="http://localhost:8000/v1")
response = await client.ask("Hello, world!", model="meta-llama/Llama-3.1-8B-Instruct")

# Streaming
async for chunk in client.ask_stream("Tell me a story", model="meta-llama/Llama-3.1-8B-Instruct"):
    print(chunk, end="")

# vLLM-specific: Guided JSON output
response = await client.ask(
    "Extract the person's name and age from: 'John is 30 years old'",
    model="meta-llama/Llama-3.1-8B-Instruct",
    guided_json={"type": "object", "properties": {"name": {"type": "string"}, "age": {"type": "integer"}}}
)

# vLLM-specific: LoRA adapter
response = await client.ask(
    "Summarize this document...",
    model="meta-llama/Llama-3.1-8B-Instruct",
    lora_adapter="my-finetuned-adapter"
)
```

### Internal Behavior

1. **Initialization:**
   - Resolve `base_url` from parameter → `VLLM_BASE_URL` env → default `http://localhost:8000/v1`
   - Resolve optional `api_key` from parameter → `VLLM_API_KEY` env → `None`
   - Create `AsyncOpenAI` client pointing to vLLM server

2. **ask() Flow:**
   - Build standard chat completion request
   - Add vLLM-specific parameters to `extra_body` if provided:
     - `guided_json`, `guided_regex`, `guided_choice` for constrained generation
     - `lora_request` for LoRA adapters
     - Extended sampling parameters (`top_k`, `min_p`, etc.)
   - Send request via `AsyncOpenAI.chat.completions.create()`
   - Parse response into `AIMessage` with usage stats

3. **ask_stream() Flow:**
   - Same as `ask()` but with `stream=True`
   - Yield text chunks via async generator
   - Handle SSE stream parsing

4. **Health/Diagnostics:**
   - `health_check()` — Query `/health` endpoint
   - `list_models()` — Query `/v1/models` endpoint
   - `server_info()` — Query vLLM-specific `/version` endpoint

### Edge Cases & Error Handling

| Scenario | Handling |
|---|---|
| Server unreachable | Raise `ConnectionError` with helpful message including base_url |
| Model not found | Raise `ValueError` with list of available models from `/v1/models` |
| Invalid guided_json schema | Let vLLM return 400, propagate error with schema details |
| LoRA adapter not loaded | Let vLLM return error, propagate with adapter name |
| Request timeout | Use configurable timeout (default 120s), raise `TimeoutError` |
| Rate limiting | Implement exponential backoff (reuse from OpenAIClient) |
| Streaming disconnect | Yield partial content, raise `StreamingError` on premature close |

---

## Capabilities

### New Capabilities

| Capability | Description |
|---|---|
| `vllm-ask` | Send prompt to vLLM server, receive completion |
| `vllm-ask-stream` | Stream completion tokens from vLLM server |
| `vllm-guided-output` | Constrained generation using JSON schema |
| `vllm-lora-adapter` | Request-time LoRA adapter selection |
| `vllm-health-check` | Verify vLLM server connectivity |
| `vllm-list-models` | List models served by vLLM instance |

### Modified Capabilities

| Capability | Modification |
|---|---|
| `client-factory` | Register `vllm` client type for factory pattern |

---

## Impact & Integration

| Component | Impact |
|---|---|
| `parrot/clients/vllm.py` | CREATE — New vLLMClient implementation |
| `parrot/models/vllm.py` | CREATE — vLLM model enum and request models |
| `parrot/clients/factory.py` | MODIFY — Register vLLMClient |
| `parrot/clients/__init__.py` | MODIFY — Export vLLMClient |
| `tests/test_vllm_client.py` | CREATE — Unit tests |

---

## Open Questions

| Question | Owner | Notes |
|---|---|---|
| Should `guided_json` integrate with existing `StructuredOutputConfig`? | Developer | Could map StructuredOutputConfig to vLLM's guided_json format |
| Should we expose vLLM's `prefix_caching` parameter? | Developer | Advanced feature, may be out of scope for v1 |
| Should the client auto-detect vLLM vs Ollama based on `/version` response? | Developer | Could be useful but adds complexity |
| Should we support vLLM's batch API (`/v1/batch`)? | Developer | Yes

---

## References

- vLLM Documentation: https://docs.vllm.ai/
- vLLM OpenAI-Compatible Server: https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html
- vLLM Guided Decoding: https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html#guided-decoding
- vLLM LoRA Support: https://docs.vllm.ai/en/latest/models/lora.html
- Existing LocalLLMClient: `parrot/clients/localllm.py`
