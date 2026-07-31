---
id: F004
query_type: web_fetch
intent: Moonshot/Kimi API documentation - OpenAI compatibility and custom features
urls_fetched:
  - https://platform.kimi.ai/docs/guide/migrating-from-openai-to-kimi
  - https://platform.kimi.ai/docs/guide/use-kimi-k2-thinking-model
  - https://platform.kimi.ai/docs/guide/utilize-the-streaming-output-feature-of-kimi-api
  - https://platform.kimi.ai/docs/guide/use-json-mode-feature-of-kimi-api
  - https://platform.kimi.ai/docs/guide/use-kimi-vision-model
  - https://platform.kimi.ai/docs/guide/use-context-caching-feature-of-kimi-api
  - https://platform.kimi.ai/docs/guide/use-kimi-api-to-complete-tool-calls
---

## Base Configuration
- **Base URL**: `https://api.moonshot.ai/v1`
- **Auth**: Bearer token (`Authorization: Bearer $MOONSHOT_API_KEY`)
- **Fully OpenAI SDK compatible** — change base_url + api_key

## Models
| Model | Context | Vision | Thinking | Notes |
|-------|---------|--------|----------|-------|
| kimi-k3 | 1M | Yes | Always on (reasoning_effort) | Flagship, 2.8T params |
| kimi-k2.7-code | 256K | Yes+video | Always on | Code-focused |
| kimi-k2.7-code-highspeed | 256K | Yes+video | Always on | ~180-260 tok/s |
| kimi-k2.6 | 256K | Yes+video | Default on, disable-able | General-purpose |
| moonshot-v1-128k | 128K | No | No | Legacy |
| moonshot-v1-8k-vision-preview | 8K | Yes | No | Legacy vision |
| moonshot-v1-128k-vision-preview | 128K | Yes | No | Legacy vision |

## CRITICAL: Parameter Constraints
K3/K2.7/K2.6 models have FIXED parameters. Must NOT send:
- temperature, top_p, n, presence_penalty, frequency_penalty
- API returns `invalid_request_error` if passed

moonshot-v1-* models accept these normally (temperature range [0,1] not [0,2]).

## Custom Handling Required
1. **Parameter stripping** for K-series models
2. **Thinking mode**: `reasoning_effort` (K3) vs `thinking` dict (K2.x) via extra_body
3. **`reasoning_content`** in responses — parse and preserve for multi-turn
4. **Streaming usage**: in `choices[0].usage` not top-level `usage`
5. **`max_completion_tokens`** preferred over `max_tokens`
6. **`partial` mode** — message-level `partial: true` for assistant prefill
7. **Dynamic tool loading** — K3 system messages with `tools` field
8. **`prompt_cache_key`** — session identifier for cache optimization
9. **No image URLs** — only base64 and file-ID references for vision
10. **`tool_choice: "required"`** only on kimi-k3

## Standard OpenAI-compatible (inherited from OpenAIClient)
- Chat completions endpoint and request/response format
- Tool calling (definition, response, tool results — max 128 tools)
- JSON mode and Structured Output (json_schema)
- Streaming SSE format
- Vision with base64 images
- Context caching is automatic (transparent, no manual management)
