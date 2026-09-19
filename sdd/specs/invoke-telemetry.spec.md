---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Lifecycle Telemetry for `invoke()` (JevClient + OpenAIBaseClient)

**Feature ID**: FEAT-<NNN>
**Date**: 2026-09-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

`AbstractClient` exposes three lifecycle-telemetry hooks — `_emit_before_call`,
`_emit_after_call` and `_emit_failed_call_safe` (`clients/base.py:559-821`). They
emit `BeforeClientCallEvent` / `AfterClientCallEvent` / `ClientCallFailedEvent`
and forward them to the global registry, where `MetricsSubscriber`, OTel
subscribers and cost/token recorders consume them (input/output tokens,
duration, model, finish reason, error count).

Only `ask()` / `ask_stream()` call these hooks. **`invoke()` calls none of them,
in any client** (an AST audit on 2026-09-19 found 14 `invoke()`
implementations; none of them calls `_emit_before_call`). `invoke()` computes
usage and returns it in `InvokeResult.usage`, but that value stays with the
caller and never reaches the event bus. So every `invoke()` call is missing from
telemetry: no tokens, no cost, no latency, no error count, no trace span.

This spec fixes the gap for two clients:

- **`JevClient.invoke()`** (`ai-parrot-client-jev`, `client.py:677`): the Jev /
  System One client. Its `ask()` already has full telemetry
  (`client.py:553-576`), so this spec only brings `invoke()` up to the same level.
- **`OpenAIBaseClient.invoke()`** (`openai_base.py:1526`): the shared
  implementation that OpenAIClient, OpenRouter, Moonshot, Nvidia, Meta,
  BedrockMantle and GeminiOpenAICompat inherit, since none of them overrides
  `invoke()`.

### Goals
- `JevClient.invoke()` emits exactly one `BeforeClientCallEvent` and exactly one
  terminal event: either `AfterClientCallEvent` or `ClientCallFailedEvent`. The
  success event carries `duration_ms`, `input_tokens`, `output_tokens`, `model`
  and `finish_reason`.
- `OpenAIBaseClient.invoke()` does the same on all of its exit paths: the normal
  completion, the `BudgetExhausted` → finalize path, the double-`BudgetExhausted`
  partial-result path, and every error path.
- The emitted fields follow the conventions of each client's own `ask()`, so
  dashboards need no special case for `invoke()`.
- Event emission never changes what `invoke()` returns or raises.

### Non-Goals (explicitly out of scope)
- Telemetry for the `invoke()` implementations of any other client. The same
  audit found these also emit nothing: AnthropicClient, ClaudeAgentClient,
  GoogleGenAIClient, GeminiLiveClient, BedrockConverseBase, GrokClient,
  Gemma4Client, TransformersClient, OpenAICodexClient. **GroqClient,
  LocalLLMClient and ZaiClient subclass `OpenAIBaseClient` but override
  `invoke()`**, so they do NOT get this fix. See §8 Q1.
- Per-round `ClientRoundEvent` for `invoke()`. It is a single-shot call with no
  tool rounds.
- A shared "instrumented invoke" wrapper or decorator on `AbstractClient`.
  `clients/base.py` is foundation code and cannot change without discussion
  first (`.agent/CONTEXT.md`). This spec only calls the hooks that already exist.
- Changes to `ask()`, `ask_stream()`, `InvokeResult`, or the event models.

---

## 2. Architectural Design

### Overview

Each `invoke()` gets the same three-hook structure that its own `ask()` already
uses:

```
validate / resolve inputs  (errors here: no events, same as ask())
        │
tc = _emit_before_call(...) ; t0 = time.perf_counter()
        │
provider dispatch ──raises──▶ await _emit_failed_call_safe(tc, …, t0, exc) ; re-raise / wrap as before
        │ returns
await _emit_after_call(tc, duration_ms, input_tokens, output_tokens, model, finish_reason)
        │
post-processing (parse into output_type, build InvokeResult)
```

**Decision: the terminal event describes the provider call, not the parse.**
`AfterClientCallEvent` is emitted as soon as the provider returns. Parsing
happens afterwards: `answers_to_type`, `_parse_structured_output`,
`custom_parser` and the truncation guard `_raise_if_truncated`. If one of these
raises, the exception still propagates unchanged, but no `ClientCallFailedEvent`
is emitted. Two reasons:
1. The tokens were consumed and billed. Cost recorders must see them. A failed
   event has no token fields (`_emit_failed_call` signature, `base.py:750`), so
   emitting one would lose the cost.
2. `JevClient.ask()` already works this way: `_emit_after_call` runs before
   `_build_message` → `answers_to_type` (`client.py:568-584`).

Each call emits exactly one terminal event. The terminal event is never emitted
twice, and after a terminal event has been emitted, no failed event follows.

**Where the before-event goes.** Input resolution that can fail without
contacting the provider stays **before** `_emit_before_call`. That covers the
Jev question/state resolution and OpenAIBaseClient's model, prompt, max_tokens
and "client not initialised" checks. Those failures emit nothing, which matches
`ask()`, where `_emit_before_call` also comes after input resolution
(`jev/client.py:545-559`, `openai_base.py:796-805`).

#### JevClient.invoke()

| Field | Value (mirrors `JevClient.ask()`, `client.py:553-576`) |
|---|---|
| `_emit_before_call` | `client_name=self.client_name`, `model=resolved_model`, `temperature=None`, `system_prompt=system_prompt`, `has_tools=False` |
| after: `model` | `response.model` |
| after: `duration_ms` | `(time.perf_counter() - started) * 1000` |
| after: tokens | `usage = self._usage_from(response)` → `usage.prompt_tokens` / `usage.completion_tokens` |
| after: `finish_reason` | `"completed"` |
| failed | `await self._emit_failed_call_safe(tc, self.client_name, resolved_model, started, exc)`, **then** the existing `raise self._handle_invoke_error(exc) from exc` |

The `usage` computed for the after-event is **reused** for
`_build_invoke_result` rather than computed twice.

#### OpenAIBaseClient.invoke()

| Field | Value (mirrors `OpenAIBaseClient.ask()`, `openai_base.py:797-805, 1034-1043`) |
|---|---|
| `_emit_before_call` | `client_name=self.client_name`, `model=resolved_model`, `temperature=temperature`, `system_prompt=resolved_prompt`, `has_tools="tools" in kwargs`, `parent_trace=None` |
| after: `model` | `resolved_model` |
| after: tokens | normal / finalize path: `CompletionUsage.from_openai(response.usage)` → `prompt_tokens` / `completion_tokens` (the same `usage` object is then passed to `_build_invoke_result`); partial path: `None` / `None` |
| after: `finish_reason` | normal path: `self._extract_finish_reason(response)`; finalize path **and** partial path: `"budget_exhausted"` (the same literal that `ask()` sets on `stop_reason`, `openai_base.py:1030`) |
| failed | any exception escaping the dispatch block before the after-event (including `BudgetError` subclasses other than a caught `BudgetExhausted`, and a `BudgetExhausted` raised again when the finalize path fails, other than the handled partial path) → `await self._emit_failed_call_safe(tc, self.client_name, resolved_model, t0, exc)`, then the existing `except BudgetError: raise` / `except InvokeError: raise` / `raise self._handle_invoke_error(exc)` chain runs **unchanged** |

The three exit paths of the dispatch block, as they exist today
(`openai_base.py:1600-1677`):
1. `_chat_completion` returns → **normal path**.
2. `_chat_completion` raises `BudgetExhausted` → `_finalize_budgeted_chat`
   returns → **finalize path** (`_budget_forced = True`).
3. `_finalize_budgeted_chat` also raises `BudgetExhausted` → an `InvokeResult`
   with `partial_text` and an empty `CompletionUsage()` is returned →
   **partial path**. This is a successful return, not an error, so it emits
   `AfterClientCallEvent` and not the failed event.

### Component Diagram
```
caller ──invoke()──▶ JevClient / OpenAIBaseClient
                          │  _emit_before_call ──emit_nowait──▶ client registry ──forward_to_global──▶ global registry
                          │  provider call (system_one / _chat_completion)
                          │  _emit_after_call | _emit_failed_call_safe ──await──▶ client registry ──await──▶ global registry
                          ▼                                                                       │
                     InvokeResult                                         MetricsSubscriber / OTel / cost recorders
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractClient._emit_before_call` | calls | sync; returns the `TraceContext` (`base.py:559`) |
| `AbstractClient._emit_after_call` | calls (awaited) | `base.py:696` |
| `AbstractClient._emit_failed_call_safe` | calls (awaited) | never masks the original exception (`base.py:790`) |
| `JevClient.invoke` | modifies | `ai-parrot-client-jev/.../jev/client.py:677` |
| `OpenAIBaseClient.invoke` | modifies | `ai-parrot/.../clients/openai_base.py:1526` |
| OpenAIClient, OpenRouterClient, MoonshotClient, NvidiaClient, MetaClient, BedrockMantleClient, GeminiOpenAICompatClient | inherit (no code change) | none of them overrides `invoke()` |

### Data Models
No new or changed models. The existing event models are used as they are:
`BeforeClientCallEvent`, `AfterClientCallEvent`, `ClientCallFailedEvent`
(`parrot.core.events.lifecycle.events`).

### New Public Interfaces
None. The public signature of `invoke()` does not change in either client.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: JevClient.invoke telemetry | yes | Field table in §2 "JevClient.invoke()"; the hook placement in the §2 Overview diagram; parse errors emit no failed event | — |
| M2: OpenAIBaseClient.invoke telemetry | yes | Field table + the 3 exit paths in §2 "OpenAIBaseClient.invoke()"; exactly one terminal event; the existing except-chain is unchanged | — |

### Module 1: JevClient.invoke() telemetry
- **Path**: `packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py`
- **Responsibility**: Wrap the `system_one` dispatch in `invoke()` with before, after and failed emission, following `ask()`. Add unit tests to `tests/clients/test_jev_client.py`.
- **Depends on**: existing `AbstractClient` hooks only.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py:677
  class JevClient(AbstractClient):  # verified: jev/client.py:119
      async def invoke(  # verified: jev/client.py:677 — signature UNCHANGED
          self,
          prompt: str,
          *,
          output_type: Optional[type] = None,
          structured_output: Optional[StructuredOutputConfig] = None,
          model: Optional[str] = None,
          system_prompt: Optional[str] = None,
          max_tokens: Optional[int] = None,
          temperature: float = 0.0,
          use_tools: bool = False,
          tools: Optional[list] = None,
          questions: Optional[QuestionsInput] = None,
          state: Any = None,
      ) -> InvokeResult:
          """Stateless typed evaluation of ``prompt``.

          Emits BeforeClientCallEvent before the System One request and exactly one
          terminal event: AfterClientCallEvent (tokens, duration, response.model,
          finish_reason="completed") when the request returns, or ClientCallFailedEvent
          when ``system_one`` raises. Errors while resolving questions or state (before
          the request) and parse errors (after it) emit no failed event.

          Raises:
              InvokeError: Wrapping any failure (unchanged).
          """
  ```

### Module 2: OpenAIBaseClient.invoke() telemetry
- **Path**: `packages/ai-parrot/src/parrot/clients/openai_base.py`
- **Responsibility**: Wrap the dispatch block of `invoke()` (the normal, finalize and partial paths) with before, after and failed emission, following `ask()`. Add unit tests under `packages/ai-parrot/tests/unit/clients/`.
- **Depends on**: existing `AbstractClient` hooks only.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/clients/openai_base.py:1526
  class OpenAIBaseClient(AbstractClient):  # verified: openai_base.py:73
      async def invoke(  # verified: openai_base.py:1526 — signature UNCHANGED
          self,
          prompt: str,
          *,
          output_type: type | None = None,
          structured_output: StructuredOutputConfig | None = None,
          model: str | None = None,
          system_prompt: str | None = None,
          max_tokens: int | None = None,
          temperature: float = 0.0,
          use_tools: bool = False,
          tools: list | None = None,
      ) -> InvokeResult:
          """Lightweight stateless invocation routed through the completion funnel.

          Emits BeforeClientCallEvent right before the first ``_chat_completion`` dispatch
          and exactly one terminal event: AfterClientCallEvent on the normal, finalize
          (finish_reason="budget_exhausted") and partial (tokens None,
          finish_reason="budget_exhausted") paths, or ClientCallFailedEvent when the
          dispatch raises. Errors before dispatch and parse errors after it emit no failed event.

          Raises:
              BudgetError / InvokeError: unchanged from today.
          """
  ```

---

## 4. Test Specification

Pattern to follow: `packages/ai-parrot/tests/unit/clients/test_client_failed_call_emission.py`.
Subscribe with `client.events.subscribe(EventCls, cb)`, then run
`await asyncio.sleep(0.05)` to drain the `emit_nowait` tasks. **Note:** the
`_Stub` in that file overrides `invoke()` with `raise NotImplementedError`. The
new OpenAIBaseClient tests need a stub that does NOT override `invoke()`, or
they will not test the real method.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_invoke_emits_before_and_after_with_usage` | M1 | Uses `stub_api`. One Before and one After event. The After event has `input_tokens`/`output_tokens` equal to the response usage, `model == response.model`, `finish_reason == "completed"`, `duration_ms > 0`, `client_name == "jev"` |
| `test_invoke_api_error_emits_failed_and_raises_invokeerror` | M1 | The stub returns an HTTP error. One Failed event, no After event, `InvokeError` still raised |
| `test_invoke_missing_questions_emits_nothing` | M1 | A `JevConfigurationError` raised before the request produces no events at all |
| `test_invoke_emits_before_and_after` | M2 | Fake `_chat_completion` with usage 10/5 and `finish_reason="stop"`. The After event has 10/5, `finish_reason == "stop"`, `model == resolved_model` |
| `test_invoke_error_emits_failed_not_after` | M2 | `_chat_completion` raises `RuntimeError`. One Failed event (`error_type == "RuntimeError"`), no After event, `InvokeError` raised |
| `test_invoke_budget_finalize_emits_after_budget_exhausted` | M2 | `_chat_completion` raises `BudgetExhausted` and `_finalize_budgeted_chat` returns. After event with `finish_reason == "budget_exhausted"` and the finalize usage |
| `test_invoke_budget_partial_emits_after_without_tokens` | M2 | Both raise `BudgetExhausted`. After event with `input_tokens is None`, `output_tokens is None`, `finish_reason == "budget_exhausted"`; the `InvokeResult` is returned |
| `test_invoke_parse_failure_emits_after_only` | M2 | Truncated response (`finish_reason="length"`) with `output_type` set. After event emitted, then `InvokeError`/`TruncatedResponseError` raised, no Failed event |
| `test_invoke_exactly_one_terminal_event` | M1, M2 | Parametrized over the paths above: `len(after) + len(failed) == 1` |

### Integration Tests
None required. The global-registry forwarding is already covered by the existing lifecycle tests.

---

## 5. Acceptance Criteria

- [ ] `JevClient.invoke()` emits `BeforeClientCallEvent` + `AfterClientCallEvent` on success, with `input_tokens`, `output_tokens`, `duration_ms`, `model=response.model` and `finish_reason="completed"`.
- [ ] `JevClient.invoke()` emits `ClientCallFailedEvent` (and no After event) when `system_one` raises, and still raises `InvokeError`.
- [ ] `OpenAIBaseClient.invoke()` emits Before + After on the normal path, with `finish_reason` from `_extract_finish_reason(response)` and the tokens from `CompletionUsage.from_openai`.
- [ ] `OpenAIBaseClient.invoke()` emits After with `finish_reason="budget_exhausted"` on both the finalize path and the partial path (partial: tokens `None`).
- [ ] `OpenAIBaseClient.invoke()` emits Failed (no After) on dispatch errors, and the exception it raises (type and message) is unchanged.
- [ ] Every `invoke()` call that reaches dispatch produces exactly one terminal event. Input-resolution errors produce no events.
- [ ] Neither `invoke()` signature and neither `InvokeResult` changes. `clients/base.py` is not modified.
- [ ] New tests pass: `pytest tests/clients/test_jev_client.py packages/ai-parrot/tests/unit/clients/ -v`.
- [ ] Existing invoke tests still pass (`tests/clients/test_jev_client.py::test_invoke_*`, and the OpenAI-family invoke tests).
- [ ] `ruff check` is clean on the modified files.

---

## 6. Codebase Contract

### Verified Imports
```python
# openai_base.py — already imported, reuse as is
import time                                                             # verified: openai_base.py:26
from ..core.exceptions import BudgetAccountingError, BudgetError, BudgetExhausted  # verified: openai_base.py:41
# jev/client.py — already imported
import time                                                             # verified: jev/client.py:37
# tests
from parrot.core.events.lifecycle.events import (                       # verified: clients/base.py:50-56 (same import)
    BeforeClientCallEvent, AfterClientCallEvent, ClientCallFailedEvent,
)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):                           # line 235
    client_name: str = "generic"                                        # line 243
    def _emit_before_call(self, *, client_name: str, model: str,
        temperature: Optional[float] = None, system_prompt: Optional[str] = None,
        has_tools: bool = False, parent_trace: Optional[TraceContext] = None) -> TraceContext:  # line 559
    async def _emit_after_call(self, tc: TraceContext, *, client_name: str, model: str,
        duration_ms: float, input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None, finish_reason: Optional[str] = None) -> None:     # line 696
    async def _emit_failed_call(self, tc, *, client_name, model, duration_ms, exc) -> None:  # line 750
    async def _emit_failed_call_safe(self, tc: TraceContext, client_name: str, model: str,
        t0: float, exc: Exception) -> None:                             # line 790 — positional; t0 = perf_counter()
    def _build_invoke_result(self, output, output_type, model, usage, raw_response=None) -> InvokeResult:  # line 2158
    def _handle_invoke_error(self, exception: Exception) -> InvokeError:  # line 2186 — returns an existing InvokeError unchanged

# packages/ai-parrot/src/parrot/clients/openai_base.py
class OpenAIBaseClient(AbstractClient):                                 # line 73
    async def _finalize_budgeted_chat(...)                              # line 286
    async def invoke(...) -> InvokeResult:                              # line 1526
    #   resolved_prompt / config / resolved_model / max_tokens resolution   1572-1575
    #   "not initialised" RuntimeError check                                1597-1598
    #   _budget_call_id + _BUDGET_CALL_CTX.set(...)                          1606-1607
    #   response = await self._chat_completion(model=resolved_model, messages=messages, use_tools=True, **kwargs)  1609
    #   except BudgetExhausted → _finalize_budgeted_chat(...) → _budget_forced = True    1612-1624
    #   except BudgetExhausted as bx2 → return partial InvokeResult(usage=CompletionUsage())  1625-1637
    #   _raise_if_truncated / custom_parser / _parse_structured_output       1643-1653
    #   usage = CompletionUsage.from_openai(response.usage)                  1660
    #   except BudgetError: raise / except InvokeError: raise / except Exception: raise self._handle_invoke_error(exc)  1672-1677
    # ask() telemetry reference: _emit_before_call 797-805, _emit_failed_call_safe 904/913, _emit_after_call 1034-1043
    # ask() sets stop_reason = "budget_exhausted"                            1030

# packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py
class JevClient(AbstractClient):                                        # line 119
    client_name: str = "jev"                                            # line 157
    @staticmethod
    def _usage_from(response: SystemOneResponse) -> CompletionUsage:    # line 411
    async def system_one(self, state, questions, *, model=None, extra_body=None, timeout=None)  # line 425
    async def ask(...)  # telemetry reference: lines 553-576
    async def invoke(...) -> InvokeResult:                              # line 677
    #   try: _resolve_questions → _coerce_state/_build_state → system_one → answers_to_type   725-732
    #   except Exception as exc: raise self._handle_invoke_error(exc) from exc                733-734
    #   return self._build_invoke_result(output, resolved_type, response.model, self._usage_from(response), raw_response=...)  735-741
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| JevClient.invoke | `_emit_before_call` / `_emit_after_call` / `_emit_failed_call_safe` | method calls | `base.py:559/696/790` |
| OpenAIBaseClient.invoke | same three hooks | method calls | `base.py:559/696/790` |
| OpenAIBaseClient.invoke | `_extract_finish_reason(response)` | method call (already used in invoke) | `openai_base.py:1645` |
| Jev tests | `stub_api` fixture, `_client(server)`, `_sample_response()` | pytest fixture/helpers | `tests/clients/test_jev_client.py:93,125,72` |
| OpenAIBaseClient tests | `_make_openai_stub` pattern (but without the `invoke` override) | copy/adapt | `packages/ai-parrot/tests/unit/clients/test_client_failed_call_emission.py:30-72` |

### Does NOT Exist (Anti-Hallucination)
- ~~`AbstractClient._emit_invoke_*`~~ / ~~an instrumented-invoke decorator~~: there is no invoke-specific hook. Use the three generic hooks.
- ~~`_chat_completion` emitting lifecycle events~~: it emits none. The emission lives in `ask()`/`ask_stream()` (and is added to `invoke()` by this spec).
- ~~`InvokeResult.finish_reason`~~: `InvokeResult` has no finish-reason field. Take the finish reason from the response.
- ~~`ClientCallFailedEvent.input_tokens`~~: the failed event carries no token fields.
- ~~Jev tests under `packages/ai-parrot-client-jev/tests/` for invoke~~: that directory only has `test_entry_points.py`. The behavioural tests are in the repo-root `tests/clients/test_jev_client.py`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Copy the telemetry block of each client's own `ask()` exactly (field names, the `time.perf_counter()` clock, `_emit_failed_call_safe` argument order).
- `_emit_failed_call_safe` goes **before** the existing wrap/re-raise, so the original exception still propagates unchanged.
- Compute `usage` once and pass the same object to both `_emit_after_call` and `_build_invoke_result`.

### Known Risks / Gotchas
- **Double terminal emission** in OpenAIBaseClient: the dispatch block has nested `try`/`except BudgetExhausted` blocks inside an outer `try` with a wrapping except-chain. Track a local flag (e.g. `_lc_done`) so that an exception raised *after* `_emit_after_call` (a parse error) cannot also emit a Failed event in the outer handler.
- **Partial path returns from inside an `except`**. The After event must be emitted before that `return`.
- **Subclasses that override `invoke()`** (GroqClient, LocalLLMClient, ZaiClient) keep having no telemetry. Tests must not assume every `OpenAIBaseClient` subclass is covered.
- **Existing test stubs override `invoke()`** (`test_client_failed_call_emission.py:49`, `test_client_lifecycle.py:56`). The new tests need their own stub.
- **Worktree tests**: set `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-jev/src` when running pytest inside the feature worktree (the shared venv is editable-installed against the main checkout).

### External Dependencies
None.

---

## 8. Open Questions

- [ ] Q1: Follow-up spec to bring the same telemetry to the other 12 `invoke()` implementations, starting with GroqClient/LocalLLMClient/ZaiClient, which override the `OpenAIBaseClient` version? Could lifting this into a shared `AbstractClient` helper justify touching `clients/base.py`? — *Owner: Jesus Lara*: Yes

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document — spec requested without a brainstorm) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree for this spec. The `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**: M1 and M2 have no edge between them. They touch different distributions (`ai-parrot-client-jev` vs `ai-parrot`), and M1 only depends on hooks that already exist in `base.py`, not on anything M2 adds. They can run concurrently.
- **Shared files**: none. M1 → `jev/client.py` + `tests/clients/test_jev_client.py`; M2 → `openai_base.py` + a new test file under `packages/ai-parrot/tests/unit/clients/`.
- **Exclusive resources**: none (no lockfile, migration or extension rebuild).
- **Cross-feature dependencies**: none.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-19 | Jesus Lara | Initial draft |
