---
type: Wiki Overview
title: 'TASK-1475: Conference data models (PeerVote, ConferenceRound, ConferenceResult)'
id: doc:sdd-tasks-completed-task-1475-conference-data-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 1 of the spec (§2 Data Models, §3 Module 1). These Pydantic
relates_to:
- concept: mod:parrot.models
  rel: mentions
- concept: mod:parrot.models.conference
  rel: mentions
---

# TASK-1475: Conference data models (PeerVote, ConferenceRound, ConferenceResult)

**Feature**: FEAT-223 — Multi-Party Conferencing for OrchestratorAgent
**Spec**: `sdd/specs/orchestratoragent-multiparty.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements Module 1 of the spec (§2 Data Models, §3 Module 1). These Pydantic
models are the typed contract for the structured vote (`PeerVote`), per-round state
(`ConferenceRound`) and the aggregated outcome (`ConferenceResult`). Every later task
imports them, so this is the foundation.

---

## Scope

- Create `parrot/models/conference.py` with `PeerVote`, `ConferenceRound`,
  `ConferenceResult` exactly as defined in spec §2 Data Models (Pydantic v2).
- Export the three models from `parrot/models/__init__.py`.
- Write unit tests for the models (validation bounds, defaults).

**NOT in scope**: the `confer()` method, broadcasting, voting, or any orchestrator
change (those are TASK-1476 / TASK-1477).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/conference.py` | CREATE | The three Pydantic models |
| `packages/ai-parrot/src/parrot/models/__init__.py` | MODIFY | Export `PeerVote`, `ConferenceRound`, `ConferenceResult` |
| `packages/ai-parrot/tests/test_conference_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-05. Monorepo paths under `packages/ai-parrot/src/`.

### Verified Imports
```python
from pydantic import BaseModel, Field   # pydantic v2 already in use project-wide
```

### Existing Signatures to Use
```python
# Mirror existing model conventions, e.g. parrot/models/outputs.py and
# parrot/models/responses.py use `from pydantic import BaseModel, Field`.
# parrot/models/__init__.py is the export hub — append new names to it.
```

### Does NOT Exist
- ~~`parrot.models.conference`~~ — create it in this task.
- ~~`PeerVote` / `ConferenceRound` / `ConferenceResult`~~ — do not exist yet.

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/models/conference.py
from typing import Dict, List
from pydantic import BaseModel, Field


class PeerVote(BaseModel):
    chosen_label: str = Field(..., description="Anonymous label (A, B, C...) of the chosen answer; may be own.")
    revised_answer: str = Field(..., description="Agent's final answer (may keep its own or adopt another).")
    confidence: float = Field(..., ge=0, le=100, description="Confidence 0-100.")
    rationale: str = Field(..., description="Brief justification.")


class ConferenceRound(BaseModel):
    round_index: int
    answers: Dict[str, str]          # label -> answer (anonymous)
    label_to_agent: Dict[str, str]   # label -> agent_name (internal, NOT shown to the LLM)
    votes: Dict[str, PeerVote]       # agent_name -> vote


class ConferenceResult(BaseModel):
    winner_agent: str
    final_answer: str
    confidence_score: float
    rounds: List[ConferenceRound]
    vote_breakdown: Dict[str, float]
    converged: bool
```

### Key Constraints
- Pydantic v2 (`ge`/`le` validators).
- Keep field names/semantics IDENTICAL to spec §2 so later tasks line up.
- `label_to_agent` is an internal mapping; it must never be serialized into a prompt.

### References in Codebase
- `parrot/models/outputs.py` — model/dataclass conventions.
- `parrot/models/__init__.py` — export hub.

---

## Acceptance Criteria

- [ ] `from parrot.models.conference import PeerVote, ConferenceRound, ConferenceResult` works.
- [ ] `from parrot.models import PeerVote, ConferenceRound, ConferenceResult` works (exported).
- [ ] `PeerVote(confidence=150, ...)` raises a Pydantic `ValidationError` (bounds 0-100).
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/test_conference_models.py -v`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/conference.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_conference_models.py
import pytest
from pydantic import ValidationError
from parrot.models.conference import PeerVote, ConferenceRound, ConferenceResult


def _vote(**kw):
    base = dict(chosen_label="A", revised_answer="x", confidence=80, rationale="r")
    base.update(kw)
    return PeerVote(**base)


class TestPeerVote:
    def test_valid(self):
        assert _vote().confidence == 80

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            _vote(confidence=150)
        with pytest.raises(ValidationError):
            _vote(confidence=-1)


class TestConferenceModels:
    def test_round_roundtrip(self):
        r = ConferenceRound(
            round_index=1,
            answers={"A": "a1"},
            label_to_agent={"A": "agent_x"},
            votes={"agent_x": _vote()},
        )
        assert r.votes["agent_x"].chosen_label == "A"

    def test_result_fields(self):
        res = ConferenceResult(
            winner_agent="agent_x", final_answer="a1", confidence_score=80.0,
            rounds=[], vote_breakdown={"A": 80.0}, converged=True,
        )
        assert res.converged is True
```

---

## Agent Instructions

When you pick up this task: read the spec, verify the contract, set status
`in-progress`, implement, run tests, move this file to `sdd/tasks/completed/`,
update the per-spec index to `done`, and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.8)
**Date**: 2026-06-05
**Notes**: Created `parrot/models/conference.py` with `PeerVote`, `ConferenceRound`,
and `ConferenceResult` (Pydantic v2, field names/semantics identical to spec §2).
Exported all three from `parrot/models/__init__.py` (import + `__all__`). Added
`test_conference_models.py` covering confidence bounds (0/100 edges + out-of-range
rejection), round round-trip, result fields, and package-root re-export. All 6 tests
pass; `ruff check` clean.
**Deviations from spec**: none
