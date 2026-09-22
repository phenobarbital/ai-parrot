"""FEAT-589 M1 — record models: forbidden extras, finite numbers, label membership, error codes."""
from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from artifacts.laya.models import (
    ERROR_CODES,
    GROUNDED_LABELS,
    ROUTE_CHOICES,
    EvaluationCase,
    EvaluationConfig,
    EvaluationReport,
    PredictionResult,
    RouteDecision,
    SampleResult,
)


def _config(**overrides: object) -> EvaluationConfig:
    base = dict(
        worker_python=Path("/usr/bin/python3"),
        checkpoint_path=Path("/tmp/ckpt"),
        checkpoint_revision="abc123",
        output_dir=Path("/tmp/out"),
    )
    base.update(overrides)
    return EvaluationConfig(**base)


def test_error_codes_are_the_twelve_spec_codes() -> None:
    assert len(ERROR_CODES) == 12 and len(set(ERROR_CODES)) == 12
    assert "context_overflow" in ERROR_CODES and "call_cap_reached" in ERROR_CODES


def test_config_defaults_and_ranges() -> None:
    cfg = _config()
    assert cfg.primary_label == "anthropic:opus-5"
    assert cfg.injection_threshold == 0.5
    assert cfg.routing_threshold == 0.8
    with pytest.raises(ValidationError):
        _config(injection_threshold=1.5)
    with pytest.raises(ValidationError):
        _config(repeats=0)
    with pytest.raises(ValidationError):
        _config(unknown_field=1)


def test_case_label_must_belong_to_scenario() -> None:
    kwargs = dict(
        id="c1",
        scenario="routing",
        language="en",
        split="evaluation",
        state="hi",
        bucket="simple",
        source="authored",
    )
    assert EvaluationCase(expected=ROUTE_CHOICES[0], **kwargs).expected == "primary"
    with pytest.raises(ValidationError):
        EvaluationCase(expected=GROUNDED_LABELS[0], **kwargs)
    with pytest.raises(ValidationError):
        EvaluationCase(expected="primary", **{**kwargs, "language": "es"})


def test_finite_numbers_are_enforced() -> None:
    with pytest.raises(ValidationError):
        RouteDecision(choice="primary", confidence=math.nan, reason="x")
    with pytest.raises(ValidationError):
        PredictionResult(request_id="r", status="ok", inference_ms=math.inf)
    with pytest.raises(ValidationError):
        SampleResult(
            case_id="c",
            scenario="injection",
            repeat=0,
            expected="clean",
            status="ok",
            timings_ms={"worker": math.nan},
        )


def test_prediction_result_error_code_consistency() -> None:
    with pytest.raises(ValidationError):
        PredictionResult(request_id="r", status="error")
    with pytest.raises(ValidationError):
        PredictionResult(request_id="r", status="ok", error_code=ERROR_CODES[0])
    with pytest.raises(ValidationError):
        PredictionResult(request_id="r", status="error", error_code="unknown")
    assert PredictionResult(request_id="r", status="error", error_code=ERROR_CODES[0]).error_code == ERROR_CODES[0]


def test_sample_result_nullable_fields_default_none() -> None:
    sample = SampleResult(case_id="c", scenario="injection", repeat=0, expected="clean", status="ok")
    assert sample.predicted is None
    assert sample.actual_model is None
    assert sample.usage is None
    assert sample.quality_pass is None


def test_report_round_trips_json_with_empty_samples() -> None:
    report = EvaluationReport(status="complete", config=_config())
    parsed = EvaluationReport.model_validate_json(report.model_dump_json())
    assert parsed == report
    assert parsed.samples == []
