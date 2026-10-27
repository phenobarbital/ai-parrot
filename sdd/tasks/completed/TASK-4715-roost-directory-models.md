# TASK-4715: Roost directory models — Locality, InterAgentGrant, RoostAgentConfig, CapabilityMatch (M3b)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4711
**Assigned-to**: unassigned

---

## Context

Implements the Roost half of spec §3 **Module 3** (`parrot/roost/directory.py`): the advertisement each agent
publishes on its registry entry (`RoostAgentConfig`), the inter-agent grant (`InterAgentGrant`, resolved: a
configuration with capability-pattern scopes, never model-visible), the ranked result type `CapabilityMatch`,
`locality_of()` and `rank()`. `parrot/registry/registry.py` imports this module (TASK-4716), so it must import
nothing heavier than `parrot.roost.performatives`.

---

## Scope

- Create `parrot/roost/directory.py` per the spec skeleton.
- Write `tests/roost/test_directory.py`.

**NOT in scope**: grant evaluation logic (TASK-4717); registry wiring (TASK-4716)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/directory.py` | CREATE | Directory models + `locality_of` + `rank` |
| `packages/ai-parrot/tests/roost/test_directory.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from parrot.roost.performatives import CarrierKind  # created by TASK-4711
```

### Existing Signatures to Use
```python
# parrot/roost/performatives.py (TASK-4711)
class CarrierKind(str, Enum): IN_PROCESS; SAME_HOST; NETWORK; MATRIX
```

### Does NOT Exist
- ~~`BotMetadata.kind` — FEAT-746 M13 adds it; read it with `getattr(meta, 'kind', 'local')`~~
- ~~`parrot.roost.directory` importing `parrot.registry` — forbidden (import cycle with TASK-4716)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/directory.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_directory.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `locality_of`: kind in (`a2a`, `squawk`) ⇒ REMOTE; carrier IN_PROCESS ⇒ IN_PROCESS; SAME_HOST with `host_id == local_host_id` ⇒ SAME_HOST else SAME_NETWORK; NETWORK/MATRIX ⇒ SAME_NETWORK; config None ⇒ IN_PROCESS for kind local (a plain registered agent lives in this process).
- `rank`: stable sort by `(locality, cost, -score)` (AC-9).
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- spec §2 Data Models `parrot/roost/directory.py`

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Write the models and two functions.
2. Write tests.

### `packages/ai-parrot/src/parrot/roost/directory.py` (CREATE)
```python
"""Roost capability-directory models (FEAT-747 M3). Imported by parrot.registry — keep it dependency-light."""
from __future__ import annotations

from enum import IntEnum
from typing import Iterable, Literal, Optional

from pydantic import BaseModel, Field

from .performatives import CarrierKind


class Locality(IntEnum):
    IN_PROCESS = 0
    SAME_HOST = 1
    SAME_NETWORK = 2
    REMOTE = 3


class InterAgentGrant(BaseModel):
    """Capability-pattern scopes an agent may call (``hr.*``, ``*``). Empty ⇒ not granted."""

    scopes: list[str] = Field(default_factory=list)


class RoostAgentConfig(BaseModel):
    """What an agent advertises on its registry entry and how it is reached."""

    capabilities: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    category_hashes: dict[str, str] = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)
    carrier: CarrierKind = CarrierKind.IN_PROCESS
    host_id: Optional[str] = None
    cost: float = 1.0
    backing: Literal["deterministic", "llm_backed"] = "llm_backed"
    grant: Optional[InterAgentGrant] = None
    bid: Optional[dict[str, float]] = None


class CapabilityMatch(BaseModel):
    agent_name: str
    cap_id: str
    locality: Locality
    cost: float
    kind: str = "local"
    backing: str = "llm_backed"
    score: float = 1.0
    category_hash: Optional[str] = None


def locality_of(config: Optional[RoostAgentConfig], *, kind: str, local_host_id: Optional[str]) -> Locality:
    """Classify where an agent runs relative to the caller (rules in Key Constraints)."""
    raise NotImplementedError  # FILL IN


def rank(matches: Iterable[CapabilityMatch]) -> list[CapabilityMatch]:
    """Stable sort by (locality, cost, -score)."""
    return sorted(matches, key=lambda m: (int(m.locality), m.cost, -m.score))
```
**Why**: `category_hash` on `CapabilityMatch` is an additive field needed by gate L-S3 ('returns the HR agent and its category hash'); everything else is the spec skeleton verbatim.

### FILL IN checklist
- [ ] `locality_of` — bounded by Key Constraints
- [ ] tests

---

## Acceptance Criteria

- [ ] `rank()` orders by locality then cost then score
- [ ] `locality_of` classifies a2a/squawk as REMOTE and a matching host_id as SAME_HOST
- [ ] `parrot.roost.directory` imports no `parrot.registry` module
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/directory.py packages/ai-parrot/tests/roost/test_directory.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/roost/test_directory.py -q`

---

## Test Specification

```python
from parrot.roost.directory import CapabilityMatch, Locality, RoostAgentConfig, locality_of, rank
from parrot.roost.performatives import CarrierKind


def test_rank_order():
    ms = [CapabilityMatch(agent_name="r", cap_id="x", locality=Locality.REMOTE, cost=0.1),
          CapabilityMatch(agent_name="l2", cap_id="x", locality=Locality.IN_PROCESS, cost=2),
          CapabilityMatch(agent_name="l1", cap_id="x", locality=Locality.IN_PROCESS, cost=1)]
    assert [m.agent_name for m in rank(ms)] == ["l1", "l2", "r"]


def test_locality_rules():
    assert locality_of(None, kind="squawk", local_host_id=None) == Locality.REMOTE
    cfg = RoostAgentConfig(carrier=CarrierKind.SAME_HOST, host_id="h1")
    assert locality_of(cfg, kind="local", local_host_id="h1") == Locality.SAME_HOST
    assert locality_of(cfg, kind="local", local_host_id="h2") == Locality.SAME_NETWORK
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4715 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (FEAT-747 execution 0b6f3a52)
**Date**: 2026-10-26
**Notes**: Directory models delivered; merge-tier run exposed an order-dependent test (sys.modules assert); fixed in da2bea1c7 via subprocess check. feedback coder-feedback:9893254ec2f920571b1b7ff9.
Seat: gpt-5.6-sol (codex) · Attempts: 1

**Deviations from spec**: none beyond the test fix
