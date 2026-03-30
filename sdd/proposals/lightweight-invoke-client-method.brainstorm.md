# Brainstorm: Lightweight Invoke Method for LLM Clients

**Date**: 2026-03-30
**Author**: Claude
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

The current `ask()` method on all LLM clients is a heavy-weight operation: it loads conversation history, runs the prompt builder pipeline, applies retry logic, wraps results in a full `AIMessage`, and updates conversation memory. This is appropriate for conversational flows but introduces unnecessary overhead for **stateless, structured extraction tasks** — e.g. "parse this text into a Pydantic model", "classify this input", "extract entities".

Developers building tool pipelines, data extraction agents, and internal utilities need a **fast, minimal call** that:
- Skips conversation history entirely.
- Skips prompt builder / `define_prompt()`.
- Skips retry logic.
- Returns the structured output directly (not wrapped in `AIMessage`).
- Uses a cheaper/faster model by default (`_lightweight_model`).

**Affected**: Framework developers using ai-parrot clients for structured extraction, classification, and lightweight LLM calls within tools and pipelines.

## Constraints & Requirements

- Must be defined on `AbstractClient` so all 6 concrete clients inherit or override it.
- Must not break any existing `ask()` / `ask_stream()` contracts.
- Stateless by default: no conversation memory reads or writes.
- Structured output by default via `StructuredOutputConfig` or `output_type` shorthand.
- Falls back to raw `str` when no `output_type` is provided.
- Returns a new lightweight `InvokeResult` (not `AIMessage`) with: result, output_type, model, usage.
- Accepts `max_tokens` (default 4096) and `temperature` (default 0).
- Accepts optional `system_prompt` (raw string); falls back to `BASIC_SYSTEM_PROMPT` template.
- Tool calling supported but off by default (`use_tools=False`).
- Each client defines a `_lightweight_model` class attribute for cheap/fast defaults.
- Errors are caught and raised as `InvokeError` (new exception extending `ParrotError`).
- No streaming — single async call only.
- No retry logic.

---

## Options Explored

### Option A: Single Abstract Method with Per-Client Provider Call

Add `invoke()` as a concrete method on `AbstractClient` that handles the common flow (system prompt resolution, structured output config, result parsing) and delegates the actual API call to a new thin abstract method `_invoke_call()` that each client implements.

The common `invoke()` method handles:
1. Resolve `BASIC_SYSTEM_PROMPT` template variables from instance attrs (`name`, `capabilities`).
2. Build `StructuredOutputConfig` from `output_type` if needed.
3. Call `_invoke_call()` (provider-specific, returns raw response).
4. Parse structured output via existing `_parse_structured_output()`.
5. Build and return `InvokeResult`.
6. Catch exceptions, wrap in `InvokeError`.

Each client implements only `_invoke_call(prompt, system_prompt, model, max_tokens, temperature, tools, structured_output_config)` — a thin wrapper around the provider SDK.

Pros:
- Maximum code reuse — parsing, error handling, template resolution live in one place.
- Each client only implements the minimal provider-specific call.
- Easy to test: mock `_invoke_call()` to test common flow.
- Consistent behavior across all providers.

Cons:
- Adds an abstract method that all clients must implement.
- Slightly less flexibility for provider-specific optimizations (e.g. native structured output).

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| No new dependencies | All existing provider SDKs | Reuses current SDK clients |

Existing Code to Reuse:
- `parrot/clients/base.py` — `_parse_structured_output()` for parsing structured responses.
- `parrot/models/outputs.py` — `StructuredOutputConfig` for output type configuration.
- `parrot/models/basic.py` — `CompletionUsage` for token tracking.
- `parrot/exceptions.py` — `ParrotError` as base for new `InvokeError`.

---

### Option B: Fully Independent invoke() Per Client

Each client implements its own `invoke()` from scratch — no shared base implementation. `AbstractClient` only defines the abstract signature.

Pros:
- Maximum per-provider flexibility (native structured output on OpenAI/Grok, schema injection on Claude, etc.).
- No coupling between provider implementations.

Cons:
- Significant code duplication across 6 clients (system prompt resolution, error wrapping, result building).
- Higher maintenance cost — changes to `InvokeResult` or `BASIC_SYSTEM_PROMPT` must be replicated 6 times.
- Harder to guarantee consistent behavior.
- Higher effort.

Effort: High

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| No new dependencies | All existing provider SDKs | Same as Option A |

Existing Code to Reuse:
- `parrot/models/outputs.py` — `StructuredOutputConfig`
- `parrot/models/basic.py` — `CompletionUsage`

---

### Option C: Mixin-Based Composition

Create an `InvokeMixin` class that provides the `invoke()` method and helper utilities. Clients that support invoke mix it in alongside `AbstractClient`.

Pros:
- Opt-in: clients that don't support lightweight invoke don't need to implement anything.
- Clean separation of concerns — invoke logic doesn't pollute `AbstractClient`.
- Could be reused outside the client hierarchy.

Cons:
- Adds MRO complexity (Python multiple inheritance).
- The mixin still needs access to client internals (SDK client, model name, etc.) — tight coupling disguised as loose coupling.
- All 6 clients need it anyway, so opt-in adds no practical value.
- More confusing for contributors: "where does invoke() come from?"

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| No new dependencies | All existing provider SDKs | Same as Option A |

Existing Code to Reuse:
- Same as Option A, but housed in a separate mixin file.

---

## Recommendation

**Option A** is recommended because:

- The feature needs to be on **all 6 clients** — there's no opt-in scenario, so the mixin (Option C) adds indirection for no benefit.
- The common flow (template resolution, structured output parsing, error wrapping, result building) is **identical across providers** — duplicating it 6 times (Option B) is wasteful and error-prone.
- Option A keeps provider-specific logic minimal: each client only implements `_invoke_call()` which is a ~20-line thin wrapper around the SDK call. Provider-specific structured output support (native JSON schema on OpenAI/Grok vs. schema-in-prompt on Claude) is handled naturally within each `_invoke_call()`.
- The existing `_parse_structured_output()` in `AbstractClient` already handles all the edge cases — Option A reuses it directly.

**Tradeoff accepted**: Adding one abstract method (`_invoke_call`) to implement per-client is minimal compared to the code reuse gained.

---

## Feature Description

### User-Facing Behavior

Developers call `invoke()` on any LLM client for fast, stateless structured extraction:

```python
# Structured output (returns Pydantic model instance inside InvokeResult)
result = await client.invoke(
    "Extract the person's name and age from: 'John is 30 years old'",
    output_type=PersonInfo,
)
print(result.output)  # PersonInfo(name="John", age=30)
print(result.model)   # "claude-haiku-4-5-20251001"
print(result.usage)   # CompletionUsage(prompt_tokens=42, completion_tokens=15, ...)

# Raw string (no output_type)
result = await client.invoke("Summarize this text: ...")
print(result.output)  # "The text discusses..."

# Override model and params
result = await client.invoke(
    "Classify sentiment",
    output_type=SentimentResult,
    model="gpt-4o",
    max_tokens=1024,
    temperature=0.1,
)

# With tools (opt-in)
result = await client.invoke(
    "Look up the weather and format it",
    output_type=WeatherReport,
    use_tools=True,
)

# Custom system prompt
result = await client.invoke(
    "Parse this invoice",
    output_type=Invoice,
    system_prompt="You are an invoice parser. Extract all fields precisely.",
)

# Using StructuredOutputConfig for custom parsing
from parrot.models.outputs import StructuredOutputConfig, OutputFormat
config = StructuredOutputConfig(output_type=Invoice, format=OutputFormat.JSON, custom_parser=my_parser)
result = await client.invoke("Parse this", structured_output=config)
```

### Internal Behavior

1. **Entry**: `invoke()` on `AbstractClient` is called.
2. **System prompt resolution**: If no `system_prompt` provided, render `BASIC_SYSTEM_PROMPT` by substituting `$name` from `getattr(self, 'name', 'AI')` and `$capabilities` from `getattr(self, 'capabilities', '')`. Other variables (`$role`, `$goal`, `$backstory`) use instance attrs or empty strings.
3. **Structured output setup**: If `output_type` is a class (Pydantic model/dataclass), wrap it in `StructuredOutputConfig(output_type=output_type, format=OutputFormat.JSON)`. If `structured_output` (a `StructuredOutputConfig`) is passed directly, use that instead.
4. **Model resolution**: Use `model` param if provided, else `self._lightweight_model`, else fall back to `self.model`.
5. **Tool preparation**: If `use_tools=True`, prepare tools via existing `_prepare_tools()`. Otherwise skip.
6. **Provider call**: Delegate to `_invoke_call()` — each client makes one SDK call with no retry, no streaming.
7. **Response parsing**: If structured output requested, run `_parse_structured_output()` on the raw response text. Otherwise use raw text.
8. **Result building**: Construct `InvokeResult(output=parsed_result, output_type=output_type, model=model_used, usage=CompletionUsage.from_<provider>(response))`.
9. **Error handling**: Any exception during steps 6-8 is caught and re-raised as `InvokeError(message, original_exception)`.

### Edge Cases & Error Handling

- **Structured output parse failure**: `_parse_structured_output()` already handles fallbacks (JSON extraction from markdown, nested unwrapping, etc.). If all parsing fails, `InvokeError` is raised with the raw response text for debugging.
- **Provider API error**: Caught and wrapped in `InvokeError`. No retry — caller decides whether to retry.
- **Missing `_lightweight_model`**: Falls back to `self.model` (the client's default model).
- **`output_type` and `structured_output` both provided**: `structured_output` takes precedence.
- **Tool execution failure**: If `use_tools=True` and a tool fails, the error propagates as `InvokeError`.
- **Instance attributes missing** (e.g. `name`, `capabilities` when client is used standalone without a bot): `BASIC_SYSTEM_PROMPT` uses safe defaults via `getattr()`.

---

## Capabilities

### New Capabilities
- `lightweight-invoke`: Stateless, no-retry `invoke()` method on all LLM clients returning structured output directly.
- `invoke-result-model`: New `InvokeResult` response model for lightweight invocations.
- `invoke-error`: New `InvokeError` exception for invoke-specific failures.
- `lightweight-model-defaults`: Per-client `_lightweight_model` class attributes for cheap/fast model defaults.

### Modified Capabilities
- `abstract-client`: Extended with `invoke()` concrete method, `_invoke_call()` abstract method, and `BASIC_SYSTEM_PROMPT` constant.
- `client-implementations`: Each of the 6 concrete clients gains `_invoke_call()` implementation and `_lightweight_model` attribute.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/clients/base.py` | extends | Add `invoke()`, `_invoke_call()`, `BASIC_SYSTEM_PROMPT` |
| `parrot/clients/claude.py` | extends | Add `_invoke_call()`, `_lightweight_model = "claude-haiku-4-5-20251001"` |
| `parrot/clients/gpt.py` | extends | Add `_invoke_call()`, `_lightweight_model = "gpt-4.1"` |
| `parrot/clients/groq.py` | extends | Add `_invoke_call()`, `_lightweight_model = "kimi-k2-instruct"` |
| `parrot/clients/google/client.py` | extends | Add `_invoke_call()`, `_lightweight_model = "gemini-3-flash-lite"` |
| `parrot/clients/localllm.py` | extends | Add `_invoke_call()`, `_lightweight_model = None` (uses caller's model) |
| `parrot/clients/grok.py` | extends | Add `_invoke_call()`, `_lightweight_model = "grok-4-1-fast-non-reasoning"` |
| `parrot/models/responses.py` | extends | Add `InvokeResult` dataclass |
| `parrot/exceptions.py` | extends | Add `InvokeError` exception class |

---

## Parallelism Assessment

- **Internal parallelism**: High. Each client's `_invoke_call()` is independent. The base class changes (`invoke()`, `InvokeResult`, `InvokeError`, `BASIC_SYSTEM_PROMPT`) must land first, then all 6 client implementations can be done in parallel or sequentially with no conflicts.
- **Cross-feature independence**: No conflicts with in-flight specs. Changes are additive (new methods/classes only).
- **Recommended isolation**: `per-spec` — all tasks sequential in one worktree. The base class change is a dependency for all client implementations, and the total effort is moderate enough to not warrant multiple worktrees.
- **Rationale**: The shared dependency on `AbstractClient` changes means client implementations must follow the base task. Sequential execution in one worktree is simpler and avoids merge coordination.

---

## Open Questions

- [ ] Should `BASIC_SYSTEM_PROMPT` include structured output enforcement instructions (e.g. "You MUST respond with valid JSON matching the provided schema") when `output_type` is set, or should that be handled separately by the structured output config? — *Owner: Jesus*
- [ ] Should `InvokeResult` include a `raw_response` field for debugging, or keep it minimal? — *Owner: Jesus*
- [ ] For Groq's limitation (JSON mode cannot combine with tool calling), should `invoke()` raise `InvokeError` immediately if both `use_tools=True` and `output_type` are set on GroqClient? — *Owner: Jesus*
