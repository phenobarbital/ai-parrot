# TASK-2823: Budget resolution (`MODEL_WINDOWS`, kill switch) + calibration math

**Feature**: FEAT-525 — Per-Turn Conversation Compaction
**Spec**: `sdd/specs/per-turn-conversation-compaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2819
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, constraints C3 (default-on with kill switch), C11
(memory-owned EWMA) and C13 (monotonic boundary). `MODEL_WINDOWS` **does not
exist anywhere in the repo today** (spec §6 "Does NOT Exist") — the
brainstorm referred to it as if present. This task creates it, together
with the pure calibration functions that both `ConversationMemory.add_turn`
(TASK-2826) and `report_usage` use.

---

## Scope

- Create `parrot/memory/compaction/budget.py` with:
  - `MODEL_WINDOWS: Dict[str, int]` — lower-cased model-name **prefixes** →
    context window. Ship a small, tested starter table (at minimum:
    `"claude-"` → 200_000, `"gpt-4o"` → 128_000, `"gpt-4.1"` → 1_047_576,
    `"gpt-5"` → 400_000, `"o1"`/`"o3"`/`"o4"` → 200_000, `"gemini-"` →
    1_048_576, `"llama-3.1"`/`"llama-3.3"` → 131_072, `"mistral-large"` →
    128_000). Longest matching prefix wins.
  - `FALLBACK_WINDOW` re-exported from `models.py` (32_000).
  - `resolve_window(model: Optional[str]) -> int`: `None`/empty/unknown ⇒ `FALLBACK_WINDOW`.
  - `build_default_budget(model: Optional[str], *, max_turns: Optional[int] = None) -> ContextBudget`:
    `ContextBudget(window=resolve_window(model))`, with `max_turns` overriding the default 30 when given.
  - `compaction_disabled_by_env() -> bool`: `os.getenv("PARROT_COMPACTION_DISABLED") == "1"`
    (mirrors FEAT-380's `PARROT_COMPRESSION_DISABLED` at `tools/compression/stage.py:148`; **different variable**).
  - `EWMA_ALPHA = 0.2`, `CALIBRATION_MIN = 0.5`, `CALIBRATION_MAX = 2.0`.
  - `apply_usage(state: CompactionState, prompt_estimate: int, provider_prompt_tokens: Optional[int]) -> CompactionState`:
    returns `state` unchanged when `prompt_estimate <= 0` or `provider_prompt_tokens` is `None`/`<= 0`;
    otherwise `ratio = provider / estimate`, `new = alpha*ratio + (1-alpha)*state.calibration` (first sample: `new = ratio`),
    clamped to `[0.5, 2.0]`, `samples + 1`, `updated_at` set (ISO-8601).
  - `apply_commit(state: Optional[CompactionState], commit: CompactionCommit, tokenizer: str, provider_prompt_tokens: Optional[int]) -> CompactionState`:
    starts from `state or CompactionState(tokenizer=tokenizer)`; applies `apply_usage(...)` with
    `commit.prompt_estimate`; sets `boundary_turn_id = commit.boundary_turn_id` **only if** the
    state has no boundary yet or the commit's boundary is not older (see Key Constraints);
    `stage2_needed = state.stage2_needed or commit.stage2_needed`; `tokenizer` updated.
  - `state_from_dict` / `state_to_dict` helpers (or `CompactionState.to_dict/from_dict` if TASK-2819 put them on the model — reuse, do not duplicate).
- Unit tests.

**NOT in scope**: the walk itself (TASK-2828), the bot's `context_budget` property (TASK-2830).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/compaction/budget.py` | CREATE | `MODEL_WINDOWS`, `resolve_window`, `build_default_budget`, `compaction_disabled_by_env`, EWMA constants, `apply_usage`, `apply_commit` |
| `packages/ai-parrot/tests/unit/memory/compaction/test_budget.py` | CREATE | prefix resolution, fallback, env switch, EWMA clamp, boundary monotonicity |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory.compaction.models import ContextBudget, CompactionState, CompactionCommit, FALLBACK_WINDOW   # TASK-2819
import os
from datetime import datetime, timezone
from dataclasses import replace
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/compression/stage.py:148  (verified, precedent ONLY — do not import)
#     if os.getenv("PARROT_COMPRESSION_DISABLED") == "1":

# models.py (TASK-2819):
#   ContextBudget(window, reserve_output=8192, reserve_fixed=4096, high_watermark=0.80, low_watermark=0.60,
#                 max_turns=30, verbatim_tokens=15_000, min_verbatim_turns=2, oversize_tool_tokens=2_000, tool_activity_limit=Limit())
#   CompactionState(tokenizer, calibration=1.0, samples=0, boundary_turn_id=None, stage2_needed=False, updated_at=None)
#   CompactionCommit(prompt_estimate, boundary_turn_id, stage2_needed)
```

### Does NOT Exist
- ~~`MODEL_WINDOWS`~~ — nowhere in the repo (grep over `*.py`/`*.md` outside `sdd/proposals/`); create it here.
- ~~A per-model context-window table in `parrot/clients/*`~~ — none (`clients/claude.py:88` and `clients/google/client.py:1328` are unrelated constants). Do not try to import one.
- ~~`PARROT_COMPACTION_DISABLED`~~ — not read anywhere yet; only `PARROT_COMPRESSION_DISABLED` (FEAT-380) exists. Do not reuse FEAT-380's variable.
- ~~`ConversationMemory.report_usage`~~ — TASK-2826 (it will call `apply_usage` from here).

---

## Implementation Notes

### Key Constraints
- Boundary monotonicity needs turn order, which `budget.py` does not have. Contract: `apply_commit` treats the commit's `boundary_turn_id` as authoritative **because `compact_history` (TASK-2828) already guarantees it never regresses** (it starts from the persisted boundary). `apply_commit` therefore only refuses to replace a non-`None` boundary with `None`. Document this in the docstring; the regression test lives in TASK-2828.
- `apply_usage` is pure; `updated_at` uses `datetime.now(timezone.utc).isoformat()`.
- Prefix matching: `model.lower()`; iterate prefixes sorted by length descending; first `startswith` wins.
- Unknown-model logging is the **bot's** job (once per bot, TASK-2830); `resolve_window` stays silent.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/compression/stage.py:140-150` — env kill-switch style.

---

## Acceptance Criteria

- [ ] `resolve_window("claude-sonnet-5") == 200_000`; `resolve_window("gpt-4.1-mini") == 1_047_576` (longest prefix beats `"gpt-4"`-style shorter ones if present); `resolve_window("unknown-x") == 32_000`; `resolve_window(None) == 32_000`.
- [ ] `build_default_budget("claude-opus-5", max_turns=12).max_turns == 12`; default is 30.
- [ ] `compaction_disabled_by_env()` is `True` only when the variable equals `"1"` (monkeypatched env).
- [ ] `apply_usage`: first sample sets `calibration == ratio`; subsequent samples follow α=0.2; result clamped to [0.5, 2.0]; `estimate <= 0` or `None` usage returns the same state (and `samples` unchanged).
- [ ] `apply_commit(None, commit, "heuristic", 120)` builds a fresh state with the commit's boundary and `stage2_needed`; a later commit with `stage2_needed=False` does not clear a `True` flag; a commit with `boundary_turn_id=None` does not clear an existing boundary.
- [ ] All tests pass: `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/memory/compaction/test_budget.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/compaction/budget.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/memory/compaction/test_budget.py
import pytest
from parrot.memory.compaction.models import CompactionCommit, CompactionState
from parrot.memory.compaction import budget as b


@pytest.mark.parametrize("model,window", [("claude-sonnet-5", 200_000), ("gpt-4.1-mini", 1_047_576),
                                          ("unknown-x", 32_000), (None, 32_000), ("", 32_000)])
def test_resolve_window(model, window):
    assert b.resolve_window(model) == window


def test_env_kill_switch(monkeypatch):
    monkeypatch.delenv("PARROT_COMPACTION_DISABLED", raising=False)
    assert not b.compaction_disabled_by_env()
    monkeypatch.setenv("PARROT_COMPACTION_DISABLED", "1")
    assert b.compaction_disabled_by_env()


def test_apply_usage_ewma_clamped():
    s0 = CompactionState(tokenizer="heuristic")
    assert b.apply_usage(s0, 0, 100) is s0 and b.apply_usage(s0, 100, None) is s0
    s1 = b.apply_usage(s0, 100, 150)
    assert s1.calibration == pytest.approx(1.5) and s1.samples == 1
    s2 = b.apply_usage(s1, 100, 500)          # ratio 5.0 → 0.2*5 + 0.8*1.5 = 2.2 → clamp 2.0
    assert s2.calibration == 2.0


def test_apply_commit_boundary_and_flag():
    s = b.apply_commit(None, CompactionCommit(100, "t3", False), "heuristic", 120)
    assert s.boundary_turn_id == "t3" and s.stage2_needed is False
    s = b.apply_commit(s, CompactionCommit(100, "t5", True), "heuristic", None)
    s = b.apply_commit(s, CompactionCommit(100, None, False), "heuristic", None)
    assert s.boundary_turn_id == "t5" and s.stage2_needed is True
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2819 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code; update it first if anything changed
4. **Update status** in `sdd/tasks/index/per-turn-conversation-compaction.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2823-budget-resolution-calibration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-04
**Notes**: Implemented `parrot/memory/compaction/budget.py`: `MODEL_WINDOWS`
starter table (longest-prefix-first matching via `_SORTED_PREFIXES`),
`resolve_window`, `build_default_budget`, `compaction_disabled_by_env`
(`PARROT_COMPACTION_DISABLED`, distinct from FEAT-380's variable),
`apply_usage` (EWMA α=0.2, first-sample sets calibration directly,
clamped [0.5, 2.0], returns the same object on a degenerate sample),
`apply_commit` (4-arg contract per this task's Scope, superseding the
3-arg summary in spec §2's code block — boundary replaced only when the
commit's is non-`None`, `stage2_needed` OR'd, never cleared). Re-exports
`EWMA_ALPHA`/`CALIBRATION_MIN`/`CALIBRATION_MAX`/`FALLBACK_WINDOW` from
`models.py` rather than duplicating the literals. All 9 tests pass
(5 parametrized `resolve_window` cases + 4 others); `ruff check` clean.

**Deviations from spec**: none — followed this task's own `apply_commit`
signature (`state, commit, tokenizer, provider_prompt_tokens`), which is
more specific than and supersedes the spec §2 3-arg summary, per the
task's explicit instruction.
