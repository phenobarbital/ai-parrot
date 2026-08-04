# TASK-2127: dev-flow topology — definition, factories, flow builder + parity

**Feature**: FEAT-412 — Dev-Flow: SDD-Oriented AgentsFlow for Feature Development
**Spec**: `sdd/specs/sdd-dev-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2125, TASK-2126
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Authors the dev-flow graph declaratively
(`FlowDefinition`), binds live dependencies via factories, and builds the
executable `AgentsFlow` in the engine's explicit-edge mode (the OR-joins at
`planner` and `failure_handler` cannot run under the AND-join
`from_definition` scheduler — same engine limitation as dev_loop).

---

## Scope

- `dev_flow/definition.py` — `build_dev_flow_definition() -> FlowDefinition`
  (`flow="dev-flow"`). Nodes: `dev_flow.dev_intake`, `dev_flow.ideation`,
  plus reused types `dev_loop.planner`, `dev_loop.development`,
  `dev_loop.synthesis`, `dev_loop.qa`, `dev_loop.feedback_router`,
  `dev_loop.feature_handoff`, `dev_loop.failure_handler`, `dev_loop.close`.
  Edges (spec §2):
  - `dev_intake → ideation`:
    `'result.kind == "enhancement" || result.kind == "new_feature"'`
  - `dev_intake → planner`: `'result.kind == "feature"'`
  - `ideation → planner`: on_success
  - `planner → development → synthesis → qa` and the QA/feedback/handoff
    edges: REPLICATE `_build_feature_definition()` (FEAT-378) verbatim,
    including `_CEL_FEEDBACK_*` predicates and the `feedback_router →
    development` bounded-retry edge.
  - on_error fan-in: every middle node → `failure_handler`.
- `dev_flow/factories.py` — wrap `build_dev_loop_node_factories(...)` for
  the reused types + add factories for the two new node types (dispatcher,
  wiki_search, ideation config injection).
- `dev_flow/flow.py` — `build_dev_flow(*, dispatcher, redis_url,
  jira_toolkit=None, git_toolkit=None, wiki_toolkit=None,
  codereview_dispatcher=None, development_dispatcher_builder=None,
  development_pool_max=4, graph_memory=None, wiki_search=None,
  skip_qa=False, require_plan_approval=False, ideation_max_rounds=None,
  name="dev-flow", publish_flow_events=True) -> AgentsFlow` — mirror
  `build_dev_loop_feature_flow` (runner.py:178): materialize from the
  definition via factories, wire explicit edges, attach the
  `FlowEventPublisher` when `publish_flow_events`.
- Parity test between the declarative definition and the imperative wiring
  (dev_loop `test_declarative_flow.py` precedent) + definition-validity
  test.

**NOT in scope**: runner (TASK-2128), server (TASK-2129), any change to
`dev_loop/definition.py` or dev_loop factories.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/definition.py` | CREATE | Declarative topology |
| `packages/ai-parrot/src/parrot/flows/dev_flow/factories.py` | CREATE | Dependency-binding factories |
| `packages/ai-parrot/src/parrot/flows/dev_flow/flow.py` | CREATE | `build_dev_flow` |
| `packages/ai-parrot/tests/flows/dev_flow/test_definition.py` | CREATE | Validity + inventory tests |
| `packages/ai-parrot/tests/flows/dev_flow/test_flow_parity.py` | CREATE | Declarative↔imperative parity |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows import AgentsFlow                       # verified 2026-08-05
from parrot.bots.flows.flow.definition import (
    EdgeDefinition, FlowDefinition, NodeDefinition,
)
from parrot.flows.dev_loop.factories import build_dev_loop_node_factories
from parrot.flows.dev_loop.flow import FlowEventPublisher      # flow.py (class)
from parrot import conf
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/definition.py
# Authoring style to REPLICATE (verified 2026-08-05):
#   _node(id) -> NodeDefinition(id=id, type=f"dev_loop.{id}")
#   EdgeDefinition(**{"from": SRC}, to=DST, condition="on_success")
#   EdgeDefinition(**{"from": SRC}, to=DST, condition="on_condition",
#                  predicate=<CEL string>)
# FEAT-378 feature graph (copy these predicates verbatim):
#   _CEL_IS_FEATURE = 'result.kind == "feature"'
#   _CEL_QA_PASSED = "result.passed == true"
#   _CEL_FEEDBACK_ESCALATE = 'result.decision == "escalate"'
#   _CEL_FEEDBACK_ACCEPT = 'result.decision == "accept_with_notes"'
#   _CEL_FEEDBACK_RETRY = 'result.decision == "retry"'   # bound lives in
#       FeedbackRouterNode._retry_allowed(), NOT on the edge
#   feature on_error sources: (INTENT, PLANNER, DEVELOPMENT, SYNTHESIS,
#       QA, FEEDBACK_ROUTER, FEATURE_HANDOFF)
#   qa routing in feature mode: passed → feature_handoff; failed →
#       feedback_router (see _build_feature_definition docstring diagram)

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:178
def build_dev_loop_feature_flow(*, dispatcher, jira_toolkit=None,
    git_toolkit=None, wiki_toolkit=None, redis_url,
    codereview_dispatcher=None, development_dispatcher_builder=None,
    development_pool_max=4, graph_memory=None,
    require_plan_approval=False, skip_qa=False,
    name="dev-loop-feature", publish_flow_events=True) -> AgentsFlow
# ^ the declarative-materialize-then-explicit-edge pattern to mirror.
```

### Does NOT Exist
- ~~`build_dev_flow_definition` / `build_dev_flow`~~ — created here.
- ~~`build_dev_loop_definition(sdd=True)` or any new dev_loop flag~~ —
  explicitly rejected (spec §8): dev-flow is its own package/definition.
- ~~`AgentsFlow.from_definition` execution for this graph~~ — AND-join
  scheduler cannot fire the `planner` OR-join; use explicit-edge mode.
- ~~`dev_loop.research` / `dev_loop.bug_intake` / `dev_loop.
  deployment_handoff` in the dev-flow graph~~ — deliberately absent.

---

## Implementation Notes

### Key Constraints
- The reused `dev_loop.*` node types resolve from the SAME engine
  `NODE_REGISTRY` — importing `parrot.flows.dev_loop.nodes` (and
  `parrot.flows.dev_flow.nodes`) must happen before materialization;
  follow dev_loop's lazy-import discipline.
- `require_plan_approval` and `skip_qa` are forwarded into the reused node
  factories exactly as `build_dev_loop_feature_flow` does.
- Definition module stays pure (no env reads at import); read
  `conf.DEV_LOOP_QA_MAX_RETRIES` etc. inside the builder functions like
  dev_loop's `build_dev_loop_definition` does.

### References in Codebase
- `dev_loop/definition.py::_build_feature_definition` — the chain to replicate
- `dev_loop/flow.py::build_dev_loop_flow` — explicit-edge wiring + publisher
- `tests/flows/dev_loop/test_declarative_flow.py` — parity-test shape

---

## Acceptance Criteria

- [ ] `build_dev_flow_definition()` validates; node/edge inventory matches spec §2 exactly (10 nodes; no bug/research/deployment nodes)
- [ ] Parity test passes (declarative ↔ imperative)
- [ ] `build_dev_flow(...)` returns a runnable `AgentsFlow` named "dev-flow"
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_definition.py test_flow_parity.py -v`; `ruff` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_definition.py
def test_definition_validates(): ...
def test_node_inventory_matches_spec(): ...       # exact 10-node set
def test_edge_predicates(): ...                   # CEL strings verbatim
def test_no_ops_nodes_present(): ...              # bug_intake/research absent
# test_flow_parity.py
def test_declarative_imperative_parity(): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2125, TASK-2126 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/sdd-dev-flow.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`,
   update index → `"done"`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
