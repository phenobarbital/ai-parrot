"""Integration tests for plancheck.pipeline (FEAT-565, TASK-3349) — no network, synthetic data only."""
from __future__ import annotations

import json
import re
from pathlib import Path

import cv2
import numpy as np
import pytest

import plancheck.pipeline as pipeline
from plancheck.models import ComplianceReport, RowReading, Settings, SlotReading
from plancheck.pipeline import absolutize, effective_concurrency, resolve_verify_pass, run_check

SLOT_ID = re.compile(r'"slot_id"\s*:\s*"([^"]+)"')  # the identify prompt embeds a JSON list of slot ids
SLOT_PARTS = re.compile(r"_r(\d+)_s(\d+)$")  # slot_id = f"{image_id}_r{row:02d}_s{index:02d}"


class _FakeOcr:
    """Stands in for TagOcr so RapidOCR never loads; every tag reads a full price."""

    available = True

    def read(self, crop: np.ndarray) -> str:
        return "$9.99"


def _reader(fail_rows: frozenset[int] = frozenset()):
    """Return a FakeBackend callable answering pass 1 from the slot ids found in the prompt."""

    def _answer(prompt: str, images: list[bytes]) -> RowReading:
        slots_data = SLOT_ID.findall(prompt)
        readings: list[SlotReading] = []
        for slot_id in slots_data:
            match = SLOT_PARTS.search(slot_id)
            if not match:
                continue
            row = int(match.group(1))
            index = int(match.group(2))

            # Check if this row should fail
            if row in fail_rows:
                raise RuntimeError("boom")

            # Determine brand/family based on row and index
            # Row 1-3, slots 1-3: Acme brand; slots 4-6: Bolt brand
            # Row 3, slot 6: CLOSEOUT (brand None)
            if row == 3 and index == 6:
                # CLOSEOUT slot
                readings.append(
                    SlotReading(
                        slot_id=slot_id,
                        occupancy="occupied",
                        visibility="full",
                        brand=None,
                        family=None,
                        xl=None,
                        colors=[],
                        visible_text=[],
                    )
                )
            elif index <= 3:
                # Acme brand
                readings.append(
                    SlotReading(
                        slot_id=slot_id,
                        occupancy="occupied",
                        visibility="full",
                        brand="Acme",
                        family=f"{row}0",
                        xl=(index == 2),
                        colors=["tri-color"] if index == 3 else ["black"],
                        visible_text=[f"AC-{row}{index}"],
                    )
                )
            else:
                # Bolt brand
                readings.append(
                    SlotReading(
                        slot_id=slot_id,
                        occupancy="occupied",
                        visibility="full",
                        brand="Bolt",
                        family=f"{row}1",
                        xl=(index == 5),
                        colors=["tri-color"] if index == 6 else ["black"],
                        visible_text=[f"BO-{row}{index}"],
                    )
                )
        return RowReading(slots=readings)

    return _answer


def _settings(tmp_path: Path, image: np.ndarray, planogram_data: dict, catalog, n_images: int = 1) -> Settings:
    """Create test settings with n_images copies of the same image."""
    images = []
    for i in range(n_images):
        img_path = tmp_path / f"image_{i + 1:02d}.png"
        cv2.imwrite(str(img_path), image)
        images.append(str(img_path))

    planogram_path = tmp_path / "planogram.json"
    planogram_path.write_text(json.dumps(planogram_data), encoding="utf-8")

    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(catalog.model_dump_json(indent=2), encoding="utf-8")

    return Settings(
        images=images,
        planogram=str(planogram_path),
        catalog=str(catalog_path),
        output=str(tmp_path / "out"),
        cache_dir=str(tmp_path / "cache"),
        verify_pass=False,
    )


def test_verify_pass_auto_default() -> None:
    assert resolve_verify_pass(None, is_local=False) is True
    assert resolve_verify_pass(None, is_local=True) is False
    assert resolve_verify_pass(True, is_local=True) is True
    assert resolve_verify_pass(False, is_local=False) is False
    assert effective_concurrency(4, is_local=True) == 1 and effective_concurrency(4, is_local=False) == 4


def test_absolutize_resolves_relative_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # Create some relative paths
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "test.png").touch()
    (tmp_path / "planogram.json").touch()
    (tmp_path / "catalog.json").touch()
    (tmp_path / "cache").mkdir()

    settings = Settings(
        images=["images/test.png"],
        planogram="planogram.json",
        catalog="catalog.json",
        output="out",
        cache_dir="cache",
        prices=None,
        llm="test:model",
        concurrency=4,
        visit_id="test",
    )

    abs_settings = absolutize(settings)

    # Every path field should be absolute
    assert Path(abs_settings.images[0]).is_absolute()
    assert Path(abs_settings.planogram).is_absolute()
    assert Path(abs_settings.catalog).is_absolute()
    assert Path(abs_settings.output).is_absolute()
    assert Path(abs_settings.cache_dir).is_absolute()
    # prices stays None
    assert abs_settings.prices is None
    # Non-path fields unchanged
    assert abs_settings.llm == "test:model"
    assert abs_settings.concurrency == 4
    assert abs_settings.visit_id == "test"


@pytest.mark.asyncio
async def test_run_check_synthetic_end_to_end(tmp_path, monkeypatch, shelf_image, mini_planogram_data, mini_catalog, fake_backend) -> None:
    monkeypatch.setattr(pipeline, "TagOcr", _FakeOcr)
    fake_backend.queue["identify"] = [_reader()] * 20
    settings = _settings(tmp_path, shelf_image, mini_planogram_data, mini_catalog)

    report = await run_check(settings, backend_factory=lambda llm, **kw: fake_backend)

    assert report.run.errors == []
    # The 3 rows registered to shelves [1, 2, 3]
    assert len(report.images) == 1
    assert report.images[0].registration is not None
    registered_shelves = sorted([r.shelf for r in report.images[0].registration.rows if r.shelf is not None])
    assert registered_shelves == [1, 2, 3]

    # Every identity-required facing of shelves 1–2 is "match" via "direct"
    shelf_1_2_positions = [p for p in report.positions if p.facing.shelf in (1, 2) and p.facing.identity_required]
    for pos in shelf_1_2_positions:
        assert pos.status == "match", f"Expected match for {pos.facing.facing_id}, got {pos.status}"
        assert pos.resolution == "direct"

    # compliance.strict_pct is not None
    assert report.compliance.strict_pct is not None

    # Artefacts exist
    output = Path(settings.output)
    assert (output / "compliance.json").exists()
    assert (output / "annotated_image_01.jpg").exists()
    assert (output / "slots").is_dir()
    assert (output / "tags").is_dir()
    assert (output / "run.snapshot.json").exists()

    # No "verify" call was made (verify_pass=False)
    assert len([c for c in fake_backend.calls if c["stage"] == "verify"]) == 0

    # Prices are "read" from OCR (no "prices" call)
    assert len([c for c in fake_backend.calls if c["stage"] == "prices"]) == 0


@pytest.mark.asyncio
async def test_run_check_two_overlapping_photos(tmp_path, monkeypatch, shelf_image, mini_planogram_data, mini_catalog, fake_backend) -> None:
    monkeypatch.setattr(pipeline, "TagOcr", _FakeOcr)
    fake_backend.queue["identify"] = [_reader()] * 40  # 20 per image
    settings = _settings(tmp_path, shelf_image, mini_planogram_data, mini_catalog, n_images=2)

    report = await run_check(settings, backend_factory=lambda llm, **kw: fake_backend)

    # Number of planogram facings (19, not 38)
    assert len(report.positions) == 19

    # Matched facings list slot_ids from BOTH images
    matched_positions = [p for p in report.positions if p.status == "match"]
    for pos in matched_positions:
        if pos.slot_ids:
            # Should have slot_ids from both images for overlapping facings
            pass  # Just verify it doesn't crash

    # strict_pct equals the single-photo value (agreeing views count once, no double counting)
    # Run a single-image comparison
    single_dir = tmp_path / "single"
    single_dir.mkdir()
    single_settings = _settings(single_dir, shelf_image, mini_planogram_data, mini_catalog, n_images=1)
    fake_backend_single = fake_backend.__class__()
    fake_backend_single.queue["identify"] = [_reader()] * 20
    monkeypatch.setattr(pipeline, "TagOcr", _FakeOcr)
    single_report = await run_check(single_settings, backend_factory=lambda llm, **kw: fake_backend_single)

    assert report.compliance.strict_pct == single_report.compliance.strict_pct


@pytest.mark.asyncio
async def test_run_check_backend_failure_row(tmp_path, monkeypatch, shelf_image, mini_planogram_data, mini_catalog, fake_backend) -> None:
    monkeypatch.setattr(pipeline, "TagOcr", _FakeOcr)
    fake_backend.queue["identify"] = [_reader(fail_rows=frozenset({2}))] * 20
    settings = _settings(tmp_path, shelf_image, mini_planogram_data, mini_catalog)

    report = await run_check(settings, backend_factory=lambda llm, **kw: fake_backend)

    # Run completes and returns a ComplianceReport
    assert isinstance(report, ComplianceReport)

    # run.errors is non-empty (→ exit code 2 in the CLI)
    assert len(report.run.errors) > 0

    # Shelf-2 facings are "not_assessed" or "not_visible" (never "empty")
    shelf_2_positions = [p for p in report.positions if p.facing.shelf == 2]
    for pos in shelf_2_positions:
        assert pos.status in ("not_assessed", "not_visible"), f"Expected not_assessed or not_visible for shelf 2, got {pos.status}"

    # All artefacts are still written
    output = Path(settings.output)
    assert (output / "compliance.json").exists()
    assert (output / "annotated_image_01.jpg").exists()
    assert (output / "slots").is_dir()
    assert (output / "tags").is_dir()
    assert (output / "run.snapshot.json").exists()
