"""Deterministic §19 canonical project page renderer + parser (FEAT-481,
spec Module 9).

Reproduces the §19 template **verbatim**. The **parser** is this module's
other half — it round-trips our own render format back into a
:class:`ProjectState` so the reconciler (``nodes/project_reconcile.py``)
can perform a **typed section-merge** against the parsed current state
instead of a free-form whole-page regeneration (§3.1 / this task's
Implementation Notes).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..models import ProjectFrontmatter

_CLAIM_LINE_RE = re.compile(r"^- (?P<text>.*) — \[\[(?P<source>.*)\]\](?P<superseded> \(superseded\))?$")
_STAKEHOLDER_ROW_RE = re.compile(
    r"^\| \[\[Wiki/Entities/People/(?P<person>[^|]+)\|[^\]]+\]\] \| (?P<role>[^|]+) \| (?P<responsibility>[^|]+) \|$"
)
_WORKSTREAM_ROW_RE = re.compile(
    r"^\| (?P<task>[^|]+) \| (?P<owner>[^|]+) \| (?P<status>[^|]+) \| (?P<due>[^|]+) \| \[\[(?P<source>[^\]]+)\]\] \|$"
)


class SourcedClaim(BaseModel):
    """One material claim, linked to its supporting source page (rule #10).

    Attributes:
        text: The claim text (e.g. a decision, requirement, or risk).
        source: The wikilink target of the supporting meeting source page.
        superseded: ``True`` once a newer meeting explicitly supersedes
            this claim (§19 rule 3) — superseded claims are still kept,
            never deleted (§19 rule 5 / Q2 diff-guard).
    """

    text: str
    source: str
    superseded: bool = False


class StakeholderRow(BaseModel):
    """One ``## Stakeholders`` table row."""

    person: str
    role: str
    responsibility: str


class WorkstreamRow(BaseModel):
    """One ``## Workstreams and Tasks`` table row."""

    task: str
    owner: str
    status: str
    due_date: str
    source: str


class ProjectState(BaseModel):
    """The project page's full typed state (§19 sections).

    Every section the §19 template defines has a typed field here — the
    reconciler merges into this structure section-by-section, never by
    regenerating page markdown as free text.
    """

    executive_summary: str = ""
    objectives: list[str] = Field(default_factory=list)
    scope_in: list[str] = Field(default_factory=list)
    scope_out: list[str] = Field(default_factory=list)
    stakeholders: list[StakeholderRow] = Field(default_factory=list)
    current_status: str = ""
    current_requirements: list[SourcedClaim] = Field(default_factory=list)
    current_decisions: list[SourcedClaim] = Field(default_factory=list)
    workstreams: list[WorkstreamRow] = Field(default_factory=list)
    timeline: list[str] = Field(default_factory=list)
    risks: list[SourcedClaim] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    unresolved_contradictions: list[str] = Field(default_factory=list)
    clients: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    recent_source_updates: list[str] = Field(default_factory=list)
    human_notes: str = ""


def _bullets(items: list[str], *, empty_placeholder: str = "Not established") -> str:
    if not items:
        return f"- {empty_placeholder}"
    return "\n".join(f"- {item}" for item in items)


def _claim_bullets(claims: list[SourcedClaim], *, empty_placeholder: str = "None identified") -> str:
    if not claims:
        return f"- {empty_placeholder}"
    lines = []
    for claim in claims:
        suffix = " (superseded)" if claim.superseded else ""
        lines.append(f"- {claim.text} — [[{claim.source}]]{suffix}")
    return "\n".join(lines)


def _wikilink_bullets(prefix: str, names: list[str], *, empty_placeholder: str = "None identified") -> str:
    if not names:
        return f"- {empty_placeholder}"
    return "\n".join(f"- [[{prefix}/{name}|{name}]]" for name in names)


def _stakeholders_table(rows: list[StakeholderRow]) -> str:
    header = "| Person or Team | Role | Responsibility |\n| --- | --- | --- |"
    if not rows:
        return f"{header}\n| Unknown | Unknown | Unknown |"
    body = "\n".join(
        f"| [[Wiki/Entities/People/{r.person}|{r.person}]] | {r.role} | {r.responsibility} |" for r in rows
    )
    return f"{header}\n{body}"


def _workstreams_table(rows: list[WorkstreamRow]) -> str:
    header = "| Workstream or task | Owner | Status | Due date | Source |\n| --- | --- | --- | --- | --- |"
    if not rows:
        return f"{header}\n| None identified | Unknown | Unknown | Unknown | Unknown |"
    body = "\n".join(f"| {r.task} | {r.owner} | {r.status} | {r.due_date} | [[{r.source}]] |" for r in rows)
    return f"{header}\n{body}"


def _related_knowledge(clients: list[str], products: list[str], concepts: list[str]) -> str:
    def _line(label: str, prefix: str, names: list[str]) -> str:
        if not names:
            return f"- {label}: None identified"
        links = ", ".join(f"[[{prefix}/{name}|{name}]]" for name in names)
        return f"- {label}: {links}"

    return "\n".join(
        [
            _line("Clients", "Wiki/Entities/Companies", clients),
            _line("Products", "Wiki/Entities/Products", products),
            _line("Concepts", "Wiki/Concepts", concepts),
        ]
    )


def _frontmatter_block(frontmatter: ProjectFrontmatter) -> str:
    import yaml

    data = frontmatter.model_dump(exclude_none=False)
    block = yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{block}---"


def render_project_page(frontmatter: ProjectFrontmatter, state: ProjectState) -> str:
    """Render the exact §19 canonical project page.

    Args:
        frontmatter: The validated §10.2 frontmatter.
        state: The project's full typed :class:`ProjectState`.

    Returns:
        The full Markdown page (frontmatter + body).
    """
    body = f"""
# {frontmatter.title}

## Executive Summary
{state.executive_summary or "Not established"}

## Objectives and Success Criteria
{_bullets(state.objectives)}

## Scope
### In Scope
{_bullets(state.scope_in)}

### Out of Scope
{_bullets(state.scope_out)}

## Stakeholders
{_stakeholders_table(state.stakeholders)}

## Current Status
{state.current_status or "Not established"}

## Current Requirements
{_claim_bullets(state.current_requirements)}

## Current Decisions
{_claim_bullets(state.current_decisions)}

## Workstreams and Tasks
{_workstreams_table(state.workstreams)}

## Timeline and Milestones
{_bullets(state.timeline)}

## Risks and Blockers
{_claim_bullets(state.risks)}

## Open Questions
{_bullets(state.open_questions)}

## Unresolved Contradictions
{_wikilink_bullets("Wiki/Contradictions", state.unresolved_contradictions)}

## Related Knowledge
{_related_knowledge(state.clients, state.products, state.concepts)}

## Recent Source Updates
{_bullets(state.recent_source_updates, empty_placeholder="None identified")}

## Human Notes
{state.human_notes or "(none)"}
""".strip("\n")

    return f"{_frontmatter_block(frontmatter)}\n\n{body}\n"


def _parse_section(content: str, heading: str) -> str:
    """Extract the raw body text of one ``## <heading>`` section.

    Args:
        content: The full page body (post-frontmatter).
        heading: The exact heading text (without ``##``).

    Returns:
        The section's raw text (between this heading and the next
        ``##``/``###`` at the same or shallower level), stripped. Empty
        string if the heading is not found.
    """
    pattern = re.compile(rf"^## {re.escape(heading)}\n(.*?)(?=\n## |\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(content)
    return match.group(1).strip() if match else ""


def _parse_section_raw(content: str, heading: str) -> str:
    """Extract a section body WITHOUT normalizing whitespace.

    Unlike :func:`_parse_section`, this preserves the author's leading
    indentation and internal whitespace verbatim — required for sections
    the contract must round-trip byte-for-byte (e.g. ``## Human Notes``,
    §2 rule 13 / §19: "preserve Human Notes verbatim"). Only the single
    structural trailing newline the renderer appends is removed.

    Args:
        content: The full page body (post-frontmatter).
        heading: The exact heading text (without ``##``).

    Returns:
        The section's raw text with only the structural trailing newline
        stripped. Empty string if the heading is not found.
    """
    pattern = re.compile(rf"^## {re.escape(heading)}\n(.*?)(?=\n## |\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(content)
    return match.group(1).removesuffix("\n") if match else ""


def _parse_subsection(content: str, heading: str, subheading: str) -> str:
    """Extract a ``### <subheading>`` body nested under ``## <heading>``."""
    section = _parse_section(content, heading)
    pattern = re.compile(rf"^### {re.escape(subheading)}\n(.*?)(?=\n### |\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(section)
    return match.group(1).strip() if match else ""


def _parse_bullets(text: str) -> list[str]:
    lines = [line[2:].strip() for line in text.splitlines() if line.startswith("- ")]
    placeholders = {"not established", "none identified", "unknown"}
    if len(lines) == 1 and lines[0].lower() in placeholders:
        return []
    return lines


def _parse_claims(text: str) -> list[SourcedClaim]:
    claims = []
    for line in text.splitlines():
        match = _CLAIM_LINE_RE.match(line)
        if match:
            claims.append(
                SourcedClaim(
                    text=match.group("text"),
                    source=match.group("source"),
                    superseded=bool(match.group("superseded")),
                )
            )
    return claims


def _parse_wikilink_names(text: str) -> list[str]:
    names = []
    for line in text.splitlines():
        match = re.match(r"^- \[\[[^|\]]+\|([^\]]+)\]\]$", line)
        if match:
            names.append(match.group(1))
    return names


def _parse_stakeholders(text: str) -> list[StakeholderRow]:
    rows = []
    for line in text.splitlines():
        match = _STAKEHOLDER_ROW_RE.match(line)
        if match:
            rows.append(StakeholderRow(**{k: v.strip() for k, v in match.groupdict().items()}))
    return rows


def _parse_workstreams(text: str) -> list[WorkstreamRow]:
    rows = []
    for line in text.splitlines():
        match = _WORKSTREAM_ROW_RE.match(line)
        if match:
            groups = match.groupdict()
            rows.append(
                WorkstreamRow(
                    task=groups["task"].strip(),
                    owner=groups["owner"].strip(),
                    status=groups["status"].strip(),
                    due_date=groups["due"].strip(),
                    source=groups["source"].strip(),
                )
            )
    return rows


def _parse_related_knowledge(text: str, label: str) -> list[str]:
    for line in text.splitlines():
        if line.startswith(f"- {label}:"):
            rest = line.split(":", 1)[1].strip()
            if rest == "None identified":
                return []
            return re.findall(r"\[\[[^|\]]+\|([^\]]+)\]\]", rest)
    return []


def parse_project_page(content: str) -> ProjectState:
    """Round-trip our own §19 render format back into a :class:`ProjectState`.

    Args:
        content: The full page markdown (frontmatter + body), as
            previously produced by :func:`render_project_page`.

    Returns:
        The parsed :class:`ProjectState`.
    """
    body = content.split("---", 2)[-1] if content.startswith("---") else content

    executive_summary = _parse_section(body, "Executive Summary")
    if executive_summary.lower() == "not established":
        executive_summary = ""
    current_status = _parse_section(body, "Current Status")
    if current_status.lower() == "not established":
        current_status = ""
    # §2 rule 13 — Human Notes are human-authored and must round-trip
    # verbatim; parse them WITHOUT stripping so leading indentation
    # (e.g. an indented code block) survives every reconcile.
    human_notes = _parse_section_raw(body, "Human Notes")
    if human_notes.strip() == "(none)":
        human_notes = ""

    return ProjectState(
        executive_summary=executive_summary,
        objectives=_parse_bullets(_parse_section(body, "Objectives and Success Criteria")),
        scope_in=_parse_bullets(_parse_subsection(body, "Scope", "In Scope")),
        scope_out=_parse_bullets(_parse_subsection(body, "Scope", "Out of Scope")),
        stakeholders=_parse_stakeholders(_parse_section(body, "Stakeholders")),
        current_status=current_status,
        current_requirements=_parse_claims(_parse_section(body, "Current Requirements")),
        current_decisions=_parse_claims(_parse_section(body, "Current Decisions")),
        workstreams=_parse_workstreams(_parse_section(body, "Workstreams and Tasks")),
        timeline=_parse_bullets(_parse_section(body, "Timeline and Milestones")),
        risks=_parse_claims(_parse_section(body, "Risks and Blockers")),
        open_questions=_parse_bullets(_parse_section(body, "Open Questions")),
        unresolved_contradictions=_parse_wikilink_names(_parse_section(body, "Unresolved Contradictions")),
        clients=_parse_related_knowledge(_parse_section(body, "Related Knowledge"), "Clients"),
        products=_parse_related_knowledge(_parse_section(body, "Related Knowledge"), "Products"),
        concepts=_parse_related_knowledge(_parse_section(body, "Related Knowledge"), "Concepts"),
        recent_source_updates=_parse_bullets(_parse_section(body, "Recent Source Updates")),
        human_notes=human_notes,
    )
