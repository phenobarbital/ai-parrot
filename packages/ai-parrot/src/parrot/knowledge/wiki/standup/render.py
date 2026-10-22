"""Pure localized Markdown rendering for daily and period briefs."""

from parrot.knowledge.wiki.standup.models import BriefDocument, BriefItem, BriefSection, ProjectSlice

HEADINGS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Daily brief",
        "weekly_title": "Weekly brief",
        "monthly_title": "Monthly brief",
        "plate": "On your plate today",
        "by_project": "By project",
        "internal": "Internal",
        "since": "Since last brief",
        "hygiene": "Hygiene",
        "blocked": "Blocked",
        "tickets": "Open tickets",
        "recent": "Recent",
        "upcoming": "Upcoming",
        "decisions": "Open decisions",
        "drafts": "Drafts in flight",
        "tasks": "Tasks",
        "memories": "Memories",
        "new": "New",
        "closed": "Closed",
        "closed_period": "Closed this period",
        "still_open": "Still open",
        "decisions_taken": "Decisions taken",
        "sources": "Daily brief sources",
        "diagnostics": "Diagnostics",
    },
    "es": {
        "title": "Resumen diario",
        "weekly_title": "Resumen semanal",
        "monthly_title": "Resumen mensual",
        "plate": "Tus pendientes de hoy",
        "by_project": "Por proyecto",
        "internal": "Interno",
        "since": "Desde el último resumen",
        "hygiene": "Higiene",
        "blocked": "Bloqueado",
        "tickets": "Tickets abiertos",
        "recent": "Reciente",
        "upcoming": "Próximamente",
        "decisions": "Decisiones abiertas",
        "drafts": "Borradores en curso",
        "tasks": "Tareas",
        "memories": "Memorias",
        "new": "Nuevos",
        "closed": "Cerrados",
        "closed_period": "Cerrado este periodo",
        "still_open": "Aún abierto",
        "decisions_taken": "Decisiones tomadas",
        "sources": "Fuentes de resúmenes diarios",
        "diagnostics": "Diagnósticos",
    },
}


def _escape(value: str) -> str:
    """Escape inline Markdown syntax without translating its text."""
    for character in ("\\", "`", "*", "_", "{", "}", "[", "]", "<", ">"):
        value = value.replace(character, f"\\{character}")
    return value


def _item_reference(item: BriefItem) -> str:
    """Render a stable item reference while retaining its verbatim title."""
    title = _escape(item.title)
    if item.url:
        return f"[{title}]({_escape(item.url)})"
    return f"[[{_escape(item.id)}|{title}]]"


def _item_line(item: BriefItem, label: str) -> str:
    """Render one item with a localized section label and stable reference."""
    details = item.status or item.status_raw or "unknown"
    if item.age_days is not None:
        details = f"{details} — {item.age_days} days old"
    return f"- **{label}:** {_item_reference(item)} ({details})"


def _section_lines(sections: list[BriefSection], headings: dict[str, str]) -> list[str]:
    """Render populated sections as deterministic item lines."""
    lines: list[str] = []
    for section in sections:
        label = headings.get(section.key, section.key.replace("_", " ").title())
        lines.extend(_item_line(item, label) for item in section.items)
    return lines


def _project_lines(project: ProjectSlice, headings: dict[str, str]) -> list[str]:
    """Render one non-empty project slice."""
    lines = [f"### [[{_escape(project.project)}]]" + (f" — {_escape(project.status)}" if project.status else "")]
    lines.extend(_section_lines(project.sections, headings))
    return lines


def _hygiene_lines(doc: BriefDocument) -> list[str]:
    """Render source health fields and diagnostics without source bodies."""
    report = doc.hygiene
    lines = [
        f"- Ledger blockers: {report.ledger_blockers}",
        f"- Proposed decisions older than threshold: {report.proposed_decisions_older_than}",
        f"- Stale tickets: {report.stale_tickets}",
        f"- LLM: {_escape(report.llm)}",
    ]
    if report.unmapped_statuses:
        mapped = ", ".join(f"{_escape(key)} ({value})" for key, value in sorted(report.unmapped_statuses.items()))
        lines.append(f"- Unmapped statuses: {mapped}")
    if report.jira_watermark:
        lines.append(f"- Jira watermark: {_escape(report.jira_watermark)}")
    if report.attrs_indexed is not None:
        lines.append(f"- Attributes indexed: {report.attrs_indexed}")
    if report.last_lint:
        lines.append(f"- Last lint: {_escape(report.last_lint)}")
    return lines


def _rollup_sections(doc: BriefDocument) -> tuple[list[BriefSection], list[BriefSection]]:
    """Split live non-decision and decision sections for a period roll-up."""
    sections = [section for project in doc.projects for section in project.sections]
    sections.extend(doc.internal)
    return (
        [section for section in sections if section.key != "decisions"],
        [section for section in sections if section.key == "decisions"],
    )


def render_markdown(doc: BriefDocument, language: str) -> str:
    """Render stable daily or roll-up Markdown sections and source references.

    Args:
        doc: Fully collected brief data.
        language: Heading language, either ``en`` or ``es``.

    Returns:
        Localized deterministic Markdown with source titles left verbatim.

    Raises:
        ValueError: If ``language`` is not supported.
    """
    try:
        headings = HEADINGS[language]
    except KeyError as exc:
        raise ValueError(f"Unsupported standup language: {language}") from exc

    period = doc.window.period
    title_key = "title" if period == "day" else f"{period}ly_title"
    title = headings[title_key]
    date_label = doc.window.anchor.isoformat() if period == "day" else f"{doc.window.start} to {doc.window.end}"
    lines = [f"# {title} — {date_label}"]

    if period == "day":
        if doc.on_your_plate:
            lines.extend(["", f"## {headings['plate']}", ""])
            lines.extend(f"- {_escape(item)}" for item in doc.on_your_plate[:3])
        project_lines = [
            line for project in doc.projects if project.sections for line in _project_lines(project, headings)
        ]
        if project_lines:
            lines.extend(["", f"## {headings['by_project']}", "", *project_lines])
        internal_lines = _section_lines(doc.internal, headings)
        if internal_lines:
            lines.extend(["", f"## {headings['internal']}", "", *internal_lines])
    else:
        open_sections, decision_sections = _rollup_sections(doc)
        if doc.delta_closed:
            lines.extend(["", f"## {headings['closed_period']}", ""])
            lines.extend(_item_line(item, headings["closed"]) for item in doc.delta_closed)
        open_lines = _section_lines(open_sections, headings)
        if open_lines:
            lines.extend(["", f"## {headings['still_open']}", "", *open_lines])
        decision_lines = _section_lines(decision_sections, headings)
        if decision_lines:
            lines.extend(["", f"## {headings['decisions_taken']}", "", *decision_lines])
        if doc.sources:
            lines.extend(["", f"## {headings['sources']}", ""])
            lines.extend(f"- [[{_escape(source)}]]" for source in sorted(doc.sources))

    if doc.previous_brief_id and (doc.delta_new or doc.delta_closed):
        lines.extend(["", f"## {headings['since']}"])
        if doc.delta_new:
            lines.extend(["", *(_item_line(item, headings["new"]) for item in doc.delta_new)])
        if doc.delta_closed:
            lines.extend(["", *(_item_line(item, headings["closed"]) for item in doc.delta_closed)])

    lines.extend(["", f"## {headings['hygiene']}", "", *_hygiene_lines(doc)])
    if doc.diagnostics:
        lines.extend(["", f"### {headings['diagnostics']}", ""])
        lines.extend(f"- {_escape(diagnostic)}" for diagnostic in doc.diagnostics)
    return "\n".join(lines) + "\n"
