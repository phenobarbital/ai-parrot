---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Per-Round Token Usage Observability

**Date**: 2026-08-01
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

In AI-Parrot's multi-round tool-use loops (the `ask()` method on each LLM
client), intermediate token usage data is **silently discarded**. Every client
(`ClaudeClient`, `OpenAIClient`, `GoogleGenAIClient`, `GroqClient`,
`GrokClient`) runs a `while` loop that calls the provider SDK multiple times
when the LLM invokes tools, but:

1. The `response` variable is **overwritten** each round — only the final
   round's usage survives.
2. `AIMessage.usage` is built from this final response via
   `AIMessageFactory.from_<provider>()`, so it captures a single
   `CompletionUsage` snapshot.
3. `AfterClientCallEvent` fires **once** per `ask()` invocation, carrying only
   the final round's `input_tokens` / `output_tokens`.
4. The OpenTelemetry + OpenLIT observability pipeline therefore records a
   fraction of the actual token consumption.

**Who is affected**: Any deployment doing cost accounting or capacity planning.
A 5-round tool loop may consume 5x the reported tokens. The Gemma4Client is
the sole exception — it already accumulates totals across rounds (lines
528–546 of `gemma4.py`), proving the pattern works.

**Why now**: As agents adopt more complex tool chains (multi-tool, multi-round),
the gap between reported and actual usage grows. Per-agent cost attribution
(FEAT-228) is already live, but attributes under-counted tokens.

## Constraints & Requirements

- Must work across the 5 priority clients: Claude, OpenAI, Gemini, Groq, Grok.
  Others (Bedrock, HuggingFace, Gemma4) are follow-up.
- Must not break the existing `AIMessage.usage` contract — existing consumers
  see totals without code changes.
- Token usage only (input + output + total) — no pricing computation.
- A new `ClientRoundEvent` must fire after each tool-execution round.
- Streaming rounds where the provider does not report usage: fire
  `ClientRoundEvent` with `usage=None`.
- Must integrate with the existing `EventEmitterMixin` / lifecycle events
  system (FEAT-176) and the navigator-eventbus already imported by clients.
- Performance: event emission inside the tool loop must not add measurable
  latency (emit_nowait pattern).

---

## Options Explored

### Option A: Accumulate-in-Loop + Per-Round Event

Each client's tool loop accumulates a running `CompletionUsage` total and
emits a `ClientRoundEvent` after each round's tool execution. At loop exit,
the accumulated total replaces the single-round usage on the `AIMessage`.
A `total_usage()` convenience method on `AIMessage` returns the sum
(equivalent to `self.usage` under this option, for forward compatibility
with Option B if per-round history is later added).

**Flow per round:**
1. SDK call returns response with usage.
2. Build per-round `CompletionUsage` via `from_<provider>()`.
3. Add to running accumulator (`CompletionUsage.__add__`).
4. Execute tool calls.
5. Emit `ClientRoundEvent(round=N, usage=per_round, tool_calls=[...])`.
6. Continue loop or break.
7. Post-loop: `AIMessage.usage = accumulated_total`.

`AfterClientCallEvent` fires once at the end (unchanged) but now carries
the accumulated total, not just the last round.

**Pros:**
- Minimal model changes — `AIMessage.usage` stays a single `CompletionUsage`,
  no new list field, no schema migration.
- Backwards compatible — every existing consumer of `AIMessage.usage` gets
  correct totals without changes.
- Per-round detail available via `ClientRoundEvent` subscriptions — listeners
  that care can subscribe; those that don't pay nothing.
- Follows the Gemma4Client precedent (proven pattern).
- `CompletionUsage.__add__` is a small, testable primitive.

**Cons:**
- Per-round history is not persisted on the `AIMessage` itself — only
  available via event subscription (transient).
- If a listener misses a `ClientRoundEvent`, the per-round detail is lost.

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none) | All stdlib / existing framework | No new dependencies |

**Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/models/basic.py` — `CompletionUsage` (add `__add__`)
- `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` — add `ClientRoundEvent`
- `packages/ai-parrot/src/parrot/clients/base.py` — `_emit_before_call` / `_emit_after_call` pattern
- `packages/ai-parrot/src/parrot/clients/gemma4.py:528-546` — accumulation pattern

---

### Option B: Usage History List on AIMessage

Add a `usage_history: List[CompletionUsage]` field to `AIMessage`. Each
round appends its `CompletionUsage` to the list. `AIMessage.usage` becomes
a computed property returning the sum (via `CompletionUsage.__add__` over
the history list). A `total_usage()` method is syntactic sugar for the
same computation.

**Pros:**
- Full per-round detail persisted on the message object — survives
  serialization, logging, and storage.
- No event subscription needed to access per-round data.
- Richer observability: callers can see exactly which round consumed
  the most tokens.

**Cons:**
- Breaking change to `AIMessage` schema — `usage` becomes a computed
  property instead of a stored field. Existing code that sets
  `usage=CompletionUsage(...)` at construction breaks.
- Requires migration of every `AIMessageFactory.from_<provider>()` method
  and every test that constructs `AIMessage` directly.
- `usage_history` grows with round count — minor memory overhead but
  adds complexity to serialization/deserialization.
- Higher blast radius across the codebase.

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none) | All stdlib / existing framework | No new dependencies |

**Existing Code to Reuse:**
- Same as Option A, plus migration of `AIMessageFactory` and all test fixtures.

---

### Option C: Middleware / Wrapper Pattern

Instead of modifying each client's tool loop, introduce a decorator or
wrapper around `ask()` that intercepts each SDK call, captures usage,
and accumulates. Each client registers its SDK call method as the
"interceptable" point. The wrapper handles accumulation, event emission,
and total computation generically.

**Pros:**
- Single implementation point — no per-client loop modifications.
- Clean separation: usage tracking is a cross-cutting concern handled
  outside the business logic.
- Easy to add new clients — just register the intercept point.

**Cons:**
- The tool loops are structurally different across clients (while True,
  while tool_calls, while iteration < max, etc.) — a generic wrapper
  would need to understand each loop's response shape.
- Requires refactoring each client's internal SDK call into a separate
  interceptable method (significant refactor).
- Harder to debug — indirection between the loop and the usage capture.
- Over-engineered for 5 clients with similar but not identical patterns.

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none) | All stdlib / existing framework | No new dependencies |

**Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/clients/base.py` — `EventEmitterMixin` infrastructure

---

### Option D: Hybrid — Accumulate + Optional History

Combine Options A and B: accumulate in the loop, emit `ClientRoundEvent`
per round, AND store `usage_history` on `AIMessage`. But make
`usage_history` an **optional metadata** field (stored in
`AIMessage.metadata["usage_history"]`) rather than a top-level field.
`AIMessage.usage` remains a stored `CompletionUsage` set to the
accumulated total. A `total_usage()` method returns `self.usage`.

**Pros:**
- Zero breaking changes — `usage` stays a stored field with the correct total.
- Per-round history available both transiently (events) and persistently
  (metadata dict).
- No schema migration needed.

**Cons:**
- Per-round data in `metadata` is untyped — callers must know to look for
  `metadata["usage_history"]` and deserialize `List[CompletionUsage]`.
- Two sources of truth for per-round data (events vs metadata).
- Slightly more complex client loop code (accumulate + append to list +
  emit event).

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none) | All stdlib / existing framework | No new dependencies |

**Existing Code to Reuse:**
- Same as Option A

---

## Recommendation

**Option A** is recommended because:

1. **Minimal blast radius**: `AIMessage.usage` stays a stored
   `CompletionUsage` field. No schema migration, no breaking changes to
   constructors, factories, or tests.
2. **Correct totals immediately**: Every existing consumer — OTel metrics,
   OpenLIT, logging, cost dashboards — gets accurate multi-round totals
   without code changes.
3. **Per-round observability via events**: The `ClientRoundEvent` gives
   listeners real-time per-round visibility. This is the natural integration
   point for OpenTelemetry spans (one child span per round) and for the
   existing `MetricsSubscriber`.
4. **Proven pattern**: Gemma4Client already does accumulation. We're
   standardizing what already works.
5. **Forward compatible**: If we later want per-round history on the message
   (Option B or D), we can add it incrementally without changing the
   accumulation or event infrastructure built here.

The tradeoff — per-round data not persisted on `AIMessage` — is acceptable
because the primary consumers (OTel, metrics dashboards) operate on events,
not on the message object.

---

## Feature Description

### User-Facing Behavior

From a framework user's perspective:

- `AIMessage.usage` now reflects the **total** tokens consumed across all
  rounds of a multi-round tool loop, not just the final round.
- `AIMessage.total_usage()` returns the same `CompletionUsage` object
  (convenience method, forward-compatible).
- Users who subscribe to `ClientRoundEvent` receive per-round usage
  breakdowns in real time, including the round number, tool calls executed,
  and the per-round `CompletionUsage` (or `None` for streaming rounds
  where the provider did not report usage).
- `AfterClientCallEvent.input_tokens` / `.output_tokens` now carry the
  accumulated totals.
- OpenTelemetry metrics (`gen_ai.usage.input_tokens`,
  `gen_ai.usage.output_tokens`) and per-agent attribution (FEAT-228)
  report correct multi-round totals.

### Internal Behavior

1. **`CompletionUsage.__add__`**: New dunder method that sums two
   `CompletionUsage` instances field-by-field (prompt_tokens,
   completion_tokens, total_tokens, timing fields use max-or-sum,
   extra_usage merged).

2. **`ClientRoundEvent`**: New frozen dataclass in the lifecycle events
   module. Fields: `client_name`, `model`, `round_number` (1-indexed),
   `usage` (`Optional[CompletionUsage]`), `tool_calls` (list of tool
   call identifiers), `duration_ms`, `agent_name`. Emitted via
   `emit_nowait` (fire-and-forget, same pattern as `BeforeClientCallEvent`).

3. **`_emit_round_event()`**: New helper on `AbstractClient` (alongside
   `_emit_before_call` / `_emit_after_call`) that constructs and emits
   `ClientRoundEvent`.

4. **Per-client loop modification**: In each of the 5 priority clients'
   `ask()` methods, after tool execution and before continuing the loop:
   - Build per-round `CompletionUsage` from the current response.
   - Accumulate into a running total.
   - Call `_emit_round_event(round_number, per_round_usage, tool_calls)`.
   At loop exit, pass the accumulated total to `AIMessageFactory`.

5. **`AIMessage.total_usage()`**: Simple method returning `self.usage`
   (exists for forward compatibility — callers who use it today will
   benefit if `usage` semantics change later).

### Edge Cases & Error Handling

- **Provider returns no usage on a round** (e.g., some streaming
  responses): `ClientRoundEvent.usage = None`. The accumulator skips
  that round's contribution — the total will be an undercount, but
  this is strictly better than the current behavior (zero-count).
- **Single-round call (no tool use)**: No `ClientRoundEvent` is emitted
  (round count = 1, no loop iteration). `AIMessage.usage` and
  `AfterClientCallEvent` behave exactly as before.
- **Client error mid-loop**: `ClientCallFailedEvent` fires as today.
  `ClientRoundEvent`s for completed rounds are already emitted and
  the accumulated usage up to that point is available to subscribers.
  `AIMessage` is not constructed (the call raised).
- **Zero subscribers to `ClientRoundEvent`**: The `has_subscribers()`
  short-circuit (already used for `ClientStreamChunkEvent`) skips
  event construction entirely — zero overhead in the hot path.
- **Streaming `ask_stream()` rounds**: Fire `ClientRoundEvent` with
  `usage=None` when the provider does not report intermediate usage.
  Full streaming support is a follow-up evaluation.

---

## Capabilities

### New Capabilities
- `per-round-usage-tracking`: Accumulate token usage across all rounds of a
  multi-round tool loop and report accurate totals on `AIMessage.usage`.
- `client-round-event`: New lifecycle event emitted after each tool-execution
  round, carrying per-round usage, tool calls, and round metadata.
- `completion-usage-addition`: `CompletionUsage.__add__` operator for
  combining usage across rounds.

### Modified Capabilities
- `lifecycle-events-system` (FEAT-176): Extended with `ClientRoundEvent`.
- `per-agent-cost-usage-metrics` (FEAT-228): Benefits from correct totals
  without modification — the ContextVar-based `agent_name` propagation
  already rides on `AfterClientCallEvent`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `CompletionUsage` (`models/basic.py`) | extends | Add `__add__` dunder |
| `AIMessage` (`models/responses.py`) | extends | Add `total_usage()` method |
| `client.py` events module | extends | Add `ClientRoundEvent` dataclass |
| `AbstractClient` (`clients/base.py`) | extends | Add `_emit_round_event()` helper |
| `claude.py` (AnthropicClient) | modifies | Accumulate usage in tool loop |
| `gpt.py` (OpenAIClient) | modifies | Accumulate usage in tool loop |
| `google/client.py` (GoogleGenAIClient) | modifies | Accumulate usage in `_handle_multiturn_function_calls` |
| `groq.py` (GroqClient) | modifies | Accumulate usage in tool loop |
| `grok.py` (GrokClient) | modifies | Accumulate usage in tool loop |
| `MetricsSubscriber` | no change | Already reads `AfterClientCallEvent` tokens — now gets correct totals |
| `GenAIOpenTelemetrySubscriber` | optional | Could subscribe to `ClientRoundEvent` for per-round spans (follow-up) |

---

## Code Context

### User-Provided Code

_No code snippets provided during brainstorming._

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/models/basic.py:48
class CompletionUsage(BaseModel):
    prompt_tokens: int = Field(0, validation_alias=AliasChoices("prompt_tokens", "input_tokens"))  # line 70
    completion_tokens: int = Field(0, validation_alias=AliasChoices("completion_tokens", "output_tokens"))  # line 73
    total_tokens: int = 0  # line 76
    completion_time: Optional[float] = None  # line 79
    prompt_time: Optional[float] = None  # line 80
    queue_time: Optional[float] = None  # line 81
    total_time: Optional[float] = None  # line 82
    estimated_cost: Optional[float] = None  # line 85
    extra_usage: Dict[str, Any] = Field(default_factory=dict)  # line 88

    @computed_field
    @property
    def input_tokens(self) -> int: ...  # line 96
    @computed_field
    @property
    def output_tokens(self) -> int: ...  # line 102

    @classmethod
    def from_openai(cls, usage: Any) -> "CompletionUsage": ...  # line 109
    @classmethod
    def from_groq(cls, usage: Any) -> "CompletionUsage": ...  # line 118
    @classmethod
    def from_claude(cls, usage: Dict[str, Any]) -> "CompletionUsage": ...  # line 131
    @classmethod
    def from_gemini(cls, usage: Dict[str, Any]) -> "CompletionUsage": ...  # line 162
    @classmethod
    def from_grok(cls, usage: Any) -> "CompletionUsage": ...  # line 239

# From packages/ai-parrot/src/parrot/models/responses.py:72
class AIMessage(BaseModel):
    usage: CompletionUsage = Field(description="Token usage and timing information")  # line 118
    tool_calls: List[ToolCall] = Field(default_factory=list)  # line 129
    model: str  # line 111
    provider: str  # line 114
    metadata: Dict[str, Any] = Field(default_factory=dict)  # line 202

# From packages/ai-parrot/src/parrot/models/responses.py:397
class AIMessageFactory:
    @staticmethod
    def from_claude(response: Dict, ...) -> AIMessage: ...
    @staticmethod
    def from_openai(response: Any, ...) -> AIMessage: ...
    @staticmethod
    def from_gemini(response: Any, ...) -> AIMessage: ...
    @staticmethod
    def from_groq(response: Any, ...) -> AIMessage: ...

# From packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py
@dataclass(frozen=True)
class BeforeClientCallEvent(LifecycleEvent):  # line 18
    client_name: str = ""
    model: str = ""
    agent_name: Optional[str] = None

@dataclass(frozen=True)
class AfterClientCallEvent(LifecycleEvent):  # line 42
    client_name: str = ""
    model: str = ""
    duration_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    agent_name: Optional[str] = None

# From packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):  # line ~242
    def _emit_before_call(self, *, client_name, model, ...) -> TraceContext: ...  # line ~423
    async def _emit_after_call(self, tc, *, client_name, model, duration_ms,
                               input_tokens=None, output_tokens=None, finish_reason=None): ...  # line ~480
    async def _emit_failed_call(self, tc, *, client_name, model, duration_ms, exc): ...  # line ~525
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.models.basic import CompletionUsage  # models/basic.py:48
from parrot.models.responses import AIMessage, AIMessageFactory  # models/responses.py:72, 397
from parrot.core.events.lifecycle.events.client import (
    BeforeClientCallEvent, AfterClientCallEvent,
    ClientCallFailedEvent, ClientStreamChunkEvent,
)  # core/events/lifecycle/events/client.py
from parrot.core.events.lifecycle.base import LifecycleEvent  # core/events/lifecycle/base.py:21
from parrot.core.events.lifecycle.mixin import EventEmitterMixin  # mixin.py
```

#### Key Attributes & Constants
- `CompletionUsage.prompt_tokens` → `int` (models/basic.py:70)
- `CompletionUsage.completion_tokens` → `int` (models/basic.py:73)
- `CompletionUsage.total_tokens` → `int` (models/basic.py:76)
- `AIMessage.usage` → `CompletionUsage` (models/responses.py:118)
- `AIMessage.metadata` → `Dict[str, Any]` (models/responses.py:202)

#### Tool Loop Locations (per client)
- `claude.py`: `while True:` loop at lines ~534–623; usage built at line ~668
- `gpt.py`: `while getattr(result, "tool_calls", None):` loop at lines ~891–1004; usage at line ~1040
- `google/client.py`: `_handle_multiturn_function_calls()` at lines ~1766–2080; usage at line ~3559
- `groq.py`: `while result.tool_calls and conversation_turns < max_turns:` at lines ~408–499; usage at line ~593
- `grok.py`: `while current_turn < max_turns:` at lines ~277–317; usage at line ~343

### Does NOT Exist (Anti-Hallucination)
- ~~`CompletionUsage.__add__`~~ — does not exist; must be created
- ~~`AIMessage.total_usage()`~~ — does not exist; must be created
- ~~`AIMessage.usage_history`~~ — does not exist
- ~~`ClientRoundEvent`~~ — does not exist in the events module
- ~~`AbstractClient._emit_round_event()`~~ — does not exist
- ~~Any per-round event or iteration tracking in the lifecycle events system~~ — confirmed via grep

---

## Parallelism Assessment

- **Internal parallelism**: Limited. The `CompletionUsage.__add__` and
  `ClientRoundEvent` event definition are independent primitives, but the
  5 client modifications all depend on them and touch the same base class.
  However, the 5 client modifications themselves are independent of each
  other (each client file is self-contained).
- **Cross-feature independence**: No conflict with in-flight specs. FEAT-228
  (per-agent cost) is already merged. FEAT-176 (lifecycle events) is merged.
  No shared files being actively modified.
- **Recommended isolation**: `per-spec` — all tasks sequential in one worktree.
- **Rationale**: The dependency chain (primitives → base helper → per-client
  modifications → tests) is short and linear. The 5 client modifications
  could theoretically be parallel, but they all share `base.py` for the
  `_emit_round_event` helper and the test patterns are similar enough that
  sequential execution avoids merge conflicts and duplication.

---

## Open Questions

- [ ] Should `ClientRoundEvent` include the raw provider response metadata
  (e.g., cache token counts from Claude's `usage.cache_creation_input_tokens`)
  or just the normalized `CompletionUsage`? — *Owner: Jesus Lara*
- [ ] Should the `MetricsSubscriber` subscribe to `ClientRoundEvent` to emit
  per-round OTel metrics, or is the accumulated total on `AfterClientCallEvent`
  sufficient for v1? — *Owner: Jesus Lara*
- [x] Should `CompletionUsage.__add__` handle timing fields (completion_time,
  prompt_time, etc.)? — *Owner: Jesus Lara*: Yes, sum them; they represent
  cumulative time spent.
- [ ] Should we add a `rounds_count: int` field to `AIMessage` or
  `CompletionUsage` to expose the number of rounds without subscribing
  to events? — *Owner: Jesus Lara*
