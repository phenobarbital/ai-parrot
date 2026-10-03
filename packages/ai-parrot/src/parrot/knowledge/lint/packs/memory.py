"""Memory rule pack — dangling and stale agent memories (FEAT-625)."""

from __future__ import annotations

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, FixResult, Severity
from parrot.knowledge.lint.rule import make_fingerprint


def _finding(rule_id: str, severity: Severity, subjects: list[str], message: str, **data: object) -> Finding:
    """Create a consistently fingerprinted memory finding."""
    return Finding(
        rule_id=rule_id,
        severity=severity,
        subjects=subjects,
        message=message,
        fingerprint=make_fingerprint(rule_id, subjects),
        data=data,
    )


class _MemoryRule:
    """Shared report-only memory rule behavior."""

    pack = "memory"

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult | None:
        """Return no fix because memory findings need manual remediation."""
        return None


class MemoryDanglingLinkRule(_MemoryRule):
    """Report links from memory pages to unknown targets."""

    rule_id, default_severity = "memory-dangling-link", "error"

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Report every outgoing memory edge whose target is absent."""
        memory_ids = {str(memory["concept_id"]) for memory in await ctx.memories()}
        page_ids = await ctx.page_ids()
        return [
            _finding(
                self.rule_id,
                self.default_severity,
                [str(edge["src"]), str(edge["dst"])],
                f"memory page {edge['src']!r} links to unknown page {edge['dst']!r}",
                rel=str(edge["rel"]),
            )
            for edge in await ctx.edges()
            if str(edge["src"]) in memory_ids and str(edge["dst"]) not in page_ids
        ]


class StaleMemoryRule(_MemoryRule):
    """A linked page changed after the memory was written (resolved: warning)."""

    rule_id, default_severity = "stale-memory", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Report links whose target was updated after the originating memory."""
        memories = {str(memory["concept_id"]): memory for memory in await ctx.memories()}
        pages = {str(page["concept_id"]): page for page in await ctx.pages()}
        findings: list[Finding] = []
        for edge in await ctx.edges():
            src = str(edge["src"])
            dst = str(edge["dst"])
            memory = memories.get(src)
            target = pages.get(dst)
            if memory is None or target is None:
                continue
            memory_updated_at = memory.get("updated_at")
            target_updated_at = target.get("updated_at")
            if target_updated_at and memory_updated_at and str(target_updated_at) > str(memory_updated_at):
                findings.append(
                    _finding(
                        self.rule_id,
                        self.default_severity,
                        [src, dst],
                        f"linked page {dst!r} changed after memory {src!r} was written",
                        rel=str(edge["rel"]),
                        memory_updated_at=str(memory_updated_at),
                        target_updated_at=str(target_updated_at),
                    )
                )
        return findings


MEMORY_RULES = [MemoryDanglingLinkRule, StaleMemoryRule]
