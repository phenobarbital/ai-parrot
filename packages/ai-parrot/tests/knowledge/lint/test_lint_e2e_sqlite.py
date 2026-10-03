"""End-to-end lint test over a real SQLite plane (FEAT-625)."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from click.testing import CliRunner

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.store import SQLiteWikiStore

FIXTURE_REPO = Path(__file__).resolve().parents[5] / "tests" / "knowledge" / "lint" / "fixtures" / "repo"


def _lint(path: Path, *extra: str) -> dict:
    """Run ``wikitoolkit lint --json`` and return the parsed report."""
    result = CliRunner().invoke(wiki, ["lint", "--path", str(path), "--json", "--no-ledger", "--no-notes", *extra])
    assert result.exit_code == 0, result.output
    return json.loads(result.output[result.output.index("{"):])


def test_lint_fix_end_to_end(tmp_path: Path) -> None:
    """build -> seed defect -> lint -> lint --fix -> lint: only non-fixable findings remain."""
    assert FIXTURE_REPO.is_dir(), f"fixture repo missing: {FIXTURE_REPO}"
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)

    built = CliRunner().invoke(wiki, ["build", "--path", str(repo), "--no-git", "--no-graph", "--quiet"])
    assert built.exit_code == 0, built.output

    # Seed a fixable defect: a `references` edge with no inverse `related` edge.
    store = SQLiteWikiStore(repo / ".parrot" / "wiki" / "wiki.db", wiki_name="repo")
    page_ids = sorted(asyncio.run(LintContext(store).page_ids()))
    assert len(page_ids) >= 2, page_ids
    asyncio.run(store.add_edges([(page_ids[0], page_ids[1], "references", "asserted")]))

    before = _lint(repo)
    assert any(f["rule_id"] == "asymmetric-related" for f in before["findings"])

    fixed = _lint(repo, "--fix")
    assert fixed["fixed"], "lint --fix applied nothing"

    after = _lint(repo)
    assert not any(f["rule_id"] == "asymmetric-related" for f in after["findings"])
    assert not any(f.get("fixable") for f in after["findings"])
