---
type: Wiki Overview
title: 'Brainstorm Research: AgentsFlow — Current State Audit & Refactor Direction'
id: doc:sdd-proposals-agents-flow-refactor-research-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is **not a spec proposal**. It is an audit of the current AgentsFlow
  code (`parrot/bots/flow/`) intended to feed `/sdd-brainstorm` with grounded, code-verified
  observations instead of speculation. The spec(s) that follow this brainstorm will
  be informed by the decisions take
relates_to:
- concept: mod:parrot.models.crew
  rel: mentions
---

# Brainstorm Research: AgentsFlow — Current State Audit & Refactor Direction

**Date**: 2026-05-01
**Author**: Jesus
**Depends on**: `flow-primitives` (FEAT-134, merged), `agent-crew-primitives-migration` (FEAT-143, merged)
**Status**: discussion — NOT a spec yet, this is the research material that precedes the spec

---

## Purpose of this document

This is **not a spec proposal**. It is an audit of the current AgentsFlow code (`parrot/bots/flow/`) intended to feed `/sdd-brainstorm` with grounded, code-verified observations instead of speculation. The spec(s) that follow this brainstorm will be informed by the decisions taken here.

The mental model going in was: "AgentsFlow uses a global FSM that prevents parallelism and branching." After reading the code carefully, that mental model is **partially wrong** and the real problems are different. Documenting the actual state so we don't refactor based on a misdiagnosis.

---

## Headline finding: the FSM is already per-node

The repeated assumption that AgentsFlow runs a "global FSM" does not match the code:

- `AgentsFlow` class **does not inherit from `StateMachine`**. It inherits from `PersistenceMixin, SynthesisMixin` only.
- `FlowNode.fsm = AgentTaskMachine(...)` is instantiated **per node** in `add_agent()` (line 432) and reset per node in `run_flow()` (line 763).
- `_execute_agents_parallel` already uses `asyncio.gather(*tasks)` over multiple nodes simultaneously (line 1054).
- The `run_flow` loop already implements a ready-set scheduler: it computes `_get_ready_agents()`, executes them in parallel, processes transitions, repeats.

So **parallelism is structurally possible today** and was implemented. What is likely true is that it was never exercised in real workflows because:

(a) Most flows built so far have been linear or near-linear, so parallelism never manifested.
(b) The scheduler has design problems (below) that make it brittle even when parallelism is reachable.
(c) Tests probably never validated parallel execution of branches.

This reframes the refactor. We are not removing a global FSM — we are **rebuilding the scheduler around the same primitives that already exist in `flows.core`, integrating with `FlowDefinition`, and fixing real defects**.

---

## Component-by-component audit

Each row indicates: status today, real problem (if any), and disposition for the refactor.

### Already-correct components (preserve, possibly relocate)

| Component | Status | Notes |
|---|---|---|
| `parrot/bots/flow/definition.py` | Working, well-typed | Pydantic models for declarative flows. `FlowDefinition`, `NodeDefinition`, `EdgeDefinition`, `FlowMetadata`, action definitions, validators. Preserve as-is. |
| `parrot/bots/flow/svelteflow.py` | Working | Bidirectional adapter `FlowDefinition` ↔ SvelteFlow JSON. Preserve as-is. |
| `parrot/bots/flow/actions.py` + `ACTION_REGISTRY` | Working | `@register_action` decorator pattern. Built-in actions: log, notify, webhook, metric, set_context, validate, transform. Pattern is sound; preserve. |
| `parrot/bots/flow/cel_evaluator.py` | Working | CEL-based predicate evaluator. Sandboxed, Pydantic-aware, fail-safe. Notably better than `eval()`-based approaches. Preserve. |
| `parrot/bots/flow/node.py` (`Node` ABC) | Working | Action hooks (`run_pre_actions`/`run_post_actions`), logger, abstract `name`. Already aligned with `flows.core.node.Node`. Likely supersedeable by core's `Node`, but preserve the action-hook semantics. |
| `StartNode` / `EndNode` (in `parrot/bots/flow/nodes/`) | Working | Virtual nodes. Already absorbed into `flows.core.node` per FEAT-134 spec. Confirm import paths after that migration. |

### Components with real defects

| Component | Defect | Disposition |
|---|---|---|
| `AgentsFlow.run_flow` (line 686) | Polling-based scheduler — `await asyncio.sleep(0.1)` waits between iterations (line 814). Not event-driven. | Redesign scheduler around `asyncio.Event` / `asyncio.Queue` to wake on completion. |
| `_process_transitions` (line 1173) | Iterates **every** node every iteration to find ones that just transitioned. O(N) per step, doubly so given the outer loop. | Switch to event-driven: when a node completes, push its `node_id` to a transition-processing queue. |
| `FlowNode.transitions_processed: bool` | Mutable flag on the node, must be reset between runs. Confused semantics (line 1197 sets it `False` to allow retry execution). | Eliminate. With event-driven processing, no per-node "have I processed transitions for this completion?" flag is needed — completion event fires once. |
| `run_flow` reset block (line 760-769) | Reassigns `node.fsm = AgentTaskMachine(...)` to "reset" each node — creates new FSM instances destructively. | FSMs should be reusable. Either reset state in place, or build the flow graph fresh each run (preferred — see "execution instance" below). |
| `_get_ready_agents` / `_is_workflow_complete` / `_has_active_agents` | Three separate scans over all nodes per iteration. Repeated O(N) work. | Maintain ready/active/completed/failed sets incrementally — update on state transitions, not by scanning. |
| `_execute_agents_parallel` | `asyncio.gather(*tasks, return_exceptions=True)` waits for **all** tasks of this batch before processing transitions. A fast node has to wait for the slowest in its batch before its downstream nodes can be scheduled. | Replace with `asyncio.as_completed` or per-node completion events — schedule downstream as soon as a node finishes. This is the real parallelism unlock. |

### Components duplicated with `flows.core` (eliminate, import from core)

| Symbol in `parrot/bots/flow/fsm.py` | Duplicate of | Action |
|---|---|---|
| `AgentTaskMachine` (line 61) | `flows.core.fsm.AgentTaskMachine` | Delete; import from core |
| `TransitionCondition` (line 52) | `flows.core.fsm.TransitionCondition` | Delete; import from core |
| `AgentRef` (line 47) | `flows.core.types.AgentRef` | Delete; import from core |
| `DependencyResults` (line 48) | `flows.core.types.DependencyResults` | Delete; import from core |
| `PromptBuilder` (line 49) | `flows.core.types.PromptBuilder` | Delete; import from core |
| `FlowTransition` (line 116) | `flows.core.transition.FlowTransition` | Delete; import from core. Verify field parity — current dataclass has `metadata: Optional[AgentExecutionInfo]` which is odd (storing execution info on a static edge); the core version may not have that. |

### Components using outdated models

| Import in `fsm.py` | Should be |
|---|---|
| `from ...models.crew import CrewResult` | `from ..flows.core.result import FlowResult` |
| `from ...models.crew import AgentResult` | `from ..flows.core.result import NodeResult` |
| `from ...models.crew import AgentExecutionInfo` | `from ..flows.core.result import NodeExecutionInfo` |
| `from ...models.crew import build_agent_metadata` | `from ..flows.core.result import build_node_metadata` |
| `from ...models.crew import determine_run_status` | `from ..flows.core.result import determine_run_status` |

Note: `parrot.models.crew` still re-exports the old names per FEAT-134's backward-compat strategy, so the imports above work — but they should be updated for consistency with `AgentCrew` (FEAT-143).

### Components that need redesign

| Component | Issue | Direction |
|---|---|---|
| `FlowNode` (line 198) | Conflates "node definition" with "node execution state": holds `agent`, `dependencies`, `outgoing_transitions` (static), but also `result`, `response`, `error`, `execution_time`, `retry_count`, `fsm` (mutable, per-run). | Split into a static `NodeSpec` (definition: agent ref, dependencies, transitions, max_retries) and a runtime `NodeRunState` (FSM, result, error, attempts) that lives only during a single execution. |
| `DecisionNode` / `InteractiveDecisionNode` | Don't fit the `FlowNode.execute()` contract — they return `DecisionResult`, not the agent's free-form output. Currently wedged into the flow via `add_agent(decision_node)` and treated as an agent. | Introduce node-type taxonomy: `AgentNode` (executes an agent), `DecisionNode` (executes a deterministic decision producing a symbol), `InteractiveNode` (CLI/HITL primitive), with `EXECUTOR_REGISTRY` mapping node type → execution strategy. |
| `add_agent` is the only path | Every node — agent, start, end, decision — goes through `add_agent`. Misleading naming and forces agent-like contract on non-agents. | Replace with `add_node(spec: NodeSpec)` polymorphic over types. Keep `add_agent` as a convenience wrapper. |
| No `from_definition()` materializer | `FlowDefinition` exists but nothing instantiates an executable flow from it. The visual editor → execution path is broken. | Add `AgentsFlow.from_definition(definition: FlowDefinition, agent_registry)` that resolves `agent_ref` strings against an `AgentRegistry`, materializes nodes per their type, wires edges. |

---

## Real problems vs perceived problems

| Perceived | Real |
|---|---|
| "FSM is global, prevents branches" | FSM is already per-node; branches are structurally supported but scheduler is brittle |
| "No parallelism" | `asyncio.gather` already exists; the limit is *batched* parallelism — downstream waits for the slowest sibling in its batch |
| "Refactor must remove FSM" | Refactor must (a) replace polling with event-driven scheduling, (b) collapse duplication with `flows.core`, (c) split static spec from runtime state, (d) introduce node-type taxonomy |
| "DecisionResult doesn't fit Node.ask()" | Confirmed — needs node-type taxonomy with type-specific executors |

---

## Architectural direction (to discuss)

### Option A — Minimal surgery
- Eliminate duplication with `flows.core`
- Update model imports to `FlowResult`/`NodeExecutionInfo`/etc.
- Leave scheduler logic as-is (polling, per-iteration scans)
- Add `from_definition()` materializer
- Fix `DecisionNode` integration via a small `EXECUTOR_REGISTRY`

**Effort**: 1-2 weeks. **Risk**: low. **Limitation**: leaves the polling scheduler and batched-parallelism limitation in place. Sufficient for current flow shapes; insufficient for future swarm/HITL specs that need fine-grained event scheduling.

### Option B — Scheduler rewrite + spec/state split + node taxonomy
- Everything in Option A, plus:
- Replace polling loop with event-driven scheduler (`asyncio.Event` per node, completion → downstream wakeup)
- Split `FlowNode` into `NodeSpec` (static, reusable across runs) + `NodeRunState` (per-execution)
- Introduce `NODE_REGISTRY` + `EXECUTOR_REGISTRY` for typed nodes
- Maintain ready/active/completed sets incrementally instead of scanning

**Effort**: 3-4 weeks. **Risk**: medium (more surface changes), but well-bounded since AgentsFlow has no users. **Benefit**: solid foundation for Spec 3.2 (advanced decision nodes), 3.3 (iteration), 3.4 (scatter/gather), 3.5 (HITL with checkpoint). Each of those is easier on Option B than Option A.

### Option C — Full rewrite from scratch
- Start `parrot/bots/flows/agents_flow.py` from zero, using only `flows.core` primitives + the preserved declarative pieces (`definition.py`, `svelteflow.py`, `actions.py`, `cel_evaluator.py`, `decision_node.py`)
- Old `parrot/bots/flow/fsm.py` deleted, not migrated

**Effort**: 3-4 weeks (same as B). **Risk**: low because no users. **Benefit**: clean architecture without accommodating legacy decisions. **Cost**: any tests, examples, or notebooks against the current API break (acceptable per user statement).

**Recommendation**: **Option C** — given the user's stated willingness to break backward compat and the fact that AgentsFlow has no production users, a clean rewrite of the executor (preserving all the working declarative/utility components) is cleaner than mutating the existing executor in place. The risk is the same as Option B but the cognitive load is lower because the new code doesn't have to make sense alongside the old code.

---

## Open Questions

### D1 — Where does the new AgentsFlow live?

`parrot/bots/flow/` (singular) is the legacy location. `parrot/bots/flows/` (plural) is the new home of `core` (FEAT-134) and `crew.py` (FEAT-143).

**Proposal**: new executor lives at `parrot/bots/flows/agents_flow.py`. The legacy `parrot/bots/flow/` directory is sunsetted but kept until the supporting modules (decision_node, interactive_node, actions, definition, svelteflow, cel_evaluator) are also relocated under `parrot/bots/flows/` — possibly in a follow-up cleanup task.

### D2 — `NodeSpec` vs `NodeRunState` split: how strict?

If we go Option B/C, the question is whether the split is:
- **Hard**: `NodeSpec` is fully immutable, frozen dataclass; `NodeRunState` is a separate object created per `run_flow()` call.
- **Soft**: One `Node` class with clearly-marked "definition fields" and "runtime fields", reset between runs.

Hard split is cleaner conceptually and enables running the same `AgentsFlow` definition across multiple concurrent executions (multi-tenant case). Soft split is less code churn but keeps the current state-reset awkwardness.

### D3 — Event-driven scheduler: design

If we go event-driven, the core mechanism choices are:

- **`asyncio.Queue` of "completion events"**: when a node completes, push `(node_id, result|error)` to a queue; the scheduler drains the queue and dispatches transitions. Simple, single consumer.
- **Per-node `asyncio.Event`**: each downstream node waits on `all_dependencies_completed_event`. More natural for fan-in, awkward for dynamic graphs.
- **Callback chain**: each node's completion calls `await scheduler.on_complete(node_id, ...)` directly. Simplest but couples nodes to scheduler.

**Inclination**: queue-based. Single scheduler consumer, clean separation, easy to instrument and observe. Plays well with future checkpoint/resume (queue state is serializable).

### D4 — `NODE_REGISTRY` / `EXECUTOR_REGISTRY`: one or two?

Two related but distinct registries:
- `NODE_TYPE_REGISTRY`: maps `node_type` string ("agent", "decision", "interactive_decision", "human") to a `NodeSpec` subclass for validation/instantiation.
- `EXECUTOR_REGISTRY`: maps `node_type` to an executor function `async (spec, ctx, deps) -> result`.

Or fold them into one: `@register_node_type("agent")` decorator that registers both the spec class and the executor.

**Inclination**: fold into one. Less ceremony, mirrors `ACTION_REGISTRY` pattern.

### D5 — How does `from_definition()` resolve `agent_ref`?

`NodeDefinition.agent_ref: str` is a name like `"researcher_agent"`. The executor needs to materialize this into a real agent instance.

Options:
- **Pass an `AgentRegistry` to `from_definition()`**: most flexible, decouples flow from agent provisioning.
- **Use `BotManager`**: pulls from the global agent registry. Less flexible, more convenient for typical use.
- **Allow both**: `from_definition(definition, agent_resolver=...)` where resolver defaults to `BotManager.get_agent`.

**Inclination**: third option. Default to BotManager for convenience; allow override for testing and multi-tenant scenarios.

### D6 — Backward compat for AgentsFlow API: none?

User confirmed: no users, no backward compat needed. But verify by:
- Grepping the repo for `AgentsFlow(` and `AgentCrewFSM(` usage outside of tests.
- Checking if examples/ or docs/ reference the current API.

If anything turns up, the spec should explicitly enumerate what's removed vs. preserved as alias. Otherwise, clean slate.

### D7 — DecisionNode contract: how does it fit into the executor?

Current: `DecisionNode.ask()` returns `DecisionResult` with `final_decision`, `decision`, `reasoning`, `raw_response`.

For the executor:
- Result published to `FlowContext.results[node_id] = decision_result.model_dump()` (or the object itself).
- CEL predicates can read `result.final_decision == "approve"`.
- The decision symbol is the output; no special handling at scheduler level.

**Question**: should the executor know that a `DecisionNode` is "different" (e.g., for logging/metrics), or treat it polymorphically via the `EXECUTOR_REGISTRY`?

**Inclination**: fully polymorphic via registry. The executor doesn't care if a node is decision-or-agent; it cares about `(spec, ctx, deps) -> result`. Logging/metrics can be added via actions.

### D8 — `InteractiveDecisionNode` and the future HITL spec

`InteractiveDecisionNode` is a CLI-blocking primitive using `questionary` via `run_in_executor`. It works for terminal apps but does NOT scale to:
- Web UI (would need WebSocket-driven decision)
- Long pauses (questionary blocks the executor thread)
- Multi-channel HITL (Slack/Telegram approval)

**This is OK** — `InteractiveDecisionNode` is a useful primitive for dev/CLI and stays. The "real" HITL story (HITLNode with checkpoint/resume to Redis, decision via webhook) is a separate spec (3.5 in earlier numbering).

But: the scheduler design should not preclude long pauses. Specifically:
- The event-driven scheduler should allow a node in `running` state to remain there indefinitely without holding any task in `asyncio.gather`.
- This means nodes that "pause" (waiting on external decision) need to yield their task slot and be resumed by an external event.

This is foundational for Spec 3.5 — design the scheduler with this in mind even if we don't implement HITL in Spec 3.1.

### D9 — `FlowResult` and the final aggregation

Current `run_flow` aggregates results at the end by iterating `self.execution_log` and `self.nodes` (line 834-870). The shape needs to match `FlowResult` (post FEAT-134 alias):

- `output`: last terminal node's output? Last completed node? User-specified terminal node? (Today: ambiguous, last in iteration order.)
- `summary`: optional LLM-synthesized summary.
- `nodes`: list of `NodeExecutionInfo`.
- `responses`: dict of `node_id → response`.
- `errors`: dict of `node_id → error_str` for failed nodes.
- `status`: derived via `determine_run_status(success_count, failure_count)`.

**Question**: what is `output` for a branching DAG? Define explicitly. Options:
- Output of the EndNode if exactly one EndNode exists.
- Output of the last-completed node by timestamp.
- Output of a designated "terminal" node specified at flow construction time.
- Dict of all leaf node outputs (multi-output flow).

**Inclination**: prefer explicit EndNode. If exactly one EndNode exists, use its output. Otherwise, use a dict of leaf outputs and document that single-output flows should declare an EndNode.

### D10 — Cycle detection in the spec model

`FlowDefinition.validate_node_ids` validates references but not cycles. `AgentsFlow._would_create_cycle` exists but only validates at `task_flow()` call time, not at `from_definition()` time.

**Decision**: add cycle detection to `FlowDefinition.model_validator` so that any definition (loaded from JSON, built programmatically, or roundtripped from SvelteFlow) is validated for acyclicity at construction time. Belongs in the definition layer, not the executor.

---

## What the first spec covers (proposed scope)

**Spec name**: `agents-flow-dag-engine` (FEAT-NNN)

**Scope**:
1. New `AgentsFlow` executor in `parrot/bots/flows/agents_flow.py`, replacing `parrot/bots/flow/fsm.py`.
2. Imports primitives from `flows.core` (no duplication).
3. Event-driven scheduler (Option B/C, D3 queue-based).
4. `NodeSpec` / `NodeRunState` split (D2 hard split).
5. `NODE_TYPE_REGISTRY` + executor pattern (D4 folded registry) for `AgentNode`, `DecisionNode`, `InteractiveDecisionNode`, `StartNode`, `EndNode`.
6. `AgentsFlow.from_definition(definition, agent_resolver=...)` materialization (D5).
7. Updated result aggregation returning `FlowResult` with proper `output` semantics (D9).
8. Cycle detection moved to `FlowDefinition` validator (D10).
9. Integration tests with mocked agents covering: linear flow, branching (fan-out), join (fan-in), conditional with CEL predicate, retry on failure, decision node routing.

**Explicitly out of scope** (deferred to later specs):
- HITLNode with checkpoint/resume (Spec 3.5)
- ScatterNode with dynamic fan-out (Spec 3.4)
- GatherNode with policies (`all`, `any`, `n_of_m`) (Spec 3.4)
- LoopNode wrapping subgraphs (Spec 3.3)
- Multi-agent / swarm patterns (Spec 3.6)
- Redis-backed flow state persistence
- Visual editor integration testing (manual verification only)
- Migration of `parrot/bots/flow/` supporting modules (decision_node, interactive, etc.) to `parrot/bots/flows/` — done in follow-up cleanup spec

**Effort estimate**: 2-3 weeks, 8-12 SDD tasks.

---

## What I want from /sdd-brainstorm

When you run `/sdd-brainstorm` against this document, the goals are:

1. **Verify against code**: have Claude Code check that the audit findings match reality. Particularly:
   - Is `transitions_processed` really mutable-and-reset, or did I misread?
   - Is `_get_ready_agents` really called every iteration, or is there an incremental update I missed?
   - Are there examples / tests / notebooks using `AgentsFlow` or `AgentCrewFSM` that I should know about before committing to "no backward compat"?
2. **Resolve D1–D10** with code-grounded answers, particularly D2 (state split hardness), D3 (scheduler mechanism), D5 (agent resolver default), D9 (`output` semantics).
3. **Sanity-check Option C**: confirm there's no value in incrementally migrating `fsm.py` that I'm missing.
4. **Identify gotchas** in the integration points: `BotManager`, `AgentRegistry`, `ToolManager` sharing, `ExecutionMemory` initialization, `persist_results` semantics.
5. **Discuss whether D4 fold-into-one registry is wise**, or whether keeping two registries is clearer for future node types.

---

## Worktree strategy (preliminary)

- **Isolation**: `per-spec`, single worktree, sequential tasks. The new module is built incrementally — primitives → scheduler → node types → from_definition → tests — and each layer depends on the previous.
- **Cross-feature dependencies**: depends on FEAT-134 (`flow-primitives`) and FEAT-143 (`agent-crew-primitives-migration`) being on `dev`. Confirmed merged.
- **Parallelizable tracks**: minimal. The scheduler and node-type registry are independent of `from_definition()`, but the dependency chain is short enough that splitting worktrees isn't worth the overhead.

---

## Files I want Claude Code to read before brainstorming

Mandatory reads for grounding:
- `parrot/bots/flow/fsm.py` (1816 lines — the whole file)
- `parrot/bots/flow/node.py` (the abstract `Node`)
- `parrot/bots/flow/decision_node.py` (`DecisionNode`, `DecisionResult`, `DecisionMode`)
- `parrot/bots/flow/interactive_node.py` (`InteractiveDecisionNode`)
- `parrot/bots/flow/definition.py` (Pydantic models)
- `parrot/bots/flow/actions.py` (`ACTION_REGISTRY` pattern — model for `NODE_REGISTRY`)
- `parrot/bots/flow/cel_evaluator.py`
- `parrot/bots/flow/svelteflow.py`
- `parrot/bots/flows/core/` (the new primitives — full package)
- `parrot/bots/flows/crew.py` (the post-migration AgentCrew — as reference for how primitives are consumed)

Optional but useful:
- `examples/agents_flow/*` or any examples using AgentsFlow (to gauge backward compat impact)
- `tests/test_fsm*` or AgentsFlow tests (to scope test migration work)
- `parrot/bots/manager.py` / `BotManager` (for agent resolver design in D5)

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-01 | Jesus | Initial audit after reading fsm.py, node.py, decision_node, interactive_node, definition.py, actions.py, svelteflow.py, cel_evaluator.py |
