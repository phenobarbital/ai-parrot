"""FEAT-877 Module 6 — `parrot toolkits install --agent` / `list --agents`."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.cli.toolkits import toolkits
from parrot.mcp.toolkit_install import ActionReport, ToolkitRow, ToolkitState


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the CLI at tmp_path with no detected hosts."""
    monkeypatch.setattr("parrot.cli.toolkits._root", lambda path_=None, *, write: tmp_path)
    monkeypatch.setattr("parrot.cli.toolkits._resolve_hosts", lambda root, hosts_: [])
    return tmp_path


def test_cli_install_agent(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Install explicit agents without opening the template picker."""
    calls: list[tuple] = []

    def fake_install(root_, agents, hosts, *, portable=None):
        calls.append(("agents", root_, agents))
        return ActionReport(actions=["finance — seeded as agent-finance (tools: forecast)"])

    def fake_templates(root_, names, hosts, *, portable=None):
        calls.append(("templates", root_, names))
        return ActionReport(actions=["memory — seeded"])

    def fake_picker(root_, names, hosts):
        calls.append(("picker", root_, names))
        return list(names)

    monkeypatch.setattr("parrot.mcp.toolkit_install.install_agent_toolkits", fake_install)
    monkeypatch.setattr("parrot.mcp.toolkit_install.install_toolkits", fake_templates)
    monkeypatch.setattr("parrot.cli.toolkits._resolve_names", fake_picker)

    result = CliRunner().invoke(toolkits, ["install", "--agent", "finance", "--yes"])
    assert result.exit_code == 0, result.output
    assert calls == [("agents", root, ["finance"])]
    assert "seeded as agent-finance" in result.output

    result = CliRunner().invoke(toolkits, ["install", "--agent", "finance"], input="n\n")
    assert result.exit_code == 0, result.output
    assert calls == [("agents", root, ["finance"])]

    result = CliRunner().invoke(toolkits, ["install", "memory", "--agent", "finance", "--yes"])
    assert result.exit_code == 0, result.output
    assert calls[-3:] == [
        ("picker", root, ("memory",)),
        ("templates", root, ["memory"]),
        ("agents", root, ["finance"]),
    ]


def test_cli_install_agent_error_exit(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Surface an agent installation error as a Click command failure."""

    def fake_install(root_, agents, hosts, *, portable=None):
        raise ValueError("Unknown agent 'nope'")

    monkeypatch.setattr("parrot.mcp.toolkit_install.install_agent_toolkits", fake_install)

    result = CliRunner().invoke(toolkits, ["install", "--agent", "nope", "--yes"])
    assert result.exit_code == 1, result.output
    assert "Unknown agent 'nope'" in result.output


def test_cli_list_agents(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Append agent inventory only when the explicit discovery option is set."""
    calls: list[str] = []

    def fake_inventory(root_, hosts):
        return []

    def fake_agent_inventory(root_, hosts):
        calls.append("agent_inventory")
        return [
            ToolkitRow(
                name="agent-finance",
                summary="agent finance: forecast",
                class_path="parrot.mcp.agent_toolkit.AgentToolkit",
                state=ToolkitState.ENABLED,
            )
        ]

    monkeypatch.setattr("parrot.mcp.toolkit_install.inventory", fake_inventory)
    monkeypatch.setattr("parrot.mcp.toolkit_install.agent_inventory", fake_agent_inventory)

    result = CliRunner().invoke(toolkits, ["list"])
    assert result.exit_code == 0, result.output
    assert calls == []

    result = CliRunner().invoke(toolkits, ["list", "--agents"])
    assert result.exit_code == 0, result.output
    assert calls == ["agent_inventory"]
    assert "agent-finance" in result.output
    assert "discovering agents imports every agent module under AGENTS_DIR" in result.output
