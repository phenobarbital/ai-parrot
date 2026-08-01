"""Tests for the `wikitoolkit communities` CLI subcommand (FEAT-401).

Exercises the on-demand Leiden/Louvain community detection and
inter-community relations query against a real (tiny, synthetic) wiki
project built via the `wiki build` command — no mocking of the
GraphIndex pipeline, so a regression in the wiki-page → UniversalNode
adaptation or the `compute_inter_community_graph()` wiring would be
caught here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki


def _strip_log_lines(output: str) -> str:
    """Drop ANSI-coloured log lines the app's logging handler writes to
    the same stdout stream `CliRunner` captures, leaving only the
    command's own `click.echo` output (this repo's loggers prefix every
    line with an ANSI colour escape — plain `click.echo` output never
    does)."""
    return "\n".join(
        line for line in output.splitlines() if not line.startswith("\x1b[")
    )


@pytest.fixture
def built_wiki(tmp_path: Path) -> Path:
    """A tiny synthetic repo, built into a wiki project at ``tmp_path``.

    Two Python modules (one importing the other, in a subpackage — a
    natural community boundary) plus a README, matching the default
    ``--graph-kinds=module,document,overview``.
    """
    (tmp_path / "a.py").write_text(
        '"""Module A."""\n\n\ndef foo():\n    return 1\n'
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "b.py").write_text(
        '"""Module B."""\nfrom a import foo\n\n\ndef bar():\n    return foo() + 1\n'
    )
    (tmp_path / "README.md").write_text(
        "# Sample\n\nThis is a sample repo for testing.\n"
    )
    runner = CliRunner()
    result = runner.invoke(
        wiki, ["build", "--path", str(tmp_path), "--no-graph", "--quiet"],
    )
    assert result.exit_code == 0, result.output
    return tmp_path


class TestCommunitiesCommand:
    def test_shows_detected_communities(self, built_wiki):
        runner = CliRunner()
        result = runner.invoke(wiki, ["communities", "--path", str(built_wiki)])
        assert result.exit_code == 0
        output = _strip_log_lines(result.output)
        assert "# Communities" in output
        assert "algorithm=" in output

    def test_json_output_is_valid_communities_result(self, built_wiki):
        runner = CliRunner()
        result = runner.invoke(
            wiki, ["communities", "--path", str(built_wiki), "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(_strip_log_lines(result.output))
        assert "communities" in data
        assert "algorithm" in data
        assert "modularity" in data

    def test_not_built_is_graceful(self, tmp_path):
        """Running against a repo that was never `wiki build`-ed must
        not crash — a friendly message, exit 0."""
        runner = CliRunner()
        result = runner.invoke(wiki, ["communities", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert result.exception is None
        assert "not built" in result.output.lower()

    def test_no_matching_graph_kinds_is_graceful(self, built_wiki):
        """No pages match --graph-kinds → friendly message, not a crash."""
        runner = CliRunner()
        result = runner.invoke(
            wiki,
            [
                "communities", "--path", str(built_wiki),
                "--graph-kinds", "nonexistent-category",
            ],
        )
        assert result.exit_code == 0
        assert result.exception is None
        assert "graph-kinds" in result.output.lower()


class TestCommunitiesInterFlag:
    def test_shows_inter_community_header(self, built_wiki):
        """--inter always prints the density/pairs header, whether or
        not any cross-community edges exist (token-budgeted summary,
        not silence)."""
        runner = CliRunner()
        result = runner.invoke(
            wiki, ["communities", "--path", str(built_wiki), "--inter"],
        )
        assert result.exit_code == 0
        output = _strip_log_lines(result.output)
        assert "Inter-Community Relations" in output
        assert "density" in output

    def test_shows_relation_rows_when_cross_community_edges_exist(self, built_wiki):
        """The a.py <-> pkg/b.py import edge crosses the two communities
        (root files vs. pkg/), so at least one relation row must render
        with a coupling ratio."""
        runner = CliRunner()
        result = runner.invoke(
            wiki, ["communities", "--path", str(built_wiki), "--inter"],
        )
        output = _strip_log_lines(result.output)
        assert "coupling:" in output

    def test_json_output_is_valid_inter_community_graph(self, built_wiki):
        runner = CliRunner()
        result = runner.invoke(
            wiki,
            ["communities", "--path", str(built_wiki), "--inter", "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(_strip_log_lines(result.output))
        assert "relations" in data
        assert "density" in data
        assert "connected_pairs" in data
        assert "total_possible_pairs" in data

    def test_no_cross_community_edges_is_graceful(self, tmp_path):
        """A single-file repo has exactly one community and zero
        inter-community pairs — must print a graceful message, not
        crash or emit an empty table."""
        (tmp_path / "solo.py").write_text("def only():\n    return 1\n")
        runner = CliRunner()
        build = runner.invoke(
            wiki, ["build", "--path", str(tmp_path), "--no-graph", "--quiet"],
        )
        assert build.exit_code == 0, build.output
        result = runner.invoke(
            wiki, ["communities", "--path", str(tmp_path), "--inter"],
        )
        assert result.exit_code == 0
        output = _strip_log_lines(result.output)
        assert "Inter-Community Relations" in output
        assert "no cross-community edges" in output.lower()
