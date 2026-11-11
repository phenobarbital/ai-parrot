"""FEAT-877 Module 4 — seeding and installing agent sections."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.bots.agent import Agent
from parrot.mcp.hosts import HostKind
from parrot.mcp.toolkit_config import AGENT_TOOLKIT_CLASS_PATH, load_toolkits_config
from parrot.mcp.toolkit_install import (
    ToolkitState,
    agent_inventory,
    install_agent_toolkits,
    set_toolkits_enabled,
    uninstall_toolkits,
)
from parrot.mcp.toolkit_seed import seed_agent_sections, seed_toolkit_sections
from parrot.registry.registry import AgentRegistry


def _config(root: Path) -> Path:
    return root / ".parrot" / "mcp-toolkits.yaml"


def test_seed_agent_section_written(tmp_path: Path) -> None:
    result = seed_agent_sections(tmp_path, {"agent-finance": "finance"})
    assert result.created_file and result.added == ["agent-finance"]
    section = load_toolkits_config(tmp_path).toolkits["agent-finance"]
    assert section.class_path == AGENT_TOOLKIT_CLASS_PATH
    assert section.kwargs == {"agent": "finance"}

    original = _config(tmp_path).read_bytes()
    repeated = seed_agent_sections(tmp_path, {"agent-finance": "finance"})
    assert repeated.skipped == ["agent-finance"]
    assert _config(tmp_path).read_bytes() == original

    seed_toolkit_sections(tmp_path, ["memory"])
    with_template = _config(tmp_path).read_text(encoding="utf-8")
    _config(tmp_path).write_text(f"{with_template}# operator comment\n", encoding="utf-8")
    seed_agent_sections(tmp_path, {"agent-research": "research"})
    updated = _config(tmp_path).read_text(encoding="utf-8")
    assert "# operator comment" in updated
    config = load_toolkits_config(tmp_path)
    assert "memory" in config.toolkits
    assert config.toolkits["agent-research"].kwargs == {"agent": "research"}


def test_seed_agent_section_conflict(tmp_path: Path) -> None:
    seed_agent_sections(tmp_path, {"agent-finance": "finance"})
    original = _config(tmp_path).read_bytes()
    with pytest.raises(ValueError, match="agent-finance"):
        seed_agent_sections(tmp_path, {"agent-finance": "other"})
    assert _config(tmp_path).read_bytes() == original

    other_root = tmp_path / "other"
    path = _config(other_root)
    path.parent.mkdir(parents=True)
    path.write_text(
        "toolkits:\n" "  agent-x:\n" "    class: parrot.mcp.other.OtherToolkit\n" "    kwargs:\n" "      agent: x\n",
        encoding="utf-8",
    )
    other_original = path.read_bytes()
    with pytest.raises(ValueError, match="agent-x"):
        seed_agent_sections(other_root, {"agent-x": "x"})
    assert path.read_bytes() == other_original


def test_seed_agent_section_malformed_file(tmp_path: Path) -> None:
    path = _config(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("toolkits: [invalid", encoding="utf-8")
    original = path.read_bytes()

    with pytest.raises(ValueError):
        seed_agent_sections(tmp_path, {"agent-finance": "finance"})
    assert path.read_bytes() == original


class FinanceAgent(Agent):
    """Test agent with one locally exposable method."""

    async def forecast(self, months: int) -> dict:
        """Forecast cash for the next ``months`` months."""
        return {"months": months}


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a project root with an isolated registry containing ``finance``."""
    registry = AgentRegistry(agents_dir=tmp_path / "agents")
    registry.register_bot_decorator(name="finance", mcp_local=True)(FinanceAgent)
    monkeypatch.setattr("parrot.mcp.agent_toolkit.agent_registry", registry)
    root = tmp_path / "repo"
    root.mkdir()
    return root


def test_install_agent_all_or_nothing(repo: Path) -> None:
    with pytest.raises(ValueError, match="nope"):
        install_agent_toolkits(repo, ["finance", "nope"], [HostKind.CLAUDE])

    assert not _config(repo).exists()
    assert not (repo / ".mcp.json").exists()


def test_install_agent_reconciles_hosts(repo: Path) -> None:
    report = install_agent_toolkits(repo, ["finance"], [HostKind.CLAUDE])
    assert "finance — seeded as agent-finance (tools: forecast)" in report.actions

    host_config = json.loads((repo / ".mcp.json").read_text(encoding="utf-8"))
    args = host_config["mcpServers"]["parrot-agent-finance"]["args"]
    assert "mcp-local" in args
    assert "agent-finance" in args

    repeated = install_agent_toolkits(repo, ["finance"], [HostKind.CLAUDE])
    assert "finance — already installed as agent-finance" in repeated.warnings


def test_agent_inventory_rows(repo: Path) -> None:
    before = {row.name: row for row in agent_inventory(repo, hosts=[])}
    assert before["agent-finance"].state is ToolkitState.NOT_INSTALLED
    assert before["agent-finance"].summary == "agent finance: forecast"

    install_agent_toolkits(repo, ["finance"], [])
    after = {row.name: row for row in agent_inventory(repo, hosts=[])}
    assert after["agent-finance"].state is ToolkitState.ENABLED

    seed_agent_sections(repo, {"agent-ghost": "ghost"})
    with_orphan = {row.name: row for row in agent_inventory(repo, hosts=[])}
    assert with_orphan["agent-ghost"].drift[0].startswith("agent not exposable: ")


def test_uninstall_and_disable_agent_section(repo: Path) -> None:
    install_agent_toolkits(repo, ["finance"], [HostKind.CLAUDE])

    set_toolkits_enabled(repo, ["agent-finance"], False, [HostKind.CLAUDE])
    assert "parrot-agent-finance" not in json.loads((repo / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    disabled = load_toolkits_config(repo).toolkits["agent-finance"]
    assert disabled.enabled is False

    set_toolkits_enabled(repo, ["agent-finance"], True, [HostKind.CLAUDE])
    enabled_host = json.loads((repo / ".mcp.json").read_text(encoding="utf-8"))
    assert "parrot-agent-finance" in enabled_host["mcpServers"]

    uninstall_toolkits(repo, ["agent-finance"], [HostKind.CLAUDE])
    assert "agent-finance" not in load_toolkits_config(repo).toolkits
    uninstalled_host = json.loads((repo / ".mcp.json").read_text(encoding="utf-8"))
    assert "parrot-agent-finance" not in uninstalled_host["mcpServers"]


@pytest.mark.parametrize("header", ["# toolkits: managed by hand\n", "# toolkits:\nnotes: \"toolkits: none\"\n"])
def test_seed_agent_section_ignores_toolkits_mention_in_comment(tmp_path: Path, header: str) -> None:
    """A comment or value that merely mentions `toolkits:` is not mistaken for the root key."""
    config = _config(tmp_path)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(header, encoding="utf-8")

    result = seed_agent_sections(tmp_path, {"agent-finance": "finance"})

    assert result.added == ["agent-finance"]
    assert "agent-finance" in load_toolkits_config(tmp_path).toolkits


def test_seed_agent_section_empty_flow_mapping_root(tmp_path: Path) -> None:
    """`toolkits: {}` is normalised so the new section loads."""
    config = _config(tmp_path)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("toolkits: {}\n", encoding="utf-8")

    seed_agent_sections(tmp_path, {"agent-finance": "finance"})

    assert "agent-finance" in load_toolkits_config(tmp_path).toolkits
