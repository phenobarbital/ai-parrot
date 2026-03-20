# FEAT-022: vLLM Client Integration

**Status**: approved
**Created**: 2026-03-04
**Author**: Claude
**Brainstorm**: `sdd/proposals/vllm-client.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

The project needs a dedicated client for consuming **vLLM** (https://vllm.ai/) local LLM servers, supporting the standard `ask` and `ask_stream` methods compatible with `OpenAIClient` and `AnthropicClient`.

**Current State:**
The codebase already has `LocalLLMClient` (`parrot/clients/localllm.py`) which extends `OpenAIClient` and supports vLLM through its OpenAI-compatible `/v1` API. The default base URL is `http://localhost:8000/v1` (vLLM's default).

**Gap Analysis:**
1. **No explicit vLLM branding** — Users must know to use `LocalLLMClient` for vLLM
2. **Missing vLLM-specific features** — Guided/structured output via JSON schema, LoRA adapters, custom sampling, batching
3. **No vLLM model enumeration** — Model enum references Ollama models, not vLLM patterns
4. **Missing server management** — No helpers for vLLM server lifecycle, health checks specific to vLLM endpoints

### Users Affected
- Developers deploying self-hosted LLMs via vLLM for production inference
- ML engineers needing vLLM-specific features like guided output and LoRA adapters

### Why Now
vLLM is the de-facto standard for high-throughput LLM serving. Having explicit vLLM support improves discoverability and enables vLLM-specific optimizations.

---

## 2. Architectural Design

### Chosen Approach: vLLMClient with vLLM-Specific Features

Create a dedicated `vLLMClient` that extends `LocalLLMClient` but adds vLLM-specific capabilities:

1. **Guided/Structured Output** — vLLM supports JSON schema-constrained generation via `guided_json` parameter, that can be used also "structured_output" where we can convert a pydantic datamodel into a "guided_json" using a helper method.
2. **LoRA Adapter Support** — Ability to specify LoRA adapter names per request
3. **vLLM Sampling Parameters** — `top_k`, `min_p`, `repetition_penalty`, `length_penalty`
4. **Token-Level Metrics** — Parse vLLM's extended response metadata
5. **Server Info Endpoint** — Query `/health` and `/version` for diagnostics
6. **Model List Integration** — Better handling of `/v1/models` for vLLM-served models
7. **Batch API Support** — Expose vLLM's `/v1/batch` endpoint for batch processing

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      User Code                               │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                      vLLMClient                              │
│  - ask() with guided_json, lora_adapter                     │
│  - ask_stream() with vLLM sampling params                   │
│  - health_check(), list_models(), server_info()             │
│  - batch_process()                                          │
└──────────────────────────┬──────────────────────────────────┘
                           │ extends
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    LocalLLMClient                            │
│  - OpenAI-compatible ask/ask_stream                         │
│  - Configurable base_url                                    │
└──────────────────────────┬──────────────────────────────────┘
                           │ extends
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     OpenAIClient                             │
│  - AsyncOpenAI SDK                                          │
│  - Standard completion flow                                 │
└─────────────────────────────────────────────────────────────┘
```

### Integration Points

| Component | Integration |
|-----------|-------------|
| `parrot/clients/factory.py` | Register `vllm` client type |
| `parrot/bots/agent.py` | Use vLLMClient for tool-using agents |
| Existing agents | Transparent via AbstractClient interface |

### Key Tradeoffs
- **Accepting medium effort** for better user experience over trivial alias
- **Avoiding heavy native SDK dependency** that breaks remote server model
- **Building on existing LocalLLMClient** to reuse 90% of the code

---

## 3. Module Breakdown

### Module 1: vLLM Pydantic Models
**File**: `parrot/models/vllm.py`

Request/response models for vLLM-specific features:
- `VLLMConfig` — Client configuration (base_url, api_key, timeout)
- `VLLMSamplingParams` — Extended sampling parameters
- `VLLMLoRARequest` — LoRA adapter configuration
- `VLLMGuidedParams` — Guided decoding parameters
- `VLLMBatchRequest` / `VLLMBatchResponse` — Batch API models

### Module 2: vLLMClient Implementation
**File**: `parrot/clients/vllm.py`

The main client class extending `LocalLLMClient`:

```python
class vLLMClient(LocalLLMClient):
    client_type: str = "vllm"
    client_name: str = "vllm"

    async def ask(
        self,
        prompt: str,
        model: str = None,
        guided_json: Optional[Dict] = None,
        guided_regex: Optional[str] = None,
        guided_choice: Optional[List[str]] = None,
        lora_adapter: Optional[str] = None,
        top_k: int = -1,
        min_p: float = 0.0,
        repetition_penalty: float = 1.0,
        **kwargs
    ) -> AIMessage:
        ...

    async def ask_stream(
        self,
        prompt: str,
        model: str = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        ...

    async def health_check(self) -> bool:
        ...

    async def list_models(self) -> List[str]:
        ...

    async def server_info(self) -> Dict:
        ...

    async def batch_process(
        self,
        requests: List[Dict],
        **kwargs
    ) -> List[AIMessage]:
        ...
```

### Module 3: Factory Registration
**File**: `parrot/clients/factory.py` (MODIFY)

Register `vllm` client type in the client factory.

### Module 4: Client Exports
**File**: `parrot/clients/__init__.py` (MODIFY)

Export `vLLMClient` from the clients package.

### Module 5: Unit Tests
**File**: `tests/test_vllm_client.py`

Comprehensive tests covering:
- Basic ask/ask_stream functionality
- Guided output (JSON schema, regex, choices)
- LoRA adapter requests
- Extended sampling parameters
- Health check and server info
- Batch processing
- Error handling

---

## 4. API Specification

### vLLMClient Constructor

```python
vLLMClient(
    base_url: str = None,      # Default: VLLM_BASE_URL env or "http://localhost:8000/v1"
    api_key: str = None,       # Default: VLLM_API_KEY env or None
    timeout: int = 120,        # Request timeout in seconds
    **kwargs
)
```

### ask() Method

```python
async def ask(
    prompt: str,
    model: str = None,
    # Standard parameters
    temperature: float = 0.7,
    max_tokens: int = None,
    # vLLM-specific: Guided output (mutually exclusive)
    guided_json: Optional[Dict] = None,      # JSON schema for constrained generation
    guided_regex: Optional[str] = None,      # Regex pattern to match
    guided_choice: Optional[List[str]] = None,  # List of valid choices
    # vLLM-specific: LoRA
    lora_adapter: Optional[str] = None,      # Name of LoRA adapter to use
    # vLLM-specific: Sampling
    top_k: int = -1,
    min_p: float = 0.0,
    repetition_penalty: float = 1.0,
    length_penalty: float = 1.0,
    **kwargs
) -> AIMessage
```

### ask_stream() Method

Same parameters as `ask()`, returns `AsyncGenerator[str, None]`.

### Diagnostic Methods

```python
async def health_check(self) -> bool:
    """Check vLLM server health via /health endpoint."""

async def list_models(self) -> List[str]:
    """List available models via /v1/models endpoint."""

async def server_info(self) -> Dict:
    """Get vLLM server version and config via /version endpoint."""
```

### Batch Processing

```python
async def batch_process(
    requests: List[Dict],   # List of request dicts with prompt, model, etc.
    **kwargs
) -> List[AIMessage]:
    """Process multiple requests in a batch for optimal throughput."""
```

---

## 5. Acceptance Criteria

### Functional Requirements

- [ ] `vLLMClient` extends `LocalLLMClient` and inherits OpenAI-compatible behavior
- [ ] `ask()` method works with standard parameters (prompt, model, temperature)
- [ ] `ask_stream()` method yields text chunks via async generator
- [ ] `guided_json` parameter constrains output to JSON schema
- [ ] `guided_regex` parameter constrains output to regex pattern
- [ ] `guided_choice` parameter constrains output to list of choices
- [ ] `lora_adapter` parameter enables LoRA adapter selection per request
- [ ] Extended sampling parameters (`top_k`, `min_p`, etc.) are passed to vLLM
- [ ] `health_check()` queries `/health` and returns True/False
- [ ] `list_models()` queries `/v1/models` and returns model names
- [ ] `server_info()` queries `/version` and returns server metadata
- [ ] `batch_process()` processes multiple requests efficiently
- [ ] Client registered in factory with type `"vllm"`
- [ ] Environment variables `VLLM_BASE_URL` and `VLLM_API_KEY` are respected

### Error Handling

- [ ] `ConnectionError` raised when server is unreachable (with base_url in message)
- [ ] `ValueError` raised when model not found (with available models listed)
- [ ] `TimeoutError` raised when request exceeds timeout
- [ ] Invalid guided_json schema propagates vLLM's 400 error with details
- [ ] Missing LoRA adapter propagates vLLM's error with adapter name

### Non-Functional Requirements

- [ ] All methods are async (no blocking I/O)
- [ ] Reuses exponential backoff from OpenAIClient
- [ ] Configurable timeout (default 120 seconds)
- [ ] Unit tests achieve >90% code coverage

---

## 6. External Dependencies

| Package | Purpose | Notes |
|---------|---------|-------|
| `openai` | OpenAI Python SDK (AsyncOpenAI) | Already in dependencies |
| `aiohttp` | Async HTTP for health/version endpoints | Already in dependencies |
| `pydantic` | Request/response models | Already in dependencies |

No new dependencies required.

---

## 7. Open Questions

| Question | Status | Resolution |
|----------|--------|------------|
| Should `guided_json` integrate with existing `StructuredOutputConfig`? | Open | Could map StructuredOutputConfig to vLLM's guided_json format | Add a helper method to convert a pydantic model into `guided_json` syntax.
| Should we expose vLLM's `prefix_caching` parameter? | Deferred | Advanced feature, out of scope for v1 |
| Should the client auto-detect vLLM vs Ollama based on `/version` response? | Deferred | Could be useful but adds complexity |
| Should we support vLLM's batch API (`/v1/batch`)? | Resolved | Yes — include batch_process() method |

---

## 8. References

- vLLM Documentation: https://docs.vllm.ai/
- vLLM OpenAI-Compatible Server: https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html
- vLLM Guided Decoding: https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html#guided-decoding
- vLLM LoRA Support: https://docs.vllm.ai/en/latest/models/lora.html
- Existing LocalLLMClient: `parrot/clients/localllm.py`
- Brainstorm Document: `sdd/proposals/vllm-client.brainstorm.md`
