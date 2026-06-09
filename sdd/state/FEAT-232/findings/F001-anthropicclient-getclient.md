# F001 — AnthropicClient construction & SDK integration point

**Query**: locate AnthropicClient, how it builds the SDK client and reads credentials.

## Summary
`AnthropicClient(AbstractClient)` is the single Anthropic client. The SDK
object is built lazily in `get_client()`, which is the **only** place the
`AsyncAnthropic` SDK class is instantiated. All ~1600 lines of completion /
stream / vision / tool-call logic operate on whatever object `get_client()`
returns (cached per event-loop by the base class).

## Citations
- `packages/ai-parrot/src/parrot/clients/claude.py:50` — `class AnthropicClient(AbstractClient)`
- `packages/ai-parrot/src/parrot/clients/claude.py:56` — `_default_model = 'claude-sonnet-4-5'`
- `packages/ai-parrot/src/parrot/clients/claude.py:62-76` — `__init__(api_key, base_url, **kwargs)`; `self.api_key = api_key or config.get('ANTHROPIC_API_KEY')` (navconfig)
- `packages/ai-parrot/src/parrot/clients/claude.py:78-90` — `async def get_client() -> AsyncAnthropic`: lazy `from anthropic import AsyncAnthropic`; returns `AsyncAnthropic(api_key=..., max_retries=2)`
- `packages/ai-parrot/src/parrot/clients/claude.py:227` — model resolved via `(model.value if isinstance(model, ClaudeModel) else model) or (self.model or self.default_model)`

## Relevance
Subclassing `AnthropicClient` and overriding only `__init__` + `get_client()`
(to return `AsyncAnthropicBedrock` / `AsyncAnthropicAWS`) would reuse the entire
completion pipeline — IF those SDK clients expose the same `.messages.create` /
`.messages.stream` surface (they do for Bedrock/Vertex). Model-ID translation is
the one place that needs a hook before the SDK call (line 227 and siblings).
