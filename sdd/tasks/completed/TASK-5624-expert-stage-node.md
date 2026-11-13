# TASK-5624: ExpertStageNode — subagent / mob / inline execution, gate opening, episodes

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-5613, TASK-5620, TASK-5621, TASK-5622, TASK-5623
**Assigned-to**: unassigned

---

## Context

Spec §2.3 / Module 4, AC7. The `expert_stage` node runs inside AgentsFlow; `pipeline` is NOT executed here (the compiler, TASK-5625, expands it into a chain of nodes).

---

## Scope

- Create `experts/stages/node.py` with `@register_node("expert_stage", config_model=ExpertStageConfig) class ExpertStageNode(Node)`; inject `ExpertRegistry` and optional `GateHost` via node deps/ctx (decide and document).
- subagent: one expert; mob: `asyncio.gather` with per-expert attribution, then synthesis (reuse `SynthesisNode` logic or a synthesis prompt on a lightweight call — decide), skip failures unless `strict`; inline: resolve the conductor agent, `build_inline_conductor`, ask once.
- After the run: `record_episode` per expert (best effort); if `config.gate` → `GateHost.open(...)` and return a NodeResult that pauses the flow (follow how InteractiveDecisionNode pauses).
- `stages/__init__.py` imports node.py so registration happens on import.
- Tests with fake experts (no LLM).

**NOT in scope**: Scope compiler (TASK-5625); CLI (TASK-5627).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/stages/__init__.py` | CREATE | import side-effect registration |
| `packages/ai-parrot/src/parrot/experts/stages/node.py` | CREATE | ExpertStageNode |
| `packages/ai-parrot/tests/experts/test_stage_node.py` | CREATE | tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from parrot.bots.flows.flow.flow import register_node  # verified: flow.py:161
from parrot.bots.flows.core.node import Node  # verified: core/node.py:68
from parrot.bots.flows.core import FlowContext  # verified: core/__init__.py:43
from parrot.experts.activation import activate_expert  # activation.py:15 (+mode from TASK-5621)
from parrot.experts.registry import ExpertRegistry  # registry.py:27
from parrot.experts.grid.models import ExpertStageConfig  # TASK-5620
from parrot.experts.stages.inline import build_inline_conductor  # TASK-5623
from parrot.experts.knowledge.sources.episodes import Episode, record_episode  # TASK-5622
from parrot.bots.flows.core.gates import GateHost  # TASK-5613
```

### Existing Signatures to Use
```python
def register_node(name: str, *, config_model: Optional[Type[BaseModel]] = None) -> Callable[[Type[Node]], Type[Node]]  # flow.py:161
class Node(BaseModel)  # core/node.py:68 — frozen, abstract `name`
async def execute(self, ctx: "FlowContext", deps: DependencyResults, **kwargs: Any) -> Any  # AgentNode.execute, core/node.py:281 (pattern)
class SynthesisNode(Node)  # flow.py:2609
def get(self, name: str, *, tenant: str | None = None) -> ExpertAgent  # registry.py:140
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop` imports inside `parrot/bots/flows/core/gates/` or `parrot/experts/`~~ — forbidden (spec Decisions `gate-core-independent-of-dev-loop`).
- ~~HelixDB client / `HelixGateStore`~~ — no client in the repo; spec §8 Q1 open — do NOT implement.
- ~~`ExpertManifest.stage`~~, ~~`RosterSeat.tier`~~, ~~`WikiSource.remember`~~, ~~`DecisionService.propose`/`.record`~~ — do not exist.
- ~~`ExpertRegistry.get` is async~~ — it is sync (registry.py:140).
- Read flow.py around NODE_CONFIG_MODELS (:144) and from_definition (:607) to see how config_model reaches the node instance before writing the constructor.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/experts/stages/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/experts/stages/node.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/experts/test_stage_node.py",
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
1. Read flow.py 130–200 and 600–720 and the InteractiveDecisionNode pause mechanism.
2. Write node.py + __init__.py.
3. Tests: each mode with fake ExpertAgents (`ask` returning canned AIMessage-like objects), strict vs non-strict mob, gate opened with a fake store.

### Blocks

```python
# packages/ai-parrot/src/parrot/experts/stages/node.py  (CREATE)
"""expert_stage AgentsFlow node (FEAT-890 M4)."""
from __future__ import annotations
import asyncio, hashlib, logging
from typing import Any
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.flow.flow import register_node
from parrot.experts.activation import activate_expert
from parrot.experts.grid.models import ExpertStageConfig
from parrot.experts.knowledge.sources.episodes import Episode, record_episode
from parrot.experts.stages.inline import build_inline_conductor

logger = logging.getLogger(__name__)

@register_node("expert_stage", config_model=ExpertStageConfig)
class ExpertStageNode(Node):
    """Run one scope-grid stage with its experts."""
    # FILL IN: fields per how NODE_CONFIG_MODELS injects config (flow.py:144/607) — e.g. config: ExpertStageConfig

    @property
    def name(self) -> str:
        return f"expert_stage:{self.config.stage}"  # FILL IN: align with field name chosen above

    async def execute(self, ctx: Any, deps: Any, **kwargs: Any) -> Any:
        """Dispatch on config.mode; record episodes; open the gate when configured."""
        # FILL IN: subagent / mob / inline; 'pipeline' here → ValueError (compiler expands it)
```
**Why**: registration by import side effect matches the existing NODE_REGISTRY pattern (flow.py:161).

### FILL IN checklist
- [ ] dependency injection of registry/gate host
- [ ] mob synthesis approach
- [ ] pause semantics on gate
- [ ] tests

---

## Acceptance Criteria

- [ ] AC7 (subagent, mob, inline at node level).
- [ ] Episodes recorded per expert; span attrs via activate_expert(mode=...).

## Validation Commands
- `pytest packages/ai-parrot/tests/experts/test_stage_node.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5624 expert-stages-and-delegation verified`.

---

## Completion Note


- Task: TASK-5624
- Feature: expert-stages-and-delegation
- Implementation SHA: 7e4d0f8a3f9850cff4030e5520e3cb07fafb10bb
- Closed at (UTC): 2026-11-13T22:24:23+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: opus · Backend: native · Model: opus · Attempts: 1 · Duration: n/a · Tokens: n/a |
