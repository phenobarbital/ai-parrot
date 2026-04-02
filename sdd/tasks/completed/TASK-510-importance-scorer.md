# TASK-510: ImportanceScorer Abstraction + ValueScorer Port

**Feature**: refactor-episodic-agentcorememory
**Spec**: `sdd/specs/refactor-episodic-agentcorememory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 from the spec. Defines a pluggable importance-scoring protocol and ports the `ValueScorer` from `AgentCoreMemory` (`parrot/memory/core.py`). Currently, `EpisodicMemoryStore.record_episode()` uses inline heuristic logic to compute importance (1-10 scale based on outcome). This task extracts that logic into a `HeuristicScorer` and adds `ValueScorer` as an alternative strategy.

---

## Scope

- Define `ImportanceScorer` protocol with `score(episode: EpisodicMemory) -> float` returning [0.0, 1.0]
- Extract the current inline importance logic from `store.py` into `HeuristicScorer` (preserving exact behavior)
- Port `ValueScorer` from `core.py`, adapting it to work with `EpisodicMemory` model fields:
  - `outcome` → outcome weight
  - `related_tools` → tool usage weight
  - `situation` length → query length weight
  - `outcome_details` length → response length weight
  - Configurable weights and threshold (from `core.py` defaults: outcome=0.3, tool_usage=0.2, query_length=0.1, response_length=0.2, feedback=0.3, threshold=0.4)
- Write unit tests for both scorers

**NOT in scope**: Wiring scorers into `EpisodicMemoryStore` (that's TASK-515). Modifying the `EpisodicMemory` model.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/memory/episodic/scoring.py` | CREATE | ImportanceScorer protocol, HeuristicScorer, ValueScorer |
| `tests/unit/memory/episodic/test_scoring.py` | CREATE | Unit tests for both scorers |
| `parrot/memory/episodic/__init__.py` | MODIFY | Export new classes |

---

## Implementation Notes

### Pattern to Follow
```python
from typing import Protocol, runtime_checkable
from parrot.memory.episodic.models import EpisodicMemory, EpisodeOutcome

@runtime_checkable
class ImportanceScorer(Protocol):
    def score(self, episode: EpisodicMemory) -> float:
        """Return importance score in [0.0, 1.0]."""
        ...
```

### Key Constraints
- Use `Protocol` from typing, not ABC
- `HeuristicScorer` must produce equivalent results to the current inline logic in `store.py` (normalize the 1-10 scale to 0.0-1.0)
- `ValueScorer` must use Pydantic `BaseModel` for config with `Field` defaults
- All weights configurable, all scores clamped to [0.0, 1.0]

### References in Codebase
- `parrot/memory/core.py` lines with `_evaluate_interaction_value()` and `ValueScorer` — source to port
- `parrot/memory/episodic/store.py` — current inline importance logic in `record_episode()`
- `parrot/memory/episodic/models.py` — `EpisodicMemory`, `EpisodeOutcome` definitions

---

## Acceptance Criteria

- [ ] `ImportanceScorer` protocol defined with `score()` method
- [ ] `HeuristicScorer` produces normalized [0.0, 1.0] scores matching current inline logic
- [ ] `ValueScorer` port uses configurable weights and threshold
- [ ] Both scorers satisfy `isinstance(scorer, ImportanceScorer)` check
- [ ] All tests pass: `pytest tests/unit/memory/episodic/test_scoring.py -v`
- [ ] Imports work: `from parrot.memory.episodic.scoring import ImportanceScorer, HeuristicScorer, ValueScorer`

---

## Test Specification

```python
# tests/unit/memory/episodic/test_scoring.py
import pytest
from parrot.memory.episodic.scoring import ImportanceScorer, HeuristicScorer, ValueScorer
from parrot.memory.episodic.models import EpisodicMemory, EpisodeOutcome


@pytest.fixture
def success_episode():
    return EpisodicMemory(
        agent_id="test-agent",
        situation="User asked about weather",
        action_taken="Called weather API",
        outcome=EpisodeOutcome.SUCCESS,
        outcome_details="Returned forecast",
        category="TOOL_EXECUTION",
        related_tools=["weather_api"],
        embedding=[0.0] * 384,
    )


@pytest.fixture
def failure_episode():
    return EpisodicMemory(
        agent_id="test-agent",
        situation="Q",
        action_taken="Failed",
        outcome=EpisodeOutcome.FAILURE,
        category="ERROR_RECOVERY",
        embedding=[0.0] * 384,
    )


class TestHeuristicScorer:
    def test_success_scores_higher(self, success_episode, failure_episode):
        scorer = HeuristicScorer()
        assert scorer.score(success_episode) > scorer.score(failure_episode)

    def test_score_range(self, success_episode):
        scorer = HeuristicScorer()
        score = scorer.score(success_episode)
        assert 0.0 <= score <= 1.0

    def test_protocol_compliance(self):
        assert isinstance(HeuristicScorer(), ImportanceScorer)


class TestValueScorer:
    def test_configurable_weights(self, success_episode):
        scorer = ValueScorer(outcome_weight=1.0, tool_usage_weight=0.0)
        score = scorer.score(success_episode)
        assert 0.0 <= score <= 1.0

    def test_threshold(self, failure_episode):
        scorer = ValueScorer(threshold=0.4)
        score = scorer.score(failure_episode)
        # Failure with minimal content should score below threshold
        assert score < 0.4

    def test_protocol_compliance(self):
        assert isinstance(ValueScorer(), ImportanceScorer)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-510-importance-scorer.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-02
**Notes**: All 18 unit tests pass. HeuristicScorer normalizes 1-10 scale to [0.0, 1.0]. ValueScorer uses Pydantic BaseModel with configurable weights. Both satisfy ImportanceScorer protocol.

**Deviations from spec**: none
