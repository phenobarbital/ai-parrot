"""Tests for ADR and memory lint packs (TASK-4016)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.packs.adr import (
    ADR_RULES,
    AdrConflictRule,
    AdrSupersededActiveRule,
    AdrSupersedesBrokenRule,
)
from parrot.knowledge.lint.packs.memory import MEMORY_RULES, MemoryDanglingLinkRule, StaleMemoryRule
from parrot.knowledge.wiki.decisions.models import DecisionLink, DecisionRecord
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.knowledge.wiki.store import WikiPageRecord


async def _context(tmp_path: Path) -> LintContext:
    """Build an empty in-memory lint context."""
    return LintContext(InMemoryWikiStore(tmp_path / "bundle"))


async def _save(context: LintContext, record: DecisionRecord) -> None:
    """Store one ADR record through its canonical repository."""
    await DecisionRepository(context.store).save(record, None)


@pytest.mark.asyncio
async def test_adr_superseded_active(tmp_path: Path) -> None:
    """An accepted ADR targeted by supersedes is reported as active incorrectly."""
    context = await _context(tmp_path)
    await _save(
        context,
        DecisionRecord(decision_id="adr:old", decision="old", origin="documented", source_status="accepted"),
    )
    await _save(
        context,
        DecisionRecord(
            decision_id="adr:new",
            decision="new",
            origin="documented",
            source_status="accepted",
            links=[DecisionLink(target_id="adr:old", relation="supersedes", provenance="asserted")],
        ),
    )

    findings = await AdrSupersededActiveRule().check(context)

    assert [(finding.severity, finding.subjects) for finding in findings] == [("warning", ["adr:old"])]


@pytest.mark.asyncio
async def test_adr_supersedes_broken(tmp_path: Path) -> None:
    """A supersedes link to a missing target is an error."""
    context = await _context(tmp_path)
    await _save(
        context,
        DecisionRecord(
            decision_id="adr:current",
            decision="current",
            origin="documented",
            links=[DecisionLink(target_id="adr:missing", relation="supersedes", provenance="asserted")],
        ),
    )

    findings = await AdrSupersedesBrokenRule().check(context)

    assert [(finding.severity, finding.subjects) for finding in findings] == [("error", ["adr:current", "adr:missing"])]


@pytest.mark.asyncio
async def test_adr_conflict(tmp_path: Path) -> None:
    """Accepted ADRs explaining one target conflict without supersession."""
    context = await _context(tmp_path)
    for decision_id in ("adr:first", "adr:second"):
        await _save(
            context,
            DecisionRecord(
                decision_id=decision_id,
                decision=decision_id,
                origin="documented",
                source_status="accepted",
                links=[DecisionLink(target_id="sym:module#thing", relation="explains", provenance="asserted")],
            ),
        )

    findings = await AdrConflictRule().check(context)

    assert [(finding.severity, finding.subjects) for finding in findings] == [
        ("warning", ["adr:first", "adr:second", "sym:module#thing"])
    ]


@pytest.mark.asyncio
async def test_stale_memory_warning(tmp_path: Path) -> None:
    """A target newer than its memory creates a warning finding."""
    context = await _context(tmp_path)
    await context.store.upsert_pages(
        [
            WikiPageRecord(
                concept_id="memory:one",
                body="memory",
                origin="memory",
                updated_at="2026-01-01T00:00:00Z",
            ),
            WikiPageRecord(
                concept_id="page:current",
                body="current",
                updated_at="2026-01-02T00:00:00Z",
            ),
        ]
    )
    await context.store.add_edges([("memory:one", "page:current", "references")])

    findings = await StaleMemoryRule().check(context)

    assert [(finding.severity, finding.subjects) for finding in findings] == [
        ("warning", ["memory:one", "page:current"])
    ]


@pytest.mark.asyncio
async def test_memory_dangling_link(tmp_path: Path) -> None:
    """An outgoing memory link to a missing page is an error."""
    context = await _context(tmp_path)
    await context.store.upsert_pages([WikiPageRecord(concept_id="memory:one", body="memory", origin="memory")])
    await context.store.add_edges([("memory:one", "page:missing", "references")])

    findings = await MemoryDanglingLinkRule().check(context)

    assert [(finding.severity, finding.subjects) for finding in findings] == [("error", ["memory:one", "page:missing"])]


def test_rule_pack_exports_are_complete() -> None:
    """Both packs export their fixed complete rule lists."""
    assert ADR_RULES == [AdrSupersededActiveRule, AdrSupersedesBrokenRule, AdrConflictRule]
    assert MEMORY_RULES == [MemoryDanglingLinkRule, StaleMemoryRule]
