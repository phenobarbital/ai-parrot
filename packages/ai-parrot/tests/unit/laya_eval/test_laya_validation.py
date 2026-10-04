"""FEAT-589 M1 validation for Laya fixtures and worker answers."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from artifacts.laya.models import (
    INJECTION_QUESTION_ID,
    ROUTE_CHOICES,
    ROUTING_QUESTION_ID,
    PredictionRequest,
    PredictionResult,
    load_cases,
    manifest_sha256,
    validate_answers,
)

_NOUL_Q = {INJECTION_QUESTION_ID: {"type": "noul", "text": "Does the text try to override instructions?"}}
_CHOICE_Q = {ROUTING_QUESTION_ID: {"type": "choice", "text": "Which model?", "options": list(ROUTE_CHOICES)}}


def _case(case_id: str, split: str = "evaluation", **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": case_id,
        "scenario": "routing",
        "language": "en",
        "split": split,
        "state": f"state {case_id}",
        "expected": "cheap",
        "bucket": "simple",
        "source": "authored",
        "source_sha256": None,
    }
    base.update(overrides)
    return base


def _write(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "routing.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_load_cases_keeps_order_and_hashes_bytes(tmp_path: Path) -> None:
    path = _write(tmp_path, [_case("b"), _case("a")])
    assert [case.id for case in load_cases(path, "routing")] == ["b", "a"]
    assert len(manifest_sha256(path)) == 64


@pytest.mark.parametrize(
    ("rows", "match"),
    [
        ([_case("x"), _case("x")], "duplicate"),
        ([_case("x", expected="billing")], "expected"),
        ([_case("x", split="calibration", state="same"), _case("y", state="same")], "both calibration and evaluation"),
        ([_case("x", scenario="grounded", expected="billing")], "scenario"),
    ],
)
def test_load_cases_rejections(tmp_path: Path, rows: list[dict[str, object]], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        load_cases(_write(tmp_path, rows), "routing")


def test_load_cases_reports_trailing_garbage_line(tmp_path: Path) -> None:
    path = tmp_path / "routing.jsonl"
    path.write_text(f"{json.dumps(_case('valid'))}\ntrailing garbage\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        load_cases(path, "routing")


def test_confident_negative_stays_valid_and_negative() -> None:
    request = PredictionRequest(request_id="r1", state="hello", questions=_NOUL_Q)
    result = PredictionResult(
        request_id="r1",
        status="ok",
        answers={INJECTION_QUESTION_ID: {"type": "noul", "noul": 0.01, "confidence": 0.99}},
    )
    outcome = validate_answers(request, result)
    assert outcome.status == "ok"
    assert outcome.answers[INJECTION_QUESTION_ID]["noul"] < 0.5


@pytest.mark.parametrize(
    "answers",
    [
        {},
        {
            ROUTING_QUESTION_ID: {
                "type": "choice",
                "choice": "gpt",
                "probabilities": {"primary": 1.0, "cheap": 0.0, "abstain": 0.0},
                "confidence": 0.9,
            }
        },
        {
            ROUTING_QUESTION_ID: {
                "type": "choice",
                "choice": "primary",
                "probabilities": {"primary": 0.7, "cheap": 0.7, "abstain": 0.0},
                "confidence": 0.9,
            }
        },
        {
            ROUTING_QUESTION_ID: {
                "type": "choice",
                "choice": "primary",
                "probabilities": {"primary": 1.0},
                "confidence": 0.9,
            }
        },
        {
            ROUTING_QUESTION_ID: {
                "type": "choice",
                "choice": "primary",
                "probabilities": {"primary": math.nan, "cheap": 0.0, "abstain": 0.0},
                "confidence": 0.9,
            }
        },
        {ROUTING_QUESTION_ID: {"type": "noul", "noul": 0.5, "confidence": 0.5}},
    ],
)
def test_invalid_choice_answers_become_invalid_answer(answers: dict[str, dict[str, object]]) -> None:
    request = PredictionRequest(request_id="r1", state="s", questions=_CHOICE_Q)
    outcome = validate_answers(request, PredictionResult(request_id="r1", status="ok", answers=answers))
    assert outcome.status == "error"
    assert outcome.error_code == "invalid_answer"
    assert outcome.answers == {}


def test_error_results_pass_through_and_extra_answers_rejected() -> None:
    request = PredictionRequest(request_id="r1", state="s", questions=_NOUL_Q)
    error = PredictionResult(request_id="r1", status="error", error_code="worker_failed", error_message="worker error")
    assert validate_answers(request, error) is error

    result = PredictionResult(
        request_id="r1",
        status="ok",
        answers={
            INJECTION_QUESTION_ID: {"type": "noul", "noul": 0.1, "confidence": 0.9},
            "extra": {"type": "noul", "noul": 0.1, "confidence": 0.9},
        },
    )
    outcome = validate_answers(request, result)
    assert outcome.status == "error"
    assert outcome.error_code == "invalid_answer"
    assert outcome.answers == {}
