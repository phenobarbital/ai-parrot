# TASK-3184: Raise the in-process turn budget library default from 24 to 40

**Feature**: FEAT-553 — sdd-coder Shared Conventions & Turn Budget
**Spec**: `sdd/specs/sdd-coder-shared-conventions.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. An operator-measured task needed 35 turns and died against
the 24-turn library default. `build_dispatcher`'s wiring default (60, env
`DEV_LOOP_LLM_MAX_TURNS`) is untouched; only the two profile defaults move.
The "Your budget is N turns" sentence reads the profile, so it follows.

---

## Scope

- `LLMCodeDispatchProfile.max_turns` default 24 → 40; `GrokCodeDispatchProfile.max_turns` 24 → 40.
- Update the wording of the `agent_builder.py` comment that says "library default of 24".
- One new test module asserting both defaults and the untouched 60.

**NOT in scope**: docs (TASK-3183 owns `sdd-coder-orchestrator.md`); `DEFAULT_LLM_MAX_TURNS`; the `le=100` bound; investigating the 35-turn run (spec §8 Q2, separate ticket).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py` | MODIFY | `max_turns` default |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/grok.py` | MODIFY | `max_turns` default |
| `packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py` | MODIFY | comment wording only |
| `packages/ai-parrot/tests/flows/dev_loop/test_profile_turn_budget.py` | CREATE | defaults test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile     # verified: models/llm.py:10
from parrot.flows.dev_loop.models.grok import GrokCodeDispatchProfile   # verified: models/grok.py (class body :17-24)
from parrot.flows.dev_loop.agent_builder import DEFAULT_LLM_MAX_TURNS   # verified: agent_builder.py:134
```

### Existing Signatures to Use
```python
# models/llm.py
max_turns: int = Field(default=24, ge=1, le=100)     # line 23
# models/grok.py
max_turns: int = Field(default=24, ge=1, le=100)     # line 22 — the ONLY subclass that redeclares it (nova/google_compat/zai/moonshot inherit)
# agent_builder.py
#: more than the profile's conservative library default of 24. Every seat of   # line 129 (comment)
DEFAULT_LLM_MAX_TURNS: int = 60                                                  # line 134 — unchanged
# tests/flows/dev_loop/test_agent_builder.py:123  `assert profile.max_turns == DEFAULT_LLM_MAX_TURNS == 60` — must keep passing
# tests/flows/dev_loop/test_llm_code_dispatcher.py:577 test_budget_nudge_states_the_count_and_the_turn_economics — reads the profile, must keep passing
```

### Does NOT Exist
- ~~a `max_turns` override in nova.py / google_compat.py / zai.py / moonshot.py models~~ — verified none; do not add.
- ~~`RosterSeat.max_turns`~~ — no per-seat budget.
- ~~a literal `24` in `llm.py`'s "Your budget is" sentence~~ — it is `{profile.max_turns}` (llm.py:914).

---

## Implementation Blueprint

### Steps (in order)
1. Change the two defaults — *why*: AC-9.
2. Re-word the comment — *why*: it would otherwise lie about the default.
3. Add the test; run `pytest packages/ai-parrot/tests/flows/dev_loop/test_profile_turn_budget.py packages/ai-parrot/tests/flows/dev_loop/test_agent_builder.py packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py -k "turn or budget" -v`.

### `packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'max_turns: int = Field(default=24, ge=1, le=100)' …/models/llm.py)
# REPLACE line 23 with:
    max_turns: int = Field(default=40, ge=1, le=100)  # FEAT-553: a real SDD task measured 35 turns; 24 was too small
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/models/grok.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'max_turns: int = Field(default=24, ge=1, le=100)' …/models/grok.py)
# REPLACE line 22 with:
    max_turns: int = Field(default=40, ge=1, le=100)  # FEAT-553: keep in step with LLMCodeDispatchProfile
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c "library default of 24" …/agent_builder.py)
# REPLACE, in the comment at line 129, `library default of 24` with `library default of 40 (24 before FEAT-553)`
```

### `packages/ai-parrot/tests/flows/dev_loop/test_profile_turn_budget.py` (CREATE)
```python
"""Turn-budget defaults (FEAT-553, spec AC-9)."""
from parrot.flows.dev_loop.agent_builder import DEFAULT_LLM_MAX_TURNS
from parrot.flows.dev_loop.models.grok import GrokCodeDispatchProfile
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile


def test_profile_default_max_turns_is_40():
    assert LLMCodeDispatchProfile().max_turns == 40
    assert GrokCodeDispatchProfile().max_turns == 40


def test_wiring_default_unchanged():
    assert DEFAULT_LLM_MAX_TURNS == 60
```

### FILL IN checklist
- [ ] none

---

## Acceptance Criteria

- [ ] `LLMCodeDispatchProfile().max_turns == 40` and `GrokCodeDispatchProfile().max_turns == 40` (spec AC-9)
- [ ] `DEFAULT_LLM_MAX_TURNS == 60`; `le=100` unchanged (spec AC-9)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_profile_turn_budget.py packages/ai-parrot/tests/flows/dev_loop/test_agent_builder.py packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py -v`
- [ ] `ruff check` clean on the three modified files

---

## Test Specification

See the CREATE test block above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 M5, §7 "The 24 vs 60 discrepancy")
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — the two `default=24` lines and the comment at :129
4. **Update status** in `sdd/tasks/index/sdd-coder-shared-conventions.json` → `"in-progress"`
5. **Implement** — from the blueprint; touch nothing else
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3184-max-turns-library-default-40.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none
