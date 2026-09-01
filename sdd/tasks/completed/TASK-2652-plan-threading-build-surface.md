# TASK-2652: Thread DevFlowModelPlan through build_dev_flow / factories / runner

**Feature**: FEAT-486 — Refactor Dev-Flow — Per-Seat LLM Configuration, Multi-Agent Development Pool, Configurable Review
**Spec**: `sdd/specs/refactor-dev-flow.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2651
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview / §3 Module 2. Closes the verified gap: `build_dev_flow`
exposes no pool path, so dev_flow's `DevelopmentNode` always runs
single-agent. This task makes the plan reach the nodes.

---

## Scope

- Add optional keyword `model_plan: DevFlowModelPlan | None = None` to
  `build_dev_flow(...)` (`dev_flow/flow.py:85-107`) and
  `build_dev_flow_node_factories(...)` (`dev_flow/factories.py:41-56`).
- When `model_plan.dev_pool` is non-empty: forward the resolved
  `pool_config` (from TASK-2651's resolver) and
  `dispatcher_builder=agent_builder.build_dispatcher` into the
  `DevelopmentNode` factory (currently built via
  `build_dev_loop_node_factories`, `factories.py:91-106` — thread through
  its existing `development_dispatcher_builder`/pool parameters on the
  dev_loop side; grep `build_dev_loop_node_factories` signature first).
- Thread the plan through `DevFlowRunner` per-run: routing-relevant plan
  fields (dev_pool backends/counts, review pair backends, partner enabled)
  join `_execution_policy_for_fingerprint` (`dev_flow/runner.py:306`);
  non-routing fields (model strings for non-graph-shaping seats) stay out —
  follow the documented `execution_policy` convention in
  `dev_loop/checkpoint.py`.
- `model_plan=None` (or omitted) MUST produce byte-identical wiring to
  today — verified by test.
- Unit tests: omitted-plan unchanged; pool threading; fingerprint
  inclusion/exclusion.

**NOT in scope**: collapse rule/logging (TASK-2653), review dispatcher
assembly (TASK-2655), ideation model (TASK-2656), console (TASK-2658).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/flow.py` | MODIFY | `model_plan` kwarg + forwarding |
| `packages/ai-parrot/src/parrot/flows/dev_flow/factories.py` | MODIFY | plan → node factory wiring |
| `packages/ai-parrot/src/parrot/flows/dev_flow/runner.py` | MODIFY | per-run plan + fingerprint fields |
| `packages/ai-parrot/tests/flows/dev_flow/test_plan_threading.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan  # created by TASK-2651
from parrot.flows.dev_loop.agent_builder import build_dispatcher  # agent_builder.py:102
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_flow/flow.py:85-107 (keyword-only; verified 2026-09-01)
def build_dev_flow(*, dispatcher, redis_url, jira_toolkit=None, git_toolkit=None,
    wiki_toolkit=None, codereview_dispatcher=None, development_dispatcher_builder=None,
    development_pool_max: int = 4, graph_memory=None, wiki_search=None,
    skip_qa: bool = False, require_plan_approval: bool = False,
    ideation_max_rounds=None, name: str = "dev-flow", ...) -> AgentsFlow: ...

# packages/ai-parrot/src/parrot/flows/dev_flow/factories.py:41-56,91-106
def build_dev_flow_node_factories(...):  # returns dict(build_dev_loop_node_factories(...)) + 2 dev_flow entries (:127-128)

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py:87-98
class DevelopmentNode:
    def __init__(self, *, dispatcher, dispatch_profile=None,
                 pool_config: DevAgentPoolConfig | None = None,
                 dispatcher_builder: DispatcherBuilder | None = None, pool_max: int = 4,
                 require_plan_approval: bool = False, jira_toolkit=None,
                 name: str = "development"): ...
# DispatcherBuilder = Callable[[DevAgentSpec], Tuple[DevLoopCodeDispatcher, BaseModel]]  # development.py:54

# packages/ai-parrot/src/parrot/flows/dev_flow/runner.py — DevFlowRunner HAS NO __init__ (:40);
# it overrides run() (:58-213), _dev_loop_flow_factory (:276),
# _execution_policy_for_fingerprint (:306). Per-run knobs travel via extra_shared → shared_data (:133-134).

# packages/ai-parrot/src/parrot/flows/dev_loop/checkpoint.py — compute_input_fingerprint();
# execution_policy is the ONLY sanctioned carrier of routing-relevant config
# (its docstring documents that adding keys changes existing fingerprints).
# TOPOLOGY_VERSION = "1" — MUST NOT be bumped by this feature (no shape change).
```

### Does NOT Exist
- ~~`build_dev_flow(development_pool_config=...)`~~ / ~~`development_profile`~~ / ~~`repos`~~ — the plan kwarg is the new path; do not invent parallel kwargs.
- ~~`DevFlowRunner.__init__`~~ — inherits `DevLoopRunner.__init__` (`dev_loop/runner.py:389-403`); do not add one unless unavoidable, prefer flow-kwargs/extra_shared threading.
- ~~FEAT-480 allowlist changes~~ — `_SHARED_DATA_ALLOWLIST` must remain untouched by this task.

---

## Implementation Notes

### Key Constraints
- Backward compatibility is an acceptance criterion: omitted plan ⇒
  today's exact wiring (assert factory kwargs in tests).
- Verify the current `build_dev_loop_node_factories` signature before
  threading (dev_loop side may have moved since the contract was written —
  FEAT-482 is landing in adjacent files).
- Keyword-only params, `None` defaults, async untouched.

### References in Codebase
- `dev_flow/factories.py:108-128` — existing two-node factory extension pattern
- `dev_loop/flow.py:332-359` — `build_dev_loop_flow` already accepts pool params (naming precedent)

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_plan_threading.py -v`
- [ ] `build_dev_flow()` without `model_plan` produces today's wiring (test-asserted)
- [ ] Plan with 2 pool specs ⇒ DevelopmentNode factory receives matching `pool_config` + `build_dispatcher`
- [ ] Routing-relevant plan fields change the fingerprint; model-string-only changes do not
- [ ] `ruff check` clean on the three modified files

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_plan_threading.py
import pytest
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan
from parrot.flows.dev_loop.models.base import DevAgentSpec

class TestPlanThreading:
    def test_omitted_plan_is_backward_compatible(self): ...
    def test_pool_threaded_into_development_node(self): ...
    def test_fingerprint_includes_routing_fields(self): ...
    def test_fingerprint_excludes_nonrouting_fields(self): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** — TASK-2651 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** first (grep/read each anchor — FEAT-482 lands in adjacent files)
4. **Update status** in `sdd/tasks/index/refactor-dev-flow.json` → `"in-progress"`
5. **Implement**; 6. **Verify**; 7. **Move this file** to `sdd/tasks/completed/`;
8. **Update index** → `"done"`; 9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5)
**Date**: 2026-09-01
**Notes**:
- `build_dev_flow(model_plan=...)` and
  `build_dev_flow_node_factories(model_plan=...)` added as keyword-only
  optionals with `None` defaults, placed just before `name` / after
  `ideation_max_rounds` respectively.
- Contract re-verified: `build_dev_loop_node_factories` **already**
  accepts `development_pool_config` (factories.py:51) and passes it
  straight to `DevelopmentNode(pool_config=...)` (:167), so no dev_loop
  signature change was needed — dev_flow just stops leaving the parameter
  unset. `agent_builder.build_dispatcher` is imported lazily, inside the
  branch that needs it, so a plan-less build does not pay for importing
  every coding-agent client.
- **Backward-compat decision**: `resolve_model_plan()` runs only when a
  plan was actually supplied. An omitted/`None` plan therefore ignores
  `DEV_FLOW_DEV_POOL` entirely, which is what makes the
  "no breaking changes" acceptance criterion literally true (test:
  `test_omitted_plan_ignores_env_pool`). Passing an all-defaults
  `DevFlowModelPlan()` is the explicit opt-in to env resolution.
- An explicit `development_dispatcher_builder` still wins over the
  plan-derived `build_dispatcher` (test:
  `test_explicit_builder_beats_plan_derived`).
- `_execution_policy_for_fingerprint` gains a `model_plan` sub-dict
  **only when a plan is present** — pre-FEAT-486 fingerprints are
  bit-stable. Routing-relevant fields included: per-spec
  `(agent, count)` for the pool, `review.primary.agent`, and
  `research_partner.enabled`. Deliberately excluded (non-routing, so a
  model swap is a resume *hit*): `research_primary`, per-spec `model`,
  `review.counter_model`. Mirrors the conditional-key precedent at
  `dev_loop/runner.py:1383-1389`.
- `DevFlowRunner` needed no `__init__` and no new attribute: the plan
  rides `self._dev_loop_flow_kwargs`, which `_dev_loop_flow_factory`
  already splats into `build_dev_flow` — so checkpoint recovery rebuilds
  the flow with the same plan for free.
- `TOPOLOGY_VERSION` not bumped; `_SHARED_DATA_ALLOWLIST` untouched.
- 20 new unit tests pass; full `tests/flows/dev_flow/` suite green
  (235 passed). `ruff check` clean on all three modified files.

**Deviations from spec**: none. One pre-existing lint artifact noted:
`dev_flow/flow.py` carries a `# noqa: PLC0415` that bare `ruff check`
reports as RUF100 (the repo ships no ruff config, so PLC0415 is not
enabled by default). It is present on `dev` before this task and was
left alone rather than "fixed" as out-of-scope; my own new lazy import
therefore carries no `noqa`.
