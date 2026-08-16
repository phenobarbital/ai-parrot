# TASK-1983: Dream Models, Config & State Persistence

**Feature**: FEAT-390 — Dream Cycle — Episodic→Wiki Brain Consolidation
**Spec**: `sdd/specs/dream-cycle-brain-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation module for the dream-cycle pipeline (spec §3 Module 1). Every other
task consumes these models: `DreamState` (scheduler/runner persisted state),
`DreamConfig` (tunables), `DistilledKnowledge` (distill LLM output contract),
`DreamCycleReport` (structured cycle result). State persists as a JSON sidecar
file — NOT a table in the wiki DB.

---

## Scope

- Create package `parrot/memory/dream/` with `__init__.py` and `models.py`.
- Implement Pydantic v2 models exactly as spec §2 "Data Models":
  `DreamState`, `DreamConfig`, `DistilledKnowledge`, `DreamCycleReport`.
- `DreamConfig` fields with defaults: `importance_threshold=5`,
  `similarity_threshold=0.75`, `max_groups_per_cycle=20`,
  `org_promotion_cycles=3`, `distill_model="gemini-3.1-flash-lite"`,
  `startup_jitter_seconds=60`, `failure_backoff_divisor=4`.
- Implement JSON sidecar persistence helpers for `DreamState`:
  `save_state(state, path)` (write to temp file + `os.replace`, atomic) and
  `load_state(path, agent_id)` (returns a fresh default `DreamState` on
  missing file OR corrupt/unparseable JSON — never raises).
- Write unit tests in `tests/memory/dream/test_models.py` (+ empty
  `tests/memory/dream/__init__.py` / conftest if the tree needs it).

**NOT in scope**: BrainStore (TASK-1984), runner logic (TASK-1986),
scheduler (TASK-1987), any wiki or episodic imports beyond `MemoryNamespace`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/dream/__init__.py` | CREATE | Package init; export the 4 models + persistence helpers |
| `packages/ai-parrot/src/parrot/memory/dream/models.py` | CREATE | Models + `save_state`/`load_state` |
| `tests/memory/dream/__init__.py` | CREATE | Test package init |
| `tests/memory/dream/test_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field  # pydantic v2, already a dependency
from parrot.memory.episodic.models import MemoryNamespace
# verified: packages/ai-parrot/src/parrot/memory/episodic/models.py:214
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/episodic/models.py:214
class MemoryNamespace(BaseModel): ...  # org_id / agent_id / user_id scoping
```

Model shapes (from spec §2 — implement verbatim):
```python
class DreamState(BaseModel):
    agent_id: str
    last_run: datetime | None = None
    next_due: datetime | None = None
    interval_hours: float = 24.0
    running: bool = False
    running_since: datetime | None = None
    cycles_completed: int = 0
    episodes_consolidated: int = 0
    reinforcement_counts: dict[str, int] = Field(default_factory=dict)
    promoted_pages: list[str] = Field(default_factory=list)

class DistilledKnowledge(BaseModel):
    title: str
    body: str
    category: str = "lesson"
    confidence: float = 0.5

class DreamCycleReport(BaseModel):
    started_at: datetime
    finished_at: datetime | None = None
    episodes_collected: int = 0
    groups_formed: int = 0
    groups_distilled: int = 0
    groups_skipped: int = 0
    pages_written: list[str] = Field(default_factory=list)
    pages_promoted: list[str] = Field(default_factory=list)
    aborted: bool = False
    abort_reason: str | None = None
```

### Does NOT Exist
- ~~`parrot/memory/dream/`~~ — this task CREATES it; nothing imports it yet
- ~~a `dream_state` table in wiki.db~~ — state is a JSON **file** sidecar
- ~~`DreamState.reinforcement_count` on wiki pages~~ — counts live in
  `DreamState.reinforcement_counts` (dict page_id → int)

---

## Implementation Notes

### Pattern to Follow
Pydantic models + module-level helpers, Google-style docstrings, strict type
hints (see `parrot/memory/unified/models.py` for the house style).

Atomic write pattern:
```python
tmp = path.with_suffix(".tmp")
tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
os.replace(tmp, path)
```

### Key Constraints
- `load_state` must be tolerant: missing file, invalid JSON, or schema
  mismatch → return `DreamState(agent_id=agent_id)` and log WARNING.
- Use `datetime` timezone-aware (UTC) consistently.
- No wiki/episodic-store imports here (keep the module import-light).

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/unified/models.py` — Pydantic style,
  Field(description=...) conventions.

---

## Acceptance Criteria

- [ ] `from parrot.memory.dream import DreamState, DreamConfig, DistilledKnowledge, DreamCycleReport, save_state, load_state` works
- [ ] `save_state` writes atomically (temp + `os.replace`)
- [ ] `load_state` on missing/corrupt file returns default state, never raises
- [ ] All tests pass: `pytest tests/memory/dream/test_models.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/dream/`

---

## Test Specification

```python
# tests/memory/dream/test_models.py
import pytest
from parrot.memory.dream import (
    DreamConfig, DreamState, load_state, save_state,
)


def test_dream_config_defaults():
    cfg = DreamConfig()
    assert cfg.importance_threshold == 5
    assert cfg.max_groups_per_cycle == 20
    assert cfg.org_promotion_cycles == 3
    assert cfg.similarity_threshold == 0.75


def test_dream_state_roundtrip(tmp_path):
    state = DreamState(agent_id="a1", cycles_completed=2,
                       reinforcement_counts={"mem-abc": 1})
    path = tmp_path / "dream_state.json"
    save_state(state, path)
    loaded = load_state(path, agent_id="a1")
    assert loaded == state


def test_load_state_missing_file(tmp_path):
    loaded = load_state(tmp_path / "nope.json", agent_id="a1")
    assert loaded.agent_id == "a1"
    assert loaded.cycles_completed == 0


def test_load_state_corrupt_file(tmp_path):
    path = tmp_path / "dream_state.json"
    path.write_text("{not json", encoding="utf-8")
    loaded = load_state(path, agent_id="a1")
    assert loaded.agent_id == "a1"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/dream-cycle-brain-consolidation.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1983-dream-models.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-30
**Notes**: Implemented `DreamState`, `DreamConfig`, `DistilledKnowledge`,
`DreamCycleReport` verbatim per spec §2, plus atomic `save_state`/`load_state`
JSON sidecar helpers (tempfile-suffix write + `os.replace`, tolerant load on
missing/corrupt file). 7 unit tests pass; `ruff check` clean.

**Deviations from spec**: The Codebase Contract listed
`from parrot.memory.episodic.models import MemoryNamespace` as a verified
import, but none of the four model shapes in spec §2 actually reference
`MemoryNamespace` — it is not used by `DreamState`/`DreamConfig`/
`DistilledKnowledge`/`DreamCycleReport`. Omitted the unused import to keep
the module lint-clean and import-light per the task's own constraint ("No
wiki/episodic-store imports here"); `MemoryNamespace` is expected to be
consumed directly by `DreamCycleRunner` (TASK-1986) instead.
