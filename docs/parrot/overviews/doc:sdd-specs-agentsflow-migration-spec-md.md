---
type: Wiki Overview
title: 'Feature Specification: AgentsFlow Migration — finish moving `bots/flow/` into
  `bots/flows/`'
id: doc:sdd-specs-agentsflow-migration-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-163 moved AgentsFlow's **FSM engine** out of `parrot/bots/flow/fsm.py`
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.fsm
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.persistence
  rel: mentions
- concept: mod:parrot.bots.flows.core.transition
  rel: mentions
- concept: mod:parrot.bots.flows.flow
  rel: mentions
- concept: mod:parrot.bots.flows.flow.cel_evaluator
  rel: mentions
- concept: mod:parrot.bots.flows.flow.nodes
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: AgentsFlow Migration — finish moving `bots/flow/` into `bots/flows/`

**Feature ID**: FEAT-196
**Date**: 2026-05-28
**Author**: Jesus Lara
**Status**: implemented
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

…(truncated)…
