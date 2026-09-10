# TASK-3141: Bedrock Draining, One Tools-Disabled Finalization, Report Attachment and Stream Sentinel

**Feature**: FEAT-550 — Cumulative Question Token Budgets for Bedrock and Mantle
**Spec**: `sdd/specs/token-budget-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3140
**Assigned-to**: unassigned

---

## Context

Module 4, client-integration half 2 (spec §2.3 "Finalization and Partial Results",
§2.4 streaming sentinel, §3 M4 "Build finalization payloads inside all text loops"). With
TASK-3140 in place, a `BudgetExhausted` from `ledger.reserve(phase="work")` now surfaces
inside `ask` / `ask_stream` / `resume` / `invoke`. This task turns that into the spec's
behaviour:

1. stop scheduling ordinary rounds/tools (the ledger is already `draining`);
2. if this client is the **answer owner** (`scope.is_root and scope.owner_designated`) →
   `claim_finalization(owner_call_id)`; build the finalization frame → `prepare_finalization`
   → **one** `phase="final"` attempt with tools removed, fallback disabled;
3. return/yield the answer with `metadata["token_budget"]` = report,
   `stop_reason="budget_exhausted"` on forced termination, `answer_complete` truthful;
4. if not owner (child) → re-raise `BudgetExhausted` (owner handles it); if finalization
   cannot fit / reserve zero / frame unavailable → raise `BudgetExhausted` carrying
   `report["partial_text"]` so the bot boundary (TASK-3137) returns a partial result.

---

## Scope

- `bedrock.py` `BedrockConverseBase`:
  - `_finalize_budgeted(payload, *, bedrock_messages, content_blocks, all_tool_calls, call_id, round_number, resolved_model, original_prompt, turn_id) -> Dict[str, Any] | None`
    — shared by `ask` and `resume`: performs owner check + claim + frame + one final attempt
    via `_budgeted_attempt(..., phase="final")` and `_sdk_create(final_payload, handle=...)`;
    returns the final Converse `result` dict, or raises `BudgetExhausted` with
    `partial_text` when it cannot run;
  - `ask` / `resume`: wrap the round's `_budgeted_attempt` block in
    `except BudgetExhausted as bx:` → `result = await self._finalize_budgeted(...)`; then
    `break` out of the loop (no tool execution on the final result even if it contains
    `toolUse`, spec §2.3 table row 3); mark `_budget_forced = True`;
  - after `AIMessageFactory.from_bedrock(...)`: if a scope is live, attach
    `ai_message.metadata["token_budget"] = (await scope.ledger.report()).model_dump()`;
    if `_budget_forced`, set `ai_message.stop_reason = "budget_exhausted"` (keep provider
    `finish_reason`), and if the final result had `stopReason == "tool_use"` or the
    provider truncated → `answer_complete=False` in the report (ledger flag setter
    `ledger.set_answer_complete(False)` — add this small method to `QuestionBudget` here);
  - structured output: when `_budget_forced` and the final text fails to parse (or
    provider length cutoff) → do not call `custom_parser`; return raw text (existing
    `except Exception: final_output = assistant_response_text` covers parse failure; add
    the `_raise_if_truncated` bypass so a truncated final does not raise `InvokeError` but
    yields partial text + incomplete report);
  - `ask_stream`: on `BudgetExhausted` in a round → same finalization via
    `_sdk_stream(final_payload, handle=...)`, yielding the finalization text chunks in the
    same stream; then the existing tail yields exactly one terminal `AIMessage` with the
    report and `stop_reason="budget_exhausted"`; if finalization cannot run → raise
    `BudgetExhausted` with `partial_text=accumulated_text` (the bot boundary emits the
    single sentinel);
  - `invoke`: `except BudgetError: raise` **before** `except Exception as exc: raise self._handle_invoke_error(exc)`
    (spec §3 M3 exception rule — invoke wrapping); a budget-forced invoke returns
    `InvokeResult(output=raw_text, output_type=None, budget_report=report)` and never
    reaches a custom parser (spec §2.3).
- Tests (append to `test_token_budget_bedrock.py`): "Finalization" client rows (one
  tools-disabled attempt; zero reserve skips; oversized input skips; final result with
  `toolUse` → no execution, `answer_complete=False`; no fallback on the final attempt),
  "Streaming" rows (finalization chunks in-stream, exactly one sentinel, cancellation →
  no finalization request), "Structured result" (budget cutoff never reaches
  `custom_parser`; `InvokeResult.budget_report` populated).

**NOT in scope**: Mantle (TASK-3143), bot translation (TASK-3137 — already done by then), docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py` | MODIFY | Finalization in the four text methods, report attachment, invoke guard |
| `packages/ai-parrot/src/parrot/clients/budget.py` | MODIFY | `QuestionBudget.set_answer_complete()` |
| `packages/ai-parrot-client-amazon/tests/unit/test_token_budget_bedrock.py` | MODIFY | Append finalization/stream/structured tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev `755c61347` on 2026-09-11 plus TASK-3139/3140 declared outputs.

### Verified Imports
```python
from parrot.core.exceptions import BudgetError, BudgetExhausted            # TASK-3132
from parrot.clients.budget_scope import current_budget_scope              # TASK-3134 (already imported by TASK-3140)
from .budget import BedrockBudgetAdapter, FINALIZATION_INSTRUCTION        # TASK-3139
# bedrock.py already imports InvokeError (:51), AIMessageFactory/InvokeResult (:54), CompletionUsage/ToolCall (:52)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py (after TASK-3140)
    async def _budgeted_attempt(self, payload, *, route, stream, call_id, round_number, attempt_number, phase="work")   # yields _AttemptHandle
    async def _sdk_create(self, payload, handle=None) -> Dict[str, Any]
    async def _sdk_stream(self, payload, handle=None) -> AsyncIterator[Dict[str, Any]]
    def _get_budget_adapter(self) -> BedrockBudgetAdapter
    # ask(): `while True:` loop at ~897; after loop: `final_output = None` / `assistant_response_text = "".join(...)` / `if output_config:` block with
    #   `self._raise_if_truncated(result.get("stopReason"), model=resolved_model)` then `custom_parser` / `_parse_structured_output`;
    #   `ai_message = AIMessageFactory.from_bedrock(response=result, ...)` (~1063); `return ai_message` (~1099)
    # ask_stream(): `synthetic_response = {...}` then `_lc_stream_msg = AIMessageFactory.from_bedrock(...)`; `yield _lc_stream_msg` (1 occurrence, ~1372)
    # resume(): loop mirrors ask() without fallback; `ai_message = AIMessageFactory.from_bedrock(response=result, input_text="[Resumed Conversation]", ...)`
    # invoke(): `except InvokeError: raise` / `except Exception as exc: raise self._handle_invoke_error(exc)` (~1699-1702);
    #   `return self._build_invoke_result(output, output_type, resolved_model, usage, result)` (1 occurrence, ~1697)

# packages/ai-parrot/src/parrot/clients/base.py
    def _build_invoke_result(self, output, output_type, model, usage, raw) -> InvokeResult      # line 2097
    def _raise_if_truncated(self, finish_reason, *, model) -> None                              # line 2221 (raises TruncatedResponseError/InvokeError)

# packages/ai-parrot/src/parrot/clients/budget.py (TASK-3133/3134)
class QuestionBudget:
    async def claim_finalization(self, owner_call_id: str) -> bool
    async def report(self) -> BudgetReport
    _answer_complete: bool   # instance attr initialised True (TASK-3133 blueprint)

# packages/ai-parrot/src/parrot/clients/budget_scope.py (TASK-3134/3137)
class BudgetScope: is_root: bool; owner_designated: bool; owner_call_id: Optional[str]; ledger: QuestionBudget
```

### Does NOT Exist
- ~~A second finalization attempt / retry / fallback model~~ — spec §2.3 "Admit at most one physical inference attempt … automatic retries and fallback are disabled for it"; do not route the final attempt through `_should_use_fallback`.
- ~~Executing a `toolUse` returned by the final attempt~~ — forbidden (spec §2.3 table row 3).
- ~~`AIMessage.stop_reason` left as the provider value on forced termination~~ — spec §2.3: `stop_reason="budget_exhausted"`, provider value kept in `finish_reason`.
- ~~`QuestionBudget.set_answer_complete`~~ — added in this task (tiny lock-guarded setter).
- ~~`InvokeResult.metadata`~~ — use `budget_report` (TASK-3132).

---

## Implementation Notes

### Pattern to Follow
```python
# ask()/resume() round site (after TASK-3140 wrapped it)
try:
    async with self._budgeted_attempt(payload, route="converse", stream=False, call_id=_bq_call_id, round_number=_lc_round_number + 1, attempt_number=1) as _h:
        result = await self._sdk_create(payload, handle=_h)
        await _h.settle(result.get("usage"))
except BudgetExhausted as _bx:
    result = await self._finalize_budgeted(payload, bedrock_messages=bedrock_messages, content_blocks=content_blocks,
                                           all_tool_calls=all_tool_calls, call_id=_bq_call_id, round_number=_lc_round_number + 1,
                                           resolved_model=resolved_model, partial_text=_partial_text(bedrock_messages))
    _budget_forced = True
    content_blocks = result.get("output", {}).get("message", {}).get("content", [])
    bedrock_messages.append({"role": "assistant", "content": content_blocks})
    break
```

### Key Constraints
- Owner check: `scope = current_budget_scope()`; owner iff `scope.is_root and scope.owner_designated`
  **or** (direct client root: `scope.is_root and not scope.owner_designated` — "A direct client
  root is its own answer owner", spec §2.1 — designate it now with `scope.designate_owner(call_id)`).
  A child scope → re-raise the `BudgetExhausted` untouched.
- `claim_finalization(scope.owner_call_id)` returning `False` → raise `BudgetExhausted` (already claimed / in-flight).
- Frame: `{"payload": payload, "completed_tool_calls": [tc for tc in all_tool_calls if tc.error is None and tc.result is not None], "pending_tool_calls": [...toolUse in content_blocks not yet executed...], "answer_text": partial}`
  → `adapter.prepare_finalization(frame)`; count/reserve the **transformed** payload (spec §2.3
  "Count this transformed final payload") — `_budgeted_attempt(final_payload, phase="final")`
  does that.
- Final attempt exception handling: pre-dispatch failure → `release()`; post-dispatch → `uncertain`;
  either way return partial (raise `BudgetExhausted` with `partial_text`) — no retry.
- `partial_text`: concatenation of all `"text"` blocks from assistant turns already in
  `bedrock_messages` plus `answer_text` if any.
- Report attachment happens for **every** budgeted call (forced or not), so successful budgeted
  answers also carry `metadata["token_budget"]` (AC "parent report includes every debit").
- `ask_stream` cancellation: `except asyncio.CancelledError: raise` before the `BudgetExhausted`
  handler → never start finalization on cancel (spec §2.3 table row 4).
- `invoke`: the `BudgetExhausted` from a work reservation in `invoke` has no tool frame → owner
  finalization still applies (single-shot call: frame = payload without tools); if it cannot fit,
  return `InvokeResult(output=raw_text_or_empty, output_type=None, model=..., usage=CompletionUsage(), raw_response=None, budget_report=report)`
  rather than raising (spec §2.3 "`InvokeResult` gains an optional `budget_report` … A
  budget-truncated or invalid structured result returns raw partial text, `output_type=None`").

### References in Codebase
- `bedrock.py:1030-1060` — structured-output parse block in `ask()` (`_raise_if_truncated` → parser).
- `bedrock.py:1230-1372` — stream loop + tail.
- `packages/ai-parrot-client-amazon/tests/unit/test_bedrock_multiround_usage.py` — `_tool_round` / `_final_round` fixture helpers to reuse.

---

## Implementation Blueprint

### Steps (in order)
1. Add `QuestionBudget.set_answer_complete` — *why*: the report must be truthful about provider cutoff/tool-call-in-final (spec §2.3 flags).
2. Implement `_finalize_budgeted` once — *why*: `ask`/`resume`/`invoke` share the same owner/claim/frame/one-attempt logic.
3. Wire `ask` and `resume` round sites + report attachment + `stop_reason` + structured bypass.
4. Wire `ask_stream` (streamed finalization + single sentinel) with the cancel guard.
5. Wire `invoke` (`BudgetError` re-raise before `_handle_invoke_error`; `budget_report`).
6. Tests.

### `packages/ai-parrot/src/parrot/clients/budget.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3134: grep -c '    def restore_settled(' packages/ai-parrot/src/parrot/clients/budget.py)
# BEFORE — insert above `    def restore_settled(`
    async def set_answer_complete(self, value: bool) -> None:
        """Record whether the terminal answer is complete (provider cutoff, parse failure, final tool call → False)."""
        async with self._lock:
            self._answer_complete = bool(value)
            self._revision += 1
```
**Why**: `answer_complete` is a report flag (spec §2.3) whose truth is known only by the provider loop.

### `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py` (MODIFY — shared finalizer)
```python
# occurrences: 1 (verified after TASK-3140: grep -c '    async def _budgeted_attempt(' packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py)
# BEFORE — insert above `    async def _budgeted_attempt(`
    async def _finalize_budgeted(
        self, payload: Dict[str, Any], *, bedrock_messages: List[Dict[str, Any]], content_blocks: List[Dict[str, Any]],
        all_tool_calls: List[ToolCall], call_id: str, round_number: int, resolved_model: str, partial_text: str, stream: bool = False,
    ) -> Any:
        """Owner-only, one tools-disabled final attempt inside A_final (spec §2.3); raises BudgetExhausted with partial_text otherwise.

        Returns the Converse ``result`` dict (non-stream) or the stream iterator plus its handle (stream=True).
        """
        scope = current_budget_scope()
        if scope is None or not scope.is_root:
            raise BudgetExhausted("child scope exhausted", report={"partial_text": partial_text})  # owner handles it
        if not scope.owner_designated:
            scope.designate_owner(call_id)  # direct client root is its own owner (spec §2.1)
        ledger = scope.ledger
        if not await ledger.claim_finalization(scope.owner_call_id):
            raise BudgetExhausted("finalization already claimed or in-flight", operation_id=ledger.operation_id,
                                  report={**(await ledger.report()).model_dump(), "partial_text": partial_text})
        frame = {
            "payload": payload,
            "completed_tool_calls": [tc.model_dump() if hasattr(tc, "model_dump") else vars(tc) for tc in all_tool_calls if getattr(tc, "error", None) is None],
            "pending_tool_calls": [b["toolUse"] for b in content_blocks if isinstance(b, dict) and "toolUse" in b],
            "answer_text": partial_text,
        }
        final_payload = self._get_budget_adapter().prepare_finalization(frame)
        try:
            async with self._budgeted_attempt(final_payload, route="converse", stream=stream, call_id=call_id,
                                              round_number=round_number, attempt_number=1, phase="final") as _h:
                # FILL IN: non-stream -> result = await self._sdk_create(final_payload, handle=_h); await _h.settle(result.get("usage")); return result
                #          stream -> return (await self._sdk_stream(final_payload, handle=_h), _h)  — caller settles at metadata.
                #          Post-dispatch exception -> _h.uncertain("final_dispatch_failed") then raise BudgetExhausted(partial). No retry, no fallback.
                #          Bounded by spec §2.3 table rows 1-3.
                raise NotImplementedError
        except BudgetExhausted as bx:
            bx.report = {**(bx.report or {}), "partial_text": partial_text}
            raise
```
**Why this shape**: centralises the §2.3 decision table; the `stream` flag lets `ask_stream` reuse it without duplicating claim/frame logic.

### `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py` (MODIFY — loops, tail, invoke)
```python
# FILL IN: ask() and resume() — apply the "Pattern to Follow" at their round sites (wrapped by TASK-3140). Initialise `_budget_forced = False`
#          before each loop. After `ai_message = AIMessageFactory.from_bedrock(...)` in BOTH methods insert:
        _bq_scope = current_budget_scope()
        if _bq_scope is not None:
            if _budget_forced:
                ai_message.stop_reason = "budget_exhausted"  # provider value stays in finish_reason (spec §2.3)
                if result.get("stopReason") in ("tool_use", "max_tokens"):
                    await _bq_scope.ledger.set_answer_complete(False)
            ai_message.metadata["token_budget"] = (await _bq_scope.ledger.report()).model_dump()
# Structured output in ask(): guard the `self._raise_if_truncated(...)` call with `if not _budget_forced:` and, when `_budget_forced`, skip
#          custom_parser entirely (final_output = assistant_response_text; set_answer_complete(False) if output_config). Bounded by spec §2.3
#          "must not reach a custom parser as if it were validated".
```
```python
# occurrences: 1 (verified: grep -c '        yield _lc_stream_msg' packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py)
# FILL IN: ask_stream() — inside the round loop add `except asyncio.CancelledError: raise` then `except BudgetExhausted as _bx:` which calls
#          `_finalize_budgeted(..., stream=True)`, iterates the returned final stream yielding text chunks (append to accumulated_text),
#          settles at its metadata event, sets `stop_reason` from messageStop, `_budget_forced = True`, and `break`s. Before `yield _lc_stream_msg`
#          attach the report / stop_reason exactly as in ask(). Exactly ONE terminal AIMessage is yielded. Bounded by spec §2.4 sentinel rule.
```
```python
# occurrences: 1 (verified: grep -c '            return self._build_invoke_result(output, output_type, resolved_model, usage, result)' packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py)
# FILL IN: invoke() — wrap its single _sdk_create (TASK-3140) in `except BudgetExhausted as _bx:` -> try `_finalize_budgeted(...)` with
#          all_tool_calls=[] ; on success parse as usual but never call custom_parser when forced; on failure return
#          InvokeResult(output=partial, output_type=None, model=resolved_model, usage=CompletionUsage(), raw_response=None, budget_report=report).
#          Replace `return self._build_invoke_result(...)` with a version that sets `.budget_report` when a scope is live.
#          Add `except BudgetError: raise` immediately before `except Exception as exc: raise self._handle_invoke_error(exc)`.
#          Bounded by spec §2.3 InvokeResult paragraph and §3 M3 "InvokeError wrapping".
```
**Why**: the final attempt must never be retried or executed as a tool round; `stop_reason`/report attachment is the single truthful surface for callers.

### `packages/ai-parrot-client-amazon/tests/unit/test_token_budget_bedrock.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3140: grep -c 'class TestAttemptHooks' packages/ai-parrot-client-amazon/tests/unit/test_token_budget_bedrock.py)
# AFTER — append at end of file
class TestFinalization:
    async def test_one_tools_disabled_attempt_within_a_final(self):
        # FILL IN: budget 10_000; _sdk_create side_effect: tool round (2000/500), tool round (3000/700), then FINAL (assert payload has no toolConfig
        #          and maxTokens <= 600); ask(...) returns stop_reason "budget_exhausted", metadata token_budget finalization_attempted True,
        #          finalized True, exactly 3 SDK calls. Bounded by spec §2.3 example.
        raise NotImplementedError

    async def test_zero_reserve_and_oversized_input_skip_inference(self):
        # FILL IN: final_answer_reserve=0 -> BudgetExhausted raised to the caller (direct client) with partial_text and 2 SDK calls only;
        #          with reserve but adapter.count_input patched to return 4000 for the final -> same. Bounded by spec §2.3 table row 2.
        raise NotImplementedError

    async def test_final_tool_call_not_executed_and_no_fallback(self):
        # FILL IN: final result stopReason tool_use -> no _execute_tool call, answer_complete False; capacity error on final -> no second attempt.
        raise NotImplementedError


class TestStreamingFinalization:
    async def test_finalization_chunks_in_stream_and_single_sentinel(self):
        # FILL IN: fake streams: round1 tool_use, then exhaustion, then final stream yielding "fin"; collected == [..., "fin", AIMessage]; exactly one AIMessage.
        raise NotImplementedError

    async def test_cancellation_never_finalizes(self):
        # FILL IN: cancel the consuming task mid-round; assert no phase="final" reservation and the reservation is uncertain/settled. Bounded by spec §2.3 row 4.
        raise NotImplementedError


class TestStructuredResult:
    async def test_budget_cutoff_never_reaches_custom_parser(self):
        # FILL IN: structured_output with custom_parser mock; forced finalization result truncated -> parser not called, output is raw text,
        #          report.answer_complete False. Bounded by spec §2.3.
        raise NotImplementedError

    async def test_invoke_result_carries_budget_report(self):
        # FILL IN: invoke(..., token_budget=N) -> InvokeResult.budget_report is a dict with "operation_id". Bounded by spec §2.3.
        raise NotImplementedError
```
**Why**: spec §4 rows "Finalization", "Streaming" (finalization / sentinel / cancellation), "Structured result".

### FILL IN checklist
- [ ] `bedrock.py::_finalize_budgeted` attempt body (stream vs non-stream, exception mapping); bounded by spec §2.3 table
- [ ] `ask`/`resume` round-site wiring + report/stop_reason/structured bypass; bounded by spec §2.3
- [ ] `ask_stream` finalization + cancel guard + single sentinel; bounded by spec §2.4
- [ ] `invoke` guard + `budget_report`; bounded by spec §2.3 / §3 M3
- [ ] all test bodies

---

## Acceptance Criteria

- [ ] Spec §2.3 example reproduces end-to-end on `ask()`: exactly three SDK calls, final payload without `toolConfig`, `maxTokens ≤ 600`
- [ ] Reserve zero or oversized final input → no closing inference; partial text propagated in `BudgetExhausted.report["partial_text"]`
- [ ] A `toolUse` in the final result is never executed; capacity error on the final never triggers fallback or a second attempt
- [ ] Every budgeted `AIMessage` carries `metadata["token_budget"]`; forced termination sets `stop_reason="budget_exhausted"` and keeps `finish_reason`
- [ ] `ask_stream` streams finalization text in-band and yields exactly one terminal `AIMessage`; cancellation never starts finalization
- [ ] Budget-truncated structured output never reaches `custom_parser`; `InvokeResult.budget_report` populated; `BudgetError` escapes `invoke()` untouched by `_handle_invoke_error`
- [ ] Child scope → `BudgetExhausted` re-raised (no finalization in the child)
- [ ] `pytest packages/ai-parrot-client-amazon/tests/unit -q` passes

---

## Test Specification

Scaffold above. Add `test_child_scope_reraises_without_finalizing` (enter a root scope, derive `.child()`, run `ask` inside it → `BudgetExhausted`, zero `phase="final"` reservations).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2.3 (entire), §2.4 streaming paragraph, §3 Module 4
2. **Check dependencies** — TASK-3140 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `_budgeted_attempt`, `_AttemptHandle`, `prepare_finalization` exist as TASK-3139/3140 declared
4. **Update status** in `sdd/tasks/index/token-budget-bedrock.json` → `"in-progress"`
5. **Implement** from the Blueprint
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3141-bedrock-finalization-loops.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
