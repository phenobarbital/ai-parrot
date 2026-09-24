"""Unit tests for AgentRegistry.update_agent_tooling() (FEAT-593 TASK-3657)."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from parrot.registry import registry as registry_module
from parrot.registry.registry import AgentRegistry, BotConfig
from parrot.tools.spec import ToolkitSpec


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path)
    f = tmp_path / "agents" / "general" / "demo.yaml"
    f.parent.mkdir(parents=True)
    f.write_text(yaml.safe_dump({"agent": {"name": "demo", "toolkits": [], "tags": ["x"]}, "model": {"provider": "p"}}))
    reg = AgentRegistry.__new__(AgentRegistry)
    reg.logger = SimpleNamespace(info=lambda *a, **k: None)
    cfg = BotConfig(name="demo", class_name="C", module="m")
    reg.get_metadata = lambda name: SimpleNamespace(file_path=f, bot_config=cfg) if name == "demo" else None
    return reg, f


def test_rewrites_in_place(setup):
    reg, f = setup
    reg.update_agent_tooling("demo", toolkits=[ToolkitSpec(slug="jira", params={"a": 1})])
    data = yaml.safe_load(f.read_text())
    assert data["agent"]["toolkits"][0]["slug"] == "jira" and data["model"] == {"provider": "p"}
    assert not list(f.parent.glob(".*.tmp"))


def test_refuses_outside_agents_dir(setup, tmp_path):
    reg, _ = setup
    outside = tmp_path.parent / "demo.yaml"
    reg.get_metadata = lambda name: SimpleNamespace(file_path=outside, bot_config=object())
    with pytest.raises(PermissionError):
        reg.update_agent_tooling("demo", toolkits=[])
