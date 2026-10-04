"""Fixable plane rules: bidirectional related + FTS index drift (FEAT-625)."""

from __future__ import annotations

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, FixResult
from parrot.knowledge.lint.rule import make_fingerprint

INVERSE_RELATIONS: dict[str, str] = {
    "references": "related",
    "related": "related",
    "supersedes": "superseded_by",
}
SYMMETRIC_RELATIONS = frozenset({"references", "related"})


class AsymmetricRelatedRule:
    """A->B exists (references/related/supersedes) without the inverse B->A."""

    rule_id = "asymmetric-related"
    pack = "plane"
    default_severity = "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Flag edges whose inverse edge is absent (broken targets are skipped)."""
        edges = await ctx.edges()
        page_ids = await ctx.page_ids()
        present = {(str(e["src"]), str(e["dst"]), str(e["rel"])) for e in edges}
        findings: list[Finding] = []
        seen: set[tuple[str, str, str]] = set()
        for src, dst, rel in sorted(present):
            inverse = INVERSE_RELATIONS.get(rel)
            if inverse is None or src == dst or dst not in page_ids:
                continue
            satisfied = (dst, src, inverse) in present or (
                rel in SYMMETRIC_RELATIONS and any((dst, src, r) in present for r in SYMMETRIC_RELATIONS)
            )
            if satisfied or (src, dst, inverse) in seen:
                continue
            seen.add((src, dst, inverse))
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    severity="warning",
                    subjects=[src, dst],
                    message=f"{src} -{rel}-> {dst} has no inverse {dst} -{inverse}-> {src}",
                    fixable=True,
                    fingerprint=make_fingerprint(self.rule_id, [src, dst, inverse]),
                    data={"src": src, "dst": dst, "rel": rel, "inverse": inverse},
                )
            )
        return findings

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult:
        """Add exactly the missing inverse edge (idempotent; never deletes)."""
        d = finding.data
        current = {(str(e["src"]), str(e["dst"]), str(e["rel"])) for e in await ctx.store.dump_edges()}
        if (d["dst"], d["src"], d["inverse"]) in current:
            return FixResult(fingerprint=finding.fingerprint, applied=False, detail="inverse already present")
        await ctx.store.add_edges([(d["dst"], d["src"], d["inverse"], "asserted")])
        return FixResult(
            fingerprint=finding.fingerprint,
            applied=True,
            detail=f"added {d['dst']} -{d['inverse']}-> {d['src']}",
        )


class FtsIndexDriftRule:
    """Search index row counts differ from content tables."""

    rule_id = "fts-index-drift"
    pack = "plane"
    default_severity = "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Report drifted indexes from ``store.index_drift()``."""
        drift = await ctx.store.index_drift()
        if not drift:
            return []
        subjects = sorted(drift)
        return [
            Finding(
                rule_id=self.rule_id,
                severity="warning",
                subjects=subjects,
                message=f"index drift: {drift}",
                fixable=True,
                fingerprint=make_fingerprint(self.rule_id, subjects),
                data={"drift": drift},
            )
        ]

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult:
        """Rebuild the derived search indexes."""
        result = await ctx.store.rebuild_index()
        return FixResult(fingerprint=finding.fingerprint, applied=bool(result.get("rebuilt")), detail=str(result))


PLANE_FIX_RULES = [AsymmetricRelatedRule, FtsIndexDriftRule]
