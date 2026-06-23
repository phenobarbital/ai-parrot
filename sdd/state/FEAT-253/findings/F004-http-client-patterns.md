---
id: F004
slug: http-client-patterns
query: "aiohttp vs httpx and REST client architecture"
type: grep
---

## Finding: Mixed aiohttp + httpx usage, CLAUDE.md mandates aiohttp

### HTTPService base class
**File:** `packages/ai-parrot/src/parrot/interfaces/http.py`
- Central HTTP client class with auth injection (Bearer, API key, Basic)
- `async_request()` creates `aiohttp.ClientSession` with auth/proxy/timeout
- Also has httpx path (both coexist)

### RESTTool base class
**File:** `packages/ai-parrot-tools/src/parrot_tools/resttool.py`
- Wraps `HTTPService` with `base_url`, `api_key`, URL building
- Good pattern for GigSmart to follow or extend

### Massive client (best error handling)
**File:** `packages/ai-parrot-tools/src/parrot_tools/massive/client.py`
- Typed exception hierarchy: `MassiveAPIError`, `MassiveRateLimitError`, `MassiveTransientError`
- Retry with exponential backoff, Retry-After header parsing
- Best existing example for GigSmart error handling

### No existing GraphQL client
- Searched entire codebase — zero GraphQL client implementations
- GigSmart would be the FIRST GraphQL client in ai-parrot

### Decision:
- Use `aiohttp` per CLAUDE.md policy (not httpx as SPEC suggests)
- Follow Massive client's typed exception pattern
- Build new GraphQL transport layer
