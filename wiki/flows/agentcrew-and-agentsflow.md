---
title: "Multi Agent Orchestration: AgentCrew and AgentsFlow"
summary: "Technical reference for the two multi-agent orchestrators (AgentCrew execution modes and the event driven AgentsFlow DAG) and the shared primitives in parrot.bots.flows.core."
---

# Multi Agent Orchestration: AgentCrew and AgentsFlow

## Purpose

`parrot.bots.flows` holds the framework's two multi-agent orchestrators and the
primitives they share:

- **`AgentCrew`** (`crew/crew.py`) groups a set of agents and runs them in one of
  four modes: `run_sequential` (pipeline), `run_parallel` (independent tasks),
  `run_flow` (dependency DAG declared with `task_flow()`) and `run_loop`
  (repeat until an LLM judged condition is met). It also offers `run()`
  (parallel run plus LLM synthesis), `ask()` and `summary()` over the results.
- **`AgentsFlow`** (`flow/flow.py`) is an event driven DAG executor over `Node`
  instances. Each node runs as its own `asyncio` task, a completion queue feeds
  the scheduler, and downstream nodes are dispatched as soon as their inputs are
  resolved. Graphs are built with `add_node()` / `add_edge()` or declaratively
  from a `FlowDefinition`. It supports conditional edges, decision nodes,
  checkpointing, `suspend()` and `resume()`.
- **`flows/core`** holds what both use: `Node`, `AgentNode`, `StartNode`,
  `EndNode`, `FlowContext`, `FlowResult`, `NodeResult`, `NodeExecutionInfo`,
  `FlowTransition`, the `AgentTaskMachine` FSM and the `AgentLike` protocol.

Use `AgentCrew` when you have a known list of agents and a simple topology.
Use `AgentsFlow` when you need conditional routing, OR joins, decision nodes,
retries, telemetry callbacks, or durable execution.

All of these are re-exported from `parrot.bots.flows`
(`from parrot.bots.flows import AgentCrew, AgentsFlow, FlowContext, ...`).

## Public API

Modules:

- [`parrot.bots.flows.crew.crew`](ref:parrot.bots.flows.crew.crew) — `AgentCrew` and its run modes.
- [`parrot.bots.flows.flow.flow`](ref:parrot.bots.flows.flow.flow) — `AgentsFlow`, `FlowEdge`, `EDGE_CONDITIONS`, `NODE_REGISTRY`, `register_node`, `CompletionEvent`.
- [`parrot.bots.flows.flow.nodes`](ref:parrot.bots.flows.flow.nodes) — `DecisionFlowNode`, `DecisionNodeConfig`, `DecisionMode`, `DecisionType`, `BinaryDecision`, `ApprovalDecision`, `MultiChoiceDecision`.
- [`parrot.bots.flows.flow.definition`](ref:parrot.bots.flows.flow.definition) — `FlowDefinition`, `NodeDefinition`, `EdgeDefinition`, `FlowMetadata`.
- [`parrot.bots.flows.core.context`](ref:parrot.bots.flows.core.context) — `FlowContext`.
- [`parrot.bots.flows.core.node`](ref:parrot.bots.flows.core.node) — `Node`, `AgentNode`, `StartNode`, `EndNode`.
- [`parrot.bots.flows.core.result`](ref:parrot.bots.flows.core.result) — `FlowResult`, `NodeResult`, `NodeExecutionInfo`.
- [`parrot.models.crew_definition`](ref:parrot.models.crew_definition) — `CrewDefinition`, `AgentDefinition`, `ToolNodeDefinition`, `FlowRelation`, `ExecutionMode`.

Key `AgentCrew` methods (all verified in `crew/crew.py`):

| Method | Signature (abridged) |
|---|---|
| `run_sequential` | `(query, user_id=None, session_id=None, pass_full_context=True, generate_summary=True, synthesis_prompt=None, agent_sequence=None, max_tokens=8192, temperature=0.1, model=None, **kwargs) -> FlowResult` |
| `run_parallel` | `(tasks, all_results=True, user_id=None, session_id=None, generate_summary=True, synthesis_prompt=None, max_tokens=8192, temperature=0.1, **kwargs) -> FlowResult` |
| `run_flow` | `(initial_task, max_iterations=100, generate_summary=True, synthesis_prompt=None, user_id=None, session_id=None, max_tokens=8192, temperature=0.1, on_agent_complete=None, **kwargs) -> FlowResult` |
| `run_loop` | `(initial_task, condition, max_iterations=2, user_id=None, session_id=None, agent_sequence=None, pass_full_context=True, generate_summary=True, synthesis_prompt=None, model=None, max_tokens=8192, temperature=0.1, **kwargs) -> FlowResult` |
| `run` | `(task, synthesis_prompt=None, user_id=None, session_id=None, max_tokens=8192, temperature=0.1, **kwargs) -> AIMessage` |
| `task_flow` | `(source_agent, target_agents)` — declares dependencies for `run_flow` |
| `add_agent` / `remove_agent` / `add_tool_node` / `add_shared_tool` | register members; `add_tool_node(tool, node_id, *, args=None, kwargs=None, description=None)` adds a deterministic, no LLM `ToolNode` |
| `from_definition` | classmethod, `(crew_def, *, class_resolver, tool_resolver=None, google_api_key=None, **kwargs)` |
| `on_complete` / `on_error` | register result hooks |

Key `AgentsFlow` members (verified in `flow/flow.py`):

| Member | Notes |
|---|---|
| `AgentsFlow(name, *, definition=None, agent_registry=None, on_node_event=None, checkpoint=False, durable=False, flow_id=None, persist_results=True, result_storage=None, ...)` | full checkpoint keyword list is in the source |
| `add_node(node)` | raises `ValueError` on a duplicate `node_id` |
| `add_edge(from_, to, *, condition="always", predicate=None) -> FlowEdge` | `predicate` is a CEL string or a callable `(source_result) -> bool` |
| `await run_flow(ctx=None, *, on_complete=()) -> FlowResult` | `ctx` is a `FlowContext` or a prompt string |
| `from_definition(definition, *, agent_registry=None, node_factories=None, checkpoint=None, ...)` | classmethod; resolves every `agent_ref` eagerly |
| `to_definition()` | fails for graphs with callable predicates |
| `add_node_event_listener(callback)` | callback `(event, node_id, info)` |
| `await suspend()` / `await AgentsFlow.resume(flow_id, checkpoint_id=None, *, agent_registry, ...)` | durable execution |

## Configuration & Parameters

### AgentCrew constructor

`AgentCrew(name="AgentCrew", agents=None, shared_tool_manager=None, max_parallel_tasks=10, llm=None, auto_configure=True, truncation_length=None, truncate_context_summary=True, ..., agent_execution_timeout=600.0, persist_results=True, result_storage=None, persist_agent_results=True, enable_execution_wiki=True, execution_wiki_path=None, tenant=None, generate_infographic=False, result_agent_name="result-agent", infographic_theme=None, google_api_key=None, **kwargs)`

- `max_parallel_tasks` bounds concurrent agents (semaphore rate limiting).
- `agent_execution_timeout` is the per agent timeout in seconds.
- `llm` is used for synthesis and for the `run_loop` stop condition.
- `persist_results=False` turns off all result persistence; `persist_agent_results` only disables per agent incremental persistence.
- `enable_execution_wiki` records runs and intermediate results in a per crew WikiStore (default path `{cwd}/.parrot/crew_wiki/<crew-slug>`), active only when persistence is on.
- `tenant` defaults to `"global"` and is persisted with every saved execution.

### CrewDefinition

`CrewDefinition` (a Pydantic model) has `crew_id`, `tenant`, `name`, `description`, `execution_mode` (`ExecutionMode.SEQUENTIAL | PARALLEL | FLOW | LOOP`), `agents` (`AgentDefinition` list with `agent_id`, `agent_class`, `name`, `config`, `tools`, `system_prompt`), `tool_nodes`, `flow_relations` (`FlowRelation` with `source` / `target`, each a string or list; used in `FLOW` mode), `shared_tools`, `max_parallel_tasks`, `generate_infographic`, `result_agent_name`, `infographic_theme`, `enable_execution_wiki`, `execution_wiki_path`, `metadata`.

`AgentCrew.from_definition` instantiates each agent via `class_resolver(agent_def.agent_class)` (falling back to `BasicAgent` when the resolver returns `None`), passing `name`, `tools` and `**agent_def.config`. Shared tools are resolved through `tool_resolver`; when it is `None` they are skipped.

### FlowDefinition

`FlowDefinition` has `flow` (name), `version`, `description`, `metadata` (`FlowMetadata`), `nodes` and `edges`.

- `NodeDefinition`: `id`, `type` (a `NODE_REGISTRY` key), `label`, `agent_ref`, `instruction`, `max_retries`, `config`, `pre_actions`, `post_actions`, `metadata`, `position`.
- `EdgeDefinition`: `from_`, `to` (string or list), `condition` (one of `always`, `on_success`, `on_error`, `on_timeout`, `on_condition`; default `on_success`), `predicate` (CEL, required for `on_condition`), `instruction`, `priority`, `label`.
- `FlowMetadata`: `max_parallel_tasks`, `default_max_retries`, `execution_timeout`, `truncation_length`, `enable_execution_memory`, `checkpoint`, `checkpoint_retention`, `checkpoint_history`, `checkpoint_include_responses`, `durable`, and embedding settings.

Note the default differs: `add_edge()` defaults to `condition="always"`, while `EdgeDefinition.condition` defaults to `"on_success"`.

### Edge semantics and events

`EDGE_CONDITIONS = ("always", "on_success", "on_error", "on_timeout", "on_condition")`. Once at least one edge is declared, the scheduler uses explicit-edge mode: a node is dispatched when all incoming edges are resolved and at least one fired (OR join); if none fired the node is skipped and the skip propagates.

`on_node_event` callbacks receive `event` in `flow_started`, `node_started`, `node_completed`, `node_failed`, `node_skipped`, `flow_completed`. Callback exceptions are logged, never propagated.

### DecisionFlowNode

`DecisionFlowNode(node_id=..., agents={name: agent}, config=DecisionNodeConfig(...), ...)`. `DecisionNodeConfig` takes `mode` (`DecisionMode.CIO | BALLOT | CONSENSUS`), `decision_type` (`DecisionType.BINARY | APPROVAL | MULTI_CHOICE | CUSTOM`), `decision_schema`, `vote_weight_strategy`, `custom_weights`, `minimum_votes`, `coordinator_agent_name`, `cross_pollination_rounds` (default 1), `escalation_policy`, `options`. Per run mutable state lives in `FlowContext.shared_data[node_id]`.

## Usage Examples

AgentCrew pipeline and DAG (agents are any `BasicAgent` / `AbstractBot`):

```python
import asyncio
from parrot.bots.flows import AgentCrew


async def main(researcher, writer, editor_a, editor_b, reviewer) -> None:
    crew = AgentCrew(
        name="content-crew",
        agents=[researcher, writer, editor_a, editor_b, reviewer],
        max_parallel_tasks=4,
    )

    # Pipeline: each agent receives the previous agent's output.
    seq = await crew.run_sequential(
        "Write a brief on vector databases",
        agent_sequence=[researcher.name, writer.name],
    )
    print(seq.status, seq.output)

    # DAG: fan-out to two editors, fan-in to the reviewer.
    crew.task_flow(researcher, writer)
    crew.task_flow(writer, [editor_a, editor_b])
    crew.task_flow([editor_a, editor_b], reviewer)
    result = await crew.run_flow("Write a brief on vector databases")
    print(result.output)

    # Independent tasks in parallel.
    par = await crew.run_parallel([
        {"agent_id": editor_a.name, "query": "Summarize topic A"},
        {"agent_id": editor_b.name, "query": "Summarize topic B"},
    ])
    print(par.output)

    # Iterate until an LLM judges the condition satisfied.
    loop = await crew.run_loop(
        initial_task="Draft a haiku",
        condition="The haiku follows the 5-7-5 syllable pattern",
        max_iterations=3,
        agent_sequence=[writer.name],
    )
    print(loop.output)
```

AgentsFlow with conditional edges:

```python
from parrot.bots.flows import AgentsFlow, AgentNode, FlowContext


async def run(triage_agent, fast_agent, deep_agent) -> None:
    flow = AgentsFlow("support-flow")
    flow.add_node(AgentNode(agent=triage_agent, node_id="triage"))
    flow.add_node(AgentNode(agent=fast_agent, node_id="fast"))
    flow.add_node(AgentNode(agent=deep_agent, node_id="deep"))

    # Python callable predicate; a CEL string works too.
    flow.add_edge("triage", "fast", predicate=lambda r: "simple" in str(r).lower())
    flow.add_edge("triage", "deep", predicate=lambda r: "simple" not in str(r).lower())

    result = await flow.run_flow(FlowContext(initial_task="My invoice is wrong"))
    print(result.status, result.output)
```

Declarative construction:

```python
from parrot.bots.flows import AgentsFlow
from parrot.bots.flows.flow.definition import FlowDefinition


async def run_declared(data: dict, registry) -> None:
    definition = FlowDefinition.model_validate(data)
    flow = AgentsFlow.from_definition(definition, agent_registry=registry)
    result = await flow.run_flow("start")
    print(result.status)
```

Building a crew from a `CrewDefinition`:

```python
from parrot.bots.flows import AgentCrew
from parrot.models.crew_definition import CrewDefinition


def build(crew_def: CrewDefinition, classes: dict) -> AgentCrew:
    return AgentCrew.from_definition(
        crew_def,
        class_resolver=lambda name: classes.get(name),
    )
```

## Gotchas

- **`FlowResult.output` is polymorphic.** One executed leaf yields that leaf's scalar output; two or more leaves yield `dict[node_id, output]`; no executed leaf yields `{}`. Read `FlowResult.node_results` for a stable `dict[node_id, scalar]` shape (documented in `core/result.py`).
- **Edge default mismatch.** `add_edge()` uses `"always"`; declarative `EdgeDefinition` uses `"on_success"`. Passing a `predicate` to `add_edge()` promotes the condition to `"on_condition"`; `"on_condition"` without a predicate raises `ValueError`.
- **Explicit-edge mode is OR join.** As soon as one edge exists, `Node.dependencies` / `Node.successors` are no longer the source of truth; a node whose incoming edges all resolved without any firing is skipped, and so are its descendants.
- **Callable predicates cannot be serialized.** `to_definition()` fails for such graphs, so with `checkpoint=True` you must pass `checkpoint_definition` (see the constructor docs in `flow.py`).
- **Fresh nodes per run.** `AgentsFlow.run_flow()` materializes new `Node` instances each call, so concurrent runs on the same flow instance do not share FSM state. The FSM transitions are driven by the scheduler, not inside `Node.execute()`.
- **`from_definition` fails fast.** Every `agent_ref` is resolved eagerly against the `agent_registry`; a bad ref raises at construction, not at run time.
- **No `SynthesisMixin` on `AgentsFlow`.** Unlike `AgentCrew`, it only inherits `PersistenceMixin`; synthesize through an `on_complete` hook (`synthesize_results`, which needs `FlowContext.synthesis_client`).
- **`run_flow` on a crew needs `task_flow()` first.** The DAG is built from `task_flow(source, targets)` calls, which index `workflow_graph` by agent `name`, so agents must already be added.
- **Loop termination is LLM judged.** `run_loop` stops on the model's verdict about `condition` or at `max_iterations` (default 2), whichever comes first.
- **Interactive decision node alias.** `InteractiveDecisionNode` exported from `parrot.bots.flows.flow` is the `@register_node` wrapper in `flow.py`, not the canonical class in `flow/nodes.py`.

## Related

- [AgentCrew architecture](../architecture/07-agentcrew.md) — design walkthrough of crew execution, persistence and the execution wiki.
- [AgentsFlow architecture](../architecture/08-agentsflow-dag.md) — DAG first orchestration with per node FSM.
- [Decision node usage](DECISION_NODE_USAGE.md) — worked examples for `DecisionFlowNode` modes.
- Source: `packages/ai-parrot/src/parrot/bots/flows/` (`crew/`, `flow/`, `core/`) and `packages/ai-parrot/src/parrot/models/crew_definition.py`.
