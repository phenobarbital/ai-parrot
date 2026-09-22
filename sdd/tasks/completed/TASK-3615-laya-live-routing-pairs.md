# TASK-3615: Paired primary-only vs routed live calls with rubric checks and evidence capture

**Feature**: FEAT-589 — Evaluate Laya for typed classification and agent model routing
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3613, TASK-3611
**Assigned-to**: unassigned

---

## Context

Spec §2: "Run paired primary-only and routed calls on the same fixtures with separate sessions
and matching generation settings." This task appends `run_live_routing_pairs()` to
`artifacts/laya/live.py`. For each routing case with a `RouteDecision`, it reserves two budget
slots, calls the agent once with the primary model bound and once with the decision's selected
model bound (both through `LayaEvaluationAgent.ask_routed`, so the same hook path is exercised),
records model evidence, usage, latency and the rubric outcome per arm, and stops with
`call_cap_reached` samples when the cap cannot cover a full pair. Provider errors are recorded
per arm (`provider_error`) without substitution.

The agent is duck-typed here (anything with `async ask_routed(question, decision, **kwargs)`),
so the unit test needs no real `Agent`, client or credentials.

---

## Scope

- Append to `artifacts/laya/live.py`: `rubric_pass(answer, rubric) -> bool | None`,
  `load_rubrics(path) -> dict`, `run_live_routing_pairs(agent, cases, decisions, config, budget, rubrics) -> list[SampleResult]`.
- Write `packages/ai-parrot/tests/unit/laya_eval/test_laya_live_pairs.py`.

**NOT in scope**: constructing the real agent/client (TASK-3616); metrics (TASK-3612).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/live.py` | MODIFY | Append rubric helpers + paired live runner |
| `packages/ai-parrot/tests/unit/laya_eval/test_laya_live_pairs.py` | CREATE | Pair accounting, cap stop, provider error, evidence + rubric per arm |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `1a7ccd5a1` on 2026-09-21; `live.py` (TASK-3613) and `routing.py` (TASK-3611) symbols fixed by their blueprints.

### Verified Imports
```python
from parrot.models.responses import AIMessage                     # verified: responses.py:75 (.response: Optional[str] :81, .output :80)
from artifacts.laya.live import LiveCallBudget, extract_model_evidence, ModelEvidence   # TASK-3613 (same file)
from artifacts.laya.models import EvaluationCase, EvaluationConfig, RouteDecision, SampleResult   # TASK-3605
from artifacts.laya.routing import LayaEvaluationAgent           # TASK-3611 — TYPE_CHECKING import only; runtime duck-types the agent
```

### Existing Signatures to Use
```python
# artifacts/laya/routing.py (TASK-3611)
async def ask_routed(self, question: str, decision: RouteDecision, **kwargs: Any) -> AIMessage   # forces use_tools/vector/history False
# artifacts/laya/live.py (TASK-3613)
class LiveCallBudget: reserve() -> bool; reserve_pair() -> bool; remaining: int
def extract_model_evidence(message: AIMessage, requested_model: str | None) -> ModelEvidence
# parrot base ask kwargs accepted (base.py:984-1006, 1138): session_id: str, max_tokens via **kwargs, temperature via **kwargs
# routing_rubrics.json shape (TASK-3607): {case_id: {"exact_answer": str} | {"required_facts": [str, ...]}}
```

### Does NOT Exist
- ~~`agent.ask(model=...)`~~ — both arms go through `ask_routed` with a bound decision (primary arm binds `RouteDecision(choice="primary", selected_model=config.primary_api_model, reason="primary_arm")`).
- ~~budget refunds on failure~~ — none (spec §2 "including failed calls").
- ~~an LLM-judge for rubrics~~ — rubric check is exact/substring matching only (spec non-goals exclude answer-vs-evidence entailment).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "artifacts/laya/live.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/laya_eval/test_laya_live_pairs.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Separate sessions per arm: `session_id=f"{case.id}:primary"` / `f"{case.id}:routed"`; matching
  generation settings: `max_tokens=config.max_output_tokens`, `temperature=0.0` on both arms.
- The routed arm uses the case's `RouteDecision` as-is (if `choice != "cheap"` it is a primary call
  by policy and must still be recorded under `arm="routed"` with `decision` attached).
- `rubric_pass`: `exact_answer` ⇒ normalized (casefold, strip, collapse whitespace) equality with
  the answer text; `required_facts` ⇒ every fact casefold-substring of the answer; no rubric ⇒ `None`.
- Answer text: `message.response if isinstance(message.response, str) else str(message.output)`.
- `timings_ms={"llm_ms": ...}` measured around each `ask_routed`.

---

## Implementation Blueprint

### Steps (in order)
1. Append `load_rubrics` and `rubric_pass` — *why*: pure helpers, tested first.
2. Append `_arm_sample` (one call → one `SampleResult`) — *why*: both arms share the exact same recording code.
3. Append `run_live_routing_pairs` — *why*: pair reservation, order, cap stop.
4. Tests with a fake agent; commit (`live.py` tracked; `git add -f` the test).

### `artifacts/laya/live.py` (MODIFY — append at end of file)
```python
# occurrences: 1 (verified: grep -c '^def extract_model_evidence' artifacts/laya/live.py)
# AFTER — append below the `extract_model_evidence` function (last definition in TASK-3613's blueprint)
import json, re, time                       # move to the import block at the top
from collections.abc import Sequence        # move to the import block at the top
from pathlib import Path                    # move to the import block at the top
from artifacts.laya.models import EvaluationCase, RouteDecision, SampleResult   # extend the existing models import


def load_rubrics(path: Path) -> dict[str, dict[str, Any]]:
    """Load ``routing_rubrics.json`` ({case_id: {"exact_answer": str} | {"required_facts": [str]}})."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for case_id, rubric in data.items():
        if ("exact_answer" in rubric) == ("required_facts" in rubric):
            raise ValueError(f"rubric {case_id!r} must have exactly one of exact_answer / required_facts")
    return data


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def rubric_pass(answer: str, rubric: dict[str, Any] | None) -> bool | None:
    """Exact normalized match or all required facts present; None when no rubric exists."""
    if rubric is None:
        return None
    if "exact_answer" in rubric:
        return _norm(answer) == _norm(str(rubric["exact_answer"]))
    return all(_norm(str(fact)) in _norm(answer) for fact in rubric["required_facts"])


async def _arm_sample(agent: Any, case: EvaluationCase, arm: str, decision: RouteDecision, config: EvaluationConfig,
                      rubric: dict[str, Any] | None) -> SampleResult:
    """One logical call → one SampleResult; provider errors are recorded, never substituted."""
    t0 = time.perf_counter()
    base = dict(case_id=case.id, scenario="routing", repeat=0, arm=arm, expected=case.expected, decision=decision,
                requested_model=decision.selected_model, selected_model=decision.selected_model)
    try:
        message = await agent.ask_routed(case.state, decision, session_id=f"{case.id}:{arm}",
                                         max_tokens=config.max_output_tokens, temperature=0.0)
    except Exception as exc:  # provider/model error: record with the stable code (spec §2)
        return SampleResult(status="error", error_code="provider_error", timings_ms={"llm_ms": (time.perf_counter() - t0) * 1000.0},
                            answer=f"{type(exc).__name__}: {exc}", **base)
    llm_ms = (time.perf_counter() - t0) * 1000.0
    evidence = extract_model_evidence(message, decision.selected_model)
    answer = message.response if isinstance(message.response, str) else str(message.output)
    # FILL IN: return SampleResult(status="ok", predicted=decision.choice, error_code=evidence.error_code, timings_ms={"llm_ms": llm_ms},
    #          reported_model=evidence.reported_model, actual_model=evidence.actual_model, fallback_metadata=evidence.fallback_metadata,
    #          usage=evidence.usage, answer=answer, quality_pass=rubric_pass(answer, rubric), **base) — bounded by spec §2 evidence rules
    raise NotImplementedError


async def run_live_routing_pairs(agent: Any, cases: Sequence[EvaluationCase], decisions: dict[str, RouteDecision],
                                 config: EvaluationConfig, budget: LiveCallBudget, rubrics: dict[str, dict[str, Any]],
                                 ) -> list[SampleResult]:
    """Primary-only vs routed call per case, two slots reserved BEFORE dispatch; stop at the cap (spec §2)."""
    primary_decision = RouteDecision(choice="primary", selected_model=config.primary_api_model, confidence=None, reason="primary_arm")
    samples: list[SampleResult] = []
    for case in cases:
        decision = decisions.get(case.id)
        if decision is None:
            continue
        if not budget.reserve_pair():
            samples.append(SampleResult(case_id=case.id, scenario="routing", repeat=0, arm="primary", expected=case.expected,
                                        status="error", error_code="call_cap_reached", decision=decision))
            break
        rubric = rubrics.get(case.id)
        samples.append(await _arm_sample(agent, case, "primary", primary_decision, config, rubric))
        samples.append(await _arm_sample(agent, case, "routed", decision, config, rubric))
    return samples
```
**Why**: spec §2 — "reserve a slot before dispatch. Require two remaining slots before starting a
pair." and "provider model errors are recorded without substitution".

### `packages/ai-parrot/tests/unit/laya_eval/test_laya_live_pairs.py` (CREATE)
```python
"""FEAT-589 M4 — paired live calls: accounting, cap stop, provider errors, evidence and rubric per arm."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage

from artifacts.laya.live import LiveCallBudget, rubric_pass, run_live_routing_pairs
from artifacts.laya.models import EvaluationCase, EvaluationConfig, RouteDecision


def _cfg(**kw) -> EvaluationConfig:
    base = dict(worker_python=Path("/bin/python3"), checkpoint_path=Path("/tmp/c"), checkpoint_revision="r", output_dir=Path("/tmp/o"),
                live=True, primary_api_model="P", cheap_api_model="C", max_live_calls=4)
    base.update(kw)
    return EvaluationConfig(**base)


def _case(i: str, expected: str = "cheap") -> EvaluationCase:
    return EvaluationCase(id=i, scenario="routing", language="en", split="evaluation", state=f"question {i}", expected=expected, bucket="simple", source="t")


class FakeAgent:
    def __init__(self, fail_for: str | None = None, raw: bool = True):
        self.calls, self.fail_for, self.raw = [], fail_for, raw

    async def ask_routed(self, question, decision, **kwargs):
        self.calls.append((question, decision.selected_model, kwargs))
        if self.fail_for and decision.selected_model == self.fail_for:
            raise RuntimeError("provider says no")
        return AIMessage(input=question, output="Paris", response="Paris", model=decision.selected_model, provider="claude",
                         raw_response={"model": f"{decision.selected_model}-real"} if self.raw else None,
                         usage=CompletionUsage(prompt_tokens=5, completion_tokens=1, total_tokens=6))


def test_rubric_pass_exact_and_facts():
    assert rubric_pass(" paris ", {"exact_answer": "Paris"}) is True
    assert rubric_pass("Paris is in France", {"required_facts": ["paris", "france"]}) is True
    assert rubric_pass("Rome", {"exact_answer": "Paris"}) is False and rubric_pass("x", None) is None


async def test_pair_uses_separate_sessions_matching_settings_and_both_arms_recorded():
    agent = FakeAgent()
    decisions = {"a": RouteDecision(choice="cheap", selected_model="C", confidence=0.9, reason="cheap")}
    samples = await run_live_routing_pairs(agent, [_case("a")], decisions, _cfg(), LiveCallBudget(4), {"a": {"exact_answer": "Paris"}})
    assert [s.arm for s in samples] == ["primary", "routed"] and [c[1] for c in agent.calls] == ["P", "C"]
    sessions = {c[2]["session_id"] for c in agent.calls}
    assert sessions == {"a:primary", "a:routed"} and all(c[2]["max_tokens"] == 256 and c[2]["temperature"] == 0.0 for c in agent.calls)
    assert all(s.quality_pass is True and s.actual_model == f"{s.selected_model}-real" for s in samples)


async def test_cap_stops_before_a_partial_pair_and_counts_both_arms():
    budget = LiveCallBudget(3)
    decisions = {i: RouteDecision(choice="cheap", selected_model="C", confidence=0.9, reason="cheap") for i in ("a", "b")}
    samples = await run_live_routing_pairs(FakeAgent(), [_case("a"), _case("b")], decisions, _cfg(), budget, {})
    assert [s.arm for s in samples[:2]] == ["primary", "routed"] and samples[2].error_code == "call_cap_reached" and budget.used == 2


async def test_provider_error_recorded_without_substitution_and_slot_consumed():
    budget = LiveCallBudget(2)
    decisions = {"a": RouteDecision(choice="cheap", selected_model="C", confidence=0.9, reason="cheap")}
    samples = await run_live_routing_pairs(FakeAgent(fail_for="C"), [_case("a")], decisions, _cfg(), budget, {})
    routed = samples[1]
    assert routed.status == "error" and routed.error_code == "provider_error" and routed.selected_model == "C" and budget.remaining == 0


async def test_missing_raw_model_marks_model_unverified_per_arm():
    # FILL IN: FakeAgent(raw=False) -> both samples have actual_model None and error_code "model_unverified" while status == "ok" — spec §2
    raise NotImplementedError
```
**Why**: spec §4 "Live configuration/cap" ("both arms counted; no partial pair after cap") and
"Model evidence" per arm; spec §2 "separate sessions and matching generation settings".

### FILL IN checklist
- [ ] `live.py::_arm_sample` — ok `SampleResult` construction from evidence + rubric
- [ ] `test_laya_live_pairs.py::test_missing_raw_model_marks_model_unverified_per_arm`

---

## Acceptance Criteria

- [ ] AC-1 — Each case produces exactly one `primary` and one `routed` sample with distinct session ids and identical `max_tokens`/`temperature`.
- [ ] AC-2 — With 3 slots and 2 cases, the second pair is refused with `call_cap_reached` and `budget.used == 2`.
- [ ] AC-3 — A provider exception becomes a `provider_error` sample; the slot is consumed; no model substitution occurs.
- [ ] AC-4 — Evidence and rubric outcome are recorded per arm; missing raw model ⇒ `model_unverified`.
- [ ] `ruff check artifacts/laya/live.py` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_live_pairs.py -q`
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_live.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §2 routing/live paragraphs and §4 routing metrics.
2. Confirm TASK-3613 and TASK-3611 are completed; verify the append anchor with `grep -n`.
3. Implement from the Blueprint; run both Validation Commands; commit; move this file; update the index; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-coder (native, backend=native, model=sonnet, attempt_uid=921afcba1fa74385b0ff52686b917540), consolidated by sdd-worker orchestrator
**Date**: 2026-09-22
**Notes**: Appended `load_rubrics`, `rubric_pass`, and `run_live_routing_pairs` to `artifacts/laya/live.py`.
Each routing case reserves two budget slots via `LiveCallBudget.reserve_pair()` before dispatch; calls
`agent.ask_routed` once per arm (primary bound, then the case's routed decision bound), records model
evidence/usage/latency/rubric outcome per arm, wraps provider exceptions as `status="error"`/
`error_code="provider_error"` with no substitution, never refunds a consumed slot on failure, and stops
with a single `call_cap_reached` sample (no partial pair) when `reserve_pair()` fails. Clean delivery,
correctly committed (only the two declared files; `live.py`'s `git add` printed the harmless
already-tracked/`.gitignore` advisory since it was created by TASK-3613, confirmed staged as `M` not
untracked). Merge-tier validation: 82/82 passed, 1 skipped (unrelated benchmarks-import quirk).

**Deviations from spec**: none
