---
type: Wiki Overview
title: 'TASK-1599: Node Types Reference Documentation'
id: doc:sdd-tasks-active-task-1599-node-types-reference-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: for every registered node type in AI-Parrot's orchestration layer.
relates_to:
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.crew.nodes
  rel: mentions
- concept: mod:parrot.bots.flows.flow.flow
  rel: mentions
- concept: mod:parrot.bots.flows.flow.nodes
  rel: mentions
---

# TASK-1599: Node Types Reference Documentation

**Feature**: FEAT-249 — Update AgentCrew & AgentsFlow Documentation
**Spec**: `sdd/specs/update-agentcrew-agentflow-documentation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 3 from the spec. It creates the Node Types
> Reference page that both the AgentCrew and AgentsFlow guides will
> cross-reference. It is done first because Modules 1 and 2 link to it.

---

## Scope

- Create `docs/orchestration/node-types.md` with comprehensive documentation
  for every registered node type in AI-Parrot's orchestration layer.
- Document the Node Registry mechanism (`NODE_REGISTRY`, `@register_node`).
- Document each node type with its fields, configuration, and usage pattern:
  - `Node` (abstract base)
  - `AgentNode` (`"agent"`)
  - `StartNode` (`"start"`)
  - `EndNode` (`"end"`)
  - `DecisionNode` (`"decision"`) — all three modes (CIO, BALLOT, CONSENSUS)
  - `InteractiveDecisionFlowNode` (`"interactive_decision"`)
  - `SynthesisNode` (`"synthesis"`)
  - `CrewAgentNode` (crew-specific, for advanced users)
- Document how to create custom nodes by subclassing `Node` and using
  `@register_node`.
- Include code examples showing how each node type is instantiated and used
  within an `AgentsFlow`.
- Link to the existing `docs/DECISION_NODE_USAGE.md` for the DecisionFlowNode
  deep-dive.

**NOT in scope**:
- Modifying any Python source code
- Rewriting `docs/DECISION_NODE_USAGE.md`
- Updating `mkdocs.yml` (that's TASK-1602)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/orchestration/node-types.md` | CREATE | Node Types Reference page |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.

### Verified Imports

```python
# Primary import path for all node types
from parrot.bots.flows import (
    Node, AgentNode, StartNode, EndNode,
    DecisionFlowNode, BinaryDecision,
)
# verified: packages/ai-parrot/src/parrot/bots/flows/__init__.py:13-22

# Decision configuration types
from parrot.bots.flows.flow.nodes import (
    DecisionFlowNode,          # line 253
    DecisionNodeConfig,        # line 213
    DecisionMode,              # line 50 — CIO, BALLOT, CONSENSUS
    DecisionType,              # line 58 — BINARY, APPROVAL, MULTI_CHOICE, CUSTOM
    DecisionResult,            # line 139
    BinaryDecision,            # line 81
    ApprovalDecision,          # line 95
    MultiChoiceDecision,       # line 116
    EscalationPolicy,          # line 182
    VoteWeight,                # line 67 — EQUAL, SENIORITY, CONFIDENCE, CUSTOM
)
# verified: packages/ai-parrot/src/parrot/bots/flows/flow/nodes.py

# Node registry and edge infrastructure
from parrot.bots.flows.flow.flow import (
    EDGE_CONDITIONS,           # line 78
    NODE_REGISTRY,             # line 106  (read-only, for documentation purposes)
    register_node,             # line 115
)
# verified: packages/ai-parrot/src/parrot/bots/flows/flow/flow.py

# Crew-specific node
from parrot.bots.flows.crew.nodes import CrewAgentNode  # line 28
# verified: packages/ai-parrot/src/parrot/bots/flows/crew/nodes.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flows/core/node.py
class Node(BaseModel):  # line 68 — frozen Pydantic model
    node_id: str
    # PrivateAttr: _pre_actions, _post_actions, _logger
    def add_pre_action(self, action: ActionCallback) -> None:   # line 126
    def add_post_action(self, action: ActionCallback) -> None:  # line 134
    async def run_pre_actions(self, prompt: str = "", **ctx) -> None:  # line 144

class AgentNode(Node):  # line 182
    agent: AgentLike
    dependencies: Set[str]
    successors: Set[str]
    fsm: Optional[AgentTaskMachine]
    timeout: Optional[float]
    async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs) -> NodeResult:  # ~line 250

class StartNode(Node):  # line 323 — name defaults to '__start__'

class EndNode(Node):    # line 408 — name defaults to '__end__'

# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
@register_node("decision")
class DecisionNode(Node):  # line 1053
    decision_config: DecisionNodeConfig
    agents: Dict[str, Any]

@register_node("interactive_decision")
class InteractiveDecisionFlowNode(Node):  # line 1129

@register_node("synthesis")
class SynthesisNode(Node):  # line 1208

# packages/ai-parrot/src/parrot/bots/flows/crew/nodes.py
class CrewAgentNode(AgentNode):  # line 28
    def _build_prompt(self, ctx: FlowContext, deps: DependencyResults) -> str:  # line 44
    @staticmethod
    def _format(input_data: Dict[str, Any]) -> str:  # line 68
```

### Node Registry (verified at flow.py:1052-1290)

| Registry Key | Class | Source |
|---|---|---|
| `"agent"` | `AgentNode` | `core/node.py:182` |
| `"start"` | `StartNode` | `core/node.py:323` |
| `"end"` | `EndNode` | `core/node.py:408` |
| `"decision"` | `DecisionNode` | `flow/flow.py:1053` |
| `"interactive_decision"` | `InteractiveDecisionFlowNode` | `flow/flow.py:1129` |
| `"synthesis"` | `SynthesisNode` | `flow/flow.py:1208` |

### Edge Conditions (verified at flow.py:78)

```python
EDGE_CONDITIONS = ("always", "on_success", "on_error", "on_timeout", "on_condition")
```

### Does NOT Exist

- ~~`parrot.bots.flows.flow.flow.ConditionalNode`~~ — no such class; conditional routing is done via `add_edge()` with `condition="on_condition"`
- ~~`parrot.bots.flows.flow.flow.TaskNode`~~ — no such class; use `AgentNode`
- ~~`parrot.bots.flows.flow.flow.BranchNode`~~ — no such class
- ~~`Node.run()`~~ — the method is `execute()`, not `run()`
- ~~`AgentsFlow.add_agent()`~~ — method is `add_node()`, not `add_agent()`

---

## Implementation Notes

### Pattern to Follow

Use the style of `docs/architecture/08-agentsflow-dag.md` for technical depth
but target a user-facing audience — more "how to use" than "how it works
internally". Structure each node type section consistently:

```markdown
### NodeType (`"registry_key"`)

> One-line description.

**Fields:**
| Field | Type | Description |
|---|---|---|

**Usage:**
\`\`\`python
# Complete example
\`\`\`

**Notes:**
- Important behavior details
```

### Key Constraints

- Include mermaid diagrams where helpful (e.g., showing the node registry
  dispatch, or a flow with multiple node types).
- Use `pymdownx.tabbed` for alternative examples where appropriate.
- Use `!!! tip`, `!!! warning`, `!!! note` admonitions for callouts.
- All imports must match the Verified Imports above exactly.
- Link to `DECISION_NODE_USAGE.md` for the DecisionFlowNode deep-dive:
  `[Decision Node Usage Guide](../DECISION_NODE_USAGE.md)`

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/core/node.py` — base Node, AgentNode, StartNode, EndNode
- `packages/ai-parrot/src/parrot/bots/flows/flow/nodes.py` — DecisionFlowNode, decision types/enums
- `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` — registered wrappers (DecisionNode, InteractiveDecisionFlowNode, SynthesisNode), NODE_REGISTRY
- `packages/ai-parrot/src/parrot/bots/flows/crew/nodes.py` — CrewAgentNode
- `examples/decision_workflow_example.py` — DecisionNode usage example
- `examples/decision_simple_working.py` — Minimal decision example

---

## Acceptance Criteria

- [ ] `docs/orchestration/node-types.md` exists with all six registered node types documented
- [ ] CrewAgentNode documented for advanced users
- [ ] Custom node creation section with `@register_node` example
- [ ] All import paths match verified imports above
- [ ] Each node type section includes a code example
- [ ] Links to `docs/DECISION_NODE_USAGE.md` for deep-dive on DecisionFlowNode
- [ ] `mkdocs build --strict` passes (can be tested by temporarily adding to nav)

---

## Test Specification

```bash
# Build docs with the new file (temporarily add to mkdocs.yml nav)
source .venv/bin/activate
mkdocs build --strict 2>&1 | grep -i "error\|warning"

# Verify no broken internal links
grep -n '\]\(.*\.md\)' docs/orchestration/node-types.md | while read line; do
  file=$(echo "$line" | grep -oP '\(\.\.?/[^)]+\)' | tr -d '()')
  [ -n "$file" ] && [ ! -f "docs/orchestration/$file" ] && [ ! -f "docs/$file" ] && echo "BROKEN: $line"
done

# Verify all import paths are current
grep -oP 'from parrot\.\S+' docs/orchestration/node-types.md | sort -u | while read imp; do
  module=$(echo "$imp" | sed 's/from //' | tr '.' '/')
  [ ! -d "packages/ai-parrot/src/$module" ] && [ ! -f "packages/ai-parrot/src/${module}.py" ] && echo "BAD IMPORT: $imp"
done
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/update-agentcrew-agentflow-documentation.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY documentation:
   - Confirm every import in "Verified Imports" still exists
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Read `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` to verify NODE_REGISTRY entries
   - If anything has changed, update the contract FIRST, then write docs
4. **Read existing examples** at `examples/decision_workflow_example.py` and `examples/decision_simple_working.py` for reference patterns
5. **Create** `docs/orchestration/` directory if it doesn't exist
6. **Write** `docs/orchestration/node-types.md` following the scope above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-1599-node-types-reference.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
