# TASK-4243: Public surface, documentation and hermetic Q&A reference benchmark

**Feature**: FEAT-652 — Answer-Accuracy Metrics for the Evaluation Harness
**Spec**: `sdd/specs/eval-answer-accuracy-metrics.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4237, TASK-4238, TASK-4239, TASK-4240, TASK-4241, TASK-4242
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. Every previous task created its module without touching
`parrot/eval/__init__.py` so they could run concurrently; this task is the single place that
exports the new names, documents the feature, and proves the whole path end-to-end with a
hermetic Q&A benchmark (mock bot, no DB, no real LLM): dataset → `EvalRunner` with
`CompositeEvaluator` (text metrics + `GroundednessMetric` + `LLMJudgeMetric` with a fake client and
`InMemoryJudgeCache`) → `EvalReport` → `record()` + `check_regression()`.

---

## Scope

- MODIFY `eval/__init__.py`: import and export every new public name (spec §2 "New Public Interfaces").
- CREATE `docs/eval/answer-accuracy-metrics.md`.
- CREATE `tests/eval/benchmarks/qa_reference.jsonl` (5 tasks) and `tests/eval/test_qa_benchmark_e2e.py`.
- Export assertions live inside `test_qa_benchmark_e2e.py` (no separate `test_public_exports.py`) so the file list stays fixed.

**NOT in scope**: any behavioural change to the modules of TASK-4237..4242; CLI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | imports + `__all__` entries |
| `docs/eval/answer-accuracy-metrics.md` | CREATE | user documentation |
| `packages/ai-parrot/tests/eval/benchmarks/qa_reference.jsonl` | CREATE | 5-task dataset |
| `packages/ai-parrot/tests/eval/test_qa_benchmark_e2e.py` | CREATE | end-to-end + exports test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.eval import EvalRunConfig, EvalRunner, JSONLDatasetLoader, NoopSandboxProvider, SingleTurnRollout  # verified: eval/__init__.py:38,61-66,29-37,68-74
from parrot.eval.evaluators.text import ContainsMatch, ExactMatch, TokenF1, normalize_text   # TASK-4238
from parrot.eval.evaluators.composite import CompositeEvaluator                             # TASK-4238
from parrot.eval.evaluators.groundedness import GroundednessMetric                          # TASK-4239
from parrot.eval.evaluators.llm_judge import LLMJudgeMetric                                 # TASK-4241
from parrot.eval.judge import InMemoryJudgeCache, JudgeCache, JudgeCriterion, JudgeVerdict, PostgresJudgeCache, Rubric, judge_cache_key  # TASK-4240
from parrot.eval.regression import BaselineStore, InMemoryBaselineStore, PostgresBaselineStore, RegressionVerdict, check_regression  # TASK-4242
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/eval/__init__.py
from parrot.eval.evaluators.state_based import StateBasedEvaluator, StateMatch   # line 75  ← anchor: add the new imports right below
__all__ = [ ... "JiraToolkitBinder", ]                                           # line 90-154; `    "JiraToolkitBinder",` is line 153 ← anchor: add new names right below (before the closing bracket)

# packages/ai-parrot/src/parrot/eval/runner.py
class EvalRunner:  # line 116: __init__(*, dataset, agent_factory, rollout, evaluator, sandbox_provider, config, event_bus=None, event_registry=None, sink=None); async run() -> EvalReport :159
# packages/ai-parrot/src/parrot/eval/datasets.py
class JSONLDatasetLoader(DatasetLoader):  # line 66: async load(self, source: str) -> EvalDataset :76  (one EvalTask JSON object per line)
# packages/ai-parrot/src/parrot/eval/sandbox/base.py
class NoopSandboxProvider(SandboxProvider)  # line 259
# packages/ai-parrot/tests/eval/factories.py — mock-bot style (class with `async def ask(self, question)`), test_benchmarks_e2e.py — e2e style to mirror
```

### Does NOT Exist
- ~~`parrot.eval.metrics`~~ package — metrics live under `parrot.eval.evaluators.*`.
- ~~`docs/eval/`~~ directory — create it.
- ~~`EvalRunner.evaluators`~~ (plural) — one `evaluator`; use `CompositeEvaluator` to combine.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/eval/__init__.py", "action": "MODIFY"},
    {"path": "docs/eval/answer-accuracy-metrics.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/eval/benchmarks/qa_reference.jsonl", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/eval/test_qa_benchmark_e2e.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/eval/runner.py#EvalRunner",
    "sym:packages/ai-parrot/src/parrot/eval/datasets.py#JSONLDatasetLoader",
    "sym:packages/ai-parrot/src/parrot/eval/sandbox/base.py#NoopSandboxProvider",
    "sym:packages/ai-parrot/src/parrot/eval/rollout.py#SingleTurnRollout"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `__init__.py` ordering: keep the new imports after the `state_based` import (line 75) and before
  `EvalTask.model_rebuild()`; append names to `__all__` right after `"JiraToolkitBinder",`.
- The e2e must be hermetic: mock bot returns an `AIMessage`-shaped object (as in TASK-4237's tests)
  whose answer depends on the question so some tasks pass and some fail deterministically;
  fake judge client always returns `correct=True`.
- Dataset rows: `{"task_id": "...", "inputs": {"query": "..."}, "expected": {"answer": [...], "must_contain": [...]}, "tags": ["qa"|"numeric"]}`.
- Docs: dataset shape, each metric's pass rule, judge configuration (model pinning, `n_samples`, cache backends,
  `EVAL_DB_DSN`), regression gate usage, and the FEAT-398 limits inherited by `GroundednessMetric`.

### References in Codebase
- `packages/ai-parrot/tests/eval/test_benchmarks_e2e.py` and `factories.py` — e2e harness wiring to copy.
- `docs/groundedness.md` — doc style and the limits section to link.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `__init__.py` — *why*: it is the public contract spec §5 AC-9 checks.
2. Write the dataset and the e2e test — *why*: proves every module composes through the runner.
3. Write the docs last, from the working test — *why*: examples in docs must be the ones that run.

### `packages/ai-parrot/src/parrot/eval/__init__.py` (MODIFY — imports)
```python
# occurrences: 1 (verified: grep -c 'from parrot.eval.evaluators.state_based import StateBasedEvaluator, StateMatch' packages/ai-parrot/src/parrot/eval/__init__.py)
# AFTER — insert below `from parrot.eval.evaluators.state_based import StateBasedEvaluator, StateMatch` (verified: eval/__init__.py:75)
from parrot.eval.evaluators.text import ContainsMatch, ExactMatch, TokenF1, normalize_text
from parrot.eval.evaluators.composite import CompositeEvaluator
from parrot.eval.evaluators.groundedness import GroundednessMetric
from parrot.eval.evaluators.llm_judge import LLMJudgeMetric
from parrot.eval.judge import (
    InMemoryJudgeCache, JudgeCache, JudgeCriterion, JudgeVerdict, PostgresJudgeCache, Rubric, judge_cache_key,
)
from parrot.eval.regression import (
    BaselineStore, InMemoryBaselineStore, PostgresBaselineStore, RegressionVerdict, check_regression,
)
```

### `packages/ai-parrot/src/parrot/eval/__init__.py` (MODIFY — `__all__`)
```python
# occurrences: 1 (verified: grep -c '    "JiraToolkitBinder",' packages/ai-parrot/src/parrot/eval/__init__.py)
# AFTER — insert below `    "JiraToolkitBinder",` (verified: eval/__init__.py:153)
    # FEAT-652 — answer-accuracy metrics
    "normalize_text", "ExactMatch", "ContainsMatch", "TokenF1", "CompositeEvaluator",
    "GroundednessMetric", "LLMJudgeMetric",
    "JudgeCriterion", "Rubric", "JudgeVerdict", "judge_cache_key",
    "JudgeCache", "InMemoryJudgeCache", "PostgresJudgeCache",
    "BaselineStore", "InMemoryBaselineStore", "PostgresBaselineStore", "RegressionVerdict", "check_regression",
```
**Why**: one edit site for exports keeps TASK-4237..4242 free of file overlap (spec Worktree Strategy).

### `packages/ai-parrot/tests/eval/benchmarks/qa_reference.jsonl` (CREATE)
```json
{"task_id": "qa-1", "inputs": {"query": "What is the capital of France?"}, "expected": {"answer": ["Paris", "París"], "must_contain": ["paris"]}, "tags": ["qa"]}
{"task_id": "qa-2", "inputs": {"query": "What is 25 * 47?"}, "expected": {"answer": "1175", "must_contain": ["1175"]}, "tags": ["numeric"]}
# FILL IN: three more rows (one the mock bot answers wrongly on purpose, e.g. qa-5 expects "Berlin" but the bot answers "Munich") — bounded by AC-2
```

### `packages/ai-parrot/tests/eval/test_qa_benchmark_e2e.py` (CREATE)
```python
"""End-to-end Q&A reference benchmark + public export check (TASK-4243)."""
from pathlib import Path

from parrot.eval import (
    CompositeEvaluator, ContainsMatch, EvalRunConfig, EvalRunner, ExactMatch, GroundednessMetric, InMemoryBaselineStore,
    InMemoryJudgeCache, JSONLDatasetLoader, JudgeCriterion, LLMJudgeMetric, NoopSandboxProvider, Rubric, SingleTurnRollout,
    TokenF1, check_regression,
)
from parrot.eval.judge import JudgeVerdict
from parrot.models.basic import CompletionUsage

DATASET = Path(__file__).parent / "benchmarks" / "qa_reference.jsonl"
ANSWERS = {"capital of France": "Paris.", "25 * 47": "The result is 1175."}  # FILL IN: cover all 5 rows, one wrong on purpose


class _QABot:
    async def ask(self, question: str):
        text = next((a for k, a in ANSWERS.items() if k in question), "I don't know")
        return type("Msg", (), {"content": text, "model": "mock:qa", "usage": CompletionUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
                                "tool_calls": [], "metadata": {}})()


class _AlwaysCorrectJudge:
    async def ask(self, prompt, model, **kw):
        return type("R", (), {"content": "", "structured_output": JudgeVerdict(criteria={"correct": True})})()


def test_public_exports():
    import parrot.eval as e
    for name in ("ExactMatch", "ContainsMatch", "TokenF1", "CompositeEvaluator", "GroundednessMetric", "LLMJudgeMetric", "Rubric",
                 "JudgeVerdict", "InMemoryJudgeCache", "PostgresJudgeCache", "InMemoryBaselineStore", "PostgresBaselineStore", "check_regression"):
        assert name in e.__all__ and hasattr(e, name)


async def test_qa_benchmark_e2e():
    dataset = await JSONLDatasetLoader().load(str(DATASET))
    rubric = Rubric(name="qa", version="1", criteria=[JudgeCriterion(name="correct", question="Is the answer correct?")])
    evaluator = CompositeEvaluator(
        [ExactMatch(), ContainsMatch(), TokenF1(threshold=0.5), GroundednessMetric(),
         LLMJudgeMetric(_AlwaysCorrectJudge(), judge_model="fake:judge", rubric=rubric, cache=InMemoryJudgeCache(), model_under_test="mock:qa")],
        required=("exact_match",), threshold=0.5)

    async def factory(sandbox):
        return _QABot()

    runner = EvalRunner(dataset=dataset, agent_factory=factory, rollout=SingleTurnRollout(), evaluator=evaluator,
                        sandbox_provider=NoopSandboxProvider(), config=EvalRunConfig(k=2))
    report = await runner.run()
    # FILL IN: assert 0 < report.pass_k < 1, "qa" in report.per_tag, every result trajectory has tokens.total == 8;
    #          store = InMemoryBaselineStore(); await store.record(report); (await check_regression(report, store)).passed;
    #          a degraded copy (per_tag["qa"] - 0.5) fails the gate — bounded by AC-2/AC-3
```

### `docs/eval/answer-accuracy-metrics.md` (CREATE)
```markdown
# Answer-Accuracy Metrics for the Evaluation Harness (FEAT-652)

<!-- FILL IN sections, in this order, each with a runnable snippet taken from test_qa_benchmark_e2e.py:
     1. Overview + when to use which metric (table from spec §B)
     2. Dataset shape (expected.answer / must_contain / tags)
     3. Text metrics and CompositeEvaluator pass rules
     4. GroundednessMetric — link docs/groundedness.md "Known limits"
     5. LLMJudgeMetric — Rubric, judge ≠ model under test, n_samples (1 local / 3 CI), cache backends, EVAL_DB_DSN
     6. Regression gate — record() vs check_regression(), per-tag rule, tolerance
     7. What is still out of scope (CLI, cost, shadow mode) — bounded by spec AC-10 -->
```

### FILL IN checklist
- [ ] `qa_reference.jsonl` — rows 3-5; AC-2
- [ ] `test_qa_benchmark_e2e.py::test_qa_benchmark_e2e` — assertions + degraded report; AC-2/AC-3
- [ ] `docs/eval/answer-accuracy-metrics.md` — seven sections; AC-4

---

## Acceptance Criteria

- [ ] AC-1: every name in spec §2 "New Public Interfaces" imports from `parrot.eval` and is listed in `__all__`.
- [ ] AC-2: `test_qa_benchmark_e2e` runs with no DB and no real LLM, yields `0 < pass_k < 1` and per-tag figures, and trajectories carry tokens from the mock bot.
- [ ] AC-3: `record()` then `check_regression()` passes on the same report and fails on a degraded copy.
- [ ] AC-4: `docs/eval/answer-accuracy-metrics.md` covers dataset shape, every metric's pass rule, judge configuration and the regression gate.
- [ ] Full suite: `pytest packages/ai-parrot/tests/eval -q` green; `ruff check packages/ai-parrot/src/parrot/eval/__init__.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/eval/test_qa_benchmark_e2e.py -q`
- `pytest packages/ai-parrot/tests/eval/test_benchmarks_e2e.py -q`
- `pytest packages/ai-parrot/tests/eval/test_registry.py -q`

---

## Test Specification

See the e2e blueprint block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug eval-answer-accuracy-metrics --feature-id FEAT-652`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-4237, TASK-4238, TASK-4239, TASK-4240, TASK-4241, TASK-4242 must all be `"done"`
4. **Verify the Codebase Contract** — re-run `grep -c` on both `__init__.py` anchors; a count of 0 means drift: stop and report
5. **Update status** in `sdd/tasks/index/eval-answer-accuracy-metrics.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint, completing every `# FILL IN:`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`, then the whole `tests/eval` directory once (this task is the feature's closing gate)
8. **Commit the code** — stage only the four files listed
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4243 eval-answer-accuracy-metrics verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
