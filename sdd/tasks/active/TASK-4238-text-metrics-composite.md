# TASK-4238: Deterministic text metrics (exact_match, contains, token_f1) and CompositeEvaluator

**Feature**: FEAT-652 — Answer-Accuracy Metrics for the Evaluation Harness
**Spec**: `sdd/specs/eval-answer-accuracy-metrics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The harness has one metric (`state_match`). Conversational and Q&A agents
need reference-based scoring over `trajectory.final_output` against `task.expected`, and an
evaluator that combines several metrics with "required" and "threshold" semantics. The three
metrics are pure, deterministic and LLM-free; `CompositeEvaluator` is the generic aggregator
that TASK-4239 / TASK-4241 metrics plug into and that TASK-4243's benchmark uses.

---

## Scope

- Create `eval/evaluators/text.py`: `normalize_text`, `ExactMatch` (`exact_match`),
  `ContainsMatch` (`contains`), `TokenF1` (`token_f1`).
- Create `eval/evaluators/composite.py`: `CompositeEvaluator` (`composite`).
- Unit tests for both files.

**NOT in scope**: groundedness or LLM-judge metrics; exports in `eval/__init__.py` (TASK-4243);
semantic similarity / embeddings; stemming or language-specific tokenization.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/evaluators/text.py` | CREATE | normalize_text + three metrics |
| `packages/ai-parrot/src/parrot/eval/evaluators/composite.py` | CREATE | CompositeEvaluator |
| `packages/ai-parrot/tests/eval/test_text_metrics.py` | CREATE | metric tests |
| `packages/ai-parrot/tests/eval/test_composite.py` | CREATE | evaluator tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.eval.evaluators.base import AbstractEvaluator, Metric        # verified: eval/evaluators/base.py:64,24
from parrot.eval.models import EvalResult, EvalTask, MetricScore, Trajectory  # verified: eval/models.py:148,18,131,96
from parrot.eval.registry import get_evaluator, get_metric, register_evaluator, register_metric  # verified: eval/registry.py:69,136,36,103
from parrot.eval.sandbox.base import Sandbox                              # verified: eval/sandbox/base.py (class Sandbox(ABC))
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/eval/evaluators/base.py
class Metric(ABC):                 # line 24
    name: str
    async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore: ...  # line 38
class AbstractEvaluator(ABC):      # line 64
    async def evaluate(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> EvalResult: ...  # line 73

# packages/ai-parrot/src/parrot/eval/models.py
class EvalTask(BaseModel):         # line 18: task_id, inputs: dict, expected: dict | None, tags: list[str], ...
class Trajectory(BaseModel):       # line 96: final_output: Any | None, attempt: int, ...
class MetricScore(BaseModel):      # line 131: name, value: float, passed: bool | None, detail: dict
class EvalResult(BaseModel):       # line 148: task_id, attempt, scores: list[MetricScore], passed: bool, trajectory

# packages/ai-parrot/src/parrot/eval/registry.py
def register_metric(name)          # line 103 — raises ValueError on a duplicate name (module-level decoration only, never inside tests)
def register_evaluator(name)       # line 36  — same rule

# Reference implementation to mirror: eval/evaluators/state_based.py:34-154 (StateMatch) and :162-203 (StateBasedEvaluator)
```

### Does NOT Exist
- ~~`parrot.eval.evaluators.text`~~, ~~`parrot.eval.evaluators.composite`~~ — created here.
- ~~`Metric.__init__`~~ — the ABC has no constructor; define your own `__init__` with keyword-only options.
- ~~`MetricScore.weight`~~ — weights live on `CompositeEvaluator`, not on scores.
- ~~`EvalTask.expected_answer`~~ — the reference is `task.expected["answer"]` / `task.expected["must_contain"]`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/eval/evaluators/text.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/eval/evaluators/composite.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/eval/test_text_metrics.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/eval/test_composite.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/eval/evaluators/base.py#Metric",
    "sym:packages/ai-parrot/src/parrot/eval/evaluators/base.py#AbstractEvaluator",
    "sym:packages/ai-parrot/src/parrot/eval/models.py#MetricScore",
    "sym:packages/ai-parrot/src/parrot/eval/models.py#EvalResult",
    "sym:packages/ai-parrot/src/parrot/eval/registry.py#register_metric",
    "sym:packages/ai-parrot/src/parrot/eval/registry.py#register_evaluator"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Registration happens at module import; `register_metric` raises on duplicates, so tests import the
  module (never re-decorate) and resolve via `get_metric("exact_match")` to prove registration.
- A missing `expected` key is a scored failure (`value 0.0`, `passed False`, `detail["reason"]`),
  never an exception — the runner must keep going.
- `final_output` may be `None` or non-str: coerce with `"" if None else str(...)`.
- `normalize_text`: `casefold()`, strip ASCII punctuation (`string.punctuation`) when `strip_punct`,
  collapse whitespace with `" ".join(text.split())`.
- Token F1 (SQuAD style): tokens = normalized text split on whitespace; `common = Counter(a) & Counter(b)`;
  `precision = common/len(pred)`, `recall = common/len(ref)`, F1 = harmonic mean; 0.0 when either side is empty
  (1.0 when both are empty). Max over a list of acceptable answers.
- `CompositeEvaluator`: `weights` default 1.0 per metric; weighted mean over `value`; `passed` =
  `all(s.passed is not False for s in required_scores) and weighted_mean >= threshold`.

### References in Codebase
- `packages/ai-parrot/src/parrot/eval/evaluators/state_based.py` — layout, logger, registration, detail dict.

---

## Implementation Blueprint

### Steps (in order)
1. Write `text.py` with `normalize_text` first — *why*: every metric shares the same normalization so results are comparable.
2. Implement the three metrics, each reading its `expected` key via a small `_expected_answers(task)` helper — *why*: str-or-list handling in one place.
3. Write `composite.py` — *why*: required/threshold semantics are the contract TASK-4243's benchmark relies on.
4. Write both test files; run validation commands.

### `packages/ai-parrot/src/parrot/eval/evaluators/text.py` (CREATE)
```python
"""Deterministic reference-based text metrics (FEAT-652, Module 2).

``exact_match`` / ``contains`` / ``token_f1`` score ``trajectory.final_output``
against ``task.expected`` — no LLM anywhere in this module.
"""
from __future__ import annotations

import logging
import re
import string
from collections import Counter
from typing import Any, Literal

from parrot.eval.evaluators.base import Metric
from parrot.eval.models import EvalTask, MetricScore, Trajectory
from parrot.eval.registry import register_metric
from parrot.eval.sandbox.base import Sandbox

logger = logging.getLogger(__name__)
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def normalize_text(text: str, *, casefold: bool = True, strip_punct: bool = True) -> str:
    """Casefold, strip ASCII punctuation and collapse whitespace."""
    out = text.casefold() if casefold else text
    if strip_punct:
        out = out.translate(_PUNCT_TABLE)
    return " ".join(out.split())


def _expected_answers(task: EvalTask, key: str = "answer") -> list[str]:
    """Return ``task.expected[key]`` as a list of strings (``[]`` when missing)."""
    raw = (task.expected or {}).get(key)
    if raw is None:
        return []
    return [str(x) for x in raw] if isinstance(raw, (list, tuple)) else [str(raw)]


def _output_text(trajectory: Trajectory) -> str:
    return "" if trajectory.final_output is None else str(trajectory.final_output)


def _missing(name: str, key: str) -> MetricScore:
    return MetricScore(name=name, value=0.0, passed=False, detail={"reason": f"expected.{key} missing"})


@register_metric("exact_match")
class ExactMatch(Metric):
    """1.0 iff the normalized output equals any accepted answer; passed == (value == 1.0)."""

    name = "exact_match"

    def __init__(self, *, casefold: bool = True, strip_punct: bool = True) -> None:
        self._casefold = casefold
        self._strip_punct = strip_punct

    async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore:
        answers = _expected_answers(task)
        if not answers:
            return _missing(self.name, "answer")
        # FILL IN: normalize output and each answer with self._casefold/self._strip_punct; value 1.0 on any equality;
        #          detail={"matched": <answer or None>, "normalized_output": ...} — bounded by AC-1
```
```python
@register_metric("contains")
class ContainsMatch(Metric):
    """Fraction of ``expected["must_contain"]`` found in the output; passed by ``mode`` ("all" | "any")."""

    name = "contains"

    def __init__(self, *, mode: Literal["all", "any"] = "all", regex: bool = False) -> None:
        self._mode = mode
        self._regex = regex

    async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore:
        needles = _expected_answers(task, "must_contain")
        if not needles:
            return _missing(self.name, "must_contain")
        # FILL IN: for regex=False compare normalize_text(needle) in normalize_text(output); for regex=True use re.search(needle, output, re.I);
        #          value = found/len(needles); passed = all found if mode=="all" else any; detail={"found": [...], "missing": [...]} — bounded by AC-2


@register_metric("token_f1")
class TokenF1(Metric):
    """SQuAD-style token F1 vs. the best accepted answer; passed == value >= threshold."""

    name = "token_f1"

    def __init__(self, *, threshold: float = 0.5) -> None:
        self._threshold = threshold

    @staticmethod
    def _f1(pred: list[str], ref: list[str]) -> float:
        # FILL IN: Counter intersection; 1.0 when both empty, 0.0 when exactly one is empty; harmonic mean otherwise — bounded by AC-3
        raise NotImplementedError

    async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore:
        answers = _expected_answers(task)
        if not answers:
            return _missing(self.name, "answer")
        pred = normalize_text(_output_text(trajectory)).split()
        best = max(self._f1(pred, normalize_text(a).split()) for a in answers)
        return MetricScore(name=self.name, value=best, passed=best >= self._threshold,
                           detail={"threshold": self._threshold, "candidates": len(answers)})
```
**Why this shape**: three tiny classes sharing `normalize_text` and `_expected_answers` keep the
semantics identical across metrics (spec §3 M2); `_missing` enforces the "missing expected is a
scored failure, never a crash" rule (spec §7).

### `packages/ai-parrot/src/parrot/eval/evaluators/composite.py` (CREATE)
```python
"""CompositeEvaluator — combine any registered metrics (FEAT-652, Module 2)."""
from __future__ import annotations

import logging
from collections.abc import Collection, Mapping, Sequence

from parrot.eval.evaluators.base import AbstractEvaluator, Metric
from parrot.eval.models import EvalResult, EvalTask, MetricScore, Trajectory
from parrot.eval.registry import register_evaluator
from parrot.eval.sandbox.base import Sandbox

logger = logging.getLogger(__name__)


@register_evaluator("composite")
class CompositeEvaluator(AbstractEvaluator):
    """Run every metric; ``passed`` = all *required* metrics passed AND weighted mean >= ``threshold``.

    A metric whose ``passed`` is ``None`` contributes only its ``value``. Metric exceptions are
    caught and recorded as ``value 0.0 / passed False / detail["error"]`` so one broken metric
    never aborts a run.
    """

    def __init__(self, metrics: Sequence[Metric], *, required: Collection[str] = (),
                 threshold: float = 1.0, weights: Mapping[str, float] | None = None) -> None:
        if not metrics:
            raise ValueError("CompositeEvaluator needs at least one metric")
        self._metrics = list(metrics)
        self._required = set(required)
        self._threshold = threshold
        self._weights = dict(weights or {})

    async def evaluate(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> EvalResult:
        scores: list[MetricScore] = []
        for metric in self._metrics:
            try:
                scores.append(await metric.score(task, trajectory, sandbox))
            except Exception as exc:  # one broken metric must not abort the run
                logger.warning("metric %s failed on task %s: %s", metric.name, task.task_id, exc)
                scores.append(MetricScore(name=metric.name, value=0.0, passed=False, detail={"error": str(exc)}))
        # FILL IN: weighted mean over scores (weight = self._weights.get(name, 1.0)); required_ok = no required score with passed is False;
        #          passed = required_ok and mean >= self._threshold — bounded by AC-4/AC-5
        raise NotImplementedError
```
**Why**: mirrors `StateBasedEvaluator.evaluate` (one `EvalResult`, scores list) while adding the
aggregation rules the spec fixes; the exception guard is the same posture as the guardrail
pipeline ("never fail the turn").

### `packages/ai-parrot/tests/eval/test_text_metrics.py` (CREATE)
```python
"""Unit tests for exact_match / contains / token_f1 (TASK-4238)."""
from parrot.eval.evaluators.text import ContainsMatch, ExactMatch, TokenF1, normalize_text
from parrot.eval.models import EvalTask, Trajectory
from parrot.eval.registry import get_metric


def _tr(text):
    return Trajectory(task_id="t", attempt=1, final_output=text)


def test_registered_names():
    assert get_metric("exact_match") is ExactMatch and get_metric("contains") is ContainsMatch and get_metric("token_f1") is TokenF1


def test_normalize_text():
    assert normalize_text("  Hello, World!  ") == "hello world"


async def test_exact_match_normalizes_and_accepts_list():
    task = EvalTask(task_id="t", inputs={}, expected={"answer": ["Paris", "París"]})
    # FILL IN: "PARIS." → value 1.0 passed True; "Lyon" → 0.0 False — bounded by AC-1

# FILL IN: test_contains_all_vs_any_and_regex, test_token_f1_threshold (known values: pred "a b c" vs ref "a b d" → F1 0.6667),
#          test_text_metrics_missing_expected (value 0.0, passed False, detail["reason"]) — bounded by AC-2, AC-3, AC-6
```

### `packages/ai-parrot/tests/eval/test_composite.py` (CREATE)
```python
"""Unit tests for CompositeEvaluator (TASK-4238)."""
import pytest
from parrot.eval.evaluators.base import Metric
from parrot.eval.evaluators.composite import CompositeEvaluator
from parrot.eval.models import EvalTask, MetricScore, Trajectory
from parrot.eval.registry import get_evaluator


class _Const(Metric):
    def __init__(self, name, value, passed):
        self.name, self._v, self._p = name, value, passed
    async def score(self, task, trajectory, sandbox=None):
        return MetricScore(name=self.name, value=self._v, passed=self._p)

# FILL IN: test_registered (get_evaluator("composite")); test_required_overrides_threshold (required "a" fails, mean 0.9 ≥ 0.5 → passed False);
#          test_weights_and_passed_none (weights {"a": 3}, passed None contributes value); test_metric_exception_recorded;
#          test_empty_metrics_raises (ValueError) — bounded by AC-4, AC-5
```

### FILL IN checklist
- [ ] `text.py::ExactMatch.score` — normalization + detail; AC-1
- [ ] `text.py::ContainsMatch.score` — substring/regex, mode; AC-2
- [ ] `text.py::TokenF1._f1` — SQuAD F1; AC-3
- [ ] `composite.py::CompositeEvaluator.evaluate` — weighted mean + required rule; AC-4/AC-5
- [ ] both test files — bodies; AC-1..AC-6

---

## Acceptance Criteria

- [ ] AC-1: `exact_match` is 1.0/True for case/punctuation/whitespace variants of any accepted answer, 0.0/False otherwise.
- [ ] AC-2: `contains` returns the found fraction; `mode="all"` vs `"any"` decide `passed`; `regex=True` uses `re.search`.
- [ ] AC-3: `token_f1` matches hand-computed F1 (e.g. 0.6667 for `a b c` vs `a b d`) and `passed` follows `threshold`.
- [ ] AC-4: `CompositeEvaluator.passed` is False when any required metric has `passed is False`, even if the weighted mean ≥ threshold.
- [ ] AC-5: weights apply; `passed=None` scores contribute value only; a raising metric yields a recorded failure, not an exception.
- [ ] AC-6: missing `expected` keys produce `value 0.0`, `passed False`, `detail["reason"]`.
- [ ] `get_metric("exact_match"|"contains"|"token_f1")`, `get_evaluator("composite")` resolve.
- [ ] `ruff check packages/ai-parrot/src/parrot/eval/evaluators/text.py packages/ai-parrot/src/parrot/eval/evaluators/composite.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/eval/test_text_metrics.py -q`
- `pytest packages/ai-parrot/tests/eval/test_composite.py -q`
- `pytest packages/ai-parrot/tests/eval/test_registry.py -q`

---

## Test Specification

See the two test blueprint blocks above; the `_Const` metric stub is the fixture for the evaluator.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug eval-answer-accuracy-metrics --feature-id FEAT-652`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — `grep`/`read` every reference before writing code
5. **Update status** in `sdd/tasks/index/eval-answer-accuracy-metrics.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint, completing every `# FILL IN:`; never change a signature, registry name or path it fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the four files listed
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4238 eval-answer-accuracy-metrics verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
