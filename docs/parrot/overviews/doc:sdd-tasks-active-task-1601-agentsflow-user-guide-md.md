---
type: Wiki Overview
title: 'TASK-1601: AgentsFlow User Guide Documentation'
id: doc:sdd-tasks-active-task-1601-agentsflow-user-guide-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 1. **What is AgentsFlow?** — DAG-first executor with per-node FSM, event-driven
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.flow.definition
  rel: mentions
- concept: mod:parrot.bots.flows.flow.flow
  rel: mentions
---

# TASK-1601: AgentsFlow User Guide Documentation

**Feature**: FEAT-249 — Update AgentCrew & AgentsFlow Documentation
**Spec**: `sdd/specs/update-agentcrew-agentflow-documentation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1599
**Assigned-to**: unassigned

---

## Context

> This task implements Module 2 from the spec. It creates the comprehensive
> AgentsFlow User Guide — the first user-facing documentation for AI-Parrot's
> DAG-first flow executor. Currently there is NO dedicated AgentsFlow
> documentation; the only related page (`DECISION_NODE_USAGE.md`) covers a
> single node type. This guide fills that gap entirely.

---

## Scope

- Create `docs/orchestration/agentsflow.md` with the following sections:

  1. **What is AgentsFlow?** — DAG-first executor with per-node FSM, event-driven
     wave scheduling. How it differs from AgentCrew's `run_flow()` mode.
  2. **Quick Start** — Minimal linear flow: 2 agents, `add_node()`, `add_edge()`,
     `run_flow()`.
  3. **Building a Flow Programmatically** — `add_node()`, `add_edge()`,
     edge conditions (`always`, `on_success`, `on_error`, `on_timeout`,
     `on_condition`), predicates (callable or CEL expression), `FlowEdge`.
  4. **Building from a Definition** — `FlowDefinition`, `NodeDefinition`,
     `EdgeDefinition`, `from_definition()`, JSON format example.
  5. **Running a Flow** — `run_flow()`, `FlowContext` (as string or object),
     `FlowResult` structure, `on_complete` callbacks.
  6. **Node Lifecycle & Events** — Per-node FSM states
     (`idle → ready → running → completed/failed/blocked`),
     `add_node_event_listener()`, event types
     (`flow_started`, `node_started`, `node_completed`, `node_failed`,
     `node_skipped`, `flow_completed`).
  7. **Pre/Post Actions** — `Node.add_pre_action()`, `Node.add_post_action()`,
     action callbacks.
  8. **Conditional Routing** — Branching patterns with `on_condition` edges,
     fan-out/fan-in topology, the known limitation with multiple terminal
     nodes (link to `DECISION_NODE_USAGE.md` for workarounds).
  9. **Error Handling & Retries** — `on_error` edges, retry policies,
     `on_timeout` edges.
  10. **Comparison: AgentCrew.run_flow vs AgentsFlow.run_flow** — Feature
      comparison table.

- Cross-reference `docs/orchestration/node-types.md` for node type details.

**NOT in scope**:
- Modifying any Python source code
- Rewriting `docs/DECISION_NODE_USAGE.md`
- Updating `mkdocs.yml` (that's TASK-1602)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/orchestration/agentsflow.md` | CREATE | AgentsFlow User Guide |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Primary import path
from parrot.bots.flows import (
    AgentsFlow,
    FlowDefinition, NodeDefinition, EdgeDefinition,
    Node, AgentNode, StartNode, EndNode,
    FlowResult, FlowContext,
    DecisionFlowNode, BinaryDecision,
)
# verified: packages/ai-parrot/src/parrot/bots/flows/__init__.py:13-22,74-78

# Edge conditions and registry (for documentation reference)
from parrot.bots.flows.flow.flow import (
    EDGE_CONDITIONS,    # line 78
    NODE_REGISTRY,      # line 106
    FlowEdge,           # line 82
    register_node,      # line 115
)
# verified: packages/ai-parrot/src/parrot/bots/flows/flow/flow.py

# Flow definition models
from parrot.bots.flows.flow.definition import (
    FlowDefinition,    # line 289
    NodeDefinition,    # line 125
    EdgeDefinition,    # line 188
)
# verified: packages/ai-parrot/src/parrot/bots/flows/flow/definition.py

# Agent types for examples
from parrot.bots import Agent
# verified: packages/ai-parrot/src/parrot/bots/__init__.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
class AgentsFlow(PersistenceMixin):  # line 157
    def add_node(self, node: Node) -> None:  # line 224
    def add_edge(self, from_: str, to: str,
                 condition: str = "always",
                 predicate: Optional[Union[str, Callable]] = None) -> FlowEdge:  # line 241
    def add_node_event_listener(self, callback: Callable) -> None:  # line 297
    async def run_flow(self, ctx: Optional[Union[FlowContext, str]] = None,
                       *, on_complete: Tuple[...] = ()) -> FlowResult:  # line 663
    @classmethod
    def from_definition(cls, definition: FlowDefinition, *,
                        agent_registry: Optional[AgentRegistry] = None) -> "AgentsFlow":  # line 352

# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
EDGE_CONDITIONS = ("always", "on_success", "on_error", "on_timeout", "on_condition")  # line 78

@dataclass
class FlowEdge:  # line 82
    from_: str
    to: str
    condition: str = "always"
    predicate: Optional[Union[str, Callable[[Any], bool]]] = None

# packages/ai-parrot/src/parrot/bots/flows/flow/definition.py
class NodeDefinition(BaseModel):  # line 125
class EdgeDefinition(BaseModel):  # line 188
class FlowDefinition(BaseModel):  # line 289

# packages/ai-parrot/src/parrot/bots/flows/core/node.py
class Node(BaseModel):  # line 68
    def add_pre_action(self, action: ActionCallback) -> None:   # line 126
    def add_post_action(self, action: ActionCallback) -> None:  # line 134

class AgentNode(Node):  # line 182
    async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs) -> NodeResult:
```

### Does NOT Exist

- ~~`AgentsFlow.add_agent()`~~ — method is `add_node()`, not `add_agent()`
- ~~`AgentsFlow.on_condition()`~~ — not a method; use `add_edge()` with `condition="on_condition"` and a `predicate`
- ~~`AgentsFlow.run()`~~ — method is `run_flow()`, not `run()`
- ~~`AgentsFlow.set_start_node()`~~ — no such method; add a `StartNode` via `add_node()`
- ~~`parrot.bots.flows.flow.flow.ConditionalNode`~~ — no such class
- ~~`parrot.bots.flows.flow.flow.TransitionNode`~~ — no such class
- ~~`FlowEdge.weight`~~ — FlowEdge has no weight attribute

---

## Implementation Notes

### Pattern to Follow

Structure each section with explanation → parameters → complete example →
output/notes. Build complexity gradually:

```markdown
## Section Title

> Brief explanation of the concept.

### Subsection

**Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|

**Example:**
\`\`\`python
# Complete, runnable example
\`\`\`
```

### Key Constraints

- The comparison table at the end (§10) must be consistent with the one in
  TASK-1600's AgentCrew guide. Use the same columns and criteria.
- Use mermaid diagrams for:
  - Wave scheduling (how nodes dispatch in waves)
  - Fan-out/fan-in topology examples
  - Conditional routing patterns
- When documenting the known limitation with conditional branches and
  multiple terminal nodes, link to `docs/DECISION_NODE_USAGE.md` §Solutions.
- Import paths must use `from parrot.bots.flows import AgentsFlow`.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` — main AgentsFlow class (1.3k lines)
- `packages/ai-parrot/src/parrot/bots/flows/flow/definition.py` — FlowDefinition models
- `packages/ai-parrot/src/parrot/bots/flows/core/node.py` — base Node classes
- `packages/ai-parrot/src/parrot/bots/flows/core/fsm.py` — AgentTaskMachine FSM
- `packages/ai-parrot/src/parrot/bots/flows/core/context.py` — FlowContext
- `packages/ai-parrot/src/parrot/bots/flows/core/result.py` — FlowResult, NodeResult
- `examples/decision_workflow_example.py` — flow with decision nodes
- `docs/architecture/08-agentsflow-dag.md` — internal architecture reference
- `docs/DECISION_NODE_USAGE.md` — decision node known limitations

---

## Acceptance Criteria

- [ ] `docs/orchestration/agentsflow.md` exists with all ten sections from the scope
- [ ] Programmatic flow construction documented with `add_node()` / `add_edge()` examples
- [ ] Definition-based construction documented with `FlowDefinition` / `from_definition()`
- [ ] All five edge conditions documented with examples
- [ ] Event listener system documented (`add_node_event_listener`, event types)
- [ ] Conditional routing patterns documented with known limitation referenced
- [ ] All import paths match verified imports (no old paths)
- [ ] Cross-references to `docs/orchestration/node-types.md` work
- [ ] Comparison table: AgentCrew.run_flow vs AgentsFlow.run_flow included
- [ ] `mkdocs build --strict` passes (can be tested by temporarily adding to nav)

---

## Test Specification

```bash
# Build docs with the new file
source .venv/bin/activate
mkdocs build --strict 2>&1 | grep -i "error\|warning"

# Verify no old/incorrect class names
grep -n "FSM workflow\|state machine workflow\|add_agent\b" docs/orchestration/agentsflow.md
# Expected: no output (AgentsFlow is DAG-based, uses add_node not add_agent)

# Verify import paths are current
grep -oP 'from parrot\.\S+' docs/orchestration/agentsflow.md | sort -u | while read imp; do
  module=$(echo "$imp" | sed 's/from //' | tr '.' '/')
  [ ! -d "packages/ai-parrot/src/$module" ] && [ ! -f "packages/ai-parrot/src/${module}.py" ] && echo "BAD IMPORT: $imp"
done
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/update-agentcrew-agentflow-documentation.spec.md`
2. **Check dependencies** — verify TASK-1599 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports and signatures are still accurate
4. **Read `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`** for the full AgentsFlow API
5. **Read `packages/ai-parrot/src/parrot/bots/flows/flow/definition.py`** for FlowDefinition models
6. **Read existing examples** in `examples/decision_workflow_example.py`
7. **Read `docs/architecture/08-agentsflow-dag.md`** for architecture context
8. **Write** `docs/orchestration/agentsflow.md` following the scope above
9. **Verify** all acceptance criteria are met
10. **Move this file** to `sdd/tasks/completed/TASK-1601-agentsflow-user-guide.md`
11. **Update index** → `"done"`
12. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
