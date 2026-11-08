"""Tests for the parrot-e2e runner adapter (FEAT-709 M4)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope.datatypes import TestTarget
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


@pytest.mark.parametrize("settings", [{}, {"plan": ""}])
def test_missing_plan_is_value_error(settings: dict[str, str]) -> None:
    """An absent or empty plan is a readable ValueError, never a KeyError (issue:a3aebc40ef48)."""
    with pytest.raises(ValueError, match=r"'plan'.*test_runners\.toml"):
        ADAPTER.distribution_of("", settings=settings)
    with pytest.raises(ValueError, match=r"'plan'.*test_runners\.toml"):
        ADAPTER.invocation(
            [], distribution="d", worktree=Path("."), settings=settings, policy=None, report_path="r"
        )  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["parrot", "e2e", "run", "--plan", "sdd/state/FEAT-581/e2e-plan.md"], ["sdd/state/FEAT-581/e2e-plan.md"]),
        (["parrot", "e2e", "verify", "--plan=sdd/state/FEAT-581/e2e-plan.md"], ["sdd/state/FEAT-581/e2e-plan.md"]),
        (["parrot", "e2e", "run", "--owner-id", "o", "--plan", "p.md"], ["p.md"]),
        (["parrot", "e2e", "run"], []),
        (["parrot", "e2e", "run", "--plan"], []),
        (["pytest", "tests/test_x.py"], None),
    ],
)
def test_operands_surface_the_plan(argv: list[str], expected: list[str] | None) -> None:
    """The declared --plan is the operand; no --plan means no operand (issue:3ae0b2ae0ef4)."""
    assert ADAPTER.operands(argv) == expected


def test_distribution_prefers_target() -> None:
    settings = {"plan": "sdd/state/FEAT-581/e2e-plan.md"}
    assert ADAPTER.distribution_of("sdd/state/FEAT-815/e2e-plan.md", settings=settings) == "FEAT-815"
    assert ADAPTER.distribution_of("", settings=settings) == "FEAT-581"
    with pytest.raises(ValueError):
        ADAPTER.distribution_of("", settings={})


def _plan_argument(targets: list[TestTarget], settings: dict[str, str]) -> str:
    """The ``--plan`` value of the invocation built for ``targets`` under ``settings``."""
    invocation = ADAPTER.invocation(
        targets, distribution="d", worktree=Path("."), settings=settings, policy=None, report_path="r"
    )  # type: ignore[arg-type]
    return invocation.argv[4]


def test_invocation_prefers_target_plan() -> None:
    settings = {"plan": "sdd/state/FEAT-581/e2e-plan.md"}
    declared = TestTarget("sdd/state/FEAT-815/e2e-plan.md", "FEAT-815", "declared", runner="parrot-e2e")
    contract_only = TestTarget("", "FEAT-581", "contract", runner="parrot-e2e")
    assert _plan_argument([declared], settings) == "sdd/state/FEAT-815/e2e-plan.md"
    assert _plan_argument([contract_only], settings) == settings["plan"]
    assert _plan_argument([], settings) == settings["plan"]
    with pytest.raises(ValueError):
        _plan_argument([contract_only], {})


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
