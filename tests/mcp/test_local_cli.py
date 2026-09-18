"""Unit tests for the `parrot mcp-local` CLI command.

FEAT-485: lazy registration, --list, resolution failures, override
passthrough to `create_toolkit_mcp_server`, and the serve path against
the stub toolkit.
"""

from pathlib import Path
from unittest.mock import MagicMock

from click.testing import CliRunner
from parrot.cli import cli


def _write_memory_config(tmp_path: Path) -> None:
    """Write an explicit `memory:` section — nothing resolves implicitly (FEAT-570)."""
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir(exist_ok=True)
    (parrot_dir / "mcp-toolkits.yaml").write_text(
        "toolkits:\n  memory:\n    class: parrot.tools.working_memory.tool.WorkingMemoryToolkit\n    kwargs: {}\n"
    )


def test_list_shows_nothing_on_bare_repo(monkeypatch, tmp_path):
    """`--list` on a bare repo (no config file) lists nothing (FEAT-570)."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["mcp-local", "--list"])

    assert result.exit_code == 0, result.output
    for name in ("scraping", "browsing", "memory"):
        assert name not in result.output


def test_list_shows_declared_section(monkeypatch, tmp_path):
    """`--list` prints a section declared in `.parrot/mcp-toolkits.yaml`."""
    _write_memory_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["mcp-local", "--list"])

    assert result.exit_code == 0, result.output
    assert "memory" in result.output
    assert "enabled" in result.output


def test_list_does_not_import_toolkit_classes(monkeypatch, tmp_path):
    """`--list` never resolves/imports the toolkit classes it names."""
    import sys

    monkeypatch.chdir(tmp_path)
    sys.modules.pop("parrot_tools.scraping.toolkit", None)
    sys.modules.pop("parrot.tools.working_memory.tool", None)

    runner = CliRunner()
    result = runner.invoke(cli, ["mcp-local", "--list"])

    assert result.exit_code == 0, result.output
    assert "parrot_tools.scraping.toolkit" not in sys.modules
    assert "parrot.tools.working_memory.tool" not in sys.modules


def test_unknown_name_nonzero(monkeypatch, tmp_path):
    """Unknown name exits non-zero; stderr lists resolvable names."""
    _write_memory_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["mcp-local", "nonsense"])

    assert result.exit_code != 0
    assert "Unknown toolkit name" in result.output
    assert "memory" in result.output  # resolvable names listed


def test_unknown_name_names_the_install_command(monkeypatch, tmp_path):
    """The hard cut's only migration aid (FEAT-570)."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["mcp-local", "browsing"])

    assert result.exit_code != 0
    assert "parrot toolkits install browsing" in result.output


def test_missing_distribution_gets_a_different_message(monkeypatch, tmp_path):
    """A configured toolkit whose distribution is missing is NOT told to
    `parrot toolkits install` — that command cannot fix a missing extra."""
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir()
    (parrot_dir / "mcp-toolkits.yaml").write_text(
        "toolkits:\n  ghost:\n    class: nonexistent_package.module.GhostToolkit\n    kwargs: {}\n"
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["mcp-local", "ghost"])

    assert result.exit_code != 0
    assert "Cannot import toolkit" in result.output
    assert "parrot toolkits install ghost" not in result.output


def test_list_mentions_no_builtins(monkeypatch, tmp_path):
    """`--list`'s output and help text contain no "built-in" language."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["mcp-local", "--list"])
    assert result.exit_code == 0, result.output
    assert "built-in" not in result.output.lower()

    help_result = runner.invoke(cli, ["mcp-local", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "built-in" not in help_result.output.lower()


def test_missing_name_without_list_nonzero(monkeypatch, tmp_path):
    """NAME is required unless --list is given."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["mcp-local"])

    assert result.exit_code != 0


def test_lazy_registration():
    """`mcp-local` is registered against the local_cli module path."""
    from parrot.cli import cli as group

    assert group._lazy_commands["mcp-local"] == "parrot.mcp.local_cli"


def test_lazy_command_resolves():
    """`LazyGroup.get_command` resolves `mcp-local` to the click command."""
    from parrot.cli import cli as group

    cmd = group.get_command(None, "mcp-local")

    assert cmd is not None
    assert cmd.name == "mcp-local"


def test_overrides_passed(monkeypatch, tmp_path):
    """--include/--exclude/--config reach create_toolkit_mcp_server."""
    captured = {}

    def fake_factory(name, root, **overrides):
        captured["name"] = name
        captured["root"] = Path(root)
        captured["overrides"] = overrides
        return MagicMock()

    monkeypatch.setattr("parrot.mcp.toolkit_server.create_toolkit_mcp_server", fake_factory)
    monkeypatch.setattr(
        "parrot.mcp.local_cli.asyncio.run",
        lambda coro: getattr(coro, "close", lambda: None)(),
    )
    _write_memory_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    custom_cfg = tmp_path / "custom.yaml"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "mcp-local",
            "memory",
            "--config",
            str(custom_cfg),
            "--include",
            "a",
            "--include",
            "b",
            "--exclude",
            "c",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["name"] == "memory"
    assert captured["root"].resolve() == tmp_path.resolve()
    assert captured["overrides"]["include"] == ["a", "b"]
    assert captured["overrides"]["exclude"] == ["c"]
    assert captured["overrides"]["config_path"] == custom_cfg


def test_serve_path_stub_toolkit(monkeypatch, tmp_path):
    """Serve path resolves the stub toolkit and drives server.start()."""
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir()
    (parrot_dir / "mcp-toolkits.yaml").write_text(
        "toolkits:\n  stub:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    kwargs: {}\n"
    )
    monkeypatch.chdir(tmp_path)

    started = {}

    async def fake_start(self):
        started["called"] = True

    monkeypatch.setattr("parrot.mcp.local_server.StdioMCPServer.start", fake_start)

    runner = CliRunner()
    result = runner.invoke(cli, ["mcp-local", "stub"])

    assert result.exit_code == 0, result.output
    assert started.get("called") is True


def test_keyboard_interrupt_clean_exit(monkeypatch, tmp_path):
    """A KeyboardInterrupt during serve exits cleanly with status 0."""
    _write_memory_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    def fake_factory(name, root, **overrides):
        return MagicMock()

    def raise_kb(coro):
        getattr(coro, "close", lambda: None)()
        raise KeyboardInterrupt()

    monkeypatch.setattr("parrot.mcp.toolkit_server.create_toolkit_mcp_server", fake_factory)
    monkeypatch.setattr("parrot.mcp.local_cli.asyncio.run", raise_kb)

    runner = CliRunner()
    result = runner.invoke(cli, ["mcp-local", "memory"])

    assert result.exit_code == 0, result.output
