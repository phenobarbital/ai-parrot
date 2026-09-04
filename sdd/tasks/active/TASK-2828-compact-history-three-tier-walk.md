# TASK-2828: `compact_history` — the pure three-tier pre-pass (+ RAW `<tool-activity>` renderer)

**Feature**: FEAT-525 — Per-Turn Conversation Compaction
**Spec**: `sdd/specs/per-turn-conversation-compaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2821, TASK-2823, TASK-2827
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8, goals G1/G9/G10/G13, the resolved decisions "Turn cap vs
token budget", "Oversized tool results", and §7 gotchas "Single huge newest
turn", "All prunables exhausted", "Legacy histories". This is the heart of
the feature: a pure, synchronous function that turns a `ConversationHistory`
plus a `ContextBudget` into `TurnView`s (RAW or PRUNED, with the
`assistant_suffix` already materialized) and the list of `Omission`s the bot
must flush before rendering. Nothing here touches a store or the network.

---

## Scope

- Create `parrot/memory/compaction/compact.py` with:
  - `render_tool_activity(turn: ConversationTurn, limit: Limit) -> str` — RAW suffix:
    `""` when no invocations; else `"\n\n<tool-activity>\n" + lines + "\n</tool-activity>"` with one
    line per invocation (up to `limit.max_invocations`, then `"… +N more"`):
    `- {name} {ok|error}[ {elapsed:.1f}s] in={canonical_input[:max_input_chars]}[ out={excerpt[:max_output_chars]} …(+N chars)][ error={error}]`
    (reuse `policies.format_invocation_line`; excerpt from `inv.output`, which is already the preview when
    offloaded — then the line carries the write-time notice via the policy instead of `out=`). If the whole
    block exceeds `limit.max_block_tokens` (counted with the given counter), collapse trailing lines to `"… +N more"`.
  - `render_raw_view(turn, limit, *, oversize: Collection[int] = (), policies=None, counter) -> Tuple[str, Tuple[Omission, ...]]`:
    like `render_tool_activity` but invocations whose index is in `oversize` are rendered through their
    `PrunePolicy` (notice + omission) — the oversize rule inside the verbatim tier. `render_tool_activity`
    is the `oversize=()` special case.
  - `compact_history(history, budget, *, policies=None, boundary_turn_id=None, counter=None,
    calibration=1.0, current_chatbot_id=None, include_other_agents=True) -> CompactionResult` implementing:
    1. `counter = counter or get_default_counter()`; `available = budget.available`; `watermark = int(budget.high_watermark * available)`.
    2. Candidate turns = `history.turns` minus foreign turns when `include_other_agents=False`
       (foreign ⇔ `current_chatbot_id is not None and turn.chatbot_id is not None and differ`) minus turns
       with a blank `assistant_response` (render skips them anyway; they are **not** listed in `dropped_turn_ids`).
    3. Ceiling: keep the last `budget.max_turns` candidates; the rest go to `dropped_turn_ids` (ceiling drops
       do **not** set `stage2_needed` — they are FEAT-524's existing `max_turns` behaviour).
    4. Per-turn base count: `tc = turn.token_count if not needs_recount(turn, counter) else count_turn(turn, counter)`
       (legacy turns counted lazily, never stamped here — purity).
    5. Walk newest → oldest with `cum = 0`, `n_raw = 0`, `pruned_seen = False`:
       - `forced = boundary_index is not None and idx <= boundary_index` (boundary looked up by `turn_id` among the kept candidates; not found ⇒ no forcing).
       - oversize set for this turn = indices of invocations with `counter.count(inv.output or "") > budget.oversize_tool_tokens`, **empty for the newest turn**.
       - RAW candidate: `raw_suffix, raw_om = render_raw_view(...)`; `raw_size = ceil(calibration * (tc.user + tc.assistant + counter.count(raw_suffix)))`.
       - PRUNED candidate: `pr_suffix, pr_om = prune_turn(turn, limit=budget.tool_activity_limit, policies=policies)`; `pr_size = ceil(calibration * (tc.user + tc.assistant + counter.count(pr_suffix)))`.
       - Decide: **RAW** if `not forced and not pruned_seen and (n_raw < budget.min_verbatim_turns or (cum + raw_size <= budget.verbatim_tokens and cum + raw_size <= watermark))`;
         else **PRUNED** if `cum + pr_size <= watermark or n_raw == 0` (never drop the newest); else **DROPPED**
         (and every older turn is dropped too — tiers are contiguous).
       - RAW ⇒ view(state=RAW, suffix=raw_suffix, est=raw_size), collect `raw_om`, `cum += raw_size`, `n_raw += 1`.
         PRUNED ⇒ view(state=PRUNED, suffix=pr_suffix, est=pr_size), collect `pr_om`, `cum += pr_size`, `pruned_seen = True`.
    6. `stage2_needed = any watermark drop occurred or cum > available`.
    7. `new_boundary = turn_id of the newest PRUNED turn` if any PRUNED view exists, else the incoming `boundary_turn_id` (never regresses: forced turns ⊇ old boundary).
    8. Return `CompactionResult(views oldest→newest, omissions (deduplicated by content_id, order preserved),
       history_estimate=Σ est, boundary_turn_id=new_boundary, stage2_needed, dropped_turn_ids)`.
- Unit + `hypothesis` property tests in `packages/ai-parrot/tests/unit/memory/compaction/test_compact.py`
  using the `chatty_history` / `database_history` / `make_turn` fixtures from TASK-2819's `conftest.py`.

**NOT in scope**: flushing omissions or rendering `HistoryMessage`s (bot,
TASK-2830 / render, TASK-2824); persisting the boundary (TASK-2826/2830);
the policies themselves (TASK-2827).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/compaction/compact.py` | CREATE | `render_tool_activity`, `render_raw_view`, `compact_history` |
| `packages/ai-parrot/tests/unit/memory/compaction/test_compact.py` | CREATE | chatty/database walks, min-verbatim guard, oversize rule, boundary, dropped/stage2, legacy count, purity property |
| `packages/ai-parrot/tests/unit/memory/compaction/conftest.py` | MODIFY (if needed) | extend `make_turn` with `tool_output_chars` if TASK-2819 left it minimal |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use only what is listed here. Verify anything else before using it.

### Verified Imports
```python
from parrot.memory.abstract import ConversationHistory, ConversationTurn                        # dev 198e6fecd: memory/abstract.py:130, :16
from parrot.memory.compaction.models import (ContextBudget, Limit, CompactionResult, TurnView, TurnState,
                                             Omission, TokenCount)                              # TASK-2819
from parrot.memory.compaction.tokens import TokenCounter, count_turn, needs_recount, get_default_counter, HeuristicCounter   # TASK-2821
from parrot.memory.compaction.policies import PrunePolicy, prune_turn, format_invocation_line, get_policy   # TASK-2827
from parrot.memory.compaction.budget import apply_commit   # TASK-2823 — tests only (boundary monotonic round-trip)
from hypothesis import given, settings, strategies as st                                        # verified: hypothesis 6.165.10
import math
```

### Existing Signatures to Use
```python
# models.py (TASK-2819)
ContextBudget(window, reserve_output=8_192, reserve_fixed=4_096, high_watermark=0.80, low_watermark=0.60, max_turns=30,
              verbatim_tokens=15_000, min_verbatim_turns=2, oversize_tool_tokens=2_000, tool_activity_limit=Limit())
ContextBudget.available -> int          # window - reserve_output - reserve_fixed, never < 0  (32_000 → 19_712)
TurnView(turn_id, chatbot_id, user_text, assistant_text, assistant_suffix, state, estimated_tokens)   # frozen
CompactionResult(views: Tuple[TurnView,...], omissions: Tuple[Omission,...], history_estimate: int,
                 boundary_turn_id: Optional[str], stage2_needed: bool, dropped_turn_ids: Tuple[str,...])  # frozen
TokenCount(user, assistant, tools, total, tokenizer)
# tokens.py (TASK-2821): count_turn(turn, counter) -> TokenCount ; needs_recount(turn, counter) -> bool ; HeuristicCounter.count = bytes//4 (min 1)
# policies.py (TASK-2827): prune_turn(turn, *, limit=Limit(), policies=None) -> (suffix, omissions) ; suffix "" when no invocations
#                          format_invocation_line(inv, *, limit, body) -> "- {name} {ok|error}[ {s}s] in={…} {body}"
# conftest.py (TASK-2819): make_turn(i, *, tokens=150, tool_output_chars=0, chatbot_id="bot"); fixtures chatty_history (50×150 tok),
#                          database_history (10 × ~8k tok with one 30_000-char tool output), counter=HeuristicCounter(), budget=ContextBudget(window=32_000)
# render.py contract (TASK-2824): views are consumed oldest→newest; blank assistant_text views are skipped there too.
```

### Does NOT Exist
- ~~`parrot.memory.compaction.compact`~~ — this task creates it.
- ~~`ContextBudget.low_watermark` in the walk~~ — reserved for Stage 2; **unused** here.
- ~~Truncating a turn's text~~ — never; a single huge newest turn renders RAW in full and sets `stage2_needed` when it alone exceeds `available`.
- ~~`TurnState.SUMMARIZED` views~~ — never produced here (Stage 2 non-goal).
- ~~Persisting anything~~ — `compact_history` writes nothing, stamps no `token_count` on legacy turns, mutates neither `history` nor its turns (`deepcopy`-compared in tests).
- ~~`context_used` in any size or view~~ — excluded by decision (TASK-2821 excludes it from `TokenCount`; `TurnView` has no such field).

---

## Implementation Notes

### Pattern to Follow
```python
def compact_history(history, budget, *, policies=None, boundary_turn_id=None, counter=None,
                    calibration=1.0, current_chatbot_id=None, include_other_agents=True) -> CompactionResult:
    counter = counter or get_default_counter()
    available = budget.available
    watermark = int(budget.high_watermark * available)
    candidates = [t for t in history.turns if (t.assistant_response or "").strip()
                  and (include_other_agents or not _is_foreign(t, current_chatbot_id))]
    dropped = [t.turn_id for t in candidates[:-budget.max_turns]] if len(candidates) > budget.max_turns else []
    kept = candidates[-budget.max_turns:]
    boundary_index = next((i for i, t in enumerate(kept) if t.turn_id == boundary_turn_id), None)
    views_rev, omissions, cum, n_raw, pruned_seen, overflow = [], [], 0, 0, False, False
    for idx in range(len(kept) - 1, -1, -1):
        turn = kept[idx]; newest = idx == len(kept) - 1
        tc = turn.token_count if not needs_recount(turn, counter) else count_turn(turn, counter)
        base = tc.user + tc.assistant
        oversize = () if newest else tuple(i for i, inv in enumerate(turn.tool_invocations)
                                          if counter.count(inv.output or "") > budget.oversize_tool_tokens)
        ...  # RAW / PRUNED / DROPPED decision exactly as in Scope step 5
    ...
```

### Key Constraints
- **Deterministic**: no randomness, no clock, no dict-order dependence on anything but the input; `math.ceil` for sizes.
- **Pure**: never mutate `history`, its turns or their invocations; build new tuples.
- Oversize check uses `inv.output` as stored (preview after write-time offload → small → not oversize again; the write-time notice is then produced by the policy because `"output" in inv.omitted`).
- Omission dedup by `content_id` keeps the first occurrence (identical content in two turns → one `Omission`, both notices carry the same id).
- Foreign turns' omissions are kept in the result like any other (spec §7 "Foreign turns": the bot stores them under the *current* history key).
- Google-style docstrings; module docstring states purity.

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/render.py:87-160` (FEAT-524, on dev) — foreign-turn rule to mirror (`current_chatbot_id`/`include_other_agents`).
- `packages/ai-parrot/src/parrot/security/groundedness/normalize.py` — pure module style.

---

## Acceptance Criteria

- [ ] `test_three_tier_walk_chatty`: 50 × ~150-token turns, `ContextBudget(window=32_000)` ⇒ 30 views (ceiling), all `RAW`, `omissions == ()`, `stage2_needed is False`, 20 ceiling-dropped ids.
- [ ] `test_three_tier_walk_database`: 10 × ~8k-token turns with a 30 000-char tool output ⇒ newest `RAW`, all others `PRUNED`, `history_estimate <= 0.8 * available`, one `Omission` per pruned turn (plus the oversize one from the newest? — **no**: newest is exempt), `boundary_turn_id == views[-2].turn_id`.
- [ ] `test_min_verbatim_turns_guard`: newest turn of 40k tokens alone ⇒ still `RAW`, `stage2_needed is True`, nothing truncated; with `min_verbatim_turns=2` the second-newest is also RAW even when over `verbatim_tokens`.
- [ ] `test_oversize_rule_inside_verbatim_tier`: a small history where turn N-1 has a 3 000-token output ⇒ its view is `RAW` but its suffix contains `<tool-output-omitted` and the result carries that `Omission`; the newest turn's identical output is rendered `out=` (exempt).
- [ ] `test_persisted_boundary_forces_pruned`: chatty history with `boundary_turn_id=views[10].turn_id` ⇒ views 0..10 `PRUNED` although the budget allows RAW; returned boundary ≥ the given one (never older); `apply_commit` round-trip keeps it.
- [ ] `test_dropped_sets_stage2`: `ContextBudget(window=16_000)` on the database history ⇒ non-empty `dropped_turn_ids` from watermark overflow, `stage2_needed is True`, every kept view intact.
- [ ] `test_legacy_turn_counted_lazily`: turns with `token_count=None` are sized with the passed counter and remain `token_count=None` afterwards.
- [ ] `test_compact_is_pure_and_deterministic` (hypothesis, ≥100 examples): `compact_history(h, b) == compact_history(h, b)`; `h == deepcopy_before`; views oldest→newest; RAW views are a suffix of the kept turns (no RAW older than a PRUNED).
- [ ] `render_tool_activity` respects `Limit.max_invocations` (`"… +N more"`) and `max_output_chars` (`…(+N chars)`); `""` for no invocations.
- [ ] All tests pass: `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/memory/compaction/test_compact.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/compaction/compact.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/memory/compaction/test_compact.py
import copy
from hypothesis import given, settings, strategies as st
from parrot.memory.abstract import ConversationHistory
from parrot.memory.compaction.models import ContextBudget, TurnState
from parrot.memory.compaction.compact import compact_history, render_tool_activity
from parrot.memory.compaction.tokens import HeuristicCounter


def test_three_tier_walk_chatty(chatty_history, budget, counter):
    r = compact_history(chatty_history, budget, counter=counter)
    assert len(r.views) == 30 and all(v.state is TurnState.RAW for v in r.views)
    assert r.omissions == () and r.stage2_needed is False and len(r.dropped_turn_ids) == 20


def test_three_tier_walk_database(database_history, budget, counter):
    r = compact_history(database_history, budget, counter=counter)
    assert r.views[-1].state is TurnState.RAW and all(v.state is TurnState.PRUNED for v in r.views[:-1])
    assert r.history_estimate <= int(0.8 * budget.available) and len(r.omissions) == len(r.views) - 1
    assert r.boundary_turn_id == r.views[-2].turn_id and all("<tool-output-omitted" in v.assistant_suffix for v in r.views[:-1])


def test_persisted_boundary_forces_pruned(chatty_history, budget, counter):
    first = compact_history(chatty_history, budget, counter=counter)
    b = first.views[10].turn_id
    r = compact_history(chatty_history, budget, counter=counter, boundary_turn_id=b)
    assert all(v.state is TurnState.PRUNED for v in r.views[:11]) and r.views[11].state is TurnState.RAW
    assert r.boundary_turn_id == b


def test_dropped_sets_stage2(database_history, counter):
    r = compact_history(database_history, ContextBudget(window=16_000), counter=counter)
    assert r.dropped_turn_ids and r.stage2_needed is True


@settings(max_examples=100, deadline=None)
@given(st.data())
def test_compact_is_pure_and_deterministic(data, counter):
    h = data.draw(st_history())            # strategy from conftest (TASK-2819) or defined here
    before = copy.deepcopy(h)
    b = ContextBudget(window=data.draw(st.integers(min_value=13_000, max_value=200_000)))
    r1, r2 = compact_history(h, b, counter=counter), compact_history(h, b, counter=counter)
    assert r1 == r2 and h == before
    states = [v.state for v in r1.views]
    assert states == sorted(states, key=lambda s: s is TurnState.RAW)   # PRUNED* then RAW*
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2821, 2823, 2827 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code; update it first if anything changed
4. **Update status** in `sdd/tasks/index/per-turn-conversation-compaction.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2828-compact-history-three-tier-walk.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
