"""Wiki index/overview + project meeting indexes (FEAT-481, spec Module 12,
contract §24/§18).

``Wiki/index.md`` (§24.1) and the §18 project meeting indexes are rendered
**deterministically** — every managed page is reachable, so there is
nothing for an LLM to judge. ``Wiki/overview.md`` (§24.2) is the one
piece here that needs a judgment call: it updates only on a **material**
change, which :func:`overview_materially_changed` asks the strong-tier
client to assess (never rewritten on every ingest).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel

from parrot.clients.base import AbstractClient

#: Bound on the "Recently Updated" trailing log so the index page does
#: not grow unbounded (oldest entries roll off, they remain discoverable
#: via `Wiki/log.md`, the append-only authority).
_MAX_RECENT_ENTRIES = 20


def render_wiki_index(
    projects: list[tuple[str, str]],
    recently_updated: list[tuple[str, str, str]],
) -> str:
    """§24.1 — render ``Wiki/index.md``, deterministically.

    Args:
        projects: ``(project_name, one_line_status)`` pairs, every
            managed project.
        recently_updated: ``(date, page_path, reason)`` triples, newest
            first — truncated to :data:`_MAX_RECENT_ENTRIES`.

    Returns:
        The full ``Wiki/index.md`` Markdown.
    """
    project_lines = (
        "\n".join(f"- [[Projects/{name}/{name}|{name}]] - {status}" for name, status in projects)
        if projects
        else "- None yet"
    )
    recent_lines = (
        "\n".join(f"- {d} - [[{page}]] - {reason}" for d, page, reason in recently_updated[:_MAX_RECENT_ENTRIES])
        if recently_updated
        else "- None yet"
    )

    return f"""# Wiki Index

## Overview
- [[Wiki/overview|Knowledge Overview]]

## Projects
{project_lines}

## Sources
- [[Wiki/Sources/index|Source Index]]

## Entities
- [[Wiki/Entities/index|Entity Index]]

## Concepts
- [[Wiki/Concepts/index|Concept Index]]

## Syntheses
- [[Wiki/Syntheses/index|Synthesis Index]]

## Contradictions
- [[Wiki/Contradictions/index|Contradiction Index]]

## Review Queue
- [[Wiki/Review Queue|Review Queue]]

## Recently Updated
{recent_lines}
"""


class OverviewChangeAssessment(BaseModel):
    """The strong-tier client's §24.2 materiality verdict."""

    materially_changed: bool
    reason: str


async def overview_materially_changed(
    strong_client: AbstractClient,
    existing_overview: str,
    new_developments: list[str],
) -> OverviewChangeAssessment:
    """§24.2 — decide whether ``Wiki/overview.md`` needs updating.

    Args:
        strong_client: The strong-tier :class:`AbstractClient`.
        existing_overview: The current overview body.
        new_developments: This ingest's material developments (decisions,
            new projects, contradictions, ...).

    Returns:
        The :class:`OverviewChangeAssessment`.
    """
    if not new_developments:
        return OverviewChangeAssessment(materially_changed=False, reason="No new developments this operation.")

    prompt = "\n".join(
        [
            "Existing overview:",
            existing_overview or "(none yet)",
            "",
            "This operation's developments:",
            *[f"- {d}" for d in new_developments],
            "",
            (
                "Does this materially change the active project portfolio, major "
                "organizational priorities, shared risks/blockers, cross-project "
                "dependencies, important recurring concepts, or important unresolved "
                "contradictions (contract §24.2)?"
            ),
        ]
    )
    result = await strong_client.invoke(prompt, output_type=OverviewChangeAssessment, temperature=0.0)
    return result.output


def render_overview(existing_overview: str, addition: str) -> str:
    """§24.2 — append a materially-significant addition to the overview.

    Args:
        existing_overview: The current overview body (empty on first
            write).
        addition: The new material statement(s) to fold in — every major
            statement must already link to its supporting page (§24.2).

    Returns:
        The updated overview body.
    """
    if not existing_overview.strip():
        return addition.strip() + "\n"
    return f"{existing_overview.rstrip()}\n\n{addition.strip()}\n"


def render_project_meeting_index_active(project_name: str, entries: list[tuple[str, str, str]]) -> str:
    """§18 — the active project meeting index.

    Args:
        project_name: The project's Title-Case name.
        entries: ``(date, meeting_page_link, one_line_significance)``
            triples, already filtered to the active window.

    Returns:
        The rendered ``Meeting Summaries/index.md`` Markdown.
    """
    lines = "\n".join(f"- {d} - [[{link}|{link.rsplit('/', 1)[-1]}]] - {sig}" for d, link, sig in entries)
    return f"# {project_name} - Meeting Summaries\n\n## Active Meetings\n\n{lines or '- None yet'}\n"


def render_project_meeting_index_archive(project_name: str, entries: list[tuple[str, str, str]]) -> str:
    """§18 — the archived project meeting index, grouped by ``YYYY``/``MM``.

    Args:
        project_name: The project's Title-Case name.
        entries: ``(date, meeting_page_link, one_line_significance)``
            triples, already filtered to OUTSIDE the active window.

    Returns:
        The rendered ``Meeting Summaries/Archive/index.md`` Markdown.
    """
    by_year_month: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    for d, link, sig in entries:
        year, month = d[:4], d[5:7]
        by_year_month.setdefault((year, month), []).append((d, link, sig))

    sections = []
    for year, month in sorted(by_year_month):
        rows = by_year_month[(year, month)]
        lines = "\n".join(f"- {d} - [[{link}|{link.rsplit('/', 1)[-1]}]] - {sig}" for d, link, sig in rows)
        sections.append(f"## {year}\n\n### {month}\n\n{lines}")

    body = "\n\n".join(sections) if sections else "## None yet"
    return f"# {project_name} - Archived Meeting Summaries\n\n{body}\n"


def split_active_and_archived(
    entries: list[tuple[str, str, str]],
    *,
    active_window_days: int,
    today: date | None = None,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """§18/§31 — split meeting-index entries by the configurable active window.

    Args:
        entries: ``(date, meeting_page_link, one_line_significance)``
            triples.
        active_window_days: The active window (days) —
            ``conf.WIKI_KB_ACTIVE_WINDOW_DAYS`` (default 14, D7).
        today: The reference date (defaults to today, UTC).

    Returns:
        ``(active, archived)`` — ``active`` sorted newest-first,
        ``archived`` sorted oldest-first (for the year/month grouping).
    """
    reference = today or datetime.now(UTC).date()
    cutoff = reference - timedelta(days=active_window_days)

    active = [e for e in entries if date.fromisoformat(e[0]) >= cutoff]
    archived = [e for e in entries if date.fromisoformat(e[0]) < cutoff]

    active.sort(key=lambda e: e[0], reverse=True)
    archived.sort(key=lambda e: e[0])
    return active, archived
