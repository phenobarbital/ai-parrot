"""FEAT-633 TASK-4089 (rev 0.5 D2 / C21): the ``test_command`` fallback contract.

Repos that set ``test_command`` in ``sdd/config.json`` skip ``cache_test_contract`` / ``select_tests`` /
``test_report`` (the shipped ``/sdd-task`` and ``/sdd-done`` say so, on every host). Repos that do not set it
run the helpers, and a helper that cannot load the FEAT-699 ``test_scope`` kernel must fail with ONE line on
stderr and a non-zero exit -- never a traceback.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from parrot.sdd.scripts import cache_test_contract, select_tests, test_report

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SHIPPED_TEST_COMMAND_DOCS = (
    ".claude/commands/sdd-task.md",
    ".agent/workflows/sdd-task.md",
    ".agents/skills/sdd-task/SKILL.md",
    ".claude/commands/sdd-done.md",
    ".agent/workflows/sdd-done.md",
    ".agents/skills/sdd-done/SKILL.md",
)


@pytest.fixture
def no_kernel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Make ``import test_scope`` fail: empty kernel parent, no cached modules, no real path entry."""
    for mod in (cache_test_contract, select_tests, test_report):
        monkeypatch.setattr(mod, "_KERNEL_PARENT", tmp_path)
    for name in [n for n in sys.modules if n == "test_scope" or n.startswith("test_scope.")]:
        monkeypatch.delitem(sys.modules, name)
    real = str(Path(select_tests.__file__).resolve().parents[2] / "flows" / "dev_loop")
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != real])


def _assert_one_line_error(capsys: pytest.CaptureFixture[str], rc: int) -> None:
    err = capsys.readouterr().err
    assert rc != 0
    assert "Traceback" not in err
    assert len(err.strip().splitlines()) == 1, err
    assert "test_scope" in err


def test_cache_test_contract_fails_cleanly_without_kernel(
    no_kernel: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = tmp_path / "x.spec.md"
    spec.write_text("# spec\n", encoding="utf-8")
    index = tmp_path / "x.json"
    index.write_text("{}", encoding="utf-8")
    rc = cache_test_contract.main(["--spec", str(spec), "--index", str(index)])
    _assert_one_line_error(capsys, rc)


def test_select_tests_fails_cleanly_without_kernel(no_kernel: None, capsys: pytest.CaptureFixture[str]) -> None:
    rc = select_tests.main(["--tier", "merge"])
    _assert_one_line_error(capsys, rc)


def _missing_runner_plan(monkeypatch: pytest.MonkeyPatch, distributions: tuple[str, ...]) -> None:
    """Plan one invocation per distribution, all with a runner that is not on PATH."""
    kernel = select_tests._load_kernel()
    from test_scope.datatypes import Invocation, ScopePlan

    plan = ScopePlan(
        tier="merge",
        invocations=tuple(
            Invocation(distribution=d, argv=("parrot-no-such-runner-r2", "-q"), targets=()) for d in distributions
        ),
        escalated=(),
        core_hits=(),
        skipped_escalations=(),
        notes=(),
    )
    monkeypatch.setattr(kernel, "changed_files", lambda worktree, base_ref: [])
    monkeypatch.setattr(kernel, "plan_tests", lambda **_kwargs: plan)


def test_select_tests_run_without_runner_fails_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--run` whose planned runner is not on PATH reports ONE line (even across invocations), exit 1 (FEAT-633 R2)."""
    _missing_runner_plan(monkeypatch, ("a", "b"))
    rc = select_tests.main(["--tier", "merge", "--worktree", str(tmp_path), "--base", "HEAD", "--run"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "Traceback" not in err
    assert len(err.strip().splitlines()) == 1, err
    assert "parrot-no-such-runner-r2" in err and "not run" in err and "test_command" in err


def test_select_tests_run_without_runner_is_recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With an owner, the unstarted invocation is recorded as a failed suite, so the report can never render it green."""
    monkeypatch.setenv("SDD_TEST_REPORT_DIR", str(tmp_path / "reports"))
    _missing_runner_plan(monkeypatch, ("a",))
    worktree = tmp_path / "wt"
    worktree.mkdir()
    rc = select_tests.main(
        ["--tier", "merge", "--worktree", str(worktree), "--base", "HEAD", "--run",
         "--feature", "FEAT-9", "--report-task", "TASK-9", "--no-baseline"]
    )
    capsys.readouterr()
    assert rc == 1
    from test_scope import report

    records, _notes = report.load_records("FEAT-9")
    suites = [s for record in records.values() for s in record.suites]
    assert suites and all(s.status == "no_junit" and s.exit_code == 127 for s in suites), suites


def test_test_report_fails_cleanly_without_kernel(
    no_kernel: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    index = tmp_path / "x.json"
    index.write_text(json.dumps({"feature_id": "FEAT-1", "tasks": [{"id": "TASK-1"}]}), encoding="utf-8")
    rc = test_report.main(["decide-rerun", "--index", str(index)])
    _assert_one_line_error(capsys, rc)


@pytest.mark.parametrize("rel", _SHIPPED_TEST_COMMAND_DOCS)
def test_shipped_docs_carry_the_test_command_rule(rel: str) -> None:
    """The shipped ``/sdd-task`` and ``/sdd-done`` (3 hosts each) name the ``test_command`` switch."""
    path = _REPO_ROOT / rel
    if not path.is_file():
        pytest.skip("not a repo checkout (installed package)")
    text = path.read_text(encoding="utf-8")
    assert "test_command" in text, rel
    assert "sdd/config.json" in text, rel
