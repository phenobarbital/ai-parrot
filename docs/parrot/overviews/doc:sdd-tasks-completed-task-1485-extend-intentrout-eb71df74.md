---
type: Wiki Overview
title: 'TASK-1485: Extend IntentRouterConfig with output-mode routing fields'
id: doc:sdd-tasks-completed-task-1485-extend-intentrouterconfig-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 2. Adds the configuration fields the output-mode
relates_to:
- concept: mod:parrot.registry.capabilities.models
  rel: mentions
---

# TASK-1485: Extend IntentRouterConfig with output-mode routing fields

**Feature**: FEAT-224 — IntentRouterMixin Embedding-Based Output-Mode Routing
**Spec**: `sdd/specs/intent-router-mixin-embedding-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2. Adds the configuration fields the output-mode
router needs (model name, phrase bank, threshold, margin, activation flag) to
the EXISTING `IntentRouterConfig`, without touching the existing retrieval-
routing fields (no regression to TASK-unrelated behavior).

---

## Scope

- Add five fields to `IntentRouterConfig` (`registry/capabilities/models.py`):
  - `enable_output_mode_routing: bool = False`
  - `embedding_model: str = "intfloat/multilingual-e5-small"`
  - `output_mode_routes: dict[str, list[str]] = {}` (keys are `OutputMode` *values* as strings)
  - `output_mode_threshold: float = 0.55` (ge=0.0, le=1.0)
  - `discrepancy_margin: float = 0.05` (ge=0.0, le=1.0)
- Keep all existing fields and their defaults unchanged.
- Add a unit test asserting new defaults and that existing fields are intact.

**NOT in scope**: the engine, the mixin, RequestContext, the base hook. Do not
add validation that parses `output_mode_routes` keys into `OutputMode` here —
the mixin (TASK-1488) maps strings to `OutputMode` at configure time.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/capabilities/models.py` | MODIFY | Add 5 fields to `IntentRouterConfig` (Pydantic v2) |
| `packages/ai-parrot/tests/registry/test_intentrouterconfig_outputmode.py` | CREATE | defaults + back-compat assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.registry.capabilities.models import IntentRouterConfig  # verified: registry/capabilities/models.py:149
from pydantic import BaseModel, Field                               # IntentRouterConfig is a pydantic BaseModel
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/registry/capabilities/models.py:149
class IntentRouterConfig(BaseModel):
    confidence_threshold: float = Field(0.7, ge=0.0, le=1.0)   # ~line 171
    hitl_threshold: float = Field(0.3, ge=0.0, le=1.0)
    strategy_timeout_s: float = Field(30.0, gt=0.0)
    exhaustive_mode: bool = Field(False)
    max_cascades: int = Field(3, ge=1, le=10)
    custom_keywords: dict[str, str] = Field(default_factory=dict)
    # ADD the 5 new fields AFTER these — do not reorder/rename existing ones.
```

### Does NOT Exist
- ~~`IntentRouterConfig.embedding_model`~~ / ~~`.output_mode_routes`~~ /
  ~~`.output_mode_threshold`~~ / ~~`.discrepancy_margin`~~ /
  ~~`.enable_output_mode_routing`~~ — none exist yet; this task adds them.
- ~~`OutputModeRouterConfig`~~ — do not create a separate config class; extend the existing one.

---

## Implementation Notes

### Pattern to Follow
```python
# append inside class IntentRouterConfig (Pydantic v2 — uses Field, ge/le already used in this file)
enable_output_mode_routing: bool = Field(
    False, description="Activate the deterministic output-mode router")
embedding_model: str = Field(
    "intfloat/multilingual-e5-small", description="SentenceTransformer model id")
output_mode_routes: dict[str, list[str]] = Field(
    default_factory=dict,
    description="Phrase bank: OutputMode value (str) -> reference utterances")
output_mode_threshold: float = Field(
    0.55, ge=0.0, le=1.0, description="Min max-cosine to accept a route; below -> abstain")
discrepancy_margin: float = Field(
    0.05, ge=0.0, le=1.0, description="If (best-second) < margin, consult the LLM tie-breaker")
```

### Key Constraints
- Pydantic v2 conventions already in this file — mirror them (`Field`, `ge`, `le`).
- Defaults must keep `enable_output_mode_routing=False` so existing configs are unaffected.

---

## Acceptance Criteria

- [ ] All 5 fields present with the exact defaults above.
- [ ] Existing fields unchanged (`confidence_threshold`, `hitl_threshold`,
      `strategy_timeout_s`, `exhaustive_mode`, `max_cascades`, `custom_keywords`).
- [ ] `IntentRouterConfig()` constructs with defaults; `enable_output_mode_routing is False`.
- [ ] `pytest packages/ai-parrot/tests/registry/test_intentrouterconfig_outputmode.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/registry/capabilities/models.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/registry/test_intentrouterconfig_outputmode.py
from parrot.registry.capabilities.models import IntentRouterConfig


def test_new_outputmode_defaults():
    c = IntentRouterConfig()
    assert c.enable_output_mode_routing is False
    assert c.embedding_model == "intfloat/multilingual-e5-small"
    assert c.output_mode_routes == {}
    assert c.output_mode_threshold == 0.55
    assert c.discrepancy_margin == 0.05


def test_existing_fields_intact():
    c = IntentRouterConfig()
    assert c.confidence_threshold == 0.7
    assert c.hitl_threshold == 0.3
    assert c.max_cascades == 3
```

---

## Agent Instructions

Standard SDD flow. Verify the contract, implement, make tests pass, move file to
`completed/`, update index to `done`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Opus)
**Date**: 2026-06-05
**Notes**: Added 5 fields to `IntentRouterConfig` after `custom_keywords`. Existing
fields untouched. 3 unit tests pass. Pre-existing unrelated `F401 StoreScore` import
warning at models.py:22 left as-is (out of scope; not introduced by this task).
**Deviations from spec**: `output_mode_threshold` default 0.55 -> 0.85 (calibration
fix, see TASK-1484 — e5 cosines cluster high; 0.55 made abstain dead). Other 4 fields
exactly as specified.
