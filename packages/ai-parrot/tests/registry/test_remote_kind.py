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


async def test_remote_metadata_and_factory_refuse_instantiation(tmp_path):
    """Every instantiation path raises the typed error for a remote entry."""
    reg = AgentRegistry(agents_dir=tmp_path)
    reg.register_remote(_cfg())
    with pytest.raises(RemoteAgentNotInstantiable):
        await reg.get_metadata("hr").get_instance()
    with pytest.raises(RemoteAgentNotInstantiable):
        reg.create_agent_factory(_cfg())


def test_remote_definition_round_trips_through_yaml(tmp_path):
    """create_agent_definition keeps kind, endpoint and contract categories."""
    reg = AgentRegistry(agents_dir=tmp_path)
    path = reg.create_agent_definition(_cfg())
    reloaded = AgentRegistry(agents_dir=tmp_path)
    assert reloaded.load_agent_definition_file(path) is True
    meta = reloaded.get_metadata("hr")
    assert meta.kind == AgentKind.SQUAWK
    assert meta.endpoint == "squawk://hr:7470"
    assert meta.contract_categories == ["hr.reports"]


async def test_remote_entry_is_pbac_checked_before_the_remote_refusal(tmp_path):
    """A denied caller gets AgentAccessDenied; an allowed one gets the typed refusal without the endpoint."""
    from unittest.mock import AsyncMock, MagicMock, patch

    pytest.importorskip("navigator_auth.abac.policies.resources")
    from parrot.auth.agent_guard import AgentAccessDenied

    reg = AgentRegistry(agents_dir=tmp_path)
    reg.register_remote(_cfg())
    evaluator = MagicMock()
    reg._evaluator = evaluator
    eval_ctx = MagicMock()
    eval_ctx.username = "user-42"
    with patch("parrot.auth.agent_guard._build_eval_context_from_request", new=AsyncMock(return_value=eval_ctx)):
        evaluator.check_access.return_value = MagicMock(allowed=False, matched_policy="deny", reason="no")
        with pytest.raises(AgentAccessDenied):
            await reg.get_instance("hr", request=MagicMock())

        evaluator.check_access.return_value = MagicMock(allowed=True)
        with pytest.raises(RemoteAgentNotInstantiable) as exc_info:
            await reg.get_instance("hr", request=MagicMock())
    assert "squawk://" not in str(exc_info.value)


def test_remote_entry_advertises_its_roost_capabilities(tmp_path):
    """register_remote mirrors the roost block into the capability index, replacing stale entries."""
    from parrot.roost.directory import RoostAgentConfig

    reg = AgentRegistry(agents_dir=tmp_path)
    reg.register_remote(_cfg(roost=RoostAgentConfig(capabilities=["hr.reports.headcount"], keywords=["headcount"])))
    (match,) = reg.find_capability("headcount")
    assert match.cap_id == "hr.reports.headcount"
    assert reg.find_capability("headcount", include_remote=False) == []

    reg.register_remote(_cfg(roost=RoostAgentConfig(capabilities=["hr.reports.attrition"], keywords=["attrition"])))
    assert reg.find_capability("headcount") == []
    assert [m.cap_id for m in reg.find_capability("attrition")] == ["hr.reports.attrition"]
