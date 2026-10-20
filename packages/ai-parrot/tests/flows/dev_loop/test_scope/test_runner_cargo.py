"""Tests for the cargo runner adapter (FEAT-709 TASK-4527)."""

from __future__ import annotations

from pathlib import Path

from parrot.flows.dev_loop.test_scope.runners.cargo import ADAPTER, parse_libtest

FIXTURES = Path(__file__).parent / "fixtures"


def _parse(name: str, exit_code: int):
    text = (FIXTURES / name).read_text()
    return parse_libtest(text, crate="demo", exit_code=exit_code, suite="cargo:demo", duration_s=0.1, timed_out=False)


def test_parse_libtest_ok() -> None:
    report = _parse("libtest-ok.txt", 0)
    assert report.status == "passed"
    assert report.tests == 3 and report.passed == 2 and report.skipped == 1
    assert ("cargo:demo::tests::slow_case", "skipped") in report.nodes


def test_parse_libtest_failed() -> None:
    report = _parse("libtest-failed.txt", 101)
    assert report.status == "failed"
    assert report.failed == 2 and report.passed == 1
    assert set(report.failure_text) == {"cargo:demo::tests::divides", "cargo:demo::tests::parses"}
    assert "left: 3" in report.failure_text["cargo:demo::tests::divides"]
    assert "failures:" not in report.failure_text["cargo:demo::tests::parses"]
    assert "ParseIntError" in report.failure_text["cargo:demo::tests::parses"]


def test_parse_libtest_compile_error() -> None:
    report = _parse("libtest-compile-error.txt", 101)
    assert report.status == "unavailable"
    assert report.tests == 0


def test_adapter_argv_and_operands(tmp_path: Path) -> None:
    assert ADAPTER.matches(["cargo", "test", "-p", "demo", "adds", "--", "--nocapture"])
    assert not ADAPTER.matches(["cargo", "build"])
    assert ADAPTER.operands(["cargo", "test", "-p", "demo", "adds", "--", "x"]) == ["adds"]
    assert ADAPTER.is_broad(["cargo", "test"], worktree=None) is False
    assert ADAPTER.validate_settings({}, worktree=tmp_path)
    assert ADAPTER.validate_settings({"crate": "demo"}, worktree=tmp_path) == []
    assert ADAPTER.validate_settings({"crate": "./crates/demo"}, worktree=tmp_path)
    report = ADAPTER.parse_report(
        report_path=None,
        exit_code=0,
        stdout=(FIXTURES / "libtest-ok.txt").read_text(),
        stderr="",
        duration_s=0.0,
        timed_out=False,
        suite="cargo:demo",
    )
    assert report.nodes[0][0] == "cargo:demo::tests::adds"
