"""Unit tests for plancheck.report (FEAT-565, TASK-3348)."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import get_args

import numpy as np
import pytest

from plancheck.models import (
    BrandShare,
    ComplianceReport,
    ComplianceSummary,
    ImageInfo,
    PositionResult,
    PositionStatus,
    PriceReading,
    RunInfo,
    Settings,
    ShelfScore,
    Slot,
    SlotObservation,
)
from plancheck.report import STATUS_COLORS, annotate, write_report


def _mini_report(mini_planogram, tmp_path: Path) -> tuple[ComplianceReport, Settings]:
    """One image, two observations (one registered + matched, one unregistered), hand-built."""
    facing = mini_planogram.facings[0]  # shelf=1, slot=1, sku="AC-11", brand="Acme"

    registered_slot = Slot(
        slot_id="img1_r00_s00",
        image_id="img1",
        row=0,
        index=0,
        box=(150, 90, 220, 330),
        tag_id="img1_r00_p00",
        tag_box=(150, 300, 220, 330),
        origin="tag_anchored",
    )
    unregistered_slot = Slot(
        slot_id="img1_r00_s01",
        image_id="img1",
        row=0,
        index=1,
        box=(370, 90, 440, 330),
        tag_id=None,
        tag_box=None,
        origin="gap_filled",
    )
    price = PriceReading(raw="$12.99", amount=Decimal("12.99"), currency="USD", source="ocr", status="read")
    registered_obs = SlotObservation(
        slot=registered_slot,
        reading=None,
        resolved_sku=facing.sku,
        candidate_skus=[facing.sku],
        resolution="direct",
        price=price,
        facing_id=facing.facing_id,
        registration_grade="high",
        issues=[],
    )
    unregistered_obs = SlotObservation(
        slot=unregistered_slot,
        reading=None,
        resolved_sku=None,
        candidate_skus=[],
        resolution="unresolved",
        facing_id=None,
        registration_grade=None,
        issues=[],
    )
    position = PositionResult(
        facing=facing,
        status="match",
        resolution="direct",
        strict_credit=1.0,
        lenient_credit=1.0,
        observed_sku=facing.sku,
        observed_brand=facing.brand,
        price=price,
        price_expected=Decimal("12.99"),
        price_match=True,
        slot_ids=[registered_slot.slot_id],
    )
    shelf_score = ShelfScore(
        shelf=1,
        expected=6,
        covered=1,
        decided=1,
        strict_pct=100.0,
        lenient_pct=100.0,
        occupancy_pct=100.0,
        empty_facing_ids=[],
    )
    brand_share = BrandShare(
        brand="Acme",
        expected_facings=9,
        expected_share=0.5,
        observed_facings=1,
        observed_share=0.11,
        linear_share=0.11,
        occupancy_pct=11.0,
    )
    compliance_summary = ComplianceSummary(
        strict_pct=100.0,
        lenient_pct=100.0,
        coverage=0.05,
        occupancy_pct=50.0,
        products_expected=19,
        products_present=1,
        unexpected_skus=[],
        price=None,
        reference_direct_facings=1,
        strict_pct_direct_reference=100.0,
        lenient_pct_direct_reference=100.0,
    )
    image_hash = "a" * 64
    image_info = ImageInfo(
        image_id="img1",
        path="img1.jpg",
        sha256=image_hash,
        width=1600,
        height=1200,
        tag_rows=3,
        tags=6,
        slots=2,
        registration=None,
    )
    run_info = RunInfo(
        visit_id="visit-1",
        planogram_id=mini_planogram.planogram_id,
        llm="google:gemini-3.8-flash",
        ocr_llm="google:gemini-3.8-flash",
        verify_pass=False,
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:05:00Z",
        errors=[],
        catalog_missing_skus=[],
    )
    report = ComplianceReport(
        run=run_info,
        images=[image_info],
        slots=[registered_obs, unregistered_obs],
        positions=[position],
        shelves=[shelf_score],
        brands=[brand_share],
        compliance=compliance_summary,
        notes=[],
    )
    planogram_path = tmp_path / "planogram.json"
    planogram_path.write_text(json.dumps({"mini": True}), encoding="utf-8")
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    settings = Settings(
        images=["img1.jpg"],
        planogram=str(planogram_path),
        catalog=str(catalog_path),
        output=str(tmp_path / "out"),
        cache_dir=str(tmp_path / "cache"),
    )
    return report, settings


def test_status_colors_cover_all_statuses() -> None:
    assert set(STATUS_COLORS) == set(get_args(PositionStatus)) | {"unregistered"}
    assert all(len(c) == 3 and all(0 <= v <= 255 for v in c) for c in STATUS_COLORS.values())


def test_annotate_returns_copy_same_shape(shelf_image, mini_planogram, tmp_path) -> None:
    report, _ = _mini_report(mini_planogram, tmp_path)
    original = shelf_image.copy()
    result = annotate(shelf_image, report.slots, report.positions)
    assert result.shape == shelf_image.shape
    assert result is not shelf_image
    np.testing.assert_array_equal(shelf_image, original)
    assert not np.array_equal(result, shelf_image)


def test_write_report_refuses_existing_dir(shelf_image, mini_planogram, tmp_path) -> None:
    report, settings = _mini_report(mini_planogram, tmp_path)
    output_dir = Path(settings.output)
    output_dir.mkdir(parents=True)
    sentinel = output_dir / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_report(report, {"img1": shelf_image}, settings, {})
    assert list(output_dir.iterdir()) == [sentinel]


def test_write_report_artifacts(shelf_image, mini_planogram, tmp_path) -> None:
    report, settings = _mini_report(mini_planogram, tmp_path)
    path = write_report(report, {"img1": shelf_image}, settings, {"identify": "v1"})
    output_dir = Path(settings.output)
    assert path == output_dir / "compliance.json"
    assert (output_dir / "annotated_img1.jpg").exists()
    slot_files = sorted((output_dir / "slots").iterdir())
    assert len(slot_files) == len(report.slots)
    tagged = [obs for obs in report.slots if obs.slot.tag_box is not None and obs.slot.tag_id is not None]
    tag_files = sorted((output_dir / "tags").iterdir())
    assert len(tag_files) == len(tagged)
    snapshot = json.loads((output_dir / "run.snapshot.json").read_text(encoding="utf-8"))
    assert set(snapshot) == {"settings", "prompt_versions", "llm", "ocr_llm", "inputs"}
    assert snapshot["inputs"]["prices"] is None
    assert snapshot["inputs"]["images"] == {"img1": report.images[0].sha256}


def test_compliance_json_roundtrip(shelf_image, mini_planogram, tmp_path) -> None:
    report, settings = _mini_report(mini_planogram, tmp_path)
    path = write_report(report, {"img1": shelf_image}, settings, {})
    loaded = ComplianceReport.model_validate_json(path.read_text(encoding="utf-8"))
    assert loaded == report
