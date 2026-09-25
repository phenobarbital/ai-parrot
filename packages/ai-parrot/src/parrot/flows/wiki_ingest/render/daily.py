"""Deterministic §23 daily note renderer (FEAT-481, spec Module 12).

Reproduces the contract's §23 template verbatim. The daily note is a
**synthesis** across the day's meetings, never a concatenation — the
merge/de-duplication happens in ``nodes/daily.py`` before this module
ever sees the final :class:`DailyState`; this renderer only lays out
already-synthesized content.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import DailyNoteFrontmatter


class ProjectUpdateEntry(BaseModel):
    """One ``### [[Project Name]]`` block under ``## Project Updates``."""

    project_name: str
    updates: list[str] = Field(default_factory=list)


class DailyState(BaseModel):
    """The daily note's typed state (§23 sections).

    Attributes:
        daily_summary: The most important developments across the day.
        project_updates: One entry per project touched that day.
        decisions: Decisions + affected project.
        action_items: Action, owner, due date, and project.
        risks: Risks or blockers.
        contradictions_and_review: Contradiction/review-item wikilinks.
        meetings: Meeting source page wikilink targets.
        human_notes: Preserved verbatim across updates.
    """

    daily_summary: str = ""
    project_updates: list[ProjectUpdateEntry] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    contradictions_and_review: list[str] = Field(default_factory=list)
    meetings: list[str] = Field(default_factory=list)
    human_notes: str = ""


def _bullets(items: list[str], *, empty_placeholder: str) -> str:
    if not items:
        return f"- {empty_placeholder}"
    return "\n".join(f"- {item}" for item in items)


def _project_updates(entries: list[ProjectUpdateEntry]) -> str:
    if not entries:
        return "None identified"
    blocks = []
    for entry in entries:
        heading = f"### [[Projects/{entry.project_name}/{entry.project_name}|{entry.project_name}]]"
        blocks.append(f"{heading}\n{_bullets(entry.updates, empty_placeholder='No material update.')}")
    return "\n\n".join(blocks)


def _meetings(meetings: list[str]) -> str:
    if not meetings:
        return "- None identified"
    return "\n".join(f"- [[{m}]]" for m in meetings)


def _frontmatter_block(frontmatter: DailyNoteFrontmatter) -> str:
    import yaml

    data = frontmatter.model_dump(exclude_none=False)
    block = yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{block}---"


def render_daily_page(frontmatter: DailyNoteFrontmatter, state: DailyState) -> str:
    """Render the exact §23 daily note.

    Args:
        frontmatter: The validated §10.6 frontmatter.
        state: The day's synthesized :class:`DailyState`.

    Returns:
        The full Markdown page (frontmatter + body).
    """
    body = f"""
# {frontmatter.title}

## Daily Summary
{state.daily_summary or "Not established"}

## Project Updates
{_project_updates(state.project_updates)}

## Decisions
{_bullets(state.decisions, empty_placeholder="None identified")}

## Action Items
{_bullets(state.action_items, empty_placeholder="None identified")}

## Risks and Blockers
{_bullets(state.risks, empty_placeholder="None identified")}

## Contradictions and Review Items
{_bullets(state.contradictions_and_review, empty_placeholder="None identified")}

## Meetings
{_meetings(state.meetings)}

## Human Notes
{state.human_notes or "(none)"}
""".strip("\n")

    return f"{_frontmatter_block(frontmatter)}\n\n{body}\n"
