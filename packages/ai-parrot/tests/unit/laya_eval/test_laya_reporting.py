"""FEAT-589 M4 — reporting: nearest-rank percentiles, confusion matrix, nulls, failed samples, no overwrite."""
from __future__ import annotations

from pathlib import Path

import pytest

from artifacts.laya.models import EvaluationConfig, EvaluationReport, RouteDecision, SampleResult
from artifacts.laya.reporting import confusion_matrix, nearest_rank_percentile, summarize, write_report


def _s(
    case_id,
    expected,
    predicted=None,
    status="ok",
    repeat=0,
    error_code=None,
    arm="local",
    quality_pass=None,
    actual_model=None,
    usage=None,
    fallback_metadata=None,
    decision=None,
    scenario="injection",
    **kw,
) -> SampleResult:
    return SampleResult(
        case_id=case_id,
        scenario=scenario,
        repeat=repeat,
        expected=expected,
        predicted=predicted,
        status=status,
        error_code=error_code,
        arm=arm,
        quality_pass=quality_pass,
        actual_model=actual_model,
        usage=usage,
        fallback_metadata=fallback_metadata,
        decision=decision,
        timings_ms=kw.pop("timings", {}),
        **kw,
    )


def test_nearest_rank_matches_documented_definition():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert nearest_rank_percentile(vals, 50) == 30.0 and nearest_rank_percentile(vals, 95) == 50.0
    assert nearest_rank_percentile([7.0], 95) == 7.0 and nearest_rank_percentile([], 50) is None


def test_confusion_matrix_keeps_errors_in_a_visible_column():
    m = confusion_matrix(
        [
            _s("a", "clean", "clean"),
            _s("b", "injection", "clean"),
            _s("c", "injection", status="error", error_code="inference_timeout"),
        ],
        ("injection", "clean"),
    )
    assert m["clean"]["clean"] == 1 and m["injection"]["clean"] == 1 and m["injection"]["__error__"] == 1


def test_summarize_counts_failed_samples_in_denominator_and_uses_repeat_zero_only():
    samples = [
        _s("a", "clean", "clean", timings={"inference_ms": 5.0}),
        _s("a", "clean", "injection", repeat=1, timings={"inference_ms": 6.0}),
        _s("b", "injection", status="error", error_code="worker_failed"),
    ]
    block = summarize(samples)["scenarios"]["injection"]
    assert block["n_cases"] == 2 and block["n_error"] == 1 and block["accuracy"] == 0.5
    assert block["prediction_flips"] == 1 and block["timings"]["inference_ms"]["n"] == 2
    assert block["errors_by_code"] == {"worker_failed": 1}


def test_unavailable_values_are_null_not_zero():
    block = summarize([_s("a", "clean", "clean")])["scenarios"]["injection"]
    assert block["timings"]["roundtrip_ms"]["p50_ms"] is None and block["timings"]["roundtrip_ms"]["n"] == 0


def test_write_report_refuses_non_empty_directory(tmp_path):
    cfg = EvaluationConfig(
        worker_python=Path("/bin/python3"),
        checkpoint_path=tmp_path,
        checkpoint_revision="r",
        output_dir=tmp_path / "out",
    )
    report = EvaluationReport(status="incomplete", config=cfg, limitations=["no worker"])
    json_path, md_path = write_report(report, tmp_path / "out")
    assert json_path.exists() and md_path.read_text().startswith("# Laya CPU evaluation")
    with pytest.raises(FileExistsError):
        write_report(report, tmp_path / "out")


def test_routing_block_cost_is_null_without_prices_and_fallbacks_listed(tmp_path):
    """Routing samples for arms primary/routed with usage + one fallback_metadata={"used_fallback_model": True}."""
    # Create routing scenario samples with local arm and routing arms (primary/routed)
    samples = [
        # Local repeat-0 with routing decision
        _s(
            "route1",
            "primary",
            "primary",
            scenario="routing",
            arm="local",
            repeat=0,
            decision=RouteDecision(choice="primary", reason="test"),
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            actual_model="anthropic:opus-5",
            quality_pass=True,
        ),
        # Primary arm sample
        _s(
            "route1",
            "primary",
            "primary",
            scenario="routing",
            arm="primary",
            repeat=0,
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            actual_model="anthropic:opus-5",
            quality_pass=True,
        ),
        # Routed arm sample with fallback
        _s(
            "route2",
            "cheap",
            "cheap",
            scenario="routing",
            arm="routed",
            repeat=0,
            usage={"prompt_tokens": 50, "completion_tokens": 25},
            actual_model="anthropic:haiku",
            fallback_metadata={"used_fallback_model": True},
            quality_pass=True,
        ),
    ]

    # Inject scenario type
    for s in samples:
        s.scenario = "routing"

    metrics = summarize(samples, prices=None)
    routing_metrics = metrics["scenarios"]["routing"]["routing"]

    # Check cost is None without prices
    assert routing_metrics["arms"]["primary"]["cost"] is None
    assert routing_metrics["arms"]["routed"]["cost"] is None

    # Check fallback samples are listed
    assert "route2" in routing_metrics["arms"]["routed"]["fallback_samples"]
    assert len(routing_metrics["arms"]["primary"]["fallback_samples"]) == 0


def test_render_markdown_contains_required_disclaimers(tmp_path):
    """Markdown report contains smoke dataset disclaimer and logical-call cap statement."""
    cfg = EvaluationConfig(
        worker_python=Path("/bin/python3"),
        checkpoint_path=tmp_path,
        checkpoint_revision="r",
        output_dir=tmp_path / "out",
    )
    report = EvaluationReport(
        status="complete",
        config=cfg,
        limitations=["test limitation"],
        metrics={"percentile_definition": "test", "scenarios": {}},
    )
    md = write_report(report, tmp_path / "out")[1]
    content = md.read_text()
    assert "Smoke datasets" in content
    assert "not an HTTP-attempt or money cap" in content
