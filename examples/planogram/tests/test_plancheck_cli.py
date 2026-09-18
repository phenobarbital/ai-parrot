"""Unit tests for the planogram_check CLI (FEAT-565, TASK-3350) — the pipeline is always faked."""

from __future__ import annotations

import json
import logging
import types
from pathlib import Path

import pytest

import planogram_check
from plancheck.reference import DESCRIPTOR_FIELDS


def _fake_report(errors: list[str]) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        run=types.SimpleNamespace(errors=errors),
        compliance=types.SimpleNamespace(strict_pct=50.0, lenient_pct=75.0, coverage=0.9),
    )


def _patch_run(monkeypatch, *, errors: list[str] | None = None, raises: Exception | None = None) -> list:
    """Replace planogram_check.run_check; return the list that captures the Settings it received."""
    seen: list = []

    async def _run(settings, **_kw):
        seen.append(settings)
        if raises is not None:
            raise raises
        return _fake_report(errors or [])

    monkeypatch.setattr(planogram_check, "run_check", _run)
    return seen


def _run_args(tmp_path: Path) -> list[str]:
    # Create test files
    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    (img_dir / "a.png").write_bytes(b"fake image data")

    planogram_file = tmp_path / "planogram.json"
    planogram_file.write_text('{"planogram": {}, "shelves": []}', encoding="utf-8")

    return [
        "--images-dir",
        str(img_dir),
        "--planogram",
        str(planogram_file),
        "--output",
        str(tmp_path / "out"),
        "--cache-dir",
        str(tmp_path / "cache"),
    ]


def test_cli_has_no_catalog_option(tmp_path) -> None:
    code = planogram_check.main(["--catalog", str(tmp_path / "catalog.json")])
    assert code == 1  # unknown option: descriptors live in the planogram now


def test_cli_exit_codes(tmp_path, monkeypatch) -> None:
    args = _run_args(tmp_path)

    # Test successful run
    seen = _patch_run(monkeypatch, errors=[])
    code = planogram_check.main(args)
    assert code == 0
    assert len(seen) == 1

    # Test with errors
    seen = _patch_run(monkeypatch, errors=["row failed"])
    code = planogram_check.main(args)
    assert code == 2

    # Test FileExistsError
    seen = _patch_run(monkeypatch, raises=FileExistsError("x"))
    code = planogram_check.main(args)
    assert code == 1

    # Test ValueError
    seen = _patch_run(monkeypatch, raises=ValueError("x"))
    code = planogram_check.main(args)
    assert code == 1

    # Test unknown flag
    code = planogram_check.main(["--unknown-flag"])
    assert code == 1


def test_cli_verify_pass_tristate() -> None:
    parser = planogram_check.build_parser()
    assert parser.parse_args([]).verify_pass is None
    assert parser.parse_args(["--verify-pass"]).verify_pass is True
    assert parser.parse_args(["--no-verify-pass"]).verify_pass is False
    assert parser.parse_args([]).marks is True and parser.parse_args(["--no-marks"]).marks is False


def test_cli_settings_passthrough(tmp_path, monkeypatch) -> None:
    args = _run_args(tmp_path)
    args.extend(
        [
            "--llm",
            "llamacpp:occupancy",
            "--base-url",
            "http://127.0.0.1:8089/v1",
            "--roi",
            "0.1",
            "0",
            "0.9",
            "1",
            "--no-marks",
            "--visit-id",
            "v1",
        ]
    )

    seen = _patch_run(monkeypatch, errors=[])
    code = planogram_check.main(args)
    assert code == 0
    assert len(seen) == 1

    settings = seen[0]
    assert settings.llm == "llamacpp:occupancy"
    assert settings.base_url == "http://127.0.0.1:8089/v1"
    assert settings.roi == (0.1, 0.0, 0.9, 1.0)
    assert settings.marks is False
    assert settings.visit_id == "v1"
    assert settings.verify_pass is None
    assert all(Path(p).is_absolute() for p in settings.images)
    assert len(settings.images) == 1


def test_cli_images_mutually_exclusive_and_bad_roi(tmp_path, monkeypatch) -> None:
    args = _run_args(tmp_path)

    # Test mutually exclusive
    args_with_both = args.copy()
    args_with_both.extend(["--images", str(tmp_path / "a.png")])
    code = planogram_check.main(args_with_both)
    assert code == 1

    # Test bad ROI
    args_with_bad_roi = args.copy()
    args_with_bad_roi.extend(["--roi", "0.9", "0", "0.1", "1"])
    code = planogram_check.main(args_with_bad_roi)
    assert code == 1

    # Test bad concurrency
    args_with_bad_concurrency = args.copy()
    args_with_bad_concurrency.extend(["--concurrency", "0"])
    code = planogram_check.main(args_with_bad_concurrency)
    assert code == 1


def test_cli_empty_images_dir(tmp_path, monkeypatch) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    args = [
        "--images-dir",
        str(empty_dir),
        "--planogram",
        str(tmp_path / "planogram.json"),
        "--output",
        str(tmp_path / "out"),
    ]
    (tmp_path / "planogram.json").write_text('{"planogram": {}, "shelves": []}', encoding="utf-8")

    seen = _patch_run(monkeypatch, errors=[])
    code = planogram_check.main(args)
    assert code == 1
    assert len(seen) == 0

    # Test with non-image files
    (empty_dir / "notes.txt").write_text("notes")
    code = planogram_check.main(args)
    assert code == 1


def test_cli_init_descriptors(tmp_path, mini_planogram_data) -> None:
    for shelf in mini_planogram_data["shelves"]:
        for product in shelf["products"].values():
            for name in DESCRIPTOR_FIELDS:
                product.pop(name, None)
    planogram_file = tmp_path / "planogram.json"
    planogram_file.write_text(json.dumps(mini_planogram_data), encoding="utf-8")

    assert planogram_check.main(["--planogram", str(planogram_file), "--init-descriptors"]) == 0
    written = json.loads(planogram_file.read_text(encoding="utf-8"))
    positions = [p for shelf in written["shelves"] for p in shelf["products"].values()]
    assert all(p[name] is None for p in positions for name in DESCRIPTOR_FIELDS)

    missing = tmp_path / "nope.json"
    assert planogram_check.main(["--planogram", str(missing), "--init-descriptors"]) == 1
