---
id: FW-011
query_id: Q010
type: wiki_page
intent: "Orient: shared state between flow nodes (FlowContext) — the closest thing to a blackboard today."
executed_at: 2026-10-25T22:46:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# FW-011 — FlowContext.shared_data is a plain dict shared by all nodes (no single-writer, no versioning, no ACL, no subscriptions); checkpointable via to_snapshot

## Summary

`bots/flows/core/context.py::FlowContext` (l.56, dataclass) is the shared execution state for AgentCrew and AgentsFlow: `shared_data: Dict[str, Any]` (l.94, 'Arbitrary key-value data shared across all nodes (replaces AgentContext.shared_data)'), `agent_registry: Optional[AgentRegistry]` (l.97) used by `resolve_agent(agent_ref)` → `agent_registry.get_bot_instance` (l.154), `trace_context: Optional[TraceContext]` (l.112), `completed_tasks`, `node_metadata`, `mark_completed` (l.177), `mark_failed`, `get_input_for_node` (l.259), `to_snapshot()` → `ContextSnapshot` (checkpointing; excludes registry/synthesis_client/trace_context). Added in TASK-976 together with `NodeResult`. This is a mutable dict with no writer ownership, no version/compare-and-set, no ACL per key and no change notifications — the brainstorm's VERIFY 'no shared versioned key-value with ACLs' is CONFIRMED. A free wiki query for 'blackboard single writer versioned' returned only unrelated versioned stores (`skills/store.py::SkillRegistry`, `tools/execution_plan/models.py::PlanRunMetadata` — 'versioned plan_run document persisted in the checkpoint shared-data projection', which shows shared_data already hosts one versioned document by convention).

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/core/context.py`
  lines: 56
  symbol: `FlowContext`
  wiki_page_id: file:packages/ai-parrot/src/parrot/bots/flows/core/context.py (score=0.40)
  excerpt: |
    class FlowContext:  # Execution state tracker for a single flow/crew run.
- path: `packages/ai-parrot/src/parrot/bots/flows/core/context.py`
  lines: 94-97
  symbol: `FlowContext.shared_data / agent_registry`
  excerpt: |
    shared_data: Dict[str, Any] = field(default_factory=dict)
    """Arbitrary key-value data shared across all nodes (replaces AgentContext.shared_data)."""
    agent_registry: Optional["AgentRegistry"] = field(default=None)
- path: `packages/ai-parrot/src/parrot/bots/flows/core/context.py`
  lines: 112
  symbol: `FlowContext.trace_context`
  excerpt: |
    trace_context: Optional["TraceContext"] = field(default=None)
- path: `packages/ai-parrot/src/parrot/bots/flows/core/context.py`
  lines: 145-154
  symbol: `FlowContext.resolve_agent`
  excerpt: |
    if self.agent_registry is None: raise ... 'no agent_registry is bound to this FlowContext'
    agent = self.agent_registry.get_bot_instance(agent_ref)
- path: `packages/ai-parrot/src/parrot/bots/flows/core/context.py`
  lines: 177
  symbol: `FlowContext.mark_completed`
- path: `packages/ai-parrot/src/parrot/bots/flows/core/context.py`
  lines: 259
  symbol: `FlowContext.get_input_for_node`
- path: `packages/ai-parrot/src/parrot/bots/flows/__init__.py`
  lines: 1-60
  symbol: `parrot.bots.flows exports`
  wiki_page_id: file:packages/ai-parrot/src/parrot/bots/flows/__init__.py (score=0.76)
  excerpt: |
    core: shared types, FSM (AgentTaskMachine, TransitionCondition), nodes, result models, context, storage (ExecutionMemory, VectorStoreMixin, PersistenceMixin, SynthesisMixin)
- path: `packages/ai-parrot/src/parrot/tools/execution_plan/models.py`
  lines: n/a
  symbol: `PlanRunMetadata`
  excerpt: |
    Versioned plan_run document persisted in the checkpoint shared-data projection.
- path: `sdd/tasks/completed/TASK-976-add-shared-data-and-noderesult.md`
  lines: n/a
  symbol: `TASK-976 shared_data + NodeResult`
  wiki_page_id: file:sdd/tasks/completed/TASK-976-add-shared-data-and-noderesult.md (score=0.73)

## Notes

`parrot.bots.flows.core` also exports an FSM (`AgentTaskMachine`, `TransitionCondition`) — a per-node state machine that a per-conversation protocol engine could be modelled after. In Matrix, room **state events** (`m.parrot.agent_card/channel/tunnel`, FW-005) are the existing 'replace-not-append' store the brainstorm maps the blackboard onto.
