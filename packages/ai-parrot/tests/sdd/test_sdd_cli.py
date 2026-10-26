"""CLI tests for ``parrot sdd`` (FEAT-633 M6)."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from parrot.cli import cli
from parrot.sdd.cli import sdd


def test_lazy_registration() -> None:
    assert cli._lazy_commands["sdd"] == "parrot.sdd.cli"
    assert cli.get_command(None, "sdd") is sdd


def test_install_status_uninstall_roundtrip(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--host", "claude", "--host", "codex"])
    assert result.exit_code == 0, result.output
    status = runner.invoke(cli, ["sdd", "status", "--path", str(tmp_path), "--json"])
    report = json.loads(status.output)
    assert report["hosts"]["claude"]["missing"] == [] and report["hosts"]["codex"]["missing"] == []
    result = runner.invoke(cli, ["sdd", "uninstall", "--path", str(tmp_path), "--host", "claude", "--host", "codex"])
    assert result.exit_code == 0, result.output


def test_unknown_host_is_a_usage_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--host", "vim"])
    assert result.exit_code == 2


def test_force_flag_overwrites(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path)])
    target = next((tmp_path / ".claude/commands").glob("*.md"))
    target.write_text("user edit\n")
    skipped = runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path)])
    assert skipped.exit_code == 0 and target.read_text() == "user edit\n"
    forced = runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--force"])
    assert forced.exit_code == 0 and target.read_text() != "user edit\n"


def test_portable_flag(tmp_path: Path) -> None:
    """C25: --portable writes the bare guard-hook line."""
    result = CliRunner().invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--portable"])
    assert result.exit_code == 0, result.output
    assert (
        "parrot sdd run worktree_environment --hook || exit 2"
        in (tmp_path / ".claude/agents/sdd-worker.md").read_text()
    )


def test_status_human_output(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--host", "codex"])
    result = runner.invoke(cli, ["sdd", "status", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (
        "codex:" in result.output
        and "0 missing" in result.output
        and "seed sdd/CONVENTIONS.md: seed-present" in result.output
    )


def test_malformed_config_exits_1(tmp_path: Path) -> None:
    (tmp_path / "sdd").mkdir()
    (tmp_path / "sdd/config.json").write_text("{nope")
    result = CliRunner().invoke(cli, ["sdd", "install", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_dry_run_flag_prints_plan_and_writes_nothing(tmp_path: Path) -> None:
    """C5 at the CLI layer."""
    result = CliRunner().invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "plan: write" in result.output
    assert not any(tmp_path.iterdir())


def test_run_dispatches_helper_help() -> None:
    """Q1: `parrot sdd run reserve_ids --help` reaches the helper's argparse and exits 0."""
    result = CliRunner().invoke(cli, ["sdd", "run", "reserve_ids", "--help"])
    assert result.exit_code == 0, result.output
    assert "--kind" in result.output and "--base-branch" in result.output  # reserve_ids' own argparse help


def test_run_unknown_helper_lists_available() -> None:
    result = CliRunner().invoke(cli, ["sdd", "run", "nope"])
    assert result.exit_code == 1
    assert "unknown helper" in result.output and "reserve_ids" in result.output and "sdd_meta" in result.output


def test_run_sdd_meta_is_dispatchable() -> None:
    """`sdd_meta` is a real helper after TASK-4299 (shipped markdown uses `parrot sdd run sdd_meta parse <spec>`)."""
    result = CliRunner().invoke(cli, ["sdd", "run", "sdd_meta", "--help"])
    assert result.exit_code == 0, result.output


def test_run_propagates_helper_exit_code() -> None:
    """A helper that argparse-rejects exits 2 — the code must pass through, not be flattened to 1."""
    result = CliRunner().invoke(cli, ["sdd", "run", "reserve_ids", "--kind", "bogus"])
    assert result.exit_code == 2
