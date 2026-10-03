"""Plane rule pack — report-only integrity rules (FEAT-625)."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, FixResult, Severity
from parrot.knowledge.lint.rule import make_fingerprint
from parrot.knowledge.pageindex.okf.concept_id import _slugify


def _finding(rule_id: str, severity: Severity, subjects: list[str], message: str, **data: object) -> Finding:
    """Create a consistently fingerprinted report-only finding."""
    return Finding(
        rule_id=rule_id,
        severity=severity,
        subjects=subjects,
        message=message,
        fingerprint=make_fingerprint(rule_id, subjects),
        data=data,
    )


class _ReportOnly:
    """Shared no-op fix implementation for report-only plane rules."""

    pack = "plane"

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult | None:
        """Return no fix because plane findings require manual remediation."""
        return None


class BrokenLinkRule(_ReportOnly):
    """Edge target does not resolve in this wiki or namespace."""

    rule_id, default_severity = "broken-link", "error"

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Report each edge classified as broken by the active store."""
        findings: list[Finding] = []
        for edge in await ctx.store.broken_edges():
            src = str(edge["src"])
            dst = str(edge["dst"])
            rel = str(edge["rel"])
            data = {key: value for key, value in edge.items() if key not in {"src", "dst", "rel"}}
            findings.append(
                _finding(
                    self.rule_id,
                    self.default_severity,
                    [src, dst],
                    f"edge from {src!r} to {dst!r} (rel: {rel!r}) targets an unresolved page",
                    rel=rel,
                    **data,
                )
            )
        return findings


class DuplicateSlugRule(_ReportOnly):
    """Two or more pages whose title slugifies to the same slug."""

    rule_id, default_severity = "duplicate-slug", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Report every slug shared by two or more page identifiers."""
        groups: dict[str, list[str]] = defaultdict(list)
        for page in await ctx.pages():
            groups[_slugify(str(page.get("title") or page["concept_id"]))].append(str(page["concept_id"]))
        return [
            _finding(
                self.rule_id,
                self.default_severity,
                sorted(ids),
                f"slug {slug!r} shared by {len(ids)} pages",
                slug=slug,
            )
            for slug, ids in sorted(groups.items())
            if len(ids) > 1
        ]


class OrphanPageRule(_ReportOnly):
    """Page has no inbound edge and is not a designated root."""

    rule_id, default_severity = "orphan-page", "warning"
    _ROOT_PREFIXES = ("adr:", "issue:", "spec:")

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Report non-root pages that are not the destination of an edge."""
        page_ids = await ctx.page_ids()
        inbound_ids = {str(edge["dst"]) for edge in await ctx.edges()}
        return [
            _finding(self.rule_id, self.default_severity, [concept_id], "page has no inbound edge")
            for concept_id in sorted(page_ids - inbound_ids)
            if not concept_id.startswith(self._ROOT_PREFIXES)
        ]


class OrphanSourceRule(_ReportOnly):
    """Source is registered but did not produce a page."""

    rule_id, default_severity = "orphan-source", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Report sources returned by the store's orphan-source fast path."""
        return [
            _finding(self.rule_id, self.default_severity, [source_id], "source produced no pages")
            for source_id in await ctx.store.orphan_sources()
        ]


class MissingBodyRule(_ReportOnly):
    """Page body is empty."""

    rule_id, default_severity = "missing-body", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Report pages returned by the store's missing-body fast path."""
        return [
            _finding(self.rule_id, self.default_severity, [concept_id], "page has an empty body")
            for concept_id in await ctx.store.missing_bodies()
        ]


class StaleSourceRule(_ReportOnly):
    """Tracked source changed since its last ingestion."""

    rule_id, default_severity = "stale-source", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Report stale tracked sources when a source manager is available."""
        sources = ctx.extras.get("sources")
        if sources is None:
            return []
        entries = await asyncio.to_thread(sources.list_sources)
        findings: list[Finding] = []
        for entry in entries:
            if await asyncio.to_thread(sources.is_stale, entry.source_id):
                findings.append(
                    _finding(self.rule_id, self.default_severity, [entry.source_id], "source has changed since ingestion")
                )
        return findings


PLANE_RULES = [BrokenLinkRule, OrphanPageRule, OrphanSourceRule, DuplicateSlugRule, MissingBodyRule, StaleSourceRule]
