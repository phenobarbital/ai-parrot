---
type: Wiki Overview
title: 'Feature Specification: Update AgentCrew & AgentsFlow Documentation'
id: doc:sdd-specs-update-agentcrew-agentflow-documentation-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The public-facing documentation for AI-Parrot's orchestration layer (AgentCrew
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.crew.crew
  rel: mentions
- concept: mod:parrot.bots.flows.flow.definition
  rel: mentions
- concept: mod:parrot.bots.flows.flow.flow
  rel: mentions
- concept: mod:parrot.bots.flows.flow.nodes
  rel: mentions
- concept: mod:parrot.models.crew_definition
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Update AgentCrew & AgentsFlow Documentation

**Feature ID**: FEAT-249
**Date**: 2026-06-20
**Author**: Jesus Lara
**Status**: draft
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

The public-facing documentation for AI-Parrot's orchestration layer (AgentCrew
and AgentsFlow) is outdated, incomplete, and structurally fragmented:

1. **Outdated class names and imports**: `docs/crew.md` references
   `EnhancedAgentCrew` and `from parrot.bots.orchestration.crew import
   EnhancedAgentCrew` — the class is now `AgentCrew` in
   `parrot.bots.flows.crew.crew` (migrated in earlier FEATs).

2. **Incorrect architectural descriptions**: `docs/ORCHESTRATION.md` describes
   AgentsFlow as "FSM workflows" when it is actually a DAG-first executor
   with per-node FSM (fundamentally different semantics).

3. **Scattered pages**: Five separate files (`crew.md`, `ORCHESTRATION.md`,
   `orchestration.md`, `crew_summary.md`, `crew_handler.md`) cover overlapping
   topics with inconsistent depth and language (some Spanish, some English).

4. **Missing coverage**: No documentation explains what AgentsFlow is, what
   node types exist (AgentNode, StartNode, EndNode, DecisionNode,
   InteractiveDecisionNode, SynthesisNode), how to construct flows
   programmatically vs from definitions, or edge conditions.

5. **Single-topic focus**: The only dedicated "Orchestration & Flows" entry in
   the nav (`DECISION_NODE_USAGE.md`) covers only DecisionFlowNode and its
   known limitations — not the broader system.

6. **Published URL gap**: The current public URL
   (`https://phenobarbital.github.io/ai-parrot/docs/DECISION_NODE_USAGE/`)
   only shows the previous version of Decision Flow Node usage.

### Goals

- Provide a single, authoritative **AgentCrew User Guide** covering all four
  execution modes (sequential, parallel, flow, loop) with complete runnable
  examples.
- Provide a single, authoritative **AgentsFlow User Guide** covering DAG
  construction, all node types, edge conditions, event listeners, and the
  `from_definition()` factory with complete runnable examples.
- Provide a **Node Types Reference** documenting every registered node type,
  its configuration, and usage patterns.
- Consolidate the current 5+ scattered pages into the new structure, updating
  the mkdocs nav accordingly.
- All documentation in English.

### Non-Goals (explicitly out of scope)

- Rewriting the internal architecture docs (`docs/architecture/07-agentcrew.md`
  and `08-agentsflow-dag.md`) — those remain as architecture reference.
- Adding new features to AgentCrew or AgentsFlow code.
- Documenting the `OrchestratorAgent` or `A2AProxyRouter` in detail (they
  can keep their current pages).
- Auto-generated API reference from docstrings (mkdocstrings already handles
  that in `docs/api-reference/`).

---

## 2. Architectural Design

### Overview

This is a **documentation-only** feature. No Python code changes are required.
The deliverable is a set of Markdown files in `docs/` and an updated
`mkdocs.yml` nav section.

The new documentation structure replaces the scattered pages with three focused
guides under a renamed "Orchestration & Flows" nav section:

```
docs/
├── orchestration/
│   ├── agentcrew.md          # AgentCrew User Guide
│   ├── agentsflow.md         # AgentsFlow User Guide
│   └── node-types.md         # Node Types Reference
├── DECISION_NODE_USAGE.md    # kept as-is (linked from node-types.md)
```

### Component Diagram

```
mkdocs.yml nav
  └── "Orchestration & Flows"
        ├── AgentCrew Guide         → docs/orchestration/agentcrew.md
        ├── AgentsFlow Guide        → docs/orchestration/agentsflow.md
        ├── Node Types Reference    → docs/orchestration/node-types.md
        └── Decision Node Usage     → docs/DECISION_NODE_USAGE.md (existing)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `mkdocs.yml` | modifies | Update nav structure, remove old entries, add new ones |
| `docs/crew.md` | removes | Content superseded by `orchestration/agentcrew.md` |
| `docs/ORCHESTRATION.md` | removes | Content superseded by new guides |
| `docs/orchestration.md` | removes | Spanish-language page, superseded |
| `docs/crew_summary.md` | removes | Content folded into agentcrew.md |
| `docs/crew_handler.md` | keeps | Handler-specific, different audience |
| `docs/DECISION_NODE_USAGE.md` | keeps | Linked from node-types.md |
| `docs/architecture/07-agentcrew.md` | keeps | Internal architecture reference |
| `docs/architecture/08-agentsflow-dag.md` | keeps | Internal architecture reference |

### New Public Interfaces

N/A — documentation only.

### Data Models

N/A — documentation only.

---

## 3. Module Breakdown

### Module 1: AgentCrew User Guide

- **Path**: `docs/orchestration/agentcrew.md`
- **Responsibility**: Comprehensive user-facing guide for AgentCrew
- **Content outline**:
  1. **What is AgentCrew?** — High-level explanation, when to use it
  2. **Quick Start** — Minimal example creating a crew and running it
  3. **Creating a Crew** — Constructor parameters, `add_agent()`,
     `add_shared_tool()`, `from_definition()`
  4. **Execution Modes** — One section per mode with full runnable examples:
     - `run_sequential()` — pipeline, `pass_full_context`
     - `run_parallel()` — fan-out, task format, `all_results`
     - `run_flow()` — DAG with `task_flow()`, dependency declarations
     - `run_loop()` — iterative refinement, condition, `max_iterations`
     - `run()` — universal dispatcher
  5. **Results & Synthesis** — `FlowResult`, `summary()`, `get_agent_result()`
  6. **Hooks** — `on_complete()`, `on_error()` callbacks
  7. **Execution Memory** — `ExecutionMemory`, `get_memory_snapshot()`,
     `clear_memory()`
  8. **Visualization** — `visualize_workflow()`, `validate_workflow()`
  9. **When to Use AgentCrew vs AgentsFlow** — Decision table
- **Depends on**: none

### Module 2: AgentsFlow User Guide

- **Path**: `docs/orchestration/agentsflow.md`
- **Responsibility**: Comprehensive user-facing guide for AgentsFlow
- **Content outline**:
  1. **What is AgentsFlow?** — DAG-first executor, how it differs from
     AgentCrew's `run_flow()` mode
  2. **Quick Start** — Minimal linear flow example
  3. **Building a Flow Programmatically** — `add_node()`, `add_edge()`,
     edge conditions (`always`, `on_success`, `on_error`, `on_timeout`,
     `on_condition`), predicates (callable or CEL expression)
  4. **Building from a Definition** — `FlowDefinition`, `NodeDefinition`,
     `EdgeDefinition`, `from_definition()`, JSON format
  5. **Running a Flow** — `run_flow()`, `FlowContext`, `FlowResult`
  6. **Node Lifecycle & Events** — FSM states, `add_node_event_listener()`,
     event types (`flow_started`, `node_started`, `node_completed`, etc.)
  7. **Pre/Post Actions** — `add_pre_action()`, `add_post_action()`
  8. **Conditional Routing** — Branching patterns, fan-out/fan-in
  9. **Error Handling & Retries** — `on_error` edges, retry policies
  10. **Comparison: AgentCrew.run_flow vs AgentsFlow.run_flow** — Feature
      comparison table
- **Depends on**: Module 3 (cross-references node types)

### Module 3: Node Types Reference

- **Path**: `docs/orchestration/node-types.md`
- **Responsibility**: Reference for every registered node type
- **Content outline**:
  1. **Node Registry** — How `NODE_REGISTRY` and `@register_node` work
  2. **Base Node** — `Node(BaseModel)`, frozen Pydantic model, fields,
     pre/post action hooks
  3. **AgentNode** (`"agent"`) — Wraps an agent + FSM, `execute()`,
     `dependencies`, `successors`, `timeout`
  4. **StartNode** (`"start"`) — Virtual entry point, `__start__`
  5. **EndNode** (`"end"`) — Virtual exit point, `__end__`
  6. **DecisionNode** (`"decision"`) — Three decision modes (CIO, BALLOT,
     CONSENSUS), `DecisionNodeConfig`, `DecisionResult`, link to
     `DECISION_NODE_USAGE.md` for deep dive
  7. **InteractiveDecisionNode** (`"interactive_decision"`) — HITL gate,
     escalation policies
  8. **SynthesisNode** (`"synthesis"`) — In-graph LLM summarization
  9. **CrewAgentNode** — Crew-specific agent node (used internally by
     AgentCrew, documented for advanced users)
  10. **Creating Custom Nodes** — How to subclass `Node` and register with
      `@register_node`
- **Depends on**: none

### Module 4: mkdocs.yml Update & Page Cleanup

- **Path**: `mkdocs.yml` + removal of superseded files
- **Responsibility**: Update navigation, remove old pages
- **Changes**:
  1. Replace the "Orchestration & Flows" nav section with new entries
  2. Remove `crew.md` from "Bots & Agents" nav section (superseded)
  3. Remove `crew_summary.md` from "Bots & Agents" nav section (folded in)
  4. Remove old files: `docs/crew.md`, `docs/ORCHESTRATION.md`,
     `docs/orchestration.md`, `docs/crew_summary.md`
  5. Keep `docs/crew_handler.md` in "Bots & Agents" (handler-specific)
  6. Keep `docs/DECISION_NODE_USAGE.md` linked from node-types.md
  7. Keep `docs/EXECUTION_MEMORY.md` in "Memory & Knowledge"
- **Depends on**: Modules 1, 2, 3

---

## 4. Test Specification

### Verification

Since this is documentation-only, testing is build-based:

| Test | Description |
|---|---|
| `mkdocs build --strict` | Build succeeds with no warnings/errors |
| Nav link validation | All nav entries resolve to existing files |
| Internal link check | Cross-references between the three guides resolve |
| Code snippet accuracy | Import paths and class names in examples match current codebase |

### Test Commands

```bash
# Build docs and check for errors
source .venv/bin/activate && mkdocs build --strict

# Verify removed files are not referenced
grep -rn "crew\.md\|ORCHESTRATION\.md\|orchestration\.md\|crew_summary\.md" mkdocs.yml
# Expected: no output (or only in comments)
```

---

## 5. Acceptance Criteria

- [ ] `docs/orchestration/agentcrew.md` exists and covers all four execution
      modes (sequential, parallel, flow, loop) with runnable code examples
- [ ] `docs/orchestration/agentsflow.md` exists and covers DAG construction,
      edge conditions, `from_definition()`, events, and conditional routing
      with runnable code examples
- [ ] `docs/orchestration/node-types.md` exists and documents all six
      registered node types (agent, start, end, decision,
      interactive_decision, synthesis) plus CrewAgentNode
- [ ] All import paths in code examples use current correct paths
      (`from parrot.bots.flows import ...`)
- [ ] `mkdocs.yml` nav updated with new "Orchestration & Flows" section
      pointing to the three new guides + existing Decision Node Usage
- [ ] Superseded pages removed: `docs/crew.md`, `docs/ORCHESTRATION.md`,
      `docs/orchestration.md`, `docs/crew_summary.md`
- [ ] `docs/crew_handler.md` and `docs/DECISION_NODE_USAGE.md` remain
      unchanged
- [ ] `mkdocs build --strict` passes with no errors
- [ ] Each guide includes a "When to use X vs Y" comparison section
- [ ] Documentation is entirely in English

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# Primary import path — all public symbols
from parrot.bots.flows import (
    AgentCrew, CrewAgentNode,
    AgentsFlow,
    FlowDefinition, NodeDefinition, EdgeDefinition,
    DecisionFlowNode, BinaryDecision,
    Node, AgentNode, FlowResult, FlowContext, FlowTransition,
    AgentLike, FlowStatus,
)
# verified: packages/ai-parrot/src/parrot/bots/flows/__init__.py:13-22

# CrewDefinition (separate model package)
from parrot.models.crew_definition import CrewDefinition
# verified: packages/ai-parrot/src/parrot/models/crew_definition.py:90

# Decision-related types
from parrot.bots.flows.flow.nodes import (
    DecisionFlowNode,
    DecisionNodeConfig,
    DecisionMode,        # CIO, BALLOT, CONSENSUS
    DecisionType,        # BINARY, APPROVAL, MULTI_CHOICE, CUSTOM
    DecisionResult,
    BinaryDecision,
    ApprovalDecision,
    MultiChoiceDecision,
    EscalationPolicy,
    VoteWeight,          # EQUAL, SENIORITY, CONFIDENCE, CUSTOM
)
# verified: packages/ai-parrot/src/parrot/bots/flows/flow/nodes.py:50-213

# Flow edge conditions
from parrot.bots.flows.flow.flow import EDGE_CONDITIONS, NODE_REGISTRY
# verified: packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:78,106

# Flow definition models
from parrot.bots.flows.flow.definition import (
    FlowDefinition,   # line 289
    NodeDefinition,    # line 125
    EdgeDefinition,    # line 188
)
# verified: packages/ai-parrot/src/parrot/bots/flows/flow/definition.py
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):  # line 93
    async def run_sequential(self, query: str, ...) -> FlowResult:  # line 1172
    async def run_parallel(self, tasks: List[Dict[str, Any]], ...) -> FlowResult:  # line 1966
    async def run_flow(self, initial_task: str, ...) -> FlowResult:  # line 2289
    async def run_loop(self, initial_task: str, condition: str, ...) -> FlowResult:  # line 1500
    async def run(self, ...) -> FlowResult:  # line 2618
    def task_flow(self, source: str, targets: list) -> None:  # line 626
    def add_agent(self, agent) -> None:  # line 439
    def remove_agent(self, agent_id: str) -> None:  # line 500
    def add_shared_tool(self, tool) -> None:  # line 510
    def on_complete(self, callback) -> None:  # line 252
    def on_error(self, callback) -> None:  # line 267
    @classmethod
    def from_definition(cls, crew_def: "CrewDefinition", ...) -> "AgentCrew":  # line 346
    def visualize_workflow(self) -> None:  # line 2526
    def validate_workflow(self) -> bool:  # line 2545
    async def summary(self, mode: str = "full_report", ...) -> str:  # inherited from SynthesisMixin
    def get_agent_result(self, agent_id: str) -> Any:  # line 590
    def clear_memory(self) -> None:  # line 2784
    def get_memory_snapshot(self) -> dict:  # line 2791

# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
class AgentsFlow(PersistenceMixin):  # line 157
    def add_node(self, node: Node) -> None:  # line 224
    def add_edge(self, from_: str, to: str, condition: str = "always", predicate = None) -> FlowEdge:  # line 241
    def add_node_event_listener(self, callback: Callable) -> None:  # line 297
    async def run_flow(self, ctx = None, *, on_complete = ()) -> FlowResult:  # line 663
    @classmethod
    def from_definition(cls, definition: FlowDefinition, ...) -> "AgentsFlow":  # line 352

# packages/ai-parrot/src/parrot/bots/flows/core/node.py
class Node(BaseModel):  # line 68 — frozen Pydantic model
class AgentNode(Node):  # line 182
class StartNode(Node):  # line 323
class EndNode(Node):  # line 408

# packages/ai-parrot/src/parrot/bots/flows/flow/nodes.py
class DecisionFlowNode(Node):  # line 253
class InteractiveDecisionNode(Node):  # referenced in flow.py:1128-1207

# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py (registered wrappers)
@register_node("decision")
class DecisionNode(Node):  # line 1053
@register_node("interactive_decision")
class InteractiveDecisionFlowNode(Node):  # line 1128
@register_node("synthesis")
class SynthesisNode(Node):  # line 1208
```

### Node Registry (verified at flow.py:1288-1290)

| Registry Key | Class | Source |
|---|---|---|
| `"agent"` | `AgentNode` | `core/node.py:182` |
| `"start"` | `StartNode` | `core/node.py:323` |
| `"end"` | `EndNode` | `core/node.py:408` |
| `"decision"` | `DecisionNode` | `flow/flow.py:1053` |
| `"interactive_decision"` | `InteractiveDecisionFlowNode` | `flow/flow.py:1128` |
| `"synthesis"` | `SynthesisNode` | `flow/flow.py:1208` |

### Edge Conditions (verified at flow.py:78)

```python
EDGE_CONDITIONS = ("always", "on_success", "on_error", "on_timeout", "on_condition")
```

### Does NOT Exist (Anti-Hallucination)

- ~~`from parrot.bots.orchestration.crew import EnhancedAgentCrew`~~ — old
  import, class was renamed and moved
- ~~`EnhancedAgentCrew`~~ — renamed to `AgentCrew`
- ~~`parrot.bots.orchestration`~~ — package was reorganized into
  `parrot.bots.flows`
- ~~`AgentCrew.run_fsm()`~~ — no such method; AgentsFlow is DAG-based, not FSM
- ~~`AgentsFlow.add_agent()`~~ — method is `add_node()`, not `add_agent()`
- ~~`AgentsFlow.on_condition()`~~ — not a method; use `add_edge()` with
  `condition="on_condition"` and a `predicate`
- ~~`CrewDefinition` in `parrot.bots.flows`~~ — it lives in
  `parrot.models.crew_definition`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use `mkdocstrings` `::: parrot.bots.flows.AgentCrew` directives where
  appropriate for auto-generated API docs within the guides.
- Use mermaid diagrams for flow visualization (mkdocs supports them via
  `pymdownx.superfences`).
- Use `pymdownx.tabbed` for showing alternative approaches (programmatic vs
  definition-based construction).
- Follow the style of `docs/architecture/07-agentcrew.md` for technical depth
  but target a user-facing audience (more "how to" than "how it works").
- Include admonitions (`!!! tip`, `!!! warning`, `!!! note`) for important
  callouts.

### Known Risks / Gotchas

- **Broken external links**: If the current published URL
  (`/docs/DECISION_NODE_USAGE/`) is bookmarked by users, removing it from the
  nav could break links. Mitigation: the file stays, only the nav moves it.
- **mkdocs build strictness**: `--strict` mode may catch broken internal links
  during the transition. Run the build after each page change.
- **Code examples must be accurate**: Since there are no automated tests for
  docs, code snippets must be manually verified against the codebase contract
  above. Every import path must match `§6 Verified Imports`.

### External Dependencies

None — documentation only. mkdocs + material theme + mkdocstrings are already
configured in the project.

---

## 8. Open Questions

- [ ] Should `docs/crew_handler.md` be folded into the new AgentCrew guide or
      remain separate? — *Owner: Jesus Lara*
- [ ] Should examples reference real LLM providers (OpenAI, Anthropic) or use
      mock/test agents for portability? — *Owner: Jesus Lara*
- [ ] Should the removed pages (`crew.md`, `ORCHESTRATION.md`, etc.) be kept
      as redirects or fully deleted? — *Owner: Jesus Lara*

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks)
- All four modules should be implemented sequentially because Module 4
  (mkdocs.yml update) depends on Modules 1-3 being complete, and Modules 1-2
  cross-reference Module 3.
- No cross-feature dependencies — this spec is self-contained.
- Since this is documentation-only, a worktree is optional but not harmful.
  Can work directly on a feature branch from `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-20 | Jesus Lara | Initial draft |
