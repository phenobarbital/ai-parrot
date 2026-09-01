"""§31 Archive workflow (FEAT-481, spec Module 14, D7).

Maintains the rolling, **configurable** active window (default
:data:`~parrot.flows.wiki_ingest.conf.WIKI_KB_ACTIVE_WINDOW_DAYS` = 14):
moves old daily notes to ``Diary/Archive/YYYY/`` and old project meeting
index references to ``Meeting Summaries/Archive/index.md`` — **never**
moves/archives canonical ``Wiki/Sources/Meetings/`` pages, canonical
project pages, or raw bundles (§31 explicit prohibitions). Callable both
standalone (the agent façade's ``archive`` intent) and as ingest step 22
(spec Module 6, TASK-2672 — ``runner._maybe_run_archive`` picks this
module up automatically once it exists).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from .. import conf
from .. import vault as vault_module
from .indexes import (
    render_project_meeting_index_active,
    render_project_meeting_index_archive,
    split_active_and_archived,
)


class ArchiveReport(BaseModel):
    """Result of one §31 archive run.

    Attributes:
        archived_daily_notes: ``Diary/Daily Notes/`` paths moved to
            ``Diary/Archive/YYYY/``.
        archived_project_meeting_refs: ``(project, count)`` pairs — how
            many meeting-index entries were moved to each project's
            archive index.
        changed: ``True`` if anything moved this run — §31: "Append an
            ``archive`` entry to ``Wiki/log.md`` only when something
            changed."
    """

    archived_daily_notes: list[str] = Field(default_factory=list)
    archived_project_meeting_refs: list[tuple[str, int]] = Field(default_factory=list)
    changed: bool = False


async def _archive_daily_notes(toolkit: Any, *, active_window_days: int, today: date) -> list[str]:
    """§31 — move daily notes older than the active window, unchanged.

    Args:
        toolkit: This subsystem's own ``ObsidianToolkit``.
        active_window_days: The configurable active window.
        today: Reference date for the cutoff.

    Returns:
        Vault-relative paths moved.
    """
    archived: list[str] = []
    try:
        listing = await toolkit.list_notes(folder="Diary/Daily Notes", recursive=False)
    except FileNotFoundError:
        return archived

    for note in listing.get("notes", []):
        path = note["path"]
        stem = path.rsplit("/", 1)[-1].removesuffix(".md")
        try:
            note_date = date.fromisoformat(stem)
        except ValueError:
            continue
        cutoff = today - timedelta(days=active_window_days - 1)
        if note_date >= cutoff:
            continue

        destination = f"Diary/Archive/{note_date.year}/{stem}.md"
        result = await toolkit.move_note(path, destination)
        await vault_module.fixup_links(
            toolkit, old_path=path, new_path=destination, affected_backlinks=result.get("affected_backlinks", [])
        )
        archived.append(destination)

    return archived


async def _archive_project_meeting_refs(
    toolkit: Any, project_name: str, *, active_window_days: int, today: date
) -> int:
    """§31 — re-split one project's meeting index by the active window.

    Never moves/archives the canonical ``Wiki/Sources/Meetings/`` pages
    themselves — only the project's own index *references* to them.

    Args:
        toolkit: This subsystem's own ``ObsidianToolkit``.
        project_name: The project's Title-Case name.
        active_window_days: The configurable active window.
        today: Reference date for the cutoff.

    Returns:
        The number of entries moved to the archive index this run.
    """
    active_path = f"Projects/{project_name}/Meeting Summaries/index.md"
    archive_path = f"Projects/{project_name}/Meeting Summaries/Archive/index.md"

    try:
        active_note = await toolkit.read_note(active_path)
    except FileNotFoundError:
        return 0

    original_active_entries = _parse_meeting_index(active_note["content"])
    entries = list(original_active_entries)
    try:
        archive_note = await toolkit.read_note(archive_path)
        entries += _parse_meeting_index(archive_note["content"])
    except FileNotFoundError:
        pass

    active_entries, archived_entries = split_active_and_archived(
        entries, active_window_days=active_window_days, today=today
    )
    # Entries that WERE active before this run but are no longer — i.e.
    # newly moved out of the active window this call.
    moved_count = len([e for e in original_active_entries if e not in active_entries])

    new_active_content = render_project_meeting_index_active(project_name, active_entries)
    new_archive_content = render_project_meeting_index_archive(project_name, archived_entries)

    await toolkit.update_note(active_path, new_active_content, preserve_frontmatter=False)
    try:
        await toolkit.update_note(archive_path, new_archive_content, preserve_frontmatter=False)
    except FileNotFoundError:
        await toolkit.create_note(archive_path, new_archive_content)

    return moved_count


def _parse_meeting_index(content: str) -> list[tuple[str, str, str]]:
    """Parse §18 meeting-index bullet lines: ``- DATE - [[link|title]] - sig``."""
    entries = []
    for line in content.splitlines():
        match = re.match(r"^- (\d{4}-\d{2}-\d{2}) - \[\[([^|\]]+)\|[^\]]+\]\] - (.*)$", line)
        if match:
            entries.append((match.group(1), match.group(2), match.group(3)))
    return entries


async def run_archive(
    toolkit: Any,
    registry: Any,
    *,
    active_window_days: int | None = None,
    today: date | None = None,
) -> ArchiveReport:
    """Run the §31 archive workflow.

    Args:
        toolkit: This subsystem's own ``ObsidianToolkit`` (spec Module 4).
        registry: This subsystem's ``MeetingRegistry`` — unused directly
            here (kept for signature symmetry with the other Module 14
            workflows and the orchestrator's lazy call), reserved for a
            future overdue-item cross-check.
        active_window_days: Overrides
            :data:`conf.WIKI_KB_ACTIVE_WINDOW_DAYS` (D7).
        today: Reference date (defaults to today, UTC).

    Returns:
        The :class:`ArchiveReport`.
    """
    window = active_window_days if active_window_days is not None else conf.WIKI_KB_ACTIVE_WINDOW_DAYS
    reference = today or datetime.now(UTC).date()

    archived_daily = await _archive_daily_notes(toolkit, active_window_days=window, today=reference)

    archived_refs: list[tuple[str, int]] = []
    try:
        projects_listing = await toolkit.list_notes(folder="Projects", recursive=False)
    except FileNotFoundError:
        projects_listing = {"notes": []}

    for note in projects_listing.get("notes", []):
        project_name = note["path"].rsplit("/", 1)[-1].removesuffix(".md")
        moved = await _archive_project_meeting_refs(
            toolkit, project_name, active_window_days=window, today=reference
        )
        if moved:
            archived_refs.append((project_name, moved))

    return ArchiveReport(
        archived_daily_notes=archived_daily,
        archived_project_meeting_refs=archived_refs,
        changed=bool(archived_daily or archived_refs),
    )
