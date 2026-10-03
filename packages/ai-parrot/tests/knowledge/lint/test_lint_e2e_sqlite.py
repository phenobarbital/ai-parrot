"""End-to-end lint test for SQLite backend (FEAT-625)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from parrot.knowledge.lint import LintOptions, LintRunner
from parrot.knowledge.wiki.store import SQLiteWikiStore


@pytest.mark.asyncio
async def test_lint_end_to_end_sqlite(tmp_path: Path) -> None:
    """Build a fixture plane, seed defects, run lint, then lint --fix, then lint again.

    Only the non-fixable findings remain.
    """
    # Create a temporary SQLite store
    store_path = tmp_path / "wiki.db"
    store = SQLiteWikiStore(store_path)

    # Build the fixture plane
    fixture_repo = Path(__file__).parent.parent.parent.parent / "tests" / "knowledge" / "lint" / "fixtures" / "repo"
    assert fixture_repo.exists(), f"Fixture repo not found at {fixture_repo}"

    # Build the wiki
    from parrot.knowledge.wiki.vault_scan import scan_repository
    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper

    root = fixture_repo
    config = type("Config", (), {"storage_path": lambda self, r: tmp_path, "backend": "sqlite"})()
    bookkeeper = WikiBookkeeper(store, root=root, config=config)

    scan = scan_repository(
        root,
        suffixes=[".md"],
        exclude_dirs=[],
        body_max_chars=10000,
        max_file_bytes=1000,
        use_git=False,
    )

    await store.upsert_pages(scan.pages)
    await store.add_edges(scan.edges)
    await bookkeeper.log_operation("build", "lint_e2e", {"pages": len(scan.pages), "edges": len(scan.edges)})

    # Seed defects: asymmetric references edge, broken edge, duplicate slug
    # 1. Asymmetric related: page1 -> page2 (related) but page2 -> page1 (missing)
    await store.add_edges([("page1", "page2", "related", "asserted")])

    # 2. Broken link: page3 -> nonexistent (broken)
    # Already in the scan, so no need to add

    # 3. Duplicate slug: page4 -> page1 (duplicate)
    # Already in the scan, so no need to add

    # First lint run: should find 3 findings
    options = LintOptions(fix=False, ledger=False, notes=False)
    runner = LintRunner(store, root=root, config=config)
    report1 = await runner.run(options)

    assert len(report1.findings) == 3, f"Expected 3 findings, got {len(report1.findings)}: {report1.findings}"
    finding_ids = {f.rule_id for f in report1.findings}
    assert "asymmetric-related" in finding_ids, "Missing asymmetric-related finding"
    assert "broken-link" in finding_ids, "Missing broken-link finding"
    assert "duplicate-slug" in finding_ids, "Missing duplicate-slug finding"

    # Second lint run with --fix: asymmetric-related should be fixed
    options_fix = LintOptions(fix=True, ledger=False, notes=False)
    report2 = await runner.run(options_fix)

    # After fix, asymmetric-related should be gone, but broken-link and duplicate-slug remain
    assert len(report2.findings) == 2, f"Expected 2 findings after fix, got {len(report2.findings)}: {report2.findings}"
    finding_ids = {f.rule_id for f in report2.findings}
    assert "asymmetric-related" not in finding_ids, "asymmetric-related should be fixed"
    assert "broken-link" in finding_ids, "Missing broken-link finding"
    assert "duplicate-slug" in finding_ids, "Missing duplicate-slug finding"

    # Third lint run: should still have only broken-link and duplicate-slug
    report3 = await runner.run(options)

    assert len(report3.findings) == 2, f"Expected 2 findings after re-check, got {len(report3.findings)}: {report3.findings}"
    finding_ids = {f.rule_id for f in report3.findings}
    assert "asymmetric-related" not in finding_ids, "asymmetric-related should stay fixed"
    assert "broken-link" in finding_ids, "Missing broken-link finding"
    assert "duplicate-slug" in finding_ids, "Missing duplicate-slug finding"

    # Verify the fix was applied: page2 -> page1 (related) should exist
    edges = await store.dump_edges()
    related_edges = [e for e in edges if e[0] == "page2" and e[2] == "related"]
    assert len(related_edges) == 1, f"Expected 1 related edge from page2, got {len(related_edges)}: {related_edges}"
    assert related_edges[0][1] == "page1", f"Expected page2 -> page1, got {related_edges[0]}"
    assert related_edges[0][3] == "asserted", f"Expected provenance asserted, got {related_edges[0][3]}"
