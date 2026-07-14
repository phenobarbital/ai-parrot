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
    return tmp_path


class TestDiscovery:
    def test_skips_noise_directories(self, sample_repo):
        found = cli.discover_python_files(sample_repo)
        names = {p.name for p in found}
        assert names == {"a.py", "b.py"}
        assert not any(".venv" in p.parts for p in found)

    def test_single_file(self, sample_repo):
        found = cli.discover_python_files(sample_repo / "a.py")
        assert [p.name for p in found] == ["a.py"]

    def test_deterministic_order(self, sample_repo):
        assert cli.discover_python_files(sample_repo) == cli.discover_python_files(
            sample_repo
        )


class TestBuildCodeGraph:
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
