# FEAT-XXX — Generic Agent Evaluation Harness (`AbstractEvaluator` + `EvalRunner`)

**Status:** Brainstorm v3 — decisions resolved + corrected against the live codebase (input artifact for `/sdd-spec`)
**Package:** `packages/ai-parrot` (core) — new module `parrot/eval/`
**Depends on:** `AbstractBot`, `AbstractClient`, `EventBus`, `navconfig`. Extends FEAT-176 (Lifecycle Events) taxonomy.

**Codebase grounding (verified 2026-06-03).** Confirmed and used as-is:
`AbstractBot.ask()/conversation()/ask_stream()` (`parrot/bots/abstract.py`); `AbstractClient.ask()/ask_stream()`
— **the real contract; there is no `completion()/stream()/embed()`** (`parrot/clients/base.py`); `EventBus`
(`parrot/core/events/evb.py`) + FEAT-176 spec & `parrot/core/events/lifecycle/`; `AbstractLoader` (real name —
**not** `BaseLoader`) returning `List[Document]` (`parrot/loaders/abstract.py`); `AgentRegistry`/`@register_agent`
(`parrot/registry/registry.py`); `IntentRouterMixin`, `CapabilityRegistry`; async Postgres + JSONB via asyncpg.
**Does NOT exist yet — this (or related) work must build it:** `parrot/eval/*`; `AuditLedger`; the shadow-mode
framework; `@register_evaluator`/`@register_metric` (the bot registry is **not** generic); `moto`-based service
mocks (tests use `unittest.mock` only). Note: FEAT-176 is **merged on `dev`** (2026-05-16,
`TraceContext`/`EventRegistry`/lifecycle events) and FEAT-177 OTel **has a spec**
(`sdd/specs/otel-observability.spec.md`) — both are available to build on, not blockers.

---

## 1. Purpose

Provide a single, agent-agnostic harness that benchmarks **every** agent type in AI-Parrot
(coding, tool/toolkit, conversational RAG, multi-agent crews, deterministic flows) under one
runner, with pluggable scoring. The harness is designed as the offline twin of a *planned*
pre-deployment shadow-mode testing framework (not implemented yet — a separate, still-open gap).
When that framework lands it shares this harness's datasets, metrics and Postgres baseline store:
baseline = annotated goal states offline vs. live traffic online.

Non-goal: re-implement SWE-bench/τ-bench. We implement the *harness contract*; their datasets are
ingested as `EvalDataset` instances.

---

## 2. Core design decision — five orthogonal axes

The `EvalRunner` knows none of the type-specific logic. Five independently swappable concerns:

| Axis | Abstraction | Responsibility |
|------|-------------|----------------|
| WHAT | `EvalDataset` / `EvalTask` | The unit(s) of evaluation: inputs + expected/goal state |
| WHO  | `AgentFactory` (callable) | Produces a fresh `AbstractBot` per attempt (stochastic isolation) |
| HOW (exec) | `RolloutStrategy` + `Sandbox` | Drives the agent against a task inside an isolated env, emits a `Trajectory` |
| HOW (score) | `AbstractEvaluator` + `Metric` | Maps `(EvalTask, Trajectory[, Sandbox]) -> EvalResult` |
| HOW (orchestrate) | `EvalRunner` | Concurrency, pass^k repeats, sandbox lifecycle, aggregation, event emission |

The polymorphic point is `AbstractEvaluator`. Per agent type:

- `TestExecutionEvaluator` — SWE-bench style; runs the repo test command in a `DockerSandbox`.
- `StateBasedEvaluator` — τ-bench style; diffs final sandbox state vs. annotated goal state.
- `RetrievalEvaluator` — recall@k / MRR / nDCG against a gold chunk set (RAG).
- `GroundednessEvaluator` — rubric-based LLM-as-judge (RAG generation). See §5.1.
- `RoutingEvaluator` — classification accuracy for `IntentRouterMixin` / `CapabilityRegistry`.
- `TrajectoryEvaluator` — multi-agent coordination (handoff success, deadlock detection, turn count).
- `CompositeEvaluator` — runs several evaluators, merges `MetricScore`s (RAG = retrieval + generation).

---

## 3. Data model (Pydantic v2, frozen at I/O boundaries)

```python
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class EvalTask(BaseModel):
    """Immutable unit of evaluation."""
    model_config = ConfigDict(frozen=True, extra="allow")

    task_id: str
    inputs: dict[str, Any]                      # what is fed to the agent (query, issue, scenario)
    expected: dict[str, Any] | None = None      # gold answer / goal state / test command
    sandbox_spec: "SandboxSpec | None" = None   # how to provision the isolated env
    user_scenario: str | None = None            # instructions for the LLM user simulator (τ-bench)
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
    """Full execution trace for one (task, attempt). The single source of truth for scoring."""
    model_config = ConfigDict(extra="allow")

    task_id: str
    attempt: int                                 # 1..k for pass^k
    turns: list[TurnRecord] = Field(default_factory=list)
    final_output: Any | None = None
    final_state: dict[str, Any] | None = None     # sandbox snapshot taken post-rollout
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: float = 0.0
    setup_latency_ms: float = 0.0                 # D2: AbstractBot instantiation (factory) time
    latency_ms: float = 0.0                       # rollout-only execution time
    error: str | None = None
    trace_context: dict[str, str] | None = None   # W3C traceparent/tracestate (FEAT-176)


class MetricScore(BaseModel):
    name: str
    value: float                                  # normalized; binary metrics use 0.0/1.0
    passed: bool | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class EvalResult(BaseModel):
    task_id: str
    attempt: int
    scores: list[MetricScore]
    passed: bool                                  # overall task success for this attempt
    trajectory: Trajectory
```

---

## 4. Execution abstractions

### 4.1 Sandbox (isolated, resettable env)

```python
from abc import ABC, abstractmethod

class SandboxSpec(BaseModel):
    kind: Literal["docker", "in_memory_state", "mock_api", "noop"]
    image: str | None = None                      # docker
    setup: list[str] = Field(default_factory=list)
    seed_state: dict[str, Any] | None = None      # initial DB/API state for state-based eval
    git_truncate_after: str | None = None         # commit/issue marker; re-applied on every reset

class Sandbox(ABC):
    @abstractmethod
    async def __aenter__(self) -> "Sandbox": ...
    @abstractmethod
    async def __aexit__(self, *exc) -> None: ...
    @abstractmethod
    async def reset(self, seed_state: dict[str, Any] | None) -> None:
        """D3: re-seed state AND re-apply git-history truncation. Must leave a pristine env."""
    @abstractmethod
    async def health_check(self) -> bool:
        """D3: pooled docker sandboxes are health-checked on reset; failures -> evict + reprovision."""
    @abstractmethod
    async def snapshot(self) -> dict[str, Any]:
        """Capture final state for state-based evaluators."""
    async def exec(self, cmd: list[str]) -> "ExecResult":
        """Run a command (test-execution evaluators). Optional per kind."""
        raise NotImplementedError

class SandboxProvider(ABC):
    """D3: DockerSandbox uses a POOL (provision is the bottleneck). reset() health-checks; a
    dirty/unhealthy container is evicted and reprovisioned before the next attempt is served.
    Sandbox concurrency budget == pool size. in_memory_state / mock_api are provisioned fresh."""
    @abstractmethod
    async def acquire(self, spec: SandboxSpec) -> Sandbox: ...
    @abstractmethod
    async def release(self, sandbox: Sandbox) -> None: ...
```

Concrete: `DockerSandbox` (coding; pooled+reset, git history re-truncated each reset),
`InMemoryStateSandbox` (toolkit/state-based; owns a resettable in-memory `StateBackend` wired into
the toolkit-under-test through a per-toolkit `ToolkitBinder` — see §13; fresh per attempt),
`MockAPISandbox` (HTTP/API toolkits; builds on the existing `unittest.mock`-based fakes in
`tests/integration/` — there is **no** `moto`-style service mocking in the repo today, so it is added
per-toolkit as needed; fresh per attempt),
`NoopSandbox` (pure conversational/RAG, no world state).

### 4.2 RolloutStrategy (composition over inheritance — strategy pattern)

```python
from collections.abc import Callable, Awaitable
# D2: invoked fresh per attempt. Receives the already-reset Sandbox so the factory can wire the
# toolkit-under-test to the sandbox's StateBackend BEFORE returning the bot (see §13). Stateless
# evals (Noop/Docker) simply ignore the argument.
AgentFactory = Callable[["Sandbox"], Awaitable["AbstractBot"]]

class RolloutStrategy(ABC):
    @abstractmethod
    async def run(self, bot: "AbstractBot", task: EvalTask, sandbox: Sandbox) -> Trajectory: ...

class SingleTurnRollout(RolloutStrategy):
    """One ask(); capture output. RAG, classification, single-shot tasks."""

class ConversationalRollout(RolloutStrategy):
    """Loop bot.conversation() against a UserSimulator until done|max_turns (τ-bench)."""
    def __init__(self, user_sim: "UserSimulator", max_turns: int = 30): ...

class CodingRollout(RolloutStrategy):
    """Agentic loop in DockerSandbox until a patch is produced or max_turns reached."""
```

### 4.3 UserSimulator (LLM-driven, not scripted)

```python
class UserSimulator(ABC):
    @abstractmethod
    async def respond(self, conversation: list[TurnRecord], scenario: str) -> str | None:
        """Return next user utterance, or None to signal task complete / give up."""

class LLMUserSimulator(UserSimulator):
    """Backed by an AbstractClient, called via `client.ask()` (the real contract is `ask()/ask_stream()`
    — there is no `completion()/stream()/embed()`); constrained by the scenario goal, temp=0 for
    reproducibility.
    D6: seeded selection/order only; agent-side randomness handled via k>1, not seeding."""
    def __init__(self, client: "AbstractClient", system_prompt: str | None = None): ...
```

---

## 5. Scoring abstractions

```python
class Metric(ABC):
    name: str
    @abstractmethod
    async def score(self, task: EvalTask, trajectory: Trajectory,
                    sandbox: Sandbox | None = None) -> MetricScore: ...

class AbstractEvaluator(ABC):
    """Type-specific scoring. Composes one or more Metrics; defines overall pass condition."""
    @abstractmethod
    async def evaluate(self, task: EvalTask, trajectory: Trajectory,
                       sandbox: Sandbox | None = None) -> EvalResult: ...
```

`StateBasedEvaluator.evaluate` calls `await sandbox.snapshot()` and diffs against `task.expected`.
`TestExecutionEvaluator.evaluate` calls `await sandbox.exec(task.expected["test_cmd"])`.

Registry — a **new, lightweight decorator registry** at `parrot/eval/registry.py`. The existing
`AgentRegistry`/`@register_agent` is **bot-specific** (`register_bot_decorator`, tied to `BotMetadata`)
and is NOT reused; we only mirror its decorator ergonomics with a minimal `name -> class` map:

```python
@register_evaluator("state_based")
class StateBasedEvaluator(AbstractEvaluator): ...

@register_metric("recall_at_k")
class RecallAtK(Metric): ...
```

### 5.1 LLM-as-judge — rubric-based, reference-aware (D4)

```python
class RubricCriterion(BaseModel):
    key: str                                      # e.g. "is_grounded", "answers_question"
    description: str

class Rubric(BaseModel):
    rubric_id: str
    version: str                                  # part of the judge cache key
    criteria: list[RubricCriterion]

class GroundednessEvaluator(AbstractEvaluator):
    """Rubric-driven judge. Returns per-criterion booleans (NOT a vague scalar) to cut
    position/verbosity bias. reference-aware when task.expected holds a gold answer; reference-free
    only as fallback.

    Config (navconfig):
      - judge_client:  AbstractClient (invoked via `ask()` with structured output). Default: a
                       structured-output-capable provider (Claude/OpenAI).
                       NEVER Gemini as judge — no native structured output w/ function calling.
                       Prefer judge provider != provider-under-test (self-preference bias).
      - judge_model_version: PINNED. Part of cache key; changing it invalidates baselines (D8/D9).
      - temperature: 0.0
      - self_consistency_n: 1 by default (fast iteration); 3 with majority vote on `passed`
                            inside the CI gate (D9) so the gate is not flaky. Graded scores -> median.
    """
    def __init__(self, judge_client, rubric: "Rubric | None" = None,
                 self_consistency_n: int = 1): ...
```

**Judge cache (D4 + D8):** key = `hash(judge_model_version, rubric.version, trajectory_content_hash)`,
stored in the same Postgres JSONB store as eval results. Re-scoring is the cheap operation (agent
LLM calls dominate cost), so iterating rubrics is near-free.

---

## 6. EvalRunner (orchestration)

```python
class EvalRunConfig(BaseModel):
    k: int = 1                       # D1: 1 for local iteration; CI release gate sets k=4
    max_concurrency: int = 8         # bounded rollouts
    sandbox_pool_size: int = 4       # D3: docker pool size == sandbox concurrency budget
    fail_fast: bool = False
    seed: int | None = None          # D6: controls user-sim, task selection & order ONLY (best-effort)

class EvalRunner:
    def __init__(self, *, dataset: EvalDataset, agent_factory: AgentFactory,
                 rollout: RolloutStrategy, evaluator: AbstractEvaluator,
                 sandbox_provider: SandboxProvider, config: EvalRunConfig,
                 event_bus: "EventBus | None" = None,
                 sink: "EvalReportSink | None" = None): ...

    async def run(self) -> "EvalReport": ...
```

Flow per `(task, attempt)` — each fully isolated, gathered under `asyncio.Semaphore`:

1. `sandbox = await provider.acquire(task.sandbox_spec)` (under sandbox/pool semaphore)
2. `await sandbox.reset(task.sandbox_spec.seed_state)`  (re-seeds + re-truncates git; health-checked)
3. `t0 = perf_counter(); bot = await agent_factory(sandbox)` — D2: fresh instance, toolkits bound to the sandbox's `StateBackend` (§13); record `setup_latency_ms`
4. `trajectory = await rollout.run(bot, task, sandbox)`  — record rollout `latency_ms`
5. `trajectory.final_state = await sandbox.snapshot()`
6. `result = await evaluator.evaluate(task, trajectory, sandbox)`
7. `await provider.release(sandbox)`; emit `EvalRolloutCompleted`

Aggregation in `EvalReport`:

- **pass@1** = mean over tasks of (attempt 1 passed)
- **pass^k** = fraction of tasks where ALL k attempts passed (PRIMARY reliability metric)
- per-metric mean/median; per-`tag` breakdown
- cost_usd, setup_latency_ms, latency_ms percentiles (p50/p95)
- full `Trajectory` retained per attempt (D5: store raw) for failure-mode clustering (follow-up FEAT)

---

## 7. EventBus / FEAT-176 integration (D7: extend FEAT-176)

Eval events join the FEAT-176 taxonomy (four scopes, W3C TraceContext, dual-emit fire-and-forget,
error-isolation model B): `EvalRunStarted`, `EvalRolloutStarted`, `EvalRolloutCompleted`,
`EvalRolloutFailed`, `EvalRunCompleted`.

- These are **read-only observability events**. An eval observer that could abort a run would be an
  interceptor — explicitly out of scope, consistent with the locked observability/interception split.
- Eval orchestration sits in a layer ABOVE the `ask()/conversation()` lifecycle, so these are a **new
  event group under the existing taxonomy with their own scope**, not bot-lifecycle events. To be
  formalized in the FEAT-176 spec.
- The rollout propagates `trace_context` into each agent `ask()/conversation()` call, so one eval run
  is a single distributed trace. FEAT-177 (OTel, `sdd/specs/otel-observability.spec.md`) then covers
  evals for free once its semantic layer lands (FEAT-176 plumbing is already merged on `dev`).

---

## 8. Persistence — Postgres JSONB (D8)

Same store as the judge cache (§5.1) and (once built) the shadow-mode baseline. This is operational
telemetry, kept deliberately separate from any future signed/regulatory audit store — **no
`AuditLedger` exists in the codebase today**; if one is later introduced it must stay a distinct
concern.

```
eval_runs       (run_id, dataset_name, config JSONB, started_at, finished_at, summary JSONB)
eval_results    (run_id, task_id, attempt, passed, scores JSONB, trajectory JSONB)
eval_baselines  (dataset_name, tag, run_id, pass_k, captured_at)
judge_cache     (cache_key, judge_model_version, rubric_version, verdict JSONB, created_at)
```

```python
class EvalReportSink(ABC):
    @abstractmethod
    async def persist(self, report: "EvalReport") -> str: ...   # returns run_id

class PostgresEvalSink(EvalReportSink): ...   # async via asyncpg / asyncio.to_thread as appropriate
```

---

## 9. CI integration (D9)

- `--dry-run` / `--check` flags (matches the registry-generation CI pattern).
- **Release gate runs with `k=4`** (D1). Local iteration default `k=1`.
- Gate fails if `pass^k` drops more than `regression_threshold` (X%) vs. the **latest tagged baseline**
  for that dataset (`eval_baselines`), with manual baseline override available.
- Judge runs in the gate use `self_consistency_n=3` (majority vote on `passed`) to avoid flaky gates.

---

## 10. Dataset loading

```python
class EvalDataset(BaseModel):
    name: str
    tasks: list[EvalTask]

class DatasetLoader(ABC):  # distinct from AbstractLoader (which produces List[Document])
    @abstractmethod
    async def load(self, source: str) -> EvalDataset: ...
```

Concrete: `JSONLDatasetLoader`, `YAMLDatasetLoader`, `HFDatasetLoader` (ingest SWE-bench Verified /
τ²-bench directly via `datasets.load_dataset`). Reusing `AbstractLoader` would violate its contract.

---

## 11. Resolved decisions (summary)

| # | Decision | Resolution |
|---|----------|-----------|
| D1 | pass^k vs pass@k / k default | Headline = pass^k. `k=1` local iteration; `k=4` CI release gate. |
| D2 | Agent instantiation granularity | Fresh `AbstractBot` per attempt via `agent_factory(sandbox)` (the factory binds the toolkit-under-test to the sandbox state); measure `setup_latency_ms` separately from rollout `latency_ms`. |
| D3 | Sandbox isolation | Docker = pooled + reset (health-check, evict+reprovision on dirty/failed reset; git re-truncated each reset). State/mock = fresh per attempt. |
| D4 | LLM-as-judge | Rubric-based per-criterion booleans, reference-aware, pinned judge model (≠ model-under-test, never Gemini), temp=0, persistent cache, self-consistency n=1 default / n=3 in CI gate. |
| D5 | Failure-mode clustering | Store raw trajectories now; auto-clustering is a follow-up FEAT. |
| D6 | Reproducibility / seeding | Best-effort. `seed` controls user-sim, task selection & order only. Agent-side randomness absorbed by `k>1`, not seeding. Raw trajectories enable re-scoring + audit. |
| D7 | Event taxonomy | Extend FEAT-176; new read-only event group with its own orchestration-layer scope (not bot-lifecycle events). |
| D8 | Report sink | Persist to Postgres JSONB (shared with judge cache + shadow-mode baseline). Separate from `AuditLedger`. |
| D9 | CI gate | `--dry-run`/`--check`; gate on pass^k regression vs. latest tagged baseline; k=4; judge self-consistency n=3. |
| D10 | Module placement | `parrot/eval/` in core. Promote to a workspace package only if dataset/Docker deps grow. |
| D11 | State-based path (toolkit agents) | Toolkits have **no shared backing-store abstraction** (`DatabaseToolkit`=DSN→asyncdb via `self._connection`; `JiraToolkit`=client + `credential_resolver` resolved in `_pre_execute`). The sandbox therefore owns a resettable `StateBackend` and a per-toolkit `ToolkitBinder` wires it in at those documented injection points. Scoring = subset-equality of `snapshot()` vs `expected.goal_state` (+ optional `forbidden`). The harness ships **two reference binders** (`DatabaseToolkitBinder`, `JiraToolkitBinder`) as the first benchmark target. See §13. |

---

## 12. Why this is the right base

- Five-axis split: adding a new agent type = one `AbstractEvaluator` subclass (+ maybe one
  `RolloutStrategy`). Runner, datasets, sandboxes, reporting untouched.
- `Trajectory` as single source of truth: re-score old runs with new metrics/rubrics without
  re-running agents (cheap, since LLM calls dominate cost).
- State-based + LLM-driven user simulation are first-class -> toolkit agents (enterprise clients)
  get verifiable, reliability-oriented (pass^k) evals, not string-match brittleness.
- Shared `EventBus`/trace context + Postgres sink make the offline harness and the online
  shadow-mode framework the same infrastructure viewed from two angles.

---

## 13. State-based path: `StateBasedEvaluator` + `InMemoryStateSandbox` (first benchmark target)

This is the concrete vertical slice to build first — it exercises the whole five-axis contract
without Docker, and it's where AI-Parrot's enterprise value lives (toolkit agents that mutate Jira /
databases / CRMs). It is the τ-bench-style path: **drive the agent, then diff the world it left
behind against an annotated goal state.**

### 13.0 The reality this design must respect

Verified in the codebase — there is **no common "store" object** to swap. Each toolkit reaches its
backend differently, so a single "wrap a mock store" sandbox is not possible. The injection points
that *do* exist (`parrot/tools/toolkit.py`, `parrot/bots/database/toolkits/`, JiraToolkit):

| Toolkit | Backend held as | Where the real I/O happens | Injection point |
|---------|-----------------|----------------------------|-----------------|
| `DatabaseToolkit` / `PostgresToolkit` | `self.dsn` → lazy `self._connection` (asyncdb), set in `start()` | `_execute_crud` / query helpers over `self._connection` | replace `self._connection` with a fake driver, set `self._connected = True`, skip `start()` |
| `JiraToolkit` | `self.jira` client + `self.credential_resolver` | per call, after `_pre_execute` resolves creds & client | swap `self.credential_resolver` for a static stub **and** pre-seed `self.jira` with a fake client |
| any `AbstractToolkit` | varies | inside the bound method | override `_pre_execute(tool_name, **kw)` (called by `ToolkitTool._execute` before every tool) |

The harness reconciles this heterogeneity with **one state container + per-toolkit binders** instead
of forcing every toolkit onto a single interface.

### 13.1 `StateBackend` — the resettable world

```python
class StateBackend(ABC):
    """In-memory, resettable world state owned by the sandbox (NOT by the toolkit).
    A ToolkitBinder adapts it to whatever API a given toolkit expects."""
    @abstractmethod
    async def reset(self, seed_state: dict[str, Any] | None) -> None: ...
    @abstractmethod
    async def snapshot(self) -> dict[str, Any]:
        """Deterministic, fully-ordered dump of current state — the input to scoring."""

class DictStateBackend(StateBackend):
    """Generic collection store: {collection: {entity_id: {field: value}}}.
    Exposes create/get/update/delete/list/query used by the fake drivers below.
    snapshot() returns a deep copy with collections & keys sorted (stable diffs)."""
```

`DictStateBackend` is enough for Jira issues, CRUD tables, CRM records, ticket queues — anything
modelled as keyed entities. Specialised backends (e.g. a SQL-aware one) can come later; the contract
is just `reset`/`snapshot`.

### 13.2 `ToolkitBinder` — wire the backend into the toolkit-under-test

```python
class ToolkitBinder(ABC):
    """Adapts a StateBackend to one toolkit type by hijacking its documented
    injection point. Pure, synchronous wiring — no network, no real creds."""
    @abstractmethod
    def bind(self, toolkit: "AbstractToolkit", backend: StateBackend) -> None: ...

class DatabaseToolkitBinder(ToolkitBinder):
    """Sets toolkit._connection = FakeAsyncDBConnection(backend); toolkit._connected = True.
    FakeAsyncDBConnection implements the asyncdb surface the toolkit actually calls
    (execute/query/fetch...) translated into DictStateBackend ops. start()/close() become no-ops."""

class JiraToolkitBinder(ToolkitBinder):
    """toolkit.auth_type forced to a no-network mode; toolkit.credential_resolver = StaticResolver(test_token);
    toolkit.jira = FakeJiraClient(backend) so _pre_execute's cache check passes without a real client."""
```

Binders are the only toolkit-specific code in the whole path; adding a new state-based toolkit = one
binder + a `FakeXClient`. Ship `DatabaseToolkitBinder` + `JiraToolkitBinder` first.

### 13.3 `InMemoryStateSandbox`

```python
class InMemoryStateSandbox(Sandbox):
    """kind="in_memory_state". Fresh per attempt (provisioning is ~free), so no pool, no eviction."""
    def __init__(self, backend: StateBackend, binder: ToolkitBinder):
        self._backend, self._binder = backend, binder

    async def __aenter__(self): return self
    async def __aexit__(self, *exc): ...
    async def reset(self, seed_state):  await self._backend.reset(seed_state)
    async def health_check(self):       return True          # in-memory is always healthy
    async def snapshot(self):           return await self._backend.snapshot()
    async def exec(self, cmd):          raise NotImplementedError  # state-based, not test-execution

    def bind(self, toolkit: "AbstractToolkit") -> None:      # called by the AgentFactory (§13.4)
        self._binder.bind(toolkit, self._backend)

class InMemoryStateSandboxProvider(SandboxProvider):
    """acquire() builds a fresh DictStateBackend + binder per attempt; release() is GC.
    No pool — provisioning cost ≈ 0, so sandbox concurrency == rollout concurrency."""
```

### 13.4 The `AgentFactory` does the binding (why D2 now takes the sandbox)

```python
async def make_jira_agent(sandbox: Sandbox) -> AbstractBot:
    toolkit = JiraToolkit(auth_type="basic_auth")            # constructed but NOT connected to real Jira
    sandbox.bind(toolkit)                                    # _pre_execute now resolves to the fake client
    return JiraAgent(name="eval", toolkits=[toolkit], use_llm="anthropic")
```

The runner calls `agent_factory(sandbox)` (step 3, §6) *after* `reset()`, guaranteeing every attempt
starts from the seeded state with a freshly-bound, freshly-instantiated bot.

### 13.5 `StateBasedEvaluator` — subset diff, not full equality

```python
@register_evaluator("state_based")
class StateBasedEvaluator(AbstractEvaluator):
    """τ-bench style. Compares the post-rollout snapshot against the annotated goal.

    task.expected = {
      "goal_state": {collection: {entity_id: {field: value, ...}}},  # MUST hold (subset match)
      "forbidden":  {collection: [entity_id, ...]} | None,           # MUST NOT exist (e.g. cancelled)
    }

    Subset semantics: only fields named in goal_state are asserted; unrelated state the agent
    touched is ignored. This is deliberately path-independent — many valid tool sequences can reach
    the same correct world, so we score the WORLD, not the exact tool calls. (Tool-call inspection
    over trajectory.turns is available as an optional secondary signal but is not the pass gate.)
    """
    async def evaluate(self, task, trajectory, sandbox=None) -> EvalResult:
        final = trajectory.final_state or (await sandbox.snapshot())
        score = await StateMatch().score(task, trajectory, sandbox)
        return EvalResult(task_id=task.task_id, attempt=trajectory.attempt,
                          scores=[score], passed=bool(score.passed), trajectory=trajectory)

@register_metric("state_match")
class StateMatch(Metric):
    """value = matched_assertions / total_assertions (0..1).
    passed = (all goal_state assertions hold) AND (no forbidden entity present).
    detail = {"mismatches": [...], "forbidden_present": [...]} for failure-mode clustering (D5)."""
```

`trajectory.final_state` is already populated by the runner (step 5, §6), so the evaluator normally
diffs that and never needs the live sandbox — which keeps re-scoring (D8 cache) fully offline.

### 13.6 End-to-end benchmark assembly (the "camino")

```python
dataset = await YAMLDatasetLoader().load("benchmarks/jira_triage.yaml")
# each EvalTask:
#   inputs:        {"query": "Triage and assign all unassigned bugs in PROJ to the on-call engineer"}
#   user_scenario: "...for ConversationalRollout / LLMUserSimulator (optional, multi-turn)"
#   sandbox_spec:  SandboxSpec(kind="in_memory_state",
#                              seed_state={"issues": {"PROJ-1": {"type":"bug","assignee":None}, ...}})
#   expected:      {"goal_state": {"issues": {"PROJ-1": {"assignee": "oncall"}}},
#                   "forbidden":  None}

runner = EvalRunner(
    dataset=dataset,
    agent_factory=make_jira_agent,                       # binds toolkit -> sandbox (§13.4)
    rollout=SingleTurnRollout(),                          # or ConversationalRollout(LLMUserSimulator(...))
    evaluator=StateBasedEvaluator(),
    sandbox_provider=InMemoryStateSandboxProvider(binder=JiraToolkitBinder()),
    config=EvalRunConfig(k=4, max_concurrency=8),         # k=4 → pass^k headline (D1)
    sink=PostgresEvalSink(),
)
report = await runner.run()    # report.pass_k is the reliability number; per-task mismatches stored
```

Per `(task, attempt)`: acquire fresh sandbox → `reset(seed_state)` → `agent_factory(sandbox)` (binds)
→ rollout drives the agent (its Jira tool calls mutate `DictStateBackend`) → `snapshot()` →
`StateBasedEvaluator` subset-diffs vs `goal_state` → persist. `pass^k` over all attempts is the
headline reliability metric.

### 13.7 Build order for the slice

1. `StateBackend` + `DictStateBackend` (+ snapshot determinism tests).
2. `InMemoryStateSandbox` + `InMemoryStateSandboxProvider`.
3. `DatabaseToolkitBinder` + `FakeAsyncDBConnection` (smallest real toolkit surface; unit-testable
   against `PostgresToolkit` without a DB) — proves the binding pattern.
4. `StateBasedEvaluator` + `StateMatch` metric.
5. Minimal `EvalRunner` (k, concurrency, the 7-step flow) + `JSONLDatasetLoader`.
6. `JiraToolkitBinder` + `FakeJiraClient`; first real `jira_triage` benchmark dataset.
7. `PostgresEvalSink` + `eval_runs`/`eval_results` tables; pass^k baseline capture.

Everything else (Docker/test-execution, RAG retrieval/groundedness, multi-agent trajectory) reuses
this skeleton by swapping only the `Sandbox` + `AbstractEvaluator` axes.
