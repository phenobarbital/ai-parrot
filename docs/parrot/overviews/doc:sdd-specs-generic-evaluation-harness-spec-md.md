---
type: Wiki Overview
title: 'Feature Specification: Generic Agent Evaluation Harness (`AbstractEvaluator`
  + `EvalRunner`)'
id: doc:sdd-specs-generic-evaluation-harness-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot ships many agent types — coding, tool/toolkit, conversational RAG,
  multi-agent crews,
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.bots.database.agent
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.base
  rel: mentions
- concept: mod:parrot.clients.base
  rel: mentions
- concept: mod:parrot.core.events.evb
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
- concept: mod:parrot.eval
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Generic Agent Evaluation Harness (`AbstractEvaluator` + `EvalRunner`)

**Feature ID**: FEAT-217
**Date**: 2026-06-03
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x (after FEAT-176 Lifecycle Events, already merged on `dev`)

> Source brainstorm: `sdd/proposals/generic-evaluation-harness.brainstorm.md` (v3, codebase-verified 2026-06-03)

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot ships many agent types — coding, tool/toolkit, conversational RAG, multi-agent crews,
deterministic flows — but has **no agent-agnostic way to benchmark any of them**. Each kind of agent
is verified ad-hoc (unit tests with `unittest.mock`, manual smoke runs), which is brittle
(string-match assertions), non-reproducible (no `pass^k` reliability number), and impossible to
regression-gate in CI. Enterprise value lives in **toolkit agents that mutate real systems** (Jira,
databases, CRMs); those need *verifiable, reliability-oriented* evaluation, not exact-string checks.

This feature provides a single, pluggable harness that runs an agent against a dataset of tasks
inside an isolated environment, scores the result with a swappable evaluator, repeats `k` times for a
reliability metric, and persists trajectories so old runs can be re-scored cheaply. It is designed as
the offline twin of a *planned* (not-yet-built) pre-deployment shadow-mode framework, sharing the
same datasets, metrics, and Postgres baseline store.

### Goals

- A five-axis, orthogonal architecture (`EvalDataset`, `AgentFactory`, `RolloutStrategy`+`Sandbox`,
  `AbstractEvaluator`+`Metric`, `EvalRunner`) where adding a new agent type = one evaluator subclass.
- `Trajectory` as the single source of truth for scoring → re-score without re-running agents.
- A **complete vertical slice** for the state-based path (`InMemoryStateSandbox` +
  `StateBasedEvaluator`) wired to a real toolkit agent (DB and Jira), proving the contract end-to-end.
- `pass^k` (all `k` attempts pass) as the headline reliability metric; `pass@1` reported alongside.
- Persistence to Postgres JSONB (runs, results, baselines, judge cache) reusing the existing async
  Postgres pattern.
- Read-only eval lifecycle events that extend the FEAT-176 taxonomy (already merged on `dev`).

### Non-Goals (explicitly out of scope)

- `DockerSandbox` / `TestExecutionEvaluator` (SWE-bench-style coding evals) — interfaces defined, no
  concrete implementation in this feature.
- RAG `RetrievalEvaluator` / `GroundednessEvaluator` (LLM-as-judge) and the judge cache — interfaces
  reserved; implementation deferred to a follow-up.
- Multi-agent `TrajectoryEvaluator`, `RoutingEvaluator`, `CompositeEvaluator` — deferred.
- The online shadow-mode framework itself (separate, still-open gap). Only the shared store schema is
  introduced here.
- Automatic failure-mode clustering — raw trajectories are stored now (D5); clustering is a follow-up.
- Re-implementing SWE-bench/τ-bench datasets — they are *ingested* as `EvalDataset`, not re-authored.
- Reusing `AbstractLoader` for datasets (it produces `List[Document]`; that contract does not fit
  eval tasks — see brainstorm §10). A distinct `DatasetLoader` is introduced instead.

---

## 2. Architectural Design

### Overview

`EvalRunner` knows none of the type-specific logic. Five independently swappable concerns:

| Axis | Abstraction | Responsibility |
|------|-------------|----------------|
| WHAT | `EvalDataset` / `EvalTask` | Inputs + expected/goal state |
| WHO  | `AgentFactory` (callable) | Produces a fresh `AbstractBot` per attempt, **bound to the sandbox state** |
| HOW (exec) | `RolloutStrategy` + `Sandbox` | Drives the agent in an isolated env, emits a `Trajectory` |
| HOW (score) | `AbstractEvaluator` + `Metric` | `(EvalTask, Trajectory[, Sandbox]) -> EvalResult` |
| HOW (orchestrate) | `EvalRunner` | Concurrency, `pass^k`, sandbox lifecycle, aggregation, events |

The polymorphic point is `AbstractEvaluator`. This feature implements the **state-based path** end to
end and leaves the other evaluators as reserved registry slots.

**The state-based reality (D11).** There is **no common backing-store abstraction** across toolkits:
`DatabaseToolkit` holds a DSN and a lazy `self._connection` (asyncdb); `JiraToolkit` holds
`self.jira` + a `credential_resolver` resolved per-call in `_pre_execute`. A single "wrap a mock
store" sandbox is therefore impossible. The harness reconciles this with **one resettable
`StateBackend` owned by the sandbox + a per-toolkit `ToolkitBinder`** that wires the backend into the
toolkit at its documented injection point. `agent_factory(sandbox)` performs the binding.

### Component Diagram

```
EvalRunner
   │  per (task, attempt), under asyncio.Semaphore:
   ├─→ SandboxProvider.acquire(spec) ─→ Sandbox (InMemoryStateSandbox owns a StateBackend)
   │        └─ Sandbox.reset(seed_state)
   ├─→ AgentFactory(sandbox) ─→ AbstractBot     (ToolkitBinder wires StateBackend into toolkit)
   ├─→ RolloutStrategy.run(bot, task, sandbox) ─→ Trajectory
   │        └─ agent tool calls mutate the StateBackend
   ├─→ Sandbox.snapshot() ─→ trajectory.final_state
   ├─→ AbstractEvaluator.evaluate(task, trajectory, sandbox) ─→ EvalResult
   └─→ EvalReportSink.persist(report)            EventBus / EventRegistry (read-only events)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot` (`bots/abstract.py:155`) | drives | rollout calls `bot.ask()` / `bot.conversation()` |
| `AbstractClient` (`clients/base.py:242`) | uses | `LLMUserSimulator` + judge call `client.ask()` (NOT `completion()`) |
| `AbstractToolkit` (`tools/toolkit.py:191`) | binds into | `ToolkitBinder` overrides backend via `_pre_execute` / attributes |
| `DatabaseToolkit` (`bots/database/toolkits/base.py:78`) | binds into | replace `self._connection`, set `self._connected = True` |
| `JiraToolkit` (`parrot_tools/jiratoolkit.py:630`) | binds into | swap `self.credential_resolver` + pre-seed `self.jira` |
| `EventBus` (`core/events/evb.py:72`) | publishes to | dual-emit channel `lifecycle.<EvalEvent>` (per FEAT-176) |
| `EventRegistry` (`core/events/lifecycle/registry.py:90`) | emits to | read-only eval events; model-B error isolation |
| `TraceContext` (`core/events/lifecycle/trace.py:15`) | propagates | one eval run = one distributed trace (FEAT-177 OTel covers it) |
| Postgres (asyncpg) | persists to | `eval_runs` / `eval_results` / `eval_baselines` / `judge_cache` |
| `navconfig` (`from navconfig import config`) | configures | judge/model/threshold settings |

### Data Models

```python
# parrot/eval/models.py — Pydantic v2, frozen at I/O boundaries
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class EvalTask(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")
    task_id: str
    inputs: dict[str, Any]
    expected: dict[str, Any] | None = None      # gold answer / goal_state / test command
    sandbox_spec: "SandboxSpec | None" = None
    user_scenario: str | None = None            # for the LLM user simulator (τ-bench)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

class ToolCallRecord(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: Any | None = None
    error: str | None = None
    latency_ms: float | None = None

class TurnRecord(BaseModel):
    role: Literal["user", "agent", "tool", "system"]
    content: str | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    timestamp: float

class TokenUsage(BaseModel):
    prompt: int = 0
    completion: int = 0
    total: int = 0

class Trajectory(BaseModel):
    model_config = ConfigDict(extra="allow")
    task_id: str
    attempt: int                                 # 1..k for pass^k
    turns: list[TurnRecord] = Field(default_factory=list)
    final_output: Any | None = None
    final_state: dict[str, Any] | None = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: float = 0.0
    setup_latency_ms: float = 0.0                 # AbstractBot instantiation+bind time (D2)
    latency_ms: float = 0.0                       # rollout-only time
    error: str | None = None
    trace_context: dict[str, str] | None = None   # W3C traceparent/tracestate (FEAT-176)

class MetricScore(BaseModel):
    name: str
    value: float                                  # normalized; binary metrics 0.0/1.0
    passed: bool | None = None
    detail: dict[str, Any] = Field(default_factory=dict)

class EvalResult(BaseModel):
    task_id: str
    attempt: int
    scores: list[MetricScore]
    passed: bool
    trajectory: Trajectory

class EvalDataset(BaseModel):
    name: str
    tasks: list[EvalTask]
```

### New Public Interfaces

```python
# parrot/eval/sandbox/base.py
from abc import ABC, abstractmethod
from collections.abc import Callable, Awaitable

class SandboxSpec(BaseModel):
    kind: Literal["docker", "in_memory_state", "mock_api", "noop"]
    image: str | None = None
    setup: list[str] = Field(default_factory=list)
    seed_state: dict[str, Any] | None = None
    git_truncate_after: str | None = None

class Sandbox(ABC):
    @abstractmethod
    async def __aenter__(self) -> "Sandbox": ...
    @abstractmethod
    async def __aexit__(self, *exc) -> None: ...
    @abstractmethod
    async def reset(self, seed_state: dict[str, Any] | None) -> None: ...
    @abstractmethod
    async def health_check(self) -> bool: ...
    @abstractmethod
    async def snapshot(self) -> dict[str, Any]: ...
    async def exec(self, cmd: list[str]) -> "ExecResult":
        raise NotImplementedError

class SandboxProvider(ABC):
    @abstractmethod
    async def acquire(self, spec: SandboxSpec) -> Sandbox: ...
    @abstractmethod
    async def release(self, sandbox: Sandbox) -> None: ...

# D2: factory receives the (already reset) sandbox so it can bind the toolkit before returning.
AgentFactory = Callable[["Sandbox"], Awaitable["AbstractBot"]]

# parrot/eval/sandbox/state.py
class StateBackend(ABC):
    @abstractmethod
    async def reset(self, seed_state: dict[str, Any] | None) -> None: ...
    @abstractmethod
    async def snapshot(self) -> dict[str, Any]: ...

class DictStateBackend(StateBackend):
    """{collection: {entity_id: {field: value}}}; create/get/update/delete/list/query.
    snapshot() returns a deep copy with collections & keys sorted (stable diffs)."""

class ToolkitBinder(ABC):
    @abstractmethod
    def bind(self, toolkit: "AbstractToolkit", backend: StateBackend) -> None: ...

class DatabaseToolkitBinder(ToolkitBinder): ...   # sets _connection=FakeAsyncDBConnection, _connected=True
class JiraToolkitBinder(ToolkitBinder): ...        # sets credential_resolver=StaticResolver, jira=FakeJiraClient

class InMemoryStateSandbox(Sandbox):
    def __init__(self, backend: StateBackend, binder: ToolkitBinder): ...
    def bind(self, toolkit: "AbstractToolkit") -> None: ...   # called by AgentFactory

class InMemoryStateSandboxProvider(SandboxProvider): ...      # fresh per attempt, no pool

# parrot/eval/rollout.py
class RolloutStrategy(ABC):
    @abstractmethod
    async def run(self, bot: "AbstractBot", task: EvalTask, sandbox: Sandbox) -> Trajectory: ...

class SingleTurnRollout(RolloutStrategy): ...
class ConversationalRollout(RolloutStrategy):
    def __init__(self, user_sim: "UserSimulator", max_turns: int = 30): ...

class UserSimulator(ABC):
    @abstractmethod
    async def respond(self, conversation: list[TurnRecord], scenario: str) -> str | None: ...

class LLMUserSimulator(UserSimulator):
    def __init__(self, client: "AbstractClient", system_prompt: str | None = None): ...

# parrot/eval/evaluators/base.py
class Metric(ABC):
    name: str
    @abstractmethod
    async def score(self, task: EvalTask, trajectory: Trajectory,
                    sandbox: Sandbox | None = None) -> MetricScore: ...

class AbstractEvaluator(ABC):
    @abstractmethod
    async def evaluate(self, task: EvalTask, trajectory: Trajectory,
                       sandbox: Sandbox | None = None) -> EvalResult: ...

# parrot/eval/evaluators/state_based.py
@register_evaluator("state_based")
class StateBasedEvaluator(AbstractEvaluator): ...   # subset diff of snapshot vs expected.goal_state (+ forbidden)

@register_metric("state_match")
class StateMatch(Metric): ...

# parrot/eval/runner.py
class EvalRunConfig(BaseModel):
    k: int = 1                       # 1 local; CI release gate = 4
    max_concurrency: int = 8
    sandbox_pool_size: int = 4       # only for pooled (docker) sandboxes
    fail_fast: bool = False
    seed: int | None = None          # user-sim, task selection & order only (best-effort)

class EvalRunner:
    def __init__(self, *, dataset: EvalDataset, agent_factory: AgentFactory,
                 rollout: RolloutStrategy, evaluator: AbstractEvaluator,
                 sandbox_provider: SandboxProvider, config: EvalRunConfig,
                 event_bus: "EventBus | None" = None,
                 sink: "EvalReportSink | None" = None): ...
    async def run(self) -> "EvalReport": ...

# parrot/eval/sink.py
class EvalReportSink(ABC):
    @abstractmethod
    async def persist(self, report: "EvalReport") -> str: ...   # returns run_id

class PostgresEvalSink(EvalReportSink): ...
```

---

## 3. Module Breakdown

### Module 1: Data models
- **Path**: `packages/ai-parrot/src/parrot/eval/models.py`
- **Responsibility**: All Pydantic models in §2 (EvalTask, Trajectory, EvalResult, EvalDataset, …).
- **Depends on**: pydantic v2 (already used everywhere).

### Module 2: Registry
- **Path**: `packages/ai-parrot/src/parrot/eval/registry.py`
- **Responsibility**: New lightweight `name -> class` decorator registry; `@register_evaluator`,
  `@register_metric`. **Does NOT reuse** `AgentRegistry` (bot-specific, `register_bot_decorator`).
- **Depends on**: Module 1.

### Module 3: Sandbox ABCs
- **Path**: `packages/ai-parrot/src/parrot/eval/sandbox/base.py`
- **Responsibility**: `SandboxSpec`, `Sandbox`, `SandboxProvider`, `AgentFactory`, `NoopSandbox`.
- **Depends on**: Module 1.

### Module 4: State sandbox + binders (vertical slice core)
- **Path**: `packages/ai-parrot/src/parrot/eval/sandbox/state.py`
- **Responsibility**: `StateBackend`, `DictStateBackend`, `ToolkitBinder`, `DatabaseToolkitBinder`
  (+`FakeAsyncDBConnection`), `JiraToolkitBinder` (+`FakeJiraClient`, `StaticResolver`),
  `InMemoryStateSandbox`, `InMemoryStateSandboxProvider`.
- **Depends on**: Module 3; `DatabaseToolkit`, `JiraToolkit` (read their injection points only).

### Module 5: Rollout + user simulation
- **Path**: `packages/ai-parrot/src/parrot/eval/rollout.py`
- **Responsibility**: `RolloutStrategy`, `SingleTurnRollout`, `ConversationalRollout`,
  `UserSimulator`, `LLMUserSimulator` (calls `client.ask()`).
- **Depends on**: Modules 1, 3; `AbstractBot`, `AbstractClient`.

### Module 6: Evaluator ABCs
- **Path**: `packages/ai-parrot/src/parrot/eval/evaluators/base.py`
- **Responsibility**: `Metric`, `AbstractEvaluator`.
- **Depends on**: Modules 1, 3.

### Module 7: State-based evaluator
- **Path**: `packages/ai-parrot/src/parrot/eval/evaluators/state_based.py`
- **Responsibility**: `StateBasedEvaluator` (subset diff vs `goal_state` + `forbidden`), `StateMatch`.
- **Depends on**: Modules 2, 4, 6.

### Module 8: Datasets
- **Path**: `packages/ai-parrot/src/parrot/eval/datasets.py`
- **Responsibility**: `DatasetLoader` ABC, `JSONLDatasetLoader`, `YAMLDatasetLoader`. (`HFDatasetLoader`
  reserved/optional.) Distinct from `AbstractLoader`.
- **Depends on**: Module 1.

### Module 9: Runner + report
- **Path**: `packages/ai-parrot/src/parrot/eval/runner.py`
- **Responsibility**: `EvalRunConfig`, `EvalRunner` (the 7-step flow, semaphores, `pass^k`/`pass@1`
  aggregation, percentiles), `EvalReport`.
- **Depends on**: Modules 1, 3, 5, 6; `EventBus`/`EventRegistry` (optional events).

### Module 10: Persistence sink
- **Path**: `packages/ai-parrot/src/parrot/eval/sink.py`
- **Responsibility**: `EvalReportSink` ABC, `PostgresEvalSink` (asyncpg + JSONB), table DDL for
  `eval_runs` / `eval_results` / `eval_baselines` / `judge_cache`.
- **Depends on**: Modules 1, 9.

### Module 11: Eval lifecycle events
- **Path**: `packages/ai-parrot/src/parrot/eval/events.py`
- **Responsibility**: `EvalRunStarted`, `EvalRolloutStarted`, `EvalRolloutCompleted`,
  `EvalRolloutFailed`, `EvalRunCompleted` as FEAT-176 `LifecycleEvent` subclasses (read-only,
  new orchestration-layer scope).
- **Depends on**: `core/events/lifecycle/base.py` (`LifecycleEvent`), Module 9.

### Module 12: First benchmark dataset + wiring
- **Path**: `packages/ai-parrot/tests/eval/benchmarks/` (datasets) + example factory.
- **Responsibility**: `db_crud.jsonl` and `jira_triage.yaml` plus an `AgentFactory` that binds a
  `DatabaseToolkit` / `JiraToolkit` agent to the sandbox; proves end-to-end `pass^k`.
- **Depends on**: Modules 4, 7, 8, 9.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_dict_state_backend_reset_seeds` | 4 | `reset(seed)` loads collections; `snapshot()` deep-copies |
| `test_dict_state_backend_snapshot_deterministic` | 4 | snapshot keys/collections sorted, stable across calls |
| `test_db_binder_replaces_connection` | 4 | binder sets `_connection`/`_connected`; CRUD hits backend |
| `test_db_binder_no_real_network` | 4 | bound `PostgresToolkit` never calls asyncdb `start()` |
| `test_jira_binder_static_resolver` | 4 | `_pre_execute` resolves to `FakeJiraClient`, no real HTTP |
| `test_in_memory_sandbox_reset_health` | 4 | `health_check()` True; `reset` re-seeds; `exec` raises |
| `test_state_match_subset_pass` | 7 | only `goal_state` fields asserted; extra state ignored |
| `test_state_match_mismatch_detail` | 7 | mismatch & `forbidden_present` recorded in `detail` |
| `test_state_evaluator_uses_final_state` | 7 | evaluator scores `trajectory.final_state` w/o live sandbox |
| `test_registry_register_evaluator` | 2 | decorator registers + resolves by name; dup name errors |
| `test_single_turn_rollout_records_trajectory` | 5 | one `ask()`, turns + latency captured |
| `test_llm_user_simulator_calls_ask` | 5 | uses `client.ask()`, stops on `None` |
| `test_runner_pass_k_aggregation` | 9 | `pass^k` = all-k-pass fraction; `pass@1` = attempt-1 mean |
| `test_runner_isolation_per_attempt` | 9 | fresh sandbox+bot per attempt; failure → `EvalRolloutFailed` |
| `test_jsonl_yaml_loader_roundtrip` | 8 | loaders parse into `EvalDataset` |

### Integration Tests
| Test | Description |
|---|---|
| `test_db_crud_benchmark_e2e` | Full run over `db_crud.jsonl` with a real `DatabaseAgent` bound to `InMemoryStateSandbox`; `StateBasedEvaluator` reports `pass^k` |
| `test_jira_triage_benchmark_e2e` | Same for `jira_triage.yaml` via `ConversationalRollout` + `LLMUserSimulator` (mock judge/user client) |
| `test_postgres_sink_persists_run` | `PostgresEvalSink.persist()` writes `eval_runs`/`eval_results`, returns `run_id` (skipped if no DB) |
| `test_eval_events_emitted` | `EvalRunStarted`/`EvalRolloutCompleted`/`EvalRunCompleted` reach a subscriber via `EventRegistry` |

### Test Data / Fixtures
```python
@pytest.fixture
def seed_issues():
    return {"issues": {"PROJ-1": {"type": "bug", "assignee": None},
                       "PROJ-2": {"type": "task", "assignee": "bob"}}}

@pytest.fixture
def jira_triage_task(seed_issues):
    return EvalTask(
        task_id="triage-1",
        inputs={"query": "Assign all unassigned bugs in PROJ to 'oncall'."},
        sandbox_spec=SandboxSpec(kind="in_memory_state", seed_state=seed_issues),
        expected={"goal_state": {"issues": {"PROJ-1": {"assignee": "oncall"}}}, "forbidden": None},
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `parrot/eval/` package exists with Modules 1–11 and importable public names per §2.
- [ ] `from parrot.eval import EvalRunner, EvalTask, Trajectory, StateBasedEvaluator` resolves.
- [ ] `DictStateBackend.snapshot()` is deterministic (sorted) and a deep copy (no aliasing).
- [ ] `DatabaseToolkitBinder` binds a real `PostgresToolkit` so CRUD tools mutate the backend with **no
      asyncdb connection** opened (`start()` not invoked against a real DSN).
- [ ] `JiraToolkitBinder` binds a real `JiraToolkit` so tool calls resolve through `_pre_execute` to a
      `FakeJiraClient` with **no real HTTP** and no `credential_resolver` network call.
- [ ] `agent_factory(sandbox)` is the binding point; the runner instantiates a **fresh** bot per
      attempt and records `setup_latency_ms` separately from rollout `latency_ms`.
- [ ] `StateBasedEvaluator` passes iff every `expected.goal_state` assertion holds (subset match) and
      no `expected.forbidden` entity is present; mismatches recorded in `MetricScore.detail`.
- [ ] `EvalRunner.run()` reports `pass^k` (all-k-pass fraction) as headline and `pass@1`, plus
      per-tag breakdown and p50/p95 for `cost_usd`/`latency_ms`/`setup_latency_ms`.
- [ ] Raw `Trajectory` is retained per attempt in the report (D5).
- [ ] `db_crud` and `jira_triage` benchmarks run end-to-end and produce a `pass^k` number.
- [ ] Eval events are FEAT-176 `LifecycleEvent` subclasses, **read-only**, dual-emit opt-in.
- [ ] `PostgresEvalSink` persists `eval_runs`/`eval_results` via asyncpg+JSONB (integration test
      gated on DB availability).
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/eval/ -v`).
- [ ] No breaking changes to existing public API (additive package only).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified 2026-06-03 against `dev`.

### Verified Imports
```python
from parrot.bots.abstract import AbstractBot              # bots/abstract.py:155
from parrot.clients.base import AbstractClient            # clients/base.py:242
from parrot.tools import AbstractToolkit, tool            # tools/__init__.py:143,144
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool  # tools/toolkit.py:191
from parrot.bots.database.toolkits.base import DatabaseToolkit  # bots/database/toolkits/base.py:78
from parrot.bots.database.agent import DatabaseAgent      # bots/database/agent.py:114
from parrot.core.events.evb import EventBus, Event        # core/events/evb.py:72,24
from parrot.core.events.lifecycle.registry import EventRegistry   # registry.py:90
from parrot.core.events.lifecycle.trace import TraceContext       # trace.py:15
from parrot.core.events.lifecycle.base import LifecycleEvent      # base.py:21
from parrot.registry import register_agent                # registry/__init__.py:12 (NOT reused — reference only)
from parrot.stores.models import Document                 # stores/models.py:40
from navconfig import config                              # standard config accessor
# JiraToolkit lives in the satellite tools package:
from parrot_tools.jiratoolkit import JiraToolkit          # ai-parrot-tools/.../jiratoolkit.py:630
```

### Existing Class Signatures
```python
# bots/abstract.py
class AbstractBot(...):                                    # line 155
    async def conversation(self, ...): ...                # line 3107  → returns AIMessage
    async def ask(self, ...): ...                         # line 3660  → returns AIMessage
    async def ask_stream(self, ...): ...                  # line 3715  → AsyncIterator[str|AIMessage]

# clients/base.py
class AbstractClient(EventEmitterMixin, ABC):             # line 242
    async def ask(self, ...): ...                         # line 1497  (abstract)
    async def ask_stream(self, ...): ...                  # line 1535  (abstract)

# tools/toolkit.py

…(truncated)…
