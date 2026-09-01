"""Tests for the example consoles' research-seat MCP wiring (FEAT-484/485).

Loads ``examples/dev_loop/mcp_wiring.py`` (and ``server.py`` for the
``_parse_dev_agents`` guard) via ``importlib.util.spec_from_file_location``
— the same pattern as ``test_adversarial_server_wiring.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_EXAMPLES_DIR = Path(__file__).parents[5] / "examples" / "dev_loop"

_REPO_YAML = """
toolkits:
  repo:
    class: parrot.tools.repo.toolkit.ReadOnlyRepoToolkit
    enabled: true
    kwargs:
      repo_root: /abs/checkout
  disabled_one:
    class: parrot.tools.working_memory.tool.WorkingMemoryToolkit
    enabled: false
"""


def _load_example_module(basename: str, module_name: str):
    path = _EXAMPLES_DIR / basename
    if not path.exists():
        pytest.skip(f"{basename} not found at {path}")
    if module_name in sys.modules:
        del sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mcp_wiring():
    return _load_example_module("mcp_wiring.py", "_dev_loop_mcp_wiring_under_test")


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    (tmp_path / ".parrot").mkdir()
    (tmp_path / ".parrot" / "mcp-toolkits.yaml").write_text(_REPO_YAML, encoding="utf-8")
    return tmp_path


class TestBuildResearchMcp:
    def test_kill_switch(self, mcp_wiring, repo_root, monkeypatch):
        monkeypatch.setenv("DEV_LOOP_RESEARCH_MCP_ENABLED", "false")
        servers, tools = mcp_wiring.build_research_mcp(repo_root)
        assert servers == {} and tools == []

    def test_auto_serves_declared_enabled_sections_only(self, mcp_wiring, repo_root, monkeypatch):
        monkeypatch.delenv("DEV_LOOP_RESEARCH_MCP_ENABLED", raising=False)
        monkeypatch.delenv("DEV_LOOP_RESEARCH_MCP_TOOLKITS", raising=False)
        servers, tools = mcp_wiring.build_research_mcp(repo_root)
        assert "parrot-repo" in servers
        # Disabled sections and undeclared built-ins are never auto-spawned.
        assert "parrot-disabled_one" not in servers
        assert "parrot-memory" not in servers
        assert "mcp__parrot-repo" in tools

    def test_toolkit_entry_carries_config_override(self, mcp_wiring, repo_root, monkeypatch):
        monkeypatch.delenv("DEV_LOOP_RESEARCH_MCP_TOOLKITS", raising=False)
        servers, _tools = mcp_wiring.build_research_mcp(repo_root)
        args = servers["parrot-repo"]["args"]
        assert args[:2] == ["mcp-local", "repo"]
        assert "--config" in args
        assert args[args.index("--config") + 1] == str(repo_root / ".parrot" / "mcp-toolkits.yaml")

    def test_explicit_selection_may_name_builtins(self, mcp_wiring, repo_root, monkeypatch):
        monkeypatch.setenv("DEV_LOOP_RESEARCH_MCP_TOOLKITS", "memory")
        servers, tools = mcp_wiring.build_research_mcp(repo_root)
        assert "parrot-memory" in servers
        assert "mcp__parrot-memory" in tools

    def test_unknown_selection_warns_and_skips(self, mcp_wiring, repo_root, monkeypatch, caplog):
        monkeypatch.setenv("DEV_LOOP_RESEARCH_MCP_TOOLKITS", "ghost")
        with caplog.at_level("WARNING"):
            servers, _tools = mcp_wiring.build_research_mcp(repo_root)
        assert "parrot-ghost" not in servers
        assert any("ghost" in rec.message for rec in caplog.records)

    def test_no_yaml_yields_no_toolkit_servers(self, mcp_wiring, tmp_path, monkeypatch):
        monkeypatch.delenv("DEV_LOOP_RESEARCH_MCP_TOOLKITS", raising=False)
        servers, _tools = mcp_wiring.build_research_mcp(tmp_path)
        assert not any(name.startswith("parrot-") for name in servers)

    def test_invalid_yaml_degrades_with_warning(self, mcp_wiring, tmp_path, monkeypatch, caplog):
        (tmp_path / ".parrot").mkdir()
        (tmp_path / ".parrot" / "mcp-toolkits.yaml").write_text("unknown_key: 1\n", encoding="utf-8")
        monkeypatch.delenv("DEV_LOOP_RESEARCH_MCP_TOOLKITS", raising=False)
        with caplog.at_level("WARNING"):
            servers, _tools = mcp_wiring.build_research_mcp(tmp_path)
        assert not any(name.startswith("parrot-") for name in servers)
        assert any("Ignoring invalid" in rec.message for rec in caplog.records)

    def test_wikitoolkit_included_when_binary_resolves(self, mcp_wiring, repo_root, monkeypatch):
        monkeypatch.setattr(
            "_dev_loop_mcp_wiring_under_test.resolve_wikitoolkit_bin",
            lambda _root: "/opt/bin/wikitoolkit",
        )
        monkeypatch.setattr("shutil.which", lambda _n: "/opt/bin/wikitoolkit")
        servers, tools = mcp_wiring.build_research_mcp(repo_root)
        assert servers["wikitoolkit"]["args"] == ["mcp"]
        assert "mcp__wikitoolkit__wiki_query" in tools


class TestParseDevAgentsGuard:
    def test_gpt_rejected_cleanly(self):
        """FEAT-486: 'gpt' is a research-partner-only catalog entry — the
        parser must reject it with its own message, not a pydantic blow-up
        from DevAgentSpec's Literal."""
        server = _load_example_module("server.py", "_dev_loop_server_under_test_mcp")
        with pytest.raises(ValueError, match="not a development backend"):
            server._parse_dev_agents([{"agent": "gpt", "model": "gpt-5.6-sol", "count": 1}])
