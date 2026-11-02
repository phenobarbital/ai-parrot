"""CLI coverage for the FEAT-784 spec consequence and publish commands."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.decisions.consequences import ConsequenceReport
from parrot.knowledge.wiki.decisions.consequences_render import CheckResult
from parrot.knowledge.wiki.decisions.publish import PublishResult
from parrot.knowledge.wiki.decisions import spec_cli


@pytest.fixture
def runner() -> CliRunner:
    """Return an isolated click command runner."""
    return CliRunner()


def _report(status: str, exit_code: int) -> ConsequenceReport:
    """Build the smallest valid consequence report for CLI exit assertions."""
    return ConsequenceReport(status=status, exit_code=exit_code)


def test_groups_registered(runner: CliRunner) -> None:
    """The lazy top-level groups expose their required subcommands."""
    assert runner.invoke(wiki, ["spec", "--help"]).exit_code == 0
    assert "publish" in runner.invoke(wiki, ["decisions", "--help"]).output


def test_check_unconfigured_repo_is_skipped(runner: CliRunner, tmp_path) -> None:
    """An unconfigured repository reports the portability note without a service."""
    (tmp_path / "s.spec.md").write_text("# S\n\n## 2. Design\n\n## 8. Open Questions\n", encoding="utf-8")

    result = runner.invoke(wiki, ["spec", "consequences", "check", "s.spec.md", "--path", str(tmp_path)])

    assert result.exit_code == 0
    assert "not configured" in result.output


@pytest.mark.parametrize(
    ("status", "exit_code"),
    [("pass", 0), ("conflict", 1), ("invalid", 2), ("incomplete", 3)],
)
def test_check_exit_matrix(
    runner: CliRunner, tmp_path, monkeypatch: pytest.MonkeyPatch, status: str, exit_code: int
) -> None:
    """A current check preserves the consequence report's prescribed exit code."""
    from parrot.knowledge.wiki.decisions import consequences_render, spec_audit

    report = _report(status, exit_code)

    async def fake_check(service: object, spec_path: object) -> CheckResult:
        """Return a fixed current result without opening a wiki plane."""
        del service, spec_path
        return CheckResult(status="current", report=report)

    monkeypatch.setattr(spec_audit, "is_configured", lambda root: True)
    monkeypatch.setattr(spec_cli, "_service", lambda root: object())
    monkeypatch.setattr(consequences_render, "check_spec", fake_check)

    result = runner.invoke(
        wiki,
        ["spec", "consequences", "check", "s.spec.md", "--json", "--path", str(tmp_path)],
    )

    assert result.exit_code == exit_code
    assert json.loads(result.output) == {**report.model_dump(mode="json"), "check": "current"}


@pytest.mark.parametrize("check_status", ["stale", "missing"])
def test_check_stale_or_missing_is_nonzero(
    runner: CliRunner, tmp_path, monkeypatch: pytest.MonkeyPatch, check_status: str
) -> None:
    """A stale or missing rendered section requests repair even for a pass report."""
    from parrot.knowledge.wiki.decisions import consequences_render, spec_audit

    async def fake_check(service: object, spec_path: object) -> CheckResult:
        """Return a report whose generated sections need repair."""
        del service, spec_path
        return CheckResult(status=check_status, report=_report("pass", 0))

    monkeypatch.setattr(spec_audit, "is_configured", lambda root: True)
    monkeypatch.setattr(spec_cli, "_service", lambda root: object())
    monkeypatch.setattr(consequences_render, "check_spec", fake_check)

    result = runner.invoke(wiki, ["spec", "consequences", "check", "s.spec.md", "--path", str(tmp_path)])

    assert result.exit_code == 3


@pytest.mark.parametrize(("status", "exit_code"), [("published", 0), ("already-published", 0), ("refused", 1)])
def test_publish_exit_codes(
    runner: CliRunner, tmp_path, monkeypatch: pytest.MonkeyPatch, status: str, exit_code: int
) -> None:
    """Publication maps result status to the CLI's all-or-nothing exit code."""
    from parrot.knowledge.wiki.decisions import approvals, publish

    class FakePublisher:
        """Minimal publisher returning the parameterized result."""

        def __init__(self, *args: object) -> None:
            """Accept the real publisher's collaborator list."""
            del args

        async def publish(self, batch_id: str) -> PublishResult:
            """Return one deterministic publication result."""
            return PublishResult(batch_id=batch_id, status=status)

    service = SimpleNamespace(store=object(), config=object(), adapter=object())
    monkeypatch.setattr(spec_cli, "_service", lambda root: service)
    monkeypatch.setattr(approvals.ApprovalManifest, "load", lambda path: object())
    monkeypatch.setattr(publish, "BatchPublisher", FakePublisher)

    result = runner.invoke(
        wiki,
        ["decisions", "publish", "--batch", "batch-1", "--json", "--path", str(tmp_path)],
    )

    assert result.exit_code == exit_code
    assert json.loads(result.output)["status"] == status
