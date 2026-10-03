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
    return json.loads(result.output[result.output.index("{") :])


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


def _snapshot(store: SQLiteWikiStore) -> tuple:
    """Pages (ids + bodies) and edges of the plane."""
    pages = asyncio.run(store.dump_pages())
    return asyncio.run(store.dump_edges()), sorted((str(p["concept_id"]), str(p.get("body"))) for p in pages)


def test_default_lint_leaves_store_unchanged(tmp_path: Path) -> None:
    """AC1: a default run (real defaults: notes off) leaves edges and page bodies identical."""
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)
    built = CliRunner().invoke(wiki, ["build", "--path", str(repo), "--no-git", "--no-graph", "--quiet"])
    assert built.exit_code == 0, built.output

    store = SQLiteWikiStore(repo / ".parrot" / "wiki" / "wiki.db", wiki_name="repo")
    before = _snapshot(store)
    result = CliRunner().invoke(wiki, ["lint", "--path", str(repo), "--json", "--no-ledger"])
    assert result.exit_code in (0, 1), result.output
    assert _snapshot(store) == before


def test_wiki_lint_tool_default_leaves_store_unchanged(tmp_path: Path) -> None:
    """AC1 via the MCP tool: default arguments do not touch pages or edges."""
    from parrot.knowledge.wiki.tools import WikiLintTool

    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)
    built = CliRunner().invoke(wiki, ["build", "--path", str(repo), "--no-git", "--no-graph", "--quiet"])
    assert built.exit_code == 0, built.output

    store = SQLiteWikiStore(repo / ".parrot" / "wiki" / "wiki.db", wiki_name="repo")
    before = _snapshot(store)
    tool = WikiLintTool(store, storage_dir=repo / ".parrot" / "wiki")
    asyncio.run(tool._execute())
    assert _snapshot(store) == before


def test_wiki_lint_tool_fix_writes_audit_log(tmp_path: Path) -> None:
    """AC3: wiki_lint(fix=true) logs LINT to log.md like the CLI does."""
    from parrot.knowledge.wiki.tools import WikiLintTool

    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)
    built = CliRunner().invoke(wiki, ["build", "--path", str(repo), "--no-git", "--no-graph", "--quiet"])
    assert built.exit_code == 0, built.output
    wiki_dir = repo / ".parrot" / "wiki"
    store = SQLiteWikiStore(wiki_dir / "wiki.db", wiki_name="repo")
    asyncio.run(WikiLintTool(store, storage_dir=wiki_dir)._execute(fix=True))
    assert "LINT" in (wiki_dir / "log.md").read_text(encoding="utf-8")
