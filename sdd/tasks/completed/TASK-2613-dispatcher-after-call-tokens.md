# TASK-2613: Carry accumulated tokens on the dispatcher's after-call event

**Feature**: FEAT-479 — Dev-Flow / Dev-Loop Telemetry Accounting on the Lifecycle Bus
**Spec**: `sdd/specs/devflow-telemetry-accounting.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3, fixing spec §1 Finding 4. **Standalone bug fix** —
valuable on its own, independent of the rest of the feature.

`LLMCodeDispatcher._safe_emit_after_call` calls `client._emit_after_call(...)`
with `client_name`, `model` and `duration_ms` — but never `input_tokens` or
`output_tokens`, even though `_emit_after_call` accepts both. Result: the one
**awaited** (therefore exactly-delivered) LLM-call event on the dispatcher
path always reports `None` tokens.

> **⚠ This task deliberately overrides FEAT-405 R4. Read spec §3 Module 3's
> override block before starting.** R4 (`novaclient-dev-loop.brainstorm.md:107-111`)
> and the comment at `llm.py:198-200` say a summing loop here is forbidden,
> because FEAT-397 accumulates rounds inside `AbstractClient.ask()`. But this
> loop never calls `ask()` (FEAT-405's own "Gap B"), and the per-round events
> that closed Gap B use `emit_nowait` — fire-and-forget — which accounting
> cannot depend on. The override was decided 2026-08-31 and is recorded in the
> spec with its rejected alternatives.
>
> **R4's intent is preserved**: accumulate with the sanctioned
> `CompletionUsage.__add__` primitive, never a hand-rolled field-by-field sum.

---

## Scope

- Accumulate the per-round `CompletionUsage` across the turn loop in
  `_dispatch_loop`, using `CompletionUsage.__add__`.
- Extend `_safe_emit_after_call` with `input_tokens` / `output_tokens`
  parameters and forward them to `client._emit_after_call`.
- Pass the accumulated totals at the call site in the `finally` block.
- **Update the stale comment at `llm.py:198-200`** so it points at spec §3
  Module 3's override block instead of saying "forbidden".
- Write the unit test below.

**NOT in scope**: changing `_emit_round_event` or the per-round
`ClientRoundEvent` emission (it is correct — keep emitting one event per
round); changing `clients/base.py`; changing any other dispatcher.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | Accumulate + forward tokens; update comment |
| `packages/ai-parrot/tests/flows/dev_loop/test_dispatch_round_events.py` | MODIFY | Add the regression test (file already exists) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# CompletionUsage — the accumulation primitive. Verify the exact import path
# from llm.py's existing imports before adding a new one; llm.py ALREADY
# imports CompletionUsage (it is referenced in _extract_usage's return type).
# verified: packages/ai-parrot/src/parrot/models/basic.py — class CompletionUsage
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
    async def _dispatch_loop(                              # around line 170
        self, *, brief, profile, output_model, run_id: str,
        node_id: str, stream_key: str, cwd: str,
    ) -> T:
        client = self._create_client(profile)              # line 184
        model = self._resolve_model(profile, client)       # line 186
        tc = self._safe_emit_before_call(client, model=model, has_tools=bool(tools))  # line 201
        loop_t0 = time.perf_counter()                      # line 202
        try:
            for turn_index in range(profile.max_turns):    # line 204
                round_t0 = time.perf_counter()
                response = await self._chat_completion(...)  # line 206
                round_duration_ms = (time.perf_counter() - round_t0) * 1000
                ...
        finally:                                            # around line 320
            await self._safe_emit_after_call(               # line 321
                client, tc, model=model,
                duration_ms=(time.perf_counter() - loop_t0) * 1000,
            )
        # ^^^ THE BUG: no input_tokens / output_tokens passed.

    async def _safe_emit_after_call(                        # line 483
        self, client: Any, tc: Any, *, model: str, duration_ms: float
    ) -> None:
        """Call ``client._emit_after_call`` once, at the end of the dispatch."""
        if tc is None:
            return
        method = getattr(client, "_emit_after_call", None)
        if not callable(method):
            return
        await method(
            tc,
            client_name=self._client_display_name(client),
            model=model,
            duration_ms=duration_ms,
        )                                                   # ends line 495

    @staticmethod
    def _extract_usage(response) -> tuple[Optional[CompletionUsage], Optional[Dict]]:  # line 497
        """Returns (usage, raw_usage); (None, None) when the provider
        reported nothing. Never raises."""

# packages/ai-parrot/src/parrot/clients/base.py
    async def _emit_after_call(                             # line 589
        self, tc, *, client_name: str, model: str, duration_ms: float,
        input_tokens: Optional[int] = None,                 # already accepted
        output_tokens: Optional[int] = None,                # already accepted
        finish_reason: Optional[str] = None,
    ) -> None: ...
        # await self.events.emit(event)  @ line 630  <-- AWAITED, exact

# packages/ai-parrot/src/parrot/models/basic.py
class CompletionUsage:
    def __add__(self, other: Any) -> "CompletionUsage": ...  # line 273
        """Field-wise sum for multi-round tool-use accumulation."""
    # Field names are prompt_tokens / completion_tokens / total_tokens
    # (NOT input_tokens/output_tokens — see the mapping note below).

# Reference: how a real client passes tokens (clients/claude.py:733-742)
_lc_usage = getattr(ai_message, 'usage', None)
await self._emit_after_call(
    _lc_tc, client_name=..., model=model, duration_ms=...,
    input_tokens=getattr(_lc_usage, 'input_tokens', None) if _lc_usage else None,
    output_tokens=getattr(_lc_usage, 'output_tokens', None) if _lc_usage else None,
    finish_reason=getattr(ai_message, 'stop_reason', None),
)
```

### ⚠ Field-name mapping (get this right)

`CompletionUsage` uses `prompt_tokens` / `completion_tokens`, while
`_emit_after_call` takes `input_tokens` / `output_tokens`. The existing
`_emit_round_event` call site already does this mapping — copy it:

```python
# clients/base.py:566-568 (inside the ClientRoundEvent construction)
input_tokens=usage.prompt_tokens if usage is not None else None,
output_tokens=usage.completion_tokens if usage is not None else None,
```

### Does NOT Exist

- ~~`AIMessage.total_usage()` on this path~~ — it exists
  (`models/responses.py:281`) but is **unreachable here**: this loop never
  builds an `AIMessage`, which is the entire reason for Finding 4.
- ~~`CompletionUsage.input_tokens` / `.output_tokens`~~ — the fields are
  `prompt_tokens` / `completion_tokens`. Using the wrong names silently
  yields `None` via `getattr(..., None)`.
- ~~A hand-rolled `total_in += usage.prompt_tokens` sum~~ — forbidden. Use
  `CompletionUsage.__add__`; that is what makes this override acceptable.
- ~~`self._accumulated_usage` as dispatcher instance state~~ — must NOT exist.
  One dispatcher instance is shared across concurrent runs (see
  `dispatchers/_shared.py:30-45`); accumulate in a **local variable** inside
  `_dispatch_loop`, never on `self`.

---

## Implementation Notes

### Pattern to Follow

```python
        tc = self._safe_emit_before_call(...)
        loop_t0 = time.perf_counter()
        accumulated: Optional[CompletionUsage] = None   # LOCAL, never self.*
        try:
            for turn_index in range(profile.max_turns):
                ...
                usage, raw_usage = self._extract_usage(response)
                if usage is not None:
                    accumulated = usage if accumulated is None else accumulated + usage
                # existing per-round emission stays exactly as-is
                self._emit_round_event(...)
                ...
        finally:
            await self._safe_emit_after_call(
                client, tc, model=model,
                duration_ms=(time.perf_counter() - loop_t0) * 1000,
                input_tokens=accumulated.prompt_tokens if accumulated else None,
                output_tokens=accumulated.completion_tokens if accumulated else None,
            )
```

### Key Constraints

- **Never fabricate `0`.** If no round reported usage, `accumulated` stays
  `None` and both token args stay `None`. A `0` would be indistinguishable
  from a genuinely-zero call downstream.
- Accumulate in a **local**, never on `self` — the dispatcher instance is
  shared across concurrent runs.
- The `finally` must still emit when the loop raises (including the
  `max_turns` exhaustion path at `llm.py:318`), reporting the tokens burned
  before the failure. That is a spec goal, not an edge case.
- Keep `_safe_emit_after_call`'s defensive `getattr`/`callable` guards — some
  test doubles do not implement `_emit_after_call`.
- Give the two new parameters defaults of `None` so any other caller keeps
  working.

### Updating the stale comment (required)

`llm.py:198-200` currently reads, in part: *"NO accumulation here: one event
per round; summing is FEAT-397's client-layer job, not this loop's (see spec
§1 Non-Goals — a summing loop here is forbidden)."*

Replace the parenthetical with a pointer to the override, e.g.: *"Per-round
events are still one-per-round and are NOT summed for that purpose. FEAT-479
additionally accumulates a per-call total here (via `CompletionUsage.__add__`)
solely to populate the awaited `AfterClientCallEvent` — see
`sdd/specs/devflow-telemetry-accounting.spec.md` §3 Module 3 for why FEAT-405
R4 is deliberately overridden on this path."*

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/claude.py:733-742` — reference call site
- `packages/ai-parrot/src/parrot/clients/base.py:566-568` — the field-name mapping
- `packages/ai-parrot/src/parrot/models/basic.py:273` — `CompletionUsage.__add__`

---

## Acceptance Criteria

- [ ] `_safe_emit_after_call` accepts and forwards `input_tokens` / `output_tokens`.
- [ ] A multi-round dispatch emits an `AfterClientCallEvent` whose tokens equal
      the **sum** of the rounds, not the last round.
- [ ] A dispatch where no round reported usage emits `None` tokens, never `0`.
- [ ] A dispatch that raises mid-loop still emits the after-call event with the
      tokens burned so far.
- [ ] Accumulation uses `CompletionUsage.__add__`, not a hand-rolled sum.
- [ ] No accumulation state is stored on `self`.
- [ ] The `llm.py:198-200` comment is updated to reference the override.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatch_round_events.py -v` passes.
- [ ] Existing dispatcher tests still pass:
      `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_dispatch_round_events.py  (ADD)

async def test_dispatcher_after_call_carries_accumulated_tokens(...):
    """Regression guard for FEAT-479 Finding 4: _safe_emit_after_call dropped
    the token counts entirely, so the one AWAITED (exactly-delivered) event
    always reported None."""
    # Drive a 2-round dispatch reporting (1000, 500) then (2000, 700).
    # Reuse this module's existing fake-client / captured-events harness.
    after = [e for e in captured if type(e).__name__ == "AfterClientCallEvent"]
    assert len(after) == 1
    assert after[0].input_tokens == 3000     # summed, not 2000 (last round)
    assert after[0].output_tokens == 1200


async def test_after_call_tokens_none_when_unreported(...):
    """No round reported usage -> None, never a fabricated 0."""
    after = [e for e in captured if type(e).__name__ == "AfterClientCallEvent"][0]
    assert after.input_tokens is None
    assert after.output_tokens is None


async def test_after_call_emitted_with_partial_tokens_on_failure(...):
    """A loop that raises still reports what it burned."""
    with pytest.raises(Exception):
        await dispatcher._dispatch_loop(...)   # fails on round 2
    after = [e for e in captured if type(e).__name__ == "AfterClientCallEvent"][0]
    assert after.input_tokens == 1000          # round 1's tokens survive
```

**Harness note**: `test_dispatch_round_events.py` already exists and captures
`ClientRoundEvent`s from this loop (TASK-2089). Extend its existing fixtures
rather than building a new harness — and assert the round events are still
emitted one-per-round, so this change does not regress TASK-2089.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — especially §3 Module 3's override block
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — `llm.py` is a hot, actively-churning
   file; confirm the line numbers and the `finally` block before editing
4. **Update status** in `sdd/tasks/index/devflow-telemetry-accounting.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2613-dispatcher-after-call-tokens.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-08-31
**Notes**: Added a local `accumulated: Optional[CompletionUsage] = None`
variable in `_dispatch_loop`, updated once per round via
`CompletionUsage.__add__` (never a hand-rolled field sum), and forwarded
`accumulated.prompt_tokens` / `accumulated.completion_tokens` (mapped to
`input_tokens`/`output_tokens` — the existing `_emit_round_event` field-name
mapping) into the `finally` block's `_safe_emit_after_call` call. Extended
`_safe_emit_after_call`'s signature with `input_tokens`/`output_tokens`
(both `Optional[int] = None`) and forwarded them to
`client._emit_after_call`. Updated the stale `llm.py:191-200` comment to
point at spec §3 Module 3's override instead of saying "forbidden".
Extended the existing `test_dispatch_round_events.py` (did not create a new
file, per scope) with a new `_AfterCallCollector` harness and a
`TestAfterCallTokens` class covering: tokens summed across rounds (not last
round), `None` when unreported (never fabricated `0`), partial tokens
preserved when the loop raises via `max_turns` exhaustion, and a regression
guard that round events remain one-per-round (not summed) — 4 new tests,
14/14 in the file passing. `TestNoAccumulation.test_source_contains_no_summing`
(the pre-existing FEAT-405 R4 guard) still passes unmodified: my local
variable is named `accumulated`, not `_accumulated_usage`, and no
`total_usage` string appears — consistent with the task's explicit
constraint that accumulation must be a local, never `self.*`. Full
`packages/ai-parrot/tests/flows/dev_loop/` suite (excluding the 3
pre-existing unrelated failures) passes: 1111 passed, 5 skipped. `ruff
check` adds 3 new `UP045` (`Optional[X]` vs `X | None`) findings on my new
lines, matching the file's own pre-existing `Optional` convention
throughout (`_extract_usage`'s return type, etc.) — left as-is, consistent
with TASK-2612's precedent of following existing style rather than
modernizing unrelated code. No other new findings; the new test-file
additions are fully `ruff`-clean.

**Deviations from spec**: none.
