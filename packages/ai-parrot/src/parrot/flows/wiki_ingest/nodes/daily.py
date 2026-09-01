"""Daily diary synthesis node (FEAT-481, spec Module 12, contract §23).

The daily note is a **synthesis** of every meeting processed for a given
date — never a concatenation. When a second meeting lands on the same
date, the existing note is parsed back into a typed
:class:`~..render.daily.DailyState` and the cheap-tier client is asked to
merge + de-duplicate, not simply append a second copy of similar
statements.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from parrot.clients.base import AbstractClient

from ..models import DailyNoteFrontmatter
from ..naming import now_iso
from ..render.daily import DailyState, ProjectUpdateEntry, render_daily_page
from ..render.project import _parse_section

_SYSTEM_PROMPT = (
    "You are synthesizing a daily note across one or more meetings for a "
    "governed knowledge base (contract §23). Merge the existing daily summary "
    "with the new meeting's material developments — produce ONE coherent "
    "synthesis, not a concatenation. Remove duplicate or redundant statements. "
    "Only include developments actually supported by the day's meetings "
    "(rule #12)."
)


class DailySynthesisProposal(BaseModel):
    """The cheap-tier client's typed §23 synthesis proposal."""

    daily_summary: str
    project_updates: list[ProjectUpdateEntry] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class DailySynthesisResult(BaseModel):
    """Result of one daily-note synthesis call.

    Attributes:
        frontmatter: The validated §10.6 frontmatter.
        content: The rendered page.
        vault_path: ``Diary/Daily Notes/<date>.md``.
    """

    frontmatter: DailyNoteFrontmatter
    content: str
    vault_path: str


def _parse_daily_body(content: str) -> DailyState:
    """Best-effort round-trip of our own §23 render format."""
    body = content.split("---", 2)[-1] if content.startswith("---") else content

    daily_summary = _parse_section(body, "Daily Summary")
    if daily_summary.lower() == "not established":
        daily_summary = ""
    human_notes = _parse_section(body, "Human Notes")
    if human_notes == "(none)":
        human_notes = ""

    project_updates = []
    updates_section = _parse_section(body, "Project Updates")
    if updates_section.strip() != "None identified":
        for block in re.split(r"(?=^### )", updates_section, flags=re.MULTILINE):
            block = block.strip()
            if not block:
                continue
            heading_match = re.match(r"^### \[\[Projects/[^|]+\|([^\]]+)\]\]", block)
            if not heading_match:
                continue
            name = heading_match.group(1)
            updates = [
                line[2:].strip()
                for line in block.splitlines()[1:]
                if line.startswith("- ") and line[2:].strip() != "No material update."
            ]
            project_updates.append(ProjectUpdateEntry(project_name=name, updates=updates))

    def _bullets(heading: str) -> list[str]:
        text = _parse_section(body, heading)
        return [
            line[2:].strip()
            for line in text.splitlines()
            if line.startswith("- ") and line[2:].strip().lower() != "none identified"
        ]

    meetings = []
    for line in _parse_section(body, "Meetings").splitlines():
        m = re.match(r"^- \[\[([^\]]+)\]\]$", line)
        if m:
            meetings.append(m.group(1))

    return DailyState(
        daily_summary=daily_summary,
        project_updates=project_updates,
        decisions=_bullets("Decisions"),
        action_items=_bullets("Action Items"),
        risks=_bullets("Risks and Blockers"),
        contradictions_and_review=_bullets("Contradictions and Review Items"),
        meetings=meetings,
        human_notes=human_notes,
    )


def _merge_unique(existing: list[str], new: list[str]) -> list[str]:
    merged = list(existing)
    for item in new:
        if item not in merged:
            merged.append(item)
    return merged


async def run_daily_synthesis(
    cheap_client: AbstractClient,
    *,
    existing_content: str | None,
    day: str,
    meeting_source_link: str,
    project_name: str | None,
    new_project_updates: list[str],
    new_decisions: list[str],
    new_action_items: list[str],
    new_risks: list[str],
    new_contradictions_and_review: list[str] | None = None,
) -> DailySynthesisResult:
    """Synthesize (never concatenate) the daily note for ``day``.

    Args:
        cheap_client: The cheap-tier :class:`AbstractClient` (spec G7 —
            bulk extraction, summary-first reads).
        existing_content: The existing daily note's Markdown, or ``None``
            when today's note doesn't exist yet.
        day: ``YYYY-MM-DD``.
        meeting_source_link: Wikilink target of the new meeting's source
            page.
        project_name: The new meeting's primary project, if resolved.
        new_project_updates: This meeting's material project updates.
        new_decisions: This meeting's decisions.
        new_action_items: This meeting's action items.
        new_risks: This meeting's risks/blockers.
        new_contradictions_and_review: Contradiction/review-item links
            raised by this meeting.

    Returns:
        The :class:`DailySynthesisResult`.
    """
    existing_state = _parse_daily_body(existing_content) if existing_content else None

    prompt = "\n".join(
        [
            f"Date: {day}",
            f"Existing daily summary: {existing_state.daily_summary if existing_state else '(none yet)'}",
            f"Existing decisions: {[d for d in (existing_state.decisions if existing_state else [])]}",
            "",
            f"New meeting: [[{meeting_source_link}]] (project: {project_name or 'Unknown'})",
            f"New project updates: {new_project_updates}",
            f"New decisions: {new_decisions}",
            f"New action items: {new_action_items}",
            f"New risks: {new_risks}",
        ]
    )
    result = await cheap_client.invoke(
        prompt, output_type=DailySynthesisProposal, system_prompt=_SYSTEM_PROMPT, temperature=0.0
    )
    proposal: DailySynthesisProposal = result.output

    merged_project_updates = list(existing_state.project_updates) if existing_state else []
    for entry in proposal.project_updates:
        existing_entry = next((e for e in merged_project_updates if e.project_name == entry.project_name), None)
        if existing_entry is None:
            merged_project_updates.append(entry)
        else:
            existing_entry.updates = _merge_unique(existing_entry.updates, entry.updates)

    state = DailyState(
        daily_summary=proposal.daily_summary,
        project_updates=merged_project_updates,
        decisions=_merge_unique(existing_state.decisions if existing_state else [], proposal.decisions),
        action_items=_merge_unique(existing_state.action_items if existing_state else [], proposal.action_items),
        risks=_merge_unique(existing_state.risks if existing_state else [], proposal.risks),
        contradictions_and_review=_merge_unique(
            existing_state.contradictions_and_review if existing_state else [],
            new_contradictions_and_review or [],
        ),
        meetings=_merge_unique(existing_state.meetings if existing_state else [], [meeting_source_link]),
        human_notes=existing_state.human_notes if existing_state else "",
    )

    now = now_iso()
    frontmatter = DailyNoteFrontmatter(
        id=f"daily:{day}",
        title=f"{day} Daily Notes",
        date=day,
        meetings=state.meetings,
        projects=[e.project_name for e in state.project_updates],
        created=now,
        updated=now,
    )
    content = render_daily_page(frontmatter, state)

    return DailySynthesisResult(
        frontmatter=frontmatter, content=content, vault_path=f"Diary/Daily Notes/{day}.md"
    )
