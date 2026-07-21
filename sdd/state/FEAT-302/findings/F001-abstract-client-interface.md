---
id: F001
slug: abstract-client-interface
query: Read AbstractClient base class
type: read
---

## Finding: AbstractClient Interface

**Path**: `packages/ai-parrot/src/parrot/clients/base.py` (line 244+)

AbstractClient extends `EventEmitterMixin` and `ABC`. Required abstract methods:
- `get_client() -> Any` (line 846) — returns SDK client instance
- `ask(prompt, model, max_tokens, temperature, ...) -> MessageResponse` (line 1525)
- `ask_stream(prompt, ...) -> AsyncIterator[Union[str, AIMessage]]` (line 1563)
- `resume(session_id, user_input, state) -> MessageResponse` (line 1592)
- `invoke(prompt, ...) -> InvokeResult` (line 1614) — lightweight stateless

Key class attributes: `client_type: str`, `client_name: str`, `_default_model`, `_fallback_model`, `_lightweight_model`, `_min_cache_tokens`.

Context manager: `__aenter__` opens aiohttp session + calls `_ensure_client()`, `__aexit__` closes session.

Provided methods: `complete()`, `_prepare_tools()`, `_execute_tool()`, `_prepare_conversation_context()`, `_parse_structured_output()`.

Streaming convention: yield `str` chunks, then a final `AIMessage` sentinel with usage/metadata.
