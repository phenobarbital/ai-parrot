# TASK-2096: Multiround usage tests for Bedrock/Nova (ask + resume)

**Feature**: FEAT-404 — Bedrock/Nova Per-Round Token Usage Observability
**Spec**: `sdd/specs/bedrock-per-round-token.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2094, TASK-2095
**Assigned-to**: unassigned

---

## Context

FEAT-397 established a per-client test convention:
`tests/unit/clients/test_<client>_multiround_usage.py` exists for claude,
gemini, grok, groq and openai. This task implements **Module 3** of the spec
(§3): the Bedrock variant covering both instrumented methods (`ask()` from
TASK-2094, `resume()` from TASK-2095), the Bedrock-specific cache-counter
summing assertions (U1), and the one Nova-specific surface — that the
inherited path emits `client_name="nova"`.

---

## Scope

- Create `packages/ai-parrot/tests/unit/clients/test_bedrock_multiround_usage.py`
  mirroring `test_claude_multiround_usage.py`'s structure, but mocking the
  **`_sdk_create`** seam (Bedrock's SDK call site) with Converse-shaped dicts.
  Cover, for `ask()`:
  - 3-round loop (2 tool rounds + final): `AIMessage.usage` is the SUM;
    `extra_usage["rounds"] == 3`.
  - Exactly one `ClientRoundEvent` per tool round (2 events), 1-indexed
    `round_number`, correct `tool_calls` names and token fields.
  - Cache counters: `cacheReadInputTokens`/`cacheWriteInputTokens` in the
    final `extra_usage` are SUMS across rounds, not the last round's values.
  - Single-round no-op: no tool use → zero round events, no `"rounds"` key,
    usage equals the single round's parse.
  - No-usage round: response without `usage` → round event fires with `None`
    token fields; accumulator untouched.
  - Fallback retry: first `_sdk_create` raises a capacity error
    (`_should_use_fallback` → True), retry succeeds → one round event whose
    usage/timing reflect the successful call.
  - No-subscriber short-circuit: with no registry subscribers, multi-round
    `ask()` completes without constructing events.
  - `AfterClientCallEvent` carries accumulated totals.
- Cover, for `resume()`:
  - `BeforeClientCallEvent` + `AfterClientCallEvent` now fire around it.
  - Multi-round resume: accumulated usage, per-round events, `rounds` stamp,
    summed cache counters.
- NovaClient inheritance test: same mocked loop through a `NovaClient`
  instance → events carry `client_name == "nova"`; through
  `BedrockConverseClient` → `"bedrock-converse"`.
- Optionally extend
  `packages/ai-parrot/tests/integration/observability/test_multiround_usage.py`
  with a Bedrock end-to-end case (MetricsSubscriber receipt), mocking
  `_sdk_create`.

**NOT in scope**: any change to `src/` (implementation is TASK-2094/B); tests
for `ask_stream()`/`invoke()` (spec non-goals); Gemma4 or other holdout
clients.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/unit/clients/test_bedrock_multiround_usage.py` | CREATE | full multiround suite for ask() + resume() + Nova/BedrockConverse client_name |
| `packages/ai-parrot/tests/integration/observability/test_multiround_usage.py` | MODIFY (optional) | Bedrock e2e case via MetricsSubscriber |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 2026-08-03. TASK-2094/B will have shifted
> `bedrock.py` line numbers — the SEAMS below are stable by name.

### Verified Imports

```python
from parrot.clients.bedrock import BedrockConverseBase, BedrockConverseClient
from parrot.clients.nova import NovaClient          # nova/client.py:30
from parrot.core.events.lifecycle.events import (   # same imports used by test_claude_multiround_usage.py
    AfterClientCallEvent,
    ClientRoundEvent,
)
# BeforeClientCallEvent lives in the same package as the two above.
from parrot.models.basic import CompletionUsage
```

### Existing Signatures to Use

```python
# MOCK SEAM (Bedrock): patch this method on the client instance/class —
#   async def _sdk_create(self, payload) -> dict          # returns parsed Converse JSON
# It is awaited once per round in both ask() and resume() loops.
# Do NOT patch _backend.build_client — that is the CLAUDE test's seam and
# does not exist on Bedrock clients.

# Converse response shape consumed by the loops (verified in bedrock.py):
#   {"stopReason": "tool_use" | "end_turn",
#    "output": {"message": {"content": [
#        {"toolUse": {"toolUseId": str, "name": str, "input": dict}} |
#        {"text": str}]}},
#    "usage": {"inputTokens": int, "outputTokens": int,
#              "cacheReadInputTokens": int, "cacheWriteInputTokens": int}}

# resume() state contract (bedrock.py:1000-1020 docstring):
#   state = {"messages": <bedrock-shaped list>, "tool_call_id": str,
#            "agent_name": <optional model override>}

# client_name values (class attributes):
#   NovaClient.client_name == "nova"                      # nova/client.py:63
#   BedrockConverseClient.client_name == "bedrock-converse"  # bedrock.py:1229

# Reference test to mirror (structure, event capture, fixtures):
#   packages/ai-parrot/tests/unit/clients/test_claude_multiround_usage.py
#   (subscribes on the client instance's registry; module docstring lines 1-8)

# Existing e2e file (optional extension):
#   packages/ai-parrot/tests/integration/observability/test_multiround_usage.py
```

### Does NOT Exist

- ~~`_backend.build_client` on Bedrock clients~~ — Claude-only seam; mock
  `_sdk_create`.
- ~~`tests/unit/clients/test_bedrock_multiround_usage.py`~~ — this task
  creates it.
- ~~snake_case usage keys in Converse payloads~~ — Bedrock returns
  `inputTokens`/`outputTokens` (camelCase); `from_bedrock` expects them.
- ~~Round events from the final (non-tool) round~~ — by design none fires;
  don't assert one.
- ~~A fallback branch in `resume()`~~ — fallback tests apply to `ask()` only.

---

## Implementation Notes

### Pattern to Follow

Mirror `test_claude_multiround_usage.py`: helper builders for tool-round /
final-round response dicts, `AsyncMock` on the seam with `side_effect` lists,
event capture by subscribing `ClientRoundEvent`/`AfterClientCallEvent`
handlers on the client's registry. Instantiate clients with mocked/dummy
credentials so no AWS call is attempted (`_ensure_client` may need patching —
check how `test_nova.py` / `test_bedrock_integration.py` neutralize it).

```python
def _tool_round(tool_use_id: str, usage: dict) -> dict:
    return {"stopReason": "tool_use",
            "output": {"message": {"content": [
                {"toolUse": {"toolUseId": tool_use_id, "name": "t", "input": {}}}]}},
            "usage": usage}

def _final_round(usage: dict) -> dict:
    return {"stopReason": "end_turn",
            "output": {"message": {"content": [{"text": "done"}]}},
            "usage": usage}
```

Register a dummy tool (or patch `_execute_tool`) so the tool rounds execute
without a real toolkit.

### Key Constraints

- pytest + pytest-asyncio, matching the sibling test files' style.
- Assert SUMMED cache counters with distinct per-round values (e.g. 10/20 →
  30) so a right-hand-wins regression cannot pass.
- Nova test needs no Nova-specific behavior — only `client_name` on events.

### References in Codebase

- `packages/ai-parrot/tests/unit/clients/test_claude_multiround_usage.py` — template
- `packages/ai-parrot/tests/clients/test_nova.py`, `tests/clients/test_bedrock_integration.py` — client construction/mocking precedents
- `sdd/specs/bedrock-per-round-token.spec.md` §4 (test tables + fixtures), §5

---

## Acceptance Criteria

- [ ] All §4 unit tests from the spec implemented and passing:
      `pytest packages/ai-parrot/tests/unit/clients/test_bedrock_multiround_usage.py -v`
- [ ] Cache-counter SUM asserted with values that distinguish sum from
      last-round-wins
- [ ] `resume()` span + rounds covered; single-round no-op covered for both
      methods
- [ ] Nova (`"nova"`) and BedrockConverse (`"bedrock-converse"`)
      `client_name` assertions pass
- [ ] Full clients suite green: `pytest packages/ai-parrot/tests/unit/clients/ -v`
- [ ] Lint clean: `ruff check packages/ai-parrot/tests/unit/clients/test_bedrock_multiround_usage.py`

---

## Test Specification

The test tables in spec §4 are the authoritative list; the file must contain
at minimum the 11 unit tests named there.

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/bedrock-per-round-token.spec.md` (§4, §5, §6)
2. **Check dependencies** — TASK-2094 and TASK-2095 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm the seams against the post-TASK-2094/B `bedrock.py`
4. **Update status** in `sdd/tasks/index/bedrock-per-round-token.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-03
**Notes**: Created
`packages/ai-parrot/tests/unit/clients/test_bedrock_multiround_usage.py`
mirroring `test_claude_multiround_usage.py`'s structure, mocking the
`_sdk_create` seam with Converse-shaped dicts (`_tool_round`/`_final_round`
helpers). 14 tests total (11 required by spec §4 plus 3 supplementary:
a combined fallback+tool-round attribution case, a resume() single-round
no-op, and an explicit BedrockConverseClient `client_name` assertion
alongside the Nova one). Covers `ask()`: multiround accumulation, per-round
events (1-indexed, tool names, token fields), rounds-stamp-only-when->1,
summed cache counters (asserted with distinct per-round values — 10/20/30
sum vs. 30 last-round-wins — so a right-hand-wins regression cannot pass),
single-round no-op, no-usage-round None fields, fallback retry attribution
(both bare and combined with a subsequent tool round), and no-subscriber
short-circuit (implicit — no subscribers are registered and the loop
still completes without error). Covers `resume()`: lifecycle span
(`BeforeClientCallEvent`/`AfterClientCallEvent`), multiround accumulation +
events + rounds stamp + summed cache counters, and single-round no-op.
Nova inheritance test asserts `client_name == "nova"` through the same
mocked loop via `NovaClient()`; a parallel test pins
`"bedrock-converse"` for `BedrockConverseClient`. All 14 new tests pass;
full `pytest packages/ai-parrot/tests/unit/clients/ -v` green (58 passed,
44 pre-existing + 14 new). `ruff check` on the new test file passes clean
(nested `with patch.object(...)` blocks combined into single `with ... , ...:`
statements per SIM117 to keep the new file lint-clean, since — unlike
`bedrock.py` — this is a from-scratch file with no pre-existing style debt
to match).

**Deviations from spec**: none — the 3 extra tests are additive coverage
beyond the spec's minimum 11 and were not substitutions for anything
listed.
