---
type: Wiki Overview
title: 'TASK-1600: AgentCrew User Guide Documentation'
id: doc:sdd-tasks-active-task-1600-agentcrew-user-guide-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: '1. **What is AgentCrew?** — High-level explanation: multi-agent orchestrator'
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.models.crew_definition
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
---

# TASK-1600: AgentCrew User Guide Documentation

**Feature**: FEAT-249 — Update AgentCrew & AgentsFlow Documentation
**Spec**: `sdd/specs/update-agentcrew-agentflow-documentation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1599
**Assigned-to**: unassigned

---

## Context

> This task implements Module 1 from the spec. It creates the comprehensive
> AgentCrew User Guide that replaces the outdated `docs/crew.md` (which
> references the old `EnhancedAgentCrew` class and wrong imports). This guide
> covers all four execution modes with runnable examples and cross-references
> the Node Types Reference (TASK-1599).

---

## Scope

- Create `docs/orchestration/agentcrew.md` with the following sections:

  1. **What is AgentCrew?** — High-level explanation: multi-agent orchestrator
     with four execution modes, when to use it vs AgentsFlow.
  2. **Quick Start** — Minimal example: create 2 agents, form a crew, run
     sequentially. Show the import, construction, and result.
  3. **Creating a Crew** — Constructor parameters, `add_agent()`,
     `add_shared_tool()`, `from_definition()` with `CrewDefinition`.
  4. **Execution Modes** — One subsection per mode with complete runnable
     examples:
     - `run_sequential()` — pipeline, `pass_full_context` parameter
     - `run_parallel()` — fan-out, task format (`List[Dict]`), `all_results`
     - `run_flow()` — DAG with `task_flow()`, dependency declarations,
       `visualize_workflow()`, `validate_workflow()`
     - `run_loop()` — iterative refinement, `condition` string, `max_iterations`
     - `run()` — universal dispatcher (auto-selects mode)
  5. **Results & Synthesis** — `FlowResult` structure, `summary()` with
     `mode="full_report"` and `mode="executive_summary"`,
     `get_agent_result()`.
  6. **Hooks** — `on_complete()`, `on_error()` callbacks with examples.
  7. **Execution Memory** — `ExecutionMemory`, `get_memory_snapshot()`,
     `clear_memory()`.
  8. **Visualization** — `visualize_workflow()`, `validate_workflow()`.
  9. **When to Use AgentCrew vs AgentsFlow** — Decision table comparing
     capabilities, use cases, and tradeoffs.

- Cross-reference `docs/orchestration/node-types.md` for node type details
  (link to TASK-1599's output).

**NOT in scope**:
- Modifying any Python source code
- Rewriting `docs/crew_handler.md` (handler-specific, different audience)
- Updating `mkdocs.yml` (that's TASK-1602)
- Removing old `docs/crew.md` (that's TASK-1602)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/orchestration/agentcrew.md` | CREATE | AgentCrew User Guide |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Primary import path
from parrot.bots.flows import (
    AgentCrew, CrewAgentNode,
    FlowResult, FlowContext,
)
# verified: packages/ai-parrot/src/parrot/bots/flows/__init__.py:16,62-63

# CrewDefinition for from_definition()
from parrot.models.crew_definition import CrewDefinition
# verified: packages/ai-parrot/src/parrot/models/crew_definition.py:90

# Agent types used in examples
from parrot.bots import Agent, Chatbot
# verified: packages/ai-parrot/src/parrot/bots/__init__.py

# Tool decorator for examples
from parrot.tools import tool
# verified: packages/ai-parrot/src/parrot/tools/__init__.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):  # line 93

    # Constructor (key parameters)
    def __init__(self, ...):  # line 132
        # Key attrs: agents, workflow_graph, execution_memory, max_parallel_tasks

    # Execution modes
    async def run_sequential(self, query: str, user_id: str = None,
                             pass_full_context: bool = True, ...) -> FlowResult:  # line 1172
    async def run_parallel(self, tasks: List[Dict[str, Any]],
                           all_results: Optional[bool] = True, ...) -> FlowResult:  # line 1966
    async def run_flow(self, initial_task: str, ...) -> FlowResult:  # line 2289
    async def run_loop(self, initial_task: str, condition: str,
                       max_iterations: int = ..., pass_full_context: bool = True,
                       ...) -> FlowResult:  # line 1500
    async def run(self, ...) -> FlowResult:  # line 2618

    # DAG construction
    def task_flow(self, source: str, targets: list) -> None:  # line 626

    # Agent management
    def add_agent(self, agent) -> None:  # line 439
    def remove_agent(self, agent_id: str) -> None:  # line 500
    def add_shared_tool(self, tool) -> None:  # line 510

    # Hooks
    def on_complete(self, callback) -> None:  # line 252
    def on_error(self, callback) -> None:  # line 267

    # Results
    def get_agent_result(self, agent_id: str) -> Any:  # line 590

    # Factory
    @classmethod
    def from_definition(cls, crew_def: "CrewDefinition", *,
                        class_resolver: Callable, tool_resolver = None,
                        **kwargs) -> "AgentCrew":  # line 346

    # Visualization
    def visualize_workflow(self) -> None:  # line 2526
    def validate_workflow(self) -> bool:  # line 2545

    # Memory
    def clear_memory(self) -> None:  # line 2784
    def get_memory_snapshot(self) -> dict:  # line 2791

    # Synthesis (inherited from SynthesisMixin)
    async def summary(self, mode: str = "full_report", ...) -> str:

# packages/ai-parrot/src/parrot/bots/flows/core/result.py
class FlowResult:  # canonical result shape
    # output, responses, agents, errors, status, summary
```

### Does NOT Exist

- ~~`from parrot.bots.orchestration.crew import EnhancedAgentCrew`~~ — old path, class renamed and moved
- ~~`EnhancedAgentCrew`~~ — renamed to `AgentCrew`
- ~~`parrot.bots.orchestration`~~ — reorganized into `parrot.bots.flows`
- ~~`AgentCrew.run_fsm()`~~ — no such method
- ~~`AgentCrew.run_workflow()`~~ — method is `run_flow()`, not `run_workflow()`
- ~~`AgentCrew.add_task()`~~ — no such method; use `task_flow()` for DAG edges
- ~~`AgentCrew.execute()`~~ — the method is `run()` or mode-specific methods

---

## Implementation Notes

### Pattern to Follow

Follow the structure of a tutorial-style guide. Each execution mode section
should follow this pattern:

```markdown
### Sequential Execution (`run_sequential`)

> One-line description of what this mode does.

**When to use**: brief criteria

**Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|

**Example:**
\`\`\`python
# Complete runnable example
\`\`\`

**Output:**
\`\`\`
# What the user would see
\`\`\`
```

### Key Constraints

- Import paths must use `from parrot.bots.flows import AgentCrew` — NEVER the
  old `from parrot.bots.orchestration.crew import EnhancedAgentCrew`.
- Use mermaid diagrams for the flow execution mode (showing DAG topology).
- Use `pymdownx.tabbed` to show programmatic vs definition-based construction.
- Include the comparison table between AgentCrew and AgentsFlow at the end.
- Use admonitions (`!!! tip`, `!!! warning`) for important callouts.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` — main AgentCrew class (3.7k lines)
- `examples/crew/crew_flows.py` — sequential, parallel, flow, loop examples
- `examples/crew/crew_loop.py` — iterative refinement example
- `examples/crew/simple.py` — minimal crew setup
- `examples/crew/market_researcher.py` — real-world example
- `docs/crew_summary.md` — existing summary() docs (will be folded into this guide)
- `docs/architecture/07-agentcrew.md` — internal architecture reference

---

## Acceptance Criteria

- [ ] `docs/orchestration/agentcrew.md` exists with all nine sections from the scope
- [ ] All four execution modes documented with runnable code examples
- [ ] `from_definition()` factory documented with `CrewDefinition` example
- [ ] All import paths match verified imports (no old `EnhancedAgentCrew` references)
- [ ] Cross-references to `docs/orchestration/node-types.md` work
- [ ] Comparison table: AgentCrew vs AgentsFlow included
- [ ] `mkdocs build --strict` passes (can be tested by temporarily adding to nav)

---

## Test Specification

```bash
# Build docs with the new file
source .venv/bin/activate
mkdocs build --strict 2>&1 | grep -i "error\|warning"

# Verify no old class names leaked into the guide
grep -n "EnhancedAgentCrew\|parrot\.bots\.orchestration" docs/orchestration/agentcrew.md
# Expected: no output

# Verify import paths are current
grep -oP 'from parrot\.\S+' docs/orchestration/agentcrew.md | sort -u | while read imp; do
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
4. **Read existing examples** in `examples/crew/` for code patterns to include
5. **Read `docs/crew_summary.md`** for summary() content to fold in
6. **Write** `docs/orchestration/agentcrew.md` following the scope above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-1600-agentcrew-user-guide.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
