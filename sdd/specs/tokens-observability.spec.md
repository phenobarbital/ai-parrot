---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Per-Round Token Usage Observability

**Feature ID**: FEAT-397
**Date**: 2026-08-01
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.x
**Brainstorm**: `sdd/proposals/tokens-observability.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

In AI-Parrot's multi-round tool-use loops (the `ask()` method on each LLM
client), intermediate token usage data is **silently discarded**. Every
priority client (`AnthropicClient`, `OpenAIClient`, `GoogleGenAIClient`,
`GroqClient`, `GrokClient`) runs a `while` loop that calls the provider SDK
multiple times when the LLM invokes tools, but:

1. The `response` variable is **overwritten** each round — only the final
   round's usage survives (Gemini is worse: it reports the *first*
   response's usage, ignoring the whole loop).
2. `AIMessage.usage` is built from a single response via
   `AIMessageFactory.from_<provider>()`, capturing one `CompletionUsage`
   snapshot.
3. `AfterClientCallEvent` fires **once** per `ask()` invocation, carrying
   only that single round's `input_tokens` / `output_tokens`.
4. The OpenTelemetry + OpenLIT observability pipeline therefore records a
   fraction of actual token consumption — a 5-round tool loop may consume
   5× the reported tokens. Per-agent cost attribution (FEAT-228) is live
   but attributes under-counted tokens.

`Gemma4Client` is the sole exception — it already accumulates totals across
rounds (`gemma4.py:528-546`), proving the pattern works.

### Goals

- Accumulate per-round `CompletionUsage` inside the tool loop of the 5
  priority clients and set the **accumulated total** on `AIMessage.usage`.
- Emit a new `ClientRoundEvent` after each round's tool execution, carrying
  round number, normalized token counts, raw provider usage payload, and
  the tools called.
- `AfterClientCallEvent` carries accumulated totals (no schema change).
- `AIMessage.total_usage()` convenience method returning the summed usage.
- Round count exposed as `usage.extra_usage["rounds"]` (no schema change).
- Per-round OTel metrics in v1: `MetricsSubscriber` subscribes to
  `ClientRoundEvent` and records per-round token usage on a **dedicated**
  per-round instrument (never the existing total histogram — that would
  double-count).
- Token usage only (input + output + total + provider extras) — no pricing
  computation.

### Non-Goals (explicitly out of scope)

- Pricing/cost computation — OpenTelemetry + OpenLIT own cost accounting;
  this feature reports tokens only.
- `usage_history` list on `AIMessage` (brainstorm Option B rejected — high
  blast radius; see `sdd/proposals/tokens-observability.brainstorm.md`).
- Per-round instrumentation of `ask_stream()` — streaming rounds where
  providers do not report intermediate usage are a follow-up evaluation.
  Where a round's usage is unavailable, the event fires with token fields
  `None` (decided in brainstorm).
- Non-priority clients (`BedrockClient`, `TransformersClient`,
  `Gemma4Client`, `ClaudeAgentClient`, `GeminiLiveClient`) — follow-up.
  (Gemma4 already accumulates totals; it only lacks the event emission.)
- Per-round child spans in `GenAIOpenTelemetrySubscriber` — optional
  follow-up; v1 covers metrics only.

---

## 2. Architectural Design

### Overview

**Chosen approach (brainstorm Option A): Accumulate-in-Loop + Per-Round Event.**

Each client's tool loop:
1. SDK call returns a response with usage.
2. Build per-round `CompletionUsage` via the existing
   `CompletionUsage.from_<provider>()` factory.
3. Add it to a running accumulator using the new `CompletionUsage.__add__`.
4. Execute the requested tool calls.
5. Emit `ClientRoundEvent(round_number=N, input_tokens=…, output_tokens=…,
   raw_usage=<provider payload>, tool_calls=(…,))` via the new
   `AbstractClient._emit_round_event()` helper (fire-and-forget
   `emit_nowait`, same pattern as `BeforeClientCallEvent`).
6. Loop continues or breaks.
7. Post-loop: the accumulated total (with
   `extra_usage["rounds"] = <round count>`) becomes `AIMessage.usage`, and
   `_emit_after_call()` receives the accumulated token totals.

**Serialization constraint (verified)**: `LifecycleEvent.to_dict()` in
`navigator_eventbus` runs a strict `json.dumps` validation over every field.
A nested Pydantic `CompletionUsage` instance would raise `TypeError`.
`ClientRoundEvent` therefore carries **flat token ints** (consistent with
`AfterClientCallEvent`) plus a JSON-safe `raw_usage: Optional[dict]` for the
provider-native payload (per resolved question: raw metadata IS included).
Tool calls ride as a `tuple` of tool-name strings (`to_dict()` converts
tuples to lists — same precedent as `PromptCacheAppliedEvent.segment_hashes`).

**Per-round metrics without double counting**: `MetricsSubscriber` gains a
`ClientRoundEvent` handler that records tokens on a NEW histogram
`parrot.client.round.token.usage` (attributes: `gen_ai.system`,
`gen_ai.request.model`, `parrot.agent.name`, `parrot.round.number`,
`gen_ai.token.type`) and increments a NEW counter `parrot.client.rounds`.
The existing `gen_ai.client.token.usage` histogram keeps recording only
from `AfterClientCallEvent` (now-correct totals) — per-round records never
land on it, so sums stay meaningful.

Single-round calls (no tool use) behave exactly as today: no
`ClientRoundEvent`, `AIMessage.usage` unchanged in shape, totals identical.

### Component Diagram

```
client.ask(prompt)
   │ _emit_before_call() ──────────────► BeforeClientCallEvent
   ▼
┌─ tool loop (per round r = 1..N) ─────────────────────────────┐
│  SDK call → response(usage_r)                                 │
│  per_round = CompletionUsage.from_<provider>(usage_r)         │
│  accumulated += per_round          (CompletionUsage.__add__)  │
│  execute tool calls                                           │
│  _emit_round_event(r, per_round, raw_usage, tools) ──► ClientRoundEvent
└───────────────────────────────────────────────────────────────┘
   │
   ├─ accumulated.extra_usage["rounds"] = N
   ├─ AIMessage.usage = accumulated     (total_usage() → usage)
   └─ _emit_after_call(input=Σ, output=Σ) ──► AfterClientCallEvent
                                                    │
                     ┌──────────────────────────────┤
                     ▼                              ▼
        MetricsSubscriber                MetricsSubscriber (existing)
        _on_client_round (NEW)           _on_client_after — unchanged,
        parrot.client.round.token.usage  now receives correct totals
        parrot.client.rounds
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `CompletionUsage` (`models/basic.py`) | extends | New `__add__` dunder; `extra_usage["rounds"]` convention |
| `AIMessage` (`models/responses.py`) | extends | New `total_usage()` method |
| `events/client.py` | extends | New `ClientRoundEvent` frozen dataclass + `__init__` export |
| `AbstractClient` (`clients/base.py`) | extends | New `_emit_round_event()` helper next to `_emit_before_call`/`_emit_after_call` |
| `claude.py` `ask()` tool loop | modifies | Accumulate + emit per round |
| `gpt.py` `ask()` tool loop | modifies | Accumulate + emit per round |
| `google/client.py` `_handle_multiturn_function_calls()` | modifies | Accumulate + emit per round; `ask()` must use loop total, not first response |
| `groq.py` `ask()` tool loop | modifies | Accumulate + emit per round |
| `grok.py` `ask()` tool loop | modifies | Accumulate + emit per round |
| `MetricsSubscriber` (`observability/subscribers/metrics.py`) | extends | Subscribe `ClientRoundEvent`; new per-round instruments |
| `GenAIOpenTelemetrySubscriber` | no change (v1) | Per-round spans are a follow-up |
| FEAT-228 agent attribution | no change | `agent_name` ContextVar read at event construction, same as the other client events |

### Data Models

```python
# core/events/lifecycle/events/client.py — NEW event
@dataclass(frozen=True)
class ClientRoundEvent(LifecycleEvent):
    """Emitted after each tool-execution round inside a client's ask() loop.

    NOT emitted for single-round calls (no tool use). Token fields are None
    when the provider did not report usage for the round (some streaming
    paths). raw_usage is the provider-native usage payload, JSON-safe.
    """
    client_name: str = ""
    model: str = ""
    round_number: int = 0                 # 1-indexed
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    tool_calls: tuple = ()                # tool-name strings; to_dict() → list
    duration_ms: float = 0.0              # this round's SDK call duration
    raw_usage: Optional[dict] = None      # provider-native payload (JSON-safe)
    agent_name: Optional[str] = None      # FEAT-228 ContextVar, same as siblings
```

```python
# models/basic.py — CompletionUsage addition semantics
def __add__(self, other: "CompletionUsage") -> "CompletionUsage":
    """Field-wise sum for multi-round accumulation.

    - prompt/completion/total tokens: int sum.
    - timing fields (completion_time, prompt_time, queue_time, total_time):
      sum when either side is set (resolved in brainstorm: they represent
      cumulative time spent); None + None → None.
    - estimated_cost: sum when either side is set; None + None → None.
    - extra_usage: shallow merge (right side wins on key conflict).
    """
```

### New Public Interfaces

```python
# models/responses.py — AIMessage
def total_usage(self) -> CompletionUsage:
    """Total token usage across all rounds of the generating call.

    Today this returns ``self.usage`` (which clients set to the
    accumulated multi-round total). Exists as a stable entry point in
    case per-round history is added later.
    """
    return self.usage

# clients/base.py — AbstractClient
def _emit_round_event(
    self,
    tc: TraceContext,
    *,
    client_name: str,
    model: str,
    round_number: int,
    usage: Optional[CompletionUsage],
    raw_usage: Optional[dict],
    tool_calls: Sequence[str],
    duration_ms: float,
) -> None:
    """Fire-and-forget ClientRoundEvent (emit_nowait + forward_to_global).

    Short-circuits via self.events.has_subscribers(ClientRoundEvent)
    when nobody listens — zero hot-path overhead.
    """
```

---

## 3. Module Breakdown

### Module 1: completion-usage-addition
- **Path**: `packages/ai-parrot/src/parrot/models/basic.py`
- **Responsibility**: `CompletionUsage.__add__` per the semantics above;
  document the `extra_usage["rounds"]` convention in the class docstring.
- **Depends on**: nothing.

### Module 2: client-round-event
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py`
  + `events/__init__.py` export.
- **Responsibility**: `ClientRoundEvent` frozen dataclass (JSON-safe fields
  only) + `__all__` export.
- **Depends on**: nothing.

### Module 3: emit-round-helper
- **Path**: `packages/ai-parrot/src/parrot/clients/base.py`
- **Responsibility**: `AbstractClient._emit_round_event()` with
  `has_subscribers()` short-circuit, `emit_nowait`, `forward_to_global`,
  and FEAT-228 `agent_name` population.
- **Depends on**: Module 2.

### Module 4: aimessage-total-usage
- **Path**: `packages/ai-parrot/src/parrot/models/responses.py`
- **Responsibility**: `AIMessage.total_usage()` method.
- **Depends on**: nothing.

### Module 5: claude-loop-accumulation
- **Path**: `packages/ai-parrot/src/parrot/clients/claude.py`
- **Responsibility**: Accumulate per-round usage in the `while True:` loop
  (~lines 534–623); emit round events; pass accumulated total (with
  `rounds` count) into the final `AIMessage` and `_emit_after_call`.
- **Depends on**: Modules 1–3.

### Module 6: openai-loop-accumulation
- **Path**: `packages/ai-parrot/src/parrot/clients/gpt.py`
- **Responsibility**: Same treatment for the `while tool_calls:` loop
  (~lines 891–1004). Note gpt.py has two call paths
  (`_responses_completion` / `_chat_completion`) — both accumulate.
- **Depends on**: Modules 1–3.

### Module 7: gemini-loop-accumulation
- **Path**: `packages/ai-parrot/src/parrot/clients/google/client.py`
- **Responsibility**: Accumulate inside `_handle_multiturn_function_calls()`
  (~lines 1766–2080) and fix `ask()` (~line 3559) to use the **loop
  total** instead of the initial response's usage. This client currently
  under-reports worst of all five.
- **Depends on**: Modules 1–3.

### Module 8: groq-loop-accumulation
- **Path**: `packages/ai-parrot/src/parrot/clients/groq.py`
- **Responsibility**: Same treatment for the `while result.tool_calls…`
  loop (~lines 408–499).
- **Depends on**: Modules 1–3.

### Module 9: grok-loop-accumulation
- **Path**: `packages/ai-parrot/src/parrot/clients/grok.py`
- **Responsibility**: Same treatment for the `while current_turn…` loop
  (~lines 277–317).
- **Depends on**: Modules 1–3.

### Module 10: per-round-metrics
- **Path**: `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py`
- **Responsibility**: Subscribe `ClientRoundEvent`; new instruments
  `parrot.client.round.token.usage` (histogram, reuse the existing
  token-space bucket boundaries) and `parrot.client.rounds` (counter);
  attributes `gen_ai.system`, `gen_ai.provider.name`,
  `gen_ai.request.model`, `parrot.agent.name`, `parrot.round.number`,
  `gen_ai.token.type`. Never touch `gen_ai.client.token.usage` from this
  handler (double-count guard).
- **Depends on**: Module 2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_completion_usage_add_tokens` | 1 | Token fields sum correctly |
| `test_completion_usage_add_timing` | 1 | Timing fields sum; None+None stays None; None+x → x |
| `test_completion_usage_add_extra_merge` | 1 | `extra_usage` shallow merge, right wins |
| `test_client_round_event_to_dict` | 2 | Frozen, JSON-serializable via `to_dict()`, tuple→list |
| `test_emit_round_event_short_circuit` | 3 | Zero subscribers → zero emissions/allocations |
| `test_emit_round_event_agent_name` | 3 | FEAT-228 ContextVar propagated onto the event |
| `test_total_usage_returns_usage` | 4 | `AIMessage.total_usage() is AIMessage.usage` |
| `test_<client>_multiround_accumulates` | 5–9 | Mocked 3-round tool loop → `AIMessage.usage` = sum of the 3 rounds; `extra_usage["rounds"] == 3` |
| `test_<client>_singleround_no_event` | 5–9 | No tool use → no `ClientRoundEvent`; usage identical to pre-feature behavior |
| `test_<client>_after_call_totals` | 5–9 | `AfterClientCallEvent.input_tokens/output_tokens` equal accumulated sums |
| `test_round_event_usage_none` | 5–9 | Round without provider usage → event fires with token fields None; accumulator skips it |
| `test_metrics_round_histogram` | 10 | `ClientRoundEvent` → `parrot.client.round.token.usage` records with `parrot.round.number`; `gen_ai.client.token.usage` NOT recorded from this handler |
| `test_metrics_rounds_counter` | 10 | `parrot.client.rounds` increments per event |

### Integration Tests

| Test | Description |
|---|---|
| `test_multiround_end_to_end` | Mocked provider returning tool_use twice then stop: assert N `ClientRoundEvent`s, accumulated `AIMessage.usage`, correct `AfterClientCallEvent` totals, and per-round metric records — all through the real event registry + in-memory metric reader |
| `test_per_agent_round_attribution` | Under `agent_identity("bot-a")`, round metrics carry `parrot.agent.name = "bot-a"` (FEAT-228 regression guard) |

### Test Data / Fixtures

```python
# Reuse the in-memory metric reader fixtures from
# packages/ai-parrot/tests/integration/observability/ (test_poc.py pattern)
# and the mock-SDK client fixtures from tests/unit/clients/test_client_lifecycle.py.
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `CompletionUsage.__add__` exists with documented semantics (tokens
      sum; timing fields sum; extra_usage merges).
- [ ] `ClientRoundEvent` exists, is exported from
      `parrot.core.events.lifecycle.events`, and passes the strict
      `to_dict()` JSON check.
- [ ] All 5 priority clients (`claude.py`, `gpt.py`, `google/client.py`,
      `groq.py`, `grok.py`) accumulate per-round usage: a mocked 3-round
      loop yields `AIMessage.usage` equal to the sum of the three rounds.
- [ ] `AIMessage.usage.extra_usage["rounds"]` carries the round count on
      multi-round calls.
- [ ] One `ClientRoundEvent` fires per tool round (after tool execution),
      with round number, flat token counts, `raw_usage` provider payload,
      and tool names; none fires on single-round calls.
- [ ] Rounds lacking provider usage fire the event with token fields `None`
      and do not corrupt the accumulated total.
- [ ] `AfterClientCallEvent` carries accumulated totals (existing schema,
      no new fields).
- [ ] `AIMessage.total_usage()` returns the accumulated `CompletionUsage`.
- [ ] `MetricsSubscriber` records `parrot.client.round.token.usage` and
      `parrot.client.rounds` from `ClientRoundEvent`, dimensioned by
      `parrot.round.number` and `parrot.agent.name`; the existing
      `gen_ai.client.token.usage` histogram receives ONLY the
      `AfterClientCallEvent` totals (no double counting).
- [ ] Zero-subscriber short-circuit: no event construction when nothing
      listens to `ClientRoundEvent`.
- [ ] No breaking changes: `AIMessage.usage` remains a stored
      `CompletionUsage`; existing consumers get correct totals unchanged.
- [ ] No pricing computation added anywhere.
- [ ] Existing suites pass: `pytest packages/ai-parrot/tests/unit/clients/ -v`
      and `pytest packages/ai-parrot/tests/integration/observability/ -v`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `dev` @ 2026-08-01 (post-merge e8af9c3f4). The FEAT-393
> merge touched only forms/formdesigner — clients, models, events, and
> observability files are unchanged from brainstorm verification.

### Verified Imports

```python
from parrot.models.basic import CompletionUsage            # models/basic.py:48
from parrot.models.responses import AIMessage, AIMessageFactory  # models/responses.py:72, 397
from parrot.core.events.lifecycle.events.client import (
    BeforeClientCallEvent, AfterClientCallEvent,
    ClientCallFailedEvent, ClientStreamChunkEvent,
)                                                          # events/client.py
from parrot.core.events.lifecycle.events import AfterClientCallEvent  # events/__init__.py:25 (add ClientRoundEvent to line ~23 block + __all__)
from navigator_eventbus.lifecycle.base import LifecycleEvent  # site-packages; events/client.py imports it
from parrot.observability.attributes import resolve_gen_ai_system  # subscribers/metrics.py:30
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/models/basic.py
class CompletionUsage(BaseModel):                          # line 48
    model_config = ConfigDict(populate_by_name=True)       # line 66
    prompt_tokens: int      # line 70, alias input_tokens
    completion_tokens: int  # line 73, alias output_tokens
    total_tokens: int = 0   # line 76
    completion_time: Optional[float]  # line 79
    prompt_time: Optional[float]      # line 80
    queue_time: Optional[float]       # line 81
    total_time: Optional[float]       # line 82
    estimated_cost: Optional[float]   # line 85
    extra_usage: Dict[str, Any]       # line 88
    # computed read-only aliases: input_tokens (line 96), output_tokens (line 102)
    # factories: from_openai:109, from_groq:118, from_claude:131,
    #            from_bedrock:141, from_gemini:162, from_claude_agent:179, from_grok:239

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                                # line 72
    usage: CompletionUsage        # line 118 — stored field, stays stored
    tool_calls: List[ToolCall]    # line 129
    metadata: Dict[str, Any]      # line 202
class AIMessageFactory:                                    # line 397

# packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py
@dataclass(frozen=True) class BeforeClientCallEvent(LifecycleEvent)   # line 18
@dataclass(frozen=True) class AfterClientCallEvent(LifecycleEvent)    # line 42
    # client_name, model, duration_ms, input_tokens: Optional[int],
    # output_tokens: Optional[int], finish_reason, agent_name
@dataclass(frozen=True) class PromptCacheAppliedEvent(LifecycleEvent) # line 124
    # segment_hashes: tuple = ()  ← precedent for tuple fields on frozen events

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):              # line ~242
    def _emit_before_call(...) -> TraceContext             # lines 423-478, emit_nowait
    async def _emit_after_call(self, tc, *, client_name, model, duration_ms,
        input_tokens=None, output_tokens=None, finish_reason=None)  # lines 480-523
    async def _emit_failed_call(...)                       # lines 525-562
    # after emit: self.events.forward_to_global(event)

# navigator_eventbus/lifecycle/base.py (installed package, verified)
class LifecycleEvent:
    def to_dict(self) -> dict[str, Any]:
        # converts TraceContext→dict, datetime→isoformat, tuple→list,
        # then STRICT json.dumps validation — raises TypeError on any
        # non-JSON value. A nested Pydantic model would FAIL here.

# packages/ai-parrot/src/parrot/observability/subscribers/metrics.py
class MetricsSubscriber:
    _client_cost_total   # line 103, counter gen_ai.client.cost.total
    _client_op_duration  # line 122, histogram gen_ai.client.operation.duration
    _client_token_usage  # line 127, histogram gen_ai.client.token.usage
    def register(self, registry) -> None                   # line 155
        # registry.subscribe(AfterClientCallEvent, self._on_client_after)  line 162
    async def _on_client_after(self, event) -> None        # line 190
        # base attrs incl. "parrot.agent.name": event.agent_name or "unknown"  line 200
        # token records: lines 211-218 with "gen_ai.token.type": input/output
    # token-space bucket boundaries constant near line 41
```

### Tool Loop Locations (per client — the modification sites)

| Client | Loop | Usage currently taken from |
|---|---|---|
| `clients/claude.py` `ask()` (line 412) | `while True:` lines ~534–623 | last `result` dict → `from_claude` at ~668; `_emit_after_call` ~689 |
| `clients/gpt.py` `ask()` (line 666) | `while tool_calls:` lines ~891–1004 | last `response` → `from_openai` at ~1040; `_emit_after_call` ~1057 |
| `clients/google/client.py` `ask()` (line 2782) | `_handle_multiturn_function_calls()` lines ~1766–2080 | **FIRST** response → `from_gemini` at ~3559 (bug); `_emit_after_call` ~3589 |
| `clients/groq.py` `ask()` (line 270) | `while result.tool_calls…:` lines ~408–499 | last `response` → `from_groq` at ~593; `_emit_after_call` ~608 |
| `clients/grok.py` `ask()` (line 188) | `while current_turn…:` lines ~277–317 | `final_response.usage` → `from_grok` at ~343; `_emit_after_call` ~370 |

Reference accumulation pattern: `clients/gemma4.py:528-546`.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `CompletionUsage.__add__` | client tool loops | `accumulated = accumulated + per_round` | models/basic.py:48 |
| `ClientRoundEvent` | `AbstractClient._emit_round_event()` | `emit_nowait` + `forward_to_global` | clients/base.py:423-478 (pattern) |
| `_emit_round_event()` | each client loop | call after tool execution | loop table above |
| `ClientRoundEvent` | `MetricsSubscriber.register()` | `registry.subscribe(ClientRoundEvent, self._on_client_round)` | metrics.py:155-162 |
| `agent_name` on event | FEAT-228 ContextVar | read at event construction | same pattern as `_emit_before_call` |

### Does NOT Exist (Anti-Hallucination)

- ~~`CompletionUsage.__add__`~~ — created by Module 1
- ~~`AIMessage.total_usage()`~~ — created by Module 4
- ~~`AIMessage.usage_history`~~ — does not exist and is NOT added (rejected option)
- ~~`ClientRoundEvent`~~ — created by Module 2; grep for "round"/"iteration" in the events package returns zero results today
- ~~`AbstractClient._emit_round_event()`~~ — created by Module 3
- ~~`parrot/core/events/lifecycle/base.py`~~ — moved to `navigator_eventbus.lifecycle.base` (TASK-1820); do not import the old path
- ~~`CompletionUsage.from_response()`~~ — no generic factory exists; use the per-provider `from_<provider>` classmethods
- ~~`MetricsSubscriber._on_client_round`~~ — created by Module 10
- ~~`parrot.client.round.token.usage` / `parrot.client.rounds` instruments~~ — created by Module 10

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Fire-and-forget emission (`emit_nowait` + `forward_to_global`) for
  `ClientRoundEvent`, mirroring `_emit_before_call` — never `await` inside
  the tool loop hot path.
- `has_subscribers(ClientRoundEvent)` short-circuit before constructing the
  event, mirroring the `ClientStreamChunkEvent` hot-path guard.
- Frozen dataclass events with JSON-safe fields only; tuples for sequences
  (`PromptCacheAppliedEvent.segment_hashes` precedent).
- `CompletionUsage.__add__` returns a NEW instance (Pydantic models here are
  not frozen, but treat accumulation immutably like `gemma4.py` does).
- FEAT-228: populate `agent_name` from the `current_agent_name` ContextVar
  at event construction time, exactly like the sibling client events.
- Async-first; Google-style docstrings; strict type hints.

### Known Risks / Gotchas

- **Double counting**: recording per-round tokens onto the existing
  `gen_ai.client.token.usage` histogram would double every token (rounds +
  total). Guard: per-round records go ONLY to
  `parrot.client.round.token.usage`; acceptance criterion enforces it.
- **`to_dict()` strict JSON validation**: any non-primitive field on
  `ClientRoundEvent` (Pydantic model, set, custom object) raises
  `TypeError` at emit time. `raw_usage` must be a plain dict — providers
  returning protobuf usage objects (Grok/xai_sdk) must be converted (the
  `from_grok` factory already shows the getattr-based extraction).
- **Gemini's first-response bug**: `google/client.py` builds usage from the
  initial response, not the loop. Module 7 must both accumulate AND rewire
  which usage reaches the `AIMessage` — the largest behavioral change of
  the five clients.
- **Rounds without usage**: accumulator skips `None`-usage rounds → totals
  may still under-count on some streaming paths. Strictly better than
  today; documented, and the event's `None` tokens make the gap observable.
- **Metric cardinality**: `parrot.round.number` multiplies series. Loops
  are bounded (max_turns 10–15), so cardinality is bounded; note it in the
  metrics docstring for operators.
- **Error mid-loop**: `ClientCallFailedEvent` semantics unchanged; rounds
  already emitted stay emitted — subscribers see partial usage even when
  the call ultimately fails (a feature, not a bug: those tokens were spent).
- **`extra_usage` merge on `__add__`**: right-side wins on conflicts;
  provider raw payloads stored per-round in `extra_usage` will overwrite
  each other in the total — acceptable, since per-round detail lives on the
  events, and `raw_usage` preserves it there.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (none) | — | stdlib + existing framework only |

---

## 8. Open Questions

- [x] Should `CompletionUsage.__add__` handle timing fields? — *Resolved in
      brainstorm*: Yes, sum them; they represent cumulative time spent.
- [x] Should `ClientRoundEvent` include raw provider usage metadata? —
      *Resolved (spec Q&A 2026-08-01)*: Yes — `raw_usage: Optional[dict]`
      field alongside the normalized flat token counts.
- [x] Per-round OTel metrics in v1? — *Resolved (spec Q&A 2026-08-01)*:
      Yes — `MetricsSubscriber` subscribes to `ClientRoundEvent` with a
      `parrot.round.number` dimension on dedicated per-round instruments.
- [x] Expose rounds count without event subscriptions? — *Resolved (spec
      Q&A 2026-08-01)*: `usage.extra_usage["rounds"]`, following the
      `from_claude_agent` `num_turns` precedent. No schema change.
- [ ] Exact naming of the per-round instruments (`parrot.client.round.token.usage`
      / `parrot.client.rounds`) — confirm against OTel SemConv conventions
      during Module 10; may prefer `gen_ai.`-prefixed names if a fitting
      SemConv exists. — *Owner: implementer*
- [x] Should `Gemma4Client` (already accumulating) get `ClientRoundEvent`
      emission in this feature or in the follow-up batch with Bedrock/HF?
      Default: follow-up. — *Owner: Jesus Lara*: follow-up

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in one
  worktree.
- **Rationale**: Short linear dependency chain (Modules 1–4 primitives →
  Modules 5–9 client loops → Module 10 metrics → integration tests). The
  five client modules are mutually independent but share the Module 3
  helper in `clients/base.py` and near-identical test patterns; sequential
  execution avoids conflicts and duplication.
- **Cross-feature dependencies**: none. FEAT-176 (lifecycle events),
  FEAT-228 (per-agent attribution), and the eventbus extraction (TASK-1820)
  are all merged.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-01 | Jesus Lara | Initial draft from tokens-observability brainstorm (Option A) + 3 spec-time resolutions |
