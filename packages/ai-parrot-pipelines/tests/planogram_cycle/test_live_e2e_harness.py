"""Offline tests for the planogram live E2E harness (FEAT-612)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[4]
E2E_DIR = REPO_ROOT / "examples" / "planogram" / "e2e"
ADMITTED = [
    f"examples/planogram/e2e/{name}"
    for name in ("conftest.py", "models.py", "runner.py", "test_compliance.py", "README.md")
]
IGNORED = [
    "examples/planogram/e2e/manifest.json",
    "examples/planogram/e2e/private/store_photo.jpg",
    "examples/planogram/e2e/cases/shelves/config.json",
    "examples/planogram/e2e/cases/shelves/definition.json",
    "examples/planogram/e2e/ground_truth.json",
    "examples/planogram/e2e/cache/0123abcd.json",
    "examples/planogram/e2e/out/shelves/compliance.json",
    "examples/planogram/e2e/out/shelves/report.json",
    "examples/planogram/e2e/out/shelves/compliance_render.png",
    "examples/planogram/e2e/plan.pdf",
    "examples/planogram/e2e/local_helper.py",
]


@pytest.fixture(scope="module")
def harness():
    """Load the example modules by path and remove their temporary imports."""
    loaded = []
    for name, path in (
        ("planogram_e2e_models", E2E_DIR / "models.py"),
        ("planogram_e2e_runner", E2E_DIR / "runner.py"),
    ):
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        loaded.append(name)
    try:
        yield sys.modules["planogram_e2e_runner"]
    finally:
        for name in loaded:
            sys.modules.pop(name, None)


def _is_ignored(path: str) -> bool:
    """Return true when git ignores a synthetic path."""
    proc = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT, check=False)
    if proc.returncode not in (0, 1):
        pytest.skip(f"git check-ignore unavailable (rc={proc.returncode})")
    return proc.returncode == 0


@pytest.mark.parametrize("path", ADMITTED)
def test_gitignore_admits_harness_files(path: str) -> None:
    assert not _is_ignored(path)


@pytest.mark.parametrize("path", IGNORED)
def test_gitignore_keeps_private_material_ignored(path: str) -> None:
    assert _is_ignored(path)


def _case(tmp_path: Path, **overrides):
    data = {
        "case_id": "shelves",
        "planogram_type": "product_on_shelves",
        "photos": [tmp_path / "photo.jpg"],
        "config_path": tmp_path / "config.json",
        "ground_truth_path": tmp_path / "truth.json",
        "backend": "fake:model",
        "cache_dir": tmp_path / "cache",
        "output_dir": tmp_path / "output",
    }
    data.update(overrides)
    return data


def _truth(harness, **overrides):
    data = {
        "expected_positions": {"f1": "p1"},
        "expected_occupancy": {},
        "expected_rules": {},
        "overall_score": 0.8,
        "score_tolerance": 0.1,
        "min_coverage": 0.8,
        "max_identity_errors": 0,
        "max_occupancy_errors": 0,
    }
    data.update(overrides)
    return harness.GroundTruth.model_validate(data)


def test_opt_in_default_off(harness):
    assert harness.opt_in_enabled({}) is False
    assert harness.opt_in_enabled({"PARROT_TEST_REAL_LLM": "0"}) is False
    assert harness.opt_in_enabled({"PARROT_TEST_REAL_LLM": "1"}) is True


def test_missing_prerequisites_names_files_and_env(harness, tmp_path):
    case = harness.LiveCase(**_case(tmp_path))
    manifest = harness.LiveManifest(cases=[case], required_env={"fake": ["FAKE_KEY_VAR"]})
    reasons = harness.missing_prerequisites(case, manifest, {})
    assert len(reasons) == 4
    assert all(str(path) in " ".join(reasons) for path in (case.photos[0], case.config_path, case.ground_truth_path))
    assert "FAKE_KEY_VAR" in " ".join(reasons)
    assert harness.missing_prerequisites(case, manifest, {"FAKE_KEY_VAR": "x"}) == [
        reason for reason in reasons if "missing file" in reason
    ]


def test_live_case_rejects_wrong_type_and_implicit_model(harness, tmp_path):
    with pytest.raises(ValidationError):
        harness.LiveCase(**_case(tmp_path, planogram_type="ink_wall"))
    with pytest.raises(ValidationError):
        harness.LiveCase(**_case(tmp_path, backend="fake"))
    case = harness.LiveCase(**_case(tmp_path))
    assert case.max_provider_requests == 64
    assert case.timeout_seconds == 600.0


def test_malformed_manifest_fails(harness, tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{")
    with pytest.raises(json.JSONDecodeError):
        harness.load_manifest(path)
    path.write_text(
        json.dumps({"cases": [{**{key: str(value) for key, value in _case(tmp_path).items()}, "unknown": 1}]})
    )
    with pytest.raises(ValidationError):
        harness.load_manifest(path)
    case = _case(Path("cases"))
    payload = {
        "cases": [
            {key: str(value) for key, value in case.items()},
            {**{key: str(value) for key, value in case.items()}, "case_id": "shelves"},
        ]
    }
    path.write_text(json.dumps(payload))
    with pytest.raises(ValidationError):
        harness.load_manifest(path)


def test_ground_truth_missing_labels_and_bounds(harness):
    valid = {
        "expected_positions": {},
        "expected_occupancy": {},
        "expected_rules": {},
        "overall_score": 0,
        "score_tolerance": 0,
        "min_coverage": 0,
        "max_identity_errors": 0,
        "max_occupancy_errors": 0,
    }
    with pytest.raises(ValidationError):
        harness.GroundTruth.model_validate({key: value for key, value in valid.items() if key != "expected_rules"})
    with pytest.raises(ValidationError):
        harness.GroundTruth.model_validate(valid)
    with pytest.raises(ValidationError):
        harness.GroundTruth.model_validate({**valid, "expected_positions": {"f1": "p1"}, "score_tolerance": 1.5})


def test_compare_passes_and_flags_failures(harness):
    truth = _truth(harness)
    result = {
        "overall_compliance_score": 0.85,
        "coverage": 0.9,
        "position_results": [{"facing_id": "f1", "identity": "p1", "status": "match"}],
        "shelf_scores": [],
    }
    assert harness.compare_ground_truth(result, truth) == []
    failed = {**result, "overall_compliance_score": float("nan"), "coverage": None, "position_results": []}
    violations = harness.compare_ground_truth(failed, truth)
    assert any("score" in item for item in violations)
    assert any("coverage" in item for item in violations)
    assert any("identity" in item for item in violations)


def test_compare_unassessed_rule_is_violation(harness):
    truth = _truth(harness, expected_positions={}, expected_rules={"r1": True})
    result = {
        "overall_compliance_score": 0.8,
        "coverage": 1.0,
        "position_results": [],
        "shelf_scores": [{"rule_results": [{"rule_id": "r1", "assessed": False, "passed": None}]}],
    }
    assert any("rule r1" in item for item in harness.compare_ground_truth(result, truth))
