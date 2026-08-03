# TASK-2094: Instrument BedrockConverseBase.ask() with per-round usage accounting

**Feature**: FEAT-404 — Bedrock/Nova Per-Round Token Usage Observability
**Spec**: `sdd/specs/bedrock-per-round-token.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-397 shipped the four-part per-round usage idiom (init accumulator /
accumulate per round / emit `ClientRoundEvent` in the tool-use branch / stamp
accumulated total) for five clients; `BedrockConverseBase.ask()` is the
verified single remaining site whose instrumentation covers both
`BedrockConverseClient` and `NovaClient` by inheritance. This task implements
**Module 1** of the spec (§3): the `ask()` change plus the Bedrock-specific
cache-counter summing (U1). It is the core deliverable — the dev-loop's
`UsageReport` (FEAT-405) renders "—" for Bedrock seats until this lands.

---

## Scope

- Implement the four-part FEAT-397 idiom inside `BedrockConverseBase.ask()`
  (`packages/ai-parrot/src/parrot/clients/bedrock.py:578-862`), mirroring
  `AnthropicClient.ask()` (`clients/claude.py`) structurally:
  - Init `_lc_round_number = 0` / `_lc_accumulated_usage: Optional[CompletionUsage] = None`
    before the `while True` at line 738.
  - Time each loop iteration with `time.perf_counter()`; increment
    `_lc_round_number` and compute `duration_ms` after `_sdk_create` returns.
    The timer must span the try/except **including the fallback retry**
    (lines 742-749) so usage/timing attribute to the successful call — one
    round event per loop iteration.
  - Per round: `raw = result.get("usage") or None`; when present, build
    `CompletionUsage.from_bedrock(raw)` and accumulate via `+`. **Then
    explicitly re-sum `cacheReadInputTokens` and `cacheWriteInputTokens` into
    the accumulator's `extra_usage`** — `__add__` shallow-merges
    right-hand-wins, so without this the counters are last-round-only (U1).
    When `usage` is absent, leave the accumulator untouched.
  - Collect this round's tool names in the block loop (759-800); call
    `self._emit_round_event(_lc_tc, client_name=self.client_name, model=resolved_model,
    round_number=..., usage=..., raw_usage=..., tool_calls=..., duration_ms=...)`
    at the end of the `stopReason == "tool_use"` branch (after tool execution,
    before the message appends at 805-807). The final non-tool round emits
    NO round event (parity with the five reference clients).
  - After `AIMessageFactory.from_bedrock` (836-845): when the accumulator is
    non-None, replace `ai_message.usage` with it, stamping
    `extra_usage["rounds"] = _lc_round_number` **only when > 1**. Single-round
    calls must be a strict behavioral no-op.
- Update the `ask()` docstring cache note (lines 626-630) to state that
  cache counters are now summed across rounds.

**NOT in scope**: `resume()` (TASK-2095 — it needs a lifecycle span first),
`ask_stream()`/`invoke()` (spec non-goals), any change to `clients/base.py`,
`models/basic.py`, `metrics.py`, `nova/client.py`, or event schemas. Tests
beyond a smoke run (TASK-2096 owns the test suite).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/bedrock.py` | MODIFY | four-part idiom in `ask()` loop + cache-counter sum + docstring note |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 2026-08-03 (spec §6 re-verified same day).

### Verified Imports

```python
# Already imported in bedrock.py — do NOT re-import:
#   time (line 36), uuid (line 37)
from parrot.models.basic import CompletionUsage   # from_bedrock already used by invoke()
# _emit_before_call/_emit_round_event/_emit_after_call are INHERITED from
# AbstractClient (clients/base.py) — no import needed, call via self.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/bedrock.py
class BedrockConverseBase:
    async def ask(self, prompt, model=None, ...) -> AIMessage:  # line 578
        # docstring cache note to UPDATE: lines 626-630
        # _lc_tc = self._emit_before_call(client_name=self.client_name, ...)  lines 659-666  ← ALREADY EXISTS
        # _lc_t0 = time.perf_counter()                                        line 667       ← ALREADY EXISTS
        # while True:                                                         line 738
        #     result = await self._sdk_create(payload)                        line 740
        #     fallback: _should_use_fallback → second _sdk_create             lines 742-749
        #     if result.get("stopReason") == "tool_use":                      line 756
        #         per-block tool exec loop (toolUse blocks)                   lines 759-800
        #         message appends + continue                                  lines 805-807
        #     else: break                                                     lines 808-810
        # ai_message = AIMessageFactory.from_bedrock(response=result, ...)    lines 836-845
        # await self._emit_after_call(_lc_tc, ...)                            lines 853-861  ← reads ai_message.usage

# packages/ai-parrot/src/parrot/clients/base.py (inherited)
def _emit_round_event(self, tc, *, client_name, model, round_number,
    usage, raw_usage, tool_calls, duration_ms) -> None:  # line 488, SYNC
    # short-circuits when no ClientRoundEvent subscribers (lines 531-537)

# packages/ai-parrot/src/parrot/models/basic.py
@classmethod
def from_bedrock(cls, usage: Dict[str, Any]) -> "CompletionUsage":  # line 146
    # puts cacheReadInputTokens/cacheWriteInputTokens into extra_usage (161-164)
def __add__(self, other) -> "CompletionUsage":  # line 273
    # "extra_usage: shallow merge; the right-hand operand wins" (291-292)

# THE REFERENCE IMPLEMENTATION — copy this shape:
# packages/ai-parrot/src/parrot/clients/claude.py
#   init accumulator:        lines 533-535
#   round timer:             line 540; round_number++/duration: 557-558
#   accumulate-or-None:      lines 560-572
#   tool names per round:    lines 578, 634
#   emit in tool_use branch: lines 640-650
#   stamp total + rounds>1:  lines 715-722
```

### Does NOT Exist

- ~~`BedrockConverseBase._telemetry_client_name`~~ — Claude-only property
  (`claude.py:187`). Bedrock uses `self.client_name` (see lines 660, 855).
- ~~`CompletionUsage.__add__` summing `extra_usage` values~~ — it shallow-merges;
  the cache-counter sum MUST be done locally in this loop.
- ~~`from_claude` for Bedrock payloads~~ — use `CompletionUsage.from_bedrock`;
  Converse usage is camelCase (`inputTokens`/`outputTokens`).
- ~~Any existing round accounting in this method~~ — there is none; you are
  adding it.

---

## Implementation Notes

### Pattern to Follow

Copy `clients/claude.py:533-572,640-650,715-722` structurally, adapting:
`result.get("usage")` (dict, camelCase) instead of `result.get("usage")` from
`model_dump()`; `CompletionUsage.from_bedrock` instead of `from_claude`;
`self.client_name` instead of `self._telemetry_client_name`; Converse block
shape (`block["toolUse"]["name"]`) for tool names.

Cache-counter fix-up after each `+`:

```python
# __add__ shallow-merges extra_usage right-hand-wins; re-sum cache counters
# so multi-round totals honour the ask() docstring (spec §2, U1).
```

### Key Constraints

- `_emit_round_event` is sync; `_emit_after_call` is async (already awaited).
- Keep `_lc_`-prefixed local names — greppable convention across clients.
- Strict single-round no-op: no `rounds` key, and usage equals today's value.
- No behavior change when no subscriber is registered (the primitive
  short-circuits — do not add your own guard).

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/claude.py` — reference idiom
- `sdd/specs/bedrock-per-round-token.spec.md` §2, §3 (Module 1), §7
- `sdd/specs/tokens-observability.spec.md` — FEAT-397 contract

---

## Acceptance Criteria

- [ ] Multi-round `ask()` returns accumulated `AIMessage.usage`;
      `extra_usage["rounds"]` present only when rounds > 1
- [ ] `cacheReadInputTokens`/`cacheWriteInputTokens` are SUMS across rounds
- [ ] One `ClientRoundEvent` per tool round, none for the final round,
      `client_name == self.client_name`
- [ ] Fallback retry: usage/timing attributed to the successful call
- [ ] Single-round call behaviorally identical to pre-change
- [ ] `ask()` docstring updated (cache-counter multi-round semantics)
- [ ] Existing suite green: `pytest packages/ai-parrot/tests/unit/clients/ -v`
- [ ] No changes outside `clients/bedrock.py`
- [ ] Lint clean: `ruff check packages/ai-parrot/src/parrot/clients/bedrock.py`

---

## Test Specification

Full test suite is TASK-2096. For this task, verify no regression:

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/unit/clients/ -v
pytest packages/ai-parrot/tests/clients/test_bedrock_integration.py -v
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/bedrock-per-round-token.spec.md` (esp. §2, §3 Module 1, §6, §7)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — line numbers above were verified 2026-08-03; re-verify before editing
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
