"""Deterministic Markdown for the generated spec sections (FEAT-784 Module 7)."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Literal

from parrot.knowledge.wiki.decisions.consequences import (
    ConsequenceReport,
    ConsequenceService,
    GoverningDossier,
    GoverningEntry,
)
from parrot.knowledge.wiki.decisions.models import _Strict
from parrot.knowledge.wiki.store import estimate_tokens

GOVERNING_HEADING = "## Governing Decisions"
CONSEQUENCES_HEADING = "## Consequences"
NOT_CONFIGURED_LINE = "_decision audit not configured in this repository_"
_HEADER_RE = re.compile(
    r"<!-- decision-audit: input_digest=(\S+) evaluation_digest=(\S+) rules_version=(\d+) status=(\S+) -->"
)


class CheckResult(_Strict):
    """Outcome of a read-only check."""

    status: Literal["current", "stale", "missing"]
    report: ConsequenceReport


def _header(report: ConsequenceReport) -> str:
    """Return the stable, machine-readable section header."""
    rules = report.snapshot.rules_version if report.snapshot is not None else 0
    return (
        f"<!-- decision-audit: input_digest={report.input_digest} evaluation_digest={report.evaluation_digest} "
        f"rules_version={rules} status={report.status} -->"
    )


def _value(value: str | None) -> str:
    """Render an optional authored field without hiding missing data."""
    return value if value else "not recorded"


def _values(values: list[str]) -> str:
    """Render a deterministic list or an explicit missing-data marker."""
    return ", ".join(sorted(values)) if values else "not recorded"


def _governing_entry_lines(entry: GoverningEntry) -> list[str]:
    """Render one governing entry using only ``GoverningEntry`` fields."""
    supersedes = [f"{ref.decision_id}@{ref.revision}" for ref in entry.supersedes]
    return [
        f"### {entry.decision_id}@{entry.revision}",
        "",
        f"- Title: {_value(entry.title)}",
        f"- Statement: {_value(entry.statement)}",
        f"- Normative: {_value(entry.normative)}",
        f"- About: {_values(entry.about)}",
        f"- Targets: {_values(entry.targets)}",
        f"- Rationale: {_value(entry.rationale)}",
        f"- Consequences: {_value(entry.consequences)}",
        f"- Supersedes: {_values(supersedes)}",
        f"- Freshness: {_value(entry.freshness)}",
    ]


def render_governing(dossier: GoverningDossier, *, budget_tokens: int, report: ConsequenceReport) -> str:
    """Render the complete governing set, enumerating any presentation omissions."""
    lines = [GOVERNING_HEADING, "", _header(report), ""]
    if dossier.empty_plane:
        searched = ", ".join(sorted(dossier.searched_subsystems)) or "none"
        lines.append(f"No eligible decisions govern subsystems: {searched}")
        lines.append("")

    entries = sorted(dossier.entries, key=lambda entry: entry.decision_id)
    omitted = set(dossier.omitted_ids)
    for index, entry in enumerate(entries):
        entry_lines = _governing_entry_lines(entry)
        candidate = "\n".join([*lines, *entry_lines]).rstrip("\n") + "\n"
        if estimate_tokens(candidate) > budget_tokens:
            omitted.update(item.decision_id for item in entries[index:])
            break
        lines.extend(entry_lines)
        lines.append("")

    if omitted:
        lines.extend(["Omitted (budget):", *[f"- {decision_id}" for decision_id in sorted(omitted)], ""])
    return "\n".join(lines).rstrip("\n") + "\n"


def _one_line(value: str) -> str:
    """Collapse authored prose to one deterministic Markdown line."""
    return " ".join(value.split()) if value else "not recorded"


def render_consequences(report: ConsequenceReport) -> str:
    """Render status, every finding, diagnostics, coverage, and the lossless JSON report."""
    lines = [
        CONSEQUENCES_HEADING,
        "",
        _header(report),
        "",
        f"Audit status: `{report.status}` (exit {report.exit_code})",
        "",
        "Findings:",
    ]
    findings = sorted(report.findings, key=lambda finding: (finding.kind, finding.fingerprint))
    if findings:
        for finding in findings:
            severity = "BLOCKING" if finding.blocking else "advisory"
            waived_by = finding.waived_by or "not recorded"
            participants = _values(
                [f"{participant.decision_id}@{participant.revision}" for participant in finding.participants]
            )
            lines.append(
                f"- `{finding.kind}` [{severity}]; waived_by: {waived_by}; participants: {participants}; "
                f"scope: {_values(finding.scope)}; message: {_one_line(finding.message)}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "Diagnostics:"])
    diagnostics = sorted(
        report.diagnostics,
        key=lambda diagnostic: (
            diagnostic.code,
            diagnostic.path or "",
            diagnostic.decision_id or "",
            diagnostic.message,
        ),
    )
    if diagnostics:
        for diagnostic in diagnostics:
            lines.append(
                f"- `{diagnostic.code}`; path: {_value(diagnostic.path)}; message: {_one_line(diagnostic.message)}"
            )
    else:
        lines.append("- none")

    coverage = report.coverage
    lines.extend(
        [
            "",
            "Coverage:",
            f"- Subsystems: {_values(coverage.subsystems)}",
            f"- Unmapped tags: {_values(coverage.unmapped_tags)}",
            f"- Targets resolved: {coverage.targets_resolved}/{coverage.targets_total}",
            f"- Impact complete: {str(coverage.impact_complete).lower()}",
            f"- Inventory complete: {str(coverage.inventory_complete).lower()}",
            f"- Omitted ids: {_values(coverage.omitted_ids)}",
            "",
            "```json",
            json.dumps(report.model_dump(mode="json"), sort_keys=True, indent=2),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def _without_section(text: str, heading: str) -> str:
    """Remove every generated section with ``heading`` from Markdown text."""
    pattern = re.compile(rf"(?ms)^{re.escape(heading)}[ \t]*\n.*?(?=^## |\Z)")
    return pattern.sub("", text)


def _insert_before(text: str, block: str, anchor: re.Pattern[str]) -> str:
    """Insert ``block`` before an anchor, or append it when the anchor is absent."""
    normalized_block = block.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    match = anchor.search(text)
    if match is None:
        prefix = text.rstrip("\n")
        return f"{prefix}\n\n{normalized_block}\n" if prefix else f"{normalized_block}\n"
    prefix = text[: match.start()].rstrip("\n")
    suffix = text[match.start() :].lstrip("\n")
    if prefix:
        return f"{prefix}\n\n{normalized_block}\n\n{suffix}"
    return f"{normalized_block}\n\n{suffix}"


def splice_sections(text: str, governing_md: str, consequences_md: str) -> str:
    """Replace or insert both sections at fixed positions (before section 2 and section 8)."""
    result = text.replace("\r\n", "\n").replace("\r", "\n")
    result = _without_section(result, GOVERNING_HEADING)
    result = _without_section(result, CONSEQUENCES_HEADING)
    result = _insert_before(result, governing_md, re.compile(r"(?m)^## 2\."))
    result = _insert_before(result, consequences_md, re.compile(r"(?m)^## 8\."))
    return result


def _section_text(text: str, heading: str) -> str | None:
    """Return a generated section with one canonical trailing newline."""
    match = re.search(rf"(?ms)^{re.escape(heading)}[ \t]*\n.*?(?=^## |\Z)", text)
    if match is None:
        return None
    return match.group(0).rstrip("\n") + "\n"


def _read_header(text: str, heading: str) -> tuple[str, str] | None:
    """Return persisted input/evaluation digests, or ``None`` for an absent or malformed header."""
    section = _section_text(text, heading)
    if section is None:
        return None
    for line in section.splitlines()[1:]:
        if not line.strip():
            continue
        match = _HEADER_RE.fullmatch(line.strip())
        return None if match is None else (match.group(1), match.group(2))
    return None


def _render_skipped(text: str) -> str:
    """Remove generated sections and place one portability marker before section 2."""
    result = text.replace("\r\n", "\n").replace("\r", "\n")
    result = _without_section(result, GOVERNING_HEADING)
    result = _without_section(result, CONSEQUENCES_HEADING)
    result = re.sub(rf"(?m)^{re.escape(NOT_CONFIGURED_LINE)}[ \t]*\n?", "", result)
    return _insert_before(result, NOT_CONFIGURED_LINE, re.compile(r"(?m)^## 2\."))


async def render_spec(service: ConsequenceService, spec_path: Path, *, budget_tokens: int) -> ConsequenceReport:
    """Evaluate, render and splice, writing the spec only when its bytes change."""
    report = await service.evaluate(spec_path)
    path = service.root / spec_path
    text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    if report.status == "skipped":
        new_text = _render_skipped(text)
    else:
        dossier = await service.governing(spec_path, budget_tokens=budget_tokens)
        new_text = splice_sections(
            text,
            render_governing(dossier, budget_tokens=budget_tokens, report=report),
            render_consequences(report),
        )
    if new_text != text:
        await asyncio.to_thread(path.write_text, new_text, encoding="utf-8")
    return report


async def check_spec(service: ConsequenceService, spec_path: Path) -> CheckResult:
    """Recompute and compare digests and consequence content without writing."""
    report = await service.evaluate(spec_path)
    if report.status == "skipped":
        return CheckResult(status="current", report=report)
    text = await asyncio.to_thread((service.root / spec_path).read_text, encoding="utf-8")
    persisted = (_read_header(text, GOVERNING_HEADING), _read_header(text, CONSEQUENCES_HEADING))
    if None in persisted:
        return CheckResult(status="missing", report=report)
    expected_digests = (report.input_digest, report.evaluation_digest)
    if any(digests != expected_digests for digests in persisted):
        return CheckResult(status="stale", report=report)
    if _section_text(text, CONSEQUENCES_HEADING) != render_consequences(report):
        return CheckResult(status="stale", report=report)
    return CheckResult(status="current", report=report)
