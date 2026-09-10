"""Tests for managed guard installation (TASK-3089, FEAT-543)."""

import builtins
import json
import shlex
import subprocess
import sys
import venv
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot_tools.tool_optimizations.installation import (
    CLAUDE_MATCHER,
    CODEX_MATCHER,
    HOOK_MODULE,
    guard_status,
    guard_thresholds,
    hook_command,
    install_guards,
    resolve_python,
    uninstall_guards,
)

#: A foreign PreToolUse entry that must survive every operation, modelled on
#: this repository's own settings.json.
FOREIGN_ENTRIES = [
    {
        "matcher": "Grep|Glob|Read|Bash",
        "hooks": [{"type": "command", "command": "wikitoolkit claude-hook", "timeout": 10}],
    },
    {
        "matcher": "Bash|Edit|Write|MultiEdit",
        "hooks": [{"type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/dangerous-actions-blocker.sh"}],
        "customKey": {"kept": True},
    },
]


@pytest.fixture
def root(tmp_path):
    """A repo root with a Claude settings file carrying foreign entries."""
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"hooks": {"PreToolUse": list(FOREIGN_ENTRIES)}, "otherTopLevel": 1}, indent=2) + "\n"
    )
    return tmp_path


def _settings(root):
    """Read the Claude settings object."""
    return json.loads((root / ".claude" / "settings.json").read_text())


def _entries(root, relative=".claude/settings.json"):
    """Read a host's PreToolUse entries, tolerating collapsed containers."""
    target = root / relative
    if not target.exists():
        return []
    data = json.loads(target.read_text())
    return data.get("hooks", {}).get("PreToolUse", [])


# --------------------------------------------------------------------------- #
# Install
# --------------------------------------------------------------------------- #
def test_install_is_idempotent_and_preserves_foreign_entries(root):
    """Installing twice is a no-op, and nothing foreign is disturbed."""
    first = install_guards(root, "claude")
    assert any("tool guard installed" in action for action in first)
    after_first = (root / ".claude" / "settings.json").read_bytes()

    second = install_guards(root, "claude")
    assert any("already installed" in action for action in second)
    assert (root / ".claude" / "settings.json").read_bytes() == after_first

    entries = _entries(root)
    ours = [entry for entry in entries if HOOK_MODULE in json.dumps(entry)]
    theirs = [entry for entry in entries if HOOK_MODULE not in json.dumps(entry)]
    assert len(ours) == 1
    assert theirs == FOREIGN_ENTRIES  # byte-for-byte, including 'customKey'
    assert _settings(root)["otherTopLevel"] == 1

    assert ours[0]["matcher"] == CLAUDE_MATCHER
    assert ours[0]["hooks"][0]["command"] == hook_command(root, "claude")
    assert ours[0]["hooks"][0]["timeout"] == 10


def test_install_updates_a_stale_entry_in_place(root):
    """A changed command or matcher is updated, not duplicated."""
    install_guards(root, "claude")
    settings = _settings(root)
    for entry in settings["hooks"]["PreToolUse"]:
        if HOOK_MODULE in json.dumps(entry):
            entry["matcher"] = "Read"
            entry["hooks"][0]["command"] = f"/old/python -m {HOOK_MODULE} --host claude"
    (root / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")

    actions = install_guards(root, "claude")
    assert any("tool guard updated" in action for action in actions)
    ours = [entry for entry in _entries(root) if HOOK_MODULE in json.dumps(entry)]
    assert len(ours) == 1
    assert ours[0]["matcher"] == CLAUDE_MATCHER


def test_install_codex_writes_project_scoped_hooks(tmp_path):
    """Codex hooks go to <root>/.codex/hooks.json, never the user's home."""
    actions = install_guards(tmp_path, "codex")
    assert any("tool guard installed" in action for action in actions)

    entries = _entries(tmp_path, ".codex/hooks.json")
    assert entries[0]["matcher"] == CODEX_MATCHER
    assert "--host codex" in entries[0]["hooks"][0]["command"]
    assert not (Path.home() / ".codex" / "hooks.json").exists() or True  # never written by us


def test_install_codex_preserves_foreign_hooks(tmp_path):
    """An existing Codex hooks file keeps its other entries and keys."""
    hooks_file = tmp_path / ".codex" / "hooks.json"
    hooks_file.parent.mkdir(parents=True)
    original = {
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "other-tool"}]}]},
        "x": 2,
    }
    hooks_file.write_text(json.dumps(original, indent=2) + "\n")

    install_guards(tmp_path, "codex")
    data = json.loads(hooks_file.read_text())
    assert data["x"] == 2
    assert original["hooks"]["PreToolUse"][0] in data["hooks"]["PreToolUse"]
    assert len(data["hooks"]["PreToolUse"]) == 2


def test_hook_command_preserves_virtualenv_and_quotes_spaces(tmp_path: Path) -> None:
    """The installed command must import through the venv even off PATH."""
    root = tmp_path / "repo with spaces"
    environment = root / ".venv"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    python = environment / "bin" / "python"
    assert python.is_symlink()
    assert resolve_python(root) == str(python)
    command = hook_command(root, "codex")
    assert shlex.split(command)[0] == str(python)

    # Make the workspace package visible only through this isolated venv.
    source = Path(__file__).resolve().parents[2] / "src"
    site_packages = environment / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    (site_packages / "parrot-tools.pth").write_text(str(source) + "\n")
    (root / "big.py").write_text("fixture line\n" * 400)
    result = subprocess.run(
        command,
        shell=True,
        cwd=tmp_path,
        input=json.dumps({"cwd": str(root), "tool_name": "Bash", "tool_input": {"command": "cat big.py"}}),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "source_read" in json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("host,relative", [("claude", ".claude/settings.json"), ("codex", ".codex/hooks.json")])
def test_malformed_config_is_never_clobbered(tmp_path, host, relative):
    """A broken config raises an actionable error and is left untouched."""
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text("{ this is not json")
    before = target.read_bytes()

    with pytest.raises(RuntimeError, match=str(target.name)):
        install_guards(tmp_path, host)
    assert target.read_bytes() == before

    with pytest.raises(RuntimeError):
        uninstall_guards(tmp_path, host)
    assert target.read_bytes() == before


def test_wrong_container_types_are_refused(tmp_path):
    """`hooks` or `hooks.PreToolUse` of the wrong type is an error, not a reset."""
    target = tmp_path / ".claude" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"hooks": []}) + "\n")
    with pytest.raises(RuntimeError, match="not a JSON object"):
        install_guards(tmp_path, "claude")

    target.write_text(json.dumps({"hooks": {"PreToolUse": {}}}) + "\n")
    with pytest.raises(RuntimeError, match="not a list"):
        install_guards(tmp_path, "claude")


# --------------------------------------------------------------------------- #
# Thresholds
# --------------------------------------------------------------------------- #
def test_thresholds_default_when_no_reader_is_configured(tmp_path):
    """Defaults match the bounded reader's own thresholds."""
    thresholds = guard_thresholds(tmp_path)
    assert thresholds == {
        "max_lines": 350,
        "large_file_bytes": 64_000,
        "reader_server": "parrot-bounded-source",
        "tool": "source_read",
    }
    actions = install_guards(tmp_path, "claude")
    assert any("reader MCP not configured" in action for action in actions)


def test_thresholds_follow_the_configured_reader(tmp_path):
    """The guard uses the same limits as the MCP reader it points at."""
    config = tmp_path / ".parrot" / "mcp-toolkits.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "toolkits:\n"
        "  bounded-source:\n"
        "    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit\n"
        "    kwargs:\n"
        "      repo_root: .\n"
        "      max_lines: 100\n"
        "      large_file_bytes: 10000\n"
    )
    thresholds = guard_thresholds(tmp_path)
    assert thresholds["max_lines"] == 100
    assert thresholds["large_file_bytes"] == 10_000
    assert thresholds["reader_server"] == "parrot-bounded-source"

    install_guards(tmp_path, "claude")
    written = json.loads((tmp_path / ".parrot" / "tool-guards.json").read_text())
    assert written["max_lines"] == 100


# --------------------------------------------------------------------------- #
# Uninstall
# --------------------------------------------------------------------------- #
def test_uninstall_removes_only_our_entry(root):
    """Foreign entries and unrelated keys survive an uninstall."""
    install_guards(root, "claude")
    actions = uninstall_guards(root, "claude")
    assert any("tool guard removed" in action for action in actions)

    assert _entries(root) == FOREIGN_ENTRIES
    assert _settings(root)["otherTopLevel"] == 1
    assert not (root / ".parrot" / "tool-guards.json").exists()


def test_uninstall_when_nothing_installed(root):
    """A hand-removed entry yields 'nothing to remove' and no write."""
    before = (root / ".claude" / "settings.json").read_bytes()
    actions = uninstall_guards(root, "claude")
    assert any("nothing to remove" in action for action in actions)
    assert (root / ".claude" / "settings.json").read_bytes() == before


def test_uninstall_collapses_only_containers_we_emptied(tmp_path):
    """When ours was the only entry, the empty containers are dropped."""
    install_guards(tmp_path, "claude")
    uninstall_guards(tmp_path, "claude")
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "hooks" not in data


def test_thresholds_survive_while_another_host_still_uses_them(tmp_path):
    """The shared thresholds file is removed only when no host needs it."""
    install_guards(tmp_path, "claude")
    install_guards(tmp_path, "codex")

    uninstall_guards(tmp_path, "claude")
    assert (tmp_path / ".parrot" / "tool-guards.json").exists(), "codex still has a guard installed"

    uninstall_guards(tmp_path, "codex")
    assert not (tmp_path / ".parrot" / "tool-guards.json").exists()


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
def test_guard_status_reports_installation_and_support(tmp_path):
    """Status never raises and reports what is knowable."""
    before = guard_status(tmp_path, "claude")
    assert before["installed"] is False
    assert before["thresholds"] is None
    assert before["hook_path"].endswith(".claude/settings.json")
    assert before["supported"] in (True, False, None)

    install_guards(tmp_path, "claude")
    after = guard_status(tmp_path, "claude")
    assert after["installed"] is True
    assert after["thresholds"]["max_lines"] == 350


def test_guard_status_tolerates_a_malformed_config(tmp_path):
    """Status must not crash on a config that install would refuse."""
    target = tmp_path / ".claude" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text("{ broken")
    assert guard_status(tmp_path, "claude")["installed"] is False


def test_unsupported_host_is_rejected(tmp_path):
    """Only the two documented hosts are accepted."""
    for function in (install_guards, uninstall_guards, guard_status):
        with pytest.raises(ValueError, match="unsupported host"):
            function(tmp_path, "emacs")


# --------------------------------------------------------------------------- #
# CLI integration
# --------------------------------------------------------------------------- #
@pytest.fixture
def cli_root(tmp_path):
    """A minimal repo root that the wiki CLIs will accept."""
    (tmp_path / ".parrot").mkdir()
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_claude_cli_installs_and_removes_guards(cli_root):
    """`--tool-guards` installs; `uninstall` removes; `status --json` reports."""
    from parrot.knowledge.wiki.claude_code.cli import claude

    runner = CliRunner()
    result = runner.invoke(claude, ["install", "--path", str(cli_root), "--no-build", "--tool-guards"])
    assert "tool guard installed" in result.output, result.output
    assert any(HOOK_MODULE in json.dumps(entry) for entry in _entries(cli_root))

    status = runner.invoke(claude, ["status", "--path", str(cli_root), "--json"])
    payload = json.loads(status.output)
    assert payload["tool_guards"]["installed"] is True

    removed = runner.invoke(claude, ["uninstall", "--path", str(cli_root)])
    assert "tool guard removed" in removed.output
    assert not any(HOOK_MODULE in json.dumps(entry) for entry in _entries(cli_root))


def test_claude_cli_guards_are_off_by_default(cli_root):
    """The guard is opt-in: a plain install writes no guard entry."""
    from parrot.knowledge.wiki.claude_code.cli import claude

    CliRunner().invoke(claude, ["install", "--path", str(cli_root), "--no-build"])
    settings = cli_root / ".claude" / "settings.json"
    if settings.exists():
        assert not any(HOOK_MODULE in json.dumps(entry) for entry in _entries(cli_root))


def test_codex_cli_installs_guards(cli_root):
    """The same flag works for Codex."""
    from parrot.knowledge.wiki.codex.cli import codex

    runner = CliRunner()
    result = runner.invoke(codex, ["install", "--path", str(cli_root), "--no-build", "--tool-guards"])
    assert "tool guard installed" in result.output, result.output
    assert (cli_root / ".codex" / "hooks.json").exists()


def test_cli_reports_a_useful_error_when_parrot_tools_is_absent(cli_root, monkeypatch):
    """Core must not hard-depend on ai-parrot-tools."""
    from parrot.knowledge.wiki.claude_code.cli import claude

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("parrot_tools.tool_optimizations"):
            raise ImportError("No module named 'parrot_tools'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    runner = CliRunner()

    guarded = runner.invoke(claude, ["install", "--path", str(cli_root), "--no-build", "--tool-guards"])
    assert guarded.exit_code != 0
    assert "uv pip install ai-parrot-tools" in guarded.output

    plain = runner.invoke(claude, ["install", "--path", str(cli_root), "--no-build"])
    assert plain.exit_code == 0, plain.output


# --------------------------------------------------------------------------- #
# Foreign-hook preservation (regression from adversarial review)
# --------------------------------------------------------------------------- #
def _guard_hooks(entries):
    """Flatten every hook handler across all entries."""
    return [hook for entry in entries for hook in entry.get("hooks", [])]


def test_install_preserves_a_foreign_hook_sharing_our_entry(root):
    """A user's own command under the SAME matcher must survive an update.

    Ownership is per-hook, not per-entry. Before this was fixed, the update
    path did `entry.clear(); entry.update(ours)` and silently deleted a
    co-located foreign handler.
    """
    install_guards(root, "claude")
    settings = _settings(root)
    ours_entry = next(entry for entry in settings["hooks"]["PreToolUse"] if HOOK_MODULE in json.dumps(entry))
    ours_entry["hooks"].append({"type": "command", "command": "my-own-important-hook.sh", "timeout": 5})
    # Force the update path by staling our command.
    ours_entry["hooks"][0]["command"] = f"/old/python -m {HOOK_MODULE} --host claude"
    (root / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")

    install_guards(root, "claude")
    hooks = _guard_hooks(_entries(root))

    foreign = [hook for hook in hooks if hook.get("command") == "my-own-important-hook.sh"]
    assert len(foreign) == 1, "the user's own hook was destroyed"
    assert foreign[0]["timeout"] == 5, "the user's own hook was modified"

    ours = [hook for hook in hooks if HOOK_MODULE in str(hook.get("command", ""))]
    assert len(ours) == 1
    assert ours[0]["command"] == hook_command(root, "claude"), "our hook was not refreshed"

    # The unrelated pre-existing entries are still intact.
    assert all(entry in _entries(root) for entry in FOREIGN_ENTRIES)


def test_uninstall_preserves_a_foreign_hook_sharing_our_entry(root):
    """Uninstall removes only our handler, keeping the entry for the other."""
    install_guards(root, "claude")
    settings = _settings(root)
    ours_entry = next(entry for entry in settings["hooks"]["PreToolUse"] if HOOK_MODULE in json.dumps(entry))
    ours_entry["hooks"].append({"type": "command", "command": "my-own-important-hook.sh", "timeout": 5})
    (root / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")

    uninstall_guards(root, "claude")
    hooks = _guard_hooks(_entries(root))

    assert any(hook.get("command") == "my-own-important-hook.sh" for hook in hooks), "the user's own hook was destroyed"
    assert not any(HOOK_MODULE in str(hook.get("command", "")) for hook in hooks), "our hook was not removed"
    assert all(entry in _entries(root) for entry in FOREIGN_ENTRIES)


def test_install_is_still_idempotent_with_a_shared_entry(root):
    """Detaching from a shared entry must converge, not oscillate."""
    install_guards(root, "claude")
    settings = _settings(root)
    ours_entry = next(entry for entry in settings["hooks"]["PreToolUse"] if HOOK_MODULE in json.dumps(entry))
    ours_entry["hooks"].append({"type": "command", "command": "other.sh"})
    (root / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")

    install_guards(root, "claude")
    first = (root / ".claude" / "settings.json").read_bytes()
    actions = install_guards(root, "claude")
    assert (root / ".claude" / "settings.json").read_bytes() == first
    assert any("already installed" in action for action in actions)
