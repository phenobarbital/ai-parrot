"""FEAT-589 M2 — context budget preflight: boundary passes, overflow rejects, nothing is truncated."""
from __future__ import annotations

import io
import json
from typing import Any

from artifacts.laya import worker

_COUNT = lambda s: len(s.split())  # noqa: E731 — deterministic fake tokenizer
_Q = {"category": {"type": "choice", "text": "which label", "options": ["billing", "technical"]}}


def test_exact_boundary_is_allowed():
    state = "one two three"
    budget = _COUNT(state) + _COUNT("which label") + 2
    assert worker.check_context_budget(_COUNT, state, _Q, budget) is None


def test_one_over_is_rejected_with_counts_in_message():
    state = "one two three"
    budget = _COUNT(state) + _COUNT("which label") + 2 - 1
    msg = worker.check_context_budget(_COUNT, state, _Q, budget)
    assert msg and str(budget) in msg and "truncated" in msg


def test_unknown_limit_skips_check():
    assert worker.check_context_budget(_COUNT, "x " * 10_000, _Q, None) is None


def test_overflow_surfaces_as_context_overflow_result_and_state_untouched():
    class _Agent:
        def __init__(self):
            self.seen = []

        def system_one(self, state, questions):
            self.seen.append(state)
            return {}

    agent = _Agent()
    predictor = worker.LayaPredictor(agent, max_input_tokens=3, count_tokens=_COUNT)
    req = json.dumps({"request_id": "big", "state": "a b c d e f", "questions": {"q": {"type": "noul", "text": "t"}}})
    out = io.StringIO()
    worker.serve(io.StringIO(req + "\n"), predictor, out)
    rec = json.loads(out.getvalue())
    assert rec["error_code"] == "context_overflow" and rec["request_id"] == "big"
    assert agent.seen == []  # inference never ran; nothing was truncated to make it fit


def test_fitting_request_reaches_the_agent_untruncated(monkeypatch):
    class _Agent:
        def __init__(self):
            self.seen = []

        def system_one(self, state, questions):
            self.seen.append(state)
            return {"q": {"type": "noul", "noul": 0.9, "confidence": 0.95}}

    agent = _Agent()
    predictor = worker.LayaPredictor(agent, max_input_tokens=100, count_tokens=_COUNT)

    # Mock _to_laya_questions and _from_laya_answers to identity fakes
    monkeypatch.setattr(worker, "_to_laya_questions", lambda q: q)
    monkeypatch.setattr(worker, "_from_laya_answers", lambda q, r: r)

    state = "a b c d e f"
    questions = {"q": {"type": "noul", "text": "t"}}
    res = predictor.predict(state, questions)
    assert agent.seen == [state]
    assert res == {"q": {"type": "noul", "noul": 0.9, "confidence": 0.95}}
