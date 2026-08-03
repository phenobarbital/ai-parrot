---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# FEAT-404 was allocated by scripts/sdd/reserve_ids.py during /sdd-proposal
# (see sdd/proposals/bedrock-per-round-token.proposal.md §7, tooling note).
# No new reservation is made for this spec — the ledger already records it
# (next_feature_id: 405).
reuse_feature_id: FEAT-404
---

# Feature Specification: Bedrock/Nova Per-Round Token Usage Observability

**Feature ID**: FEAT-404
**Date**: 2026-08-03
**Author**: Jesus Lara
**Status**: draft
**Target version**: current dev cycle
**Proposal**: `sdd/proposals/bedrock-per-round-token.proposal.md` (mode: enrichment)
**Research audit**: `sdd/state/FEAT-404/` (findings F001–F010)
**Continues**: FEAT-397 (`sdd/specs/tokens-observability.spec.md`)

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-397 shipped per-round token accounting for five clients (Anthropic,
OpenAI, Gemini, Groq, Grok) and explicitly deferred `BedrockClient` in its
non-goals (`sdd/specs/tokens-observability.spec.md:73`); `NovaClient` did not
yet exist when that spec was written. Today `BedrockConverseBase.ask()` runs a
multi-round tool loop with **no** round accounting: `AIMessage.usage` carries
only the *last* round's usage, no `ClientRoundEvent` is ever emitted, and
`extra_usage["rounds"]` is never stamped. `BedrockConverseBase.resume()` is
worse — it carries **no lifecycle instrumentation at all** (no
`BeforeClientCallEvent`/`AfterClientCallEvent` span, no round events).

This matters now because the dev-loop Nova backend (see
`sdd/proposals/novaclient-dev-loop.brainstorm.md`, [R5]) treats Bedrock
per-round usage as an **external dependency provided by this feature**: its
`UsageReport` degrades to "—" for Bedrock-backed seats until FEAT-404 lands.

The gap closes at a single site: `NovaClient` inherits `ask()`/`resume()`
verbatim from `BedrockConverseBase` (its 121-line body defines only
`__init__` and class attributes), so instrumenting the base class covers
`BedrockConverseClient` **and** `NovaClient` in one change.

### Goals

- Replicate FEAT-397's four-part instrumentation idiom (init accumulator /
  accumulate per round / emit `ClientRoundEvent` inside the tool-use branch /
  stamp accumulated total) in `BedrockConverseBase.ask()`.
- Instrument `BedrockConverseBase.resume()` as well — including establishing
  the call-level lifecycle span it currently lacks (**U2: completeness over
  parity**).
- Sum `cacheReadInputTokens`/`cacheWriteInputTokens` explicitly across rounds
  in the Bedrock loops, compensating for `CompletionUsage.__add__`'s
  documented right-hand-wins shallow merge of `extra_usage` (**U1**).
- Ship the per-client test convention: `test_bedrock_multiround_usage.py`
  plus a NovaClient inheritance assertion (`client_name="nova"`).
- Strict no-op for single-round (non-tool) calls and when no
  `ClientRoundEvent` subscriber is registered.

### Non-Goals (explicitly out of scope)

- **`clients/base.py`, `models/basic.py`, `metrics.py`, `ClientRoundEvent`
  schema** — no changes. `_emit_round_event` is provider-agnostic and
  inherited; `CompletionUsage.__add__`/`from_bedrock` stay as-is (U1 rejected
  changing `__add__` for cross-client blast radius); the sole consumer
  (`MetricsSubscriber`) has no provider branching.
- **`clients/nova/client.py`** — receives the fix by inheritance; no code
  change. `clients/nova/audio.py` (voice path) has no Converse tool loop.
- **`BedrockConverseBase.ask_stream()`** — per-round streaming remains a
  standing FEAT-397 non-goal for every client.
- **`BedrockConverseBase.invoke()`** — single-shot, no tool loop; nothing to
  accumulate per round.
- **`Gemma4Client`** (U3), **`ClaudeAgentClient`**, **`TransformersClient`**,
  **`GeminiLiveClient`** — follow-ups, each needing its own design decision.
- **`LLMCodeDispatcher`'s `ask()` bypass** — orthogonal blind spot, owned by
  the dev-loop feature (`novaclient-dev-loop` brainstorm, [R8]).
- **No dollar-cost estimation** — token counts and rounds only.

---

## 2. Architectural Design

### Overview

A verbatim replication of the four-part idiom from `AnthropicClient.ask()`
(`clients/claude.py`), applied to the two tool loops in
`clients/bedrock.py`. No new abstractions, no new events, no new modules —
this is instrumentation insertion at verified line ranges, reusing three
already-existing primitives:

1. `CompletionUsage.from_bedrock(usage)` (`models/basic.py:146-165`) parses
   each round's Converse `usage` dict (already used by `invoke()`).
2. `CompletionUsage.__add__` (`models/basic.py:273`) accumulates rounds —
   with an **explicit post-add fix-up of the two cache counters**, because
   `__add__` shallow-merges `extra_usage` right-hand-wins while
   `from_bedrock` stores `cacheReadInputTokens`/`cacheWriteInputTokens`
   there as first-class numbers. Naive accumulation would report
   last-round-only cache tokens, silently contradicting `ask()`'s own
   docstring (`bedrock.py:626-630`).
3. `AbstractClient._emit_round_event` (`clients/base.py:488-562`) emits the
   `ClientRoundEvent`; it short-circuits (client + global registry check)
   when nobody listens, so instrumentation is zero-cost with observability
   off.

**`ask()`** already holds a call-level span (`_lc_tc` at line 659, `_lc_t0`
at 667); the four parts drop into the existing loop (738-810) and
post-factory stamp site (836-845).

**`resume()`** has no span. Decision (§8, resolved in this spec): establish
the **full call-level lifecycle span** — `_emit_before_call` before the loop
and `await _emit_after_call` after it — rather than attaching round events to
an orphan `TraceContext.new_root()`. Rationale: U2 already chose completeness
over parity, and orphan round events with no parent call span would be
inconsistent with every other emission site in the codebase; the extra diff
is small and brings `resume()` to full telemetry parity with `ask()`.

Bedrock uses `self.client_name` for telemetry (`bedrock.py:660,855`) — keep
that convention (do NOT copy `AnthropicClient._telemetry_client_name`, a
Claude-specific backend-mapping property, `claude.py:187`). Round events
therefore carry `client_name="nova"` for `NovaClient` and
`"bedrock-converse"` for `BedrockConverseClient` automatically.

### Component Diagram

```
BedrockConverseBase.ask()  ──┐   per round   ┌──> _emit_round_event() ──> ClientRoundEvent
BedrockConverseBase.resume() ┘  (tool_use    └──> (short-circuits if no      │
        │                        branch)          subscribers)               v
        │ inherited verbatim                                        MetricsSubscriber
        ├── NovaClient            (client_name="nova")              ._on_client_round
        └── BedrockConverseClient (client_name="bedrock-converse")  (no change)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BedrockConverseBase.ask()` (`bedrock.py:578-862`) | modifies | four-part idiom into loop 738-810; stamp after 836-845 |
| `BedrockConverseBase.resume()` (`bedrock.py:1000-1128`) | modifies | new lifecycle span + four-part idiom into loop 1063-1119 |
| `AbstractClient._emit_before_call` (`base.py:431`) | uses | already inherited; `resume()` starts calling it |
| `AbstractClient._emit_round_event` (`base.py:488`) | uses | already inherited; no change |
| `AbstractClient._emit_after_call` (`base.py:564`) | uses | `resume()` starts calling it (async) |
| `CompletionUsage.from_bedrock` (`basic.py:146`) | uses | per-round parser; unchanged |
| `CompletionUsage.__add__` (`basic.py:273`) | uses | accumulator; unchanged — cache counters fixed up locally |
| `NovaClient` (`nova/client.py:30`) | inherits | receives fix for free; test-only surface |
| `BedrockConverseClient` (`bedrock.py:1217`) | inherits | receives fix for free |
| `MetricsSubscriber._on_client_round` (`metrics.py:253`) | consumes | provider-agnostic; no change |

### Data Models

No new models. The existing contract is reused verbatim:

```python
# Per-round (existing ClientRoundEvent, core/events/lifecycle/events/client.py:177):
#   client_name, model, round_number (1-indexed), input_tokens/output_tokens/
#   total_tokens (None when provider reported no usage), tool_calls, duration_ms,
#   raw_usage (provider-native dict)
# Per-call (existing AIMessage.usage: CompletionUsage):
#   accumulated across rounds; extra_usage["rounds"] = N only when N > 1;
#   extra_usage["cacheReadInputTokens"/"cacheWriteInputTokens"] = SUM across rounds
```

### New Public Interfaces

None. This feature is invisible at the public API level except that
`AIMessage.usage` for multi-round Bedrock/Nova calls now reports accumulated
totals (previously last-round-only) — the documented FEAT-397 semantics.

---

## 3. Module Breakdown

### Module 1: `ask()` instrumentation + cache-counter summing
- **Path**: `packages/ai-parrot/src/parrot/clients/bedrock.py`
- **Responsibility**: The core change; covers Nova by inheritance.
  - Init `_lc_round_number = 0` / `_lc_accumulated_usage = None` before the
    `while True` at line 738 (mirror `claude.py:533-535`).
  - Time each round: `_lc_round_t0 = time.perf_counter()` at the top of the
    loop body; increment round number and compute `duration_ms` after
    `_sdk_create` returns (mirror `claude.py:540,557-558`). **Fallback
    retry**: the in-loop `_should_use_fallback` branch (`bedrock.py:742-749`)
    issues a *second* `_sdk_create` in the same iteration — attribute the
    round's usage and timing to the successful call, exactly as `claude.py`
    does (its timer spans the try/except including the retry; one round
    event per loop iteration either way).
  - Per round: `raw = result.get("usage") or None`; when present, build
    `CompletionUsage.from_bedrock(raw)` and accumulate via `+`; **then
    explicitly sum `cacheReadInputTokens` and `cacheWriteInputTokens` into
    the accumulator's `extra_usage`** (U1 — `__add__` alone keeps only the
    last round's values). When absent, the accumulator is untouched and the
    round event fires with `usage=None` (mirror `claude.py:560-572`).
  - Collect `_lc_round_tool_names` inside the block loop (759-800) and call
    `self._emit_round_event(_lc_tc, client_name=self.client_name, ...)` at
    the end of the `stopReason == "tool_use"` branch (after tool execution,
    before appending messages — mirror `claude.py:640-650`). The final
    non-tool round emits **no** round event, matching all five reference
    clients.
  - After `AIMessageFactory.from_bedrock` (836-845): when the accumulator is
    non-None, replace `ai_message.usage` with it, stamping
    `extra_usage["rounds"] = _lc_round_number` **only when
    `_lc_round_number > 1`** (mirror `claude.py:715-722`). Single-round
    calls are a strict no-op. The existing `_emit_after_call` (853-861)
    then picks up accumulated totals automatically via `ai_message.usage`.
  - Update the `ask()` docstring cache note (626-630) to state the
    multi-round semantics: cache counters are now summed across rounds.
- **Depends on**: nothing new — all primitives exist.

### Module 2: `resume()` lifecycle span + instrumentation
- **Path**: `packages/ai-parrot/src/parrot/clients/bedrock.py`
- **Responsibility**: Strictly larger than Module 1 (F010) — `resume()`
  currently emits nothing.
  - Establish the call-level span: `_lc_tc = self._emit_before_call(
    client_name=self.client_name, model=resolved_model,
    temperature=self.temperature, system_prompt=None, has_tools=bool(
    tool_specs), parent_trace=None)` after model resolution, plus
    `_lc_t0 = time.perf_counter()`; end with `await self._emit_after_call(
    _lc_tc, ...)` carrying accumulated totals and the final stop reason
    before returning (mirror `ask()`'s 659-667 and 852-861).
  - Apply the same four-part idiom to the loop at 1063-1119, including the
    cache-counter fix-up, the tool-use-branch-only emission, and the
    accumulated-total + `rounds` stamp on the returned `AIMessage`
    (post-`AIMessageFactory.from_bedrock`, 1121-1128). Note `resume()` has
    no fallback branch — the loop body is simpler than `ask()`'s.
  - Document the deliberate asymmetry in the `resume()` docstring: Bedrock/
    Nova `resume()` reports rounds while the five reference clients'
    `resume()` does not (U2 — accepted; closing it elsewhere is a
    follow-up). This note exists so the asymmetry is not later "fixed" by
    removal.
- **Depends on**: Module 1 (idiom established there; same file, sequential).

### Module 3: Tests
- **Path**: `packages/ai-parrot/tests/unit/clients/test_bedrock_multiround_usage.py`
  (new), optionally `packages/ai-parrot/tests/integration/observability/test_multiround_usage.py`
  (extend).
- **Responsibility**:
  - Mirror `test_claude_multiround_usage.py`, but mock the
    **`_sdk_create`** seam (Bedrock's SDK call site — NOT
    `_backend.build_client`, which is a Claude-only concept): drive a
    2-tool-round + final-round `ask()`; assert accumulated
    `AIMessage.usage`, one `ClientRoundEvent` per tool round with correct
    `round_number`/`tool_calls`/token fields, `extra_usage["rounds"] == 3`,
    and **summed** cache counters across rounds.
  - Same assertions for `resume()`, plus: `BeforeClientCallEvent` and
    `AfterClientCallEvent` now fire around it.
  - Single-round no-op test: no tool use → no round event, no `rounds` key,
    usage identical to today's behavior.
  - No-usage round test: provider omits `usage` → round event fires with
    `usage=None` token fields, accumulator untouched.
  - NovaClient inheritance test: the same mocked loop through a `NovaClient`
    instance emits events with `client_name == "nova"`. This is the only
    Nova-specific surface.
  - Fallback-retry test: capacity error → fallback `_sdk_create` succeeds →
    round usage/timing attributed to the successful call, one round event.
- **Depends on**: Modules 1–2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_ask_multiround_accumulates_usage` | M1 | 3-round loop: `AIMessage.usage` is the sum, not last round |
| `test_ask_emits_round_event_per_tool_round` | M1 | exactly N-1 events for N rounds; 1-indexed; tool names captured |
| `test_ask_stamps_rounds_only_when_multiround` | M1 | `extra_usage["rounds"]` present iff rounds > 1 |
| `test_ask_sums_cache_tokens_across_rounds` | M1 | `cacheRead/cacheWriteInputTokens` are sums, not last-round (U1) |
| `test_ask_single_round_is_noop` | M1 | no tool use → no event, no `rounds` key, usage unchanged |
| `test_ask_round_without_usage_emits_none` | M1 | missing `usage` → event fires with None tokens; accumulator untouched |
| `test_ask_fallback_retry_attribution` | M1 | capacity error + fallback → usage/timing from successful call |
| `test_ask_no_subscribers_short_circuits` | M1 | no registry subscribers → no event construction, no error |
| `test_resume_has_lifecycle_span` | M2 | Before/AfterClientCallEvent fire around `resume()` |
| `test_resume_multiround_accumulates_and_emits` | M2 | same four assertions as ask() over the resume loop |
| `test_nova_inherits_instrumentation` | M3 | `NovaClient` path emits `client_name == "nova"` |

### Integration Tests

| Test | Description |
|---|---|
| (optional) extend `tests/integration/observability/test_multiround_usage.py` | end-to-end `MetricsSubscriber` receipt of Bedrock rounds, mocking `_sdk_create` |

### Test Data / Fixtures

```python
# Converse-shaped mock responses (dicts — _sdk_create returns parsed JSON):
def _tool_round(tool_use_id: str, usage: dict) -> dict:
    return {
        "stopReason": "tool_use",
        "output": {"message": {"content": [
            {"toolUse": {"toolUseId": tool_use_id, "name": "t", "input": {}}}
        ]}},
        "usage": usage,  # {"inputTokens": .., "outputTokens": ..,
                         #  "cacheReadInputTokens": .., "cacheWriteInputTokens": ..}
    }

def _final_round(usage: dict) -> dict:
    return {
        "stopReason": "end_turn",
        "output": {"message": {"content": [{"text": "done"}]}},
        "usage": usage,
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Multi-round `BedrockConverseBase.ask()` returns `AIMessage.usage`
      accumulated across all rounds; `extra_usage["rounds"]` stamped only
      when rounds > 1.
- [ ] `cacheReadInputTokens`/`cacheWriteInputTokens` in the final
      `extra_usage` are the **sum** across rounds (U1), and the `ask()`
      docstring (`bedrock.py:626-630`) states this.
- [ ] One `ClientRoundEvent` per tool round, emitted at the end of the
      `stopReason == "tool_use"` branch, none for the final round —
      placement-compatible with the five FEAT-397 reference clients.
- [ ] `resume()` gains a full call-level lifecycle span
      (`BeforeClientCallEvent`/`AfterClientCallEvent`) plus the same
      per-round instrumentation (U2), with the deliberate asymmetry vs.
      reference clients documented in its docstring.
- [ ] Single-round (non-tool) `ask()` behavior is byte-identical to today:
      no round event, no `rounds` key.
- [ ] A round whose response carries no `usage` emits a round event with
      `None` token fields and leaves the accumulator untouched.
- [ ] Fallback retry (`bedrock.py:742-749`) attributes round usage and
      timing to the successful call.
- [ ] `NovaClient` and `BedrockConverseClient` receive everything by
      inheritance — zero changes in `nova/client.py`; events carry
      `client_name="nova"` / `"bedrock-converse"` respectively.
- [ ] No changes to `clients/base.py`, `models/basic.py`,
      `observability/subscribers/metrics.py`, or any event schema.
- [ ] `test_bedrock_multiround_usage.py` passes; full suite green:
      `pytest packages/ai-parrot/tests/unit/clients/ -v`.
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `dev` on 2026-08-03 (post-`a62803899`). All paths are
> under `packages/ai-parrot/`.

### Verified Imports

```python
from parrot.clients.bedrock import BedrockConverseBase, BedrockConverseClient  # src/parrot/clients/bedrock.py:1217 (client)
from parrot.clients.nova import NovaClient                    # src/parrot/clients/nova/client.py:30
from parrot.clients.claude import AnthropicClient             # src/parrot/clients/claude.py (reference impl)
from parrot.models.basic import CompletionUsage               # src/parrot/models/basic.py
from parrot.core.events.lifecycle.events import (             # verified via test_claude_multiround_usage.py imports
    AfterClientCallEvent,
    ClientRoundEvent,                                         # class at core/events/lifecycle/events/client.py:177
)
```

### Existing Class Signatures

```python
# src/parrot/clients/bedrock.py  (imports: time line 36, uuid line 37)
class BedrockConverseBase:
    async def ask(self, prompt, model=None, ..., tools=None, use_tools=None, ...) -> AIMessage:  # line 578
        # docstring cache-counter note: lines 626-630 — UPDATE in Module 1
        # _lc_tc = self._emit_before_call(client_name=self.client_name, ...)   line 659-666
        # _lc_t0 = time.perf_counter()                                          line 667
        # while True:                                                           line 738
        #     result = await self._sdk_create(payload)                          line 740
        #     fallback branch: _should_use_fallback → 2nd _sdk_create           lines 742-749
        #     if result.get("stopReason") == "tool_use":                        line 756
        #         per-block tool exec loop                                      lines 759-800
        #         append assistant+user msgs, continue                          lines 805-807
        #     else: break                                                       lines 808-810
        # ai_message = AIMessageFactory.from_bedrock(response=result, ...)      lines 836-845
        # await self._emit_after_call(_lc_tc, client_name=self.client_name,...) lines 853-861

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage:  # line 1000
        # NO _emit_before_call / _lc_tc / _lc_t0 anywhere in this method
        # while True: result = await self._sdk_create(payload)                  lines 1063-1064
        #     tool_use branch                                                   lines 1068-1116
        #     else: break                                                       lines 1117-1119
        # return AIMessageFactory.from_bedrock(...)  — NO usage override        lines 1121-1128
        # NO fallback branch in this loop (unlike ask())

    async def ask_stream(self, ...): ...   # line 864 — OUT OF SCOPE
    async def invoke(self, ...): ...       # line 1130 — OUT OF SCOPE (single-shot)

class BedrockConverseClient(BedrockConverseBase):  # line 1217
    client_name: str = "bedrock-converse"          # line 1229

# src/parrot/clients/nova/client.py
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):  # line 30
    client_type: str = "nova"     # line 62
    client_name: str = "nova"     # line 63
    # body is __init__ + class attributes ONLY; ask()/resume() inherited verbatim

# src/parrot/clients/base.py
class AbstractClient:
    def _emit_before_call(self, *, client_name, model, temperature=None,
        system_prompt=None, has_tools=False, parent_trace=None) -> TraceContext:  # line 431
    def _emit_round_event(self, tc, *, client_name, model, round_number,
        usage, raw_usage, tool_calls, duration_ms) -> None:  # line 488
        # short-circuits: self.events AND get_global_registry() subscriber check, lines 531-537
    async def _emit_after_call(self, tc, *, client_name, model, ...) -> None:  # line 564 (async!)

# src/parrot/models/basic.py
class CompletionUsage:
    @classmethod
    def from_bedrock(cls, usage: Dict[str, Any]) -> "CompletionUsage":  # line 146
        # extra_usage = {"cacheReadInputTokens": .., "cacheWriteInputTokens": ..}  lines 161-164
    def __add__(self, other) -> "CompletionUsage":  # line 273
        # "extra_usage: shallow merge; the right-hand operand wins" — lines 291-292

# src/parrot/clients/claude.py — the reference four-part idiom (COPY THIS SHAPE)
#   init accumulator:      lines 533-535
#   round timer:           line 540; round_number++/duration: lines 557-558
#   accumulate-or-None:    lines 560-572
#   tool names per round:  lines 578, 634
#   emit in tool_use branch: lines 640-650
#   stamp accumulated total + rounds (only if > 1): lines 715-722

# src/parrot/observability/subscribers/metrics.py — consumer, NO CHANGE
#   registry.subscribe(ClientRoundEvent, self._on_client_round)   line 184
#   async def _on_client_round(self, event: ClientRoundEvent):    line 253
```

### Integration Points

| New Code | Connects To | Via | Verified At |
|---|---|---|---|
| `ask()` round emission | `AbstractClient._emit_round_event` | inherited method call | `base.py:488` |
| `ask()` round parsing | `CompletionUsage.from_bedrock` | classmethod call | `basic.py:146` (already called from `invoke()`, `bedrock.py:1208` region) |
| `resume()` span | `_emit_before_call` / `_emit_after_call` | inherited method calls | `base.py:431,564` |
| tests | `_sdk_create` | mock seam | `bedrock.py:740,1064` |

### Does NOT Exist (Anti-Hallucination)

- ~~`BedrockConverseBase._telemetry_client_name`~~ — Claude-only property
  (`claude.py:187`); Bedrock uses `self.client_name` (`bedrock.py:660,855`).
  Do NOT introduce it.
- ~~Any lifecycle instrumentation in `resume()`/`invoke()`/`ask_stream()`~~ —
  `_emit_before_call`/`_lc_tc`/`_lc_t0` appear ONLY inside `ask()`
  (`bedrock.py:659,667,854,857`). Module 2 creates it for `resume()`.
- ~~A fallback-retry branch in `resume()`'s loop~~ — only `ask()` has one
  (`bedrock.py:742-749`).
- ~~`_backend.build_client` on Bedrock~~ — Claude's SDK seam; Bedrock's mock
  seam is `_sdk_create`.
- ~~`CompletionUsage.__add__` deep-merging or summing `extra_usage`~~ — it
  shallow-merges right-hand-wins by documented contract (`basic.py:291-292`);
  the cache-counter sum must be done locally in the Bedrock loops.
- ~~`tests/unit/clients/test_bedrock_multiround_usage.py`~~ — does not exist
  yet; this feature creates it (existing convention: claude/gemini/grok/
  groq/openai variants).
- ~~Round accumulation consumed anywhere in `parrot/flows/dev_loop/`~~ — the
  dev-loop bypass of `ask()` is real but out of scope here (FEAT-404 is the
  client-layer half; the dispatcher half belongs to the nova dev-loop
  feature).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **The four-part idiom, verbatim** from `AnthropicClient.ask()` — the five
  reference clients are structurally identical; Bedrock must match so round
  counts are comparable in the same metrics. Emission point is *inside* the
  tool-use branch only (final round emits nothing).
- **Reuse `from_bedrock` + `__add__`** — no hand-summed token fields
  (`Gemma4Client`'s manual sum is the anti-pattern).
- **`_lc_`-prefixed locals** — keep the naming convention so the
  instrumentation is greppable across clients.
- **`_emit_after_call` is async** (`await`); `_emit_before_call` and
  `_emit_round_event` are sync fire-and-forget.
- Async throughout; Google-style docstrings; `self.logger`.

### Known Risks / Gotchas

- **Cache-token shallow merge (the trap)**: `__add__` keeps only the
  right-hand `extra_usage` values on key conflict. Without the explicit
  local sum, multi-round calls silently report last-round-only cache
  counters — this contradicts the docstring promise and is invisible unless
  tested. Mitigation: dedicated test + local fix-up (U1).
- **Fallback retry attribution**: the round timer must span the try/except
  (including the fallback `_sdk_create`) so `duration_ms` and usage belong
  to the successful call — one round event per loop iteration.
- **Deliberate asymmetry**: Bedrock/Nova `resume()` will report rounds that
  the five reference clients' `resume()` does not. Documented in the
  docstring so a future "consistency cleanup" doesn't remove it (U2).
- **Strict single-round no-op**: `extra_usage["rounds"]` only when > 1;
  replacing `ai_message.usage` with a single-round accumulator equals
  today's value by construction — the tests must pin both.
- **Merge risk is low** (no tool-loop refactor in 4 months; F009), but the
  companion nova dev-loop feature touches other files in the same package —
  keep this spec's diff confined to `bedrock.py` + tests.
- **Tooling note** (from the proposal): `wikitoolkit` default store is
  stale; use `--store .parrot/wiki`. `reserve_ids.py` refuses dirty trees —
  the untracked `docs/parrot/` wiki.db is excluded via `.git/info/exclude`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | none new; `aioboto3` (Bedrock) and event primitives already present |

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks sequential in one worktree.
- **Rationale**: Modules 1 and 2 edit the same two methods in the same file
  (`clients/bedrock.py`); Module 3's tests exercise both. Parallel worktrees
  would guarantee conflicts for zero wall-clock gain.
- **Cross-feature dependencies**: none block this spec. The nova dev-loop
  feature (brainstorm `novaclient-dev-loop`) *consumes* this feature ([R5]:
  degrades cleanly until FEAT-404 lands) — land FEAT-404 first when
  possible, but no ordering is enforced.
- **Standing hazard** (Q1 note, `novaclient-dev-loop` brainstorm):
  concurrent SDD id-reservation runs can reset `dev` to `origin` — push
  immediately after every commit while this feature is in flight.

---

## 8. Open Questions

> Resolution trail — all proposal-phase decisions carried forward.

- [x] **U1 — Sum cache tokens across rounds, or last-round-wins?** —
      *Resolved in proposal*: Sum them explicitly in the Bedrock loop after
      `__add__`. `CompletionUsage.__add__` and `models/basic.py` stay
      **untouched** — no cross-client blast radius.
- [x] **U2 — Stop at `ask()` for parity, or also instrument `resume()`?** —
      *Resolved in proposal*: `ask()` **+** `resume()`. Deliberately puts
      Bedrock/Nova ahead of the five reference clients; the asymmetry is
      accepted and documented, closing it elsewhere is a follow-up.
- [x] **U3 — Fold `Gemma4Client` in?** — *Resolved in proposal*: No.
      Strictly Bedrock + Nova; Gemma4/ClaudeAgent/Transformers/GeminiLive
      are filed as follow-ups.
- [x] **U4 — `resume()` span: full lifecycle events, or round events on a
      local `TraceContext.new_root()`?** — *Resolved in this spec*: **full
      lifecycle span** (`_emit_before_call` → rounds → `_emit_after_call`).
      Consistent with U2's completeness choice; avoids orphan round events
      with no parent call span; small extra diff. **User-confirmed
      2026-08-03** — no open questions remain.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-03 | Jesus Lara (via /sdd-spec) | Initial draft from FEAT-404 proposal |
| 0.2 | 2026-08-03 | Jesus Lara | U4 (resume span design) user-confirmed — all questions resolved |
