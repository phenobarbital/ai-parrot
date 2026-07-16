---
type: Wiki Overview
title: 'TASK-010: Declarative dev-loop `FlowDefinition` + node factories + parity'
id: doc:sdd-tasks-completed-task-010-declarative-definition-factories-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 8 (G1) — the integration task. Re-express the dev-loop
  graph
relates_to:
- concept: mod:parrot.bots.flows.flow.definition
  rel: mentions
- concept: mod:parrot.bots.flows.flow.flow
  rel: mentions
- concept: mod:parrot.flows.dev_loop.factories
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.bug_intake
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.close
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.deployment_handoff
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.development
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.failure_handler
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.intent_classifier
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.qa
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.research
  rel: mentions
---

# TASK-010: Declarative dev-loop `FlowDefinition` + node factories + parity

**Feature**: FEAT-250 — Dev-Loop Refactor
**Spec**: `sdd/specs/dev-loop-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-001, TASK-003, TASK-006, TASK-007, TASK-008, TASK-009
**Assigned-to**: unassigned

---

## Context

Implements Module 8 (G1) — the integration task. Re-express the dev-loop graph
declaratively as a `FlowDefinition` and run it via
`AgentsFlow.from_definition(..., node_factories=...)`, reproducing the exact
FEAT-132 routing. The legacy `build_dev_loop_flow()` becomes a thin wrapper.

---

## Scope

- Register each dev-loop node class as a node type with
  `@register_node("dev_loop.intent_classifier")`, `dev_loop.bug_intake`,
  `dev_loop.research`, `dev_loop.development`, `dev_loop.qa`,
  `dev_loop.deployment_handoff`, `dev_loop.failure_handler`,
  `dev_loop.close`.
- `dev_loop/definition.py`: `build_dev_loop_definition(*, revision=False) ->
  FlowDefinition` — nodes + edges mirroring the current routing:
  intent→(bug)→bug_intake→research / intent→(non-bug)→research;
  research→development→qa; qa→(pass)→deployment_handoff, qa→(fail)→failure;
  on_error from each middle node → failure; deployment_handoff→close. (The
  `revision=True` graph is authored in TASK-012 but the param exists here.)
- `dev_loop/factories.py`: `build_dev_loop_node_factories(*, dispatcher,
  jira_toolkit, git_toolkit, log_toolkits, redis_url, repos) -> dict[str,
  Callable]` returning a factory per `dev_loop.*` node type that closes over the
  live deps and returns the constructed node (node_id/dependencies/successors
  from the materializer args).
- Rewrite `build_dev_loop_flow(...)` as a thin wrapper:
  `AgentsFlow.from_definition(build_dev_loop_definition(), agent_registry=...,
  node_factories=build_dev_loop_node_factories(...))`, preserving its current
  public signature (back-compat) and the event-publisher / lifecycle wiring.
- Routing parity test (`test_definition_routing_matches_legacy`).

**NOT in scope**: revision graph internals (TASK-012); engine `node_factories`
(TASK-001).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/definition.py` | CREATE | `build_dev_loop_definition` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py` | CREATE | `build_dev_loop_node_factories` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/*.py` | MODIFY | `@register_node("dev_loop.*")` decorators |
| `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` | MODIFY | `build_dev_loop_flow` → wrapper over declarative path |
| `packages/ai-parrot/tests/flows/dev_loop/test_declarative_flow.py` | CREATE | Parity + registration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.flow.flow import AgentsFlow, register_node          # flow.py:157,124
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition  # definition.py
from parrot.flows.dev_loop.nodes.intent_classifier import IntentClassifierNode  # intent_classifier.py
from parrot.flows.dev_loop.nodes.bug_intake import BugIntakeNode
from parrot.flows.dev_loop.nodes.research import ResearchNode
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.flows.dev_loop.nodes.failure_handler import FailureHandlerNode
from parrot.flows.dev_loop.nodes.close import DevLoopCloseNode              # from TASK-009
```

### Existing Signatures to Use
```python
# Current imperative reference — REPRODUCE this routing exactly:
# packages/ai-parrot/src/parrot/flows/dev_loop/flow.py:154  build_dev_loop_flow(*, dispatcher, jira_toolkit,
#     log_toolkits, redis_url, name="dev-loop", publish_flow_events=True, lifecycle_events=True)
#   edges (verbatim semantics):
#     intent → bug_intake   (predicate _is_bug)
#     intent → research     (predicate _is_not_bug)
#     bug_intake → research
#     research → development → qa
#     qa → handoff (predicate _qa_passed); qa → failure (predicate _qa_failed)
#     {intent,bug_intake,research,development,qa,handoff} → failure (condition="on_error")
#   plus FlowEventPublisher on_node_event + FlowLifecycleAdapter listener.

# Engine (from TASK-001):
AgentsFlow.from_definition(definition, *, agent_registry=None, node_factories=None)
# EdgeDefinition predicate is a CEL string (definition.py) — for predicate routing
# use condition="on_condition" + a CEL predicate, OR keep callables by adding the
# edges programmatically after from_definition. Decide and document.

# Node constructors (from current code):
IntentClassifierNode(redis_url=...)            # intent_classifier.py
BugIntakeNode(redis_url=...)                    # bug_intake.py
ResearchNode(dispatcher, jira_toolkit, log_toolkits=None, git_toolkit=..., repos=...)  # research.py (TASK-006)
DevelopmentNode(dispatcher)                     # development.py:32
QANode(dispatcher)                              # qa.py:55
DeploymentHandoffNode(jira_toolkit)             # deployment_handoff.py:57
FailureHandlerNode(jira_toolkit)                # failure_handler.py:34
DevLoopCloseNode(jira_toolkit)                  # close.py (TASK-009)
```

### Does NOT Exist
- ~~any `@register_node` usage in dev_loop today~~ — added here.
- ~~`dev_loop/definition.py` / `dev_loop/factories.py`~~ — created here.
- CEL predicates on `EdgeDefinition` mapping 1:1 to the current Python callables
  (`_is_bug`, `_qa_passed`) — the callables read `result.kind` / `result.passed`.
  If CEL cannot express them cleanly, add those predicate edges programmatically
  via `flow.add_edge(..., predicate=callable)` AFTER `from_definition` (still
  declarative topology for the rest). Document the choice.

---

## Implementation Notes

### Key Constraints
- **Parity is the contract**: the declarative flow MUST route identically to
  `build_dev_loop_flow`. `test_definition_routing_matches_legacy` guards it.
- Factories close over live deps; returned nodes set
  `node_id`/`dependencies`/`successors` exactly like the engine's agent branch.
- Preserve `FlowEventPublisher` + `FlowLifecycleAdapter` wiring and the
  `_run_id_holder` exposure that `DevLoopRunner` seeds.
- Keep `build_dev_loop_flow`'s signature unchanged (callers/tests depend on it).

### References in Codebase
- `flow.py:154-263` — the imperative flow to mirror (edges + publisher wiring).
- `examples/flow/agentsflow_standalone.py` — conditional-routing + OR-join example.

---

## Acceptance Criteria

- [ ] All `dev_loop.*` node types are in `NODE_REGISTRY`.
- [ ] `build_dev_loop_definition()` returns a valid `FlowDefinition` (acyclic, refs resolve).
- [ ] `build_dev_loop_flow(...)` (unchanged signature) runs via the declarative path.
- [ ] `test_definition_routing_matches_legacy`: bug→BugIntake, non-bug→Research, qa-pass→Handoff, qa-fail→Failure, on_error→Failure.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_declarative_flow.py -v` passes.
- [ ] Existing dev-loop flow tests still pass.

---

## Test Specification
```python
def test_register_node_dev_loop_types():
    from parrot.bots.flows.flow.flow import NODE_REGISTRY
    import parrot.flows.dev_loop.factories  # triggers registration
    for t in ["dev_loop.intent_classifier","dev_loop.research","dev_loop.qa",
              "dev_loop.deployment_handoff","dev_loop.close"]:
        assert t in NODE_REGISTRY

async def test_definition_routing_matches_legacy(...):
    """Drive the declarative flow with a bug WorkBrief and a non-bug WorkBrief;
    assert the same nodes execute / skip as the imperative flow."""
```

---

## Agent Instructions
Standard SDD lifecycle. This task integrates TASK-001/003/006/007/008/009 —
verify they are in `tasks/completed/` first.

## Completion Note

**Status**: done — 2026-06-20

**What changed**
- `@register_dev_loop_node("dev_loop.*")` on all 8 node classes
  (intent_classifier, bug_intake, research, development, qa,
  deployment_handoff, failure_handler, close).
- `definition.py` (new): `build_dev_loop_definition(*, revision=False)` returns
  the declarative `FlowDefinition` (8 nodes + edges; CEL predicates mirror the
  legacy callables). `revision=True` raises `NotImplementedError` (TASK-012).
- `factories.py` (new): `build_dev_loop_node_factories(...)` → `{dev_loop.* type:
  factory}`; each factory binds live deps and stamps deps/succs.
- `flow.py`: `build_dev_loop_flow` rewritten — materializes nodes via
  `AgentsFlow.from_definition(definition, node_factories=...)` then executes in
  **explicit-edge mode** (see decision below). Signature preserved; added
  optional `git_toolkit`/`repos`.
- `nodes/base.py`: added `register_dev_loop_node` (idempotent wrapper).

**KEY DECISION — explicit-mode execution (engine limitation, verified
empirically).** The engine's `from_definition` scheduler uses an **AND-join**
(a node spawns only when *all* predecessors completed; flow.py:1046). The
dev-loop merges the bug/non-bug paths at `research` — an **OR-join**. I verified
empirically that under `from_definition` the non-bug path never spawns `research`
(bug_intake is skipped, never "completed"). The OR-join + skip-propagation the
dev-loop needs exists ONLY in the engine's explicit-edge mode. Therefore
`build_dev_loop_flow` uses `from_definition`+`node_factories` to *materialize*
(exercising TASK-001's mechanism + validating the definition) and then executes
via `add_edge` with the callable predicates, reproducing FEAT-132 routing
exactly. The declarative definition is the topology source of record (kept on
`flow._dev_loop_definition`, NOT `flow._definition`, which would re-enable the
AND-join). This honors the cardinal AC "reproduce FEAT-132 routing exactly".

**Idempotent registration (regression fix).** `register_node` raises on
duplicate; `test_lazy_import` re-imports dev_loop after purging `sys.modules`
while the engine's `NODE_REGISTRY` persists → the plain decorator raised on the
2nd import. `register_dev_loop_node` no-ops when already registered.

**Necessary corollary test updates (mandated by the G7 close node):**
- `test_flow.py`: `test_seven_nodes_registered` → `test_all_nodes_registered`
  (now 8 nodes incl. `close`) + new `test_deployment_handoff_routes_to_close`.
- `test_runner.py`: success path now terminates at `close` (added to the
  executed set; handoff PR info read from `result.responses`); qa-fail path
  reads `result.responses["failure_handler"]`. `result.output` is now a
  multi-leaf map because `close` is a second terminal alongside
  `failure_handler` — a deliberate consequence of G7.

**Verification**
- `pytest test_declarative_flow.py` → 8 passed (registration, definition
  validity, factories, CEL parity, and end-to-end routing parity: non-bug skips
  bug_intake, bug runs it, qa-fail→failure — driven through the real
  `build_dev_loop_flow`).
- `test_flow.py` (20) + `test_runner.py` (7) green.
- Full `bots/flows` engine suite: 235 passed. Full dev_loop suite: 199 passed,
  only the 10 **pre-existing** `test_research.py` env failures remain (the
  `JIRA_PROJECT`/`jira_search_issues` mock-shape issue, present with and without
  this work).
- `ruff check` clean on all 15 touched files.
