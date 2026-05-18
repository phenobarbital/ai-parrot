---
id: F002
query_id: Q003
type: read
intent: Learn AbstractClient's system-prompt API, completion/stream signatures, and options-pass-through.
executed_at: 2026-05-18T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F002 — AbstractClient API: complete()/ask()/ask_stream() with `system_prompt: Optional[str]`

## Summary

`AbstractClient` lives at `parrot/clients/base.py:242` (NOT
`abstract.py`). It exposes three public entry points used by bots:
`complete(messages, system_prompt: Optional[str] = None, ...)` (line 775),
`ask` (line 1432) and `ask_stream` (line 1470). The system prompt is
plumbed as a plain `Optional[str]` end-to-end. There is also a privacy-safe
`_system_prompt_hash()` helper (line 340) used for emitting telemetry events
without leaking the raw prompt — useful pattern to mirror for emitting a
"cache hit" event without leaking content. The default
`BASIC_SYSTEM_PROMPT` template (line 257) is the legacy fallback when no
system prompt is passed. Subclasses construct their per-provider payload
in `complete`/`ask`/`ask_stream` after the system prompt arrives as a
string.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 242-270
  symbol: `class AbstractClient(EventEmitterMixin, ABC)`
  excerpt: |
    class AbstractClient(EventEmitterMixin, ABC):
        """Abstract base Class for LLM models."""
        client_type: str = "generic"
        client_name: str = 'generic'
        _lightweight_model: Optional[str] = None
        BASIC_SYSTEM_PROMPT: str = """Your name is $name Agent.
        <system_instructions>
        ...
        </system_instructions>
        """

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 272-334
  symbol: `AbstractClient.__init__`
  excerpt: |
    def __init__(
        self,
        conversation_memory: Optional[ConversationMemory] = None,
        preset: Optional[str] = None,
        tools: Optional[List[Union[str, AbstractTool]]] = None,
        use_tools: bool = False,
        debug: bool = True,
        tool_manager: Optional[ToolManager] = None,
        **kwargs
    ):
        # temperature, top_k, top_p, max_tokens from preset or kwargs

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 340-353
  symbol: `_system_prompt_hash`
  excerpt: |
    def _system_prompt_hash(self, system_prompt: "Optional[str]") -> str:
        """Return SHA-256 hex of *system_prompt*, or empty string."""
        if not system_prompt:
            return ""
        return hashlib.sha256(system_prompt.encode()).hexdigest()

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 775-830
  symbol: `AbstractClient.complete`
  excerpt: |
    async def complete(
        self,
        ...
        system_prompt: Optional[str] = None,
        ...
    ):
        """system_prompt: Optional system prompt."""
        if system_prompt is not None:
            kwargs["system_prompt"] = system_prompt

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 1432, 1470
  symbol: `ask`, `ask_stream`
  excerpt: |
    async def ask(self, ...): ...
    async def ask_stream(self, ...): ...

## Notes

The `system_prompt: Optional[str]` signature is the natural integration
seam: subclasses receive a string today; they can keep receiving a string
by default and accept an optional richer object (e.g. a list of segments
with cache hints) when caching is enabled. Telemetry helper
`_system_prompt_hash` is a precedent for "feature off → identical
external behavior".
