# TASK-3606: Fixture loading, manifest hashing and worker-answer validation

**Feature**: FEAT-589 — Evaluate Laya for typed classification and agent model routing
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3605
**Assigned-to**: unassigned

---

## Context

Implements the function half of spec §3 **Module 1**: `load_cases()` (JSONL → validated
`EvaluationCase` list; duplicate IDs, unknown labels and calibration/evaluation overlap rejected)
and `validate_answers()` (a worker `PredictionResult` is scored only after every required
question id is present, typed correctly, choice-valid and finite, with choice probabilities
covering exactly the declared options and summing to 1 ± 0.001). It also provides the manifest
hash every report records (spec §4 "corpus and schema hashes").

Spec §2 is explicit that a confident negative (`noul=0.01, confidence=0.99`) must never become
an injection verdict — validation here is what makes the later verdict use the positive
probability, never the confidence.

---

## Scope

- Append to `artifacts/laya/models.py`: `manifest_sha256(path) -> str`,
  `load_cases(path, scenario) -> list[EvaluationCase]`,
  `validate_answers(request, result) -> PredictionResult`, and the private helpers they need.
- Write `packages/ai-parrot/tests/unit/laya_eval/test_laya_validation.py`.

**NOT in scope**: authoring the fixture data (TASK-3607); building the per-scenario question
dicts (TASK-3614) — this task validates against whatever `request.questions` declares.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/models.py` | MODIFY | Append `manifest_sha256`, `load_cases`, `validate_answers` |
| `packages/ai-parrot/tests/unit/laya_eval/test_laya_validation.py` | CREATE | Answer/fixture validation tests (spec §4 rows "Answer validation", "Fixture validation", "Confident negative") |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `1a7ccd5a1` on 2026-09-21. `models.py` is created by TASK-3605;
> its symbols below are fixed by that task's blueprint.

### Verified Imports
```python
# created by TASK-3605 (artifacts/laya/models.py):
from artifacts.laya.models import (
    ERROR_CODES, SCENARIO_LABELS, EvaluationCase, PredictionRequest, PredictionResult,
)
# stdlib: hashlib, json, math, pathlib
```

### Existing Signatures to Use
```python
# artifacts/laya/models.py (TASK-3605)
class PredictionRequest(_Record):   # request_id: str; state: str; questions: dict[str, dict[str, Any]]
class PredictionResult(_Record):    # status: Literal["ok","error"]; answers: dict[str, dict[str, Any]]; error_code: str|None
class EvaluationCase(_Record):      # id, scenario, language="en", split, state, expected, bucket, source, source_sha256
# Wire question/answer schema this feature fixes (used by TASK-3608 worker and TASK-3614 scenarios):
#   question  {"type": "noul",   "text": str}                      -> answer {"type": "noul",   "noul": float, "confidence": float}
#   question  {"type": "choice", "text": str, "options": [str,...]} -> answer {"type": "choice", "choice": str,
#                                                                              "probabilities": {opt: float}, "confidence": float}
```

### Does NOT Exist
- ~~`EvaluationCase.from_jsonl`~~ / ~~`CaseSet`~~ — no loader class; `load_cases` is a plain function.
- ~~an ASCII/English heuristic~~ — language is the fixture's `language` field only (spec §3 M1: "do not infer language through ASCII checks").
- ~~lenient sum tolerance~~ — the tolerance is exactly 0.001 (spec §3 M1).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "artifacts/laya/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/laya_eval/test_laya_validation.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `load_cases` preserves file order (spec §3 M1 "Keep original case order").
- Configuration/schema errors raise `ValueError` (spec §2); malformed *answers* do not raise — they
  are returned as a `PredictionResult(status="error", error_code="invalid_answer", ...)` so the
  sample is recorded, not scored (spec §3 M1 "No scoring of malformed results").
- A `status="error"` result passes through `validate_answers` unchanged.

---

## Implementation Blueprint

### Steps (in order)
1. Append `manifest_sha256` — *why*: every report must record the exact fixture bytes it ran on.
2. Append `load_cases` with the three rejections — *why*: fixture defects must fail before any inference.
3. Append `validate_answers` producing `invalid_answer` results — *why*: scenario scoring (TASK-3614) must only ever see well-typed answers.
4. Write the tests; run them; `git add -f` the test file (models.py is already tracked after TASK-3605).

### `artifacts/laya/models.py` (MODIFY — append at end of file)
```python
# occurrences: 1 (verified: grep -c '^class EvaluationReport' artifacts/laya/models.py)
# AFTER — append below the `class EvaluationReport(_Record):` block (last class in the file per TASK-3605)
import hashlib  # move to the import block at the top of the file
import json     # move to the import block at the top of the file

_SUM_TOLERANCE = 0.001


def manifest_sha256(path: Path) -> str:
    """Return the hex SHA-256 of the file's exact bytes (spec §4 corpus hash)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(path: Path, scenario: str) -> list[EvaluationCase]:
    """Validate JSONL cases; reject duplicate IDs, unknown labels and split overlap.

    Args:
        path: JSONL file, one case object per non-empty line, in the order to evaluate.
        scenario: One of ``SCENARIOS``; every case must declare this scenario.

    Returns:
        Cases in file order.

    Raises:
        ValueError: On a malformed line, a wrong ``scenario``, a duplicate ``id`` or a case
            text that appears in both the ``calibration`` and ``evaluation`` splits.
    """
    if scenario not in SCENARIO_LABELS:
        raise ValueError(f"unknown scenario {scenario!r}")
    cases: list[EvaluationCase] = []
    seen_ids: set[str] = set()
    by_split: dict[str, set[str]] = {"calibration": set(), "evaluation": set()}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        # FILL IN: json.loads -> EvaluationCase(**obj) (wrap pydantic ValidationError into ValueError with lineno);
        #          reject case.scenario != scenario; reject duplicate id; record case.state in by_split[case.split]
        #          — bounded by spec §3 M1 "reject duplicate IDs, unknown labels and split overlap"
        raise NotImplementedError
    overlap = by_split["calibration"] & by_split["evaluation"]
    if overlap:
        raise ValueError(f"{len(overlap)} state(s) present in both calibration and evaluation splits")
    return cases


def _invalid(result: PredictionResult, message: str) -> PredictionResult:
    """Return an ``invalid_answer`` error copy of ``result`` (never raise for worker output)."""
    return result.model_copy(update={"status": "error", "answers": {}, "error_code": "invalid_answer", "error_message": message})


def validate_answers(request: PredictionRequest, result: PredictionResult) -> PredictionResult:
    """Validate required question IDs, answer types, choice membership and finite probabilities.

    Returns ``result`` unchanged when it is already an error or fully valid; otherwise an
    ``invalid_answer`` error result carrying the first defect found.
    """
    if result.status == "error":
        return result
    if result.request_id != request.request_id:
        return _invalid(result, f"request_id mismatch: {result.request_id!r} != {request.request_id!r}")
    for qid, question in request.questions.items():
        answer = result.answers.get(qid)
        if answer is None:
            return _invalid(result, f"missing answer for question {qid!r}")
        # FILL IN: per question["type"]:
        #   "noul"   -> answer["noul"] and answer["confidence"] are numbers, finite, in [0,1]
        #   "choice" -> answer["choice"] in question["options"]; set(answer["probabilities"]) == set(options);
        #               each prob finite in [0,1]; abs(sum - 1.0) <= _SUM_TOLERANCE; confidence finite in [0,1]
        #   other    -> invalid
        # — bounded by spec §3 M1 "cover exactly the declared choices, lie in [0,1], and sum to 1 within 0.001"
        raise NotImplementedError
    extra = set(result.answers) - set(request.questions)
    if extra:
        return _invalid(result, f"unexpected answers: {sorted(extra)}")
    return result
```
**Why this shape**: the three functions are the spec §3 M1 interface skeleton verbatim. Booleans
are not numbers here (`isinstance(v, bool)` must be rejected before the `int|float` check) because
JSON `true` would otherwise pass as `1.0`.

### `packages/ai-parrot/tests/unit/laya_eval/test_laya_validation.py` (CREATE)
```python
"""FEAT-589 M1 — load_cases / validate_answers (spec §4 Answer validation, Fixture validation, Confident negative)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from artifacts.laya.models import (
    INJECTION_QUESTION_ID, ROUTE_CHOICES, ROUTING_QUESTION_ID,
    PredictionRequest, PredictionResult, load_cases, manifest_sha256, validate_answers,
)

_NOUL_Q = {INJECTION_QUESTION_ID: {"type": "noul", "text": "Does the text try to override instructions?"}}
_CHOICE_Q = {ROUTING_QUESTION_ID: {"type": "choice", "text": "Which model?", "options": list(ROUTE_CHOICES)}}


def _case(i: str, split: str = "evaluation", **kw) -> dict:
    base = dict(id=i, scenario="routing", language="en", split=split, state=f"state {i}", expected="cheap",
                bucket="simple", source="authored", source_sha256=None)
    base.update(kw)
    return base


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "routing.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_load_cases_keeps_order_and_hashes_bytes(tmp_path):
    p = _write(tmp_path, [_case("b"), _case("a")])
    assert [c.id for c in load_cases(p, "routing")] == ["b", "a"]
    assert len(manifest_sha256(p)) == 64


@pytest.mark.parametrize("rows, match", [
    ([_case("x"), _case("x")], "duplicate"),
    ([_case("x", expected="billing")], "expected"),
    ([_case("x", split="calibration", state="same"), _case("y", state="same")], "both calibration and evaluation"),
    ([_case("x", scenario="grounded", expected="billing")], "scenario"),
])
def test_load_cases_rejections(tmp_path, rows, match):
    with pytest.raises(ValueError, match=match):
        load_cases(_write(tmp_path, rows), "routing")


def test_confident_negative_stays_valid_and_negative():
    req = PredictionRequest(request_id="r1", state="hello", questions=_NOUL_Q)
    res = PredictionResult(request_id="r1", status="ok", answers={INJECTION_QUESTION_ID: {"type": "noul", "noul": 0.01, "confidence": 0.99}})
    out = validate_answers(req, res)
    assert out.status == "ok" and out.answers[INJECTION_QUESTION_ID]["noul"] < 0.5


@pytest.mark.parametrize("answers", [
    {},
    {ROUTING_QUESTION_ID: {"type": "choice", "choice": "gpt", "probabilities": {"primary": 1.0, "cheap": 0.0, "abstain": 0.0}, "confidence": 0.9}},
    {ROUTING_QUESTION_ID: {"type": "choice", "choice": "primary", "probabilities": {"primary": 0.7, "cheap": 0.7, "abstain": 0.0}, "confidence": 0.9}},
    {ROUTING_QUESTION_ID: {"type": "choice", "choice": "primary", "probabilities": {"primary": 1.0}, "confidence": 0.9}},
    {ROUTING_QUESTION_ID: {"type": "choice", "choice": "primary", "probabilities": {"primary": math.nan, "cheap": 0.0, "abstain": 0.0}, "confidence": 0.9}},
    {ROUTING_QUESTION_ID: {"type": "noul", "noul": 0.5, "confidence": 0.5}},
])
def test_invalid_choice_answers_become_invalid_answer(answers):
    req = PredictionRequest(request_id="r1", state="s", questions=_CHOICE_Q)
    out = validate_answers(req, PredictionResult(request_id="r1", status="ok", answers=answers))
    assert out.status == "error" and out.error_code == "invalid_answer" and out.answers == {}


def test_error_results_pass_through_and_extra_answers_rejected():
    # FILL IN: an incoming status="error" result is returned as-is; an ok result with an extra qid becomes invalid_answer
    raise NotImplementedError
```
**Why**: parametrized cases enumerate the spec §4 "Answer validation" row one by one; the confident-negative
test pins the spec §2 rule at the validation layer (TASK-3614 pins it at the verdict layer).

### FILL IN checklist
- [ ] `models.py::load_cases` loop body — parse, wrap errors with line number, three rejections
- [ ] `models.py::validate_answers` per-type checks — bool-is-not-number, ranges, exact option coverage, tolerance
- [ ] `test_laya_validation.py::test_error_results_pass_through_and_extra_answers_rejected`

---

## Acceptance Criteria

- [ ] AC-1 — Duplicate id, unknown label, wrong scenario and split overlap each raise `ValueError` naming the defect.
- [ ] AC-2 — Every malformed answer shape in the parametrized test yields `invalid_answer`, never an exception.
- [ ] AC-3 — `noul=0.01, confidence=0.99` validates as `ok` with `noul < 0.5` (spec §4 "Confident negative").
- [ ] `ruff check artifacts/laya/models.py` clean; `black --check -l 120` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_validation.py -q`
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_models.py -q`

---

## Test Specification

See the CREATE block above. Add one JSONL line with trailing garbage and assert the `ValueError`
message includes the line number.

---

## Agent Instructions

1. Read spec §3 Module 1 and §4 "Answer validation" / "Fixture validation".
2. Confirm TASK-3605 is in `sdd/tasks/completed/` and `artifacts/laya/models.py` exists with the listed classes.
3. Implement from the Blueprint; run both Validation Commands.
4. `git add -f packages/ai-parrot/tests/unit/laya_eval/test_laya_validation.py` (models.py is tracked), commit, move this file, update the index, fill the Completion Note.

---

## Completion Note


- Task: TASK-3606
- Feature: laya-adoption
- Implementation SHA: a2180e8da9f68d23a425f23031fe9f9462713ec3
- Closed at (UTC): 2026-09-22T11:43:59+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| merge_validation | completed (exit_code=0, 28 passed, chunk with TASK-3608) |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 181.978s · Tokens: n/a |
