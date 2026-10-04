"""Tests for report-only plane lint rules (FEAT-625)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.packs.plane import (
    PLANE_RULES,
    BrokenLinkRule,
    DuplicateSlugRule,
    MissingBodyRule,
    OrphanPageRule,
    OrphanSourceRule,
    StaleSourceRule,
)
from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.knowledge.wiki.store import WikiPageRecord


async def _context(tmp_path: Path, pages: list[WikiPageRecord]) -> LintContext:
    """Build an in-memory lint context containing the supplied pages."""
    store = InMemoryWikiStore(tmp_path / "bundle")
    await store.upsert_pages(pages)
    return LintContext(store)


@pytest.mark.asyncio
async def test_broken_link_is_error(tmp_path: Path) -> None:
    """Broken edges from the store become error-severity findings."""
    context = await _context(tmp_path, [WikiPageRecord(concept_id="source", body="body")])
    await context.store.add_edges([("source", "missing", "references")])

    findings = await BrokenLinkRule().check(context)

    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert findings[0].subjects == ["source", "missing"]
    assert findings[0].data["rel"] == "references"


@pytest.mark.asyncio
async def test_duplicate_slug(tmp_path: Path) -> None:
    """Titles with an identical OKF slug produce one finding for both pages."""
    context = await _context(
        tmp_path,
        [
            WikiPageRecord(concept_id="one", title="Foo Bar", body="one"),
            WikiPageRecord(concept_id="two", title="foo  bar!", body="two"),
        ],
    )

    findings = await DuplicateSlugRule().check(context)

    assert len(findings) == 1
    assert findings[0].subjects == ["one", "two"]
    assert findings[0].data["slug"] == "foo-bar"


@pytest.mark.asyncio
async def test_orphan_page_skips_designated_roots(tmp_path: Path) -> None:
    """Only ordinary pages without inbound edges are reported as orphans."""
    context = await _context(
        tmp_path,
        [
            WikiPageRecord(concept_id="orphan", body="orphan"),
            WikiPageRecord(concept_id="target", body="target"),
            WikiPageRecord(concept_id="adr:root", body="root"),
        ],
    )
    await context.store.add_edges([("orphan", "target", "references")])

    findings = await OrphanPageRule().check(context)

    assert [finding.subjects for finding in findings] == [["orphan"]]


@pytest.mark.asyncio
async def test_orphan_source_uses_store_fast_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Orphan source findings mirror the store's optimized result."""
    context = await _context(tmp_path, [])

    async def orphan_sources() -> list[str]:
        """Return one source from a controlled store fast-path fixture."""
        return ["source-1"]

    monkeypatch.setattr(context.store, "orphan_sources", orphan_sources)

    findings = await OrphanSourceRule().check(context)

    assert [finding.subjects for finding in findings] == [["source-1"]]


@pytest.mark.asyncio
async def test_missing_body_uses_in_memory_store(tmp_path: Path) -> None:
    """An in-memory page with no body is reported."""
    context = await _context(
        tmp_path,
        [WikiPageRecord(concept_id="empty", body=""), WikiPageRecord(concept_id="present", body="content")],
    )

    findings = await MissingBodyRule().check(context)

    assert [finding.subjects for finding in findings] == [["empty"]]


@pytest.mark.asyncio
async def test_stale_source_skips_without_manager_and_reports_stale(tmp_path: Path) -> None:
    """Stale checks are optional and only report sources the manager marks stale."""
    context = await _context(tmp_path, [])
    assert await StaleSourceRule().check(context) == []

    class Sources:
        """Minimal synchronous source-manager stand-in."""

        def list_sources(self) -> list[SimpleNamespace]:
            """Return fresh and stale source entries."""
            return [SimpleNamespace(source_id="fresh"), SimpleNamespace(source_id="stale")]

        def is_stale(self, source_id: str) -> bool:
            """Mark only the designated fixture source stale."""
            return source_id == "stale"

    context.extras["sources"] = Sources()

    findings = await StaleSourceRule().check(context)

    assert [finding.subjects for finding in findings] == [["stale"]]


def test_plane_rules_export_all_report_only_rules() -> None:
    """The plane pack exports its complete ordered rule list."""
    assert PLANE_RULES == [
        BrokenLinkRule,
        OrphanPageRule,
        OrphanSourceRule,
        DuplicateSlugRule,
        MissingBodyRule,
        StaleSourceRule,
    ]
