"""FEAT-498 TASK-2751 — `wikitoolkit symbols` CLI group."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def built_project_root(tmp_path: Path, runner: CliRunner) -> Path:
    """A built wiki project with a caller and a callee."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (root / "b.py").write_text(
        "from a import helper\n\n\ndef run():\n    return helper()\n", encoding="utf-8"
    )
    result = runner.invoke(wiki, ["build", "--path", str(root), "--no-git", "-q"])
    assert result.exit_code == 0, result.output
    return root


class TestSymbolsLookup:
    def test_symbols_lookup_json(self, runner: CliRunner, built_project_root: Path):
        result = runner.invoke(
            wiki, ["symbols", "lookup", "helper", "--path", str(built_project_root), "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["hits"][0]["qualname"] == "helper"

    def test_symbols_lookup_text(self, runner: CliRunner, built_project_root: Path):
        result = runner.invoke(
            wiki, ["symbols", "lookup", "helper", "--path", str(built_project_root)]
        )
        assert result.exit_code == 0, result.output
        assert "sym:a.py#helper" in result.output

    def test_symbols_lookup_language_filter(self, runner: CliRunner, built_project_root: Path):
        result = runner.invoke(
            wiki,
            [
                "symbols", "lookup", "helper",
                "--path", str(built_project_root), "--language", "python", "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert all(hit["rel_path"].endswith(".py") for hit in payload["hits"])

    def test_symbols_lookup_limit(self, runner: CliRunner, built_project_root: Path):
        result = runner.invoke(
            wiki,
            ["symbols", "lookup", "helper", "--path", str(built_project_root), "--limit", "1", "--json"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert len(payload["hits"]) <= 1


class TestSymbolsOutline:
    def test_symbols_outline_json(self, runner: CliRunner, built_project_root: Path):
        result = runner.invoke(
            wiki, ["symbols", "outline", "file:a.py", "--path", str(built_project_root), "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert any(s["qualname"] == "helper" for s in payload["symbols"])

    def test_symbols_outline_with_source(self, runner: CliRunner, built_project_root: Path):
        result = runner.invoke(
            wiki,
            [
                "symbols", "outline", "sym:a.py#helper",
                "--path", str(built_project_root), "--source", "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["source"] and "return 1" in payload["source"]


class TestSymbolsBlast:
    def test_symbols_blast_json(self, runner: CliRunner, built_project_root: Path):
        result = runner.invoke(
            wiki,
            ["symbols", "blast", "sym:a.py#helper", "--path", str(built_project_root), "--json"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert "b.py" in payload["files"]

    def test_symbols_blast_no_inferred(self, runner: CliRunner, tmp_path: Path):
        root = tmp_path / "repo"
        root.mkdir()
        (root / "d.py").write_text("def unique_fn():\n    return 1\n", encoding="utf-8")
        (root / "c.py").write_text("def go():\n    return unique_fn()\n", encoding="utf-8")
        build = CliRunner().invoke(wiki, ["build", "--path", str(root), "--no-git", "-q"])
        assert build.exit_code == 0, build.output

        result = runner.invoke(
            wiki,
            [
                "symbols", "blast", "sym:d.py#unique_fn",
                "--path", str(root), "--no-inferred", "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["impacted"] == []
