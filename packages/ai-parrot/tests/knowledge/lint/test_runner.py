"""Unit tests for LintRunner (FEAT-625)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions, LintReport
from parrot.knowledge.lint.runner import LintRunner
from parrot.knowledge.wiki.store import SCHEMA_VERSION


class FakeStore:
    """Minimal store fake because these rules need no retrieval-plane data."""

    def __init__(self, schema_version: str | None = None) -> None:
        self.schema_version = schema_version

    async def get_meta(self, key: str) -> str | None:
        """Return the configured schema version for the requested metadata key."""
        assert key == "schema_version"
        return self.schema_version


class FakeRule:
    """A rule with one finding that disappears after its fix is applied."""

    rule_id = "fake"
    pack = "test"
    default_severity = "warning"

    def __init__(self) -> None:
        self.fixed = False
        self.fix_calls = 0

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Return a fixable finding until ``fix`` changes the rule state."""
        if self.fixed:
            return []
        return [
            Finding(
                rule_id=self.rule_id,
                severity="warning",
                message="Needs fixing",
                fixable=True,
                fingerprint="fake-finding",
            )
        ]

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult:
        """Apply the test-only fix."""
        self.fix_calls += 1
        self.fixed = True
        return FixResult(fingerprint=finding.fingerprint, applied=True, detail="fixed fake finding")


class CrashingRule:
    """A rule that proves exceptions are isolated to the crashing rule."""

    rule_id = "crashing"
    pack = "test"
    default_severity = "error"

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Raise an exception during the check."""
        raise RuntimeError("broken rule")

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult | None:
        """Never fix because checks always fail."""
        return None


@pytest.mark.asyncio
async def test_runner_fix_then_recheck(tmp_path: Path) -> None:
    """A successful fix moves its finding from remaining to fixed."""
    rule = FakeRule()
    report = await LintRunner(FakeStore(), rules=[rule]).run(LintOptions(fix=True))  # type: ignore[arg-type]

    assert report.findings == []
    assert report.fixed == [FixResult(fingerprint="fake-finding", applied=True, detail="fixed fake finding")]
    assert report.counts == {"info": 0, "warning": 0, "error": 0}
    assert rule.fix_calls == 1


@pytest.mark.asyncio
async def test_runner_refuses_fix_on_schema_mismatch(tmp_path: Path) -> None:
    """A schema mismatch reports an error and calls no fix method."""
    store = FakeStore(f"{SCHEMA_VERSION}-different")
    rule = FakeRule()

    report = await LintRunner(store, rules=[rule]).run(LintOptions(fix=True))  # type: ignore[arg-type]

    assert rule.fix_calls == 0
    assert report.fixed == []
    assert {finding.rule_id for finding in report.findings} == {"fake", "schema-mismatch"}


@pytest.mark.asyncio
async def test_runner_isolates_crashing_rule(tmp_path: Path) -> None:
    """A crashing rule becomes a finding while other rules still run."""
    report = await LintRunner(FakeStore(), rules=[CrashingRule(), FakeRule()]).run(LintOptions())  # type: ignore[arg-type]

    assert {finding.rule_id for finding in report.findings} == {"rule-crashed", "fake"}


def test_runner_selects_rules_by_pack_and_skips_rule(tmp_path: Path) -> None:
    """Rule selection accepts packs but skips named rule ids and opt-in LLM rules."""
    rule = FakeRule()
    llm_rule = FakeRule()
    llm_rule.rule_id = "llm-rule"
    llm_rule.pack = "llm"
    runner = LintRunner(FakeStore(), rules=[rule, llm_rule])  # type: ignore[arg-type]

    assert runner._select(LintOptions(rules=["test"])) == [rule]
    assert runner._select(LintOptions(llm=True, skip=["llm-rule"])) == [rule]


def test_exit_code_fail_on() -> None:
    """Exit status honors error, warning, and disabled thresholds."""
    report = LintReport(findings=[Finding(rule_id="x", severity="warning", message="m", fingerprint="f")])
    assert LintRunner.exit_code(report, "error") == 0
    assert LintRunner.exit_code(report, "warning") == 1
    assert LintRunner.exit_code(report, None) == 0
