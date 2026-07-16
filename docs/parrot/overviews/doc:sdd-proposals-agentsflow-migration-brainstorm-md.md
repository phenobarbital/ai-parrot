---
type: Wiki Overview
title: 'Brainstorm: AgentsFlow Migration — finish moving `bots/flow/` into `bots/flows/`'
id: doc:sdd-proposals-agentsflow-migration-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-163 (`agentsflow-refactor-spec3`, merged on `dev` 2026-05-11) moved
  the
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.flow
  rel: mentions
- concept: mod:parrot.bots.flows.flow.cel_evaluator
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: AgentsFlow Migration — finish moving `bots/flow/` into `bots/flows/`

**Date**: 2026-05-28
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

FEAT-163 (`agentsflow-refactor-spec3`, merged on `dev` 2026-05-11) moved the
**FSM engine** of AgentsFlow out of `parrot/bots/flow/fsm.py` and into
`parrot/bots/flows/core/` + `parrot/bots/flows/flow.py`. The legacy
`fsm.py` was deleted (TASK-1069). FEAT-143 (`flows-consolidation`) had
previously moved `AgentCrew` to `parrot/bots/flows/crew/` and introduced the
canonical result/context models (`FlowResult`, `NodeResult`,
`FlowContext.shared_data`, `build_node_metadata`, `NodeExecutionInfo`).

**The migration is half-done.** The legacy `parrot/bots/flow/` (singular)
still hosts 17 files (~3,456 LoC) that the new world depends on:

- `parrot/bots/flows/flow.py` itself imports `FlowDefinition`,
  `DecisionFlowNode`/`DecisionResult`/`DecisionMode`/...,
  `InteractiveDecisionNode`, and (lazily) `CELPredicateEvaluator` from
  `parrot.bots.flow.*` — see verified line numbers in §Code Context.
- `parrot/flows/dev_loop/*` (8 production files, the dev-loop flow PoC)
  imports `AgentsFlow` and `Node` from `parrot.bots.flow.*`.
- 31 test files reference `parrot.bots.flow.*` directly.
- `parrot/bots/flow/__init__.py` is a hybrid re-exporter (some symbols
  forwarded to `flows/core/*`, others still living in `flow/*`).

The remaining files split into three behavioural groups:

1. **Already-canonicalised siblings** — `flow/storage/{memory,mixin,synthesis}.py`
   and `flow/tools.py` have richer/newer counterparts in
   `flows/core/storage/*` and `flows/tools.py`. The old copies are
   redundant duplicates kept alive only by stale imports.
2. **Move-only files** — `actions.py`, `cel_evaluator.py`, `definition.py`,
   `loader.py`, `svelteflow.py`. Self-contained primitives with no
   counterpart in `flows/`. They just need to relocate.
3. **Re-architecture targets** — `decision_node.py` (1,140 LoC) and
   `interactive_node.py` (99 LoC). These predate `flows/core/node.AgentNode`
   (the FEAT-137 / FEAT-163 rich node with `execute()`, hooks, timeout,
   FSM). They should be rewritten as subclasses of `AgentNode` (or `Node`)
   rather than straight-moved, so the public `DecisionNode` surface is
   homologated with the rest of the node hierarchy.

Without this migration:
- `parrot/bots/flows/` cannot be deleted-and-recreated independently of
  `parrot/bots/flow/` — they are bidirectionally coupled.
- The dev-loop PoC and 31 test files document the "wrong" import path
  as canonical, perpetuating the duplication.
- New contributors cannot tell which package is current.

---

## Constraints & Requirements

- **End-state**: `parrot/bots/flow/` is deleted in its entirety. No
  back-compat shim. (Round-1 answer.)
- **Atomic delivery**: one feature branch, one PR. Library code, dev-loop
  consumers, and test files are repointed in the same PR. (Round-1 answer.)
- **No behaviour regression** in the four AgentsFlow execution modes
  (parallel DAG `run_flow`, sequential, parallel-fanout, loop).
- **Storage reconciliation**: when behaviours diverge between
  `flow/storage/*` and `flows/core/storage/*`, the new world wins; salvage
  any missing semantics from the old code into the canonical implementation
  before deletion. (Round-2 answer.)
- **Node hierarchy**: keep the existing `flows/core/node.Node` (lightweight
  base) + `AgentNode` (subclass). `DecisionNode` and `InteractiveDecisionNode`
  must subclass `Node` or `AgentNode` — no parallel base class. (Round-2
  answer.)
- **AgentCrew model adoption**: AgentsFlow must use `FlowResult` as its
  `run()` return type, `NodeResult` for per-node output, `FlowContext`
  (with `shared_data`) as the shared run state, and
  `build_node_metadata` / `NodeExecutionInfo` for telemetry. (Round-2
  answer; aligns AgentsFlow with AgentCrew so FEAT-177 OTel subscribers
  see identical events from both engines.)
- **Curated public API**: `parrot/bots/flows/__init__.py` re-exports only
  deliberate primitives. Internals (e.g., `CELPredicateEvaluator` if used
  only by transitions, action-registry internals) stay in their submodules.
  (Round-2 answer.)
- **No new external dependencies.** This is pure refactor.
- All existing tests must still pass after import repointing — including
  the FEAT-163 contract tests
  (`tests/test_flow_primitives/test_init_reexports.py`,
  `tests/test_flow_primitives/test_contract.py`).

---

## Options Explored

### Option A: Layered atomic migration (recommended)

Single feature branch with a layered task graph that respects the import
dependency order. Each layer commits independently; nothing is half-done
between layers.

**Layer 1 — Move-only relocations (no behaviour change):**
Convert `parrot/bots/flows/flow.py` (single file) into the
`parrot/bots/flows/flow/` **subpackage** — mirroring the existing
`parrot/bots/flows/crew/` layout. The AgentsFlow class moves to
`flows/flow/flow.py`; supporting modules land alongside as siblings.
Move `actions.py`, `cel_evaluator.py`, `definition.py`, `loader.py`,
`svelteflow.py` into `parrot/bots/flows/flow/` (flat at first; split
later only if a file grows). `cel_evaluator.py` lives here as an internal
module — it is **not** re-exported at `parrot/bots/flows/__init__.py`
(Round-3 answer: only used by transitions today).

**Layer 2 — Storage reconciliation:**
Diff `flow/storage/{memory,mixin,synthesis}.py` against
`flows/core/storage/*`. Port any unique semantics from the old code into
the canonical files. Delete `flow/storage/`. Repoint stragglers
(`tools.py` already uses `flows.core.storage`, but
`test_orchestrator_agent.py`, `test_execution_memory_integration.py`, etc.
still import from the old path).

**Layer 3 — Node rewrites (behaviour-preserving):**
Reimplement `DecisionFlowNode`, `DecisionResult`, `DecisionMode`,
`DecisionType`, `BinaryDecision`, `ApprovalDecision`, `MultiChoiceDecision`,
`EscalationPolicy`, `VoteWeight`, and `InteractiveDecisionNode` as
subclasses of `flows/core/node.AgentNode` (or `Node` for non-agent
decisions). All decision/interactive node types land in a single
`flows/flow/nodes.py` module (Round-3 answer: keep node types together,
no per-decision-type file split). This mirrors `flows/crew/nodes.py`
which holds `CrewAgentNode`. Public symbol names preserved; internals
adopt `NodeResult`, `FlowContext.shared_data`, and `build_node_metadata`.
Old `decision_node.py` and `interactive_node.py` deleted.

**Layer 4 — Internal repointing:**
Update `parrot/bots/flows/flow/flow.py` (post-L1 location of the
AgentsFlow class) to import from `parrot.bots.flows.*` only. The four
cross-package imports at the current `flows/flow.py` lines 42, 45, 51,
and 508 collapse into intra-subpackage imports (e.g.,
`from .nodes import DecisionFlowNode, ...`,
`from .definition import FlowDefinition`,
`from .cel_evaluator import CELPredicateEvaluator`).

**Layer 5 — External consumer repointing + test refactor:**
Update `parrot/flows/dev_loop/{flow,nodes/*}.py` (8 files) to import from
`parrot.bots.flows.*`. **Refactor** (not just repoint) the 31 test files
that depend on `parrot.bots.flow.*` — several already break at HEAD
because they import `parrot.bots.flow.fsm` (deleted by FEAT-163). Those
tests get rewritten against the new node + result models in the same
PR (Round-3 answer: refactor, not quarantine).

**Layer 6 — Cleanup + curated public API:**
Delete `parrot/bots/flow/` entirely. Rewrite
`parrot/bots/flows/__init__.py` to expose only the deliberate primitives
(curated, not verbatim). `CELPredicateEvaluator`, action-registry
internals, and other transition/runtime plumbing remain accessible only
via their submodules (e.g., `from parrot.bots.flows.flow.cel_evaluator
import CELPredicateEvaluator`). Update any docstrings/examples that
reference the old path.

✅ **Pros:**
- Clean dependency order — each layer leaves the tree in a consistent state.
- Single PR, single review, single CI green check.
- Task graph maps 1:1 onto `/sdd-task` decomposition (6 layers → 8–10 tasks).
- Behaviour preservation is checkable per-layer (storage tests after L2,
  decision-node tests after L3, full suite after L5).

❌ **Cons:**
- Final PR diff is large (~3.5k LoC moved/rewritten + ~40 consumer files
  repointed). Review burden front-loaded.
- Layer-3 rewrite of `decision_node.py` (1,140 LoC) is non-trivial — needs
  careful behavioural diff against current `DecisionFlowNode`.

📊 **Effort:** High (~6–8 tasks; ~2-week estimate).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` ≥2 | Existing Node/AgentNode are `BaseModel(frozen=True)` | Already in use throughout `flows/core/` |
| `transitions` | FSM (already used by `AgentTaskMachine`) | No change |
| `ruff` / `mypy` | Lint + type-check during repointing | Already wired in CI |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/core/node.py` — Node + AgentNode + StartNode +
  EndNode hierarchy (canonical).
- `parrot/bots/flows/core/result.py` — FlowResult, NodeResult,
  NodeExecutionInfo, build_node_metadata.
- `parrot/bots/flows/core/context.py` — FlowContext with shared_data +
  AgentRegistry resolution.
- `parrot/bots/flows/core/storage/` — backends, memory, mixin, persistence,
  synthesis (canonical storage layer).
- `parrot/bots/flows/tools.py` — ResultRetrievalTool already migrated
  (canonical; old `flow/tools.py` is the duplicate to delete).

---

### Option B: Vertical slices (one slice per leftover file)

Decompose by file rather than by layer. Each slice is a task that
(a) moves/rewrites one file, (b) updates every consumer that imports it,
(c) deletes the old file. Each slice ends with the tree in a working state
and a passing test suite.

Slice list: `actions.py`, `cel_evaluator.py`, `definition.py`, `loader.py`,
`svelteflow.py`, `storage/*`, `decision_node.py`, `interactive_node.py`,
`node.py`, `tools.py`, `nodes/{start,end}.py`. Final slice deletes
`__init__.py` + the now-empty package directory.

✅ **Pros:**
- Each task is small and independently bisectable.
- A failing CI on one slice does not block the others.
- Easier to mentally model "this PR's diff is just decision_node".

❌ **Cons:**
- Decision-node rewrite spans many consumers (`flows/flow.py` line 45 +
  several tests) — vertical slicing doesn't reduce its surface area.
- More commits, more review cycles, more merge conflicts if multiple
  slices touch `__init__.py` or `flows/flow.py`.
- Total work is identical to Option A; only the bookkeeping differs.
- Violates the user's "atomic, one PR" constraint unless we still
  bundle all slices into one feature branch — at which point the only
  difference vs Option A is the task-graph shape.

📊 **Effort:** High (~10–12 tasks).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (same as Option A) | | |

🔗 **Existing Code to Reuse:**
- (same as Option A)

---

### Option C: Codemod-driven mass rewrite

Write a Python codemod (using `libcst` or `bowler`) that auto-rewrites
every `from parrot.bots.flow.X import Y` → `from parrot.bots.flows.X' import Y`
across the entire repo. Run the codemod, then manually handle the
behavioural work that can't be automated:
- File moves (still manual, but trivial).
- `decision_node.py` / `interactive_node.py` rewrites on `AgentNode`
  (manual — codemod can't redesign class hierarchies).
- Storage reconciliation (manual).
- `__init__.py` curation (manual).

✅ **Pros:**
- The ~40 consumer-file repointing collapses into a single codemod run.
- Codemod is itself a reviewable artefact and can be re-run if more
  imports leak in during the PR cycle.
- The diff for consumer files is mechanical, low cognitive load.

❌ **Cons:**
- Building the codemod is a task in itself (~½ day to ¾ day for libcst
  setup + correctness tests).
- Codemod cannot handle the hard parts: storage merge, decision-node
  redesign, `__init__.py` curation. Those still take Option-A effort.
- Codemod adds a dev-tool to the repo that needs its own ongoing
  maintenance / removal.
- Risk of subtly wrong rewrites (e.g., `from parrot.bots.flow import
  ACTION_REGISTRY` requires picking which new module owns
  `ACTION_REGISTRY` — not a 1:1 path swap).

📊 **Effort:** High (~6–8 tasks + ½–1 day for codemod).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `libcst` ≥1.4 | Concrete-syntax-tree codemod for Python | Mature; Meta-maintained |
| `bowler` | Alternative codemod framework | Lighter than libcst, fluent API |

🔗 **Existing Code to Reuse:**
- Same as Option A, plus any codemod helpers in `scripts/sdd/` if applicable
  (likely none — codemod would be a new artefact).

---

## Recommendation

**Option A (Layered atomic migration)** is recommended.

**Reasoning:**
- The user's constraints fix Option A as the natural shape: atomic PR,
  full deletion, full repointing. Option B reorganises tasks but does not
  reduce the surface area and breaks the cohesion of layered cleanup.
  Option C invests in tooling that pays back only on the cheapest 30% of
  the work (consumer imports) and leaves the expensive 70% (decision-node
  rewrite, storage merge, `__init__.py` curation) untouched.
- The dependency order is already linear: storage must reconcile before
  consumers can repoint; decision-node rewrites need the curated `Node`
  base in place; `flows/flow.py`'s four legacy imports cannot be dropped
  until L3 finishes. Option A's layering follows that order; Option B
  fights it.
- Layered phases give natural test-suite checkpoints:
  - After L2: `tests/test_execution_memory_integration.py` + storage tests pass.
  - After L3: `tests/test_decision_node.py` + `tests/bots/flows/test_flow_node_subclasses.py` pass.
  - After L5: `tests/flows/dev_loop/*` + the full FEAT-163 contract tests
    (`test_init_reexports.py`, `test_contract.py`) pass.
- A codemod (Option C) would still leave the L3 rewrite as the dominant
  cost. The leverage is not large enough to justify the tooling.

What we're trading off:
- A large final-PR diff (Option A) vs. many small PRs (Option B). The
  user explicitly chose atomic delivery.
- Manual import edits (Option A) vs. codemod-automated edits (Option C).
  We accept the manual edits because `ruff --fix` and IDE-driven
  "Update Imports" on file moves handle most of it for free.

---

## Feature Description

### User-Facing Behavior

For end-users of `parrot.bots.flows.*`:
- All previously documented public symbols continue to be importable —
  but only from `parrot.bots.flows`, never from `parrot.bots.flow`.
- A breaking-change note in the next release: any code that imports
  `from parrot.bots.flow ...` must change to
  `from parrot.bots.flows ...` (single character — plural). No back-compat
  shim is provided; the migration is expected to be a single sed-style
  pass for downstream repos (Navigator, internal consumers).
- The public `parrot.bots.flows.__init__` re-export list is **curated**:
  only deliberate primitives are exposed. Some symbols that used to be
  importable from the top-level `parrot.bots.flow` (e.g.,
  `ACTION_REGISTRY`, `CELPredicateEvaluator`) may need to be imported
  from their submodules going forward. The PR description will list
  every breaking re-export change with the new submodule path.

For developers inside `ai-parrot`:
- `parrot/bots/flow/` no longer exists. The only flow package is
  `parrot/bots/flows/`.
- `AgentsFlow.run()` returns a `FlowResult` (aligned with
  `AgentCrew.run_*()`), so OTel subscribers (FEAT-177), persistence
  layers, and result-retrieval tools see identical event shapes from
  both orchestration engines.

### Internal Behavior

Layered execution (see Option A above for the canonical layer list).
Each layer leaves the repo in a green-test state. Between layers, a
mid-PR commit summarises which legacy paths have been retired.

The `flows/__init__.py` curation rule: a symbol is re-exported at the
package root **only if it is part of the documented agent-developer API**
(building flows, registering nodes, inspecting results). Implementation
details (CEL evaluation internals, action-registry plumbing, FSM internals
that are only used by `AgentsFlow`'s own scheduler) stay accessible via
submodule import but are not at the root.

The `DecisionNode` rewrite preserves the public symbol names
(`DecisionFlowNode`, `DecisionResult`, `DecisionMode`, etc.) but the
implementation now:
- Subclasses `flows/core/node.AgentNode` (or `Node` for non-agent decisions).
- Uses `NodeResult` for per-decision output.
- Reads/writes via `FlowContext.shared_data` instead of ad-hoc state.
- Emits telemetry via `build_node_metadata` for uniform OTel surfacing.

### Edge Cases & Error Handling

- **Out-of-tree consumers (Navigator)**: this PR breaks any external
  import. A pre-`/sdd-spec` grep of the Navigator repo decides whether
  a coordinated Navigator-side PR is needed; if Navigator does not
  import `parrot.bots.flow.*`, no coordination is required.
- **Decision-node behavioural diff**: if a current
  `DecisionFlowNode` test relies on a specific attribute layout (e.g.,
  `result.confidence` shape, `_validate_decision` hook signature), the
  rewrite must preserve that contract. Approach: capture every public
  attribute/method touched by a test before L3 starts; treat the test
  surface as the rewrite's behavioural contract.
- **Storage backend semantics**: if `flow/storage/memory.ExecutionMemory`
  has a quirk that `flows/core/storage/memory.ExecutionMemory` lacks,
  L2 must port it before the deletion in L6. A diff harness comparing
  both `ExecutionMemory` classes against the same `NodeResult` stream is
  the recommended check.
- **Circular import resilience**: the current
  `parrot/bots/flow/__init__.py` uses `__getattr__` to lazily import
  `AgentsFlow` and break a circular dependency. After the migration,
  `parrot/bots/flows/__init__.py` may need its own laziness if
  `flows/flow.py` imports from `flows/dsl/definition` and
  `flows/dsl/definition` happens to import anything from `flows/`. Test
  this with a clean `python -c "import parrot.bots.flows; print('ok')"`
  after L6.
- **Tests that import from the singular path**: 31 files. Some may also
  import from `parrot.bots.flow.fsm` (which no longer exists — already
  broken at HEAD). Verify these tests run today before assuming the L5
  rewrite is sufficient; some may need deeper repair.

---

## Capabilities

### New Capabilities
- `agentsflow-migration`: the cleanup feature itself (this brainstorm).

### Modified Capabilities
- `agentsflow-refactor-spec3` (FEAT-163): this feature completes the
  unfinished cleanup half of FEAT-163.
- `flows-consolidation` (FEAT-143): this feature retires the last
  cross-package coupling that FEAT-143 documented as a goal.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/flow/` | **deletes** | Entire package removed in L6. |
| `parrot/bots/flows/` | extends | New submodules for moved files (dsl, actions registry, predicates, decision nodes); curated `__init__.py`. |
| `parrot/bots/flows/flow.py` | modifies | Drops four cross-package imports (lines 42, 45, 51, 508). |
| `parrot/bots/flows/core/storage/` | extends | Receives any missing semantics ported from `flow/storage/`. |
| `parrot/flows/dev_loop/` | modifies | 8 files repointed to `parrot.bots.flows.*`. |
| 31 test files | modifies | Imports updated; possibly contract tests adjusted. |
| `parrot/bots/orchestration/` | unaffected | Already migrated by FEAT-143. |
| External: Navigator project | breaks (out-of-tree) | Requires coordinated update; out of this repo's scope but flagged. |
| FEAT-177 OTel observability | indirectly benefits | Uniform `NodeExecutionInfo` from both engines → cleaner subscriber surface. |

---

## Code Context

### User-Provided Code

```python
# Source: user, illustrating the unfinished migration
# parrot/bots/flows/flow.py:508 — new code STILL imports from singular
from parrot.bots.flow.cel_evaluator import CELPredicateEvaluator
```

### Verified Codebase References

#### Singular `parrot/bots/flow/` — what's left to migrate (verified 2026-05-28)

```
parrot/bots/flow/actions.py          552 LoC   ACTION_REGISTRY, BaseAction, LogAction, NotifyAction, WebhookAction, MetricAction, SetContextAction, ValidateAction, TransformAction, register_action, create_action
parrot/bots/flow/cel_evaluator.py    140 LoC   CELPredicateEvaluator
parrot/bots/flow/decision_node.py   1140 LoC   DecisionFlowNode, DecisionMode, DecisionType, DecisionNodeConfig, DecisionResult, BinaryDecision, ApprovalDecision, MultiChoiceDecision, EscalationPolicy, VoteWeight
parrot/bots/flow/definition.py       433 LoC   FlowDefinition, FlowMetadata, NodeDefinition, NodePosition, EdgeDefinition, ActionDefinition, LogActionDef, NotifyActionDef, WebhookActionDef, MetricActionDef, SetContextActionDef, ValidateActionDef, TransformActionDef
parrot/bots/flow/interactive_node.py  99 LoC   InteractiveDecisionNode
parrot/bots/flow/loader.py           364 LoC   FlowLoader, REDIS_KEY_PREFIX
parrot/bots/flow/node.py             106 LoC   Node (old base — superseded by flows/core/node.Node; DELETE)
parrot/bots/flow/nodes/start.py       —       StartNode (old — superseded by flows/core/node.StartNode; DELETE)
parrot/bots/flow/nodes/end.py         —       EndNode (old — superseded by flows/core/node.EndNode; DELETE)
parrot/bots/flow/storage/memory.py   102 LoC   ExecutionMemory (old — superseded by flows/core/storage/memory.ExecutionMemory)
parrot/bots/flow/storage/mixin.py    141 LoC   VectorStoreMixin (old — check delta vs flows/core/storage/mixin)
parrot/bots/flow/storage/synthesis.py 108 LoC  SynthesisMixin (old — check delta vs flows/core/storage/synthesis)
parrot/bots/flow/svelteflow.py       192 LoC   from_svelteflow, to_svelteflow
parrot/bots/flow/tools.py             79 LoC   ResultRetrievalTool (old DUPLICATE — flows/tools.py is canonical; DELETE)
parrot/bots/flow/__init__.py          —       Hybrid re-export (lazy AgentsFlow via __getattr__)
```

Total: ~3,456 LoC across 17 files.

#### Canonical replacements in `parrot/bots/flows/` (verified 2026-05-28)

```python
# parrot/bots/flows/core/node.py
class Node(BaseModel, ABC):                        # frozen, arbitrary_types_allowed
    node_id: str                                   # unique per graph instance
    # _pre_actions, _post_actions: PrivateAttr lists
class AgentNode(Node):                             # rich: execute(ctx, deps, **kwargs) → Any
class StartNode(Node):                             # name='__start__'
class EndNode(Node):                               # name='__end__'

# parrot/bots/flows/core/result.py
@dataclass
class NodeResult:                                  # replaces AgentResult
    node_id: str
    node_name: str
    task: str
    result: Any
    ai_message: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    timestamp: datetime = ...
    parent_execution_id: Optional[str] = None
    execution_id: str = ...
    # @property agent_id (alias node_id), agent_name (alias node_name)
class FlowResult: ...                              # replaces CrewResult
class NodeExecutionInfo: ...                       # replaces AgentExecutionInfo
def build_node_metadata(...) -> dict: ...

# parrot/bots/flows/core/context.py
@dataclass
class FlowContext:
    node_metadata: Dict[str, NodeExecutionInfo]    # primary
    shared_data: Dict[str, Any]                    # FEAT-143
    agent_registry: Optional[AgentRegistry]        # FEAT-163
    # alias property: agent_metadata
    # methods: get_input_for_node, get_input_for_agent (alias), resolve_agent
class AgentNotFoundError(LookupError): ...

# parrot/bots/flows/core/fsm.py
class AgentTaskMachine: ...                        # the FSM

…(truncated)…
