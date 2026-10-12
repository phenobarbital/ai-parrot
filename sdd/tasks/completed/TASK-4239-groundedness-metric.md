# TASK-4239: GroundednessMetric — offline FEAT-398 scoring over a Trajectory

**Feature**: FEAT-652 — Answer-Accuracy Metrics for the Evaluation Harness
**Spec**: `sdd/specs/eval-answer-accuracy-metrics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4237
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. FEAT-398's deterministic groundedness scorer (`parrot.security.groundedness`)
only runs online as an output guardrail. This task wraps the same `EvidenceIndex` +
`GroundednessScorer` as an eval `Metric` so a persisted `Trajectory` can be re-scored offline.
It needs the per-turn `tool_calls` that TASK-4237 makes the rollouts record. Nothing under
`parrot/security/groundedness/` is modified.

---

## Scope

- Create `eval/evaluators/groundedness.py` with `GroundednessMetric` registered as `groundedness`.
- Rebuild `list[ToolCall]` from every `trajectory.turns[*].tool_calls`; build evidence with
  `EvidenceIndex.from_tool_calls(..., user_prompt=_extract_question(task))`; score with
  `GroundednessScorer(policy).score(final_output, evidence)`.
- Pass rule: `value = report.score`; `passed = score >= min_score and (not fail_on_contradicted or not report.contradicted)`;
  neutral (1.0 / True) when `report.no_evidence` or `report.no_factual_content`.
- Unit tests, including a parity test against a direct `GroundednessScorer.score()` call.

**NOT in scope**: any change to `parrot.security.groundedness`; exports (TASK-4243); LLM judging.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/evaluators/groundedness.py` | CREATE | the metric |
| `packages/ai-parrot/tests/eval/test_groundedness_metric.py` | CREATE | parity, neutral, contradicted tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.eval.evaluators.base import Metric                                   # verified: eval/evaluators/base.py:24
from parrot.eval.models import EvalTask, MetricScore, ToolCallRecord, Trajectory, TurnRecord  # verified: eval/models.py:18,131,46,96,64
from parrot.eval.registry import register_metric                                 # verified: eval/registry.py:103
from parrot.eval.rollout import _extract_question                                # verified: eval/rollout.py:362
from parrot.eval.sandbox.base import Sandbox                                     # verified: eval/sandbox/base.py
from parrot.models.basic import ToolCall                                         # verified: models/basic.py:23
from parrot.security.groundedness import EvidenceIndex, GroundednessPolicy, GroundednessReport, GroundednessScorer
    # verified: security/groundedness/__init__.py:22-32 (__all__)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/groundedness/evidence.py
class EvidenceIndex:                                                              # line 31
    @classmethod
    def from_tool_calls(cls, tool_calls: list[ToolCall], policy: GroundednessPolicy, user_prompt: str | None = None) -> EvidenceIndex  # line 61
    tool_call_count: int; evidence_truncated: bool

# packages/ai-parrot/src/parrot/security/groundedness/scorer.py
class GroundednessScorer:                                                         # line 56
    def __init__(self, policy: GroundednessPolicy | None = None) -> None          # line 66
    def score(self, answer_text: str, evidence: EvidenceIndex) -> GroundednessReport  # line 74

# packages/ai-parrot/src/parrot/security/groundedness/policy.py
class GroundednessPolicy(BaseModel):  # line 16: enabled_kinds, include_user_prompt_as_evidence=True, contradicted_band=0.15, min_alert_score=0.8, max_evidence_bytes, min_number_digits=4
class GroundednessReport(BaseModel):  # line 58: score: float :81, supported, contradicted :84, unsupported :85, no_factual_content :86, no_evidence :87, evidence_truncated

# packages/ai-parrot/src/parrot/models/basic.py
class ToolCall(BaseModel):            # line 23: id: str, name: str, arguments: Dict[str, Any], result, error, execution_time

# packages/ai-parrot/src/parrot/eval/models.py  (after TASK-4237)
class Trajectory(BaseModel):          # turns: list[TurnRecord]; final_output; response_metadata: dict (TASK-4237)
class TurnRecord(BaseModel):          # role; tool_calls: list[ToolCallRecord]
class ToolCallRecord(BaseModel):      # name, arguments, result, error, latency_ms  (NO id)

# Online reference for the evidence build: security/groundedness/guardrail.py:100-105
#   evidence = EvidenceIndex.from_tool_calls(tool_calls, self.policy, user_prompt=user_prompt)
#   report = self.scorer.score(content, evidence)
```

### Does NOT Exist
- ~~`GroundednessReport.passed`~~ — the pass rule is this metric's; the report has `score` + atom lists.
- ~~`ToolCallRecord.id`~~ — synthesize `id=f"{turn_idx}-{call_idx}"` when rebuilding `ToolCall`.
- ~~`EvidenceIndex.from_trajectory`~~ — only `from_tool_calls` exists.
- ~~`GroundednessScorer.score(trajectory)`~~ — signature is `(answer_text: str, evidence: EvidenceIndex)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/eval/evaluators/groundedness.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/eval/test_groundedness_metric.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/eval/evaluators/base.py#Metric",
    "sym:packages/ai-parrot/src/parrot/eval/models.py#Trajectory",
    "sym:packages/ai-parrot/src/parrot/eval/models.py#ToolCallRecord",
    "sym:packages/ai-parrot/src/parrot/eval/rollout.py#_extract_question",
    "sym:packages/ai-parrot/src/parrot/security/groundedness/evidence.py#EvidenceIndex",
    "sym:packages/ai-parrot/src/parrot/security/groundedness/scorer.py#GroundednessScorer",
    "sym:packages/ai-parrot/src/parrot/security/groundedness/policy.py#GroundednessPolicy",
    "sym:packages/ai-parrot/src/parrot/security/groundedness/policy.py#GroundednessReport",
    "sym:packages/ai-parrot/src/parrot/models/basic.py#ToolCall"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Read-only reuse of FEAT-398; the metric must produce the same `score` as the guardrail for
  the same text and tool calls (parity test).
- `detail` = `report.model_dump()` plus top-level `no_evidence`, `no_factual_content`,
  `tool_call_count` so dashboards do not have to dig.
- Scoring must never raise: wrap in `try/except Exception` → `value 0.0, passed False, detail["error"]`
  (same non-fatal posture as `GroundednessGuardrail.check`).
- Evidence atoms may embed sensitive values; log score + counts only, never atom text.

### References in Codebase
- `packages/ai-parrot/src/parrot/security/groundedness/guardrail.py:70-115` — evidence build + scoring call.
- `packages/ai-parrot/tests/unit/security/test_groundedness_scorer.py` — fixtures for tool-call evidence shapes.

---

## Implementation Blueprint

### Steps (in order)
1. Write `_tool_calls_from_trajectory` — *why*: `ToolCall` needs an `id`; records carry none, so synthesize a stable one.
2. Write the metric with the neutral short-circuit and the non-fatal guard — *why*: spec §3 M3 pass rule, §7 posture.
3. Write the parity test first (direct scorer vs metric) — *why*: it is the only proof the wrapper adds no drift.

### `packages/ai-parrot/src/parrot/eval/evaluators/groundedness.py` (CREATE)
```python
"""GroundednessMetric — offline FEAT-398 scoring over a Trajectory (FEAT-652, Module 3)."""
from __future__ import annotations

import logging

from parrot.eval.evaluators.base import Metric
from parrot.eval.models import EvalTask, MetricScore, Trajectory
from parrot.eval.registry import register_metric
from parrot.eval.rollout import _extract_question
from parrot.eval.sandbox.base import Sandbox
from parrot.models.basic import ToolCall
from parrot.security.groundedness import EvidenceIndex, GroundednessPolicy, GroundednessReport, GroundednessScorer

logger = logging.getLogger(__name__)


def _tool_calls_from_trajectory(trajectory: Trajectory) -> list[ToolCall]:
    """Rebuild ``ToolCall`` objects from every turn's ``ToolCallRecord`` (id synthesized)."""
    calls: list[ToolCall] = []
    for t_idx, turn in enumerate(trajectory.turns):
        for c_idx, rec in enumerate(turn.tool_calls):
            calls.append(ToolCall(id=f"{t_idx}-{c_idx}", name=rec.name, arguments=dict(rec.arguments),
                                  result=rec.result, error=rec.error,
                                  execution_time=(rec.latency_ms / 1000.0) if rec.latency_ms is not None else None))
    return calls


@register_metric("groundedness")
class GroundednessMetric(Metric):
    """Deterministic hard-fact groundedness of ``final_output`` vs. the trajectory's tool results.

    value = report.score; passed = score >= min_score and (not fail_on_contradicted or no contradicted atoms);
    ``no_evidence`` / ``no_factual_content`` are neutral (1.0 / True), mirroring the online guardrail.
    """

    name = "groundedness"

    def __init__(self, policy: GroundednessPolicy | None = None, *, min_score: float = 0.8,
                 fail_on_contradicted: bool = True) -> None:
        self._policy = policy or GroundednessPolicy()
        self._scorer = GroundednessScorer(self._policy)
        self._min_score = min_score
        self._fail_on_contradicted = fail_on_contradicted

    async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore:
        answer = "" if trajectory.final_output is None else str(trajectory.final_output)
        try:
            tool_calls = _tool_calls_from_trajectory(trajectory)
            evidence = EvidenceIndex.from_tool_calls(tool_calls, self._policy, user_prompt=_extract_question(task))
            report: GroundednessReport = self._scorer.score(answer, evidence)
        except Exception as exc:  # non-fatal, same posture as GroundednessGuardrail.check
            logger.warning("groundedness scoring failed for task %s: %s", task.task_id, exc)
            return MetricScore(name=self.name, value=0.0, passed=False, detail={"error": str(exc)})
        # FILL IN: neutral when report.no_evidence or report.no_factual_content → value 1.0, passed True;
        #          else value=report.score, passed per the rule above; detail = report.model_dump() | {"no_evidence", "no_factual_content", "tool_call_count": evidence.tool_call_count};
        #          logger.debug with score + len(contradicted)/len(unsupported) only — bounded by AC-1..AC-3
        raise NotImplementedError
```
**Why**: the evidence build is byte-for-byte the guardrail's (`guardrail.py:100-105`), so parity
is structural; the pass rule and neutrality are the only decisions this module adds.

### `packages/ai-parrot/tests/eval/test_groundedness_metric.py` (CREATE)
```python
"""Unit tests for GroundednessMetric (TASK-4239)."""
from parrot.eval.evaluators.groundedness import GroundednessMetric
from parrot.eval.models import EvalTask, ToolCallRecord, Trajectory, TurnRecord
from parrot.eval.registry import get_metric
from parrot.models.basic import ToolCall
from parrot.security.groundedness import EvidenceIndex, GroundednessPolicy, GroundednessScorer


def _trajectory(answer: str, result: object) -> Trajectory:
    rec = ToolCallRecord(name="get_revenue", arguments={}, result=result, latency_ms=20.0)
    return Trajectory(task_id="t", attempt=1, final_output=answer,
                      turns=[TurnRecord(role="agent", content=answer, tool_calls=[rec], timestamp=0.0)])


async def test_metric_matches_direct_scorer():
    task = EvalTask(task_id="t", inputs={"query": "revenue?"})
    tr = _trajectory("Revenue was $1,243,500 in Q3.", {"summary": "Revenue was $1,243,500."})
    policy = GroundednessPolicy()
    direct = GroundednessScorer(policy).score(tr.final_output, EvidenceIndex.from_tool_calls(
        [ToolCall(id="0-0", name="get_revenue", arguments={}, result={"summary": "Revenue was $1,243,500."})], policy, user_prompt="revenue?"))
    got = await GroundednessMetric(policy).score(task, tr)
    assert got.value == direct.score and got.detail["score"] == direct.score

# FILL IN: test_registered (get_metric("groundedness")); test_no_evidence_neutral (no turns → 1.0/True/detail["no_evidence"]);
#          test_contradicted_fails ("$1,234,500" vs evidence "$1,243,500" → passed False, detail["contradicted"] non-empty);
#          test_fail_on_contradicted_false_uses_threshold_only — bounded by AC-1..AC-3
```

### FILL IN checklist
- [ ] `groundedness.py::GroundednessMetric.score` — neutral branch, pass rule, detail; AC-1..AC-3
- [ ] `test_groundedness_metric.py` — four remaining tests; AC-1..AC-3

---

## Acceptance Criteria

- [ ] AC-1: identical text + tool results give the same `score` as `GroundednessScorer.score()` called directly (parity).
- [ ] AC-2: a trajectory without tool calls is neutral: `value 1.0`, `passed True`, `detail["no_evidence"] is True`.
- [ ] AC-3: a transposed-digit answer is `passed False` with `detail["contradicted"]` non-empty when `fail_on_contradicted=True`.
- [ ] `score()` never raises (exception → `value 0.0`, `passed False`, `detail["error"]`).
- [ ] `get_metric("groundedness")` resolves; `ruff check packages/ai-parrot/src/parrot/eval/evaluators/groundedness.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/eval/test_groundedness_metric.py -q`
- `pytest packages/ai-parrot/tests/unit/security/test_groundedness_scorer.py -q`

---

## Test Specification

See the blueprint block above: parity, neutral, contradicted, threshold-only.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug eval-answer-accuracy-metrics --feature-id FEAT-652`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-4237 must be `"done"` in `sdd/tasks/index/eval-answer-accuracy-metrics.json` (it provides `TurnRecord.tool_calls` population and `Trajectory.response_metadata`)
4. **Verify the Codebase Contract** — `grep`/`read` every reference before writing code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint, completing every `# FILL IN:`; never change a signature, registry name or path it fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the two files listed
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4239 eval-answer-accuracy-metrics verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

- Implemented by seat gpt-5.6-terra (codex), 1 attempt, 334s. Merged and lint-committed by the engine.
- Validation: eval suite `packages/ai-parrot/tests/eval` 144 passed, 3 skipped (merge-tier validation completed green, HEAD d5c1b893e).
- Postgres-backed paths are skipped without `EVAL_DB_DSN`; not exercised against a real DB.
- Closed manually via close_task.sh: finalize_task fidelity gate rejected it because a sibling task's review-fix commit sat in the same range.
- Deviations from spec: none.
