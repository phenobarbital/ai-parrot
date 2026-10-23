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
    expand_env_vars,
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


class TestExpandEnvVars:
    """Tests for environment-variable expansion in YAML configs."""

    def test_interpolation_syntax(self, monkeypatch):
        """``${VAR}`` is replaced by the env value."""
        monkeypatch.setenv("MY_VAULT", "/home/user/vault")
        result = expand_env_vars({"path": "${MY_VAULT}"})
        assert result == {"path": "/home/user/vault"}

    def test_interpolation_with_default(self, monkeypatch):
        """``${VAR:-default}`` falls back when VAR is unset."""
        monkeypatch.delenv("UNSET_VAR", raising=False)
        result = expand_env_vars({"path": "${UNSET_VAR:-/fallback/path}"})
        assert result == {"path": "/fallback/path"}

    def test_interpolation_default_ignored_when_set(self, monkeypatch):
        """``${VAR:-default}`` uses env value when VAR IS set."""
        monkeypatch.setenv("SET_VAR", "/real/path")
        result = expand_env_vars({"path": "${SET_VAR:-/fallback}"})
        assert result == {"path": "/real/path"}

    def test_partial_interpolation(self, monkeypatch):
        """Multiple ``${VAR}`` tokens inside a single string."""
        monkeypatch.setenv("HOST", "localhost")
        monkeypatch.setenv("PORT", "8080")
        result = expand_env_vars({"url": "https://${HOST}:${PORT}/api"})
        assert result == {"url": "https://localhost:8080/api"}

    def test_bare_name_fallback(self, monkeypatch):
        """All-caps bare name resolves to env var when it exists."""
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/my/vault")
        result = expand_env_vars({"vault_path": "OBSIDIAN_VAULT_PATH"})
        assert result == {"vault_path": "/my/vault"}

    def test_bare_name_no_match(self, monkeypatch):
        """Bare name left as-is when no matching env var exists."""
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        result = expand_env_vars({"val": "NONEXISTENT_VAR"})
        assert result == {"val": "NONEXISTENT_VAR"}

    def test_bare_name_requires_uppercase(self):
        """Lowercase strings are NOT treated as bare env-var names."""
        result = expand_env_vars({"path": "~/vaults/notes"})
        assert result == {"path": "~/vaults/notes"}

    def test_non_string_scalars_untouched(self):
        """Ints, floats, bools, None pass through unchanged."""
        data = {"port": 8080, "debug": True, "ratio": 0.5, "extra": None}
        assert expand_env_vars(data) == data

    def test_nested_dicts_and_lists(self, monkeypatch):
        """Expansion recurses into nested dicts and lists."""
        monkeypatch.setenv("TOKEN", "secret123")
        data = {
            "agent": {
                "kwargs": {
                    "tokens": ["${TOKEN}", "literal"],
                }
            }
        }
        result = expand_env_vars(data)
        assert result["agent"]["kwargs"]["tokens"] == ["secret123", "literal"]

    def test_unset_interpolation_preserved(self, monkeypatch):
        """``${UNSET}`` (no default) is left as-is for downstream errors."""
        monkeypatch.delenv("UNSET_VAR", raising=False)
        result = expand_env_vars({"key": "${UNSET_VAR}"})
        assert result == {"key": "${UNSET_VAR}"}

    def test_from_yaml_expands_env(self, tmp_path, monkeypatch):
        """End-to-end: ``from_yaml`` expands env vars before validation."""
        monkeypatch.setenv("MY_LOG_LEVEL", "WARNING")
        yaml_path = tmp_path / "cfg.yaml"
        yaml_path.write_text(
            'name: test\nagent:\n  target: "tests.agentd.fakes:EchoAgent"\n'
            'log_level: "${MY_LOG_LEVEL:-INFO}"\n'
        )
        cfg = AgentServiceConfig.from_yaml(yaml_path)
        assert cfg.log_level == "WARNING"

    def test_from_yaml_bare_name_in_kwargs(self, tmp_path, monkeypatch):
        """End-to-end: bare-name expansion works inside agent.kwargs."""
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/home/test/vault")
        yaml_path = tmp_path / "cfg.yaml"
        yaml_path.write_text(
            'name: test\nagent:\n  target: "tests.agentd.fakes:EchoAgent"\n'
            "  kwargs:\n    vault_path: OBSIDIAN_VAULT_PATH\n"
        )
        cfg = AgentServiceConfig.from_yaml(yaml_path)
        assert cfg.agent.kwargs["vault_path"] == "/home/test/vault"


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
