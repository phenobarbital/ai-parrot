"""Tests for scripts/sdd/select_tests.py (FEAT-563 TASK-3310)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.sdd.select_tests import main


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True, capture_output=True
    )


@pytest.fixture
def fixture_monorepo(tmp_path: Path) -> Path:
    """git-initialised tree: packages/a/{src/pa/x.py,tests/test_x.py}, packages/b/…, tests/test_root.py, pytest.ini."""
    files = {
        "pytest.ini": "[pytest]\n",
        "packages/a/src/pa/x.py": "X = 1\n",
        "packages/a/tests/test_x.py": "def test_x():\n    assert True\n",
        "packages/b/src/pb/y.py": "from pa.x import X\n",
        "packages/b/tests/test_y.py": "def test_y():\n    assert True\n",
        "tests/test_root.py": "def test_root():\n    assert True\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _write_index(root: Path, payload: dict[str, object]) -> Path:
    """Write a per-spec index fixture and return its repo-relative path."""
    index = root / "sdd/tasks/index/fixture.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps(payload))
    return index.relative_to(root)


def test_cli_json_and_exit_codes(fixture_monorepo, capsys):
    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")
    rc = main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tier"] == "merge"
    assert all(len({inv["distribution"]}) == 1 for inv in payload["invocations"])


def test_empty_task_plan_exits_2(fixture_monorepo):
    assert main(["--tier", "task", "--base", "HEAD", "--worktree", str(fixture_monorepo)]) == 2


def test_index_contract_selects_declared_operands(fixture_monorepo, capsys):
    """An explicit contract selects its operands instead of import-derived targets."""
    from scripts.sdd.select_tests import _load_kernel

    kernel = _load_kernel()
    contract = kernel.contract.contract_to_header(
        kernel.contract.parse_spec_contract("### Validation Contract\n\ntests:\n- packages/a/tests/test_x.py\nmarkers: none\n")
    )
    index = _write_index(
        fixture_monorepo,
        {"feature_id": "FEAT-699", "base_branch": "main", "test_contract": contract, "tasks": []},
    )

    assert main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--index", str(index)]) == 0

    output = capsys.readouterr().out
    assert "packages/a/tests/test_x.py" in output
    assert "packages/b/tests/test_y.py" not in output


def test_malformed_contract_exits_2(fixture_monorepo):
    """Malformed explicit contracts fail closed rather than selecting fallback tests."""
    index = _write_index(fixture_monorepo, {"feature_id": "FEAT-699", "test_contract": {"schema": 1}})

    assert main(["--tier", "merge", "--worktree", str(fixture_monorepo), "--index", str(index)]) == 2


def test_feature_tier_fresh_by_default(fixture_monorepo, monkeypatch):
    """Feature runs bypass the green cache unless ``--use-cache`` was explicitly selected."""
    from scripts.sdd.select_tests import _load_kernel

    _load_kernel()
    import test_scope.green_cache as green_cache

    calls: list[str] = []
    monkeypatch.setattr(green_cache, "filter_cached", lambda *args, **kwargs: calls.append("cache") or args[1])

    common = ["--tier", "feature", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--feature", "FEAT-699"]
    assert main(common) == 0
    assert calls == []
    assert main([*common, "--use-cache"]) == 0
    assert calls == ["cache"]


def test_merge_run_uses_cache_second_time(fixture_monorepo, capsys):
    """A green merge run caches an unchanged file for its next feature-scoped run."""
    (fixture_monorepo / "pyproject.toml").write_text("[project]\nname = 'fixture-root'\nversion = '0.0.0'\n")
    (fixture_monorepo / "packages/a/pyproject.toml").write_text("[project]\nname = 'a'\nversion = '0.0.0'\n")
    _git(fixture_monorepo, "add", "pyproject.toml", "packages/a/pyproject.toml")
    _git(fixture_monorepo, "commit", "-qm", "cache metadata")
    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")

    command = [
        "--tier",
        "merge",
        "--base",
        "HEAD",
        "--worktree",
        str(fixture_monorepo),
        "--feature",
        "FEAT-699",
        "--report-task",
        "TASK-4450",
        "--run",
    ]
    assert main(command) == 0
    capsys.readouterr()
    assert main(command) == 0
    assert "# cached: packages/a/tests/test_x.py" in capsys.readouterr().out


@pytest.mark.parametrize(("status", "expected"), [("baseline_red", 0), ("new_red", 1)])
def test_baseline_verdict_controls_failure_exit(fixture_monorepo, monkeypatch, status, expected):
    """Only a baseline-red failed node may turn an otherwise red invocation green."""
    from scripts.sdd.select_tests import _load_kernel

    kernel = _load_kernel()
    import scripts.sdd.select_tests as sel
    import test_scope.baseline as baseline
    from test_scope.datatypes import BaselineVerdict, PytestInvocation, ScopePlan, TestTarget

    target = "packages/a/tests/test_x.py"
    plan = ScopePlan(
        tier="merge",
        invocations=(
            PytestInvocation(
                distribution="a",
                argv=("pytest", target),
                targets=(TestTarget(path=target, distribution="a", reason="declared"),),
            ),
        ),
        escalated=(),
        core_hits=(),
        skipped_escalations=(),
        notes=(),
    )
    monkeypatch.setattr(kernel, "plan_tests", lambda **_: plan)
    monkeypatch.setattr(kernel, "changed_files", lambda *_: [])

    real_run = sel.subprocess.run

    def _failed_run(argv, **kwargs):
        if not any(str(value).startswith("pytest") for value in argv):
            return real_run(argv, **kwargs)
        junit = Path(next(value for value in argv if value.startswith("--junitxml=")).removeprefix("--junitxml="))
        junit.write_text(
            '<testsuites><testsuite tests="1" failures="1">'
            '<testcase file="packages/a/tests/test_x.py" classname="packages.a.tests.test_x" name="test_x">'
            "<failure />" "</testcase></testsuite></testsuites>"
        )
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(sel.subprocess, "run", _failed_run)
    monkeypatch.setattr(
        baseline,
        "classify_failures",
        lambda **kwargs: (BaselineVerdict(kwargs["failed_nodeids"][0], status),),
    )

    assert (
        main(
            [
                "--tier",
                "merge",
                "--base",
                "HEAD",
                "--worktree",
                str(fixture_monorepo),
                "--feature",
                "FEAT-699",
                "--report-task",
                "TASK-4450",
                "--run",
            ]
        )
        == expected
    )


def test_bad_flag_exits_2():
    assert main(["--tier", "nope"]) == 2


def test_select_tests_on_fixture_monorepo(fixture_monorepo):
    task_file = fixture_monorepo / "task.md"
    task_file.write_text("## Validation Commands\n\n- `pytest packages/a/tests/test_x.py -q`\n")
    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")

    rc = main(
        ["--tier", "task", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--task-file", "task.md", "--run"]
    )
    assert rc == 0

    (fixture_monorepo / "packages/a/tests/test_x.py").write_text("def test_x():\n    assert False\n")
    rc = main(
        ["--tier", "task", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--task-file", "task.md", "--run"]
    )
    assert rc == 1


def test_run_records_green_core_escalation(fixture_monorepo, capsys, monkeypatch):
    from scripts.sdd.select_tests import _load_kernel

    _load_kernel()  # ensures test_scope is importable as a top-level module
    import test_scope.select as select_mod
    from test_scope.policy import ScopePolicy as RealScopePolicy

    monkeypatch.setattr(select_mod, "ScopePolicy", lambda: RealScopePolicy(core_fanin_threshold=1))

    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")

    rc = main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--run"])
    assert rc == 0
    capsys.readouterr()  # discard the first call's shell-line + subprocess output

    main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert "a" in payload["skipped_escalations"]


def test_run_rearms_escalation_on_a_later_red_run(fixture_monorepo, capsys, monkeypatch):
    """FEAT-563 review (R14/AC9c): a red run on a core-escalation invocation must re-arm it — a
    stale ledger record for that distribution must not survive a red run, even one that predates
    (or otherwise never matched) the current core-file content.

    A distribution whose ledger entry already matches the current content is *skipped* by
    `pending_escalations` — the escalated invocation is then never even added to the plan, so it
    cannot go red "for real" through this path. This test instead seeds a ledger entry that does
    NOT match (so the escalation is still attempted, exactly like a genuinely-stale or corrupted
    record would be) and asserts a subsequent red run clears it rather than leaving a misleading
    record behind."""
    from scripts.sdd.select_tests import _load_kernel

    kernel = _load_kernel()
    import test_scope.select as select_mod
    from test_scope.policy import ScopePolicy as RealScopePolicy

    monkeypatch.setattr(select_mod, "ScopePolicy", lambda: RealScopePolicy(core_fanin_threshold=1))

    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")
    # Seed a ledger entry with no matching blobs, so pending_escalations does NOT skip "a"/"b".
    kernel.context.record_green_escalation(fixture_monorepo, ["a", "b"], [])
    assert "a" in kernel.context.read_ledger(fixture_monorepo)

    (fixture_monorepo / "packages/a/tests/test_x.py").write_text("def test_x():\n    assert False\n")
    rc = main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--run"])
    assert rc == 1  # "a"'s escalated suite failed; "b"'s passed

    ledger = kernel.context.read_ledger(fixture_monorepo)
    assert "a" not in ledger  # re-armed: the stale/red entry was dropped, not left in place
    assert "b" in ledger  # "b" was green and got a fresh, correct record


def test_run_records_green_cap_escalation(fixture_monorepo, monkeypatch):
    """--run on a green cap-escalated invocation writes impact blobs and its impacted hash."""
    from scripts.sdd.select_tests import _load_kernel

    kernel = _load_kernel()
    from test_scope.datatypes import PytestInvocation, ScopePlan, TestTarget

    driving_file = "packages/a/src/pa/x.py"
    plan = ScopePlan(
        tier="merge",
        invocations=(
            PytestInvocation(
                distribution="a",
                argv=("pytest", "packages/a/tests"),
                targets=(TestTarget(path="packages/a/tests", distribution="a", reason="escalated"),),
            ),
        ),
        escalated=("a",),
        core_hits=(),
        skipped_escalations=(),
        notes=(),
        cap_hits={"a": (driving_file,)},
        cap_impacted={"a": "cap-impact-hash"},
    )
    monkeypatch.setattr(kernel, "plan_tests", lambda **_: plan)
    monkeypatch.setattr(kernel, "changed_files", lambda *_: [])
    monkeypatch.setattr(
        "scripts.sdd.select_tests.subprocess",
        SimpleNamespace(run=lambda *args, **kwargs: SimpleNamespace(returncode=0)),
    )

    assert main(["--tier", "merge", "--worktree", str(fixture_monorepo), "--run"]) == 0

    ledger = kernel.context.read_ledger(fixture_monorepo)
    assert driving_file in ledger["a"].impact_blobs
    assert ledger["a"].impacted_hash == "cap-impact-hash"


def test_run_rearms_red_cap_escalation(fixture_monorepo, monkeypatch):
    """--run on a red cap-escalated invocation drops the previous ledger entry."""
    from scripts.sdd.select_tests import _load_kernel

    kernel = _load_kernel()
    from test_scope.datatypes import PytestInvocation, ScopePlan, TestTarget

    plan = ScopePlan(
        tier="merge",
        invocations=(
            PytestInvocation(
                distribution="a",
                argv=("pytest", "packages/a/tests"),
                targets=(TestTarget(path="packages/a/tests", distribution="a", reason="escalated"),),
            ),
        ),
        escalated=("a",),
        core_hits=(),
        skipped_escalations=(),
        notes=(),
        cap_hits={"a": ("packages/a/src/pa/x.py",)},
        cap_impacted={"a": "cap-impact-hash"},
    )
    kernel.context.record_green_escalation(
        fixture_monorepo,
        ["a"],
        [],
        impact_files=["packages/a/src/pa/x.py"],
        impacted_hashes={"a": "cap-impact-hash"},
    )
    monkeypatch.setattr(kernel, "plan_tests", lambda **_: plan)
    monkeypatch.setattr(kernel, "changed_files", lambda *_: [])
    monkeypatch.setattr(
        "scripts.sdd.select_tests.subprocess",
        SimpleNamespace(run=lambda *args, **kwargs: SimpleNamespace(returncode=1)),
    )

    assert main(["--tier", "merge", "--worktree", str(fixture_monorepo), "--run"]) == 1
    assert "a" not in kernel.context.read_ledger(fixture_monorepo)


# ── FEAT-617: --timeout bounds a hung test in the merge-tier sweep ──────────


def _captured_argvs(monkeypatch) -> list[list[str]]:
    """Record the pytest argvs `--run` dispatches, without executing them.

    Only pytest invocations are intercepted: `test_scope.select` shells out to
    `git diff` through the same `subprocess` module, and stubbing that too would
    break change detection before any invocation is ever planned.
    """
    import scripts.sdd.select_tests as sel

    seen: list[list[str]] = []
    real_run = sel.subprocess.run

    def _fake_run(argv, **kwargs):
        argv = list(argv)
        if any("pytest" in part for part in argv):
            seen.append(argv)
            return SimpleNamespace(returncode=0)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(sel.subprocess, "run", _fake_run)
    return seen


def test_run_without_timeout_adds_no_timeout_flag(fixture_monorepo, monkeypatch):
    """Default behaviour is unchanged: no --timeout token reaches pytest."""
    seen = _captured_argvs(monkeypatch)
    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")

    rc = main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--run"])

    assert rc == 0
    assert seen, "expected at least one planned invocation"
    for argv in seen:
        assert not any(a.startswith("--timeout") for a in argv), argv


def test_run_with_timeout_appends_flag_to_every_invocation(fixture_monorepo, monkeypatch):
    """--timeout N reaches every pytest subprocess so a hang fails loudly, by name."""
    seen = _captured_argvs(monkeypatch)
    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")

    rc = main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--run", "--timeout", "60"])

    assert rc == 0
    assert seen, "expected at least one planned invocation"
    for argv in seen:
        assert argv[-1] == "--timeout=60", argv


def test_select_tests_flags_absent_is_identical(fixture_monorepo, monkeypatch):
    """The report flags leave the original pytest argv untouched when absent."""
    seen = _captured_argvs(monkeypatch)
    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")

    assert main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--run"]) == 0

    assert seen
    for argv in seen:
        assert not any(argument.startswith("--junitxml=") for argument in argv), argv


def test_select_tests_records(fixture_monorepo, monkeypatch, tmp_path):
    """A flagged run writes the parsed suite result under its task report."""
    from scripts.sdd.select_tests import _load_kernel

    _load_kernel()
    import test_scope.report as report_mod
    import scripts.sdd.select_tests as sel

    monkeypatch.setenv("SDD_TEST_REPORT_DIR", str(tmp_path / "reports"))
    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")
    real_run = sel.subprocess.run

    def _fake_run(argv, **kwargs):
        if any("pytest" in part for part in argv):
            junit_argument = next(part for part in argv if part.startswith("--junitxml="))
            Path(junit_argument.removeprefix("--junitxml=")).write_text(
                '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="1" /></testsuites>'
            )
            return SimpleNamespace(returncode=0)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(sel.subprocess, "run", _fake_run)

    assert (
        main(
            [
                "--tier",
                "merge",
                "--base",
                "HEAD",
                "--worktree",
                str(fixture_monorepo),
                "--feature",
                "FEAT-695",
                "--report-task",
                "TASK-4412",
                "--run",
            ]
        )
        == 0
    )

    records, notes = report_mod.load_records("FEAT-695")
    record = records["TASK-4412"]
    assert notes == []
    assert record.head_sha
    assert record.base_ref == "HEAD"
    assert record.source == "select_tests"
    assert all(suite.tests == 2 and suite.passed == 1 and suite.skipped == 1 for suite in record.suites)
    assert all(suite.argv[-1].startswith("--junitxml=") for suite in record.suites)


def test_no_ledger_skips_escalation_ledger(fixture_monorepo, monkeypatch):
    """Report-only runs never alter the escalation ledger."""
    from scripts.sdd.select_tests import _load_kernel

    kernel = _load_kernel()
    from test_scope.datatypes import PytestInvocation, ScopePlan, TestTarget

    plan = ScopePlan(
        tier="merge",
        invocations=(
            PytestInvocation(
                distribution="a",
                argv=("pytest", "packages/a/tests"),
                targets=(TestTarget(path="packages/a/tests", distribution="a", reason="escalated"),),
            ),
        ),
        escalated=("a",),
        core_hits=(),
        skipped_escalations=(),
        notes=(),
        cap_hits={},
        cap_impacted={},
    )
    calls: list[str] = []
    monkeypatch.setattr(kernel, "plan_tests", lambda **_: plan)
    monkeypatch.setattr(kernel, "changed_files", lambda *_: [])
    monkeypatch.setattr(kernel.context, "record_red_run", lambda *_: calls.append("red"))
    monkeypatch.setattr(kernel.context, "record_green_escalation", lambda *_args, **_kwargs: calls.append("green"))
    monkeypatch.setattr(
        "scripts.sdd.select_tests.subprocess",
        SimpleNamespace(run=lambda *args, **kwargs: SimpleNamespace(returncode=0)),
    )

    assert main(["--tier", "merge", "--worktree", str(fixture_monorepo), "--run", "--no-ledger"]) == 0
    assert calls == []


def test_empty_plan_selection_error(fixture_monorepo, monkeypatch, tmp_path):
    """A flagged empty plan produces a reportable selection-error result."""
    from scripts.sdd.select_tests import _load_kernel

    kernel = _load_kernel()
    import test_scope.report as report_mod
    from test_scope.datatypes import ScopePlan

    monkeypatch.setenv("SDD_TEST_REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(
        kernel,
        "plan_tests",
        lambda **_: ScopePlan(
            tier="merge",
            invocations=(),
            escalated=(),
            core_hits=(),
            skipped_escalations=(),
            notes=(),
            cap_hits={},
            cap_impacted={},
        ),
    )
    monkeypatch.setattr(kernel, "changed_files", lambda *_: [])

    assert (
        main(
            [
                "--tier",
                "merge",
                "--worktree",
                str(fixture_monorepo),
                "--feature",
                "FEAT-695",
                "--report-task",
                "TASK-4412",
                "--run",
            ]
        )
        == 0
    )

    records, _ = report_mod.load_records("FEAT-695")
    record = records["TASK-4412"]
    assert record.notes == ("selection_error: no test invocations planned",)
    assert record.suites[0].status == "selection_error"
