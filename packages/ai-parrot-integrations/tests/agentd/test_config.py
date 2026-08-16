"""Unit tests for parrot.integrations.agentd.config (TASK-2210)."""

from __future__ import annotations

import os

import pytest
from parrot.integrations.agentd.config import (
    AgentServiceConfig,
    AgentTargetConfig,
    AgentTargetError,
    SchedulerConfig,
    default_socket_path,
    resolve_agent,
)


class TestConfig:
    def test_yaml_roundtrip(self, tmp_path):
        yaml_path = tmp_path / "agentd.yaml"
        yaml_path.write_text(
            """
name: my-agent
agent:
  target: "tests.agentd.fakes:EchoAgent"
  kwargs:
    name: "yaml-echo"
scheduler:
  enabled: true
  dsn: "postgres://user:pass@localhost/db"
  redis: true
exposed_methods:
  - "some_method"
log_level: "DEBUG"
max_line_bytes: 1024
shutdown_grace: 5.0
""".strip()
        )

        cfg = AgentServiceConfig.from_yaml(yaml_path)

        assert cfg.name == "my-agent"
        assert cfg.agent.target == "tests.agentd.fakes:EchoAgent"
        assert cfg.agent.kwargs == {"name": "yaml-echo"}
        assert cfg.scheduler.enabled is True
        assert cfg.scheduler.dsn == "postgres://user:pass@localhost/db"
        assert cfg.scheduler.redis is True
        assert cfg.exposed_methods == ["some_method"]
        assert cfg.log_level == "DEBUG"
        assert cfg.max_line_bytes == 1024
        assert cfg.shutdown_grace == 5.0

    def test_defaults(self, tmp_path):
        yaml_path = tmp_path / "minimal.yaml"
        yaml_path.write_text(
            'name: minimal\nagent:\n  target: "tests.agentd.fakes:EchoAgent"\n'
        )

        cfg = AgentServiceConfig.from_yaml(yaml_path)

        assert cfg.socket is None
        assert cfg.scheduler == SchedulerConfig()
        assert cfg.exposed_methods == []
        assert cfg.log_level == "INFO"
        assert cfg.max_line_bytes == 10 * 1024 * 1024
        assert cfg.shutdown_grace == 30.0

    def test_from_target_builds_config_without_yaml(self):
        cfg = AgentServiceConfig.from_target(
            "tests.agentd.fakes:EchoAgent", name="cli-agent", log_level="WARNING"
        )

        assert cfg.name == "cli-agent"
        assert cfg.agent.target == "tests.agentd.fakes:EchoAgent"
        assert cfg.log_level == "WARNING"

    def test_bad_name_rejected(self):
        with pytest.raises(ValueError):
            AgentServiceConfig(
                name="bad/name",
                agent=AgentTargetConfig(target="tests.agentd.fakes:EchoAgent"),
            )

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError):
            AgentServiceConfig(
                name="",
                agent=AgentTargetConfig(target="tests.agentd.fakes:EchoAgent"),
            )


class TestDefaultSocketPath:
    def test_uses_xdg_runtime_dir_when_set(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

        path = default_socket_path("my-agent")

        assert path == tmp_path / "parrot" / "my-agent.sock"

    def test_falls_back_to_tmp_when_unset(self, monkeypatch):
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

        path = default_socket_path("my-agent")

        assert str(path) == f"/tmp/parrot-{os.getuid()}/my-agent.sock"


class TestResolveAgent:
    async def test_class_target(self):
        cfg = AgentTargetConfig(
            target="tests.agentd.fakes:EchoAgent", kwargs={"name": "class-target"}
        )

        agent = await resolve_agent(cfg)

        assert agent.name == "class-target"
        assert agent.configured is True

    async def test_instance_target(self):
        cfg = AgentTargetConfig(target="tests.agentd.fakes:echo_instance")

        agent = await resolve_agent(cfg)

        assert agent.name == "singleton-instance"
        assert agent.configured is True

    async def test_sync_factory_target(self):
        cfg = AgentTargetConfig(
            target="tests.agentd.fakes:make_echo_agent",
            kwargs={"name": "sync-factory"},
        )

        agent = await resolve_agent(cfg)

        assert agent.name == "sync-factory"
        assert agent.configured is True

    async def test_async_factory_target(self):
        cfg = AgentTargetConfig(
            target="tests.agentd.fakes:make_echo_agent_async",
            kwargs={"name": "async-factory"},
        )

        agent = await resolve_agent(cfg)

        assert agent.name == "async-factory"
        assert agent.configured is True

    async def test_missing_module_raises(self):
        cfg = AgentTargetConfig(target="tests.agentd.does_not_exist:EchoAgent")

        with pytest.raises(AgentTargetError):
            await resolve_agent(cfg)

    async def test_missing_attr_raises(self):
        cfg = AgentTargetConfig(target="tests.agentd.fakes:DoesNotExist")

        with pytest.raises(AgentTargetError):
            await resolve_agent(cfg)

    async def test_bad_target_shape_raises(self):
        cfg = AgentTargetConfig(target="no-colon-in-target")

        with pytest.raises(AgentTargetError):
            await resolve_agent(cfg)
