---
id: FEAT-311
title: "Moonshot Client (MoonshotClient)"
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  summary: "Create MoonshotClient for Kimi Moonshot LLM (OpenAI-compatible API)"
base_branch: dev
confidence: high
research_state: sdd/state/FEAT-311/
created_at: 2026-07-16
---

# FEAT-311: Moonshot Client (MoonshotClient)

## §0 Origin

Create a native LLM client for **Kimi Moonshot** (platform.kimi.ai), exposing
their full model lineup — including kimi-k3 (1M context, 2.8T params) and
kimi-k2.7-code (code-focused) — through AI-Parrot's unified AbstractClient
interface.

Moonshot's API is OpenAI-compatible (`POST /v1/chat/completions`), but K-series
models require parameter stripping, custom thinking-mode handling, and
Moonshot-specific features (prompt_cache_key, partial mode, dynamic tool
loading).

**Why a native client?** Kimi models are already accessible through Nvidia NIM
and Groq gateways, but those lack newer models (kimi-k3), Moonshot-specific
features (prompt_cache_key, partial mode, video understanding), and carry
gateway-added latency. A direct client unlocks the full API surface.

## §1 Synthesis Summary

**Overall Confidence: HIGH**

The implementation follows a well-established pattern: NvidiaClient (254 lines)
is the closest analog — it extends OpenAIClient, overrides `_chat_completion()`
for provider quirks, and adds thinking mode via `contextvars.ContextVar`.
MoonshotClient will follow the same architecture with these additions:

1. **Parameter stripping** — K-series models reject `temperature`, `top_p`, `n`,
   `presence_penalty`, `frequency_penalty`. Must strip before forwarding.
2. **Tri-mode thinking** — `reasoning_effort` (K3), `thinking` dict (K2.6),
   always-on (K2.7-code).
3. **`reasoning_content` preservation** — parse from responses, include in
   multi-turn message history.
4. **Moonshot-specific params** — `prompt_cache_key`, `safety_identifier`,
   `partial` mode.

## §2 Codebase Findings

### §2.1 Localization

| File | Symbol | Status | Evidence |
|------|--------|--------|----------|
| `parrot/clients/moonshot.py` | `MoonshotClient` | **NEW** | F001, F004 |
| `parrot/models/moonshot.py` | `MoonshotModel` | **NEW** | F001, F004 |
| `parrot/clients/factory.py` | `SUPPORTED_CLIENTS` | MODIFY (lines 64-91) | F003 |
| `tests/clients/test_moonshot_client.py` | — | **NEW** | F003 |

### §2.2 Pattern Analog: NvidiaClient

`NvidiaClient` (`parrot/clients/nvidia.py`, 254 lines) demonstrates the exact
pattern:

```python
class NvidiaClient(OpenAIClient):
    client_type = "nvidia"
    client_name = "nvidia"
    _default_model = NvidiaModel.KIMI_K2_INSTRUCT_0905.value

    def __init__(self, api_key=None, **kwargs):
        resolved_key = api_key or config.get("NVIDIA_API_KEY")
        super().__init__(api_key=resolved_key, base_url="...", **kwargs)
        self.api_key = resolved_key  # re-set after super().__init__

    async def _chat_completion(self, model, messages, use_tools=False, **kwargs):
        # Provider-specific logic (thinking mode via extra_body)
        # Always uses client.chat.completions.create (never parse())
        ...

    async def ask(self, prompt, *, enable_thinking=False, **kwargs):
        # Sets contextvars, delegates to super().ask()
        ...
```

### §2.3 Existing Kimi References

Kimi models already appear in two provider enums:
- **Nvidia**: `KIMI_K2_THINKING`, `KIMI_K2_INSTRUCT_0905`, `KIMI_K2_5`
- **Groq**: `KIMI_K2_INSTRUCT`

No direct "moonshot" or "kimi" entry exists in `SUPPORTED_CLIENTS`.

### §2.4 Factory Registration

Add to `factory.py`:
```python
from .moonshot import MoonshotClient
# In SUPPORTED_CLIENTS:
"moonshot": MoonshotClient,
"kimi": MoonshotClient,
```

## §3 Hypothesis / Scope

### Architecture Decision: Extend OpenAIClient

**MoonshotClient extends OpenAIClient** (not AbstractClient directly) because:
- Moonshot's API is fully OpenAI-compatible at the endpoint level
- Tool calling, structured output, streaming, vision all follow OpenAI format
- Only ~5 provider-specific behaviors need overrides

### Estimated Scope

| Component | Lines (est.) | Complexity |
|-----------|-------------|------------|
| `moonshot.py` (client) | ~300-400 | Medium |
| `models/moonshot.py` (enum) | ~40 | Low |
| `factory.py` (registration) | ~5 | Trivial |
| `test_moonshot_client.py` | ~150 | Low |
| **Total** | **~500-600** | **Medium** |

### Key Overrides

1. **`__init__`** — base_url `https://api.moonshot.ai/v1`, env var `MOONSHOT_API_KEY`
2. **`_chat_completion()`** — parameter stripping for K-series, thinking mode
   injection, `max_tokens` → `max_completion_tokens` translation
3. **`ask()` / `ask_stream()`** — thinking mode kwargs via contextvars (NvidiaClient pattern)
4. **`_sanitize_params_for_model()`** — new helper to strip fixed params per model

## §4 Confidence Map

| Claim | Confidence | Evidence |
|-------|-----------|----------|
| Extends OpenAIClient (not AbstractClient) | HIGH | F001 — NvidiaClient pattern proven |
| K-series parameter stripping required | HIGH | F004 — API docs explicit |
| Thinking via contextvars pattern | HIGH | F001 — NvidiaClient analog |
| Context caching is automatic (no override) | HIGH | F004 — transparent caching |
| Factory adds 'moonshot' + 'kimi' keys | HIGH | F003 — standard pattern |
| Model enum in parrot/models/ | HIGH | F001 — all providers use this |
| Streaming usage in choices[0].usage | MEDIUM | F004 — may need override |
| Vision needs URL-blocking guard | MEDIUM | F004 — only base64/file-ID |

## §5 Open Questions

No material unknowns remain. All API details are documented and the codebase
pattern is well-established.

## §6 Features Matrix

### Covered by OpenAIClient inheritance (no custom code):
- Basic chat completions
- Tool calling (definition, execution loop, results)
- Structured output / JSON mode
- Multi-turn conversation
- Streaming (SSE format)
- Vision with base64 images

### Requires MoonshotClient overrides:
| Feature | Implementation | Priority |
|---------|---------------|----------|
| Parameter stripping (K-series) | `_sanitize_params_for_model()` in `_chat_completion()` | P0 |
| Thinking mode (K3: reasoning_effort) | `extra_body` injection via contextvars | P0 |
| Thinking mode (K2.6: thinking dict) | `extra_body` injection via contextvars | P0 |
| `reasoning_content` parsing | Response message handling | P0 |
| `max_completion_tokens` translation | `_chat_completion()` kwarg mapping | P1 |
| `prompt_cache_key` support | Constructor param + `_chat_completion()` | P1 |
| Partial mode (assistant prefill) | Message-level `partial: true` | P2 |
| Dynamic tool loading (K3) | System message with `tools` field | P2 |
| Video understanding | `video_url` content type | P2 |
| `safety_identifier` | Constructor param | P3 |

### Model List

```python
class MoonshotModel(str, Enum):
    KIMI_K3 = "kimi-k3"
    KIMI_K2_7_CODE = "kimi-k2.7-code"
    KIMI_K2_7_CODE_HIGHSPEED = "kimi-k2.7-code-highspeed"
    KIMI_K2_6 = "kimi-k2.6"
    MOONSHOT_V1_128K = "moonshot-v1-128k"
    MOONSHOT_V1_8K_VISION = "moonshot-v1-8k-vision-preview"
    MOONSHOT_V1_128K_VISION = "moonshot-v1-128k-vision-preview"
```

### Pricing (per 1M tokens, USD)

| Model | Input (cache miss) | Input (cache hit) | Output |
|-------|-------------------|-------------------|--------|
| kimi-k3 | $3.00 | $0.30 | $15.00 |
| kimi-k2.7-code | $0.95 | $0.19 | $4.00 |
| kimi-k2.7-code-highspeed | $1.90 | $0.38 | $8.00 |
| kimi-k2.6 | $0.95 | $0.16 | $4.00 |

## §7 Research Audit

| Metric | Value |
|--------|-------|
| Files read | 12 |
| Grep queries | 4 |
| Web pages fetched | 7 |
| Findings produced | 4 (F001-F004) |
| Budget profile | default |
| Truncated | No |
| State directory | `sdd/state/FEAT-311/` |

## §8 Recommended Next Step

```
/sdd-spec FEAT-311
```

**Rationale**: High-confidence localization with a clear pattern analog
(NvidiaClient). All API details documented from official Moonshot docs.
The scope is bounded (~500-600 lines across 4 files) and the architecture
decision (extend OpenAIClient) is unambiguous. Ready for full spec decomposition.

**Alternatives**:
- `/sdd-brainstorm FEAT-311` — if you want to explore alternative architectures
  (e.g., whether to use the `openai` SDK or raw `aiohttp`)
- `/sdd-task FEAT-311` — if you want to skip the spec and go straight to tasks
  (viable given the clear scope)
