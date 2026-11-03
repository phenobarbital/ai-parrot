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


def test_install_overwrites_edits_by_default_keep_edits_skips(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path)])
    target = next((tmp_path / ".claude/commands").glob("*.md"))
    target.write_text("user edit\n")
    kept = runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--keep-edits"])
    assert kept.exit_code == 0 and target.read_text() == "user edit\n"
    replaced = runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path)])
    assert replaced.exit_code == 0 and target.read_text() != "user edit\n"
    legacy = runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--force"])  # deprecated no-op
    assert legacy.exit_code == 0
    both = runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--force", "--keep-edits"])
    assert both.exit_code != 0


def test_uninstall_removes_unrecorded_assets_unless_keep_edits(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path)])
    (tmp_path / "sdd/.sdd-installed.json").unlink()
    target = next((tmp_path / ".claude/commands").glob("*.md"))
    assert runner.invoke(cli, ["sdd", "uninstall", "--path", str(tmp_path), "--keep-edits"]).exit_code == 0
    assert target.exists()
    assert runner.invoke(cli, ["sdd", "uninstall", "--path", str(tmp_path)]).exit_code == 0
    assert not target.exists()


def test_portable_flag(tmp_path: Path) -> None:
    """C25: --portable writes the bare guard-hook line."""
    result = CliRunner().invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--portable"])
    assert result.exit_code == 0, result.output
    assert (
        "parrot sdd worktree guard --hook || exit 2"
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


def test_sdd_cli_mounts_every_helper() -> None:
    """C30 item 3: mounted modules == packaged modules with main() minus _UNMOUNTED; every leaf --help exits 0."""
    import importlib
    import pkgutil

    import parrot.sdd.scripts as pkg
    from parrot.sdd.cli import _UNMOUNTED, VERBS, mounted_modules

    with_main = {
        m.name
        for m in pkgutil.iter_modules(pkg.__path__)
        if not m.ispkg and hasattr(importlib.import_module(f"parrot.sdd.scripts.{m.name}"), "main")
    }
    assert mounted_modules() == with_main - _UNMOUNTED
    for noun, verbs in VERBS.items():
        for verb in verbs:
            result = CliRunner().invoke(cli, ["sdd", noun, verb, "--help"])
            assert result.exit_code == 0, (noun, verb, result.output)
    assert CliRunner().invoke(cli, ["sdd", "run", "reserve_ids", "--help"]).exit_code == 2  # no alias (C30)


def test_verb_propagates_helper_exit_code() -> None:
    """A helper that argparse-rejects exits 2 - the code must pass through, not be flattened to 1."""
    result = CliRunner().invoke(cli, ["sdd", "ids", "reserve", "--kind", "bogus"])
    assert result.exit_code == 2
