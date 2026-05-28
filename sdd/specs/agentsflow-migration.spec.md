---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: AgentsFlow Migration — finish moving `bots/flow/` into `bots/flows/`

**Feature ID**: FEAT-196
**Date**: 2026-05-28
**Author**: Jesus Lara
**Status**: draft
**Target version**: next minor
**Depends on**: FEAT-134 (`flow-primitives`, merged), FEAT-143 (`flows-consolidation`, merged), FEAT-147 (`flows/core/storage/persistence.py`, merged), FEAT-163 (`agentsflow-refactor-spec3`, merged)
**Source brainstorm**: `sdd/proposals/agentsflow-migration.brainstorm.md` (Option A, 14 resolved questions)
**Supersedes**: FEAT-009 (`agentsflow-persistency`) — persistence work has been delivered by FEAT-147; FEAT-009 should be marked obsolete in its spec metadata as part of this feature's task graph.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-163 moved AgentsFlow's **FSM engine** out of `parrot/bots/flow/fsm.py`
into `parrot/bots/flows/core/` + `parrot/bots/flows/flow.py` and deleted
the legacy `fsm.py` (TASK-1069). FEAT-143 had previously moved `AgentCrew`
to `parrot/bots/flows/crew/` and introduced the canonical result/context
models (`FlowResult`, `NodeResult`, `FlowContext.shared_data`,
`build_node_metadata`, `NodeExecutionInfo`).

**The migration is half-done.** The legacy `parrot/bots/flow/` (singular)
still hosts 17 files (~3,456 LoC) that the new world depends on:

- `parrot/bots/flows/flow.py` itself imports `FlowDefinition`,
  decision-node types, `InteractiveDecisionNode`, and (lazily)
  `CELPredicateEvaluator` from `parrot.bots.flow.*` — see §6 for the
  exact line numbers.
- `parrot/flows/dev_loop/*` (8 production files) imports `AgentsFlow`
  and `Node` from `parrot.bots.flow.*`.
- 31 test files reference `parrot.bots.flow.*` directly. Several of
  these are **broken at HEAD** because they import the deleted
  `parrot.bots.flow.fsm` (FEAT-163 TASK-1069).
- `parrot/bots/flow/__init__.py` is a hybrid re-exporter — some symbols
  forwarded to `flows/core/*`, others still living in `flow/*`.

The remaining files split into three behavioural groups:

1. **Already-canonicalised siblings** — `flow/storage/{memory,mixin,
   synthesis}.py` and `flow/tools.py` have richer/newer counterparts in
   `flows/core/storage/*` and `flows/tools.py`. The old copies are
   redundant duplicates kept alive only by stale imports.
2. **Move-only files** — `actions.py`, `cel_evaluator.py`,
   `definition.py`, `loader.py`, `svelteflow.py`. Self-contained
   primitives with no counterpart in `flows/`.
3. **Re-architecture targets** — `decision_node.py` (1,140 LoC) and
   `interactive_node.py` (99 LoC). These predate the FEAT-137 / FEAT-163
   rich `flows/core/node.AgentNode`. They get rewritten as subclasses of
   `Node` / `AgentNode`.

Without this migration the two packages remain bidirectionally coupled,
the dev-loop PoC documents the wrong import path as canonical, and the
test suite stays partially broken at HEAD.

### Goals

- Convert `parrot/bots/flows/flow.py` (single file) into the
  `parrot/bots/flows/flow/` **subpackage**, mirroring the existing
  `parrot/bots/flows/crew/` layout. AgentsFlow → `flows/flow/flow.py`.
- Move every behavioural file out of `parrot/bots/flow/` into
  `parrot/bots/flows/flow/` (flat layout, no further subpackaging unless
  a file outgrows reason).
- Rewrite `DecisionFlowNode` family + `InteractiveDecisionNode` as
  subclasses of `flows/core/node.AgentNode` (or `Node` for non-agent
  decisions); collect them in a single `flows/flow/nodes.py`.
- Reconcile `flow/storage/*` with `flows/core/storage/*`; canonical
  `flows/core/storage/*` wins; salvage any missing semantics before
  deleting the old code.
- Adopt the FEAT-143 canonical models throughout the AgentsFlow run
  path: `FlowResult` as return type, `NodeResult` for per-node output,
  `FlowContext` (with `shared_data`) for shared run state,
  `build_node_metadata` + `NodeExecutionInfo` for telemetry.
- Curate `parrot/bots/flows/__init__.py` re-exports — only deliberate
  primitives at the package root. `CELPredicateEvaluator`,
  action-registry plumbing, and other transition/runtime internals stay
  in their submodules.
- Repoint every in-tree consumer (`parrot/bots/flows/flow.py` itself,
  `parrot/flows/dev_loop/*`, 31 test files) to the new paths in the
  same PR. Tests broken at HEAD get rewritten against the new node +
  result models, not quarantined.
- Delete `parrot/bots/flow/` entirely. No back-compat shim.

### Non-Goals (explicitly out of scope)

- **Behavioural changes to AgentsFlow's four execution modes** (parallel
  DAG `run_flow`, sequential, parallel-fanout, loop) — this is a refactor.
- **New decision-node types** — preserve the existing public surface
  (`DecisionFlowNode`, `BinaryDecision`, `ApprovalDecision`,
  `MultiChoiceDecision`, etc.) verbatim; only the implementation moves.
- **Per-decision-type module split** — the 1,140-LoC `decision_node.py`
  becomes a single `flows/flow/nodes.py` module. Rejected in brainstorm
  Round 3 — see `sdd/proposals/agentsflow-migration.brainstorm.md`.
- **Promoting `CELPredicateEvaluator` to public API** — stays internal
  to `flows/flow/` for now; promotion can happen later if a real
  external use case appears.
- **Back-compat shim at `parrot/bots/flow/`** — rejected in brainstorm
  Round 1.
- **Codemod-driven mass rewrite (Option C in brainstorm)** — rejected;
  manual edits + `ruff --fix` + IDE refactor are sufficient and the
  codemod investment doesn't pay back on the expensive 70% of the work.
- **FEAT-009 (`agentsflow-persistency`)** — superseded by FEAT-147's
  `flows/core/storage/persistence.py`; this feature only marks FEAT-009
  obsolete, it does not deliver any persistence work itself.

---

## 2. Architectural Design

### Overview

A **layered atomic migration** delivered as one feature branch and one
PR. The task graph follows a strict topological order so each layer
leaves the tree in a green-test state:

1. **L1 — Move-only relocations.** Convert `flows/flow.py` into the
   `flows/flow/` subpackage. The AgentsFlow class moves to
   `flows/flow/flow.py`. `actions.py`, `cel_evaluator.py`,
   `definition.py`, `loader.py`, `svelteflow.py` move from singular
   `flow/` flat into `flows/flow/`. No behavioural changes; new files
   import from `flows/core/*` (already canonical) instead of singular
   `flow/` siblings.
2. **L2 — Storage reconciliation.** Diff `flow/storage/{memory,mixin,
   synthesis}.py` against `flows/core/storage/*`; port any unique
   semantics into the canonical files; delete `flow/storage/`. Repoint
   any straggler imports that still reference the old storage path.
3. **L3 — Node rewrites.** Reimplement `DecisionFlowNode`,
   `DecisionResult`, `DecisionMode`, `DecisionType`, `BinaryDecision`,
   `ApprovalDecision`, `MultiChoiceDecision`, `EscalationPolicy`,
   `VoteWeight`, and `InteractiveDecisionNode` as subclasses of
   `flows/core/node.AgentNode` (or `Node` for non-agent decisions).
   All decision + interactive node types land in `flows/flow/nodes.py`
   — mirrors `flows/crew/nodes.py`. Public symbol names preserved;
   internals adopt `NodeResult`, `FlowContext.shared_data`, and
   `build_node_metadata`. Old `decision_node.py` + `interactive_node.py`
   deleted.
4. **L4 — Internal repointing.** Update `flows/flow/flow.py` (post-L1
   home of the AgentsFlow class) to import from `parrot.bots.flows.*`
   only. The four cross-package imports at the current `flows/flow.py`
   lines 42, 45, 51, 508 collapse into intra-subpackage imports.
5. **L5 — External consumer repointing + test refactor.** Repoint
   `parrot/flows/dev_loop/{flow,nodes/*}.py` (8 files) and all 31 test
   files. Tests broken at HEAD (those importing the deleted
   `parrot.bots.flow.fsm`) get **rewritten** against the new node +
   result models in the same PR.
6. **L6 — Cleanup + curated public API.** Delete `parrot/bots/flow/`
   entirely. Rewrite `parrot/bots/flows/__init__.py` to expose only the
   deliberate primitives. Update any docstrings/examples that reference
   the old path. Mark FEAT-009 spec obsolete.

### Component Diagram

```
BEFORE (current state — half-migrated):

  parrot/bots/flow/                       parrot/bots/flows/
  ├── __init__.py (hybrid re-exporter)    ├── __init__.py
  ├── actions.py        ←──┐              ├── flow.py  ──→ imports from
  ├── cel_evaluator.py  ←──┤                  parrot.bots.flow.* (lines
  ├── decision_node.py  ←──┤                  42, 45, 51, 508)
  ├── definition.py     ←──┤              ├── core/  (canonical primitives)
  ├── interactive_node.py ─┤              ├── crew/   ├── __init__.py
  ├── loader.py         ←──┤              │           ├── crew.py
  ├── node.py           ←──┤              │           └── nodes.py
  ├── nodes/{start,end} ←──┤              ├── agents/ orchestrator + A2A + HR
  ├── storage/{...}     ←──┤              └── tools.py  (canonical
  ├── svelteflow.py     ←──┤                              ResultRetrievalTool)
  └── tools.py (DUP) ←─────┘
       │
       └── 31 tests + parrot/flows/dev_loop/* import from here too


AFTER (target state — single canonical package):

  parrot/bots/flows/
  ├── __init__.py             (curated public re-exports only)
  ├── flow/                   (NEW subpackage — mirrors crew/)
  │   ├── __init__.py
  │   ├── flow.py             (AgentsFlow class; was flows/flow.py)
  │   ├── nodes.py            (DecisionFlowNode + family +
  │   │                        InteractiveDecisionNode, rewritten on AgentNode)
  │   ├── definition.py       (moved from singular)
  │   ├── loader.py           (moved)
  │   ├── svelteflow.py       (moved)
  │   ├── actions.py          (moved)
  │   └── cel_evaluator.py    (moved; INTERNAL — not re-exported)
  ├── core/                   (unchanged — canonical primitives)
  │   ├── node.py             (Node, AgentNode, StartNode, EndNode)
  │   ├── result.py           (FlowResult, NodeResult, NodeExecutionInfo,
  │   │                        build_node_metadata)
  │   ├── context.py          (FlowContext with shared_data)
  │   ├── fsm.py, transition.py, types.py
  │   └── storage/            (canonical — receives ports from L2)
  ├── crew/                   (unchanged)
  ├── agents/                 (unchanged)
  └── tools.py                (unchanged — canonical ResultRetrievalTool)

  parrot/bots/flow/           [DELETED]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/bots/flow/*` | **deletes** | Entire package removed in L6. |
| `parrot/bots/flows/flow.py` | **becomes a subpackage** | Single file → `parrot/bots/flows/flow/` subpackage. AgentsFlow class lands at `flow/flow.py`. |
| `parrot/bots/flows/core/node.{Node, AgentNode}` | reuses | DecisionFlowNode + InteractiveDecisionNode rewritten as subclasses. |
| `parrot/bots/flows/core/result.{FlowResult, NodeResult, NodeExecutionInfo}` | adopts | AgentsFlow's run() returns `FlowResult`; per-node output is `NodeResult`. |
| `parrot/bots/flows/core/context.FlowContext` | adopts | Used as the shared run-state container in all four AgentsFlow modes; `shared_data` used by decision/interactive nodes. |
| `parrot/bots/flows/core/result.build_node_metadata` | adopts | AgentsFlow telemetry built via this helper so OTel (FEAT-177) sees uniform shape from both engines. |
| `parrot/bots/flows/core/storage/{memory,mixin,persistence,synthesis}` | extends | Receives any missing semantics ported from old `flow/storage/`. |
| `parrot/bots/flows/__init__.py` | modifies | Re-exports curated — `CELPredicateEvaluator`, action registry internals, etc. removed from root surface. |
| `parrot/flows/dev_loop/{flow.py, nodes/*}` | modifies | 8 files repointed to `parrot.bots.flows.*`. |
| 31 test files | modifies / refactors | Imports updated; tests broken at HEAD (importing deleted `parrot.bots.flow.fsm`) rewritten against new models. |
| `parrot/bots/orchestration/` | unaffected | Already migrated by FEAT-143. |
| `parrot/observability/` (FEAT-177 OTel) | indirectly benefits | Uniform `NodeExecutionInfo` from both AgentCrew and AgentsFlow. |
| External: Navigator project | pre-`/sdd-task` check | If Navigator imports `parrot.bots.flow.*`, coordinate a lockstep PR. |

### Data Models

This feature introduces **no new data models**. It adopts the existing
FEAT-143 canonical models inside AgentsFlow's run path:

```python
# Canonical models AgentsFlow's run path will use (already exist):

# parrot/bots/flows/core/result.py:39
@dataclass
class NodeResult:
    node_id: str
    node_name: str
    task: str
    result: Any
    ai_message: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    timestamp: datetime
    parent_execution_id: Optional[str] = None
    execution_id: str
    # @property agent_id, agent_name — backward-compat aliases

# parrot/bots/flows/core/result.py:273
@dataclass
class FlowResult: ...

# parrot/bots/flows/core/result.py:190
@dataclass
class NodeExecutionInfo: ...

# parrot/bots/flows/core/result.py:527
def build_node_metadata(...) -> dict: ...

# parrot/bots/flows/core/context.py:51
@dataclass
class FlowContext:
    node_metadata: Dict[str, NodeExecutionInfo]    # line 74
    shared_data: Dict[str, Any]                    # line 89 (FEAT-143)
    agent_registry: Optional["AgentRegistry"]      # line 92 (FEAT-163)
```

The `DecisionFlowNode` family and `InteractiveDecisionNode` keep their
existing public attribute shapes (preserved as a behavioural contract);
only their base class changes — from the legacy `parrot.bots.flow.node.Node`
to the canonical `parrot.bots.flows.core.node.AgentNode` (or `Node`).

### New Public Interfaces

This feature introduces **no new public interfaces**. The set of
public symbols at `parrot.bots.flows` is **reduced** by curation:
internals that today are reachable from the package root (e.g.,
`CELPredicateEvaluator`, action-registry internals) move out of the
root re-exports and become submodule-only.

The set of public symbols at `parrot.bots.flow` shrinks to zero — the
package is deleted. Any code that today imports `from parrot.bots.flow
import X` must change to `from parrot.bots.flows import X` (or a
submodule path for the curated-out symbols).

---

## 3. Module Breakdown

> Each module below represents a file (or small file group) created,
> moved, rewritten, or deleted. These map ~1:1 to `/sdd-task` artefacts.

### Module 1: `flows/flow/` subpackage skeleton
- **Path**: `parrot/bots/flows/flow/{__init__.py, flow.py}`
- **Responsibility**: Convert `parrot/bots/flows/flow.py` (single file)
  into a subpackage. `flow/__init__.py` re-exports `AgentsFlow`,
  `NODE_REGISTRY`, `register_node`, `CompletionEvent`. `flow/flow.py`
  holds the AgentsFlow class body (moved from current `flows/flow.py`).
- **Depends on**: nothing (this is L1, first move).

### Module 2: Move-only relocations (5 files)
- **Path**: `parrot/bots/flows/flow/{actions.py, cel_evaluator.py,
  definition.py, loader.py, svelteflow.py}`
- **Responsibility**: Verbatim relocation from `parrot/bots/flow/` to
  `parrot/bots/flows/flow/`. Internal imports inside each file are
  updated to reference siblings via relative imports (`from .definition
  import ...`) or `parrot.bots.flows.core.*` where applicable.
- **Depends on**: Module 1.

### Module 3: Storage reconciliation
- **Path**: `parrot/bots/flows/core/storage/{memory,mixin,synthesis}.py`
- **Responsibility**: Compare old `parrot/bots/flow/storage/{memory,
  mixin,synthesis}.py` against canonical `parrot/bots/flows/core/storage/*`
  on a behavioural diff. Port any unique semantics from the old code
  into the canonical files (with covering tests). Repoint any stragglers
  that still import `parrot.bots.flow.storage.*` (e.g.,
  `tests/test_orchestrator_agent.py`,
  `tests/test_execution_memory_integration.py`). Delete
  `parrot/bots/flow/storage/`.
- **Depends on**: Module 1, Module 2.

### Module 4: `flows/flow/nodes.py` — decision + interactive nodes
- **Path**: `parrot/bots/flows/flow/nodes.py`
- **Responsibility**: Rewrite `DecisionFlowNode`, `DecisionResult`,
  `DecisionMode`, `DecisionType`, `DecisionNodeConfig`, `BinaryDecision`,
  `ApprovalDecision`, `MultiChoiceDecision`, `EscalationPolicy`,
  `VoteWeight`, and `InteractiveDecisionNode` as subclasses of
  `parrot.bots.flows.core.node.AgentNode` (or `Node` for non-agent
  decisions). Public symbol names and attribute shapes preserved as the
  behavioural contract. Internals adopt `NodeResult`,
  `FlowContext.shared_data`, and `build_node_metadata`. Delete old
  `parrot/bots/flow/{decision_node.py, interactive_node.py}`.
- **Depends on**: Module 1.

### Module 5: AgentsFlow class internal repointing
- **Path**: `parrot/bots/flows/flow/flow.py`
- **Responsibility**: Update the AgentsFlow class to import from
  `parrot.bots.flows.*` only. The four cross-package imports at lines
  42, 45, 51, 508 (in the original `flows/flow.py`) collapse into
  intra-subpackage relative imports: `from .definition import
  FlowDefinition`, `from .nodes import DecisionFlowNode, ...`,
  `from .cel_evaluator import CELPredicateEvaluator`. Adopt
  `FlowResult` as the return type of `AgentsFlow.run()`; use
  `NodeResult` for per-node output; pass a `FlowContext` (with
  `shared_data`) as the shared run state; emit telemetry via
  `build_node_metadata` + `NodeExecutionInfo`.
- **Depends on**: Modules 1, 2, 3, 4.

### Module 6: `parrot/flows/dev_loop/` consumer repointing
- **Path**: `parrot/flows/dev_loop/{flow.py, nodes/{bug_intake,
  deployment_handoff, development, failure_handler, intent_classifier,
  qa, research}.py}` (8 files)
- **Responsibility**: Replace `from parrot.bots.flow import AgentsFlow`
  with `from parrot.bots.flows import AgentsFlow`; replace `from
  parrot.bots.flow.node import Node` with `from
  parrot.bots.flows.core.node import Node`. Verify dev_loop still runs
  end-to-end after the repoint.
- **Depends on**: Module 5.

### Module 7: Test suite repointing + broken-test refactor
- **Path**: 31 test files under `packages/ai-parrot/tests/` (full list
  in §6 Codebase Contract → Verified Imports → "Tests").
- **Responsibility**: Repoint imports to `parrot.bots.flows.*` or the
  appropriate submodule. **Refactor** (not quarantine) tests that
  already break at HEAD because they import `parrot.bots.flow.fsm`
  (`test_fsm.py`, `test_agentsflow_branch.py`,
  `test_agent_crew_examples.py`, `test_execution_memory_integration.py`
  — others as discovered) — rewrite them against `flows/core/*` and
  `flows/flow/*` primitives. Ensure the full suite is green.
- **Depends on**: Modules 5, 6.

### Module 8: Curate `parrot/bots/flows/__init__.py`
- **Path**: `parrot/bots/flows/__init__.py`
- **Responsibility**: Rewrite the public re-export list to expose only
  deliberate primitives:
  - **Keep at root**: `AgentLike`, `AgentRef`, `DependencyResults`,
    `PromptBuilder`, `ActionCallback`, `CrewHookCallback`, `FlowStatus`,
    `Node`, `AgentNode`, `StartNode`, `EndNode`, `FlowResult`,
    `NodeResult`, `NodeExecutionInfo`, `FlowContext`, `FlowTransition`,
    `AgentTaskMachine`, `TransitionCondition`, `ExecutionMemory`,
    `VectorStoreMixin`, `PersistenceMixin`, `SynthesisMixin`,
    `AgentCrew`, `CrewAgentNode`, `OrchestratorAgent`,
    `A2AOrchestratorAgent`, `ResultRetrievalTool`, `AgentsFlow`,
    `NODE_REGISTRY`, `register_node`, `FlowDefinition`,
    `NodeDefinition`, `EdgeDefinition`, `DecisionFlowNode`,
    `InteractiveDecisionNode`, the public Decision sub-types
    (`BinaryDecision`, `ApprovalDecision`, `MultiChoiceDecision`).
  - **Demote to submodule-only**: `CELPredicateEvaluator`,
    `ACTION_REGISTRY`, `register_action`, `create_action`, `BaseAction`
    and concrete action classes, `from_svelteflow` / `to_svelteflow`,
    `FlowLoader`, internal action-definition Pydantic classes (the
    `*ActionDef` set). Callers needing these import from their
    submodule path (e.g., `from parrot.bots.flows.flow.cel_evaluator
    import CELPredicateEvaluator`).
- **Depends on**: Modules 5, 6, 7.

### Module 9: Delete `parrot/bots/flow/`
- **Path**: `parrot/bots/flow/` (entire directory)
- **Responsibility**: Remove the entire singular package. Verify no
  `parrot.bots.flow` import remains anywhere in-tree (`grep -rn
  "parrot\.bots\.flow\b"` returns nothing except `parrot/bots/flows`
  matches). Run the full test suite + `python -c "import
  parrot.bots.flows"` smoke test.
- **Depends on**: Modules 1–8.

### Module 10: Mark FEAT-009 obsolete + docs sweep
- **Path**: `sdd/specs/agentsflow-persistency.spec.md` + any docs
  referencing `parrot.bots.flow`
- **Responsibility**: Update `sdd/specs/agentsflow-persistency.spec.md`
  metadata: set `Status: obsolete` (or equivalent) with a note pointing
  to FEAT-147's `flows/core/storage/persistence.py` as the delivered
  replacement and this FEAT-196 spec as the migration that ratified the
  decision. Grep `docs/`, `README.md`, `CLAUDE.md`, and SDD specs for
  `parrot.bots.flow` references and update them to `parrot.bots.flows`.
- **Depends on**: Module 9.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_subpackage_import` | M1 | `import parrot.bots.flows.flow` resolves and exposes `AgentsFlow`. |
| `test_move_only_imports` | M2 | Each moved file (`actions`, `cel_evaluator`, `definition`, `loader`, `svelteflow`) imports cleanly from the new path; symbol identity preserved (same object pre/post-move when compared in a vendored snapshot). |
| `test_storage_behavioural_parity` | M3 | A `NodeResult` stream written to the canonical `ExecutionMemory` produces the same observable state (read-back, vectorisation surface, persistence hooks) as the legacy `ExecutionMemory` did. |
| `test_decision_node_contract` | M4 | Each public attribute / method of the old `DecisionFlowNode` family is present on the rewritten version with the same shape. (Captured as a freeze-test against the current public surface.) |
| `test_interactive_node_contract` | M4 | Same freeze-test for `InteractiveDecisionNode`. |
| `test_node_inheritance` | M4 | `DecisionFlowNode` is a subclass of `parrot.bots.flows.core.node.AgentNode` (or `Node`). |
| `test_agentsflow_returns_flowresult` | M5 | `AgentsFlow.run()` returns an instance of `parrot.bots.flows.core.result.FlowResult`. |
| `test_agentsflow_uses_flowcontext` | M5 | All four execution modes pass a `FlowContext` (not a custom container) to nodes; `shared_data` is observable. |
| `test_no_legacy_imports` | M9 | `grep -rn "parrot\.bots\.flow\b" packages/` returns no Python-source matches outside `parrot/bots/flows/`. |
| `test_init_curated_surface` | M8 | `parrot.bots.flows.__all__` contains exactly the curated symbol list from §3 Module 8 and excludes the demoted internals. |

### Integration Tests

| Test | Description |
|---|---|
| `test_dev_loop_end_to_end` | The `parrot/flows/dev_loop/` PoC drives a Claude Code agent through Bug → Research → Development → QA → Deployment using only `parrot.bots.flows.*` imports. |
| `test_agentsflow_four_modes` | DAG `run_flow`, sequential, parallel-fanout, and loop modes all produce `FlowResult` with `node_metadata` keyed by `node_id`, using `NodeResult` per-node. |
| `test_feat163_contract_still_passes` | `tests/test_flow_primitives/test_contract.py` and `tests/test_flow_primitives/test_init_reexports.py` continue to pass, with their assertions updated to the new path. |
| `test_otel_uniform_events` | (FEAT-177 integration) A run of AgentsFlow and a run of AgentCrew through the same OTel subscriber produce events with identical `NodeExecutionInfo` shapes. |

### Test Data / Fixtures

Reuse existing fixtures from `tests/test_flow_primitives/` and
`tests/bots/flows/`. No new fixtures required — the migration is
contract-preserving.

```python
# Freeze-test pattern for behavioural contract on rewritten nodes
@pytest.fixture
def decision_node_public_surface() -> set[str]:
    """Captured at start of feature work; failures here mean the rewrite
    silently changed the public surface."""
    return {
        "DecisionFlowNode", "DecisionResult", "DecisionMode",
        "DecisionType", "DecisionNodeConfig", "BinaryDecision",
        "ApprovalDecision", "MultiChoiceDecision", "EscalationPolicy",
        "VoteWeight",
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `parrot/bots/flow/` directory does not exist on disk.
- [ ] `grep -rn "parrot\.bots\.flow\b" packages/ docs/` returns no
  matches outside the `parrot/bots/flows/` subtree.
- [ ] `parrot/bots/flows/flow/` is a subpackage containing
  `__init__.py`, `flow.py`, `nodes.py`, `definition.py`, `loader.py`,
  `svelteflow.py`, `actions.py`, `cel_evaluator.py`.
- [ ] `parrot/bots/flows/flow/nodes.py` is the single home for
  `DecisionFlowNode`, `BinaryDecision`, `ApprovalDecision`,
  `MultiChoiceDecision`, `EscalationPolicy`, `VoteWeight`,
  `DecisionResult`, `DecisionMode`, `DecisionType`,
  `DecisionNodeConfig`, and `InteractiveDecisionNode`.
- [ ] Every Decision* / Interactive* node class subclasses
  `parrot.bots.flows.core.node.AgentNode` or
  `parrot.bots.flows.core.node.Node` (verified by `isinstance` / `mro()`
  in unit tests).
- [ ] `AgentsFlow.run()` returns an instance of `FlowResult`.
- [ ] All four AgentsFlow execution modes use `FlowContext` (with
  `shared_data`) for shared run state.
- [ ] All four modes record per-node output as `NodeResult` instances.
- [ ] AgentsFlow telemetry is built via `build_node_metadata` /
  `NodeExecutionInfo` — verified by a uniform-event integration test
  with the FEAT-177 OTel subscriber.
- [ ] `parrot/bots/flows/core/storage/*` is the only storage layer
  reachable in-tree; no `parrot.bots.flow.storage.*` import remains.
- [ ] `parrot/bots/flows/__init__.py` `__all__` matches the curated
  list in §3 Module 8 (deliberate primitives only;
  `CELPredicateEvaluator`, `ACTION_REGISTRY`, action classes,
  `FlowLoader`, SvelteFlow adapters, and `*ActionDef` schemas are
  **not** at the root).
- [ ] `parrot/flows/dev_loop/` runs end-to-end against the new imports
  (manual or automated PoC test).
- [ ] All 31 previously-affected test files pass; tests broken at HEAD
  are rewritten (not quarantined) and pass.
- [ ] `pytest` for `packages/ai-parrot/tests/` is green; no skips
  introduced by this feature.
- [ ] `ruff check .` and `mypy` (project configuration) pass on the
  migrated tree.
- [ ] `python -c "import parrot.bots.flows; print(parrot.bots.flows.__all__)"`
  exits 0 (no circular imports, curated `__all__` printed).
- [ ] `sdd/specs/agentsflow-persistency.spec.md` is marked obsolete
  with a pointer to FEAT-147 + FEAT-196.
- [ ] No new external dependencies introduced.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every reference below was
> re-verified on 2026-05-28 against `HEAD` of `dev`. Implementation
> agents MUST NOT reference imports, attributes, or methods not listed
> here without first verifying via `grep` or `read`.

### Verified Imports

```python
# Canonical primitives (already exist — adopt verbatim):
from parrot.bots.flows.core.node import Node, AgentNode, StartNode, EndNode
# verified: parrot/bots/flows/core/node.py:68, 182, 323, 387

from parrot.bots.flows.core.result import (
    NodeResult, NodeExecutionInfo, FlowResult,
    determine_run_status, build_node_metadata,
)
# verified: parrot/bots/flows/core/result.py:39, 190, 273, 162, 527

from parrot.bots.flows.core.context import FlowContext, AgentNotFoundError
# verified: parrot/bots/flows/core/context.py:51, 41

from parrot.bots.flows.core.fsm import AgentTaskMachine, TransitionCondition
from parrot.bots.flows.core.transition import FlowTransition
from parrot.bots.flows.core.storage import (
    ExecutionMemory, VectorStoreMixin, PersistenceMixin, SynthesisMixin,
)
# verified: parrot/bots/flows/core/storage/__init__.py re-exports these

# Cross-package legacy imports that MUST be removed in L4:
# parrot/bots/flows/flow.py:42
from parrot.bots.flow.definition import FlowDefinition

# parrot/bots/flows/flow.py:45  (multi-symbol import block lines 45–50)
from parrot.bots.flow.decision_node import (
    DecisionFlowNode, DecisionResult, DecisionMode, ...
)

# parrot/bots/flows/flow.py:51  (multi-symbol import block lines 51–53)
from parrot.bots.flows.flow.interactive_node import (
    InteractiveDecisionNode,
)

# parrot/bots/flows/flow.py:508  (lazy import inside a method)
from parrot.bots.flow.cel_evaluator import CELPredicateEvaluator

# parrot/bots/flow/__init__.py — lazy AgentsFlow getattr (will be deleted
# in L6 along with the entire package):
def __getattr__(name):
    if name == "AgentsFlow":
        from parrot.bots.flows.flow import AgentsFlow
        return AgentsFlow
    ...
```

### Existing Class Signatures

```python
# parrot/bots/flows/core/node.py
class Node(BaseModel):                              # line 68
    """frozen=True, arbitrary_types_allowed=True"""
    node_id: str                                    # line 100
    # _pre_actions / _post_actions: PrivateAttr lists (mutable, frozen-safe)
    # subclasses must implement the `name` property and call _init_node()

class AgentNode(Node):                              # line 182
    node_id: str                                    # line 218
    def _build_prompt(                              # line 238
        self, ctx: "FlowContext", deps: DependencyResults,
    ) -> str: ...
    async def execute(                              # line 270
        self, ctx: "FlowContext", deps: DependencyResults, **kwargs: Any,
    ) -> Any: ...

class StartNode(Node):                              # line 323
    node_id: str = Field(default="__start__")       # line 341

class EndNode(Node):                                # line 387
    node_id: str = Field(default="__end__")         # line 402

# parrot/bots/flows/core/result.py
@dataclass
class NodeResult:                                   # line 39
    node_id: str
    node_name: str
    task: str
    result: Any
    ai_message: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    parent_execution_id: Optional[str] = None
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # @property agent_id -> str (alias for node_id)
    # @property agent_name -> str (alias for node_name)

@dataclass
class NodeExecutionInfo: ...                        # line 190

@dataclass
class FlowResult: ...                               # line 273

def determine_run_status(...) -> FlowStatus: ...    # line 162
def build_node_metadata(...) -> dict: ...           # line 527

# parrot/bots/flows/core/context.py
class AgentNotFoundError(LookupError): ...          # line 41

@dataclass
class FlowContext:                                  # line 51
    node_metadata: Dict[str, NodeExecutionInfo] = field(default_factory=dict)
    # line 74
    shared_data: Dict[str, Any] = field(default_factory=dict)
    # line 89   (FEAT-143 addition)
    agent_registry: Optional["AgentRegistry"] = field(default=None)
    # line 92   (FEAT-163 addition)

    def resolve_agent(self, agent_ref: AgentRef) -> AgentLike: ...
    # line 109  (raises AgentNotFoundError on miss)
    def can_execute(self, _node_id: str, dependencies: Set[str]) -> bool: ...
    # line 150
    def mark_completed(...) -> None: ...            # line 164
    def mark_failed(...) -> None: ...               # line 193
    def get_input_for_node(...) -> Dict[str, Any]: ...
    # line 216
    # @property agent_metadata -> Dict[str, NodeExecutionInfo]  # line 249
    def get_input_for_agent(...) -> Dict[str, Any]: ...
    # line 253  (backward-compat alias for get_input_for_node)
```

### Singular `parrot/bots/flow/` — what's left to migrate (verified 2026-05-28)

```
parrot/bots/flow/actions.py            552 LoC   ACTION_REGISTRY, BaseAction, LogAction, NotifyAction, WebhookAction, MetricAction, SetContextAction, ValidateAction, TransformAction, register_action, create_action
parrot/bots/flow/cel_evaluator.py      140 LoC   CELPredicateEvaluator
parrot/bots/flow/decision_node.py     1140 LoC   DecisionFlowNode, DecisionMode, DecisionType, DecisionNodeConfig, DecisionResult, BinaryDecision, ApprovalDecision, MultiChoiceDecision, EscalationPolicy, VoteWeight
parrot/bots/flow/definition.py         433 LoC   FlowDefinition, FlowMetadata, NodeDefinition, NodePosition, EdgeDefinition, ActionDefinition, LogActionDef, NotifyActionDef, WebhookActionDef, MetricActionDef, SetContextActionDef, ValidateActionDef, TransformActionDef
parrot/bots/flow/interactive_node.py    99 LoC   InteractiveDecisionNode
parrot/bots/flow/loader.py             364 LoC   FlowLoader, REDIS_KEY_PREFIX
parrot/bots/flow/node.py               106 LoC   Node  (old base — superseded by flows/core/node.Node; DELETE)
parrot/bots/flow/nodes/start.py          —       StartNode  (old — superseded by flows/core/node.StartNode; DELETE)
parrot/bots/flow/nodes/end.py            —       EndNode  (old — superseded by flows/core/node.EndNode; DELETE)
parrot/bots/flow/storage/memory.py     102 LoC   ExecutionMemory  (old — superseded by flows/core/storage/memory.ExecutionMemory)
parrot/bots/flow/storage/mixin.py      141 LoC   VectorStoreMixin  (old — diff vs flows/core/storage/mixin)
parrot/bots/flow/storage/synthesis.py  108 LoC   SynthesisMixin  (old — diff vs flows/core/storage/synthesis)
parrot/bots/flow/svelteflow.py         192 LoC   from_svelteflow, to_svelteflow
parrot/bots/flow/tools.py               79 LoC   ResultRetrievalTool  (old DUPLICATE — flows/tools.py canonical; DELETE)
parrot/bots/flow/__init__.py            67 LoC   Hybrid re-exporter; lazy AgentsFlow via __getattr__
```

Total: ~3,456 LoC across 17 files.

### Integration Points (verified)

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `flows/flow/flow.py:AgentsFlow` | `flows/core/node.AgentNode` | inherits / composes | `parrot/bots/flows/core/node.py:182` |
| `flows/flow/nodes.py:DecisionFlowNode` | `flows/core/node.AgentNode` | inherits | `parrot/bots/flows/core/node.py:182` |
| `flows/flow/flow.py:AgentsFlow.run()` | `flows/core/result.FlowResult` | returns | `parrot/bots/flows/core/result.py:273` |
| `flows/flow/flow.py:AgentsFlow` scheduler | `flows/core/context.FlowContext` | constructs / passes | `parrot/bots/flows/core/context.py:51` |
| `flows/flow/flow.py` telemetry | `flows/core/result.build_node_metadata` | calls | `parrot/bots/flows/core/result.py:527` |
| `flows/flow/nodes.py:DecisionFlowNode` state | `FlowContext.shared_data` | reads/writes | `parrot/bots/flows/core/context.py:89` |
| `flows/flow/cel_evaluator.py:CELPredicateEvaluator` | `flows/core/transition.FlowTransition` | called by predicates | `parrot/bots/flows/core/transition.py:28` |
| FEAT-177 OTel subscriber | `flows/core/result.NodeExecutionInfo` | reads | `parrot/observability/*` (FEAT-177) |

### `parrot/bots/flows/flow.py` cross-package imports — exact removal map

| Line in `flows/flow.py` (HEAD) | Old import | Replacement after L4 |
|---|---|---|
| 42 | `from parrot.bots.flow.definition import FlowDefinition` | `from .definition import FlowDefinition` |
| 45–50 | `from parrot.bots.flow.decision_node import (DecisionFlowNode, DecisionResult, DecisionMode, ...)` | `from .nodes import (DecisionFlowNode, DecisionResult, DecisionMode, ...)` |
| 51–53 | `from parrot.bots.flow.interactive_node import (InteractiveDecisionNode,)` | `from .nodes import (InteractiveDecisionNode,)` |
| 508 (lazy) | `from parrot.bots.flow.cel_evaluator import CELPredicateEvaluator` | `from .cel_evaluator import CELPredicateEvaluator` |

The class-body landmarks (`class AgentsFlow(PersistenceMixin):` at line 133;
`@register_node("decision")` at 676, `@register_node("interactive_decision")`
at 752, `@register_node("synthesis")` at 820) are preserved by the L1 move.

### `parrot/flows/dev_loop/` consumers — exact list (8 files)

```
parrot/flows/dev_loop/flow.py                     :26   from parrot.bots.flow import AgentsFlow
parrot/flows/dev_loop/nodes/bug_intake.py         :21   from parrot.bots.flow.node import Node
parrot/flows/dev_loop/nodes/deployment_handoff.py :29   from parrot.bots.flow.node import Node
parrot/flows/dev_loop/nodes/development.py        :19   from parrot.bots.flow.node import Node
parrot/flows/dev_loop/nodes/failure_handler.py    :22   from parrot.bots.flow.node import Node
parrot/flows/dev_loop/nodes/intent_classifier.py  :22   from parrot.bots.flow.node import Node
parrot/flows/dev_loop/nodes/qa.py                 :20   from parrot.bots.flow.node import Node
parrot/flows/dev_loop/nodes/research.py           :30   from parrot.bots.flow.node import Node
```

### Tests touching `parrot.bots.flow.*` — exact list (31 files)

```
packages/ai-parrot/tests/test_agent_crew_examples.py
packages/ai-parrot/tests/test_agentsflow_branch.py
packages/ai-parrot/tests/test_cel_evaluator.py
packages/ai-parrot/tests/test_decision_node.py
packages/ai-parrot/tests/test_endnode.py
packages/ai-parrot/tests/test_execution_memory_integration.py
packages/ai-parrot/tests/test_flow_actions.py
packages/ai-parrot/tests/test_flow_definition.py
packages/ai-parrot/tests/test_flow_integration.py
packages/ai-parrot/tests/test_flow_loader.py
packages/ai-parrot/tests/test_flow_mixins.py
packages/ai-parrot/tests/test_fsm.py                          # BROKEN AT HEAD (imports parrot.bots.flow.fsm — deleted)
packages/ai-parrot/tests/test_orchestrator_agent.py
packages/ai-parrot/tests/test_svelteflow_adapter.py
packages/ai-parrot/tests/bots/flow/test_definition_cycle.py
packages/ai-parrot/tests/bots/flows/test_agents_flow.py
packages/ai-parrot/tests/bots/flows/test_flow_node_subclasses.py
packages/ai-parrot/tests/bots/flows/test_from_definition.py
packages/ai-parrot/tests/flows/dev_loop/test_flow.py          # BROKEN AT HEAD (imports parrot.bots.flow.fsm)
packages/ai-parrot/tests/test_flow_primitives/test_contract.py
packages/ai-parrot/tests/test_flow_primitives/test_init_reexports.py
```

(Plus ~10 additional files identified by `grep -rn "parrot\.bots\.flow\b"`
across the test tree — discover the full set during `/sdd-task`.)

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.bots.flow.fsm`~~ — deleted in FEAT-163 TASK-1069. Tests that
  still import it are broken at HEAD and must be rewritten in L5.
- ~~`parrot.bots.flow.FlowNode`~~ — explicitly noted as "not re-exported
  — removed in FEAT-163" in `parrot/bots/flow/__init__.py`. Use
  `parrot.bots.flows.core.node.AgentNode`.
- ~~`parrot.bots.flow.storage.persistence`~~ — already deleted by
  FEAT-147. Canonical: `parrot.bots.flows.core.storage.persistence`.
- ~~`parrot.bots.flows.dsl`~~, ~~`parrot.bots.flows.actions`~~ (as
  package), ~~`parrot.bots.flows.predicates`~~ — rejected layouts.
  Files land flat under `parrot/bots/flows/flow/`.
- ~~Back-compat shim at `parrot/bots/flow/`~~ — rejected; the package
  is deleted outright.
- ~~`parrot.bots.flow.tools.ResultRetrievalTool`~~ surviving the
  migration — the file is the old duplicate of the canonical
  `parrot/bots/flows/tools.py` and is deleted in L6.
- ~~Per-decision-type module split~~ (`flows/nodes/decision/{base,
  binary, approval, multichoice}.py`) — rejected; all decision +
  interactive node types live in a single `flows/flow/nodes.py`.
- ~~`CELPredicateEvaluator` in `parrot.bots.flows.__all__`~~ — stays
  internal; importable only from `parrot.bots.flows.flow.cel_evaluator`.
- ~~A retroactive task index for FEAT-009~~ — FEAT-009 is superseded by
  FEAT-147, not delivered by this feature. Its spec is marked obsolete
  in M10; no implementation work flows from it.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Subpackage mirroring**: the new `parrot/bots/flows/flow/` layout
  must mirror the existing `parrot/bots/flows/crew/` layout
  (`__init__.py` + main class file + `nodes.py`). Symmetry is itself
  a design constraint — when in doubt, do what `crew/` does.
- **Relative imports inside `flows/flow/`**: prefer `from .nodes import
  DecisionFlowNode` over `from parrot.bots.flows.flow.nodes import
  DecisionFlowNode`. The absolute form is allowed only in test files
  and external consumers.
- **Frozen Pydantic node base**: `Node` and `AgentNode` are frozen
  (`model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)`).
  Rewritten Decision* nodes must respect this — store mutable per-run
  state in `FlowContext.shared_data` or via `PrivateAttr` lists, never
  as ordinary mutable fields.
- **Async-first**: every method on the rewritten Decision* nodes that
  has I/O must be `async def`. Use `self.logger` for logging.
- **No `requests`/`httpx` in async paths** — use `aiohttp` (project rule).
- **Behavioural contract preservation for Decision* nodes**: the freeze
  test in §4 captures the public attribute / method set; the rewrite
  must reproduce it exactly. Internal implementation can change freely.
- **Storage diff before delete**: in L2, do not delete
  `parrot/bots/flow/storage/*` until the behavioural-parity test
  (`test_storage_behavioural_parity` in §4) is green on the canonical
  storage layer.
- **One PR, layered commits**: each Module from §3 should land as its
  own commit (or small commit cluster) on the feature branch. The PR
  description must list the layer order and the per-layer test gate.
- **Curated `__all__`**: Module 8's `__all__` list is the authoritative
  public API for `parrot.bots.flows`. The acceptance criterion in §5
  checks the list verbatim; do not add or remove without a follow-up
  PR.

### Known Risks / Gotchas

- **Out-of-tree consumers (Navigator)**: this feature breaks any
  external import of `parrot.bots.flow.*`. Before `/sdd-task`, grep the
  Navigator project for `parrot.bots.flow.*`. If found, coordinate a
  Navigator-side PR that merges in lockstep with this feature.
  *Mitigation*: pre-`/sdd-task` action item logged in §8.
- **Decision-node behavioural drift**: the 1,140-LoC rewrite of
  `decision_node.py` is the highest-risk module. *Mitigation*: the
  freeze-test captures the current public surface; CI fails the
  feature if any attribute / method disappears.
- **Storage backend semantics drift**: if old `ExecutionMemory` has a
  quirk the new one lacks, deleting before porting silently breaks
  consumers. *Mitigation*: L2 mandates the behavioural-parity test
  passes before L3 starts.
- **Circular import resilience**: today
  `parrot/bots/flow/__init__.py` uses `__getattr__` to lazily import
  `AgentsFlow` and break a circular dependency. After the migration,
  `parrot/bots/flows/__init__.py` may need its own laziness if any
  newly-located module reaches back into `flows/`. *Mitigation*:
  Module 8's smoke test runs `python -c "import parrot.bots.flows"`;
  any cycle surfaces immediately.
- **Tests broken at HEAD**: `tests/test_fsm.py` and
  `tests/flows/dev_loop/test_flow.py` import the deleted
  `parrot.bots.flow.fsm`. They will not run today. *Mitigation*: L5
  rewrites them; do not blanket-skip.
- **Large final-PR diff**: ~3.5k LoC moved/rewritten + ~40 consumer
  files repointed. *Mitigation*: layered commits + per-layer test
  checkpoint make review tractable.
- **`__init__.py` curation regressions**: silently demoting a symbol
  (e.g., `FlowLoader`) from `__all__` breaks anyone who was importing
  from the package root. *Mitigation*: the §5 acceptance criterion
  pins `__all__` to the explicit list; PR description must call out
  every demoted symbol with its new submodule path.

### External Dependencies

This feature **introduces no new external dependencies**. The
canonical `flows/core/*` already uses everything required (`pydantic`,
`navconfig`, `transitions`, etc.).

| Package | Version | Reason |
|---|---|---|
| (none) | — | Pure refactor — no new deps. |

---

## 8. Open Questions

> The brainstorm resolved all 14 questions; carrying them forward as
> resolved here for audit. No questions remain unresolved at spec time.

- [x] **Flow type / base branch** — *Resolved in brainstorm Round 0*:
  `type: feature`, `base_branch: dev`. Reflected in the frontmatter
  above.
- [x] **End-state for `parrot/bots/flow/`** — *Resolved in brainstorm
  Round 1*: delete entirely; no back-compat shim. Reflected in §1
  Goals + §5 Acceptance Criteria + §3 Module 9.
- [x] **Files needing real homologation (not just moves)** — *Resolved
  in brainstorm Round 1*: `decision_node` + `interactive_node`
  rewritten on `AgentNode`; `storage/` folded into `flows/core/storage/`;
  `definition` + `loader` + `svelteflow` + `actions` + `cel_evaluator`
  move only. Reflected in §3 Modules 2, 3, 4.
- [x] **Repointing aggression** — *Resolved in brainstorm Round 1*:
  atomic, everything in one PR. Reflected in §2 Overview + Worktree
  Strategy below.
- [x] **Storage reconciliation when behaviour diverges** — *Resolved in
  brainstorm Round 2*: new `flows/core/storage/` wins; salvage any
  missing semantics from old code before deletion. Reflected in §3
  Module 3 + §5 Acceptance Criteria.
- [x] **Node hierarchy** — *Resolved in brainstorm Round 2*:
  `flows/core/node.Node` (lightweight base) + `AgentNode` subclasses it
  — already implemented in FEAT-163. Decision* / Interactive* nodes
  subclass `Node` or `AgentNode`, not a parallel base. Reflected in §3
  Module 4 + §6 verified signatures.
- [x] **AgentCrew / FEAT-143 model adoption** — *Resolved in brainstorm
  Round 2*: `FlowResult`, `NodeResult`, `FlowContext.shared_data`,
  `build_node_metadata` + `NodeExecutionInfo` all adopted by
  AgentsFlow's run path. Reflected in §1 Goals + §3 Module 5 + §5
  Acceptance Criteria.
- [x] **Public re-export surface of `bots/flows/__init__.py`** —
  *Resolved in brainstorm Round 2*: curate; only deliberate primitives
  at the package root. Reflected in §3 Module 8 + §5 Acceptance
  Criteria.
- [x] **Submodule layout for moved files** — *Resolved in brainstorm
  Round 3*: mirror `parrot/bots/flows/crew/`. Convert `flows/flow.py`
  into a `flows/flow/` subpackage. Files land flat under
  `flows/flow/`. No `flows/dsl/`, no `flows/actions/`. Reflected in
  §2 Overview + §3 Modules 1, 2.
- [x] **Decision-node module organisation** — *Resolved in brainstorm
  Round 3*: single `flows/flow/nodes.py` for all decision +
  interactive node types. No per-type file split. Reflected in §3
  Module 4 + §5 Acceptance Criteria.
- [x] **`CELPredicateEvaluator`: public or private?** — *Resolved in
  brainstorm Round 3*: internal for now. Lives at
  `parrot/bots/flows/flow/cel_evaluator.py`; not in
  `parrot.bots.flows.__all__`. Reflected in §3 Module 8 + §5 Acceptance
  Criteria + §6 Does NOT Exist.
- [x] **FEAT-009 coordination** — *Resolved in brainstorm Round 3*:
  superseded by FEAT-147. Mark obsolete in `sdd/specs/agentsflow-
  persistency.spec.md`. Reflected in `Supersedes:` line at the top
  of this spec + §3 Module 10.
- [x] **Navigator-side coordination** — *Resolved in brainstorm Round
  3*: pre-`/sdd-task` grep check. If Navigator imports
  `parrot.bots.flow.*`, coordinate a lockstep Navigator-side PR.
  Otherwise proceed independently. Reflected in §7 Known Risks.
- [x] **Test-suite repair surface** — *Resolved in brainstorm Round
  3*: refactor existing tests in the same PR; no quarantine. Reflected
  in §3 Module 7 + §5 Acceptance Criteria.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`.
- **Rationale**: the brainstorm Parallelism Assessment establishes no
  internal parallelism is possible — Layers 1–6 have a strict
  topological dependency. Storage reconciliation (M3) must finish
  before consumers repoint storage imports; node rewrites (M4) must
  finish before the AgentsFlow class drops its decision-node imports
  (M5); M5 must finish before the singular `__init__.py` can be
  deleted (M9). Every module touches shared files (`flows/flow/flow.py`,
  `flows/__init__.py`, or the test suite). Splitting into per-task
  worktrees would force constant rebases for zero parallelism gain.
- **Cross-feature dependencies (must be merged first)**: FEAT-134,
  FEAT-143, FEAT-147, FEAT-163 — all already merged on `dev`. No
  blocker.
- **Cross-feature coordination (informational, not blocking)**:
  - **FEAT-009** (`agentsflow-persistency`) — superseded; this feature
    marks it obsolete in M10. No work flows from it.
  - **FEAT-157** (`agentcrew-hooks`) — already shipped; no conflict.
  - **FEAT-177** (`otel-observability`) — already shipped; benefits
    from this migration via uniform `NodeExecutionInfo`.
  - **Navigator project** (out-of-tree) — pre-`/sdd-task` grep check
    (§7 Known Risks).

### Worktree creation

```bash
git checkout dev
git pull --ff-only origin dev
git worktree add -b feat-196-agentsflow-migration \
  .claude/worktrees/feat-196-agentsflow-migration HEAD
cd .claude/worktrees/feat-196-agentsflow-migration
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-28 | Jesus Lara | Initial draft scaffolded from `sdd/proposals/agentsflow-migration.brainstorm.md` (Option A; 14 resolved questions carried forward). |
