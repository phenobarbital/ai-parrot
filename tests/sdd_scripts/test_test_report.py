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


@pytest.mark.parametrize(("task_count", "expected"), [(0, "skip (no tasks)"), (10, "rerun"), (15, "rerun")])
def test_decide_rerun_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str], task_count: int, expected: str) -> None:
    """Every nonempty task index produces the exact deterministic re-run decision."""
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
        lambda *args, **kwargs: SimpleNamespace(stdout="final-head\n"),
    )

    assert test_report.main(["render", "--index", str(index), "--worktree", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "### Notes" in output
    assert "skipped corrupt report: bad.json" in output


def test_render_unreadable_index_emits_no_data_section(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """issue:326c8c0da36c - an unusable index reports no data on stdout and never blocks closeout."""
    missing = tmp_path / "missing.json"

    assert test_report.main(["render", "--index", str(missing)]) == 0
    out = capsys.readouterr().out
    assert test_report.NO_DATA_HEADING in out
    assert str(missing) in out


def test_render_unreadable_index_still_writes_out_file(tmp_path: Path) -> None:
    """issue:326c8c0da36c - --out is always written, so `gh pr create --body-file` cannot fail."""
    out = tmp_path / "pr-tests.md"

    assert test_report.main(["render", "--index", str(tmp_path / "missing.json"), "--out", str(out)]) == 0
    assert out.is_file()
    assert out.read_text(encoding="utf-8").startswith(test_report.NO_DATA_HEADING)


def test_render_corrupt_index_emits_no_data_section(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """issue:326c8c0da36c - a corrupt index is a data error, reported the same fail-open way."""
    index = tmp_path / "index.json"
    index.write_text("{not json", encoding="utf-8")

    assert test_report.main(["render", "--index", str(index)]) == 0
    assert test_report.NO_DATA_HEADING in capsys.readouterr().out


def test_decide_rerun_unreadable_index_skips(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """issue:326c8c0da36c - decide-rerun yields a deterministic skip instead of an empty DECISION."""
    assert test_report.main(["decide-rerun", "--index", str(tmp_path / "missing.json")]) == 0
    assert capsys.readouterr().out.strip() == "skip (no data)"


def test_render_unwritable_out_falls_back_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """issue:326c8c0da36c - an OSError on --out is reported on stderr, not raised, and never blocks."""
    index = tmp_path / "index.json"
    _write_index(index)
    unwritable = tmp_path / "missing-dir" / "pr-tests.md"

    assert test_report.main(["render", "--index", str(index), "--out", str(unwritable)]) == 0
    captured = capsys.readouterr()
    assert "could not write" in captured.err
    assert "## Tests" in captured.out


def test_bad_arguments_still_exit_2(tmp_path: Path) -> None:
    """A malformed invocation stays loud: it is a caller bug, not missing test data."""
    assert test_report.main(["render"]) == 2
    assert test_report.main(["no-such-command"]) == 2
