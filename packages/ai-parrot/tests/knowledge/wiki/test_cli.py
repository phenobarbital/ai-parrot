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
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki import cli as wiki_cli
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

    def test_edgeless_selection_does_not_crash(self, tmp_path):
        """Narrowing --graph-kinds down to pages with no edges between
        them (here: two independent docs, no cross-references, and the
        default 'overview' dir-containment node excluded) must not
        raise ZeroDivisionError — nx.community.modularity() divides by
        deg_sum**2 internally and blows up on a truly edgeless graph."""
        (tmp_path / "a.md").write_text("# A\n\nDoc A content.\n")
        (tmp_path / "b.md").write_text("# B\n\nDoc B content.\n")
        runner = CliRunner()
        build = runner.invoke(
            wiki, ["build", "--path", str(tmp_path), "--no-graph", "--quiet"],
        )
        assert build.exit_code == 0, build.output
        result = runner.invoke(
            wiki,
            [
                "communities", "--path", str(tmp_path),
                "--graph-kinds", "document",
            ],
        )
        assert result.exit_code == 0
        assert result.exception is None
        output = _strip_log_lines(result.output)
        assert "modularity=0.0000" in output

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


@pytest.fixture(autouse=True)
def _clean_llm_fallback_env(monkeypatch):
    """Isolate the FEAT-531 auto-detection env vars from the dev machine."""
    for var in ("WIKI_EXTRACT_LLM", "WIKI_MODEL", "WIKI_LIGHTWEIGHT_MODEL", "PARROT_NO_AUTO_LLM"):
        monkeypatch.delenv(var, raising=False)


class TestExtractIntoGraphDetectionFallback:
    """FEAT-531 TASK-2894 Part A — ``_extract_into_graph``'s WIKI_EXTRACT_LLM fallback."""

    def test_uses_detection_when_unset(self, capsys):
        with patch(
            "parrot.clients.detection.detect_coding_agent_llm",
            return_value="claude-code:claude-haiku-4-5-20251001",
        ), patch(
            "parrot.clients.factory.LLMFactory.create",
            side_effect=RuntimeError("stop-after-detection"),
        ):
            result = wiki_cli._extract_into_graph(
                root=Path("/tmp/does-not-exist"),
                config=object(),
                text="hello world",
                source_uri="doc://test",
                asserted_by="agent:test",
                run_id=None,
            )
        output = capsys.readouterr().out
        assert "auto-selected claude-code:claude-haiku-4-5-20251001" in output
        assert "WIKI_EXTRACT_LLM" in output
        # Detection auto-selected a spec, so the function proceeds into the
        # try block (and degrades on the LLMFactory.create failure) rather
        # than printing the "[extract skipped...]" message.
        assert "[extract skipped" not in output
        assert result is None

    def test_respects_opt_out(self, monkeypatch, capsys):
        monkeypatch.setenv("PARROT_NO_AUTO_LLM", "1")
        with patch("parrot.clients.detection.detect_coding_agent_llm") as mock_detect:
            result = wiki_cli._extract_into_graph(
                root=Path("/tmp/does-not-exist"),
                config=object(),
                text="hello world",
                source_uri="doc://test",
                asserted_by="agent:test",
                run_id=None,
            )
        mock_detect.assert_not_called()
        assert result is None
        assert "[extract skipped" in capsys.readouterr().out

    def test_explicit_config_wins(self, monkeypatch):
        monkeypatch.setenv("WIKI_EXTRACT_LLM", "anthropic:claude-sonnet-5")
        with patch("parrot.clients.detection.detect_coding_agent_llm") as mock_detect, patch(
            "parrot.clients.factory.LLMFactory.create",
            side_effect=RuntimeError("stop-after-config-read"),
        ):
            wiki_cli._extract_into_graph(
                root=Path("/tmp/does-not-exist"),
                config=object(),
                text="hello world",
                source_uri="doc://test",
                asserted_by="agent:test",
                run_id=None,
            )
        mock_detect.assert_not_called()

    def test_degrades_when_detection_misses(self, capsys):
        with patch("parrot.clients.detection.detect_coding_agent_llm", return_value=None):
            result = wiki_cli._extract_into_graph(
                root=Path("/tmp/does-not-exist"),
                config=object(),
                text="hello world",
                source_uri="doc://test",
                asserted_by="agent:test",
                run_id=None,
            )
        assert result is None
        assert "[extract skipped" in capsys.readouterr().out


class TestIngestModelResolutionDetectionFallback:
    """FEAT-531 TASK-2894 Part B — the ``ingest`` command's light/heavy pair."""

    def _invoke_ingest(self, project: Path, capture: dict) -> None:
        def _fake_build_triage_adapters(lightweight_model, model):
            capture["lightweight_model"] = lightweight_model
            capture["model"] = model
            raise RuntimeError("stop-after-resolution")

        with patch.object(
            wiki_cli, "_build_triage_adapters", side_effect=_fake_build_triage_adapters,
        ):
            runner = CliRunner()
            runner.invoke(
                wiki,
                ["ingest", str(project), "--path", str(project), "--dry-run"],
            )

    def test_both_unset_uses_detection(self, built_wiki):
        capture: dict = {}
        with patch(
            "parrot.clients.detection.detect_coding_agent_llm",
            return_value="claude-code:claude-haiku-4-5-20251001",
        ):
            self._invoke_ingest(built_wiki, capture)
        assert capture.get("lightweight_model") == "claude-code:claude-haiku-4-5-20251001"
        assert capture.get("model") == "claude-code:claude-haiku-4-5-20251001"

    def test_opt_out_disables_detection(self, built_wiki, monkeypatch):
        monkeypatch.setenv("PARROT_NO_AUTO_LLM", "1")
        capture: dict = {}
        with patch("parrot.clients.detection.detect_coding_agent_llm") as mock_detect:
            self._invoke_ingest(built_wiki, capture)
        mock_detect.assert_not_called()
        # Neither model is configured and detection is disabled — the
        # existing ClickException path fires and _build_triage_adapters is
        # never reached.
        assert "lightweight_model" not in capture

    def test_only_one_set_does_not_autodetect(self, built_wiki, monkeypatch):
        monkeypatch.setenv("WIKI_MODEL", "anthropic:claude-sonnet-5")
        capture: dict = {}
        with patch("parrot.clients.detection.detect_coding_agent_llm") as mock_detect:
            self._invoke_ingest(built_wiki, capture)
        mock_detect.assert_not_called()
        assert "lightweight_model" not in capture

    def test_explicit_both_set_does_not_autodetect(self, built_wiki, monkeypatch):
        monkeypatch.setenv("WIKI_MODEL", "anthropic:claude-sonnet-5")
        monkeypatch.setenv("WIKI_LIGHTWEIGHT_MODEL", "anthropic:claude-haiku-4-5")
        capture: dict = {}
        with patch("parrot.clients.detection.detect_coding_agent_llm") as mock_detect:
            self._invoke_ingest(built_wiki, capture)
        mock_detect.assert_not_called()
        assert capture.get("lightweight_model") == "anthropic:claude-haiku-4-5"
        assert capture.get("model") == "anthropic:claude-sonnet-5"
