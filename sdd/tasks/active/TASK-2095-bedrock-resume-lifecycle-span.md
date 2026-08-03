# TASK-2095: Add lifecycle span + per-round instrumentation to BedrockConverseBase.resume()

**Feature**: FEAT-404 — Bedrock/Nova Per-Round Token Usage Observability
**Spec**: `sdd/specs/bedrock-per-round-token.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2094
**Assigned-to**: unassigned

---

## Context

`BedrockConverseBase.resume()` (`bedrock.py:1000-1128`) carries **no lifecycle
instrumentation at all** — no `BeforeClientCallEvent`/`AfterClientCallEvent`
span, no round events, no usage accumulation (finding F010). Spec decision U2
pulled `resume()` into scope (completeness over parity) and U4 (user-confirmed)
resolved the span design: **full call-level lifecycle span**, not orphan round
events on a local `TraceContext.new_root()`. This task implements **Module 2**
of the spec (§3). It depends on TASK-2094 because the four-part idiom and the
cache-counter fix-up land there first and are replicated here in the same file.

---

## Scope

- Establish the call-level span in `resume()`:
  - After model resolution (`resolved_model`, line 1031) and tool prep
    (line 1056-1058): `_lc_tc = self._emit_before_call(client_name=self.client_name,
    model=resolved_model, temperature=self.temperature, system_prompt=None,
    has_tools=bool(tool_specs), parent_trace=None)` and
    `_lc_t0 = time.perf_counter()`.
  - Before returning: `await self._emit_after_call(_lc_tc,
    client_name=self.client_name, model=resolved_model,
    duration_ms=(time.perf_counter() - _lc_t0) * 1000, input_tokens=...,
    output_tokens=..., finish_reason=...)` — mirror `ask()`'s call at
    `bedrock.py:853-861`, reading tokens off the (accumulated) message usage.
- Apply the same four-part idiom as TASK-2094 to the `while True` loop at
  1063-1119: init accumulator, per-round timing around `_sdk_create`
  (line 1064), accumulate via `CompletionUsage.from_bedrock` + `__add__` with
  the explicit cache-counter re-sum (U1), per-round tool names from the block
  loop (1071-1112), `_emit_round_event` at the end of the
  `stopReason == "tool_use"` branch (before the appends at 1114-1116).
- After `AIMessageFactory.from_bedrock` (1121-1128): capture the returned
  message into a local, override its `.usage` with the accumulated total,
  stamp `extra_usage["rounds"]` only when rounds > 1, then emit after-call
  and return it.
- Document the **deliberate asymmetry** in the `resume()` docstring: Bedrock/
  Nova `resume()` reports rounds and a call span while the five FEAT-397
  reference clients' `resume()` does not (U2 — accepted; do not "fix" by
  removal; closing it elsewhere is a follow-up).

**NOT in scope**: `ask()` (TASK-2094), `ask_stream()`/`invoke()` (spec
non-goals), fallback handling (**`resume()` has no fallback branch** — do not
add one), changes to any other file. Tests (TASK-2096).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/bedrock.py` | MODIFY | span + four-part idiom in `resume()`; docstring asymmetry note |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 2026-08-03 (spec §6 re-verified same day).
> Line numbers below are PRE-TASK-2094; that task edits `ask()` (578-862),
> which sits ABOVE `resume()` in the file — expect `resume()` lines to have
> shifted by the size of TASK-2094's insertions. Re-verify before editing.

### Verified Imports

```python
# Already imported in bedrock.py: time (line 36), uuid (line 37)
from parrot.models.basic import CompletionUsage
# _emit_before_call / _emit_round_event / _emit_after_call inherited from
# AbstractClient — call via self, no import.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/bedrock.py
class BedrockConverseBase:
    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage:  # line 1000
        # bedrock_messages = list(state["messages"])                    line 1029 (copy-not-alias — KEEP)
        # resolved_model = self._translate_model(...)                   lines 1031-1033
        # payload build                                                 lines 1048-1055
        # tool_specs = self._prepare_tools()                            lines 1056-1058
        # while True: result = await self._sdk_create(payload)          lines 1063-1064
        #     tool_use branch, block loop                               lines 1068-1112
        #     appends + continue                                        lines 1114-1116
        #     else: break                                               lines 1117-1119
        # return AIMessageFactory.from_bedrock(...)                     lines 1121-1128  ← becomes local + usage override
        # NO _emit_before_call / _lc_tc / _lc_t0 anywhere in resume() today
        # NO fallback branch in this loop (unlike ask())

# packages/ai-parrot/src/parrot/clients/base.py (inherited)
def _emit_before_call(self, *, client_name, model, temperature=None,
    system_prompt=None, has_tools=False, parent_trace=None) -> TraceContext:  # line 431, SYNC
def _emit_round_event(self, tc, *, client_name, model, round_number,
    usage, raw_usage, tool_calls, duration_ms) -> None:  # line 488, SYNC
async def _emit_after_call(self, tc, *, client_name, model, ...) -> None:  # line 564, ASYNC — must await

# The after-call shape to mirror — packages/ai-parrot/src/parrot/clients/bedrock.py:852-861 (inside ask()):
#   _lc_usage = ai_message.usage
#   await self._emit_after_call(_lc_tc, client_name=self.client_name, model=resolved_model,
#       duration_ms=(time.perf_counter() - _lc_t0) * 1000,
#       input_tokens=getattr(_lc_usage, 'input_tokens', None) if _lc_usage else None,
#       output_tokens=getattr(_lc_usage, 'output_tokens', None) if _lc_usage else None,
#       finish_reason=ai_message.stop_reason)
```

### Does NOT Exist

- ~~Any lifecycle instrumentation in `resume()`~~ — `_emit_before_call`/
  `_lc_tc`/`_lc_t0` appear ONLY inside `ask()` (pre-change lines 659, 667,
  854, 857). This task creates it for `resume()`.
- ~~A fallback-retry branch in `resume()`'s loop~~ — only `ask()` has one.
- ~~`TraceContext.new_root()` for round events here~~ — U4 explicitly rejected
  the orphan-trace option; the span comes from `_emit_before_call`.
- ~~`BedrockConverseBase._telemetry_client_name`~~ — use `self.client_name`.
- ~~A `system_prompt` in `resume()`~~ — it resumes from saved messages; pass
  `system_prompt=None` to `_emit_before_call`.

---

## Implementation Notes

### Pattern to Follow

By the time this task runs, TASK-2094's instrumented `ask()` in the SAME file
is the closest reference — copy its loop-body shape (minus the fallback
branch) and its post-factory stamp + after-call block.

### Key Constraints

- Keep the existing copy-not-alias of `state["messages"]` (line 1029, a
  FEAT-302 code-review fix) intact.
- `HumanInteractionInterrupt` re-raise path (1093-1101): the interrupt
  propagates BEFORE the round completes — do not emit a round event for an
  interrupted round; the span ends without `_emit_after_call` in that path
  (exception propagates; matching `ask()`'s behavior, which also emits no
  after-call on raise).
- Docstring asymmetry note is REQUIRED (spec §7 Known Risks) — it exists so a
  future consistency sweep doesn't delete the instrumentation.
- `_lc_` naming convention; sync/async split as listed above.

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/bedrock.py` — `ask()` post-TASK-2094 (primary reference)
- `sdd/specs/bedrock-per-round-token.spec.md` §2 (U4 rationale), §3 Module 2, §8
- `sdd/state/FEAT-404/findings/F010-resume-has-no-lifecycle-instrumentation.md`

---

## Acceptance Criteria

- [ ] `resume()` emits `BeforeClientCallEvent` and `AfterClientCallEvent`
      around the loop, with accumulated token totals on the after-call event
- [ ] One `ClientRoundEvent` per tool round inside `resume()`, none for the
      final round; `client_name == self.client_name`
- [ ] Returned `AIMessage.usage` is accumulated; `extra_usage["rounds"]`
      only when > 1; cache counters summed (U1)
- [ ] Single-round `resume()` (immediate non-tool stop): no round event, no
      `rounds` key
- [ ] Docstring documents the deliberate asymmetry vs. reference clients (U2)
- [ ] Existing suite green: `pytest packages/ai-parrot/tests/unit/clients/ -v`
- [ ] No changes outside `clients/bedrock.py`
- [ ] Lint clean: `ruff check packages/ai-parrot/src/parrot/clients/bedrock.py`

---

## Test Specification

Full suite is TASK-2096. For this task, no regression:

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/unit/clients/ -v
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/bedrock-per-round-token.spec.md` (esp. §2 U4, §3 Module 2, §6, §7)
2. **Check dependencies** — TASK-2094 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — `resume()` line numbers WILL have shifted after TASK-2094; re-locate before editing
4. **Update status** in `sdd/tasks/index/bedrock-per-round-token.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
