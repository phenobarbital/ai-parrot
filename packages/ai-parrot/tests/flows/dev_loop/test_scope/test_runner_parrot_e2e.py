"""Tests for the parrot-e2e runner adapter (FEAT-709 M4)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from parrot.flows.dev_loop.test_scope.runners.parrot_e2e import ADAPTER, parse_e2e_verdict

FIXTURE = Path(__file__).parent / "fixtures" / "e2e-verdict.json"


def test_fixture_counts_and_failure_text() -> None:
    report = parse_e2e_verdict(FIXTURE, exit_code=1, suite="parrot-e2e:x", duration_s=3.0, timed_out=False)
    assert (report.tests, report.passed, report.failed, report.skipped) == (3, 1, 1, 1)
    assert report.status == "failed"
    assert "boom" in report.failure_text["tests/e2e/test_a.py::test_bad"]


def test_missing_file_is_no_report() -> None:
    report = parse_e2e_verdict(
        Path("/nonexistent/e2e-verdict.json"), exit_code=0, suite="s", duration_s=0.0, timed_out=False
    )
    assert report.status == "no_report"
    assert parse_e2e_verdict(None, exit_code=0, suite="s", duration_s=0.0, timed_out=True).status == "timed_out"


def test_invalid_json_is_no_report(tmp_path: Path) -> None:
    bad = tmp_path / "e2e-verdict.json"
    bad.write_text("{not json", encoding="utf-8")
    assert parse_e2e_verdict(bad, exit_code=0, suite="s", duration_s=0.0, timed_out=False).status == "no_report"


def test_pointer_fallback(tmp_path: Path) -> None:
    run_dir = tmp_path / "e2e" / "runs" / "run-0001"
    run_dir.mkdir(parents=True)
    shutil.copy(FIXTURE, run_dir / "e2e-verdict.json")
    (tmp_path / "e2e" / "latest.json").write_text(json.dumps({"run_id": "run-0001"}), encoding="utf-8")
    report = ADAPTER.parse_report(
        report_path=tmp_path / "e2e" / "e2e-verdict.json",
        exit_code=1,
        stdout="",
        stderr="",
        duration_s=1.0,
        timed_out=False,
        suite="s",
    )
    assert report.failed == 1


def test_tiers_and_settings(tmp_path: Path) -> None:
    assert "task" not in ADAPTER.default_tiers
    (tmp_path / "plan.json").write_text("{}", encoding="utf-8")
    assert ADAPTER.validate_settings({"plan": "plan.json"}, worktree=tmp_path) == []
    assert ADAPTER.validate_settings({}, worktree=tmp_path)
    assert ADAPTER.validate_settings({"plan": "nope.json"}, worktree=tmp_path)
    assert any(
        "task tier forbidden" in p
        for p in ADAPTER.validate_settings({"plan": "plan.json", "tiers": "task,merge"}, worktree=tmp_path)
    )


def test_matches_and_argv() -> None:
    assert ADAPTER.matches(["parrot", "e2e", "run"])
    assert not ADAPTER.matches(["pytest"])
    inv = ADAPTER.invocation(
        [],
        distribution="d",
        worktree=Path("."),
        settings={"plan": "p.json", "owner_id": "o"},
        policy=None,
        report_path="r",
    )  # type: ignore[arg-type]
    assert inv.argv == ("parrot", "e2e", "run", "--plan", "p.json", "--owner-id", "o")
