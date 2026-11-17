"""Lint pack `procedure`: graph checks over sdd/procedures manifests (FEAT-891)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from parrot.knowledge.lint.models import Finding, FixResult, Severity
from parrot.knowledge.lint.rule import make_fingerprint

if TYPE_CHECKING:
    from parrot.knowledge.lint.context import LintContext


class ProcedureGraphRule:
    """Report broken edges, requires-cycles, unknown probes and the other graph errors."""

    rule_id = "procedure-graph"
    pack = "procedure"
    default_severity: Severity = "error"

    async def check(self, ctx: "LintContext") -> list[Finding]:
        """Return one finding per graph issue, or none without a procedure manifest."""
        root = ctx.root
        if root is None:
            return []
        from parrot.knowledge.wiki.procedure.producers import MANIFEST_DIR, manifest_specs

        if not any((root / MANIFEST_DIR).glob("*.yaml")):
            return []
        from parrot.knowledge.wiki.procedure.validate import validate_graph
        from parrot.sdd.scripts.procedure_probes import PROBE_COSTS

        try:
            specs, _sources = manifest_specs(root)
        except ValueError as exc:
            subjects = [MANIFEST_DIR.as_posix()]
            return [
                Finding(
                    rule_id=self.rule_id,
                    severity="error",
                    subjects=subjects,
                    message=str(exc),
                    fingerprint=make_fingerprint(self.rule_id, ["load", *subjects]),
                )
            ]
        return [
            Finding(
                rule_id=self.rule_id,
                severity=finding.severity,
                subjects=finding.subjects,
                message=f"{finding.code}: {finding.message}",
                fingerprint=make_fingerprint(self.rule_id, [finding.code, *finding.subjects]),
                data={"code": finding.code},
            )
            for finding in validate_graph(specs, known_probes=PROBE_COSTS)
        ]

    async def fix(self, ctx: "LintContext", finding: Finding) -> FixResult | None:
        """Return no result because this rule has no automatic fix."""
        return None


PROCEDURE_RULES: tuple[type, ...] = (ProcedureGraphRule,)
