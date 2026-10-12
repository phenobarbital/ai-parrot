# TASK-4241: LLMJudgeMetric — rubric-based LLM judge with cache and self-consistency

**Feature**: FEAT-652 — Answer-Accuracy Metrics for the Evaluation Harness
**Spec**: `sdd/specs/eval-answer-accuracy-metrics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4240
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 — the deferred FEAT-217 D4 judge: per-criterion booleans, a pinned judge model
that must differ from the model under test, temperature 0, `n_samples` self-consistency with
majority vote, and a cache so a re-score never re-pays the LLM. Uses `Rubric`, `JudgeVerdict`,
`JudgeCache` and `judge_cache_key` from TASK-4240 and `AbstractClient.ask()` with
`structured_output=JudgeVerdict`. Prompt wording and the text-JSON fallback are the two
judgement calls (spec marks this module not delegation-eligible).

---

## Scope

- Create `eval/evaluators/llm_judge.py` with `LLMJudgeMetric` registered as `llm_judge`.
- Cache-first scoring; `n_samples` concurrent judge calls; majority vote per criterion (ties → False);
  `value` = fraction True; `passed = value >= rubric.pass_threshold`.
- Verdict extraction: `response.structured_output` (JudgeVerdict or dict) else JSON parsed from `_extract_text(response)`;
  unparseable → `value 0.0`, `passed False`, `detail["error"]` — never raises from `score()`.
- `ValueError` at construction when `judge_model == model_under_test`.
- Unit tests with a fake client (call counter, structured and text modes).

**NOT in scope**: cache backends (TASK-4240); exports (TASK-4243); provider-specific prompt tuning;
a `Rubric.prompt_template` field (spec §8 open question — keep `build_prompt` as the override point).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/evaluators/llm_judge.py` | CREATE | the metric |
| `packages/ai-parrot/tests/eval/test_llm_judge.py` | CREATE | fake-client tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.eval.evaluators.base import Metric                                   # verified: eval/evaluators/base.py:24
from parrot.eval.models import EvalTask, MetricScore, Trajectory                 # verified: eval/models.py:18,131,96
from parrot.eval.registry import register_metric                                 # verified: eval/registry.py:103
from parrot.eval.rollout import _extract_question, _extract_text                 # verified: eval/rollout.py:362,384
from parrot.eval.sandbox.base import Sandbox                                     # verified: eval/sandbox/base.py
from parrot.eval.judge import JudgeCache, JudgeVerdict, Rubric, judge_cache_key  # created by TASK-4240 (eval/judge/__init__.py)
from parrot.clients.base import AbstractClient                                   # verified: clients/base.py (TYPE_CHECKING import only)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py
async def ask(self, prompt: str, model: str, max_tokens: Optional[int] = None, temperature: float = 0.7,
              files=None, system_prompt: Optional[str] = None, history=None,
              structured_output: Union[type, StructuredOutputConfig, None] = None, tools=None, use_tools=None,
              deep_research: bool = False, background: bool = False, lazy_loading: bool = False) -> MessageResponse   # line 1829
# Structured output is best-effort: _parse_structured_output (clients/base.py ~2569) falls back to the raw string on ValidationError,
# so the returned object may carry `.structured_output` (AIMessage, models/responses.py:190) OR only text.

# packages/ai-parrot/src/parrot/eval/rollout.py
def _extract_text(response: Any) -> str | None    # line 384 — .content / .response / .text fallbacks

# TASK-4240 (eval/judge/models.py)
class Rubric(BaseModel): name, version, criteria: list[JudgeCriterion], pass_threshold: float = 1.0
class JudgeVerdict(BaseModel): criteria: dict[str, bool]; rationale: str = ""
def judge_cache_key(*, judge_model, rubric, question, expected, answer) -> str
class JudgeCache(ABC): async get(key) -> JudgeVerdict | None; async set(key, verdict, *, judge_model_version, rubric_version)
```

### Does NOT Exist
- ~~`AbstractClient.completion()`~~ / ~~`.judge()`~~ — only `ask()`.
- ~~`MessageResponse.structured_output`~~ as a guaranteed field — read with `getattr(response, "structured_output", None)`.
- ~~`Rubric.prompt_template`~~ — not yet; `build_prompt` is the override point.
- ~~`Trajectory.model_under_test`~~ — the comparison uses the constructor argument; `trajectory.model` (TASK-4237) is only echoed into `detail`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/eval/evaluators/llm_judge.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/eval/test_llm_judge.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/eval/evaluators/base.py#Metric",
    "sym:packages/ai-parrot/src/parrot/eval/models.py#MetricScore",
    "sym:packages/ai-parrot/src/parrot/eval/rollout.py#_extract_text",
    "sym:packages/ai-parrot/src/parrot/eval/rollout.py#_extract_question",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The client is the only LLM path (`CONTEXT.md`: never call provider SDKs). Import `AbstractClient`
  under `TYPE_CHECKING` only, as `rollout.py` does, so `parrot.eval` stays importable without `navconfig`.
- Majority vote with an even `n_samples` ties to `False` (fail-closed, like the dev-loop judge panel).
- Criteria the judge omitted count as `False`; unknown extra keys are ignored.
- Cache writes happen only for a successfully parsed merged verdict.
- `detail` = `{"verdict": verdict.model_dump(), "cached": bool, "samples": n, "judge_model": ..., "rubric": f"{name}@{version}", "model_under_test": trajectory.model}`.

### References in Codebase
- `packages/ai-parrot/src/parrot/eval/rollout.py:120-150` — `LLMUserSimulator` is the existing example of calling `client.ask()` from the harness.
- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py:637-700` — majority / fail-closed semantics to mirror (do not import).

---

## Implementation Blueprint

### Steps (in order)
1. Write `_parse_verdict` (structured → dict → text JSON, with a fenced-block strip) — *why*: structured output is best-effort across providers.
2. Write `build_prompt` as a plain method — *why*: it is the single override point left open by spec §8.
3. Write `score()` cache-first, then `asyncio.gather` over `n_samples`, then `_merge` — *why*: one LLM call per unique key is AC-1.
4. Write tests with a fake client exposing a call counter.

### `packages/ai-parrot/src/parrot/eval/evaluators/llm_judge.py` (CREATE)
```python
"""LLMJudgeMetric — rubric-based LLM-as-judge with cache and self-consistency (FEAT-652, Module 5)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any

from parrot.eval.evaluators.base import Metric
from parrot.eval.judge import JudgeCache, JudgeVerdict, Rubric, judge_cache_key
from parrot.eval.models import EvalTask, MetricScore, Trajectory
from parrot.eval.registry import register_metric
from parrot.eval.rollout import _extract_question, _extract_text
from parrot.eval.sandbox.base import Sandbox

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient

logger = logging.getLogger(__name__)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _parse_verdict(response: Any) -> JudgeVerdict | None:
    """JudgeVerdict from ``response.structured_output`` or from JSON in the response text; None if neither parses."""
    structured = getattr(response, "structured_output", None)
    if isinstance(structured, JudgeVerdict):
        return structured
    if isinstance(structured, dict):
        try:
            return JudgeVerdict.model_validate(structured)
        except Exception:
            return None
    text = _extract_text(response) or ""
    # FILL IN: take the first fenced block if present, else the text; json.loads → JudgeVerdict.model_validate; None on any error — bounded by AC-4/AC-5
    raise NotImplementedError


@register_metric("llm_judge")
class LLMJudgeMetric(Metric):
    """Judge ``final_output`` against a ``Rubric`` with a pinned judge model (≠ model under test)."""

    name = "llm_judge"

    def __init__(self, client: "AbstractClient", *, judge_model: str, rubric: Rubric, cache: JudgeCache | None = None,
                 n_samples: int = 1, model_under_test: str | None = None, max_tokens: int = 1024) -> None:
        if model_under_test is not None and judge_model == model_under_test:
            raise ValueError("judge_model must differ from model_under_test (FEAT-217 D4)")
        if n_samples < 1:
            raise ValueError("n_samples must be >= 1")
        self._client, self._judge_model, self._rubric = client, judge_model, rubric
        self._cache, self._n_samples, self._max_tokens = cache, n_samples, max_tokens

    def build_prompt(self, task: EvalTask, answer: str) -> str:
        """Render question, expected (if any), the answer and the rubric's yes/no questions; demand strict JSON."""
        # FILL IN: sections QUESTION / EXPECTED (omit when task.expected is None) / ANSWER / CRITERIA (one line per criterion: name — question);
        #          final instruction: reply ONLY with JSON {"criteria": {"<name>": true|false, ...}, "rationale": "<one sentence>"} — bounded by spec §3 M5
        raise NotImplementedError
```
```python
    @staticmethod
    def _merge(verdicts: list[JudgeVerdict], rubric: Rubric) -> JudgeVerdict:
        """Majority vote per criterion; ties and missing criteria resolve to False."""
        # FILL IN: for each rubric criterion count True votes; True iff votes > len(verdicts)/2; rationale = first non-empty — bounded by AC-2
        raise NotImplementedError

    async def _ask_once(self, prompt: str) -> JudgeVerdict | None:
        response = await self._client.ask(prompt, model=self._judge_model, temperature=0.0,
                                          max_tokens=self._max_tokens, structured_output=JudgeVerdict)
        return _parse_verdict(response)

    async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore:
        answer = "" if trajectory.final_output is None else str(trajectory.final_output)
        question = _extract_question(task)
        key = judge_cache_key(judge_model=self._judge_model, rubric=self._rubric, question=question,
                              expected=task.expected, answer=answer)
        base_detail: dict[str, Any] = {"judge_model": self._judge_model, "rubric": f"{self._rubric.name}@{self._rubric.version}",
                                       "model_under_test": trajectory.model, "samples": self._n_samples}
        try:
            verdict = await self._cache.get(key) if self._cache is not None else None
            cached = verdict is not None
            if verdict is None:
                prompt = self.build_prompt(task, answer)
                samples = await asyncio.gather(*(self._ask_once(prompt) for _ in range(self._n_samples)))
                parsed = [v for v in samples if v is not None]
                if not parsed:
                    return MetricScore(name=self.name, value=0.0, passed=False, detail={**base_detail, "error": "judge output unparseable"})
                verdict = self._merge(parsed, self._rubric)
                if self._cache is not None:
                    await self._cache.set(key, verdict, judge_model_version=self._judge_model, rubric_version=self._rubric.version)
        except Exception as exc:  # never fail the run because the judge failed
            logger.warning("llm_judge failed for task %s: %s", task.task_id, exc)
            return MetricScore(name=self.name, value=0.0, passed=False, detail={**base_detail, "error": str(exc)})
        # FILL IN: value = fraction of rubric criteria True in verdict.criteria; passed = value >= pass_threshold;
        #          detail = {**base_detail, "verdict": verdict.model_dump(), "cached": cached} — bounded by AC-1..AC-3
        raise NotImplementedError
```
**Why this shape**: cache-first guarantees AC-1 (one call per unique key); `gather` keeps
`n_samples` concurrent; every failure path returns a scored failure so the runner's `pass^k`
stays meaningful (a judge outage is a failed attempt, not a crash).

### `packages/ai-parrot/tests/eval/test_llm_judge.py` (CREATE)
```python
"""Unit tests for LLMJudgeMetric with a fake client (TASK-4241)."""
import pytest
from parrot.eval.evaluators.llm_judge import LLMJudgeMetric
from parrot.eval.judge import InMemoryJudgeCache, JudgeCriterion, JudgeVerdict, Rubric
from parrot.eval.models import EvalTask, Trajectory
from parrot.eval.registry import get_metric


class FakeJudgeClient:
    """Returns scripted verdicts; counts calls; text_mode returns JSON text instead of structured_output."""

    def __init__(self, verdicts, text_mode=False):
        self.verdicts, self.text_mode, self.calls = list(verdicts), text_mode, 0

    async def ask(self, prompt, model, **kw):
        self.calls += 1
        v = self.verdicts[(self.calls - 1) % len(self.verdicts)]
        if self.text_mode:
            return type("R", (), {"content": v.model_dump_json()})()
        return type("R", (), {"content": "", "structured_output": v})()


RUBRIC = Rubric(name="qa", version="1", criteria=[JudgeCriterion(name="correct", question="Correct?"),
                                                  JudgeCriterion(name="concise", question="Concise?")])
TASK = EvalTask(task_id="t", inputs={"query": "capital of France?"}, expected={"answer": "Paris"})
TR = Trajectory(task_id="t", attempt=1, final_output="Paris", model="under-test")

# FILL IN: test_registered; test_calls_client_once_then_cached (cache=InMemoryJudgeCache(); two score() → client.calls == 1, second detail["cached"] True);
#          test_majority_vote (n_samples=3, verdicts T/T/F on "correct" → True; F/F/T → False); test_tie_is_false (n_samples=2);
#          test_rejects_same_model (ValueError); test_unparseable_output (client returning "garbage" text → 0.0/False/detail["error"]);
#          test_parses_text_json_fallback (text_mode=True) — bounded by AC-1..AC-5
```

### FILL IN checklist
- [ ] `llm_judge.py::_parse_verdict` text path; AC-4/AC-5
- [ ] `llm_judge.py::LLMJudgeMetric.build_prompt`; spec §3 M5
- [ ] `llm_judge.py::LLMJudgeMetric._merge`; AC-2
- [ ] `llm_judge.py::LLMJudgeMetric.score` final value/passed/detail; AC-1..AC-3
- [ ] `test_llm_judge.py` — seven tests; AC-1..AC-5

---

## Acceptance Criteria

- [ ] AC-1: with a cache, two `score()` calls on identical inputs make exactly one client call; the second reports `detail["cached"] is True`.
- [ ] AC-2: `n_samples=3` majority-votes each criterion; an even split resolves to False.
- [ ] AC-3: `ValueError` when `judge_model == model_under_test`; `value`/`passed` follow `rubric.pass_threshold`.
- [ ] AC-4: unparseable judge output → `value 0.0`, `passed False`, `detail["error"]`; `score()` never raises.
- [ ] AC-5: a client that returns JSON text without `structured_output` is parsed correctly.
- [ ] `get_metric("llm_judge")` resolves; `ruff check packages/ai-parrot/src/parrot/eval/evaluators/llm_judge.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/eval/test_llm_judge.py -q`

---

## Test Specification

See the blueprint block above (`FakeJudgeClient` is the only fixture).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug eval-answer-accuracy-metrics --feature-id FEAT-652`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-4240 must be `"done"` (provides `parrot.eval.judge`)
4. **Verify the Codebase Contract** — `grep`/`read` every reference before writing code
5. **Update status** in `sdd/tasks/index/eval-answer-accuracy-metrics.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint, completing every `# FILL IN:`; never change a signature, registry name or path it fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the two files listed
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4241 eval-answer-accuracy-metrics verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-4241
- Feature: eval-answer-accuracy-metrics
- Implementation SHA: ab98fd254e87d90d1f719dffb77ee37f2ce13c58
- Closed at (UTC): 2026-10-12T17:28:03+00:00
- Fix commits: ab98fd254e87d90d1f719dffb77ee37f2ce13c58

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 1 |
| seat_summary | Seat: gpt-5.6-luna · Backend: codex · Model: gpt-5.6-luna · Attempts: 1 · Duration: 76s · Tokens: n/a |
