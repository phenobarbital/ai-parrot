"""`parrot toolkits` CLI (FEAT-570, TASK-3376)."""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from parrot.cli import cli


def test_toolkits_is_registered():
    result = CliRunner().invoke(cli, ["toolkits", "--help"])
    assert result.exit_code == 0
    for sub in ("list", "status", "install", "uninstall", "enable", "disable"):
        assert sub in result.output


def test_list_on_empty_repo(tmp_path):
    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        result = CliRunner().invoke(cli, ["toolkits", "list"])
        assert result.exit_code == 0
        assert "querysource" in result.output
        assert "wikitoolkit" not in result.output


def test_install_without_names_no_tty_exits_nonzero(tmp_path, monkeypatch):
    """AC2 — CI must fail with instructions, never hang on a picker."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        result = CliRunner().invoke(cli, ["toolkits", "install"])
        assert result.exit_code != 0
        assert "non-interactive" in result.output.lower()


def test_install_unknown_name_reports_cleanly(tmp_path):
    """An unknown name exits 1 with the name in the message and writes nothing (AC8)."""
    with CliRunner().isolated_filesystem(temp_dir=tmp_path) as cwd:
        result = CliRunner().invoke(cli, ["toolkits", "install", "not-a-template", "--yes"])
        assert result.exit_code == 1
        assert "not-a-template" in result.output
        assert not (Path(cwd) / ".parrot" / "mcp-toolkits.yaml").exists()


def test_google_host_warns_user_global(tmp_path, monkeypatch):
    """Spec §8 Q1 — installing into `google` prints a user-global blast-radius warning."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        result = CliRunner().invoke(cli, ["toolkits", "install", "memory", "--host", "google", "--yes"])
        assert result.exit_code == 0
        assert "user-global" in result.output.lower()
        assert "every project" in result.output.lower()


def test_status_with_only_claude_config_reports_claude_present_others_absent(tmp_path, monkeypatch):
    """`status` with no `--host` reports on every host kind, not only detected ones."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with CliRunner().isolated_filesystem(temp_dir=tmp_path) as cwd:
        (Path(cwd) / ".mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
        result = CliRunner().invoke(cli, ["toolkits", "status"])
        assert result.exit_code == 0
        lines = result.output.splitlines()

        def _state_for(host_name: str) -> str:
            in_block = False
            for line in lines:
                if line.startswith(f"{host_name} "):
                    in_block = True
                    continue
                if in_block:
                    if line.startswith("  "):
                        return line
                    break
            return ""

        assert "present" in _state_for("claude")
        assert "absent" in _state_for("codex")
        assert "absent" in _state_for("google")
