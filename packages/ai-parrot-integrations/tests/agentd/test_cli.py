"""Tests for parrot.integrations.agentd.cli (TASK-2216).

CliRunner-based: `serve` arg parsing (yaml vs target), `ask` exit codes +
non-TTY plain output, `install-service` unit-file generation, and the
core `LazyGroup` missing-module error message.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import click
import pytest
from click.testing import CliRunner
from parrot.integrations.agentd import cli as agentd_cli
from parrot.integrations.agentd.client import DaemonNotRunning


class _FakeDaemon:
    """Stand-in for AgentDaemon -- records the config it was built with."""

    last_config = None

    def __init__(self, config) -> None:
        _FakeDaemon.last_config = config

    async def run(self) -> None:
        return None


class _FakeAskClient:
    def __init__(self, result=None, error=None) -> None:
        self._result = result
        self._error = error
        self.closed = False

    async def call(self, method, **kwargs):
        if self._error is not None:
            raise self._error
        return self._result

    async def close(self) -> None:
        self.closed = True


class TestServe:
    def test_yaml_arg(self, tmp_path, monkeypatch):
        yaml_path = tmp_path / "cfg.yaml"
        yaml_path.write_text(
            'name: my-agent\nagent:\n  target: "tests.agentd.fakes:EchoAgent"\n'
        )
        monkeypatch.setattr(agentd_cli, "AgentDaemon", _FakeDaemon)

        runner = CliRunner()
        result = runner.invoke(agentd_cli.serve, [str(yaml_path)])

        assert result.exit_code == 0, result.output
        assert _FakeDaemon.last_config.name == "my-agent"
        assert _FakeDaemon.last_config.agent.target == "tests.agentd.fakes:EchoAgent"

    def test_target_arg(self, monkeypatch):
        monkeypatch.setattr(agentd_cli, "AgentDaemon", _FakeDaemon)

        runner = CliRunner()
        result = runner.invoke(
            agentd_cli.serve, ["tests.agentd.fakes:EchoAgent", "--name", "cli-agent"]
        )

        assert result.exit_code == 0, result.output
        assert _FakeDaemon.last_config.name == "cli-agent"
        assert _FakeDaemon.last_config.agent.target == "tests.agentd.fakes:EchoAgent"

    def test_target_arg_without_name_errors(self):
        runner = CliRunner()
        result = runner.invoke(agentd_cli.serve, ["tests.agentd.fakes:EchoAgent"])

        assert result.exit_code != 0

    def test_overrides_applied(self, tmp_path, monkeypatch):
        yaml_path = tmp_path / "cfg.yaml"
        yaml_path.write_text(
            'name: my-agent\nagent:\n  target: "tests.agentd.fakes:EchoAgent"\n'
        )
        monkeypatch.setattr(agentd_cli, "AgentDaemon", _FakeDaemon)

        runner = CliRunner()
        result = runner.invoke(
            agentd_cli.serve,
            [
                str(yaml_path),
                "--socket",
                str(tmp_path / "custom.sock"),
                "--dsn",
                "postgres://x",
                "--redis",
                "--log-level",
                "DEBUG",
            ],
        )

        assert result.exit_code == 0, result.output
        cfg = _FakeDaemon.last_config
        assert cfg.socket == tmp_path / "custom.sock"
        assert cfg.log_level == "DEBUG"
        assert cfg.scheduler.dsn == "postgres://x"
        assert cfg.scheduler.redis is True


class TestAsk:
    def test_exit_codes_success(self, monkeypatch, tmp_path):
        fake_client = _FakeAskClient(result={"output": "hi there"})

        async def _fake_connect(socket_path, **kwargs):
            return fake_client

        monkeypatch.setattr(
            agentd_cli.AgentDaemonClient, "connect", staticmethod(_fake_connect)
        )
        monkeypatch.setattr(agentd_cli, "resolve_socket", lambda name: tmp_path / "fake.sock")

        runner = CliRunner()
        result = runner.invoke(agentd_cli.ask, ["myagent", "hello?"])

        assert result.exit_code == 0
        assert "hi there" in result.output
        assert fake_client.closed is True

    def test_exit_codes_daemon_not_running(self, monkeypatch, tmp_path):
        async def _fake_connect(socket_path, **kwargs):
            raise DaemonNotRunning("no daemon listening")

        monkeypatch.setattr(
            agentd_cli.AgentDaemonClient, "connect", staticmethod(_fake_connect)
        )
        monkeypatch.setattr(agentd_cli, "resolve_socket", lambda name: tmp_path / "fake.sock")

        runner = CliRunner()
        result = runner.invoke(agentd_cli.ask, ["myagent", "hello?"])

        assert result.exit_code == 1

    def test_non_tty_plain(self, monkeypatch, tmp_path):
        """CliRunner's captured stdout is never a TTY -- output must be
        plain text with no ANSI escape codes."""
        fake_client = _FakeAskClient(result={"output": "plain output"})

        async def _fake_connect(socket_path, **kwargs):
            return fake_client

        monkeypatch.setattr(
            agentd_cli.AgentDaemonClient, "connect", staticmethod(_fake_connect)
        )
        monkeypatch.setattr(agentd_cli, "resolve_socket", lambda name: tmp_path / "fake.sock")

        runner = CliRunner()
        result = runner.invoke(agentd_cli.ask, ["myagent", "hello?"])

        assert result.exit_code == 0
        assert "\x1b[" not in result.output
        assert result.output.strip() == "plain output"


class TestInstallService:
    def test_unit_content(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "cfg.yaml"
        cfg_path.write_text(
            'name: my-agent\nagent:\n  target: "tests.agentd.fakes:EchoAgent"\n'
        )
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        runner = CliRunner()
        result = runner.invoke(agentd_cli.install_service, [str(cfg_path)])

        assert result.exit_code == 0, result.output
        unit_path = fake_home / ".config" / "systemd" / "user" / "parrot-my-agent.service"
        assert unit_path.exists()

        content = unit_path.read_text()
        assert "Type=notify" in content
        assert "Restart=on-failure" in content
        assert "Environment=PYTHONUNBUFFERED=1" in content
        assert "WantedBy=default.target" in content
        assert "After=network-online.target" in content
        assert str(cfg_path) in content
        assert "sudo" not in content

    def test_system_prints_only(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "cfg.yaml"
        cfg_path.write_text(
            'name: my-agent\nagent:\n  target: "tests.agentd.fakes:EchoAgent"\n'
        )
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        runner = CliRunner()
        result = runner.invoke(agentd_cli.install_service, [str(cfg_path), "--system"])

        assert result.exit_code == 0, result.output
        assert "Type=notify" in result.stdout
        assert "sudo" not in result.stdout
        assert not (fake_home / ".config").exists()


class TestCoreRegistration:
    def test_missing_module_message(self, monkeypatch):
        """A genuinely absent distribution names the install target."""
        from parrot.cli import cli as core_cli

        def _raise_import_error(name, *args, **kwargs):
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)

        monkeypatch.setattr(importlib, "import_module", _raise_import_error)

        with pytest.raises(click.ClickException) as excinfo:
            core_cli.get_command(None, "serve")

        assert "ai-parrot-integrations[agentd]" in str(excinfo.value)

    def test_inner_import_error_reports_real_cause(self, monkeypatch):
        """An ImportError raised INSIDE an installed agentd must not be
        blamed on the (unrelated) optional extra -- that message sent a user
        chasing an already-installed package while the real failure was a
        missing transitive dependency.
        """
        from parrot.cli import cli as core_cli

        def _raise_inner(name, *args, **kwargs):
            raise ImportError(
                "cannot import name 'genai' from 'google' (unknown location)",
                name="google",
            )

        monkeypatch.setattr(importlib, "import_module", _raise_inner)

        with pytest.raises(click.ClickException) as excinfo:
            core_cli.get_command(None, "serve")

        message = str(excinfo.value)
        assert "ai-parrot-integrations[agentd]" not in message
        assert "genai" in message
        assert "parrot.integrations.agentd.cli" in message

    def test_parent_package_absence_names_extra(self, monkeypatch):
        """ModuleNotFoundError on a PARENT package still names the extra."""
        from parrot.cli import cli as core_cli

        def _raise_parent(name, *args, **kwargs):
            raise ModuleNotFoundError(
                "No module named 'parrot.integrations.agentd'",
                name="parrot.integrations.agentd",
            )

        monkeypatch.setattr(importlib, "import_module", _raise_parent)

        with pytest.raises(click.ClickException) as excinfo:
            core_cli.get_command(None, "serve")

        assert "ai-parrot-integrations[agentd]" in str(excinfo.value)

    def test_lazy_keys_registered(self):
        from parrot.cli import cli as core_cli

        for key in ("serve", "attach", "ask", "status", "install-service", "mcp-serve"):
            assert core_cli._lazy_commands.get(key) == "parrot.integrations.agentd.cli"
