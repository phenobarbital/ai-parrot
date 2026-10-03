"""Route unfixable lint findings to the ledger, report files and page notes (FEAT-625)."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from parrot.knowledge.lint.models import Finding, LintOptions, LintReport
from parrot.knowledge.lint.rule import make_fingerprint
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens

FP_MARKER = "<!-- lint-fp:{fp} -->"


def render_markdown(report: LintReport) -> str:
    """Render a human-readable report grouped by rule and severity.

    Args:
        report: Completed lint report to render.

    Returns:
        Markdown representation of the report.
    """
    lines = [
        "# Wiki lint report",
        "",
        f"- Wiki: {report.wiki_name or '(unnamed)'}",
        f"- Backend: {report.backend or '(unknown)'}",
        f"- Findings: {len(report.findings)}",
        f"- Fixed: {len(report.fixed)}",
    ]
    if report.counts:
        counts = ", ".join(f"{severity}: {count}" for severity, count in sorted(report.counts.items()))
        lines.append(f"- Counts: {counts}")

    grouped: dict[str, dict[str, list[Finding]]] = defaultdict(lambda: defaultdict(list))
    for finding in report.findings:
        grouped[finding.rule_id][finding.severity].append(finding)

    for rule_id in sorted(grouped):
        lines.extend(("", f"## {rule_id}"))
        for severity in ("error", "warning", "info"):
            findings = grouped[rule_id].get(severity, [])
            if not findings:
                continue
            lines.extend(("", f"### {severity.title()}"))
            for finding in findings:
                subjects = ", ".join(finding.subjects) or "(no subject)"
                lines.append(f"- **{subjects}**: {finding.message} ({finding.fingerprint})")

    return "\n".join(lines) + "\n"


class FindingRouter:
    """Callable router injected into LintRunner (runner.router)."""

    def __init__(self, store: BaseWikiStore, *, report_dir: Path | None = None, ledger: Any | None = None) -> None:
        """Initialize the router.

        Args:
            store: Wiki store that owns pages receiving notes.
            report_dir: Default directory for rendered report files.
            ledger: Optional ledger service receiving unfixable findings.
        """
        self.store = store
        self.report_dir = report_dir
        self.ledger = ledger
        self.logger = logging.getLogger(__name__)

    async def __call__(self, report: LintReport, options: LintOptions) -> dict[str, int]:
        """Route a report using the configured destinations.

        Args:
            report: Completed lint report.
            options: Routing controls for the run.

        Returns:
            Counts of routed findings and report files.
        """
        return await self.route(report, options)

    async def route(self, report: LintReport, options: LintOptions) -> dict[str, int]:
        """Return counts for ledger, note and report routing.

        Args:
            report: Completed lint report.
            options: Routing controls for the run.

        Returns:
            Counts keyed by routing destination.
        """
        counts = {"ledger_opened": 0, "ledger_deduped": 0, "notes_added": 0, "report_files": 0}
        residue = [
            finding for finding in report.findings if not finding.fixable and finding.severity in ("warning", "error")
        ]
        if options.ledger and self.ledger is not None:
            await self._to_ledger(residue, options, counts)
        if options.notes:
            await self._to_notes(residue, counts)
        counts["report_files"] = await self._write_reports(report, options)
        return counts

    async def _to_ledger(self, findings: list[Finding], options: LintOptions, counts: dict[str, int]) -> None:
        """Open deduplicated ledger issues, aggregating excess findings by rule.

        Args:
            findings: Non-fixable warning and error findings.
            options: Routing controls containing the per-rule cap.
            counts: Mutable routing counters.
        """
        try:
            open_issues = await self.ledger.ready_work()
        except Exception:
            self.logger.exception("Unable to read open ledger issues for lint routing")
            return

        existing_markers = {
            marker for issue in open_issues for marker in (str(issue.get("body", "")), str(issue.get("title", "")))
        }
        grouped: dict[str, list[Finding]] = defaultdict(list)
        for finding in findings:
            grouped[finding.rule_id].append(finding)

        for rule_id, rule_findings in grouped.items():
            cap = max(options.ledger_cap_per_rule, 0)
            individual = rule_findings[:cap]
            overflow = rule_findings[cap:]
            for finding in individual:
                await self._open_finding_issue(finding, existing_markers, counts)
            if overflow:
                await self._open_aggregate_issue(rule_id, overflow, existing_markers, counts)

    async def _open_finding_issue(self, finding: Finding, existing_markers: set[str], counts: dict[str, int]) -> None:
        """Open one ledger issue unless its fingerprint marker already exists.

        Args:
            finding: Finding to route.
            existing_markers: Bodies and titles of currently open issues.
            counts: Mutable routing counters.
        """
        marker = FP_MARKER.format(fp=finding.fingerprint)
        if any(marker in existing for existing in existing_markers):
            counts["ledger_deduped"] += 1
            return
        subjects = ", ".join(finding.subjects) or "(no subject)"
        title = f"lint {finding.rule_id}: {finding.message} {marker}"
        body = f"Subjects: {subjects}\n\n{finding.message}\n\n{marker}"
        try:
            await self.ledger.open_issue(
                title=title,
                body=body,
                kind="bug" if finding.severity == "error" else "tech_debt",
                severity="major" if finding.severity == "error" else "minor",
                discovered_from=f"lint:{finding.rule_id}",
                about=finding.subjects,
                actor="agent:lint",
            )
        except Exception:
            self.logger.exception("Unable to route lint finding %s to the ledger", finding.fingerprint)
            return
        existing_markers.add(marker)
        counts["ledger_opened"] += 1

    async def _open_aggregate_issue(
        self,
        rule_id: str,
        findings: list[Finding],
        existing_markers: set[str],
        counts: dict[str, int],
    ) -> None:
        """Open one deterministic aggregate issue for excess findings.

        Args:
            rule_id: Rule shared by all excess findings.
            findings: Findings beyond the configured individual issue cap.
            existing_markers: Bodies and titles of currently open issues.
            counts: Mutable routing counters.
        """
        fingerprint = make_fingerprint(f"{rule_id}:aggregate", [finding.fingerprint for finding in findings])
        marker = FP_MARKER.format(fp=fingerprint)
        if any(marker in existing for existing in existing_markers):
            counts["ledger_deduped"] += len(findings)
            return

        has_error = any(finding.severity == "error" for finding in findings)
        subjects = [subject for finding in findings for subject in finding.subjects]
        entries = "\n".join(
            f"- {', '.join(finding.subjects) or '(no subject)'}: {finding.message}" for finding in findings
        )
        title = f"lint {rule_id}: {len(findings)} aggregated findings {marker}"
        body = f"Additional findings for {rule_id}:\n{entries}\n\n{marker}"
        try:
            await self.ledger.open_issue(
                title=title,
                body=body,
                kind="bug" if has_error else "tech_debt",
                severity="major" if has_error else "minor",
                discovered_from=f"lint:{rule_id}",
                about=subjects,
                actor="agent:lint",
            )
        except Exception:
            self.logger.exception("Unable to route aggregate lint findings for %s to the ledger", rule_id)
            return
        existing_markers.add(marker)
        counts["ledger_opened"] += 1

    async def _to_notes(self, findings: list[Finding], counts: dict[str, int]) -> None:
        """Append one fingerprinted note to every eligible subject page.

        Args:
            findings: Non-fixable warning and error findings.
            counts: Mutable routing counters.
        """
        stamp = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        for finding in findings:
            marker = FP_MARKER.format(fp=finding.fingerprint)
            for subject in finding.subjects:
                if subject.startswith("adr:"):
                    continue
                try:
                    page = await self.store.get_page(subject, include_body=True)
                    if page is None or marker in str(page.get("body") or ""):
                        continue
                    body = str(page.get("body") or "")
                    body += f"\n\n> **Note ({stamp}, lint):** {finding.message} {marker}"
                    await self.store.upsert_pages(
                        [
                            WikiPageRecord(
                                concept_id=str(page["concept_id"]),
                                node_id=page.get("node_id"),
                                title=str(page.get("title") or page["concept_id"]),
                                category=str(page.get("category") or "concept"),
                                summary=str(page.get("summary") or ""),
                                body=body,
                                source_id=page.get("source_id"),
                                token_count=estimate_tokens(body),
                                origin=str(page.get("origin") or "ingest"),
                                asserted_by="agent:lint",
                                updated_at=page.get("updated_at"),
                                content_hash=page.get("content_hash"),
                            )
                        ]
                    )
                except Exception:
                    self.logger.exception("Unable to append lint note to %s", subject)
                    continue
                counts["notes_added"] += 1

    async def _write_reports(self, report: LintReport, options: LintOptions) -> int:
        """Write JSON and Markdown report files without blocking the event loop.

        Args:
            report: Completed lint report.
            options: Routing controls containing an optional report directory.

        Returns:
            Number of report files written.
        """
        out = options.report_dir or self.report_dir
        if out is None:
            return 0

        def _write() -> int:
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out) / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
            (Path(out) / "report.md").write_text(render_markdown(report), encoding="utf-8")
            return 2

        try:
            return await asyncio.to_thread(_write)
        except Exception:
            self.logger.exception("Unable to write lint reports to %s", out)
            return 0
