# TASK-5623: Inline mode — build_inline_conductor on a cloned PromptBuilder

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2.3 inline mode, AC7: the conductor keeps its identity; each expert's rules/knowledge are installed under per-expert layer names; rule-id clashes are an error; the conductor's own builder is never mutated (FEAT-778 S2).

---

## Scope

- Create `experts/stages/inline.py` with `build_inline_conductor(builder, contexts: Mapping[str, KnowledgeContext]) -> PromptBuilder`.
- Clone first; rename layers per expert (`expert_rules:<slug>`, `expert_knowledge:<slug>`); drop each expert's identity layer (conductor identity wins).
- Raise `ScopeGridError(INVALID)`-free plain `ValueError`? NO — raise `InlineCompositionError` defined here on duplicate rule ids.
- Tests: original builder unchanged; layers present; clash raises.

**NOT in scope**: The stage node itself (TASK-5624).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/stages/inline.py` | CREATE | inline composition |
| `packages/ai-parrot/tests/experts/test_stage_inline.py` | CREATE | tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from parrot.experts.knowledge.render import install_layers  # verified: render.py:54
from parrot.experts.models import KnowledgeContext  # verified: models.py:149
```

### Existing Signatures to Use
```python
def install_layers(builder: PromptBuilder, ctx: KnowledgeContext) -> PromptBuilder  # experts/knowledge/render.py:54
def clone(self) -> PromptBuilder  # bots/prompts/builder.py:253
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop` imports inside `parrot/bots/flows/core/gates/` or `parrot/experts/`~~ — forbidden (spec Decisions `gate-core-independent-of-dev-loop`).
- ~~HelixDB client / `HelixGateStore`~~ — no client in the repo; spec §8 Q1 open — do NOT implement.
- ~~`ExpertManifest.stage`~~, ~~`RosterSeat.tier`~~, ~~`WikiSource.remember`~~, ~~`DecisionService.propose`/`.record`~~ — do not exist.
- ~~`experts/stages/__init__.py`~~ — created by TASK-5624; this task does not create it (namespace import is fine for tests).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/experts/stages/inline.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/experts/test_stage_inline.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Conventions: `.claude/rules/codebase-conventions.md` (Pydantic v2, Google docstrings, `self.logger`, async I/O, no print).
- Worktree tests need `PYTHONPATH=packages/ai-parrot/src` (plus `packages/ai-parrot-integrations/src` / `packages/ai-parrot-tools/src` when touched).

---

## Implementation Blueprint

### Steps (in order)
1. Read render.py fully.
2. Write inline.py.
3. Tests with a real PromptBuilder and two synthetic KnowledgeContexts.

### Blocks

```python
# packages/ai-parrot/src/parrot/experts/stages/inline.py  (CREATE)
"""Inline multi-expert composition into a conductor (FEAT-890 M4)."""
from __future__ import annotations
from typing import Mapping
from parrot.experts.knowledge.render import install_layers
from parrot.experts.models import KnowledgeContext

class InlineCompositionError(Exception):
    """Two inlined experts declare the same rule id."""

def build_inline_conductor(builder: "PromptBuilder", contexts: Mapping[str, KnowledgeContext]) -> "PromptBuilder":
    """Return a clone of ``builder`` with every expert's layers under per-expert names."""
    composed = builder.clone()
    # FILL IN: read render.py to learn which layer names install_layers writes (expert_rules / expert_knowledge / identity);
    #          install each ctx on a scratch clone, then copy its layers into `composed` renamed with ':<slug>';
    #          skip identity; detect duplicate rule ids across experts → InlineCompositionError
    return composed
```
**Why**: installing on a scratch clone and copying renamed layers avoids touching install_layers (FEAT-778 code).

### FILL IN checklist
- [ ] layer copy/rename mechanics
- [ ] rule-id extraction
- [ ] tests

---

## Acceptance Criteria

- [ ] AC7 inline parts (no mutation, clash error).

## Validation Commands
- `pytest packages/ai-parrot/tests/experts/test_stage_inline.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5623 expert-stages-and-delegation verified`.

---

## Completion Note


- Task: TASK-5623
- Feature: expert-stages-and-delegation
- Implementation SHA: ee29b636b6966482af372aabf320a238b1242fbf
- Closed at (UTC): 2026-11-13T22:01:22+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a |
