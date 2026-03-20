# TASK-126: vLLMClient Implementation

**Feature**: FEAT-022 vLLM Client Integration
**Spec**: `sdd/specs/vllm-client.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-125
**Assigned-to**: claude-session

---

## Context

> This task implements Module 2 from the spec: vLLMClient Implementation.

Create the main `vLLMClient` class that extends `LocalLLMClient` and adds vLLM-specific features.

---

## Scope

- Create `vLLMClient` class extending `LocalLLMClient`
- Implement `ask()` method with vLLM-specific parameters
- Implement `ask_stream()` method with streaming support
- Implement `health_check()` method for server health
- Implement `list_models()` method for model enumeration
- Implement `server_info()` method for server metadata
- Implement `batch_process()` method for batch API
- Add `structured_output` parameter that converts Pydantic models to guided_json
- Handle environment variables `VLLM_BASE_URL` and `VLLM_API_KEY`

**NOT in scope**:
- Pydantic models (TASK-125)
- Factory registration (TASK-127)
- Tests (TASK-128)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/clients/vllm.py` | CREATE | vLLMClient implementation |

---

## Implementation Notes

### Class Structure

```python
from typing import Optional, Dict, List, Any, AsyncGenerator, Type
from pydantic import BaseModel
from .localllm import LocalLLMClient
from ..models.vllm import VLLMConfig, VLLMSamplingParams, pydantic_to_guided_json
from ..models.basic import AIMessage
import os

class vLLMClient(LocalLLMClient):
    """vLLM client with vLLM-specific features.

    Extends LocalLLMClient to add:
    - Guided output (JSON schema, regex, choices)
    - LoRA adapter support
    - Extended sampling parameters
    - Health check and server info
    - Batch processing
    """

    client_type: str = "vllm"
    client_name: str = "vllm"

    def __init__(
        self,
        base_url: str = None,
        api_key: str = None,
        timeout: int = 120,
        **kwargs
    ):
        # Resolve from env vars if not provided
        base_url = base_url or os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
        api_key = api_key or os.getenv("VLLM_API_KEY")

        super().__init__(base_url=base_url, api_key=api_key, **kwargs)
        self.timeout = timeout
```

### ask() Method with vLLM Features

```python
async def ask(
    self,
    prompt: str,
    model: str = None,
    # Standard parameters
    temperature: float = 0.7,
    max_tokens: int = None,
    # vLLM-specific: Guided output
    guided_json: Optional[Dict] = None,
    guided_regex: Optional[str] = None,
    guided_choice: Optional[List[str]] = None,
    structured_output: Optional[Type[BaseModel]] = None,  # Converts to guided_json
    # vLLM-specific: LoRA
    lora_adapter: Optional[str] = None,
    # vLLM-specific: Sampling
    top_k: int = -1,
    min_p: float = 0.0,
    repetition_penalty: float = 1.0,
    length_penalty: float = 1.0,
    **kwargs
) -> AIMessage:
    """Send a prompt to vLLM with optional guided output and LoRA support."""

    # Convert structured_output to guided_json if provided
    if structured_output is not None and guided_json is None:
        guided_json = pydantic_to_guided_json(structured_output)

    # Build extra_body with vLLM-specific parameters
    extra_body = {}

    if guided_json is not None:
        extra_body["guided_json"] = guided_json
    elif guided_regex is not None:
        extra_body["guided_regex"] = guided_regex
    elif guided_choice is not None:
        extra_body["guided_choice"] = guided_choice

    if lora_adapter is not None:
        extra_body["lora_request"] = {"lora_name": lora_adapter}

    # Extended sampling params
    if top_k != -1:
        extra_body["top_k"] = top_k
    if min_p > 0.0:
        extra_body["min_p"] = min_p
    if repetition_penalty != 1.0:
        extra_body["repetition_penalty"] = repetition_penalty
    if length_penalty != 1.0:
        extra_body["length_penalty"] = length_penalty

    # Pass extra_body to parent ask()
    return await super().ask(
        prompt=prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=extra_body if extra_body else None,
        **kwargs
    )
```

### Diagnostic Methods

```python
async def health_check(self) -> bool:
    """Check vLLM server health via /health endpoint."""
    import aiohttp
    try:
        # Remove /v1 suffix for health endpoint
        base = self.base_url.rstrip("/v1").rstrip("/")
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base}/health", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
    except Exception:
        return False

async def server_info(self) -> Dict[str, Any]:
    """Get vLLM server version and config via /version endpoint."""
    import aiohttp
    base = self.base_url.rstrip("/v1").rstrip("/")
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base}/version", timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.json()
            raise ConnectionError(f"Failed to get server info: {resp.status}")

async def list_models(self) -> List[str]:
    """List available models via /v1/models endpoint."""
    response = await self.client.models.list()
    return [model.id for model in response.data]
```

### Batch Processing

```python
async def batch_process(
    self,
    requests: List[Dict[str, Any]],
    **kwargs
) -> List[AIMessage]:
    """Process multiple requests in a batch for optimal throughput.

    Args:
        requests: List of request dicts with 'prompt', 'model', and optional params

    Returns:
        List of AIMessage responses
    """
    import asyncio
    tasks = [
        self.ask(
            prompt=req.get("prompt", ""),
            model=req.get("model"),
            **{k: v for k, v in req.items() if k not in ("prompt", "model")},
            **kwargs
        )
        for req in requests
    ]
    return await asyncio.gather(*tasks)
```

### Error Handling

- `ConnectionError` with base_url when server unreachable
- `ValueError` with available models when model not found
- `TimeoutError` when request exceeds timeout

---

## Acceptance Criteria

- [ ] `vLLMClient` extends `LocalLLMClient`
- [ ] Constructor resolves `VLLM_BASE_URL` and `VLLM_API_KEY` env vars
- [ ] `ask()` supports `guided_json`, `guided_regex`, `guided_choice` parameters
- [ ] `ask()` supports `structured_output` parameter (Pydantic model → guided_json)
- [ ] `ask()` supports `lora_adapter` parameter
- [ ] `ask()` supports `top_k`, `min_p`, `repetition_penalty`, `length_penalty`
- [ ] `ask_stream()` works with vLLM-specific parameters
- [ ] `health_check()` queries `/health` endpoint
- [ ] `list_models()` queries `/v1/models` endpoint
- [ ] `server_info()` queries `/version` endpoint
- [ ] `batch_process()` processes multiple requests concurrently
- [ ] Proper error handling with informative messages
- [ ] Linting passes: `ruff check parrot/clients/vllm.py`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-125 is in `tasks/completed/`
3. **Read** `parrot/clients/localllm.py` to understand the base class
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
5. **Create** `parrot/clients/vllm.py` with full implementation
6. **Run linting** and fix any issues
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-126-vllm-client.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-04
**Notes**:
- Created `parrot/clients/vllm.py` with full vLLMClient implementation
- Extends `LocalLLMClient` with vLLM-specific features
- `ask()` supports guided_json, guided_regex, guided_choice, guided_grammar
- `ask()` supports structured_output parameter (Pydantic → guided_json conversion)
- `ask()` supports lora_adapter parameter for LoRA adapters
- `ask()` supports extended sampling: top_k, min_p, repetition_penalty, length_penalty
- `ask_stream()` supports all vLLM-specific parameters
- `health_check()` queries /health endpoint
- `list_models()` queries /v1/models endpoint
- `server_info()` queries /version endpoint and returns VLLMServerInfo
- `batch_process()` processes multiple requests concurrently via asyncio.gather
- Environment variables VLLM_BASE_URL and VLLM_API_KEY are supported
- Proper error handling with ConnectionError, ValueError
- Linting passes
