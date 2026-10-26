"""Tests for remote agent kinds in the registry (FEAT-746 M13)."""

import pytest

from parrot.registry import AgentKind, AgentRegistry, BotConfig, RemoteAgentNotInstantiable


def _cfg(**kw):
    return BotConfig(name="hr", kind="squawk", endpoint="squawk://hr:7470", contract_categories=["hr.reports"], **kw)


def test_remote_config_needs_endpoint():
    with pytest.raises(ValueError):
        BotConfig(name="hr", kind="squawk")
    cfg = _cfg()
    assert cfg.kind is AgentKind.SQUAWK and cfg.class_name is None


def test_local_config_still_requires_class():
    with pytest.raises(ValueError):
        BotConfig(name="x")


async def test_register_remote_and_refuse_instance(tmp_path):
    reg = AgentRegistry(agents_dir=tmp_path)
    reg.register_remote(_cfg())
    assert [m.name for m in reg.find_serving("hr.reports")] == ["hr"]
    assert reg.find_serving("hr") == []
    assert [m.name for m in reg.find_by_kind(AgentKind.SQUAWK)] == ["hr"]
    assert reg.find_by_kind(AgentKind.LOCAL) == []
    with pytest.raises(RemoteAgentNotInstantiable):
        await reg.get_instance("hr")


def test_yaml_remote_definition(tmp_path):
    reg = AgentRegistry(agents_dir=tmp_path)
    f = tmp_path / "hr.yaml"
    f.write_text(
        "agent:\n  name: hr\n  kind: squawk\n  endpoint: squawk://hr:7470\n  contract_categories: [hr.reports]\n"
    )
    assert reg.load_agent_definition_file(f) is True
    assert reg.get_metadata("hr").kind == AgentKind.SQUAWK
