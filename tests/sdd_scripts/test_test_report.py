"""Tests for the FEAT-695 test-report CLI."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.sdd import test_report


def _write_index(path: Path, task_count: int = 1) -> None:
    """Write a feature index with deterministic task identifiers."""
    payload = {
        "feature_id": "FEAT-695",
        "tasks": [{"id": f"TASK-{number}"} for number in range(task_count)],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize(("task_count", "expected"), [(10, "rerun"), (11, "skip (11 tasks > 10)")])
def test_decide_rerun_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str], task_count: int, expected: str) -> None:
    """The task-count threshold produces the exact deterministic decision text."""
    index = tmp_path / "index.json"
    _write_index(index, task_count)

    assert test_report.main(["decide-rerun", "--index", str(index)]) == 0
    assert capsys.readouterr().out.strip() == expected


def test_render_cli_uses_fixture_record_and_final_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Render includes recorded task evidence and the final worktree HEAD."""
    index = tmp_path / "index.json"
    _write_index(index)
    reports = tmp_path / "reports"
    monkeypatch.setenv("SDD_TEST_REPORT_DIR", str(reports))
    report_mod = test_report._load_report()
    result = report_mod.SuiteResult(
        suite="ai-parrot",
        tests=2,
        passed=2,
        failed=0,
        errors=0,
        skipped=0,
        duration_s=0.25,
        exit_code=0,
        argv=("pytest",),
        status="ok",
    )
    report_mod.append_suite(
        "FEAT-695",
        "TASK-0",
        result,
        head_sha="recorded-head",
        base_ref="dev",
        tier="task",
        source="test",
    )
    monkeypatch.setattr(
        test_report.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="final-head\\n"),
    )

    assert test_report.main(["render", "--index", str(index), "--worktree", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "## Tests" in output
    assert "TASK-0 (stale): 1 suite(s), 1 attempt(s)" in output


def test_render_cli_surfaces_corrupt_record_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Corrupt record files are reported in a Notes subsection, not silently dropped."""
    index = tmp_path / "index.json"
    _write_index(index)
    reports = tmp_path / "reports"
    monkeypatch.setenv("SDD_TEST_REPORT_DIR", str(reports))
    (reports / "FEAT-695").mkdir(parents=True)
    (reports / "FEAT-695" / "bad.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(
        test_report.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="final-head\\n"),
    )

    assert test_report.main(["render", "--index", str(index), "--worktree", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "### Notes" in output
    assert "skipped corrupt report: bad.json" in output


def test_unreadable_index_exits_2(tmp_path: Path) -> None:
    """A missing index is the sole data error that returns the usage exit code."""
    assert test_report.main(["render", "--index", str(tmp_path / "missing.json")]) == 2
