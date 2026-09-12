# TASK-3189: Emit terminal attempt telemetry once, on every exit path

**Feature**: FEAT-554 — Empirical Token-Budget Sizing for sdd-coder Bedrock Seats
**Spec**: `sdd/specs/sdd-coder-bedrock-token-telemetry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3188
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (second file) and the resolution of §10 R3/R4. Today usage
reaches `AttemptTelemetryCollector` only through `DispatchCompleted`, so:

- rich fields (per-turn series, budget report, resolved model) cannot travel at
  all — `action_from_dispatch_event` whitelists seven scalars and the failure is
  swallowed (`dispatchers/_shared.py:118-124`);
- a **failed** attempt reports nothing: `dispatch.failed` payloads carry
  `error_class`/`error_message` only (`dispatchers/llm.py:184, 208, 220`), so
  every token burned before the failure is lost — and failed attempts are the
  degenerate tail this feature exists to measure.

The loop already has a single terminal choke point covering success, failure and
salvage: the `finally:` at `dispatchers/llm.py:574`, where `accumulated`,
`model` and `loop_t0` are all still in scope. Emitting there gives
exactly-once-on-every-path for free.

---

## Scope

- Accumulate a per-turn `TurnUsage` series and an unknown-usage counter inside
  the turn loop.
- Add `_emit_attempt_telemetry(...)`, which reads the bound session host from
  `_SESSION_HOST_CTX` and calls its optional `on_attempt_telemetry` method.
- Call it from the loop's existing `finally:` block — once, on every path.
- Write tests for the three terminal kinds and for failure isolation.

**NOT in scope**: binding the budget scope or populating `budget_report`
(TASK-3190 does that and passes it in), the collector's receiving side
(TASK-3193), row persistence (TASK-3191).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | Series accumulation + `_emit_attempt_telemetry` + the `finally` call |
| `packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py` | MODIFY | Terminal-telemetry tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models.telemetry import (  # created by TASK-3188
    MAX_TURN_SERIES,
    AttemptTelemetry,
    TurnUsage,
)
from parrot.flows.dev_loop.dispatchers._shared import _SESSION_HOST_CTX          # verified: parrot/flows/dev_loop/dispatchers/_shared.py:64
from parrot.models.basic import CompletionUsage                                  # verified: parrot/flows/dev_loop/dispatchers/llm.py:44
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
async def dispatch(self, ...)                                          # line 113
    client = self._create_client(profile, run_id=run_id)               # line 272
    model = self._resolve_model(profile, client)                       # line 274
    accumulated: Optional[CompletionUsage] = None  # LOCAL, never self.*  # line 294
    try:                                                               # line 306
        for turn_index in range(profile.max_turns):                    # line 307
            usage, raw_usage = self._extract_usage(response)           # line 331
            if usage is not None:                                      # line 332
                accumulated = usage if accumulated is None else accumulated + usage  # line 333
        ...
        salvaged, salvage_usage, salvage_error = await self._salvage_final_output(...)  # line 552
    finally:                                                           # line 574
        await self._safe_emit_after_call(                              # line 575
            client, tc, model=model,
            duration_ms=(time.perf_counter() - loop_t0) * 1000,
            input_tokens=accumulated.prompt_tokens if accumulated else None,   # line 580
            output_tokens=accumulated.completion_tokens if accumulated else None,
        )

@staticmethod
def _resolve_model(profile, client) -> str: ...                         # line 879
#   LLMFactory.parse_llm_string then client.model / default_model / _default_model
#   → CAN differ from RosterSeat.model (spec §9 S9)

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py
_SESSION_HOST_CTX: ContextVar[Optional[SessionHost]] = ContextVar(...)  # line 64
def _apply_to_session_host(event: DispatchEvent) -> None: ...           # line 92
    #   every exception swallowed and logged at DEBUG                   # lines 118-124
```

### Does NOT Exist
- ~~`SessionHost.on_attempt_telemetry`~~ — no host implements it yet; TASK-3193 adds it to
  `AttemptTelemetryCollector`. Guard with `getattr(host, "on_attempt_telemetry", None)`
  so every existing host (and every test double) stays unaffected.
- ~~`DispatchEvent` kind `dispatch.telemetry`~~ — do NOT add an event kind; a new kind
  would have to be threaded through the session-state projection, the CLI renderer and
  both consoles to earn its keep, and it would hit the same whitelist that motivated
  this task.
- ~~`self._accumulated` / any instance attribute for usage~~ — `accumulated` is
  deliberately LOCAL (see the comment at `llm.py:294`); keep the series local too.
- ~~`typing.List` needing a new import in `llm.py`~~ — `List`/`Optional`/`Dict` are already
  imported there; verify with `grep -n '^from typing' packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py`.
- ~~`CompletionUsage.prompt_tokens` being always set~~ — `accumulated` is `None` when no
  round reported usage; every read must guard, exactly as line 580 does.

---

## Implementation Notes

### Key Constraints
- **Exactly once, every path.** Emit from the `finally:` at line 574 and nowhere
  else. Do not also emit at the three `dispatch.completed` / three
  `dispatch.failed` publish sites — that would double count and reintroduce the
  whitelist problem.
- **Never raise.** Wrap the hook call in `try/except Exception`, log at DEBUG,
  mirroring `_apply_to_session_host`'s discipline (`_shared.py:118-124`).
  Telemetry must not turn a successful dispatch into a failed one.
- A turn with no reported usage appends `TurnUsage(round_number=n)` with both
  tokens `None` **and** increments the unknown counter. Do not skip the turn:
  the gap is the data.
- `terminal` is `"salvaged"` when the salvage path produced the result,
  `"failed"` when the block is leaving by exception, `"completed"` otherwise.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py:92-124` —
  the swallow-and-log shim pattern to copy verbatim.
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:333` — where
  per-round usage is already computed; the series is appended alongside it.

---

## Implementation Blueprint

### Steps (in order)
1. Declare the series locals next to `accumulated` — *why*: same lifetime, same "LOCAL, never self.*" rule the existing comment states, and the `finally` block needs them in scope.
2. Append one `TurnUsage` per round right after the existing accumulation — *why*: that is the only place the round's usage and its index are both known.
3. Add `_emit_attempt_telemetry` as a method near `_completion_usage_payload` — *why*: it belongs with the other telemetry-shaping helpers, not in the middle of the loop.
4. Call it from the existing `finally:` block, before `_safe_emit_after_call` — *why*: one choke point that already runs on success, failure and salvage (spec §10 R4); putting it first means a hook failure cannot skip the existing after-call event.
5. Add the tests — *why*: AC-6 (failed attempts carry partial usage) cannot be verified by reading.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` (MODIFY — locals)
```python
# occurrences: 1 (verified: grep -c '            accumulated: Optional[CompletionUsage] = None  # LOCAL, never self.*' packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py)
# AFTER — insert below `            accumulated: Optional[CompletionUsage] = None  # LOCAL, never self.*` (verified: packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:294)
            turn_series: List[TurnUsage] = []  # LOCAL, same rule as `accumulated`
            turns_with_unknown_usage = 0
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` (MODIFY — per-round append)
```python
# occurrences: 1 (verified: grep -c '                        accumulated = usage if accumulated is None else accumulated + usage' packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py)
# AFTER — insert below `                        accumulated = usage if accumulated is None else accumulated + usage` (verified: packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:333)
                    # Record EVERY turn, including one the provider reported no
                    # usage for: the `if usage is not None` guard above keeps the
                    # subtotal honest but hides the gap, so a non-null aggregate
                    # alone cannot prove complete reporting (spec §10 R5).
                    if len(turn_series) < MAX_TURN_SERIES:
                        turn_series.append(
                            TurnUsage(
                                round_number=turn_index + 1,
                                input_tokens=usage.prompt_tokens if usage is not None else None,
                                output_tokens=usage.completion_tokens if usage is not None else None,
                            )
                        )
                    if usage is None:
                        turns_with_unknown_usage += 1
```
**Why**: Appending here rather than in the `finally` is what makes a per-turn series possible at all — the `finally` sees only the aggregate. The length guard keeps the model's `max_length=MAX_TURN_SERIES` from raising mid-dispatch; it can only trigger if `max_turns` is ever raised above 100.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` (MODIFY — helper)
```python
# occurrences: 1 (verified: grep -c '    def _completion_usage_payload(' packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py)
# BEFORE — insert above `    def _completion_usage_payload(` (verified: packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:585)
    def _emit_attempt_telemetry(self, telemetry: AttemptTelemetry) -> None:
        """Hand terminal telemetry to the bound session host, at most once.

        Reads the host from `_SESSION_HOST_CTX` (verified:
        parrot/flows/dev_loop/dispatchers/_shared.py:64) and calls its OPTIONAL
        `on_attempt_telemetry`; a host without that method is a no-op, so every
        pre-FEAT-554 host and test double is unaffected.

        Deliberately not a `DispatchEvent`: `action_from_dispatch_event` copies
        only seven whitelisted `usage` scalars into the closed
        `DispatchCompleted` model and `_apply_to_session_host` swallows the
        validation error, so a payload key would vanish in silence (spec §10 R3).

        Every failure is swallowed and logged at DEBUG — telemetry must never
        change a dispatch result.
        """
        try:
            host = _SESSION_HOST_CTX.get()
            hook = getattr(host, "on_attempt_telemetry", None) if host is not None else None
            if hook is not None:
                hook(telemetry)
        except Exception:  # noqa: BLE001 - telemetry must never break a dispatch
            self.logger.debug("attempt telemetry hook failed", exc_info=True)
```
**Why**: The `getattr` guard is what makes this additive rather than a protocol change — `session_host` is duck-typed and several hosts exist. The bare `except Exception` is intentional and matches `_apply_to_session_host`'s documented rule ("the shim must never break a dispatch").

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` (MODIFY — the choke point)
```python
# occurrences: 1 (verified: grep -c '                await self._safe_emit_after_call(' packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py)
# BEFORE — insert above `                await self._safe_emit_after_call(` inside the loop's `finally:` (verified: packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:575)
                # ONE terminal emission per attempt, on every path: this
                # `finally` already covers clean completion, salvage and an
                # escaping exception, so `dispatch.failed`'s usage-less payload
                # (llm.py:184/208/220) stops losing a failed attempt's tokens
                # (spec §10 R4).
                self._emit_attempt_telemetry(
                    AttemptTelemetry(
                        resolved_model=model,
                        turns=len(turn_series),
                        # FILL IN: terminal — "salvaged" when the salvage path
                        # produced the result, "failed" when this block is
                        # leaving by exception, else "completed"; and
                        # error_class = type(exc).__name__ for the failure case.
                        # Bounded by: derive it from state already in scope
                        # (sys.exc_info() or a flag set on the salvage/except
                        # paths) — do NOT add a new instance attribute (AC-6).
                        provider_input_tokens=accumulated.prompt_tokens if accumulated else None,
                        provider_output_tokens=accumulated.completion_tokens if accumulated else None,
                        turn_series=turn_series,
                        turns_with_unknown_usage=turns_with_unknown_usage,
                    )
                )
```
**Why**: Placed before `_safe_emit_after_call` so that if the hook ever does raise past its own guard, the pre-existing event still fires. `turns` is `len(turn_series)` rather than `turn_index + 1` because the series counts what actually ran, including the salvage turn if it appended one.

### FILL IN checklist
- [ ] `llm.py::dispatch` finally block — resolve `terminal` and `error_class` from state already in scope; bounded by "no new instance attribute, correct for completed/failed/salvaged" (AC-6)
- [ ] `test_llm_code_dispatcher.py` — the four test bodies below

---

## Acceptance Criteria

- [ ] A clean multi-turn dispatch emits exactly ONE `AttemptTelemetry` with `terminal="completed"`, `turns == rounds actually run`, and a `turn_series` of that length.
- [ ] A dispatch that raises mid-loop still emits exactly ONE telemetry, with `terminal="failed"`, `error_class` set, and the tokens accumulated before the failure — not zero.
- [ ] A dispatch that exhausts `max_turns` and recovers via salvage emits `terminal="salvaged"`.
- [ ] A round whose response reports no usage appends `TurnUsage(round_number=n, input_tokens=None, output_tokens=None)` and increments `turns_with_unknown_usage`.
- [ ] A session host WITHOUT `on_attempt_telemetry` is unaffected (no exception, dispatch result unchanged).
- [ ] A hook that raises does not propagate and does not change the dispatch result.
- [ ] `resolved_model` is `_resolve_model(...)`'s value, not the profile's raw `llm` string.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py  (append)
import pytest


class _CapturingHost:
    """Duck-typed session host that records terminal telemetry."""

    def __init__(self) -> None:
        self.telemetry: list = []

    def apply(self, action, origin=None) -> None:  # the existing SessionHost duck type
        pass

    def on_attempt_telemetry(self, telemetry) -> None:
        self.telemetry.append(telemetry)


class TestTerminalTelemetry:
    async def test_clean_dispatch_emits_once(self):
        # FILL IN: drive dispatch() with the module's existing fake client over
        # N turns; assert len(host.telemetry) == 1 and terminal == "completed"
        raise NotImplementedError

    async def test_failed_dispatch_carries_partial_usage(self):
        # FILL IN: fake client raising on turn 3 after two usage-reporting
        # rounds; assert one telemetry, terminal == "failed", error_class set,
        # provider_input_tokens > 0 — bounded by AC-6 (spec §10 R4)
        raise NotImplementedError

    async def test_missing_round_usage_is_a_gap_not_a_zero(self):
        # FILL IN: one round whose response has usage=None; assert the series
        # entry is (n, None, None) and turns_with_unknown_usage == 1
        raise NotImplementedError

    async def test_host_without_hook_is_unaffected(self):
        # FILL IN: pass a host with only `apply`; assert no exception and the
        # dispatch result is unchanged
        raise NotImplementedError
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 Overview corrections 1 and 3, §3 Module 2, §10 R3/R4.
2. **Check dependencies** — TASK-3188 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-confirm lines 294, 333, 574-581 before editing; if the loop has moved, update the anchors first.
4. **Update status** in `sdd/tasks/index/sdd-coder-bedrock-token-telemetry.json` → `"in-progress"`.
5. **Implement** from the blueprint; emit from the `finally` and nowhere else.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3189-terminal-telemetry-emission.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-coder (gemini seat) via parrot-sdd-coder orchestrator; two production/test bugs repaired and merge verified by sdd-worker
**Date**: 2026-09-12
**Notes**: Wired exactly-once terminal `AttemptTelemetry` emission into
`LLMCodeDispatcher._dispatch_loop` on every exit path (completed/failed/
salvaged), with turn-series accumulation and `turns_with_unknown_usage`
tracking, via the optional `on_attempt_telemetry` hook read off
`_SESSION_HOST_CTX`. During verification two bugs surfaced and were fixed
by sdd-worker, both confined to this task's own two files:
1. **Production bug**: the `finally` block referenced the local `salvaged`
   unconditionally to pick the terminal state, but `salvaged` is only
   assigned inside the post-loop salvage branch — the ordinary
   normal-completion `return` inside the `for` loop never reaches it, so
   every non-salvage dispatch raised `UnboundLocalError`. Fixed by
   initializing `salvaged = None` alongside the other loop locals.
2. **Test bug**: 3 of the 4 `TestTerminalTelemetry` tests pre-bound
   `_SESSION_HOST_CTX` directly via `.set()` and expected it to survive
   into `dispatch()`, but `dispatch()` always overwrites the ContextVar
   from its own `session_host` kwarg (default `None`) — production
   callers (`agent_pool.py:337`) pass `session_host=` to `dispatch()`
   instead. Fixed the 3 tests to do the same.

All 66 tests in `test_llm_code_dispatcher.py` pass; `ruff check` clean.

**Deviations from spec**: none (production + test fixups, see note above)

Seat: gemini · Backend: google-compat · Model: gemini-3.5-flash · Attempts: 1 · Duration: 89.2s · Tokens: 1995755/6680
