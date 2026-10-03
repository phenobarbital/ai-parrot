"""Unit tests for the Health/Lint/Archive/Graph workflows (FEAT-481,
spec Module 14 / TASK-2673).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from parrot.flows.wiki_ingest.nodes.archive import run_archive
from parrot.flows.wiki_ingest.nodes.graph_report import run_graph_report
from parrot.flows.wiki_ingest.nodes.health import run_health
from parrot.flows.wiki_ingest.nodes.lint import run_lint
from parrot.tools.obsidian import ObsidianToolkit


def _toolkit(vault_path: Path) -> ObsidianToolkit:
    return ObsidianToolkit(
        vault_path=str(vault_path),
        allowed_operations={"read", "list", "search", "create", "update", "move", "delete"},
    )


class _FakeRegistry:
    def __init__(self, records: list) -> None:
        self._records = records

    async def all_records(self):
        return self._records


class _FakeRecord:
    def __init__(self, fireflies_id: str) -> None:
        self.fireflies_id = fireflies_id


@pytest.mark.asyncio
async def test_health_is_read_only_and_reports_items(tmp_path: Path) -> None:
    for d in ("Wiki", "Projects", "Diary", "Raw"):
        (tmp_path / d).mkdir()
    toolkit = _toolkit(tmp_path)
    registry = _FakeRegistry([_FakeRecord("id-1"), _FakeRecord("id-1"), _FakeRecord("id-2")])

    report = await run_health(toolkit, registry, vault_path=tmp_path)

    assert report.required_dirs_ok is True
    assert set(report.missing_control_files) == {
        "Wiki/index.md",
        "Wiki/overview.md",
        "Wiki/log.md",
        "Wiki/Review Queue.md",
        "Wiki/Registry/processed-sources.md",
    }
    assert report.duplicate_source_ids == ["id-1"]
    assert report.private_never_accessed is True
    # Read-only: nothing was written.
    assert not any(tmp_path.rglob("*.md"))


@pytest.mark.asyncio
async def test_health_missing_dirs_detected(tmp_path: Path) -> None:
    toolkit = _toolkit(tmp_path)
    registry = _FakeRegistry([])

    report = await run_health(toolkit, registry, vault_path=tmp_path)

    assert report.required_dirs_ok is False
    assert "Wiki" in report.missing_dirs


@pytest.mark.asyncio
async def test_lint_detects_broken_links(tmp_path: Path) -> None:
    (tmp_path / "Wiki").mkdir()
    (tmp_path / "Wiki" / "a.md").write_text("See [[Wiki/nonexistent]].\n", encoding="utf-8")
    toolkit = _toolkit(tmp_path)

    report = await run_lint(toolkit)

    assert any(f.category == "broken_wikilink" for f in report.findings)
    assert report.fixed == []


@pytest.mark.asyncio
async def test_lint_fix_deduplicates_index_entries(tmp_path: Path) -> None:
    (tmp_path / "Wiki").mkdir()
    (tmp_path / "Wiki" / "index.md").write_text(
        "# Wiki Index\n\n## Projects\n- [[Projects/Acme/Acme|Acme]]\n- [[Projects/Acme/Acme|Acme]]\n",
        encoding="utf-8",
    )
    toolkit = _toolkit(tmp_path)

    report = await run_lint(toolkit, fix=True)

    assert any(f.category == "duplicate_index_entry" for f in report.findings)
    assert report.fixed
    updated = (tmp_path / "Wiki" / "index.md").read_text()
    assert updated.count("[[Projects/Acme/Acme|Acme]]") == 1


@pytest.mark.asyncio
async def test_archive_configurable_window(tmp_path: Path) -> None:
    """Daily notes older than the configurable window move to
    Diary/Archive/YYYY/; recent notes stay put."""
    daily_dir = tmp_path / "Diary" / "Daily Notes"
    daily_dir.mkdir(parents=True)
    (daily_dir / "2026-08-20.md").write_text("# Recent\n", encoding="utf-8")
    (daily_dir / "2026-01-05.md").write_text("# Old\n", encoding="utf-8")
    toolkit = _toolkit(tmp_path)
    registry = _FakeRegistry([])

    report = await run_archive(toolkit, registry, active_window_days=14, today=date(2026, 8, 25))

    assert report.changed is True
    assert "Diary/Archive/2026/2026-01-05.md" in report.archived_daily_notes
    assert (tmp_path / "Diary" / "Archive" / "2026" / "2026-01-05.md").exists()
    assert (tmp_path / "Diary" / "Daily Notes" / "2026-08-20.md").exists()
    assert not (tmp_path / "Diary" / "Daily Notes" / "2026-01-05.md").exists()


@pytest.mark.asyncio
async def test_archive_never_moves_canonical_pages(tmp_path: Path) -> None:
    """Archive must never move canonical Wiki/Sources/Meetings/ pages or
    canonical project pages, regardless of age (§31)."""
    meetings_dir = tmp_path / "Wiki" / "Sources" / "Meetings"
    meetings_dir.mkdir(parents=True)
    old_meeting = meetings_dir / "2026-01-05 - Old Meeting - abc12345.md"
    old_meeting.write_text("# Old Meeting\n", encoding="utf-8")

    (tmp_path / "Projects" / "Acme").mkdir(parents=True)
    (tmp_path / "Projects" / "Acme" / "Acme.md").write_text("# Acme\n", encoding="utf-8")

    toolkit = _toolkit(tmp_path)
    registry = _FakeRegistry([])

    await run_archive(toolkit, registry, active_window_days=14, today=date(2026, 8, 25))

    assert old_meeting.exists()
    assert (tmp_path / "Projects" / "Acme" / "Acme.md").exists()


@pytest.mark.asyncio
async def test_graph_report_labeled_derived(tmp_path: Path) -> None:
    toolkit = _toolkit(tmp_path)

    result = await run_graph_report(toolkit, "overview")

    assert result.vault_path == "Wiki/Graph/overview.md"
    assert "Derived report" in result.content
    assert "not canonical" in result.content
