# Answer-Accuracy Metrics for the Evaluation Harness (FEAT-652)

## Overview

Use `ExactMatch` when an answer has a precise canonical form, `ContainsMatch` when it
must include required facts, and `TokenF1` when partial token overlap is meaningful.
`GroundednessMetric` checks factual claims against recorded tool evidence, while
`LLMJudgeMetric` applies a rubric when deterministic reference metrics are insufficient.
`CompositeEvaluator` combines these scores into the run's pass result.

| Metric | Pass rule | Best use |
| --- | --- | --- |
| `ExactMatch` | Normalized output equals an accepted `expected.answer` | Exact Q&A |
| `ContainsMatch` | All required strings (or any, when configured) are present | Required facts |
| `TokenF1` | Best token F1 is at least its threshold | Partial reference answers |
| `GroundednessMetric` | Meets its minimum score without contradictions; neutral without evidence | Tool-grounded facts |
| `LLMJudgeMetric` | Rubric's true-criterion fraction meets `pass_threshold` | Qualitative correctness |

## Dataset shape

JSONL datasets contain one task per line. A task has `inputs.query`, accepted
`expected.answer` values, `expected.must_contain` strings, and tags for per-tag reporting:

```json
{"task_id":"qa-1","inputs":{"query":"What is the capital of France?"},"expected":{"answer":["Paris","París"],"must_contain":["paris"]},"tags":["qa"]}
```

Load the dataset with the same code used by the reference benchmark:

```python
dataset = await JSONLDatasetLoader().load(str(DATASET))
```

## Text metrics and composite pass rules

`normalize_text` casefolds text, removes ASCII punctuation, and collapses whitespace.
`ExactMatch` succeeds only on equality after normalization. `ContainsMatch` succeeds when
all configured required substrings are present by default. `TokenF1` uses SQuAD-style token
F1 and succeeds at or above its configured threshold. A composite succeeds only if every
required metric passes and its weighted mean meets `threshold`:

```python
evaluator = CompositeEvaluator(
    [ExactMatch(), ContainsMatch(), TokenF1(threshold=0.5)],
    required=("exact_match",),
    threshold=0.5,
)
```

## GroundednessMetric

`GroundednessMetric` reconstructs evidence from tool calls recorded in a trajectory. It
passes when the score meets `min_score` and there are no contradictions by default. A result
with no evidence or no factual content is neutral (`1.0`, passing), allowing text-only Q&A
benchmarks to combine it safely with reference metrics.

It inherits the FEAT-398 constraints, including hard-data-only extraction, finite evidence
input, and small-integer handling. See [Known limits](../groundedness.md#known-limits).

## LLMJudgeMetric

Pin a judge model that differs from the model under test, define an explicit versioned
rubric, and use `n_samples=1` locally or `n_samples=3` in CI for majority voting. Reuse
`InMemoryJudgeCache` for hermetic/local runs, or `PostgresJudgeCache` for shared runs;
the PostgreSQL backend obtains its DSN from `EVAL_DB_DSN` unless one is passed explicitly.

```python
rubric = Rubric(name="qa", version="1", criteria=[JudgeCriterion(name="correct", question="Is the answer correct?")])
judge = LLMJudgeMetric(
    fake_judge,
    judge_model="provider:pinned-judge",
    rubric=rubric,
    cache=InMemoryJudgeCache(),
    n_samples=1,
    model_under_test="mock:qa",
)
```

## Regression gate

Record an approved report explicitly, then compare candidate reports against its overall and
per-tag `pass_k` figures. `check_regression()` never writes a baseline; a tag fails only
when `baseline - candidate > tolerance` (default `0.05`). Use `PostgresBaselineStore` with
`EVAL_DB_DSN` for persisted baselines or `InMemoryBaselineStore` for local checks.

```python
store = InMemoryBaselineStore()
await store.record(report)
verdict = await check_regression(report, store)
assert verdict.passed
```

## Out of scope

This feature does not add a CLI, cost accounting, production shadow-mode scoring, or joins
against production feedback. Those concerns remain outside the evaluation harness's
answer-accuracy metrics.
