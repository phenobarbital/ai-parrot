# Brainstorm: Lightweight Invoke Method for LLM Clients

**Date**: 2026-03-30
**Author**: Claude
**Status**: exploration
**Recommended Option**: D

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

### Option D: Hybrid — Abstract invoke() with Shared Helpers

`invoke()` is an **abstract method** on `AbstractClient` — each client implements the full method, including provider-specific structured output handling, content negotiation, and SDK calls. But `AbstractClient` provides **shared helper methods** that all clients call internally to avoid duplication:

- `_resolve_invoke_system_prompt(system_prompt: Optional[str]) -> str` — resolves `BASIC_SYSTEM_PROMPT` template with instance attributes (`$name`, `$capabilities`, `$role`, `$goal`, `$backstory`).
- `_build_invoke_structured_config(output_type, structured_output) -> Optional[StructuredOutputConfig]` — normalizes `output_type` shorthand into `StructuredOutputConfig`, respects `custom_parser` if declared.
- `_build_invoke_result(output, output_type, model, usage, raw_response) -> InvokeResult` — constructs the standardized return object.
- `_handle_invoke_error(exception) -> InvokeError` — catches any provider exception and wraps it in `InvokeError`.
- `_resolve_invoke_model(model: Optional[str]) -> str` — returns `model` if passed, else `self._lightweight_model`, else `self.model`.

Each client's `invoke()` implementation follows the pattern:
1. Call shared helpers for system prompt, structured config, model resolution.
2. Handle structured output **in the provider-native way** (OpenAI: native `json_schema` response_format; Claude: schema instruction in system prompt; Google: `generation_config` with schema; Groq: JSON mode with schema normalization; Grok: native `json_schema`).
3. Make the SDK call directly (no retry, no streaming, no history).
4. If `StructuredOutputConfig.custom_parser` is set, run it on the raw response; otherwise use provider-native parsing or fall back to `_parse_structured_output()`.
5. Call `_build_invoke_result()` to construct the return.
6. Wrap any exception via `_handle_invoke_error()`.

Pros:
- **Full provider flexibility**: each client controls structured output natively — OpenAI/Grok use native `json_schema`, Claude injects schema into prompt, Groq normalizes schema for its validator, Google uses `generation_config`.
- **No code duplication for common concerns**: system prompt resolution, result construction, error wrapping, model resolution all live in shared helpers.
- **Clean contract**: `invoke()` is abstract — contributors know every client must implement it.
- **custom_parser support**: the shared helper respects `StructuredOutputConfig.custom_parser` and each client can decide when to apply it (before or after provider-native parsing).
- **Mirrors how `ask()` works**: `ask()` is already abstract with shared helpers — same pattern, easy to understand.

Cons:
- Each client's `invoke()` is ~30-50 lines (vs ~20 for Option A's `_invoke_call()`). Acceptable tradeoff for the flexibility gained.
- Slightly more surface area to test per client (but each test is simpler — no mocking of base class flow).

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| No new dependencies | All existing provider SDKs | Reuses current SDK clients |

Existing Code to Reuse:
- `parrot/clients/base.py` — `_parse_structured_output()` as fallback parser, new shared helpers added here.
- `parrot/models/outputs.py` — `StructuredOutputConfig` including `custom_parser` field.
- `parrot/models/basic.py` — `CompletionUsage` and its `from_<provider>()` factory methods.
- `parrot/exceptions.py` — `ParrotError` as base for new `InvokeError`.

---

## Recommendation

**Option D** is recommended because:

- **Provider-specific structured output is fundamentally different across providers**: OpenAI and Grok support native `json_schema` in `response_format` (strict mode); Claude requires schema injection into the system prompt; Google uses `generation_config` with a schema parameter; Groq needs schema normalization (`_fix_schema_for_groq`) and cannot combine JSON mode with tools. Forcing these through a single concrete `invoke()` (Option A) would either mean lowest-common-denominator behavior or provider branching in the base class — both undesirable.
- **Common concerns are still shared**: Unlike Option B (full duplication), Option D provides shared helpers for everything that IS identical: system prompt resolution, `InvokeResult` construction, error wrapping, model resolution, `StructuredOutputConfig` normalization. No code is duplicated for these.
- **`custom_parser` flows naturally**: Each client controls when to apply `StructuredOutputConfig.custom_parser` — after provider-native parsing or as the primary parser — without the base class needing to know the provider's parsing order.
- **Consistent with existing patterns**: `ask()` is already abstract with shared helpers in `AbstractClient`. Option D follows the same convention — contributors already know this pattern.
- **Option A's tradeoff is too expensive**: Abstracting away structured output differences into a single `_invoke_call()` means the base class must handle all provider variations in its parsing step, or providers must return a uniform intermediate format — both add complexity. Option D avoids this entirely.
- **Option C (mixin) adds no value**: All 6 clients need `invoke()`, and the mixin would need access to client internals anyway.

**Tradeoff accepted**: Each client's `invoke()` is ~30-50 lines instead of ~20 for Option A's `_invoke_call()`. This is a small price for native structured output handling per provider.

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

Each client's `invoke()` follows this flow, using shared helpers from `AbstractClient`:

1. **System prompt resolution**: Call `self._resolve_invoke_system_prompt(system_prompt)`. If no `system_prompt` provided, renders `BASIC_SYSTEM_PROMPT` by substituting `$name` from `getattr(self, 'name', 'AI')` and `$capabilities` from `getattr(self, 'capabilities', '')`. Other variables (`$role`, `$goal`, `$backstory`) use instance attrs or empty strings.
2. **Structured output setup**: Call `self._build_invoke_structured_config(output_type, structured_output)`. If `output_type` is a class (Pydantic model/dataclass), wraps it in `StructuredOutputConfig(output_type=output_type, format=OutputFormat.JSON)`. If `structured_output` (a `StructuredOutputConfig`) is passed directly, uses that instead.
3. **Model resolution**: Call `self._resolve_invoke_model(model)`. Returns `model` if passed, else `self._lightweight_model`, else `self.model`.
4. **Tool preparation**: If `use_tools=True`, prepare tools via existing `_prepare_tools()`. Otherwise skip.
5. **Provider-specific structured output**: Each client applies structured output in its native way:
   - **OpenAI/Grok**: Pass `response_format={"type": "json_schema", "json_schema": {..., "strict": True}}` directly to the SDK.
   - **Claude**: Inject schema instruction into system prompt via `StructuredOutputConfig.format_schema_instruction()`.
   - **Google**: Set `generation_config` with `response_mime_type="application/json"` and `response_schema`.
   - **Groq**: Normalize schema via `_fix_schema_for_groq()`, use JSON mode.
   - **LocalLLM**: Follow OpenAI format (server-dependent).
5b. **Two-call strategy for tools + structured output (Google, Groq)**: When `use_tools=True` and `output_type` is set, providers that don't support both simultaneously perform two calls: (1) first call with tools enabled (no structured output) to get tool results and raw text, (2) second call with the complete raw result as input + structured output enabled (no tools) to parse into the target schema. This is an existing pattern already used in the codebase.
6. **SDK call**: Single async call to provider (or two-call when tools + structured output on Google/Groq) — no retry, no streaming, no conversation history.
7. **Response parsing**: If `StructuredOutputConfig.custom_parser` is set, apply it. Otherwise, use provider-native parsed response or fall back to `_parse_structured_output()`. For raw string mode (no `output_type`), return text directly.
8. **Result building**: Call `self._build_invoke_result(output, output_type, model, usage, raw_response)` to construct `InvokeResult` (includes `raw_response` for debugging).
9. **Error handling**: Wrap any exception via `self._handle_invoke_error(exception)` which raises `InvokeError`.

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
- `abstract-client`: Extended with abstract `invoke()` method, shared invoke helpers (`_resolve_invoke_system_prompt`, `_build_invoke_structured_config`, `_build_invoke_result`, `_handle_invoke_error`, `_resolve_invoke_model`), and `BASIC_SYSTEM_PROMPT` constant.
- `client-implementations`: Each of the 6 concrete clients gains `invoke()` implementation and `_lightweight_model` attribute.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/clients/base.py` | extends | Add abstract `invoke()`, shared invoke helpers, `BASIC_SYSTEM_PROMPT`, `InvokeResult` |
| `parrot/clients/claude.py` | extends | Add `invoke()`, `_lightweight_model = "claude-haiku-4-5-20251001"` |
| `parrot/clients/gpt.py` | extends | Add `invoke()`, `_lightweight_model = "gpt-4.1"` |
| `parrot/clients/groq.py` | extends | Add `invoke()`, `_lightweight_model = "kimi-k2-instruct"`, two-call for tools+structured |
| `parrot/clients/google/client.py` | extends | Add `invoke()`, `_lightweight_model = "gemini-3-flash-lite"`, two-call for tools+structured |
| `parrot/clients/localllm.py` | extends | Add `invoke()`, `_lightweight_model = None` (uses caller's model) |
| `parrot/clients/grok.py` | extends | Add `invoke()`, `_lightweight_model = "grok-4-1-fast-non-reasoning"` |
| `parrot/models/responses.py` | extends | Add `InvokeResult` dataclass |
| `parrot/exceptions.py` | extends | Add `InvokeError` exception class |

---

## Parallelism Assessment

- **Internal parallelism**: High. Each client's `invoke()` is independent. The base class changes (abstract `invoke()`, shared helpers, `InvokeResult`, `InvokeError`, `BASIC_SYSTEM_PROMPT`) must land first, then all 6 client implementations can be done in parallel or sequentially with no conflicts.
- **Cross-feature independence**: No conflicts with in-flight specs. Changes are additive (new methods/classes only).
- **Recommended isolation**: `per-spec` — all tasks sequential in one worktree. The base class change is a dependency for all client implementations, and the total effort is moderate enough to not warrant multiple worktrees.
- **Rationale**: The shared dependency on `AbstractClient` changes means client implementations must follow the base task. Sequential execution in one worktree is simpler and avoids merge coordination.

---

## Resolved Questions

- [x] **Structured output enforcement in BASIC_SYSTEM_PROMPT?** — No. `BASIC_SYSTEM_PROMPT` handles identity/security only. Structured output enforcement is handled by the combination of the user's prompt + `StructuredOutputConfig` (which generates schema instructions per provider). — *Resolved: Jesus*
- [x] **Should `InvokeResult` include `raw_response`?** — Yes. `InvokeResult` includes a `raw_response` field for debugging. — *Resolved: Jesus*
- [x] **Groq/Google: tools + structured output simultaneously?** — Not an issue. These providers already use a two-call strategy: first call with tools enabled (no structured output) to get tool results and raw text, second call with the complete result as input + structured output enabled (no tools). This existing pattern is reused in `invoke()`. — *Resolved: Jesus*

## Open Questions

- [ ] Should `InvokeResult` live in `parrot/models/responses.py` alongside `AIMessage`, or in `parrot/clients/base.py` close to the invoke helpers? — *Owner: Jesus*: yes, at responses.py.-
