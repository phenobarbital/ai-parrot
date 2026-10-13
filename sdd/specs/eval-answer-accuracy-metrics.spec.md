---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot, docs]
tags: [eval, accuracy, llm-judge, groundedness, regression-gate]
---

# Feature Specification: Answer-Accuracy Metrics for the Evaluation Harness

**Feature ID**: FEAT-652
**Date**: 2026-10-12
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x (additive to `parrot.eval`, FEAT-217 already on `dev`)

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot.eval` (FEAT-217) is the only agent-agnostic evaluation harness in ai-parrot. It
already produces the headline reliability number (`pass^k`), retains raw trajectories and
persists runs to Postgres — but it can only score **world state** (`StateMatch` against a
`goal_state`). Nothing in the harness scores the **text an agent answers with**, so every
conversational, RAG or Q&A agent is still verified by hand or with brittle string asserts.

Four concrete gaps, all verified on `dev` @ `77f16748e`:

1. `SingleTurnRollout.run` / `ConversationalRollout.run` (`eval/rollout.py:220-247`,
   `:315-355`) keep only the response text and latency. `AIMessage.usage`,
   `AIMessage.tool_calls`, `AIMessage.model` and `AIMessage.metadata` never reach the
   `Trajectory`, so token accounting, offline groundedness and guardrail-flag analysis
   are impossible from a persisted run.
2. The only `Metric` is `state_match`. There is no exact-match, containment, token-F1
   or any other reference-based metric over `trajectory.final_output`, and no evaluator
   that combines several metrics.
3. The deterministic groundedness scorer (FEAT-398, `parrot.security.groundedness`) only
   runs online as an output guardrail; it cannot be applied offline to a `Trajectory`.
4. The LLM-as-judge design was decided in FEAT-217 (D4) but deferred; the `judge_cache`
   table is created by `PostgresEvalSink._SCHEMA_DDL` and never used. Likewise the
   `eval_baselines` table exists with no regression logic behind it.

### Goals

- **Complete trajectories**: every rollout records tokens, per-turn tool calls, the model
  that answered and the response metadata (guardrail reports included), with defaults
  that keep mock bots and the existing runner working unchanged.
- **Deterministic text metrics** (`exact_match`, `contains`, `token_f1`) plus a
  `CompositeEvaluator` that combines any registered metrics with required/threshold
  semantics.
- **Offline groundedness** via a `GroundednessMetric` that reuses `GroundednessScorer`
  and `EvidenceIndex` without modifying `parrot.security.groundedness`.
- **Rubric-based LLM judge** (`LLMJudgeMetric`) honouring FEAT-217 D4: per-criterion
  booleans, a pinned judge model that must differ from the model under test,
  temperature 0, `n_samples` self-consistency (1 local / 3 CI), and a `JudgeCache`
  backed by the existing `judge_cache` table.
- **Regression gate** on `pass^k` against the existing `eval_baselines` table, evaluated
  per tag independently — an improvement in one tag never offsets a regression in
  another (same rule as `knowledge/retrieval/eval/metrics.py::check_regression`).

### Non-Goals (explicitly out of scope)

- A `parrot eval` CLI or CI wiring (FEAT-217 D9 — still a follow-up).
- `Trajectory.cost_usd` population (needs `parrot.observability.cost.CostCalculator`;
  follow-up).
- Online shadow mode, scoring of production traffic, or joining `bot_feedback` rows to
  stored turns.
- Semantic hallucination detection without an LLM judge; `GroundednessMetric` inherits
  every documented limit of FEAT-398 (hard-data atoms only).
- Modifying `clients/base.py`, `security/groundedness/*`, `knowledge/retrieval/eval/*`,
  or the `_SCHEMA_DDL` of `eval/sink.py` (both tables already have the columns needed).
- `RetrievalEvaluator` / `TrajectoryEvaluator` / `RoutingEvaluator` (still reserved).

---

## 2. Architectural Design

### Overview

Everything is additive inside `packages/ai-parrot/src/parrot/eval/`. The harness's
polymorphic point stays `Metric` / `AbstractEvaluator`; this feature adds metrics and one
evaluator to the registry, two small sub-modules (`judge/`, `regression.py`) and
enriches the data captured by the two existing rollouts.

Scoring is always computed from `Trajectory` alone (final output, turns, tool calls,
metadata), never from a live sandbox, so every new metric re-scores a persisted run
offline (FEAT-217 D5 preserved).

### Component Diagram

```
Rollout (Single/Conversational)  ──enriches──►  Trajectory{final_output, turns[].tool_calls,
        │                                                   tokens, model, response_metadata}
        │                                                            │
        ▼                                                            ▼
EvalRunner ──► CompositeEvaluator ──┬─► ExactMatch / ContainsMatch / TokenF1   (text.py)
                                    ├─► GroundednessMetric ──► EvidenceIndex + GroundednessScorer (FEAT-398)
                                    └─► LLMJudgeMetric ──► JudgeCache ──► judge_cache (Postgres)
                                                       └──► AbstractClient.ask(structured_output=JudgeVerdict)
           │
           ▼
      EvalReport ──► check_regression(report, BaselineStore) ──► eval_baselines (Postgres)
                                         └──► RegressionVerdict
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `Trajectory` / `TurnRecord` / `ToolCallRecord` / `TokenUsage` (`eval/models.py`) | extends (additive fields) | `model`, `response_metadata` added with defaults |
| `SingleTurnRollout.run`, `ConversationalRollout.run` (`eval/rollout.py`) | modifies | populate tokens/tool_calls/model/metadata from the `AIMessage` |
| `Metric`, `AbstractEvaluator` (`eval/evaluators/base.py`) | subclasses | all new metrics/evaluator |
| `register_metric`, `register_evaluator` (`eval/registry.py`) | registers | names: `exact_match`, `contains`, `token_f1`, `groundedness`, `llm_judge`, `composite` |
| `AIMessage` (`models/responses.py`) | reads | `.content`, `.usage`, `.tool_calls`, `.model`, `.metadata`, `.structured_output` |
| `CompletionUsage`, `ToolCall` (`models/basic.py`) | maps | → `TokenUsage`, `ToolCallRecord` |
| `EvidenceIndex`, `GroundednessScorer`, `GroundednessPolicy` (`security/groundedness`) | uses | read-only reuse |
| `AbstractClient.ask()` (`clients/base.py:1829`) | uses | judge call with `temperature=0.0`, `structured_output=JudgeVerdict` |
| `PostgresEvalSink._SCHEMA_DDL`, `_resolve_dsn` (`eval/sink.py`) | reuses | `judge_cache` / `eval_baselines` tables and `EVAL_DB_DSN` resolution |
| `EvalReport` (`eval/runner.py:69`) | reads | `pass_k`, `per_tag`, `dataset_name`, `run_id` for the regression gate |

### Data Models

```python
# parrot/eval/models.py — additive fields on Trajectory (defaults keep runner.model_copy() working)
class Trajectory(BaseModel):
    ...  # existing fields unchanged
    model: str | None = None                                      # AIMessage.model of the last agent turn
    response_metadata: dict[str, Any] = Field(default_factory=dict)  # AIMessage.metadata of the last agent turn

# parrot/eval/judge/models.py
class JudgeCriterion(BaseModel):
    name: str
    question: str                      # yes/no question the judge answers

class Rubric(BaseModel):
    name: str
    version: str
    criteria: list[JudgeCriterion]
    pass_threshold: float = 1.0        # fraction of criteria that must be True

class JudgeVerdict(BaseModel):
    criteria: dict[str, bool]          # criterion name → verdict
    rationale: str = ""

# parrot/eval/regression.py
class RegressionVerdict(BaseModel):
    dataset_name: str
    tolerance: float
    overall_baseline: float | None
    overall_candidate: float | None
    regressed_tags: list[str]          # "" denotes the overall pass^k
    passed: bool
```

### New Public Interfaces

```python
from parrot.eval import (
    ExactMatch, ContainsMatch, TokenF1, normalize_text,           # evaluators/text.py
    CompositeEvaluator,                                            # evaluators/composite.py
    GroundednessMetric,                                            # evaluators/groundedness.py
    JudgeCriterion, Rubric, JudgeVerdict, judge_cache_key,         # judge/models.py
    JudgeCache, InMemoryJudgeCache, PostgresJudgeCache,            # judge/cache.py
    LLMJudgeMetric,                                                # evaluators/llm_judge.py
    BaselineStore, InMemoryBaselineStore, PostgresBaselineStore,
    RegressionVerdict, check_regression,                           # regression.py
)
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Trajectory enrichment | yes | field names, helper signatures and `getattr`-tolerant extraction fixed below | — |
| M2: Text metrics + composite | yes | normalization rules, `expected` keys, pass semantics fixed below | — |
| M3: GroundednessMetric | yes | reconstruction of `ToolCall` from `ToolCallRecord`, pass rule fixed below | — |
| M4: Judge models + cache | yes | cache-key recipe, table columns and DSN resolution fixed below | — |
| M5: LLMJudgeMetric | no | prompt wording and the parse-fallback for non-structured clients are judgement calls | prompt design |
| M6: Regression gate | yes | per-tag rule and store contract fixed below | — |
| M7: Public surface + docs + e2e | yes | export list and benchmark dataset shape fixed below | — |

### Module 1: Trajectory enrichment
- **Path**: `packages/ai-parrot/src/parrot/eval/models.py` (MODIFY), `packages/ai-parrot/src/parrot/eval/rollout.py` (MODIFY)
- **Responsibility**: carry `AIMessage` usage, tool calls, model and metadata into the `Trajectory`
  produced by both rollouts. Extraction is `getattr`-tolerant so mock bots returning plain
  strings or objects without `usage` still work (defaults).
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # parrot/eval/models.py  (modifies Trajectory, verified: eval/models.py:96-128)
  class Trajectory(BaseModel):
      model: str | None = None
      """Model identifier of the last agent response (``AIMessage.model``), if known."""
      response_metadata: dict[str, Any] = Field(default_factory=dict)
      """``AIMessage.metadata`` of the last agent response (guardrail reports, routing trace, …)."""

  # parrot/eval/rollout.py  (new helpers next to _extract_text, verified: eval/rollout.py:384)
  def _usage_from_response(response: Any) -> TokenUsage:
      """Map ``response.usage`` (CompletionUsage: prompt_tokens/completion_tokens/total_tokens) to TokenUsage; zeros when absent."""
  def _tool_calls_from_response(response: Any) -> list[ToolCallRecord]:
      """Map ``response.tool_calls`` (list[ToolCall]) to ToolCallRecord; ``execution_time`` seconds → ``latency_ms``; [] when absent."""
  def _metadata_from_response(response: Any) -> tuple[str | None, dict[str, Any]]:
      """Return ``(response.model, dict(response.metadata))``; ``(None, {})`` when absent."""
  # SingleTurnRollout.run: TurnRecord(role="agent", tool_calls=_tool_calls_from_response(response)); Trajectory(tokens=..., model=..., response_metadata=...)
  # ConversationalRollout.run: per agent turn tool_calls; tokens accumulated across turns (sum of prompt/completion/total); model/metadata from the last agent turn
  ```

### Module 2: Text metrics + CompositeEvaluator
- **Path**: `packages/ai-parrot/src/parrot/eval/evaluators/text.py` (CREATE), `packages/ai-parrot/src/parrot/eval/evaluators/composite.py` (CREATE)
- **Responsibility**: reference-based scoring of `trajectory.final_output` against `task.expected`,
  and an evaluator that aggregates any metrics.
- **Depends on**: existing `Metric`, `AbstractEvaluator`, registry.
- **Interface Skeleton**:
  ```python
  # parrot/eval/evaluators/text.py  (new)
  def normalize_text(text: str, *, casefold: bool = True, strip_punct: bool = True) -> str:
      """Casefold, strip ASCII punctuation, collapse whitespace. Used by every text metric."""

  @register_metric("exact_match")            # register_metric verified: eval/registry.py:103
  class ExactMatch(Metric):                  # Metric verified: eval/evaluators/base.py:24
      """1.0 iff normalized final_output equals any of ``expected["answer"]`` (str | list[str]); else 0.0. passed == (value == 1.0)."""
      name = "exact_match"
      def __init__(self, *, casefold: bool = True, strip_punct: bool = True) -> None: ...
      async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore: ...

  @register_metric("contains")
  class ContainsMatch(Metric):
      """Fraction of ``expected["must_contain"]`` (list[str], normalized substrings, or regex when ``regex=True``) found in final_output; passed by ``mode`` ("all" | "any")."""
      name = "contains"
      def __init__(self, *, mode: Literal["all", "any"] = "all", regex: bool = False) -> None: ...
      async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore: ...

  @register_metric("token_f1")
  class TokenF1(Metric):
      """SQuAD-style token F1 between normalized final_output and ``expected["answer"]`` (max over list); passed == value >= threshold."""
      name = "token_f1"
      def __init__(self, *, threshold: float = 0.5) -> None: ...
      async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore: ...

  # parrot/eval/evaluators/composite.py  (new)
  @register_evaluator("composite")           # register_evaluator verified: eval/registry.py:36
  class CompositeEvaluator(AbstractEvaluator):   # AbstractEvaluator verified: eval/evaluators/base.py:64
      """Run every metric; passed = all(required metrics passed) and weighted mean of values >= threshold.
      A metric whose ``passed`` is None contributes its value only. Missing ``expected`` keys are a metric concern, never an evaluator crash."""
      def __init__(self, metrics: Sequence[Metric], *, required: Collection[str] = (), threshold: float = 1.0,
                   weights: Mapping[str, float] | None = None) -> None: ...
      async def evaluate(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> EvalResult: ...
  ```

### Module 3: GroundednessMetric
- **Path**: `packages/ai-parrot/src/parrot/eval/evaluators/groundedness.py` (CREATE)
- **Responsibility**: apply FEAT-398's deterministic scorer offline to a `Trajectory`.
- **Depends on**: Module 1 (needs `TurnRecord.tool_calls` populated by the rollout); `parrot.security.groundedness` (read-only).
- **Interface Skeleton**:
  ```python
  # parrot/eval/evaluators/groundedness.py  (new)
  @register_metric("groundedness")
  class GroundednessMetric(Metric):
      """Rebuild list[ToolCall] from every ``trajectory.turns[*].tool_calls`` (ToolCall verified: models/basic.py:23),
      build ``EvidenceIndex.from_tool_calls(tool_calls, policy, user_prompt=<task question>)`` (verified: security/groundedness/evidence.py:61),
      score ``GroundednessScorer(policy).score(final_output, evidence)`` (verified: scorer.py:74).
      value = report.score; passed = score >= min_score and (not fail_on_contradicted or not report.contradicted);
      detail = report.model_dump() plus {"no_evidence", "no_factual_content"} echoed at top level.
      ``no_evidence`` or ``no_factual_content`` → value 1.0, passed True (neutral, same semantics as the guardrail)."""
      name = "groundedness"
      def __init__(self, policy: GroundednessPolicy | None = None, *, min_score: float = 0.8, fail_on_contradicted: bool = True) -> None: ...
      async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore: ...
  ```

### Module 4: Judge models + cache
- **Path**: `packages/ai-parrot/src/parrot/eval/judge/__init__.py`, `judge/models.py`, `judge/cache.py` (CREATE)
- **Responsibility**: rubric/verdict data models, deterministic cache key, cache backends.
- **Depends on**: `eval/sink.py` DDL (table `judge_cache`: `cache_key TEXT UNIQUE`, `judge_model_version`, `rubric_version`, `verdict JSONB`, verified `sink.py:89-97`) and its DSN rule (`EVAL_DB_DSN`, `sink.py:122-130`).
- **Interface Skeleton**:
  ```python
  # parrot/eval/judge/models.py  (new) — JudgeCriterion / Rubric / JudgeVerdict as in §2 Data Models
  def judge_cache_key(*, judge_model: str, rubric: Rubric, question: str, expected: Any, answer: str) -> str:
      """sha256 hex over a canonical JSON of (judge_model, rubric.name, rubric.version, criteria questions, question, expected, answer).
      Stable across processes; any change in rubric version or judge model yields a different key."""

  # parrot/eval/judge/cache.py  (new)
  class JudgeCache(ABC):
      """Async key→verdict store."""
      @abstractmethod
      async def get(self, key: str) -> JudgeVerdict | None: ...
      @abstractmethod
      async def set(self, key: str, verdict: JudgeVerdict, *, judge_model_version: str, rubric_version: str) -> None: ...

  class InMemoryJudgeCache(JudgeCache):
      """Dict-backed; for tests and local runs."""

  class PostgresJudgeCache(JudgeCache):
      """asyncpg against ``judge_cache``; ``dsn`` falls back to ``EVAL_DB_DSN`` exactly like PostgresEvalSink._resolve_dsn.
      ``set`` is an UPSERT on cache_key (ON CONFLICT (cache_key) DO UPDATE); schema ensured with PostgresEvalSink's ``_SCHEMA_DDL``."""
      def __init__(self, dsn: str | None = None) -> None: ...
  ```

### Module 5: LLMJudgeMetric
- **Path**: `packages/ai-parrot/src/parrot/eval/evaluators/llm_judge.py` (CREATE)
- **Responsibility**: rubric-based LLM judging with caching and self-consistency.
- **Depends on**: Module 4; `AbstractClient.ask()` (verified `clients/base.py:1829`: `ask(prompt, model, max_tokens=None, temperature=0.7, ..., structured_output=Union[type, StructuredOutputConfig, None])`).
- **Interface Skeleton**:
  ```python
  # parrot/eval/evaluators/llm_judge.py  (new)
  @register_metric("llm_judge")
  class LLMJudgeMetric(Metric):
      """For each score(): key = judge_cache_key(...); cache hit → no LLM call (detail["cached"]=True).
      Otherwise call ``client.ask(prompt, model=judge_model, temperature=0.0, structured_output=JudgeVerdict)`` ``n_samples`` times
      (concurrently via asyncio.gather), majority-vote each criterion, store the merged verdict.
      Verdict extraction: ``response.structured_output`` when it is a JudgeVerdict/dict, else JSON parsed from ``_extract_text(response)``;
      unparseable → value 0.0, passed False, detail["error"] set (never raises).
      value = fraction of criteria True; passed = value >= rubric.pass_threshold.
      Raises ValueError at construction when ``judge_model == model_under_test`` (FEAT-217 D4: judge ≠ model under test)."""
      name = "llm_judge"
      def __init__(self, client: AbstractClient, *, judge_model: str, rubric: Rubric, cache: JudgeCache | None = None,
                   n_samples: int = 1, model_under_test: str | None = None, max_tokens: int = 1024) -> None: ...
      def build_prompt(self, task: EvalTask, answer: str) -> str:
          """Render question, expected (if any), answer and the rubric's yes/no questions; demand JSON {criteria: {name: bool}, rationale}."""
      async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore: ...
  ```

### Module 6: Regression gate
- **Path**: `packages/ai-parrot/src/parrot/eval/regression.py` (CREATE)
- **Responsibility**: compare an `EvalReport` against stored baselines, per tag, independently.
- **Depends on**: `EvalReport` (verified `eval/runner.py:69`: `run_id`, `dataset_name`, `pass_k`, `per_tag`); `eval_baselines` DDL (`sink.py:80-87`: `dataset_name`, `tag`, `run_id`, `pass_k`, `captured_at`).
- **Interface Skeleton**:
  ```python
  # parrot/eval/regression.py  (new)
  class BaselineStore(ABC):
      @abstractmethod
      async def get_baseline(self, dataset_name: str, tag: str = "") -> float | None:
          """Latest recorded pass^k for (dataset, tag); ``""`` is the overall figure. None when never recorded."""
      @abstractmethod
      async def record(self, report: EvalReport) -> None:
          """Record report.pass_k under tag "" and every report.per_tag entry under its tag."""

  class InMemoryBaselineStore(BaselineStore): ...
  class PostgresBaselineStore(BaselineStore):
      """asyncpg against ``eval_baselines``; latest row by captured_at; dsn fallback EVAL_DB_DSN as in PostgresEvalSink."""
      def __init__(self, dsn: str | None = None) -> None: ...

  async def check_regression(report: EvalReport, store: BaselineStore, *, tolerance: float = 0.05) -> RegressionVerdict:
      """A tag regresses iff baseline - candidate > tolerance; tags without a baseline never regress;
      overall ("") is checked like any tag; passed = no regressed tags. Never records — recording is the caller's explicit choice."""
  ```

### Module 7: Public surface, docs, reference benchmark
- **Path**: `packages/ai-parrot/src/parrot/eval/__init__.py` (MODIFY), `docs/eval/answer-accuracy-metrics.md` (CREATE), `packages/ai-parrot/tests/eval/benchmarks/qa_reference.jsonl` (CREATE), `packages/ai-parrot/tests/eval/test_qa_benchmark_e2e.py` (CREATE)
- **Responsibility**: export every new name from `parrot.eval`, document usage, and prove the
  whole path end-to-end with a hermetic Q&A benchmark (mock bot, `NoopSandboxProvider`,
  `CompositeEvaluator` of text metrics + `GroundednessMetric` + `LLMJudgeMetric` with a fake
  client and `InMemoryJudgeCache`, then `check_regression` against `InMemoryBaselineStore`).
- **Depends on**: Modules 1–6 (imports all of them; the only module touching `__init__.py`).
- **Interface Skeleton**:
  ```python
  # parrot/eval/__init__.py  (modifies: add imports after line 76 block and names to __all__ before `"JiraToolkitBinder",` verified: eval/__init__.py:153)
  from parrot.eval.evaluators.text import ContainsMatch, ExactMatch, TokenF1, normalize_text
  from parrot.eval.evaluators.composite import CompositeEvaluator
  from parrot.eval.evaluators.groundedness import GroundednessMetric
  from parrot.eval.evaluators.llm_judge import LLMJudgeMetric
  from parrot.eval.judge import InMemoryJudgeCache, JudgeCache, JudgeCriterion, JudgeVerdict, PostgresJudgeCache, Rubric, judge_cache_key
  from parrot.eval.regression import BaselineStore, InMemoryBaselineStore, PostgresBaselineStore, RegressionVerdict, check_regression
  ```
  `qa_reference.jsonl`: 5 `EvalTask` rows with `inputs.query`, `expected.answer`
  (str or list), `expected.must_contain`, and `tags` (`["qa"]`, `["numeric"]`).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_single_turn_copies_usage_tool_calls_model_metadata` | M1 | `AIMessage`-shaped fake → `tokens.total`, `turns[0].tool_calls`, `model`, `response_metadata` populated |
| `test_single_turn_defaults_without_usage` | M1 | plain-string response keeps zeros/empties (existing mock bots still pass) |
| `test_conversational_accumulates_tokens` | M1 | 3 agent turns → tokens summed; model/metadata from last turn |
| `test_exact_match_normalizes_and_accepts_list` | M2 | case/punctuation/whitespace; `answer: ["Paris", "París"]` |
| `test_contains_all_vs_any_and_regex` | M2 | fraction value, `mode` semantics, regex flag |
| `test_token_f1_threshold` | M2 | known F1 values; `passed` follows threshold |
| `test_text_metrics_missing_expected` | M2 | no `expected` → value 0.0, passed False, detail reason (no exception) |
| `test_composite_required_overrides_threshold` | M2 | required metric fails ⇒ passed False even if weighted mean ≥ threshold |
| `test_composite_weights_and_passed_none` | M2 | weighted mean; `passed=None` metrics only contribute value |
| `test_groundedness_metric_matches_guardrail_scorer` | M3 | same text + tool calls → same `score` as `GroundednessScorer` direct call |
| `test_groundedness_metric_no_evidence_neutral` | M3 | no tool calls → value 1.0, passed True, `detail["no_evidence"]` |
| `test_groundedness_metric_contradicted_fails` | M3 | transposed digit → passed False with `fail_on_contradicted` |
| `test_judge_cache_key_stable_and_sensitive` | M4 | same inputs → same key; rubric version / judge model change → different key |
| `test_inmemory_judge_cache_roundtrip` | M4 | get/set |
| `test_postgres_judge_cache_upsert` | M4 | skipped unless `EVAL_DB_DSN`; upsert on conflict |
| `test_llm_judge_calls_client_once_then_cached` | M5 | fake client call counter: 2 scores → 1 call; `detail["cached"]` |
| `test_llm_judge_majority_vote` | M5 | `n_samples=3`, fake returns T/T/F → True |
| `test_llm_judge_rejects_same_model` | M5 | `ValueError` when judge == model under test |
| `test_llm_judge_unparseable_output` | M5 | value 0.0, passed False, `detail["error"]` |
| `test_llm_judge_parses_text_json_fallback` | M5 | client without `structured_output` returns JSON text → parsed |
| `test_check_regression_per_tag_independent` | M6 | tag A improves, tag B regresses > tolerance → `regressed_tags == ["B"]`, passed False |
| `test_check_regression_no_baseline_passes` | M6 | empty store → passed True, `overall_baseline None` |
| `test_baseline_store_record_overall_and_tags` | M6 | `record()` writes `""` + each tag |
| `test_postgres_baseline_store` | M6 | skipped unless `EVAL_DB_DSN` |
| `test_public_exports` | M7 | `from parrot.eval import …` for every new name |

### Integration Tests
| Test | Description |
|---|---|
| `test_qa_benchmark_e2e` | `qa_reference.jsonl` + mock bot + `CompositeEvaluator(ExactMatch, ContainsMatch, GroundednessMetric, LLMJudgeMetric(fake client))` → `EvalReport.pass_k`, `per_tag`; then `record()` + `check_regression()` passes, and a degraded second report fails the gate |

### Test Data / Fixtures
```python
@pytest.fixture
def ai_message_like():
    """Minimal object exposing content/usage/tool_calls/model/metadata like AIMessage."""
    from parrot.models.basic import CompletionUsage, ToolCall
    class _Msg:
        content = "Revenue was $1,243,500 in Q3."
        model = "fake:judge-free"
        usage = CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        tool_calls = [ToolCall(id="t1", name="get_revenue", arguments={}, result={"revenue": 1243500}, execution_time=0.02)]
        metadata = {"guardrails": {}}
    return _Msg()

@pytest.fixture
def fake_judge_client():
    """Counts calls; returns an object whose .structured_output is a JudgeVerdict (or JSON text when text_mode=True)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `Trajectory` gains `model` and `response_metadata` with defaults; `EvalRunner._run_attempt`'s `model_copy(update=...)` calls work unchanged; existing `tests/eval/` still pass.
- [ ] Both rollouts populate `tokens`, per-turn `tool_calls`, `model` and `response_metadata` from an `AIMessage`-shaped response, and keep defaults for responses without those attributes.
- [ ] `exact_match`, `contains`, `token_f1`, `groundedness`, `llm_judge` resolve via `get_metric()`; `composite` via `get_evaluator()`.
- [ ] `CompositeEvaluator.passed` is False whenever any `required` metric has `passed is False`, regardless of the weighted mean.
- [ ] `GroundednessMetric` yields the same `score` as `GroundednessScorer.score()` for identical text/evidence, and is neutral (1.0 / True) on `no_evidence` or `no_factual_content`.
- [ ] `LLMJudgeMetric` performs exactly one LLM call per unique cache key, applies majority vote for `n_samples > 1`, raises `ValueError` when `judge_model == model_under_test`, and never raises from `score()` on bad judge output.
- [ ] `PostgresJudgeCache` and `PostgresBaselineStore` use the existing DDL from `eval/sink.py` and the `EVAL_DB_DSN` fallback; their tests skip without a DSN.
- [ ] `check_regression` flags a tag iff `baseline - candidate > tolerance`, independently per tag; passes with no baseline; never writes.
- [ ] `from parrot.eval import ExactMatch, ContainsMatch, TokenF1, CompositeEvaluator, GroundednessMetric, LLMJudgeMetric, Rubric, JudgeVerdict, InMemoryJudgeCache, PostgresJudgeCache, InMemoryBaselineStore, PostgresBaselineStore, check_regression` resolves.
- [ ] `docs/eval/answer-accuracy-metrics.md` documents dataset shape (`expected.answer` / `must_contain`), each metric's pass rule, judge configuration (model pinning, `n_samples`, cache) and the regression gate.
- [ ] `test_qa_benchmark_e2e` runs hermetically (no DB, no real LLM) and produces `pass_k` plus a `RegressionVerdict`.
- [ ] No file outside `packages/ai-parrot/src/parrot/eval/`, `packages/ai-parrot/tests/eval/` and `docs/eval/` is modified.
- [ ] All tests pass: `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/eval -q`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified 2026-10-12 against `dev` @ `77f16748e`.

### Verified Imports
```python
from parrot.eval.models import EvalDataset, EvalResult, EvalTask, MetricScore, TokenUsage, ToolCallRecord, Trajectory, TurnRecord
    # verified: eval/models.py:166,148,18,131,82,46,96,64
from parrot.eval.evaluators.base import AbstractEvaluator, Metric         # verified: eval/evaluators/base.py:64,24
from parrot.eval.registry import get_evaluator, get_metric, register_evaluator, register_metric
    # verified: eval/registry.py:69,136,36,103
from parrot.eval.sandbox.base import NoopSandboxProvider, Sandbox, SandboxSpec  # verified: eval/__init__.py:29-37
from parrot.eval.runner import EvalReport, EvalRunConfig, EvalRunner      # verified: eval/runner.py:69,43,116
from parrot.eval.sink import PostgresEvalSink, _SCHEMA_DDL                # verified: eval/sink.py:100,60
from parrot.eval.rollout import SingleTurnRollout, ConversationalRollout, _extract_question, _extract_text
    # verified: eval/rollout.py:190,252,362,384
from parrot.models.basic import CompletionUsage, ToolCall                 # verified: models/basic.py:48,23
from parrot.models.responses import AIMessage                             # verified: models/responses.py:93
from parrot.security.groundedness import EvidenceIndex, GroundednessPolicy, GroundednessReport, GroundednessScorer
    # verified: security/groundedness/__init__.py:22-32 (__all__)
from parrot.clients.base import AbstractClient                            # verified: clients/base.py (class), ask() at :1829
from parrot.models.outputs import StructuredOutputConfig                  # verified: models/outputs.py:59
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/eval/models.py
class ToolCallRecord(BaseModel):            # line 46 — name, arguments, result, error, latency_ms
class TurnRecord(BaseModel):                # line 64 — role, content, tool_calls: list[ToolCallRecord], timestamp
class TokenUsage(BaseModel):                # line 82 — prompt, completion, total (ints, default 0)
class Trajectory(BaseModel):                # line 96 — model_config extra="allow"; task_id, attempt, turns, final_output,
                                            #   final_state, tokens, cost_usd, setup_latency_ms, latency_ms, error, trace_context (:128)
class MetricScore(BaseModel):               # line 131 — name, value, passed: bool | None, detail: dict
class EvalResult(BaseModel):                # line 148 — task_id, attempt, scores, passed, trajectory

# packages/ai-parrot/src/parrot/eval/evaluators/base.py
class Metric(ABC):                          # line 24 — name: str; async def score(self, task, trajectory, sandbox=None) -> MetricScore
class AbstractEvaluator(ABC):               # line 64 — async def evaluate(self, task, trajectory, sandbox=None) -> EvalResult

# packages/ai-parrot/src/parrot/eval/rollout.py
class SingleTurnRollout(RolloutStrategy):   # line 190; run(): `response = await bot.ask(question)` :220, `return Trajectory(` :229, `final_output=text,` :233
class ConversationalRollout(RolloutStrategy):  # line 252; `response = await bot.conversation(` :315, `final_output=final_output,` :352
def _extract_question(task: EvalTask) -> str:        # line 362
def _extract_text(response: Any) -> str | None:      # line 384 — reads .content / .response / .text

# packages/ai-parrot/src/parrot/eval/runner.py
class EvalReport(BaseModel):                # line 69 — run_id, dataset_name, config, pass_k, pass_at_1, results, per_tag: dict[str, float],
                                            #   p50/p95 latency|setup|cost, total_tasks, total_attempts, errors (:108)
class EvalRunner:                           # line 116; _run_attempt :239 uses trajectory.model_copy(update={...}); _aggregate :362

# packages/ai-parrot/src/parrot/eval/sink.py
_SCHEMA_DDL                                 # line 60 — eval_runs :61, eval_results :70, eval_baselines :80 (dataset_name, tag, run_id, pass_k, captured_at),
                                            #   judge_cache :89 (cache_key UNIQUE, judge_model_version, rubric_version, verdict JSONB, created_at)
class PostgresEvalSink(EvalReportSink):     # line 100; _resolve_dsn() :122 reads navconfig config("EVAL_DB_DSN"); asyncpg.connect :181

# packages/ai-parrot/src/parrot/models/basic.py
class ToolCall(BaseModel):                  # line 23 — id, name, arguments, result, error, execution_time (seconds)
class CompletionUsage(BaseModel):           # line 48 — prompt_tokens :76, completion_tokens :79, total_tokens :82 (+ input/output aliases)

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                 # line 93 — model :140, usage: CompletionUsage :143, tool_calls: List[ToolCall] :157,
                                            #   structured_output :190, metadata: Dict[str, Any] :194, content property :225

# packages/ai-parrot/src/parrot/security/groundedness/
class EvidenceIndex:                        # evidence.py:31; classmethod from_tool_calls(tool_calls: list[ToolCall], policy, user_prompt=None) :61
class GroundednessScorer:                   # scorer.py:56; __init__(policy=None) :66; score(answer_text: str, evidence: EvidenceIndex) -> GroundednessReport :74
class GroundednessPolicy(BaseModel):        # policy.py:16
class GroundednessReport(BaseModel):        # policy.py:58 — score :81, contradicted :84, unsupported :85, no_factual_content :86, no_evidence :87

# packages/ai-parrot/src/parrot/clients/base.py
async def ask(self, prompt: str, model: str, max_tokens=None, temperature: float = 0.7, files=None, system_prompt=None,
              history=None, structured_output: Union[type, StructuredOutputConfig, None] = None, ...) -> MessageResponse   # line 1829
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_usage_from_response` | `AIMessage.usage` (`CompletionUsage`) | attribute read | `responses.py:143`, `basic.py:76-82` |
| `_tool_calls_from_response` | `AIMessage.tool_calls` (`ToolCall`) | attribute read | `responses.py:157`, `basic.py:23` |
| `GroundednessMetric` | `EvidenceIndex.from_tool_calls`, `GroundednessScorer.score` | method calls | `evidence.py:61`, `scorer.py:74` |
| `LLMJudgeMetric` | `AbstractClient.ask(structured_output=JudgeVerdict, temperature=0.0)` | method call | `clients/base.py:1829` |
| `PostgresJudgeCache` / `PostgresBaselineStore` | `_SCHEMA_DDL`, `EVAL_DB_DSN` | reuse | `sink.py:60`, `:122-130` |
| `check_regression` | `EvalReport.pass_k` / `.per_tag` | attribute read | `runner.py:69-99` |
| new metrics | registry | `@register_metric` / `@register_evaluator` | `registry.py:103`, `:36` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.eval.judge`~~, ~~`parrot.eval.regression`~~, ~~`parrot/eval/evaluators/{text,composite,groundedness,llm_judge}.py`~~ — created by this feature.
- ~~`Trajectory.model`~~, ~~`Trajectory.response_metadata`~~ — added by Module 1.
- ~~`GroundednessReport.passed`~~ — the report has `score` and atom lists only.
- ~~`EvalReport.baseline`~~, ~~`EvalRunner.check_regression`~~ — the gate is a standalone function.
- ~~`AbstractClient.completion()`~~ — the contract is `ask()` / `ask_stream()`.
- ~~`parrot.eval.CostCalculator`~~ — cost lives in `parrot.observability.cost`; out of scope.
- ~~`knowledge.retrieval.eval.metrics.check_regression` reuse~~ — typed on `QueryClass`; the eval gate has its own function (same rule, different key type).
- ~~`AIMessage.response` / `.text`~~ — text is the `content` property (`_extract_text` already handles the fallbacks).

### Edit Sites (Blueprint Anchors)

Verified against: `77f16748e`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/eval/models.py` | MODIFY | `    trace_context: dict[str, str] \| None = None` | `models.py:128` | 1 |
| `packages/ai-parrot/src/parrot/eval/rollout.py` | MODIFY | `            response = await bot.ask(question)` | `rollout.py:220` | 1 |
| `packages/ai-parrot/src/parrot/eval/rollout.py` | MODIFY | `                final_output=text,` | `rollout.py:233` | 1 |
| `packages/ai-parrot/src/parrot/eval/rollout.py` | MODIFY | `                response = await bot.conversation(` | `rollout.py:315` | 1 |
| `packages/ai-parrot/src/parrot/eval/rollout.py` | MODIFY | `            final_output=final_output,` | `rollout.py:352` | 1 |
| `packages/ai-parrot/src/parrot/eval/rollout.py` | MODIFY | `def _extract_text(response: Any) -> str \| None:` | `rollout.py:384` | 1 |
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | `from parrot.eval.evaluators.state_based import StateBasedEvaluator, StateMatch` | `__init__.py:75` | 1 |
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | `    "JiraToolkitBinder",` | `__init__.py:153` | 1 |
| `packages/ai-parrot/src/parrot/eval/evaluators/text.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/eval/evaluators/composite.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/eval/evaluators/groundedness.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/eval/evaluators/llm_judge.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/eval/judge/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/eval/judge/models.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/eval/judge/cache.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/eval/regression.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/eval/test_rollout.py` | MODIFY | `async def test_llm_user_simulator_returns_none_on_error():` | `test_rollout.py:123` | 1 |
| `packages/ai-parrot/tests/eval/test_text_metrics.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/eval/test_composite.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/eval/test_groundedness_metric.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/eval/test_judge_cache.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/eval/test_llm_judge.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/eval/test_regression.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/eval/benchmarks/qa_reference.jsonl` | CREATE | — | — | — |
| `packages/ai-parrot/tests/eval/test_qa_benchmark_e2e.py` | CREATE | — | — | — |
| `docs/eval/answer-accuracy-metrics.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first; every metric `score()` is `async` even when pure (contract of `Metric`).
- Pydantic v2 models for every structured payload; `MetricScore.detail` is plain JSON-able dicts.
- `logger = logging.getLogger(__name__)` at module level (as `state_based.py` does); no `print`.
- Registry names are stable public API: `exact_match`, `contains`, `token_f1`, `groundedness`, `llm_judge`, `composite`.
- `getattr(response, "usage", None)`-style extraction in Module 1 — rollouts are exercised by mock bots that return bare strings.
- Postgres code mirrors `PostgresEvalSink`: lazy `import asyncpg`, `asyncpg.connect(dsn)`, `await conn.execute(_SCHEMA_DDL)` before use, `$N` bindings, `::jsonb` casts, close in `finally`.
- Tests under `packages/ai-parrot/tests/eval/` reuse that directory's `conftest.py` (navconfig stub) and skip DB tests when `EVAL_DB_DSN` is unset, exactly like `test_postgres_sink.py`.

### Known Risks / Gotchas
- **`Trajectory` extra="allow"**: new fields must be declared explicitly (not relied upon as extras) so `model_copy(update=...)` in the runner and JSONB persistence stay typed.
- **ToolCall reconstruction** in `GroundednessMetric`: `ToolCallRecord` has no `id`; synthesize `id=f"{turn_idx}-{call_idx}"`. `EvidenceIndex` only reads `.result`, so this is safe.
- **`user_prompt` for evidence**: pass `_extract_question(task)` so `include_user_prompt_as_evidence` behaves like the online guardrail.
- **Judge model vs. provider string**: `judge_model` is the model name passed to `client.ask(model=...)`; the client instance fixes the provider. `model_under_test` is compared as a plain string.
- **Structured output is best-effort** across providers (`_parse_structured_output` falls back to raw text silently) — the metric must parse JSON from text when `structured_output` is missing, and must never raise.
- **Majority vote with even `n_samples`**: ties resolve to `False` (fail-closed, same spirit as the dev-loop judge panel).
- **Cache key must not include the judge's own output** or wall-clock data; include rubric version so a rubric edit invalidates old verdicts.
- **Baseline semantics**: `get_baseline` returns the latest row by `captured_at`; recording is explicit (`record()`), the gate never auto-records, so a failed gate cannot poison the baseline.
- **Token-F1 tokenization**: whitespace split after `normalize_text`; no stemming, no language-specific logic (documented).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2` (existing) | models |
| `asyncpg` | existing optional | `PostgresJudgeCache`, `PostgresBaselineStore` (lazy import) |

No new dependencies.

---

## 8. Open Questions

- [x] One spec or three? — *Resolved with the user (2026-10-12)*: one feature, three milestones (trajectory + text + groundedness; judge + cache; regression gate), because everything is additive inside `parrot/eval/` and shares one worktree.
- [x] Reuse `knowledge/retrieval/eval/metrics.py::check_regression`? — *Resolved*: no — it is typed on `QueryClass`; the eval gate reimplements the same per-tag rule over `str` tags.
- [x] Cost in `Trajectory`? — *Resolved*: out of scope (needs `CostCalculator`); `cost_usd` stays 0.0.
- [ ] Default `tolerance` for the regression gate (0.05 proposed, matching the retrieval harness) — *Owner: Jesus Lara* (decidable at `/sdd-done` review; implementation uses the keyword default).
- [ ] Should `LLMJudgeMetric.build_prompt` be overridable per rubric (template string on `Rubric`)? — *Owner: implementer* (keep a method override point; a `Rubric.prompt_template` field can be added later without breaking the API).

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (codex CLI not installed in this environment) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree per spec (`.claude/worktrees/feat-FEAT-652-eval-answer-accuracy-metrics`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (evidence in parentheses):
  - M3 → M1 (reads `TurnRecord.tool_calls` populated by the rollout and `Trajectory.response_metadata`).
  - M5 → M4 (imports `Rubric`, `JudgeVerdict`, `JudgeCache`, `judge_cache_key`).
  - M7 → M1, M2, M3, M4, M5, M6 (imports every public name; only module editing `eval/__init__.py`).
  - M1, M2, M4, M6 have no edges between them and are expected to run concurrently.
- **Shared files**: `eval/__init__.py` is modified only by M7; `tests/eval/test_rollout.py` only by M1. No other file is touched by two modules.
- **Exclusive resources**: none (no lockfile, extension build, migration or shared `conftest.py` change).
- **Cross-feature dependencies**: none — FEAT-217 and FEAT-398 are already merged on `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-12 | Jesus Lara | Initial approved draft: seven modules closing the answer-accuracy gaps of FEAT-217 |
