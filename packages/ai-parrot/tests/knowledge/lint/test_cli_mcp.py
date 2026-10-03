"""Tests for the wikitoolkit lint CLI and MCP wrapper (FEAT-625)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions, LintReport
from parrot.knowledge.lint.runner import LintRunner
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.project import load_project_config
from parrot.knowledge.wiki.store import SQLiteWikiStore
from parrot.knowledge.wiki.tools import create_wiki_tools


@pytest.fixture
def built_wiki(tmp_path: Path) -> Path:
    """Build a minimal SQLite wiki plane for CLI lint tests."""
    (tmp_path / "module.py").write_text('"""Fixture module."""\n', encoding="utf-8")
    result = CliRunner().invoke(wiki, ["build", "--path", str(tmp_path), "--no-graph", "--quiet"])
    assert result.exit_code == 0, result.output
    return tmp_path


def test_cli_lint_json(built_wiki: Path) -> None:
    """CLI lint emits a JSON report and writes nothing with routing disabled."""
    result = CliRunner().invoke(
        wiki,
        ["lint", "--path", str(built_wiki), "--json", "--no-ledger", "--no-notes"],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert "findings" in report
    assert "counts" in report


def test_cli_lint_exits_nonzero_on_error(built_wiki: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI lint returns a failing status when the runner reports an error."""
    from parrot.knowledge.lint import LintRunner as PublicLintRunner

    async def run_error(self: LintRunner, options: LintOptions) -> LintReport:
        return LintReport(
            findings=[Finding(rule_id="fixture", severity="error", message="fixture error", fingerprint="fixture-error")],
            counts={"info": 0, "warning": 0, "error": 1},
        )

    monkeypatch.setattr(PublicLintRunner, "run", run_error)
    result = CliRunner().invoke(
        wiki,
        ["lint", "--path", str(built_wiki), "--json", "--no-ledger", "--no-notes"],
    )

    assert result.exit_code == 1
    assert json.loads(result.output)["counts"]["error"] == 1


def test_wiki_lint_tool_registered(built_wiki: Path) -> None:
    """The native wiki tool list includes the wiki_lint MCP wrapper."""
    config = load_project_config(built_wiki)
    store = SQLiteWikiStore(config.storage_path(built_wiki) / "wiki.db", wiki_name=config.wiki_name)

    assert "wiki_lint" in {tool.name for tool in create_wiki_tools(store, root=built_wiki, config=config)}


class _ExtrasRule:
    """Rule proving runner extras survive the fix invalidation cycle."""

    rule_id = "extras"
    pack = "test"
    default_severity = "warning"

    def __init__(self) -> None:
        self.fixed = False

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Require the seeded source marker before and after invalidation."""
        assert ctx.extras["sources"] == "fixture"
        if self.fixed:
            return []
        return [
            Finding(
                rule_id=self.rule_id,
                severity="warning",
                message="fixture",
                fixable=True,
                fingerprint="extras-fixture",
            )
        ]

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult:
        """Mark the test rule fixed."""
        self.fixed = True
        return FixResult(fingerprint=finding.fingerprint, applied=True)


@pytest.mark.asyncio
async def test_runner_reseeds_extras_after_invalidation() -> None:
    """Injected sources remain available when a fixed rule is re-checked."""
    rule = _ExtrasRule()
    report = await LintRunner(_StubStore(), rules=[rule], extras={"sources": "fixture"}).run(LintOptions(fix=True))

    assert report.findings == []


class _StubStore:
    """Minimal store implementation used only by the extras runner test."""

    async def get_meta(self, key: str) -> str | None:
        """Return no stored schema marker, allowing safe test fixes."""
        assert key == "schema_version"
        return None
