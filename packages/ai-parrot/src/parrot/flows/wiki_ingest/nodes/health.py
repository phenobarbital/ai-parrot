"""§29 Health workflow (FEAT-481, spec Module 14).

A fast, **read-only** operational check — never a full lint (§30 owns
that). Never touches ``Private/`` (this module contains no code path
that reads it — confirming that boundary is a structural property, not
a runtime check).
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .. import conf

#: §4/§11 — control files §29 step 2 requires readable.
_REQUIRED_CONTROL_FILES = (
    "Wiki/index.md",
    "Wiki/overview.md",
    "Wiki/log.md",
    "Wiki/Review Queue.md",
    "Wiki/Registry/processed-sources.md",
)

#: §4 — top-level directories §29 step 1 requires present.
_REQUIRED_DIRS = ("Wiki", "Projects", "Diary", "Raw")


class HealthReport(BaseModel):
    """The §29 health check's result.

    Attributes:
        required_dirs_ok: ``True`` when every §4 top-level directory exists.
        missing_dirs: Any missing top-level directories.
        control_files_ok: ``True`` when every control file is readable.
        missing_control_files: Any unreadable/missing control files.
        pending_complete_bundles: ``Raw/Incoming/`` bundles with a
            transcript file (ready to process).
        pending_incomplete_bundles: ``Raw/Incoming/`` groups missing a
            transcript (a §13 review item waiting).
        duplicate_source_ids: Source ids appearing more than once in the
            registry (§29 step 4).
        open_review_items: Count of ``Status: Open`` entries in
            ``Wiki/Review Queue.md``.
        open_contradictions: Count of ``status: open`` contradiction pages.
        recent_log_incomplete_ops: Recent ``Wiki/log.md`` entries missing
            a ``Validation:`` line (§29 step 7 — an incomplete operation).
        private_never_accessed: Always ``True`` — this module has no
            ``Private/`` code path (§29 step 9).
    """

    required_dirs_ok: bool = True
    missing_dirs: list[str] = Field(default_factory=list)
    control_files_ok: bool = True
    missing_control_files: list[str] = Field(default_factory=list)
    pending_complete_bundles: int = 0
    pending_incomplete_bundles: int = 0
    duplicate_source_ids: list[str] = Field(default_factory=list)
    open_review_items: int = 0
    open_contradictions: int = 0
    recent_log_incomplete_ops: list[str] = Field(default_factory=list)
    private_never_accessed: bool = True


async def run_health(toolkit: Any, registry: Any, *, vault_path: str | Path) -> HealthReport:
    """Run the §29 fast health check. Read-only.

    Args:
        toolkit: This subsystem's own ``ObsidianToolkit`` (spec Module 4).
        registry: This subsystem's ``MeetingRegistry`` (FEAT-472).
        vault_path: The Obsidian vault root (for the ``Raw/Incoming/``
            filesystem scan — raw bundles are outside the Obsidian page
            model, spec Module 3).

    Returns:
        The :class:`HealthReport`.
    """
    report = HealthReport()

    vault_path = Path(vault_path)
    for dirname in _REQUIRED_DIRS:
        if not (vault_path / dirname).is_dir():
            report.missing_dirs.append(dirname)
    report.required_dirs_ok = not report.missing_dirs

    for path in _REQUIRED_CONTROL_FILES:
        try:
            await toolkit.read_note(path, include_content=False)
        except FileNotFoundError:
            report.missing_control_files.append(path)
    report.control_files_ok = not report.missing_control_files

    incoming_dir = vault_path / conf.WIKI_KB_RAW_ROOT / "Incoming"
    if incoming_dir.is_dir():
        from .raw_bundle import pair_incoming_bundles

        paired, unpaired = pair_incoming_bundles(incoming_dir)
        report.pending_complete_bundles = len(paired)
        report.pending_incomplete_bundles = len(unpaired)

    records = await registry.all_records()
    ids = [r.fireflies_id for r in records]
    report.duplicate_source_ids = [sid for sid, count in Counter(ids).items() if count > 1]

    try:
        queue_note = await toolkit.read_note("Wiki/Review Queue.md")
        report.open_review_items = queue_note["content"].count("- Status: Open")
    except FileNotFoundError:
        pass

    try:
        contradictions = await toolkit.list_notes(folder="Wiki/Contradictions", recursive=False)
        open_count = 0
        for note in contradictions.get("notes", []):
            try:
                page = await toolkit.read_note(note["path"])
                if page["frontmatter"].get("status") == "open":
                    open_count += 1
            except FileNotFoundError:
                continue
        report.open_contradictions = open_count
    except FileNotFoundError:
        pass

    try:
        log_note = await toolkit.read_note("Wiki/log.md")
        entries = re.split(r"(?=^## \[)", log_note["content"], flags=re.MULTILINE)
        for entry in entries[-10:]:
            if entry.strip().startswith("## [") and "Validation:" not in entry:
                title_match = re.match(r"^## \[[^\]]+\] \S+ \| (.+)$", entry.strip().splitlines()[0])
                report.recent_log_incomplete_ops.append(title_match.group(1) if title_match else entry[:40])
    except FileNotFoundError:
        pass

    return report
