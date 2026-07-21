---
type: Wiki Overview
title: 'Brainstorm: AgentCrew Primitives Migration (Spec 2)'
id: doc:sdd-proposals-agentcrew-primitives-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Migrate AgentCrew one execution mode at a time, in order of complexity:'
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.fsm
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# Brainstorm: AgentCrew Primitives Migration (Spec 2)

**Date**: 2026-04-30
**Author**: Jesus
**Status**: exploration
**Recommended Option**: Option A
**Depends on**: `flow-primitives` (FEAT-134, merged to dev)

---

## Problem Statement

`AgentCrew` (`parrot/bots/orchestration/crew.py`) and the new `flows.core` primitives (FEAT-134) define overlapping abstractions: both have `AgentNode`, `FlowContext`, type aliases (`AgentRef`, `DependencyResults`, `PromptBuilder`), and storage classes. This duplication means bug fixes and improvements must be applied twice, and the primitives remain unvalidated against a real consumer with real LLM calls.

**Who is affected:**
- Developers maintaining AgentCrew — they work with stale local copies instead of the canonical primitives.
- Future Spec 3 (AgentsFlow DAG engine refactor) — it would build on unvalidated primitives if Spec 2 doesn't exercise them first.

**Why now:** FEAT-134 just merged. The primitives are fresh, testable, and haven't accumulated downstream dependents. If a design flaw exists (e.g., FSM state transitions don't map to AgentCrew's `completed_tasks` pattern), now is the cheapest time to discover and fix it.

## Constraints & Requirements

- **Zero breaking changes**: API pública of `AgentCrew` (method signatures, return types, import paths) must remain identical.
- **Historical imports preserved**: `from parrot.bots.orchestration.crew import AgentNode, FlowContext` must still work.
- **Observable behavior unchanged**: execution order, status calculation, error semantics, callback timing, prompt formatting — all must be byte-for-byte equivalent (prompt) or semantically equivalent (behavior).
- **No new external dependencies**: only internal refactoring.
- **No scope creep**: no new features, no performance optimizations beyond preventing regression.
- **Inline Spec 1 patches allowed**: minor defects in primitives discovered during migration can be fixed inline with a clearly documented change; design-level defects require a separate Spec 1.1 patch.

---

## Options Explored

### Option A: Per-Mode Sequential Migration

Migrate AgentCrew one execution mode at a time, in order of complexity:

1. **Task 0**: Prep — audit existing tests, update storage imports (D5), set up `@pytest.mark.real_llm` infrastructure.
2. **Task 1**: Add `execute()` to core `AgentNode` — timeout handling, execution time tracking, pre/post action hooks. Make `_CrewAgentNode` a subclass of core `AgentNode`.
3. **Task 2**: Migrate `run_sequential` — swap local types for `flows.core` imports, replace `_CrewAgentNode` usage with the new `AgentNode` (via subclass), wire FSM transitions.
4. **Task 3**: Migrate `run_parallel` — same pattern, verify `asyncio.gather` + FSM concurrent safety.
5. **Task 4**: Migrate `run_flow` — DAG dependencies, conditional transitions, `on_agent_complete` callback wired to `on_enter_completed`.
6. **Task 5**: Migrate `run_loop` — iterative state, condition evaluation, `max_iterations` cap.
7. **Task 6**: Cleanup — remove dead local definitions (`FlowContext`, `AgentRef`, `DependencyResults`, `PromptBuilder`), verify re-exports, final regression suite.

Each task has its own regression tests that must pass before moving to the next.

Pros:
- Failure isolation: if `run_flow` migration reveals a primitive defect, `run_sequential` and `run_parallel` are already stable.
- Natural test organization: each mode already maps to distinct test cases.
- Incremental validation: every merge is a verified checkpoint.
- Easy to parallelize review: each task can be reviewed independently.

Cons:
- More SDD tasks (~7 vs ~5).
- Intermediate states where crew.py uses both old and new abstractions simultaneously.
- Each task requires its own test setup and context loading.

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `statemachine` | FSM runtime (already in deps) | Used by `AgentTaskMachine` |
| `pytest` + `pytest-asyncio` | Test infrastructure | Already configured |
| `google-genai` | Gemini Flash for real_llm tests | Already in deps |

Existing Code to Reuse:
- `packages/ai-parrot/src/parrot/bots/flows/core/node.py` — `AgentNode`, `Node` ABC (lines 34-176)
- `packages/ai-parrot/src/parrot/bots/flows/core/context.py` — `FlowContext` with backward-compat aliases (lines 25-183)
- `packages/ai-parrot/src/parrot/bots/flows/core/types.py` — `AgentRef`, `DependencyResults`, `PromptBuilder`, `AgentLike` (lines 38-100)
- `packages/ai-parrot/src/parrot/bots/flows/core/fsm.py` — `AgentTaskMachine`, `TransitionCondition` (lines 17-108)
- `packages/ai-parrot/src/parrot/bots/flows/core/result.py` — `NodeExecutionInfo`, `FlowResult`, `determine_run_status` (lines 32-487)
- `packages/ai-parrot/tests/test_agent_crew_examples.py` — existing crew tests with stub agents

---

### Option B: Per-Primitive Sequential Migration

Migrate one primitive type at a time across all modes simultaneously:

1. **Task 0**: Prep (same as Option A).
2. **Task 1**: Add `execute()` to core `AgentNode` + make `_CrewAgentNode` a subclass.
3. **Task 2**: Swap type aliases (`AgentRef`, `DependencyResults`, `PromptBuilder`) — affects all modes but is a pure import change.
4. **Task 3**: Swap `FlowContext` — all modes adopt core `FlowContext`.
5. **Task 4**: Swap `_CrewAgentNode` for core `AgentNode` subclass — the behavioral change.
6. **Task 5**: Cleanup — remove dead definitions, verify re-exports.

Each task touches all modes, validated by running the full test suite.

Pros:
- Fewer tasks (~6).
- Each primitive is migrated completely before moving to the next — no "half old, half new" within a single primitive.
- Cleaner diff per task (all type alias changes in one commit, all FlowContext changes in another).

Cons:
- Each task touches all four modes — if the type alias swap breaks `run_loop` but not the others, debugging is harder.
- Test failures are less localized: a test failure after swapping FlowContext could be in any mode.
- The `_CrewAgentNode` → core `AgentNode` swap (Task 4) is still a big-bang across all modes, which is the riskiest part.
- Intermediate state where `FlowContext` is from core but `_CrewAgentNode` is still local is architecturally odd.

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| (same as Option A) | | |

Existing Code to Reuse:
- (same as Option A)

---

### Option C: Hybrid — Primitives First, Then Mode Validation

Combine the strengths of A and B:

1. **Task 0**: Prep (same).
2. **Task 1**: Add `execute()` to core `AgentNode` + subclass `_CrewAgentNode`.
3. **Task 2**: Swap all imports at once (types, FlowContext, AgentNode subclass) — a single big migration commit.
4. **Tasks 3-6**: Per-mode validation + regression tests (one task per mode) — but the code is already migrated; these tasks only add tests and fix any issues found.

Pros:
- Fast migration: the actual code change is one task.
- Per-mode validation gives the same failure isolation as Option A for the test phase.
- Fewer total tasks if the migration goes smoothly.

Cons:
- Task 2 is high-risk: a single commit that changes everything.
- If Task 2 breaks multiple modes, the per-mode validation tasks become debugging tasks instead of confirmation tasks.
- Harder to revert: reverting Task 2 undoes everything.

Effort: Medium-Low (if clean) / High (if defects found)

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| (same as Option A) | | |

Existing Code to Reuse:
- (same as Option A)

---

## Recommendation

**Option A** is recommended because:

1. **Risk management**: The per-mode granularity isolates failures to the specific execution pattern that caused them. When `run_flow` (the most complex mode with DAG dependencies, conditional transitions, and callbacks) inevitably reveals edge cases, `run_sequential` and `run_parallel` are already validated and stable.

2. **The intermediate "half old, half new" state** (Option A's main con) is actually manageable: crew.py already imports from multiple internal modules, and adding `flows.core` as another import source during the transition is no worse than the current state where it defines things locally.

3. **Option B's per-primitive approach** is elegant in theory but fragile in practice: swapping `FlowContext` across all modes in one task means any behavioral difference in `mark_completed()` timing affects all four modes simultaneously, making root-cause analysis harder.

4. **Option C** concentrates risk in one large commit, which contradicts the core motivation of Spec 2 (validating primitives incrementally against a real consumer).

The tradeoff: ~7 tasks instead of ~5-6, with more test setup overhead per task. This is acceptable because the incremental confidence gain is worth the coordination cost, especially given that this migration is the first real-world validation of the FEAT-134 primitives.

---

## Feature Description

### User-Facing Behavior

Nothing changes. Users of `AgentCrew` continue to:
- Import from `parrot.bots.orchestration.crew` (or `parrot.models.crew` for result types).
- Call `run_sequential()`, `run_parallel()`, `run_flow()`, `run_loop()` with identical signatures.
- Receive `CrewResult` objects with the same structure, status semantics, and metadata.
- Use `add_agent()`, `task_flow()`, and all configuration methods identically.
- Import `AgentNode`, `FlowContext` from `parrot.bots.orchestration.crew` (re-exports).

### Internal Behavior

**Before migration:**
- `crew.py` defines `_CrewAgentNode`, `FlowContext`, `AgentRef`, `DependencyResults`, `PromptBuilder` locally.
- Each `run_*` method manages agent state via `FlowContext.completed_tasks: Set[str]` (implicit binary FSM: pending/completed).
- `_CrewAgentNode.execute()` handles prompt formatting, timeout, time tracking.

**After migration:**
- `crew.py` imports `AgentNode`, `FlowContext`, `AgentRef`, `DependencyResults`, `PromptBuilder` from `parrot.bots.flows.core`.
- `_CrewAgentNode` becomes a subclass of core `AgentNode`, inheriting `execute()` with timeout handling and execution time tracking. It overrides `_format_prompt()` to preserve crew-specific prompt formatting (the "Task + Context from previous agents" format).
- Each `run_*` method benefits from the per-node FSM (`AgentTaskMachine`): state transitions are explicit (idle → ready → running → completed/failed) instead of implicit set operations.
- `FlowContext.completed_tasks` is still the primary check for dependency readiness (`can_execute()`), but now each node also carries its own FSM state for richer lifecycle tracking.
- `on_agent_complete` callback in `run_flow()` fires via the FSM's `on_enter_completed` hook instead of at the current ad-hoc call site.

**Core `AgentNode.execute()` enhancement:**
The new `execute()` method on core `AgentNode` encapsulates:
1. Pre-action hooks (`run_pre_actions`).
2. Agent invocation via `agent.ask()` (or `agent.invoke()` via `AgentLike` protocol).
3. Optional timeout via `asyncio.wait_for`.
4. Execution time tracking (`start_time` / `end_time`).
5. Post-action hooks (`run_post_actions`).
6. Error handling with metadata capture.

This makes `execute()` reusable by both `AgentCrew` (via `_CrewAgentNode` subclass) and the future `AgentsFlow` refactor (Spec 3), which currently has its own simpler `FlowNode.execute()` at `parrot/bots/flow/fsm.py:266-274` that lacks timeout support and tracks timing externally.

### Edge Cases & Error Handling

- **FSM state mismatch**: If a node's FSM is in an unexpected state when `execute()` is called (e.g., already `completed`), the FSM library raises a `TransitionNotAllowed` exception. This must be caught and converted to an appropriate error response, not propagated raw.
- **Concurrent FSM mutation in `run_parallel`**: Each node has its own FSM instance — no shared state. The shared `FlowContext.completed_tasks` set is still mutated concurrently, but `set.add()` is atomic in CPython. This invariant must be explicitly tested.
- **Timeout + FSM**: When a timeout occurs, the node must transition to `failed` state before the `TimeoutError` propagates. The FSM's `fail()` transition must be called in the exception handler.
- **Callback timing change**: `on_agent_complete` moving from ad-hoc call site to FSM `on_enter_completed` may fire at a slightly different point in the execution flow. The regression test must verify that the callback receives the same arguments at the same logical moment.
- **`_format_prompt` byte-equality**: The prompt format ("Task: {task}\nContext from previous agents:\n--- From {dep_agent} ---\n{result}") is an observable invariant. Changing even whitespace can alter LLM responses. A dedicated test must assert exact prompt string equality for canonical inputs.
- **`node_id` vs `agent.name`**: AgentCrew never uses the same agent twice, so `node_id == agent.name` always holds. The migration must pass `node_id=agent.name` explicitly when constructing `AgentNode` instances.

---

## Capabilities

### New Capabilities
- `agentnode-execute`: Core `AgentNode.execute()` method with timeout handling, execution time tracking, and pre/post action hooks — shared by all orchestration engines.
- `real-llm-test-infra`: `@pytest.mark.real_llm` marker and test infrastructure for LLM-dependent regression tests.

### Modified Capabilities
- `flow-primitives` (FEAT-134): `AgentNode` gains `execute()` method; minor patches if migration reveals defects.
- `agent-crew`: Internal implementation refactored to consume `flows.core` primitives; public API unchanged.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot.bots.flows.core.node.AgentNode` | extends | Add `execute()` method with timeout + timing |
| `parrot.bots.orchestration.crew._CrewAgentNode` | modifies | Becomes subclass of core `AgentNode` |
| `parrot.bots.orchestration.crew.AgentCrew` | modifies | Internal imports change; behavior unchanged |
| `parrot.bots.orchestration.crew` (module) | modifies | Local type definitions removed, imports from `flows.core` |
| `parrot.bots.flows.core.fsm.AgentTaskMachine` | depends on | FSM hooks (`on_enter_completed`) used for callback wiring |
| `tests/` | extends | New `@pytest.mark.real_llm` regression tests |
| `parrot.bots.flow.fsm.FlowNode` | *future* (Spec 3) | Will be refactored to use core `AgentNode.execute()` |

---

## Code Context

### User-Provided Code

No user-provided code snippets during brainstorming.

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/bots/flows/core/node.py:34
class Node(ABC):
    node_id: str                    # line 61
    logger: logging.Logger          # line 62
    _pre_actions: list              # line 63
    _post_actions: list             # line 64
    def _init_node(self, node_id: str, name: str) -> None:          # line 66
    @property
    @abstractmethod
    def name(self) -> str:                                           # line 80-82
    def add_pre_action(self, action: ActionCallback) -> None:        # line 87
    def add_post_action(self, action: ActionCallback) -> None:       # line 95
    async def run_pre_actions(self, prompt: str = "", **ctx) -> None: # line 105
    async def run_post_actions(self, result: Any = None, **ctx) -> None: # line 121

# From packages/ai-parrot/src/parrot/bots/flows/core/node.py:143
@dataclass
class AgentNode(Node):
    agent: AgentLike                                # line 161
    node_id: str                                    # line 162
    dependencies: Set[str] = field(...)             # line 163
    successors: Set[str] = field(...)               # line 164
    fsm: Optional[AgentTaskMachine] = field(...)    # line 165
    @property
    def name(self) -> str:                          # line 173-176

# From packages/ai-parrot/src/parrot/bots/orchestration/crew.py:130
class _CrewAgentNode:
    def __init__(self, agent: Union[BasicAgent, AbstractBot], dependencies: Optional[Set[str]] = None): # line 141
    def _format_prompt(self, input_data: Dict[str, Any]) -> str:    # line 146
    async def execute(self, context: FlowContext, timeout: Optional[float] = None) -> Any: # line 172

# From packages/ai-parrot/src/parrot/bots/flows/core/context.py:25
@dataclass
class FlowContext:
    initial_task: str
    results: Dict[str, Any]
    responses: Dict[str, Any]
    node_metadata: Dict[str, NodeExecutionInfo]
    completion_order: List[str]
    errors: Dict[str, Exception]
    active_tasks: Set[str]
    completed_tasks: Set[str]
    # Backward-compat aliases:
    @property
    def agent_metadata(self) -> Dict[str, NodeExecutionInfo]:       # line 162
    def get_input_for_agent(self, agent_name, dependencies):        # line 170

# From packages/ai-parrot/src/parrot/bots/flows/core/fsm.py:40
class AgentTaskMachine:
    # States: idle, ready, running, completed, failed, blocked
    # Transitions: schedule, start, succeed, fail, block, unblock, retry
    # Hooks: on_enter_running(), on_enter_completed(), on_enter_failed()

# From packages/ai-parrot/src/parrot/bots/flow/fsm.py:198
@dataclass
class FlowNode(Node):
    agent: Union[BasicAgent, AbstractBot]           # line 210
    fsm: AgentTaskMachine                           # line 211
    execution_time: float = 0.0                     # line 217
    started_at: Optional[datetime] = None           # line 218
    completed_at: Optional[datetime] = None         # line 219
    retry_count: int = 0                            # line 220
    max_retries: int = 3                            # line 221
    async def execute(self, prompt: str, ctx: Dict[str, Any]) -> Any: # line 266

# From packages/ai-parrot/src/parrot/bots/flows/core/types.py:54
@runtime_checkable
class AgentLike(Protocol):
    @property
    def name(self) -> str: ...                      # line 63
    async def invoke(self, prompt: str, **kwargs: Any) -> Any: ...  # line 73
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.bots.flows.core import (              # flows/core/__init__.py
    AgentLike, AgentRef, DependencyResults, PromptBuilder,
    ActionCallback, FlowStatus,
    AgentTaskMachine, TransitionCondition,
    Node, AgentNode, StartNode, EndNode,
    FlowResult, NodeExecutionInfo, build_node_metadata, determine_run_status,
    FlowContext, FlowTransition,
    ExecutionMemory, VectorStoreMixin, PersistenceMixin, SynthesisMixin,
)

from parrot.bots.flows.core.result import build_agent_metadata  # used in _CrewAgentNode

# Re-export shim at parrot.bots.flows level:
from parrot.bots.flows import AgentNode, FlowContext  # re-exports from core
```

#### Key Attributes & Constants
- `AgentTaskMachine` states: `idle`, `ready`, `running`, `completed`, `failed`, `blocked` (fsm.py:40-108)
- `TransitionCondition` values: `ON_SUCCESS`, `ON_ERROR`, `ON_TIMEOUT`, `ON_CONDITION`, `ALWAYS` (fsm.py:17-37)
- `FlowStatus` values: `COMPLETED`, `PARTIAL`, `FAILED` (types.py:38-46)
- `FlowContext.completed_tasks: Set[str]` — primary dependency check mechanism (context.py)
- `_CrewAgentNode` result dict keys: `'response'`, `'output'`, `'execution_time'`, `'prompt'` (crew.py:198-203)

### Does NOT Exist (Anti-Hallucination)
- ~~`AgentNode.execute()`~~ — does NOT exist yet on core `AgentNode`; it's what Spec 2 Task 1 will add.
- ~~`AgentLike.ask()`~~ — the protocol defines `invoke()`, not `ask()`. Actual agents use `ask()` but the protocol says `invoke()`. This naming inconsistency is tracked for Spec 3.
- ~~`FlowNode` in `flows.core`~~ — `FlowNode` exists only in the old `parrot.bots.flow.fsm` module, not in `flows.core`.
- ~~`AgentNode.execution_time`~~ — does NOT exist on core `AgentNode`; only `FlowNode` has it.
- ~~`AgentNode.started_at` / `completed_at`~~ — do NOT exist on core `AgentNode`; only `FlowNode` has these.
- ~~`Node.execute()`~~ — the `Node` ABC has no `execute()` method; only action hooks (`run_pre_actions`, `run_post_actions`).
- ~~`@pytest.mark.real_llm`~~ — does NOT exist yet; must be created.
- ~~`FlowContext.mark_failed()`~~ — verify existence; may or may not exist depending on FEAT-134 implementation.

---

## Parallelism Assessment

- **Internal parallelism**: Limited. All tasks modify `crew.py` (the central file). Tasks 2-5 (per-mode migration) are sequential by design — each builds on the verified state of the previous one. Task 0 (prep) and Task 1 (core AgentNode enhancement) can run in parallel since they touch different files.
- **Cross-feature independence**: Spec 2 depends on FEAT-134 (merged). No other in-flight specs touch `crew.py` or `flows.core`. The `parrot/bots/flow/fsm.py` (AgentsFlow) is out of scope and will be addressed in Spec 3.
- **Recommended isolation**: `per-spec` — single worktree, tasks executed sequentially.
- **Rationale**: `crew.py` is the sole file modified by every migration task. Parallel worktrees would create merge conflicts on every task boundary. Task 0 and Task 1 could theoretically run in separate worktrees (different files), but the overhead of merging isn't worth the marginal time savings on two small tasks.

---

## Open Questions

- [x] D1 — Migration strategy: Option A/B/C — *Owner: Jesus*: **Option A (per-mode sequential)** confirmed. Option B (per-primitive) evaluated as alternative; rejected due to harder failure isolation.
- [x] D2 — LLM for regression tests — *Owner: Jesus*: **Gemini Flash** (`gemini-2.5-flash`, `temperature=0`) for behavioral tests. Mocks for structural invariants. Real LLM calls are OK; gated behind `@pytest.mark.real_llm`.
- [x] D3 — Test gating mechanism — *Owner: Jesus*: New `@pytest.mark.real_llm` marker + env var `PARROT_TEST_REAL_LLM=1`. Skip by default in CI, opt-in locally.
- [x] D4 — Audit of existing tests — *Owner: Jesus*: Included as **Task 0** within the spec.
- [x] D5 — Storage imports path — *Owner: Jesus*: Update to canonical `parrot.bots.flows.core.storage` path, done in **Task 0**.
- [x] D6 — `AgentLike` in public signatures — *Owner: Jesus*: Keep public signatures as `Union[BasicAgent, AbstractBot]`; use `AgentLike` only internally. No public signature changes in Spec 2.
- [x] D7 — `_format_prompt` destination — *Owner: Jesus*: Stays as **private method** on `_CrewAgentNode` (which becomes a subclass of core `AgentNode`).
- [x] D8 — Performance/coverage thresholds — *Owner: Jesus*: Lightweight baseline — verify 5-agent parallel flow doesn't regress >10%. No memory or coverage enforcement.
- [x] D9 — Protocol for Spec 1 defects — *Owner: Jesus*: Minor bugs fixed inline within Spec 2 with clearly documented changes. Design-level defects trigger a separate Spec 1.1 patch.
- [x] D10 — Re-export deprecation timeline — *Owner: Jesus*: Re-exports remain indefinitely for external users. Internal repo imports updated to canonical paths during Spec 2.
- [ ] D11 — `AgentLike.invoke()` vs `agent.ask()` naming inconsistency — *Owner: Jesus*: The `AgentLike` protocol defines `invoke()` but all concrete agents use `ask()`. Core `AgentNode.execute()` must decide which to call. Recommend: call `ask()` (matching concrete agents) and note the protocol inconsistency for Spec 3 cleanup.
- [ ] D12 — `execute()` return type: dict vs raw response — *Owner: Jesus*: `_CrewAgentNode.execute()` returns a dict `{'response', 'output', 'execution_time', 'prompt'}`. Core `AgentNode.execute()` should return a structured type (dataclass or dict). Recommend: return a dict with the same keys for backward compatibility; consider a `NodeExecutionResult` dataclass in Spec 3.
