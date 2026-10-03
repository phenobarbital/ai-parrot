"""LintRunner — orchestrates one lint run (FEAT-625)."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import SEVERITY_RANK, Finding, FixResult, LintOptions, LintReport, Severity
from parrot.knowledge.lint.rule import LintRule, make_fingerprint
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.store import SCHEMA_VERSION, BaseWikiStore

Router = Callable[[LintReport, LintOptions], Awaitable[dict[str, int]]]


class LintRunner:
    """Run lint rules over a wiki store and optionally apply safe fixes."""

    def __init__(
        self,
        store: BaseWikiStore,
        *,
        root: Path | None = None,
        config: Any | None = None,
        rules: Sequence[LintRule] | None = None,
        router: Router | None = None,
    ) -> None:
        self.store = store
        self.root = root
        self.config = config
        self._rules = list(rules) if rules is not None else None
        self._router = router
        self.logger = logging.getLogger(__name__)

    def _select(self, options: LintOptions) -> list[LintRule]:
        """Apply rules/skip/llm selection."""
        if self._rules is None:
            from parrot.knowledge.lint.packs import default_rules

            pool = default_rules(options)
        else:
            pool = list(self._rules)

        selected: list[LintRule] = []
        for rule in pool:
            if rule.pack == "llm" and not options.llm:
                continue
            if options.rules is not None and rule.rule_id not in options.rules and rule.pack not in options.rules:
                continue
            if rule.rule_id in options.skip:
                continue
            selected.append(rule)
        return selected

    async def _schema_ok(self) -> bool:
        """True when the plane's stored schema version equals SCHEMA_VERSION."""
        stored_version = await self.store.get_meta("schema_version")
        return stored_version is None or stored_version == SCHEMA_VERSION

    async def run(self, options: LintOptions) -> LintReport:
        """Check → (fix → invalidate → re-check) → route → log LINT."""
        started = time.monotonic()
        ctx = LintContext(self.store, root=self.root, config=self.config, options=options)
        rules = self._select(options)
        report = LintReport(
            wiki_name=str(getattr(self.config, "wiki_name", "") or ""),
            backend=type(self.store).__name__,
            rules_run=[rule.rule_id for rule in rules],
            started_at=datetime.now(tz=UTC).isoformat(),
        )
        findings_by_rule = await self._check_rules(rules, ctx)

        if options.fix:
            if not await self._schema_ok():
                report.findings = self._flatten_findings(findings_by_rule)
                report.findings.append(
                    Finding(
                        rule_id="schema-mismatch",
                        severity="error",
                        message="Refusing lint fixes because the plane schema version does not match this code.",
                        fingerprint=make_fingerprint("schema-mismatch", []),
                    )
                )
            else:
                fixed_rule_ids = await self._apply_fixes(rules, findings_by_rule, ctx, report)
                if fixed_rule_ids:
                    ctx.invalidate()
                    fixed_rules = [rule for rule in rules if rule.rule_id in fixed_rule_ids]
                    refreshed = await self._check_rules(fixed_rules, ctx)
                    findings_by_rule.update(refreshed)
                report.findings = self._flatten_findings(findings_by_rule)
        else:
            report.findings = self._flatten_findings(findings_by_rule)

        report.counts = {severity: 0 for severity in SEVERITY_RANK}
        for finding in report.findings:
            report.counts[finding.severity] += 1
        if self._router is not None:
            report.routing = await self._router(report, options)

        report.duration_ms = int((time.monotonic() - started) * 1000)
        self._audit("LINT", f"{len(report.findings)} findings, {len(report.fixed)} fixed")
        return report

    async def _check_rules(self, rules: Sequence[LintRule], ctx: LintContext) -> dict[str, list[Finding]]:
        """Run checks independently so a failed rule does not hide other results."""
        findings_by_rule: dict[str, list[Finding]] = {}
        for rule in rules:
            try:
                findings_by_rule[rule.rule_id] = await rule.check(ctx)
            except Exception as exc:
                self.logger.exception("Lint rule %s crashed", rule.rule_id)
                findings_by_rule[rule.rule_id] = [
                    Finding(
                        rule_id="rule-crashed",
                        severity="error",
                        subjects=[rule.rule_id],
                        message=f"Lint rule {rule.rule_id!r} crashed: {exc}",
                        fingerprint=make_fingerprint("rule-crashed", [rule.rule_id]),
                    )
                ]
        return findings_by_rule

    async def _apply_fixes(
        self,
        rules: Sequence[LintRule],
        findings_by_rule: dict[str, list[Finding]],
        ctx: LintContext,
        report: LintReport,
    ) -> set[str]:
        """Apply every available fix and return rule ids that changed the plane."""
        fixed_rule_ids: set[str] = set()
        rules_by_id = {rule.rule_id: rule for rule in rules}
        for rule_id, findings in findings_by_rule.items():
            rule = rules_by_id[rule_id]
            for finding in findings:
                if not finding.fixable:
                    continue
                try:
                    result = await rule.fix(ctx, finding)
                except Exception as exc:
                    self.logger.exception("Lint rule %s failed to fix finding %s", rule_id, finding.fingerprint)
                    continue
                if result is not None and result.applied:
                    report.fixed.append(result)
                    fixed_rule_ids.add(rule_id)
                    self._audit("LINT_FIX", result.detail or f"{rule_id}: {finding.fingerprint}")
        return fixed_rule_ids

    @staticmethod
    def _flatten_findings(findings_by_rule: dict[str, list[Finding]]) -> list[Finding]:
        """Return rule findings in selected-rule order."""
        return [finding for findings in findings_by_rule.values() for finding in findings]

    def _audit(self, operation: str, details: str) -> None:
        """Append to the wiki log.md when root+config are known (best-effort)."""
        if self.root is None or self.config is None:
            return
        try:
            WikiBookkeeper().log_operation(self.config.storage_path(self.root), operation, details)
        except Exception:
            self.logger.warning("Could not write %s audit record", operation, exc_info=True)

    @staticmethod
    def exit_code(report: LintReport, fail_on: Severity | None) -> int:
        """0 when no finding is at or above ``fail_on``, else 1."""
        if fail_on is None:
            return 0
        threshold = SEVERITY_RANK[fail_on]
        return int(any(SEVERITY_RANK[finding.severity] >= threshold for finding in report.findings))
