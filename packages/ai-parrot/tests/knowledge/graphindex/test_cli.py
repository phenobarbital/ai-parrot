"""Tests for the GraphIndex CLI (parrot-graphindex).

Exercises repository discovery and the local, LLM-free build → the produced
``graph.html`` / ``graph.json`` / ``GRAPH_REPORT.md`` artefacts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.knowledge.graphindex import cli


SAMPLE_A = '''\
# WHY: central hub per ADR-1
class Engine:
    """Core engine. See RFC-2119."""

    def start(self):
        return Wheel()


class Wheel:
    """A wheel."""
    pass
'''

SAMPLE_B = '''\
from a import Engine


def drive():
    """Drive the engine."""
    return Engine().start()
'''


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text(SAMPLE_A)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "b.py").write_text(SAMPLE_B)
    # Noise that must be skipped.
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "junk.py").write_text("x = 1\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.py").write_text("y = 2\n")
    # Tool output planes. `.claude` holds SDD worktrees: a full second copy
    # of the repository, per worktree.
    worktree = tmp_path / ".claude" / "worktrees" / "feat-1" / "pkg"
    worktree.mkdir(parents=True)
    (worktree / "b.py").write_text(SAMPLE_B)
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "generated.py").write_text("z = 3\n")
    return tmp_path


class TestDiscovery:
    def test_skips_noise_directories(self, sample_repo):
        found = cli.discover_python_files(sample_repo)
        names = {p.name for p in found}
        assert names == {"a.py", "b.py"}
        assert not any(".venv" in p.parts for p in found)

    def test_skips_tool_output_planes(self, sample_repo):
        """`.claude` and `build` are pruned, not walked then discarded.

        A worktree under `.claude` is a complete copy of the repository, so
        failing to prune it both duplicates every symbol and costs a full
        extra walk per worktree.
        """
        found = cli.discover_python_files(sample_repo)
        assert not any(".claude" in p.parts or "build" in p.parts for p in found)
        assert len(found) == 2

    def test_shares_the_package_wide_exclusion_list(self):
        """One list, not a per-subsystem copy that can fall behind again."""
        from parrot.knowledge.scan_excludes import SCAN_EXCLUDE_DIRS
        from parrot.knowledge.wiki.repo_scan import DEFAULT_EXCLUDE_DIRS

        assert cli._ALWAYS_SKIP is SCAN_EXCLUDE_DIRS is DEFAULT_EXCLUDE_DIRS

    def test_single_file(self, sample_repo):
        found = cli.discover_python_files(sample_repo / "a.py")
        assert [p.name for p in found] == ["a.py"]

    def test_deterministic_order(self, sample_repo):
        assert cli.discover_python_files(sample_repo) == cli.discover_python_files(
            sample_repo
        )


class TestBuildCodeGraph:

    @pytest.mark.asyncio
    async def test_configured_prefixes_reach_extractor(self, tmp_path: Path) -> None:
        """The production build loads local and foreign ADR prefixes from config."""
        configured = tmp_path / "configured"
        (configured / ".parrot").mkdir(parents=True)
        (configured / ".parrot" / "wiki.json").write_text(
            json.dumps({"decisions": {"local_prefix": "FS", "known_prefixes": ["EXT"]}}),
            encoding="utf-8",
        )
        (configured / "citing.py").write_text(
            "# FS-ADR-3, EXT-ADR-4, other-ADR-5, and FS-RFC-2119\nvalue = 1\n",
            encoding="utf-8",
        )
        configured_output = tmp_path / "configured-output"
        await cli.build_code_graph([configured], configured_output, detect_comms=False)
        configured_graph = json.loads((configured_output / "graph.json").read_text(encoding="utf-8"))
        configured_titles = {node["name"] for node in configured_graph["nodes"]}
        assert {"FS-ADR-3", "EXT-ADR-4", "ADR-5", "RFC-2119"} <= configured_titles

        unconfigured = tmp_path / "unconfigured"
        unconfigured.mkdir()
        (unconfigured / "citing.py").write_text("# FS-ADR-3\nvalue = 1\n", encoding="utf-8")
        unconfigured_output = tmp_path / "unconfigured-output"
        await cli.build_code_graph([unconfigured], unconfigured_output, detect_comms=False)
        unconfigured_graph = json.loads((unconfigured_output / "graph.json").read_text(encoding="utf-8"))
        unconfigured_titles = {node["name"] for node in unconfigured_graph["nodes"]}
        assert "ADR-3" in unconfigured_titles
        assert "FS-ADR-3" not in unconfigured_titles

        invalid = tmp_path / "invalid"
        (invalid / ".parrot").mkdir(parents=True)
        (invalid / ".parrot" / "wiki.json").write_text(
            json.dumps({"decisions": {"local_prefix": "1INVALID"}}), encoding="utf-8"
        )
        (invalid / "citing.py").write_text("# ADR-1\nvalue = 1\n", encoding="utf-8")
        invalid_output = tmp_path / "invalid-output"
        await cli.build_code_graph([invalid], invalid_output, detect_comms=False)
        invalid_graph = json.loads((invalid_output / "graph.json").read_text(encoding="utf-8"))
        assert "ADR-1" in {node["name"] for node in invalid_graph["nodes"]}

    @pytest.mark.asyncio
    async def test_nested_input_uses_repo_root_config(self, tmp_path: Path) -> None:
        """A nested input path inherits the nearest ancestor wiki config."""
        repo = tmp_path / "repo"
        (repo / ".parrot").mkdir(parents=True)
        (repo / ".parrot" / "wiki.json").write_text(
            json.dumps({"decisions": {"local_prefix": "FS"}}), encoding="utf-8"
        )
        (repo / "pkg").mkdir()
        (repo / "pkg" / "citing.py").write_text("# FS-ADR-3\nvalue = 1\n", encoding="utf-8")
        output = tmp_path / "nested-output"
        await cli.build_code_graph([repo / "pkg"], output, detect_comms=False)
        graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))
        assert "FS-ADR-3" in {node["name"] for node in graph["nodes"]}

    @pytest.mark.asyncio
    async def test_multiple_roots_keep_allowlists_isolated(self, tmp_path: Path) -> None:
        """One input root cannot grant an ADR prefix to another input root."""
        alpha = tmp_path / "alpha"
        beta = tmp_path / "beta"
        for root, prefix, filename, source in (
            (alpha, "ALPHA", "alpha.py", "# ALPHA-ADR-1 and BETA-ADR-2\nalpha = 1\n"),
            (beta, "BETA", "beta.py", "# ALPHA-ADR-1 and BETA-ADR-2\nbeta = 2\n"),
        ):
            (root / ".parrot").mkdir(parents=True)
            (root / ".parrot" / "wiki.json").write_text(
                json.dumps({"decisions": {"local_prefix": prefix}}), encoding="utf-8"
            )
            (root / filename).write_text(source, encoding="utf-8")

        combined_output = tmp_path / "combined-output"
        await cli.build_code_graph([alpha, beta], combined_output, detect_comms=False)
        combined_graph = json.loads((combined_output / "graph.json").read_text(encoding="utf-8"))
        titles_by_source = {
            source: {node["name"] for node in combined_graph["nodes"] if node["source_uri"] == source}
            for source in ("alpha.py", "beta.py")
        }
        assert {"ALPHA-ADR-1", "ADR-2"} <= titles_by_source["alpha.py"]
        assert {"ADR-1", "BETA-ADR-2"} <= titles_by_source["beta.py"]
        assert "BETA-ADR-2" not in titles_by_source["alpha.py"]
        assert "ALPHA-ADR-1" not in titles_by_source["beta.py"]

        file_output = tmp_path / "file-output"
        await cli.build_code_graph([alpha / "alpha.py"], file_output, detect_comms=False)
        file_graph = json.loads((file_output / "graph.json").read_text(encoding="utf-8"))
        file_titles = {node["name"] for node in file_graph["nodes"]}
        assert "ALPHA-ADR-1" in file_titles
        assert "BETA-ADR-2" not in file_titles

    @pytest.mark.asyncio
    async def test_writes_all_artifacts(self, sample_repo, tmp_path):
        out = tmp_path / "graphindex"
        summary = await cli.build_code_graph([sample_repo], out)
        assert (out / "graph.html").exists()
        assert (out / "graph.json").exists()
        assert (out / "GRAPH_REPORT.md").exists()
        assert summary["files_indexed"] == 2
        assert summary["node_count"] > 0

    @pytest.mark.asyncio
    async def test_graph_html_is_offline(self, sample_repo, tmp_path):
        out = tmp_path / "gi"
        await cli.build_code_graph([sample_repo], out)
        html = (out / "graph.html").read_text()
        assert "echarts.init" in html
        assert "cdn.jsdelivr.net" not in html  # vendored asset inlined

    @pytest.mark.asyncio
    async def test_communities_toggle(self, sample_repo, tmp_path):
        with_comms = await cli.build_code_graph([sample_repo], tmp_path / "c1")
        without = await cli.build_code_graph(
            [sample_repo], tmp_path / "c2", detect_comms=False
        )
        assert with_comms["community_count"] >= 0
        assert without["community_count"] == 0
        assert without["modularity"] is None

    @pytest.mark.asyncio
    async def test_adr_rfc_citations_present(self, sample_repo, tmp_path):
        out = tmp_path / "gi"
        await cli.build_code_graph([sample_repo], out)
        data = json.loads((out / "graph.json").read_text())
        titles = {n["name"] for n in data["nodes"]}
        assert {"ADR-1", "RFC-2119"} <= titles


class TestMain:
    def test_main_end_to_end(self, sample_repo, tmp_path, capsys):
        out = tmp_path / "out"
        rc = cli.main([str(sample_repo), "-o", str(out)])
        assert rc == 0
        assert (out / "graph.html").exists()
        captured = capsys.readouterr().out
        assert "GraphIndex built" in captured
        assert "Artifacts:" in captured

    def test_main_missing_path(self, tmp_path):
        rc = cli.main([str(tmp_path / "nope")])
        assert rc == 2

    def test_main_empty_repo(self, tmp_path, capsys):
        rc = cli.main([str(tmp_path), "-o", str(tmp_path / "out")])
        assert rc == 1
        assert "No Python files" in capsys.readouterr().err
