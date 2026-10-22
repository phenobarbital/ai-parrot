"""ADR rule pack — decision status consistency (FEAT-625)."""

from __future__ import annotations

from collections import defaultdict

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, FixResult, Severity
from parrot.knowledge.lint.rule import make_fingerprint
from parrot.knowledge.wiki.decisions.models import DecisionError, DecisionRecord
from parrot.knowledge.wiki.decisions.repository import DecisionRepository


def _finding(rule_id: str, severity: Severity, subjects: list[str], message: str, **data: object) -> Finding:
    """Create a consistently fingerprinted ADR finding."""
    return Finding(
        rule_id=rule_id,
        severity=severity,
        subjects=subjects,
        message=message,
        fingerprint=make_fingerprint(rule_id, subjects),
        data=data,
    )


async def _records(ctx: LintContext) -> list[DecisionRecord] | None:
    """Return the cached ADR inventory, or ``None`` when it is unavailable."""
    if "adr" not in ctx.extras:
        try:
            ctx.extras["adr"] = await DecisionRepository(ctx.store).inventory()
        except DecisionError as exc:
            ctx.logger.warning("ADR inventory unavailable: %s", exc)
            ctx.extras["adr"] = None
    return ctx.extras["adr"]


def _unavailable_finding(ctx: LintContext) -> list[Finding]:
    """Return the ADR inventory diagnostic once per lint context."""
    if ctx.extras.get("adr_inventory_unavailable_reported"):
        return []
    ctx.extras["adr_inventory_unavailable_reported"] = True
    return [
        _finding(
            "adr-inventory-unavailable",
            "info",
            [],
            "ADR inventory is unavailable; ADR consistency checks were skipped",
        )
    ]


class _AdrRule:
    """Shared report-only ADR rule behavior."""

    pack = "adr"

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult | None:
        """Return no fix because ADR consistency needs manual remediation."""
        return None


class AdrSupersededActiveRule(_AdrRule):
    """Report accepted records superseded by another ADR."""

    rule_id, default_severity = "adr-superseded-active", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Report accepted decisions targeted by a supersedes link."""
        records = await _records(ctx)
        if records is None:
            return _unavailable_finding(ctx)
        superseded = {link.target_id for record in records for link in record.links if link.relation == "supersedes"}
        return [
            _finding(
                self.rule_id,
                self.default_severity,
                [record.decision_id],
                f"accepted ADR {record.decision_id!r} is superseded by another ADR",
            )
            for record in records
            if record.source_status == "accepted" and record.decision_id in superseded
        ]


class AdrSupersedesBrokenRule(_AdrRule):
    """Report supersedes links whose targets are unknown."""

    rule_id, default_severity = "adr-supersedes-broken", "error"

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Report supersedes links that do not resolve to ADR or page identifiers."""
        records = await _records(ctx)
        if records is None:
            return _unavailable_finding(ctx)
        known_ids = {record.decision_id for record in records} | await ctx.page_ids()
        findings: list[Finding] = []
        for record in records:
            for link in record.links:
                if link.relation == "supersedes" and link.target_id not in known_ids:
                    findings.append(
                        _finding(
                            self.rule_id,
                            self.default_severity,
                            [record.decision_id, link.target_id],
                            f"ADR {record.decision_id!r} supersedes unknown target {link.target_id!r}",
                            target_id=link.target_id,
                        )
                    )
        return findings


class AdrConflictRule(_AdrRule):
    """Report accepted ADRs that explain the same target without supersession."""

    rule_id, default_severity = "adr-conflict", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Report every conflicting pair of accepted ADR records."""
        records = await _records(ctx)
        if records is None:
            return _unavailable_finding(ctx)
        explains: dict[str, list[DecisionRecord]] = defaultdict(list)
        for record in records:
            if record.source_status != "accepted":
                continue
            for link in record.links:
                if link.relation == "explains":
                    explains[link.target_id].append(record)

        findings: list[Finding] = []
        for target_id, group in sorted(explains.items()):
            ordered = sorted(group, key=lambda record: record.decision_id)
            for index, first in enumerate(ordered):
                first_supersedes = {link.target_id for link in first.links if link.relation == "supersedes"}
                for second in ordered[index + 1 :]:
                    second_supersedes = {link.target_id for link in second.links if link.relation == "supersedes"}
                    if second.decision_id in first_supersedes or first.decision_id in second_supersedes:
                        continue
                    subjects = [first.decision_id, second.decision_id, target_id]
                    findings.append(
                        _finding(
                            self.rule_id,
                            self.default_severity,
                            subjects,
                            f"accepted ADRs {first.decision_id!r} and {second.decision_id!r} both explain {target_id!r}",
                            target_id=target_id,
                        )
                    )
        return findings


ADR_RULES = [AdrSupersededActiveRule, AdrSupersedesBrokenRule, AdrConflictRule]
