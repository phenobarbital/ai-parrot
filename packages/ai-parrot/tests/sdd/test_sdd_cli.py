"""CLI tests for ``parrot sdd`` (FEAT-633 M6)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
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


@pytest.fixture
def gemini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the user-global Gemini MCP file while stale cleanup scans Google."""
    path = tmp_path / "gemini_home" / "mcp_config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setattr("parrot.knowledge.wiki.google.assets.default_mcp_config_path", lambda: path)
    return path


def test_cli_uninstall_stalled_claude_by_default(tmp_path: Path, gemini: Path) -> None:
    """Stalled cleanup defaults to the claude host, like a plain uninstall; other hosts need --host."""
    runner = CliRunner()
    for host in ("claude", "codex", "google"):
        result = runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--host", host])
        assert result.exit_code == 0, result.output
    claude_only = tmp_path / ".claude/commands/sdd-old.md"
    other_hosts = (
        tmp_path / ".agents/skills/sdd-old/SKILL.md",
        tmp_path / ".agent/agents/sdd-worker/agent.md",
    )
    for path in (claude_only, *other_hosts):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale\n", encoding="utf-8")

    result = runner.invoke(cli, ["sdd", "uninstall", "--path", str(tmp_path), "--stalled"])

    assert result.exit_code == 0, result.output
    assert not claude_only.exists()
    assert all(path.exists() for path in other_hosts)
    assert (tmp_path / ".claude/commands/sdd-status.md").is_file()

    args = ["sdd", "uninstall", "--path", str(tmp_path), "--stalled", "--host", "codex", "--host", "google"]
    result = runner.invoke(cli, args)

    assert result.exit_code == 0, result.output
    assert all(not path.exists() for path in other_hosts)


def test_cli_uninstall_stalled_rejects_keep_edits(tmp_path: Path, gemini: Path) -> None:
    """Stalled cleanup cannot use the regular uninstall preservation flag."""
    result = CliRunner().invoke(cli, ["sdd", "uninstall", "--path", str(tmp_path), "--stalled", "--keep-edits"])
    assert result.exit_code == 2


def test_cli_keep_requires_stalled(tmp_path: Path, gemini: Path) -> None:
    """The stale-only keep glob is rejected by a normal uninstall."""
    result = CliRunner().invoke(cli, ["sdd", "uninstall", "--path", str(tmp_path), "--keep", "sdd-old*"])
    assert result.exit_code == 2


def test_cli_stale_alias(tmp_path: Path, gemini: Path) -> None:
    """The legacy-spelling flag is an exact alias of the primary flag."""
    runner = CliRunner()
    stale = runner.invoke(cli, ["sdd", "uninstall", "--path", str(tmp_path), "--stale", "--dry-run"])
    stalled = runner.invoke(cli, ["sdd", "uninstall", "--path", str(tmp_path), "--stalled", "--dry-run"])
    assert stale.exit_code == stalled.exit_code == 0
    assert stale.output == stalled.output


def test_cli_stalled_cleans_mcp_entries(tmp_path: Path, gemini: Path) -> None:
    """Stalled cleanup removes parrot toolkit entries but preserves foreign entries."""
    mcp_path = tmp_path / ".mcp.json"
    mcp_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "parrot-oldkit": {"command": "parrot", "args": ["mcp-local", "oldkit"]},
                    "wikitoolkit": {"command": "wikitoolkit", "args": []},
                }
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["sdd", "uninstall", "--path", str(tmp_path), "--stalled"])

    assert result.exit_code == 0, result.output
    servers = json.loads(mcp_path.read_text(encoding="utf-8"))["mcpServers"]
    assert "parrot-oldkit" not in servers
    assert "wikitoolkit" in servers


def test_cli_status_prints_stale(tmp_path: Path, gemini: Path) -> None:
    """Human-readable status includes stale SDD and MCP summaries."""
    stale_path = tmp_path / ".claude/commands/sdd-old.md"
    stale_path.parent.mkdir(parents=True)
    stale_path.write_text("stale\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["sdd", "status", "--path", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "stale: " in result.output
    assert "stale mcp: " in result.output


def test_portable_flag(tmp_path: Path) -> None:
    """C25: --portable writes the bare guard-hook line."""
    result = CliRunner().invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--portable"])
    assert result.exit_code == 0, result.output
    assert "parrot sdd worktree guard --hook || exit 2" in (tmp_path / ".claude/agents/sdd-worker.md").read_text()


def test_sdd_cli_refuses_linked_worktree_and_resolves_subdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Write verbs refuse linked checkouts while status and explicit targets remain available."""
    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    subprocess.run(["git", "init", "-q", "-b", "main", str(primary)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(primary),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-qm",
            "init",
            "--allow-empty",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(primary), "worktree", "add", "-q", str(linked)], check=True)
    calls: list[Path] = []
    monkeypatch.setattr(
        "parrot.sdd.cli.install_sdd_integration", lambda root, *args, **kwargs: calls.append(root) or []
    )
    monkeypatch.chdir(linked)
    runner = CliRunner()

    for command in (["install", "--dry-run"], ["uninstall", "--dry-run"]):
        result = runner.invoke(sdd, command)
        assert result.exit_code == 1 and "linked worktree" in result.output
    assert calls == []
    assert runner.invoke(sdd, ["status", "--json"]).exit_code == 0

    result = runner.invoke(sdd, ["install", "--path", str(linked), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert calls == [linked.resolve()]

    nested = primary / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    result = runner.invoke(sdd, ["install", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert calls[-1] == primary.resolve()


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


def test_worktree_sync_base_help() -> None:
    """The installed CLI dispatches sync-base help to its helper."""
    result = CliRunner().invoke(cli, ["sdd", "worktree", "sync-base", "--help"])

    assert result.exit_code == 0, result.output
    assert "--cherry-pick" in result.output
    assert "--dry-run" in result.output


def test_worktree_sync_base_refusal_exit_and_json(tmp_path: Path) -> None:
    """A missing target retains the helper refusal code and JSON result contract."""
    target = tmp_path / "missing-worktree"

    result = CliRunner().invoke(cli, ["sdd", "worktree", "sync-base", str(target), "--json"])

    assert result.exit_code == 2, result.output
    report = json.loads(result.output)
    assert report["worktree"] == str(target)
    assert report["status"] == "refused"
    assert report["exit_code"] == 2
    assert "target must resolve to one worktree" in report["message"]


def test_verb_propagates_helper_exit_code() -> None:
    """A helper that argparse-rejects exits 2 - the code must pass through, not be flattened to 1."""
    result = CliRunner().invoke(cli, ["sdd", "ids", "reserve", "--kind", "bogus"])
    assert result.exit_code == 2
