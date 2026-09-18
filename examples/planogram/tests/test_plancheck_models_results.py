"""TASK-3338: result models round-trip through JSON and keep their defaults."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from plancheck.models import (
    ComplianceReport,
    ComplianceSummary,
    PositionResult,
    PriceReading,
    RunInfo,
    ScoringWeights,
    Settings,
    Slot,
    SlotObservation,
)


def _settings(**overrides) -> Settings:
    base = {"images": ["/a.jpg"], "planogram": "/p.json", "output": "/out", "cache_dir": "/cache"}
    return Settings(**{**base, **overrides})


def test_settings_defaults() -> None:
    """Defaults fixed by the spec: gemini-3.8-flash, verify_pass None (auto), marks on, weights .5/.5/.5/1."""
    settings = _settings()
    assert settings.llm == "google:gemini-3.8-flash"
    assert settings.verify_pass is None
    assert settings.marks is True
    assert settings.concurrency == 4
    assert settings.work_width == 2048
    weights = settings.weights
    assert weights.misplaced == 0.5
    assert weights.variant_unresolved == 0.5
    assert weights.inferred_present == 0.5
    assert weights.verified_by_expectation == 1.0


def test_settings_bounds() -> None:
    with pytest.raises(ValidationError):
        _settings(concurrency=0)
    with pytest.raises(ValidationError):
        _settings(concurrency=17)
    with pytest.raises(ValidationError):
        _settings(work_width=100)
    with pytest.raises(ValidationError):
        _settings(bogus=1)  # type: ignore[call-arg]


def test_slot_observation_defaults() -> None:
    slot = Slot(
        slot_id="img_r00_s00",
        image_id="img",
        row=0,
        index=0,
        box=(0, 0, 10, 10),
        origin="tag_anchored",
    )
    obs_1 = SlotObservation(slot=slot)
    obs_2 = SlotObservation(slot=slot)

    assert obs_1.resolution == "unresolved"
    assert obs_1.price.status == "not_assessed"
    assert obs_1.facing_id is None
    assert obs_1.candidate_skus == []
    assert obs_1.issues == []

    # default_factory lists must not be shared between instances
    obs_1.candidate_skus.append("AC-11")
    obs_1.issues.append("bogus")
    assert obs_2.candidate_skus == []
    assert obs_2.issues == []


def test_report_roundtrip_json(mini_planogram) -> None:
    """ComplianceReport → model_dump(mode='json') → model_validate keeps Decimals and literals."""
    facing = mini_planogram.facings[0]
    position = PositionResult(
        facing=facing,
        status="match",
        resolution="direct",
        strict_credit=1.0,
        lenient_credit=1.0,
        observed_sku=facing.sku,
        observed_brand=facing.brand,
        price=PriceReading(raw="$45.99", amount=Decimal("45.99"), currency="USD", source="llm", status="read"),
        price_expected=Decimal("45.99"),
        price_match=True,
        slot_ids=["img_r00_s00"],
    )
    report = ComplianceReport(
        run=RunInfo(
            visit_id="visit-1",
            planogram_id=mini_planogram.planogram_id,
            llm="google:gemini-3.8-flash",
            ocr_llm="google:gemini-3.8-flash",
            verify_pass=True,
            started_at="2026-09-18T00:00:00Z",
            finished_at="2026-09-18T00:01:00Z",
            errors=[],
            undescribed_skus=[],
        ),
        images=[],
        slots=[],
        positions=[position],
        shelves=[],
        brands=[],
        compliance=ComplianceSummary(
            strict_pct=100.0,
            lenient_pct=100.0,
            coverage=1.0,
            occupancy_pct=100.0,
            products_expected=1,
            products_present=1,
            unexpected_skus=[],
            price=None,
            reference_direct_facings=0,
            strict_pct_direct_reference=100.0,
            lenient_pct_direct_reference=100.0,
        ),
        notes=[],
    )

    dumped = report.model_dump(mode="json")
    serialized = json.dumps(dumped)  # must not raise (Decimal serialised as string)

    restored = ComplianceReport.model_validate(json.loads(serialized))
    assert restored.positions[0].price.amount == Decimal("45.99")
    assert restored.positions[0].price_expected == Decimal("45.99")
    assert restored.run.registration_method == "auto_alignment"


def test_run_info_constants() -> None:
    run = RunInfo(
        visit_id="visit-1",
        planogram_id="mini",
        llm="google:gemini-3.8-flash",
        ocr_llm="google:gemini-3.8-flash",
        verify_pass=True,
        started_at="2026-09-18T00:00:00Z",
        finished_at="2026-09-18T00:01:00Z",
        errors=[],
        undescribed_skus=[],
    )
    assert run.registration_method == "auto_alignment"

    with pytest.raises(ValidationError):
        RunInfo(
            visit_id="visit-1",
            planogram_id="mini",
            llm="google:gemini-3.8-flash",
            ocr_llm="google:gemini-3.8-flash",
            verify_pass=True,
            started_at="2026-09-18T00:00:00Z",
            finished_at="2026-09-18T00:01:00Z",
            errors=[],
            undescribed_skus=[],
            registration_method="manual",  # type: ignore[arg-type]
        )


def test_position_status_rejects_unknown(mini_planogram) -> None:
    facing = mini_planogram.facings[0]
    with pytest.raises(ValidationError):
        PositionResult(
            facing=facing,
            status="reviewed",  # type: ignore[arg-type]
            strict_credit=0.0,
            lenient_credit=0.0,
        )

    for status in ("not_assessed", "not_visible"):
        result = PositionResult(
            facing=facing,
            status=status,
            strict_credit=0.0,
            lenient_credit=0.0,
        )
        assert result.status == status
