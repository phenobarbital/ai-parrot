"""Tests for the ``wikitoolkit`` / ``parrot wiki`` CLI.

Drives the click commands end-to-end with ``CliRunner`` against temp
repositories — real SQLite plane, no git dependency (``--no-git``),
no LLM.
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.project import (
    config_path,
    load_project_config,
)

PY_STORE = '"""A tiny key-value store module."""\n\n\nclass Store:\n    """In-memory key-value store."""\n\n    def get(self, key):\n        """Fetch a value."""\n        return key\n'
PY_UTIL = '"""Utility helpers."""\n\n\ndef helper(key):\n    """Return the key unchanged."""\n    return key\n'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small fake repository."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "store.py").write_text(PY_STORE, encoding="utf-8")
    (tmp_path / "pkg" / "util.py").write_text(PY_UTIL, encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "# Demo\n\nA demo project.", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _build(runner: CliRunner, repo: Path, *extra: str):
    result = runner.invoke(
        wiki, ["build", "--path", str(repo), "--no-git", *extra]
    )
    assert result.exit_code == 0, result.output
    return result


class TestBuild:
    def test_build_creates_plane_and_config(self, runner, repo):
        result = _build(runner, repo)
        assert "built" in result.output
        assert config_path(repo).exists()
        config = load_project_config(repo)
        assert config.wiki_name == repo.name
        assert config.db_path(repo).exists()

    def test_rebuild_is_incremental(self, runner, repo):
        _build(runner, repo)
        result = _build(runner, repo)
        assert "0 ingested" in result.output
        assert "3 unchanged" in result.output

    def test_changed_file_reingested(self, runner, repo):
        _build(runner, repo)
        (repo / "pkg" / "util.py").write_text(
            '"""Utility helpers v2."""\n', encoding="utf-8"
        )
        result = _build(runner, repo)
        assert "1 ingested" in result.output

    def test_deleted_file_pruned(self, runner, repo):
        _build(runner, repo)
        (repo / "pkg" / "util.py").unlink()
        result = _build(runner, repo)
        assert "removed" in result.output
        page = runner.invoke(
            wiki, ["page", "file:pkg/util.py", "--path", str(repo)]
        )
        assert page.exit_code != 0

    def test_custom_name_and_backend(self, runner, repo):
        _build(runner, repo, "--name", "kb", "--backend", "memory")
        config = load_project_config(repo)
        assert config.wiki_name == "kb"
        assert config.backend == "memory"
        result = runner.invoke(
            wiki, ["query", "store", "--path", str(repo)]
        )
        assert result.exit_code == 0, result.output


class TestQuery:
    def test_query_returns_packed_stubs(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki, ["query", "key value store", "--path", str(repo)]
        )
        assert result.exit_code == 0, result.output
        assert "file:pkg/store.py" in result.output
        assert "wikitoolkit page" in result.output  # follow-up hint

    def test_query_json(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki,
            ["query", "utility helpers", "--path", str(repo), "--json"],
        )
        assert result.exit_code == 0
        rows = json.loads(result.output)
        assert any(r["concept_id"] == "file:pkg/util.py" for r in rows)
        assert all(0.0 <= r["score"] <= 1.0 for r in rows)

    def test_query_without_build_fails_with_guidance(self, runner, repo):
        result = runner.invoke(
            wiki, ["query", "anything", "--path", str(repo)]
        )
        assert result.exit_code != 0
        assert "wikitoolkit build" in result.output

    def test_query_no_results_message(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki, ["query", "zzzqqqxyzzy", "--path", str(repo)]
        )
        assert result.exit_code == 0
        assert "No wiki results" in result.output


class TestPageAndRelated:
    def test_page_full_read(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki, ["page", "file:pkg/store.py", "--path", str(repo)]
        )
        assert result.exit_code == 0
        assert "In-memory key-value store" in result.output

    def test_page_max_tokens_truncates(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki,
            [
                "page", "file:pkg/store.py",
                "--path", str(repo), "--max-tokens", "5",
            ],
        )
        assert result.exit_code == 0
        assert "truncated" in result.output

    def test_related_shows_contains_edge(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki, ["related", "file:pkg/store.py", "--path", str(repo)]
        )
        assert result.exit_code == 0
        assert "dir:pkg" in result.output
        assert "contains" in result.output


class TestUpsert:
    def test_upsert_explicit_path(self, runner, repo):
        _build(runner, repo)
        (repo / "pkg" / "util.py").write_text(
            '"""Utility helpers v2."""\n', encoding="utf-8"
        )
        result = runner.invoke(
            wiki, ["upsert", "pkg/util.py", "--path", str(repo)]
        )
        assert result.exit_code == 0, result.output
        assert "Upserted 1" in result.output
        page = runner.invoke(
            wiki, ["page", "file:pkg/util.py", "--path", str(repo)]
        )
        assert "v2" in page.output

    def test_upsert_preserves_incoming_edges(self, runner, repo):
        _build(runner, repo)
        (repo / "pkg" / "util.py").write_text(
            '"""Utility helpers v3."""\n', encoding="utf-8"
        )
        runner.invoke(wiki, ["upsert", "pkg/util.py", "--path", str(repo)])
        result = runner.invoke(
            wiki,
            ["related", "file:pkg/util.py", "--path", str(repo), "--json"],
        )
        rows = json.loads(result.output)
        rels = {(r["concept_id"], r["rel"]) for r in rows}
        assert ("dir:pkg", "contains") in rels

    def test_upsert_deleted_file_removes_pages(self, runner, repo):
        _build(runner, repo)
        (repo / "pkg" / "util.py").unlink()
        result = runner.invoke(
            wiki, ["upsert", "pkg/util.py", "--path", str(repo)]
        )
        assert result.exit_code == 0
        assert "removed 1" in result.output

    def test_upsert_ignores_excluded_dirs(self, runner, repo):
        _build(runner, repo)
        state = repo / ".parrot" / "wiki.json"
        assert state.exists()
        result = runner.invoke(
            wiki, ["upsert", ".parrot/wiki.json", "--path", str(repo)]
        )
        assert result.exit_code == 0
        assert "No wiki-relevant files" in result.output

    def test_upsert_before_build_is_noop(self, runner, tmp_path):
        (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
        result = runner.invoke(
            wiki, ["upsert", "a.py", "--path", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "not built" in result.output


class TestStatusAndExport:
    def test_status_json(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki, ["status", "--path", str(repo), "--json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["stats"]["pages"] >= 3
        assert payload["stale_sources"] == 0

    def test_export_markdown_bundle(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki, ["export", "--path", str(repo), "-o", "docs/wiki"]
        )
        assert result.exit_code == 0, result.output
        out = repo / "docs" / "wiki"
        assert (out / "index.md").exists()
        assert any(out.rglob("*store.py*"))
