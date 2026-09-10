# TASK-3143: Mantle Finalization in `_run_tool_call_loop`, Streaming Loop, Budgeted `resume` and `invoke`

**Feature**: FEAT-550 — Cumulative Question Token Budgets for Bedrock and Mantle
**Spec**: `sdd/specs/token-budget-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3142
**Assigned-to**: unassigned

---

## Context

Module 5, half 2 (spec §3 M5 "Integrate finalization with `_run_tool_call_loop` and the
separate streaming loop. Budgeted `resume` preserves its scope and stamps actual
accumulated invocation usage"). Mirrors TASK-3141 for the OpenAI-compatible loops in
`openai_base.py`, but only `BedrockMantleClient` is covered (its `budget_adapter_factory`
is what makes the shared hooks live).

---

## Scope

- `openai_base.py`:
  - `_finalize_budgeted_chat(messages, *, model_str, args, all_tool_calls, pending_tool_calls, partial_text, stream: bool)`:
    owner check / direct-root self-designation / `claim_finalization` / frame →
    `adapter.prepare_finalization` → set `_BUDGET_CALL_CTX` to `phase="final"` → **one**
    `_chat_completion(model, final_messages, use_tools=False, **final_args)` (tools removed,
    `stream=stream`); on failure `BudgetExhausted` with `partial_text`; no retry beyond the
    single budgeted attempt (`_chat_completion_budgeted` still has tenacity — for the final
    attempt pass a per-call flag `_BUDGET_CALL_CTX["single_attempt"]=True` so it uses
    `stop_after_attempt(1)`);
  - `_run_tool_call_loop`: set `_BUDGET_CALL_CTX` round numbers before each
    `call_completion(...)`; wrap that call in `except BudgetExhausted` → finalization →
    `result = response.choices[0].message` and `break` (no tool execution on the final
    result; `answer_complete=False` if it has `tool_calls`); return the extra flag
    `budget_forced` through a new attribute on `self` for the current call
    (`_BUDGET_CALL_CTX["forced"] = True`) rather than changing the 5-tuple return shape;
  - `ask()`: after `AIMessageFactory.from_openai(...)`, attach `metadata["token_budget"]`
    when a scope is live; `stop_reason="budget_exhausted"` when forced; structured output
    bypass of `_raise_if_truncated`/`custom_parser` when forced (same rule as TASK-3141);
    the first `_chat_completion` before the loop is also a round — wrap it;
  - `ask_stream()`: round loop gets `except asyncio.CancelledError: raise` then
    `except BudgetExhausted` → stream finalization chunks in-band → exactly one terminal
    `AIMessage` with report + `stop_reason`; if finalization cannot run → raise with
    `partial_text=assistant_content`;
  - `resume()`: deep-copy `state["messages"]`; the two `HumanInteractionInterrupt` sites
    (`e.agent_name = model_str`, 2 occurrences: `_run_tool_call_loop` ~466 and `ask_stream`
    ~1118) merge the `token_budget` envelope via `scope.registry.suspend(scope)`; budgeted
    `resume` passes `track_usage=True` so the returned `AIMessage.usage` carries the accumulated
    invocation usage (spec §3 M5) — only when a scope is live, to keep no-budget behaviour;
  - `invoke()`: `except BudgetError: raise` before `except Exception as exc: raise self._handle_invoke_error(exc)`;
    forced → `InvokeResult(... output_type=None, budget_report=report)`, never `custom_parser`.
- Tests (append to `test_token_budget_mantle.py`): finalization rows for Mantle (one
  tools-disabled attempt, `tools` absent from the final wire call, zero reserve / oversized
  skip, final `tool_calls` not executed), streaming rows (in-band finalization, one sentinel,
  cancellation), "budgeted resume aggregation", "Structured result", envelope on interrupt.

**NOT in scope**: Bedrock (done), docs (TASK-3145), integration scenarios (TASK-3144).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/openai_base.py` | MODIFY | Finalization, report attachment, envelope, resume usage, invoke guard |
| `packages/ai-parrot-client-amazon/tests/unit/test_token_budget_mantle.py` | MODIFY | Append finalization/stream/resume/structured tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev `755c61347` on 2026-09-11 plus TASK-3142 declared outputs.

### Verified Imports
```python
from parrot.core.exceptions import BudgetError, BudgetExhausted, HumanInteractionInterrupt   # TASK-3132 / core/exceptions.py:12
from .budget_scope import current_budget_scope, TOKEN_BUDGET_STATE_KEY                     # TASK-3134 (current_budget_scope already imported by TASK-3142)
import copy, asyncio                                                                        # stdlib (asyncio not yet imported in openai_base.py — add it)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/openai_base.py (line numbers pre-TASK-3142)
_BUDGET_CALL_CTX: ContextVar[dict]                                                     # TASK-3142
async def _chat_completion(self, model, messages, use_tools=False, stream=False, **kwargs)   # :216 (budgeted branch added by TASK-3142)
async def _run_tool_call_loop(self, *, result, response, messages, model_str, use_tools, args, call_completion=None, session_id=None,
                              lazy_loading=False, active_tool_names=None, track_usage=False, initial_duration_ms=0.0, on_round=None,
                              record_malformed_tool_calls=True, default_tool_name=None) -> tuple   # :295-313
    while getattr(result, "tool_calls", None):                                          # :404
        ... e.agent_name = model_str  (interrupt site 1, ~:466)
        response = await call_completion(model=model_str, messages=messages, use_tools=use_tools, **args)   # :503 ← anchor (1 occurrence)
        result = response.choices[0].message                                            # :511
    return result, response, all_tool_calls, accumulated_usage, round_number            # :513 ← anchor (1 occurrence)
async def ask(...)                                                                      # :523; first _chat_completion before the loop; `_run_tool_call_loop(... track_usage=True ...)` ~:694-707
async def resume(self, session_id, user_input, state)                                   # :771; `messages = state["messages"]` (in place); `model_str = state.get("agent_name", self.model or self.default_model)` ← anchor (1 occurrence); `_run_tool_call_loop(... args={}, record_malformed_tool_calls=False, default_tool_name="unknown")` (no track_usage)
async def ask_stream(...)                                                               # :893; `for _round in range(_max_tool_rounds):` ~:1012; `response_stream = await self._chat_completion(..., stream=True, **args)`; interrupt site 2 ~:1118; `yield ai_message` ← anchor (1 occurrence, ~:1160)
async def invoke(...)                                                                   # :1170; `except InvokeError: raise` / `except Exception as exc: raise self._handle_invoke_error(exc)` ~:1263-1266

# packages/ai-parrot/src/parrot/clients/base.py
def _build_invoke_result(self, output, output_type, model, usage, raw) -> InvokeResult   # :2097
def _raise_if_truncated(self, finish_reason, *, model) -> None                           # :2221
```

### Does NOT Exist
- ~~Changing `_run_tool_call_loop`'s 5-tuple return~~ — other callers (OpenAI-family satellites) depend on it; signal `forced` via `_BUDGET_CALL_CTX`.
- ~~Executing `tool_calls` present on the final response~~ — forbidden (spec §2.3 row 3).
- ~~`resume()` with `track_usage=True` unconditionally~~ — only under a live scope (spec §3 M5 "no-budget siblings remain compatible").
- ~~A second `.parse()` request after a parse failure~~ — spec §3 M5 transport restriction; the final attempt is one physical call.
- ~~`asyncio` already imported in `openai_base.py`~~ — it is not; add `import asyncio`.

---

## Implementation Notes

### Pattern to Follow
```python
# _run_tool_call_loop round call
_BUDGET_CALL_CTX.set({**_BUDGET_CALL_CTX.get(), "round_number": round_number + 1, "phase": "work"})
try:
    response = await call_completion(model=model_str, messages=messages, use_tools=use_tools, **args)
except BudgetExhausted:
    response = await self._finalize_budgeted_chat(messages, model_str=model_str, args=args, all_tool_calls=all_tool_calls,
                                                  pending_tool_calls=[], partial_text=_partial(messages), stream=False)
    _BUDGET_CALL_CTX.set({**_BUDGET_CALL_CTX.get(), "forced": True})
    result = response.choices[0].message
    round_number += 1
    break
```

### Key Constraints
- `call_completion` defaults to `self._chat_completion` in `ask()`; the finalizer must call
  `self._chat_completion` directly with `use_tools=False` and `args` minus `tools`/`tool_choice`
  (the adapter's `prepare_finalization` already produced the final `messages`; pass the
  `response_format` from `args` through).
- `_BUDGET_CALL_CTX` must be **set at the start of each public method** (`ask`, `ask_stream`,
  `resume`, `invoke`) with a fresh `call_id` and reset in `finally` (use `token = _BUDGET_CALL_CTX.set(...)` / `_BUDGET_CALL_CTX.reset(token)`).
- Single-attempt final: in `_chat_completion_budgeted` (TASK-3142) read `ctx.get("single_attempt")`
  and use `stop_after_attempt(1)` — a one-line addition to that method.
- Owner rules identical to TASK-3141 (`scope.is_root` required; self-designate when
  `not scope.owner_designated`; child → re-raise).
- `partial_text` = concatenation of assistant `content` strings already in `messages`.
- Report attachment for every budgeted `ask`/`ask_stream`/`resume` result; `InvokeResult.budget_report` for `invoke`.

### References in Codebase
- `openai_base.py:404-513` — loop body; `:1012-1130` — stream loop; `:771-817` — resume.
- TASK-3141 blueprint — same decision table for Bedrock; keep semantics identical.

---

## Implementation Blueprint

### Steps (in order)
1. Add `import asyncio`, `import copy`, `BudgetError`/`BudgetExhausted`/`TOKEN_BUDGET_STATE_KEY` imports.
2. `_finalize_budgeted_chat` + `single_attempt` support — *why*: one finalizer for `ask`/`resume`/`ask_stream`/`invoke`.
3. Loop wiring (`_run_tool_call_loop`, `ask` pre-loop call) + report/stop_reason/structured bypass in `ask`.
4. `ask_stream` finalization + cancel guard + single sentinel.
5. `resume`: deepcopy, envelope sites, conditional `track_usage=True`.
6. `invoke` guard + `budget_report`.
7. Tests.

### `packages/ai-parrot/src/parrot/clients/openai_base.py` (MODIFY — finalizer)
```python
# occurrences: 1 (verified after TASK-3142: grep -c '    async def _chat_completion_budgeted(' packages/ai-parrot/src/parrot/clients/openai_base.py)
# BEFORE — insert above `    async def _chat_completion_budgeted(`
    async def _finalize_budgeted_chat(
        self, messages: list[dict[str, Any]], *, model_str: str, args: dict[str, Any], all_tool_calls: list[ToolCall],
        pending_tool_calls: list[dict[str, Any]], partial_text: str, stream: bool,
    ) -> Any:
        """Owner-only, one tools-disabled Chat Completions attempt inside A_final (spec §2.3); raises BudgetExhausted otherwise."""
        scope = current_budget_scope()
        if scope is None or not scope.is_root:
            raise BudgetExhausted("child scope exhausted", report={"partial_text": partial_text})
        ctx = _BUDGET_CALL_CTX.get()
        if not scope.owner_designated:
            scope.designate_owner(ctx.get("call_id") or str(uuid.uuid4()))
        if not await scope.ledger.claim_finalization(scope.owner_call_id):
            raise BudgetExhausted("finalization already claimed or in-flight", operation_id=scope.ledger.operation_id,
                                  report={**(await scope.ledger.report()).model_dump(), "partial_text": partial_text})
        adapter = self.budget_adapter_factory()
        frame = {"payload": {"model": model_str, "messages": messages, **args}, "completed_tool_calls": [tc.model_dump() for tc in all_tool_calls if tc.error is None],
                 "pending_tool_calls": pending_tool_calls, "answer_text": partial_text}
        final_payload = adapter.prepare_finalization(frame)
        final_args = {k: v for k, v in args.items() if k not in ("tools", "tool_choice")}
        token = _BUDGET_CALL_CTX.set({**ctx, "phase": "final", "single_attempt": True})
        try:
            # FILL IN: return await self._chat_completion(model=model_str, messages=final_payload["messages"], use_tools=False, stream=stream, **final_args)
            #          mapping BudgetExhausted/other exceptions to BudgetExhausted(report={..., "partial_text": partial_text}); no retry, no fallback.
            #          Bounded by spec §2.3 table rows 1-3 and §3 M5 transport restriction.
            raise NotImplementedError
        finally:
            _BUDGET_CALL_CTX.reset(token)
```
**Why this shape**: identical decision table to TASK-3141 so both providers behave the same (AC "At most one finalization inference occurs per operation").

### `packages/ai-parrot/src/parrot/clients/openai_base.py` (MODIFY — loops)
```python
# occurrences: 1 (verified: grep -c '            response = await call_completion(model=model_str, messages=messages, use_tools=use_tools, \*\*args)' packages/ai-parrot/src/parrot/clients/openai_base.py)
# REPLACE that line (verified: openai_base.py:503) with the "Pattern to Follow" block above (keeps `round_t0`/`round_number += 1`/duration lines that follow it,
# but on the forced branch `break` BEFORE the tool execution of the next iteration — i.e. set `result` and break out of the while).
```
```python
# occurrences: 1 (verified: grep -c '        return result, response, all_tool_calls, accumulated_usage, round_number' packages/ai-parrot/src/parrot/clients/openai_base.py)
# FILL IN: no change to the return line; in ask() after `_run_tool_call_loop(...)` read `_BUDGET_CALL_CTX.get().get("forced")` and apply:
#          attach `ai_message.metadata["token_budget"] = (await scope.ledger.report()).model_dump()` for any live scope; if forced -> stop_reason
#          "budget_exhausted", skip _raise_if_truncated/custom_parser (raw text), set_answer_complete(False) when structured or final has tool_calls.
#          Also wrap ask()'s FIRST `_chat_completion(...)` (before the loop) with the same except-BudgetExhausted → finalize → skip loop.
#          Bounded by spec §2.3.
```
```python
# occurrences: 1 (verified: grep -c '        yield ai_message' packages/ai-parrot/src/parrot/clients/openai_base.py)
# FILL IN: ask_stream() (openai_base.py:1012-1160) — inside `for _round in range(_max_tool_rounds):` wrap `response_stream = await self._chat_completion(...)`
#          with `except asyncio.CancelledError: raise` / `except BudgetExhausted:` -> `response_stream = await self._finalize_budgeted_chat(..., stream=True)`,
#          then iterate it yielding text deltas (append to assistant_content) and capturing usage; set forced; break. Before `yield ai_message`
#          attach report / stop_reason. Exactly ONE AIMessage yielded. Bounded by spec §2.4.
```
```python
# occurrences: 2 (verified: grep -c '                            e.agent_name = model_str' packages/ai-parrot/src/parrot/clients/openai_base.py)
# FILL IN: disambiguate — apply to BOTH sites (_run_tool_call_loop ~466, ask_stream ~1118); insert directly below each:
                            _scope = current_budget_scope()
                            if _scope is not None:
                                e.state = {**(getattr(e, "state", None) or {}), TOKEN_BUDGET_STATE_KEY: await _scope.registry.suspend(_scope)}
# Bounded by spec §2.6 "merge the new namespaced envelope".
```
```python
# occurrences: 1 (verified: grep -c '        model_str = state.get("agent_name", self.model or self.default_model)' packages/ai-parrot/src/parrot/clients/openai_base.py)
# FILL IN: resume() — replace `messages = state["messages"]` with `messages = copy.deepcopy(state["messages"])`; pass
#          `track_usage=current_budget_scope() is not None` to _run_tool_call_loop and, when it returns accumulated usage, set `ai_message.usage`;
#          attach the report as in ask(). Bounded by spec §3 M5 "Budgeted resume preserves its scope and stamps actual accumulated invocation usage".
```
```python
# FILL IN: invoke() — add `except BudgetError: raise` immediately before `except Exception as exc:  # noqa: BLE001 — funnel errors are wrapped into InvokeError`;
#          wrap its `_chat_completion` in except-BudgetExhausted → `_finalize_budgeted_chat(messages, ..., all_tool_calls=[], stream=False)`; forced ->
#          output raw text, output_type None, no custom_parser; set `.budget_report` on the InvokeResult when a scope is live. Bounded by spec §2.3 / §3 M3.
```
**Why**: same surface as Bedrock; the `_BUDGET_CALL_CTX` flag avoids touching the shared 5-tuple used by other satellites.

### `packages/ai-parrot-client-amazon/tests/unit/test_token_budget_mantle.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3142: grep -c 'class TestChatCompletionHooks' packages/ai-parrot-client-amazon/tests/unit/test_token_budget_mantle.py)
# AFTER — append at end of file
class TestMantleFinalization:
    async def test_one_tools_disabled_final_attempt(self):
        # FILL IN: fake responses: tool round (950/50 usage), tool round, then FINAL — assert the final create() kwargs contain no "tools" and
        #          max_tokens <= remaining; ask() returns stop_reason budget_exhausted; exactly 3 create calls. Bounded by spec §2.3.
        raise NotImplementedError

    async def test_zero_reserve_or_oversized_skips_and_final_tool_calls_not_executed(self):
        # FILL IN: two cases from spec §2.3 table rows 2-3.
        raise NotImplementedError


class TestMantleStreaming:
    async def test_inband_finalization_single_sentinel_and_cancel(self):
        # FILL IN: mirror TASK-3141 streaming tests for the chat-completions chunk shape (choices[0].delta.content, terminal usage chunk).
        raise NotImplementedError


class TestBudgetedResume:
    async def test_resume_aggregates_usage_and_carries_envelope(self):
        # FILL IN: interrupt under budget -> state has token_budget envelope; resume(state) -> AIMessage.usage.total_tokens == sum of rounds,
        #          state["messages"] not mutated, same operation_id in report. Bounded by spec §3 M5 / §2.6.
        raise NotImplementedError


class TestMantleStructured:
    async def test_cutoff_never_reaches_parser_and_invoke_report(self):
        # FILL IN: custom_parser mock not called on forced finalization; invoke(...).budget_report has "operation_id"; BudgetError escapes invoke unwrapped.
        raise NotImplementedError
```
**Why**: spec §4 rows "Finalization", "Streaming", "Mantle accounting … budgeted resume aggregation", "Structured result", "Exception propagation (invoke wrapping)".

### FILL IN checklist
- [ ] `openai_base.py::_finalize_budgeted_chat` attempt body; bounded by spec §2.3
- [ ] `openai_base.py::_chat_completion_budgeted` — honour `single_attempt` (stop_after_attempt(1)); bounded by spec §2.3 "automatic retries … disabled"
- [ ] `_run_tool_call_loop` / `ask` / `ask_stream` / `resume` / `invoke` wiring; bounded by spec §2.3-2.4, §2.6, §3 M5
- [ ] all test bodies

---

## Acceptance Criteria

- [ ] Mantle `ask()` under the §2.3 example does exactly three wire calls; the final has no `tools`/`tool_choice`, cap ≤ remaining `A_final`
- [ ] Reserve zero / oversized final → no closing call; `partial_text` propagated; final `tool_calls` never executed and flagged `answer_complete=False`
- [ ] `ask_stream` streams finalization in-band, one terminal `AIMessage`; cancellation never finalizes
- [ ] Budgeted `resume` deep-copies state, carries the envelope from the interrupt, returns accumulated usage and the report; no-budget `resume` unchanged
- [ ] `invoke`: `BudgetError` escapes unwrapped; forced → raw text, `output_type=None`, `budget_report` set; `custom_parser` never called on cutoff
- [ ] `pytest packages/ai-parrot-client-amazon/tests/unit packages/ai-parrot/tests/clients/test_bedrock_mantle.py packages/ai-parrot/tests/unit/clients -q` passes

---

## Test Specification

Scaffold above. Add `test_child_scope_reraises_without_finalizing` (same as TASK-3141's, for Mantle).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2.3, §2.4, §2.6, §3 Module 5
2. **Check dependencies** — TASK-3142 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-run every `grep -c`; the 2× interrupt anchor MUST be applied at both sites
4. **Update status** in `sdd/tasks/index/token-budget-bedrock.json` → `"in-progress"`
5. **Implement** from the Blueprint
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3143-mantle-finalization-loops.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
