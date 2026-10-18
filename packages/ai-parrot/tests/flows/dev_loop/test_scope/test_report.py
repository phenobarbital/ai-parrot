"""Tests for the FEAT-695 test-report kernel."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope import report
from parrot.flows.dev_loop.test_scope.datatypes import PytestInvocation

XUNIT1 = """<testsuites><testsuite tests="2" failures="1" errors="0" skipped="0">
<testcase file="packages/a/tests/test_x.py" classname="packages.a.tests.test_x.TestC" name="test_ok"/>
<testcase file="packages/a/tests/test_x.py" classname="packages.a.tests.test_x" name="test_bad[1]"><failure/></testcase>
</testsuite></testsuites>"""


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    monkeypatch.setenv(report.REPORT_ROOT_ENV, str(tmp_path / "root"))


def _result(suite="core", **changes):
    values = dict(
        suite=suite,
        tests=4,
        passed=4,
        failed=0,
        errors=0,
        skipped=0,
        duration_s=1.25,
        exit_code=0,
        argv=("pytest",),
        status="ok",
    )
    values.update(changes)
    return report.SuiteResult(**values)


def _append(root: str, suite: str) -> None:
    os_environ = report.os.environ
    os_environ[report.REPORT_ROOT_ENV] = root
    report.append_suite(
        "FEAT-695", "TASK-1", _result(suite), head_sha="head", base_ref="dev", tier="task", source="test"
    )


def test_with_junit_does_not_mutate(tmp_path):
    invocation = PytestInvocation("root", ("pytest", "test_x.py"), ())
    argv = report.with_junit(invocation, tmp_path / "result.xml")
    assert invocation.argv == ("pytest", "test_x.py")
    assert argv[-3:] == ("-o", "junit_family=xunit1", f"--junitxml={tmp_path / 'result.xml'}")


def test_suite_name_variants():
    default = PytestInvocation("ai-parrot", ("pytest", "-m", "not slow"), ())
    contract = PytestInvocation("ai-parrot", ("pytest", "-m", "not real_llm"), ())
    markers = PytestInvocation("ai-parrot", ("pytest", "-m", "(unit or smoke) and not real_llm"), ())
    assert report.suite_name(default) == "ai-parrot"
    assert report.suite_name(contract) == "ai-parrot[contract]"
    assert report.suite_name(markers) == "ai-parrot[markers]"


def test_parse_junit_nodes(tmp_path):
    path = tmp_path / "result.xml"
    path.write_text(XUNIT1)
    result = report.parse_junit(path, suite="a", argv=("pytest",), exit_code=1, duration_s=2.0)
    assert result.nodes == (
        ("packages/a/tests/test_x.py::TestC::test_ok", "passed"),
        ("packages/a/tests/test_x.py::test_bad[1]", "failed"),
    )
    assert result.unmapped == 0


def test_parse_junit_unmapped_testcase(tmp_path):
    path = tmp_path / "result.xml"
    path.write_text('<testsuite tests="1"><testcase classname="test_x" name="test_unknown"/></testsuite>')
    result = report.parse_junit(path, suite="a", argv=("pytest",), exit_code=0, duration_s=1.0)
    assert result.nodes == ()
    assert result.unmapped == 1


def test_parse_junit_counts(tmp_path):
    path = tmp_path / "result.xml"
    path.write_text('<testsuites><testsuite tests="4" failures="1" errors="1" skipped="1" /></testsuites>')
    result = report.parse_junit(path, suite="a", argv=("pytest",), exit_code=1, duration_s=2.0)
    assert (result.tests, result.passed, result.failed, result.errors, result.skipped, result.status) == (
        4,
        1,
        1,
        1,
        1,
        "failed",
    )


def test_parse_junit_missing_file(tmp_path):
    result = report.parse_junit(tmp_path / "missing.xml", suite="a", argv=("pytest",), exit_code=1, duration_s=1.0)
    assert result.status == "no_junit"
    assert result.tests == 0


def test_parse_junit_malformed_and_timed_out(tmp_path):
    path = tmp_path / "bad.xml"
    path.write_text("not xml")
    assert (
        report.parse_junit(path, suite="a", argv=("pytest",), exit_code=1, duration_s=1.0).status
        == "report_parse_error"
    )
    assert (
        report.parse_junit(path, suite="a", argv=("pytest",), exit_code=1, duration_s=1.0, timed_out=True).status
        == "timed_out"
    )


def test_parse_junit_xdist_shape(tmp_path):
    path = tmp_path / "result.xml"
    path.write_text('<testsuite tests="1"><testsuite tests="2" skipped="1" /></testsuite>')
    result = report.parse_junit(path, suite="a", argv=("pytest",), exit_code=0, duration_s=1.0)
    assert (result.tests, result.passed, result.skipped) == (3, 2, 1)


def test_junit_paths_are_unique_per_invocation():
    first = report.junit_path_for("FEAT-695", "TASK-1", "one", 1)
    second = report.junit_path_for("FEAT-695", "TASK-1", "two", 2)
    assert first != second


def test_append_suite_replaces_same_suite():
    report.append_suite("FEAT-695", "TASK-1", _result("a"), head_sha="one", base_ref="dev", tier="task", source="test")
    report.append_suite("FEAT-695", "TASK-1", _result("b"), head_sha="two", base_ref="dev", tier="task", source="test")
    report.append_suite(
        "FEAT-695",
        "TASK-1",
        _result("a", tests=7, passed=7),
        head_sha="three",
        base_ref="dev",
        tier="task",
        source="test",
    )
    records, notes = report.load_records("FEAT-695")
    assert not notes
    assert records["TASK-1"].attempts == 3
    assert [(item.suite, item.tests) for item in records["TASK-1"].suites] == [("a", 7), ("b", 4)]


def test_append_suite_atomic_concurrent(tmp_path):
    root = str(tmp_path / "shared")
    processes = [multiprocessing.Process(target=_append, args=(root, suite)) for suite in ("a", "b")]
    for process in processes:
        process.start()
    for process in processes:
        process.join()
        assert process.exitcode == 0
    report.os.environ[report.REPORT_ROOT_ENV] = root
    assert {item.suite for item in report.load_records("FEAT-695")[0]["TASK-1"].suites} == {"a", "b"}


def test_report_root_env_override_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv(report.REPORT_ROOT_ENV, str(tmp_path / "override"))
    assert report.report_root() == tmp_path / "override"
    monkeypatch.delenv(report.REPORT_ROOT_ENV)
    assert report.report_root() == Path("/tmp") / f"claude-{report.os.getuid()}" / "sdd-tests"


def test_should_rerun_for_any_nonempty_feature():
    assert not report.should_rerun(0)
    assert report.should_rerun(1)
    assert report.should_rerun(15)


def _record(task_id: str, result, head="final", cached=()):
    return report.TaskTestRecord(
        "FEAT-695", task_id, head, "dev", "task", "test", "now", 1, (result,), cached=cached
    )


def test_render_aggregates_by_suite_and_marks_failures():
    records = {
        "TASK-1": _record("TASK-1", _result("a")),
        "TASK-2": _record("TASK-2", _result("a", failed=1, passed=3, status="failed")),
    }
    output = report.render_markdown(
        records, ["TASK-1", "TASK-2"], final_head="final", rerun=None, rerun_skip_reason=None
    )
    assert "| a ❌ | 8 | 7 | 1 | 0 | 0 | — | — | — | 2.50s |" in output
    assert "Gate: ⚠️ failures not classified" in output
    assert "Total (per-task invocation totals)" in output


def test_render_no_data_and_stale_marking():
    output = report.render_markdown(
        {"TASK-1": _record("TASK-1", _result(), "old")},
        ["TASK-1", "TASK-2"],
        final_head="final",
        rerun=None,
        rerun_skip_reason=None,
    )
    assert "TASK-1 (stale)" in output
    assert "TASK-2: no data" in output


def test_render_rerun_column_and_skip_reason():
    rerun = _record(report.RERUN_RECORD, _result("a"))
    output = report.render_markdown({}, [], final_head="final", rerun=rerun, rerun_skip_reason=None)
    assert "Final HEAD re-run" in output
    output = report.render_markdown({}, [], final_head="final", rerun=None, rerun_skip_reason="no tasks")
    assert "re-run skipped (no tasks)" in output


def test_render_baseline_reds_are_not_new_reds_and_cached_targets_are_counted():
    result = _result(
        failed=1,
        passed=3,
        status="failed",
        baseline=(("tests/test_example.py::test_red", "baseline_red"),),
    )
    record = _record("TASK-1", result, cached=("tests/test_one.py", "tests/test_two.py"))
    output = report.render_markdown({"TASK-1": record}, ["TASK-1"], final_head="final", rerun=None, rerun_skip_reason=None)
    assert "| core ❌ | 4 | 3 | 1 | 0 | 0 | 0 | 1 | 0 | 1.25s |" in output
    assert "cached (skipped, unchanged since green): 2 target(s)" in output
    assert "Gate: ✅ no new reds" in output


def test_render_new_red_and_unknown_gate():
    result = _result(
        failed=2,
        passed=2,
        status="failed",
        baseline=(
            ("tests/test_example.py::test_new", "new_red"),
            ("tests/test_example.py::test_unknown", "unknown"),
        ),
    )
    output = report.render_markdown({"TASK-1": _record("TASK-1", result)}, ["TASK-1"], final_head="final", rerun=None, rerun_skip_reason=None)
    assert "Gate: ❌ 1 new red, 1 unknown" in output


def test_append_cached_merges_sorted_targets():
    report.append_cached(
        "FEAT-695", "TASK-1", ("tests/b.py", "tests/a.py"), head_sha="one", base_ref="dev", tier="task", source="test"
    )
    report.append_cached(
        "FEAT-695", "TASK-1", ("tests/a.py", "tests/c.py"), head_sha="two", base_ref="dev", tier="task", source="test"
    )
    assert report.load_records("FEAT-695")[0]["TASK-1"].cached == ("tests/a.py", "tests/b.py", "tests/c.py")


def test_load_records_skips_corrupt_file():
    directory = report.report_root() / "FEAT-695"
    directory.mkdir(parents=True)
    (directory / "bad.json").write_text(json.dumps({"bad": True}))
    records, notes = report.load_records("FEAT-695")
    assert records == {}
    assert notes == ["skipped corrupt report: bad.json"]


def test_load_records_accepts_pre_feat_699_payload():
    directory = report.report_root() / "FEAT-695"
    directory.mkdir(parents=True)
    record = _record("TASK-1", _result())
    payload = report.asdict(record)
    for suite in payload["suites"]:
        suite.pop("nodes")
        suite.pop("unmapped")
        suite.pop("baseline")
    payload.pop("cached")
    (directory / "TASK-1.json").write_text(json.dumps(payload))

    records, notes = report.load_records("FEAT-695")

    assert not notes
    assert records["TASK-1"].suites[0].nodes == ()
    assert records["TASK-1"].suites[0].unmapped == 0
    assert records["TASK-1"].suites[0].baseline == ()
    assert records["TASK-1"].cached == ()


def test_junit_path_for_removes_stale_file() -> None:
    """A stale junit file from an earlier attempt is never reused as a new run's result."""
    path = report.junit_path_for("FEAT-1", "TASK-1", "root", 0)
    path.write_text("<testsuite tests='9'/>", encoding="utf-8")
    again = report.junit_path_for("FEAT-1", "TASK-1", "root", 0)
    assert again == path and not again.exists()


def test_unsafe_ids_are_not_recorded(tmp_path) -> None:
    """Path-traversal ids never write outside the report root."""
    result = report.SuiteResult("root", 1, 1, 0, 0, 0, 0.1, 0, ("pytest",), "ok")
    assert report.append_suite("../..", "TASK-1", result, head_sha="a", base_ref="b", tier="merge", source="t") is None
    assert report.load_records("../..")[0] == {}
