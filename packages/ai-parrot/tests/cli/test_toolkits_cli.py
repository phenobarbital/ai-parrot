"""`parrot toolkits` CLI (FEAT-570, TASK-3376)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import click
import pytest
from click.testing import CliRunner

from parrot.cli import cli
from parrot.mcp import toolkit_install


def _linked_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Create primary and linked-worktree metadata without invoking Git."""
    primary = tmp_path / "primary"
    admin = primary / ".git" / "worktrees" / "linked"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / ".git").write_text(f"gitdir: {admin}\n", encoding="utf-8")
    return primary, linked


def _snapshot_files(root: Path) -> dict[str, bytes]:
    """Return a byte-exact snapshot of every file below ``root``."""
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


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


def test_no_tty_without_names_exits_2(tmp_path, monkeypatch):
    """AC2 — CI must fail (exit 2) with instructions, never hang on a picker."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        result = CliRunner().invoke(cli, ["toolkits", "install"])
        assert result.exit_code == 2
        assert "non-interactive" in result.output.lower()


def test_install_unknown_name_reports_cleanly(tmp_path):
    """An unknown name exits 1 with the name in the message and writes nothing (AC8)."""
    with CliRunner().isolated_filesystem(temp_dir=tmp_path) as cwd:
        result = CliRunner().invoke(cli, ["toolkits", "install", "not-a-template", "--yes"])
        assert result.exit_code == 1
        assert "not-a-template" in result.output
        assert not (Path(cwd) / ".parrot" / "mcp-toolkits.yaml").exists()


def test_google_host_warns_user_global(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec §8 Q1 — installing into `google` prints a user-global blast-radius warning."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        result = CliRunner().invoke(cli, ["toolkits", "install", "memory", "--host", "google", "--yes"])
        assert result.exit_code == 0
        assert "user-global" in result.output.lower()
        assert "every project" in result.output.lower()
        assert str(tmp_path / ".gemini" / "config" / "mcp_config.json") in result.output


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


def test_toolkits_install_offers_self_add(tmp_path, monkeypatch):
    """Spec §4 — a missing distribution prints the `parrot self add <name>` hint after install."""
    monkeypatch.setattr("parrot.mcp.toolkit_install.dist_available", lambda _dists: False)
    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        result = CliRunner().invoke(cli, ["toolkits", "install", "scraping", "--yes"])
        assert result.exit_code == 0, result.output
        assert "parrot self add scraping" in result.output


def test_list_hints_self_add_for_missing_dist(tmp_path, monkeypatch):
    monkeypatch.setattr("parrot.mcp.toolkit_install.dist_available", lambda _dists: False)
    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        result = CliRunner().invoke(cli, ["toolkits", "list"])
        assert result.exit_code == 0, result.output
        assert "querysource: missing distribution" in result.output
        assert "parrot self add querysource" in result.output


def test_no_hint_when_dist_available(tmp_path, monkeypatch):
    monkeypatch.setattr("parrot.mcp.toolkit_install.dist_available", lambda _dists: True)
    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        result = CliRunner().invoke(cli, ["toolkits", "install", "memory", "--yes"])
        assert result.exit_code == 0, result.output
        assert "parrot self add" not in result.output


def test_inventory_rows_carry_install_metadata(tmp_path):
    from parrot.mcp.toolkit_install import inventory

    rows = {row.name: row for row in inventory(tmp_path, hosts=[])}
    assert rows["scraping"].requires_pip == ("ai-parrot-tools[scraping]",)  # TASK-4077 values
    assert rows["querysource"].requires_env == ("PG_USER", "PG_PWD")


@pytest.mark.parametrize("verb", ["install", "uninstall", "enable", "disable"])
def test_toolkits_cli_worktree_path_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verb: str) -> None:
    """All write verbs reject implicit worktrees before prompting and accept validated --path."""
    primary, linked = _linked_worktree(tmp_path)
    prompt = Mock(return_value=True)
    monkeypatch.setattr(click, "confirm", prompt)
    monkeypatch.chdir(linked)

    before_refusal = _snapshot_files(tmp_path)
    refused = CliRunner().invoke(cli, ["toolkits", verb, "memory", "--host", "claude"])
    assert refused.exit_code == 1
    assert str(primary.resolve()) in refused.output
    assert "--path" in refused.output
    assert prompt.call_count == 0
    assert _snapshot_files(tmp_path) == before_refusal

    accepted = CliRunner().invoke(
        cli,
        ["toolkits", verb, "memory", "--host", "claude", "--yes", "--path", str(linked)],
    )
    assert accepted.exit_code == 0, accepted.output

    before_invalid_path = _snapshot_files(tmp_path)
    invalid = CliRunner().invoke(
        cli,
        ["toolkits", verb, "memory", "--host", "claude", "--yes", "--path", str(tmp_path / "missing")],
    )
    assert invalid.exit_code == 2
    assert "does not exist" in invalid.output
    assert _snapshot_files(tmp_path) == before_invalid_path

    for read_verb in ("list", "status"):
        read_result = CliRunner().invoke(cli, ["toolkits", read_verb, "--host", "claude"])
        assert read_result.exit_code == 0, read_result.output


@pytest.mark.parametrize("verb,service_name", [("install", "install_toolkits"), ("enable", "set_toolkits_enabled")])
@pytest.mark.parametrize(
    "flags,expected",
    [
        pytest.param((), None, id="default"),
        pytest.param(("--portable",), True),
        pytest.param(("--no-portable",), False),
    ],
)
def test_toolkits_cli_portable_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verb: str,
    service_name: str,
    flags: tuple[str, ...],
    expected: bool | None,
) -> None:
    """Install and enable pass None, True and False exactly to their services."""
    original = getattr(toolkit_install, service_name)
    service = Mock(wraps=original)
    monkeypatch.setattr(toolkit_install, service_name, service)

    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        result = CliRunner().invoke(
            cli,
            ["toolkits", verb, "memory", "--host", "claude", "--yes", *flags],
        )

    assert result.exit_code == 0, result.output
    assert service.call_count == 1
    assert service.call_args.kwargs["portable"] is expected


def test_toolkits_cli_resolves_repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A command launched in a subdirectory writes repository-scoped files at the checkout root."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    subdirectory = repo / "nested" / "directory"
    subdirectory.mkdir(parents=True)
    monkeypatch.chdir(subdirectory)

    result = CliRunner().invoke(
        cli,
        ["toolkits", "install", "memory", "--host", "claude", "--yes", "--portable"],
    )

    assert result.exit_code == 0, result.output
    assert (repo / ".parrot" / "mcp-toolkits.yaml").is_file()
    assert (repo / ".mcp.json").is_file()
    assert not (subdirectory / ".parrot").exists()
