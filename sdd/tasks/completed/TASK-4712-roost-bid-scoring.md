# TASK-4712: Contract Net bid scoring — Bid, Award, BidScorer, FixedWeightScorer (M2 part)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4711
**Assigned-to**: unassigned

---

## Context

Implements the scoring half of spec §3 **Module 2** (`parrot/roost/scoring.py`). Resolved decision carried
from the proposal: *Contract Net bid scoring — fixed default with a pluggable override; the requester's LLM
wakes only when the rule cannot decide.* It imports nothing from other Roost modules; it depends on TASK-4711 only because that task creates the
`parrot/roost/` package (`__init__.py`).

---

## Scope

- Create `parrot/roost/scoring.py` with `Bid`, `Award`, the `BidScorer` Protocol and `FixedWeightScorer`.
- Add `rank_bids(bids, scorer, tie_epsilon)` returning an `Award` (`decided_by='llm'` on a tie).
- Write `tests/roost/test_scoring.py`.

**NOT in scope**: the Contract Net state machine (TASK-4713); the `call_for_proposals` tool (TASK-4726)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/scoring.py` | CREATE | Bid/Award models, scorer protocol, fixed-weight default, `rank_bids` |
| `packages/ai-parrot/tests/roost/test_scoring.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from pydantic import BaseModel, Field
from typing import Literal, Optional, Protocol, Sequence
```

### Existing Signatures to Use
```python
# none — this module depends on no existing parrot symbol
```

### Does NOT Exist
- ~~`ContractNet` / any bid scorer in `packages/*/src` — 0 hits~~
- ~~`parrot.bots.flows.plan.delegate` scoring — FEAT-590 'delegate' is unrelated tool-call planning~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/scoring.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_scoring.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Normalisation of cost and time is min-max over the bids in the window (a single bid normalises to 0) — because absolute cost units differ between capabilities.
- Ties: when the top two scores differ by ≤ `tie_epsilon`, return `Award(winner=None, decided_by='llm')` — the requester's LLM decides (spec AC-8).
- Empty bid list ⇒ `Award(winner=None, decided_by='rule', rejected=[])` (NO_BIDS is the engine's job).
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- spec §2 Data Models `parrot/roost/scoring.py`
- spec §3 Module 2 skeleton

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Write the models and the Protocol — *why*: TASK-4713 imports them.
2. Implement `FixedWeightScorer.score` on pre-normalised fields and `rank_bids` — *why*: scoring must be pure.
3. Write the tests.

### `packages/ai-parrot/src/parrot/roost/scoring.py` (CREATE)
```python
"""Contract Net bid scoring (FEAT-747 M2). Pure, deterministic, no I/O."""
from __future__ import annotations

from typing import Literal, Optional, Protocol, Sequence

from pydantic import BaseModel, Field


class Bid(BaseModel):
    """One ``propose`` reduced to the fields the harness scores."""

    agent_name: str
    cost: float
    time_ms: float
    confidence: float = Field(ge=0.0, le=1.0)
    message_id: str


class Award(BaseModel):
    """Outcome of a bid window."""

    winner: Optional[Bid] = None
    decided_by: Literal["rule", "llm"] = "rule"
    rejected: list[Bid] = Field(default_factory=list)


class BidScorer(Protocol):
    """Per-channel pluggable strategy. Higher is better; must be deterministic for a given bid set."""

    def score(self, bid: Bid, *, cost_norm: float, time_norm: float) -> float: ...


class FixedWeightScorer:
    """``w_conf*confidence - w_cost*cost_norm - w_time*time_norm`` with weights (0.5, 0.3, 0.2) by default."""

    def __init__(self, *, w_confidence: float = 0.5, w_cost: float = 0.3, w_time: float = 0.2) -> None:
        self.w_confidence = w_confidence
        self.w_cost = w_cost
        self.w_time = w_time

    def score(self, bid: Bid, *, cost_norm: float, time_norm: float) -> float:
        return self.w_confidence * bid.confidence - self.w_cost * cost_norm - self.w_time * time_norm


def rank_bids(bids: Sequence[Bid], scorer: Optional[BidScorer] = None, *, tie_epsilon: float = 1e-6) -> Award:
    """Score *bids* and return the Award; a tie within *tie_epsilon* ⇒ ``decided_by='llm'`` and no winner."""
    scorer = scorer or FixedWeightScorer()
    # FILL IN: min-max normalise cost/time over bids, score, sort desc (stable by agent_name), tie rule — Key Constraints
    raise NotImplementedError
```
**Why**: The spec skeleton's `score(bid)` is extended with keyword-only normalised fields so scorers stay pure and comparable within a window; the class and function names are fixed (TASK-4713 imports them).

### FILL IN checklist
- [ ] `scoring.py::rank_bids` — normalisation, ordering, tie and empty rules; bounded by Key Constraints / AC-8
- [ ] `test_scoring.py` — bodies below

---

## Acceptance Criteria

- [ ] Fixed weights pick the higher-confidence, cheaper bid deterministically
- [ ] A tie within epsilon returns `decided_by='llm'`, `winner=None`
- [ ] A custom `BidScorer` overrides the default
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/scoring.py packages/ai-parrot/tests/roost/test_scoring.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/roost/test_scoring.py -q`

---

## Test Specification

```python
from parrot.roost.scoring import Bid, FixedWeightScorer, rank_bids


def _bid(name, cost, t, conf):
    return Bid(agent_name=name, cost=cost, time_ms=t, confidence=conf, message_id=name)


def test_rule_decides():
    award = rank_bids([_bid("a", 10, 100, 0.9), _bid("b", 20, 200, 0.5)])
    assert award.winner.agent_name == "a" and award.decided_by == "rule" and len(award.rejected) == 1


def test_tie_wakes_llm():
    award = rank_bids([_bid("a", 1, 1, 0.5), _bid("b", 1, 1, 0.5)])
    assert award.winner is None and award.decided_by == "llm"


def test_empty_window():
    assert rank_bids([]).winner is None


def test_custom_scorer():
    class Cheapest:
        def score(self, bid, *, cost_norm, time_norm):
            return -bid.cost
    assert rank_bids([_bid("a", 5, 1, 1.0), _bid("b", 1, 1, 0.1)], Cheapest()).winner.agent_name == "b"
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug local-inter-agent --feature-id FEAT-747 --spec sdd/specs/local-inter-agent.spec.md --index sdd/tasks/index/local-inter-agent.json`)
2. **Read the spec** at `sdd/specs/local-inter-agent.spec.md` (§2 Data Models and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/local-inter-agent.json`
4. **Verify the Codebase Contract** — re-run `grep -c` on every MODIFY anchor before editing; a count that
   differs means the anchor moved, `0` means stop and report
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`, never rename
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4712 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (FEAT-747 execution 0b6f3a52)
**Date**: 2026-10-26
**Notes**: Delivered by engine; merge-tier green.
Seat: gpt-5.6-terra (codex) · Attempts: 1

**Deviations from spec**: none
