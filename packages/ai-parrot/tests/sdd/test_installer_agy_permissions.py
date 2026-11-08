"""Brief agy-permission-hook, task 2 — ``parrot sdd install --host google`` registers the agy hook and rules.

agy auto-approves only through ``permissions.allow`` rules in the user's settings, so the google host install
writes the named hook into ``.agents/hooks.json`` and merges the managed rules into every agy ``settings.json``.
Ownership lives next to each settings file (``parrot-sdd-rules.json``: rules parrot added + repositories using
them), so uninstall never removes a user's own rule nor a rule another repository still needs. Every test runs
against a fake ``HOME``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.sdd.installer import (
    AGY_HOOK_LINE,
    AGY_HOOK_NAME,
    AGY_OWNERSHIP_NAME,
    agy_hook_command,
    agy_settings_paths,
    install_sdd_integration,
    sdd_status,
    uninstall_sdd_integration,
)
from parrot.sdd.scripts.agy_permissions import SDD_ALLOW_RULES

HOOKS = ".agents/hooks.json"
AGY_DIR = ".gemini/antigravity-cli"
SETTINGS = f"{AGY_DIR}/settings.json"
OWNERS = f"{AGY_DIR}/{AGY_OWNERSHIP_NAME}"
SNAP_SETTINGS = "snap/antigravity-cli/common/.gemini/antigravity-cli/settings.json"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake HOME where agy has run once (its directory exists, no settings.json yet)."""
    path = tmp_path / "home"
    (path / AGY_DIR).mkdir(parents=True)
    monkeypatch.setenv("HOME", str(path))
    return path


def _init(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _init(tmp_path / "repo")


def _install(repo: Path, **kwargs: object) -> list[str]:
    kwargs.setdefault("sdd_coder", False)
    kwargs.setdefault("portable", True)
    return install_sdd_integration(repo, ("google",), **kwargs)  # type: ignore[arg-type]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _allow(path: Path) -> list[str]:
    return _read(path)["permissions"]["allow"]


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_install_registers_hook_rules_and_ownership(repo: Path, home: Path) -> None:
    actions = _install(repo)
    (entry,) = _read(repo / HOOKS)[AGY_HOOK_NAME]["PreToolUse"]
    assert entry["matcher"] == "run_command"
    assert entry["hooks"] == [{"type": "command", "command": AGY_HOOK_LINE, "timeout": 10}]
    assert _allow(home / SETTINGS) == list(SDD_ALLOW_RULES)
    assert _read(home / OWNERS) == {"rules": sorted(SDD_ALLOW_RULES), "repos": [str(repo.resolve())]}
    assert any("agy permission hook registered (bare)" in a for a in actions)
    assert any(f"{len(SDD_ALLOW_RULES)} agy rule(s) added" in a for a in actions)


def test_install_is_idempotent(repo: Path, home: Path) -> None:
    _install(repo)
    paths = (repo / HOOKS, home / SETTINGS, home / OWNERS)
    before = [p.read_bytes() for p in paths]
    actions = _install(repo)
    assert [p.read_bytes() for p in paths] == before
    assert any("agy permission hook already registered" in a for a in actions)
    assert any("agy rules present" in a for a in actions)


def test_foreign_hooks_and_user_rules_survive(repo: Path, home: Path) -> None:
    _write(repo / HOOKS, {"lint": {"PostToolUse": [{"matcher": "run_command", "hooks": [{"command": "x"}]}]}})
    original = {
        "model": "m",
        "colorScheme": "noche ñ",
        "permissions": {"allow": ["command(npm test)", "command(find)"]},
    }
    _write(home / SETTINGS, original)
    _install(repo)
    assert set(_read(repo / HOOKS)) == {"lint", AGY_HOOK_NAME}
    settings = _read(home / SETTINGS)
    assert settings["model"] == "m"
    assert settings["permissions"]["allow"][:2] == ["command(npm test)", "command(find)"]
    assert settings["permissions"]["allow"].count("command(find)") == 1
    assert "command(find)" not in _read(home / OWNERS)["rules"]
    assert "noche ñ" in (home / SETTINGS).read_text(encoding="utf-8")

    uninstall_sdd_integration(repo, ("google",))
    assert set(_read(repo / HOOKS)) == {"lint"}
    assert _read(home / SETTINGS) == original
    assert not (home / OWNERS).exists()


def test_uninstall_removes_a_hooks_file_it_alone_used(repo: Path, home: Path) -> None:
    _install(repo)
    uninstall_sdd_integration(repo, ("google",))
    assert not (repo / HOOKS).exists()
    assert _read(home / SETTINGS) == {}
    assert not (home / OWNERS).exists()


def test_rules_stay_while_another_repository_uses_them(tmp_path: Path, home: Path) -> None:
    first, second = _init(tmp_path / "a"), _init(tmp_path / "b")
    _install(first)
    _install(second)
    assert _read(home / OWNERS)["repos"] == [str(first.resolve()), str(second.resolve())]
    actions = uninstall_sdd_integration(first, ("google",))
    assert any("agy rules kept (still used by 1 other" in a for a in actions)
    assert _allow(home / SETTINGS) == list(SDD_ALLOW_RULES)
    uninstall_sdd_integration(second, ("google",))
    assert _read(home / SETTINGS) == {}


def test_ownership_alone_still_triggers_cleanup(repo: Path, home: Path) -> None:
    """A receipt without the hook marker (hand-edited, lost) must not strand the global rules."""
    _install(repo)
    receipt_path = repo / "sdd" / ".sdd-installed.json"
    receipt = _read(receipt_path)
    receipt["settings_hooks"] = []
    _write(receipt_path, receipt)
    uninstall_sdd_integration(repo, ("google",))
    assert _read(home / SETTINGS) == {}


def test_hook_failure_skips_the_rules(repo: Path, home: Path) -> None:
    (repo / ".agents").mkdir()
    (repo / HOOKS).write_text("{not json", encoding="utf-8")
    actions = _install(repo)
    assert (repo / HOOKS).read_text(encoding="utf-8") == "{not json"
    assert not (home / SETTINGS).exists()
    assert any(a.startswith("warning: .agents/hooks.json") for a in actions)
    assert any("agy rules skipped" in a for a in actions)


def test_malformed_settings_are_never_rewritten(repo: Path, home: Path) -> None:
    (home / SETTINGS).write_text("[1, 2]", encoding="utf-8")
    actions = _install(repo)
    assert (home / SETTINGS).read_text(encoding="utf-8") == "[1, 2]"
    assert any(a.startswith("warning: ~/.gemini/antigravity-cli/settings.json") for a in actions)
    assert (repo / HOOKS).is_file()


def test_malformed_hooks_file_is_kept_and_rules_still_released(repo: Path, home: Path) -> None:
    _install(repo)
    (repo / HOOKS).write_text("{broken", encoding="utf-8")
    actions = uninstall_sdd_integration(repo, ("google",))
    assert any("agy hook kept" in a for a in actions)
    assert (repo / HOOKS).read_text(encoding="utf-8") == "{broken"
    assert _read(home / SETTINGS) == {}  # the safe direction: no broad rules left behind


def test_symlinked_hooks_file_outside_the_repo_is_refused(repo: Path, home: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (repo / ".agents").mkdir()
    (repo / HOOKS).symlink_to(outside)
    actions = _install(repo)
    assert outside.read_text(encoding="utf-8") == "{}"
    assert any("resolves outside the repository" in a for a in actions)
    assert not (home / SETTINGS).exists()


def test_both_settings_files_are_updated(repo: Path, home: Path) -> None:
    _write(home / SETTINGS, {})
    _write(home / SNAP_SETTINGS, {"permissions": {"allow": ["command(ls)"]}})
    assert agy_settings_paths() == [home / SETTINGS, home / SNAP_SETTINGS]
    _install(repo)
    assert _allow(home / SETTINGS) == list(SDD_ALLOW_RULES)
    assert _allow(home / SNAP_SETTINGS)[0] == "command(ls)"
    assert set(SDD_ALLOW_RULES) <= set(_allow(home / SNAP_SETTINGS))
    snap_owners = _read((home / SNAP_SETTINGS).with_name(AGY_OWNERSHIP_NAME))
    assert "command(ls)" not in snap_owners["rules"]
    uninstall_sdd_integration(repo, ("google",))
    assert _read(home / SNAP_SETTINGS) == {"permissions": {"allow": ["command(ls)"]}}


def test_snap_only_settings_is_used_alone(home: Path) -> None:
    _write(home / SNAP_SETTINGS, {})
    assert agy_settings_paths() == [home / SNAP_SETTINGS]


def test_no_agy_installed_creates_nothing_in_home(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bare_home = tmp_path / "bare-home"
    bare_home.mkdir()
    monkeypatch.setenv("HOME", str(bare_home))
    assert agy_settings_paths() == []
    actions = _install(repo)
    assert (repo / HOOKS).is_file()
    assert not any(bare_home.iterdir())
    assert any("agy settings not found" in a for a in actions)


def test_opt_out_and_other_hosts_plan_nothing(repo: Path, home: Path) -> None:
    _install(repo, agy_permissions=False)
    assert not (repo / HOOKS).exists()
    install_sdd_integration(repo, ("claude",), sdd_coder=False, portable=True)
    assert not (repo / HOOKS).exists()
    assert not (home / SETTINGS).exists()


def test_dry_run_writes_nothing(repo: Path, home: Path) -> None:
    plan = _install(repo, dry_run=True)
    assert "plan: agy-permissions .agents/hooks.json (+ rules in ~/.gemini/antigravity-cli/settings.json)" in plan
    assert not (repo / HOOKS).exists()
    assert not any((home / AGY_DIR).iterdir())


def test_baked_form(repo: Path, home: Path) -> None:
    command, form = agy_hook_command(portable=False)
    assert form == "baked"
    assert command.endswith(" sdd hooks agy-permissions --hook") and command != AGY_HOOK_LINE
    _install(repo, portable=False)
    assert sdd_status(repo)["agy_permissions"]["form"] == "baked"


def test_status_reports_hook_and_missing_rules(repo: Path, home: Path) -> None:
    before = sdd_status(repo)["agy_permissions"]
    assert before["form"] is None
    assert before["missing_rules"] == len(SDD_ALLOW_RULES)
    _install(repo)
    after = sdd_status(repo)["agy_permissions"]
    assert after["form"] == "bare"
    assert after["command"] == AGY_HOOK_LINE
    assert after["missing_rules"] == 0
    assert after["settings"] == [{"path": str(home / SETTINGS), "missing_rules": 0}]


def test_status_ignores_an_inactive_hook(repo: Path, home: Path) -> None:
    _install(repo)
    hooks = _read(repo / HOOKS)
    hooks[AGY_HOOK_NAME]["PreToolUse"][0]["matcher"] = "wrong_tool"
    _write(repo / HOOKS, hooks)
    assert sdd_status(repo)["agy_permissions"]["form"] is None


def test_cli_flag_skips_agy_permissions(repo: Path, home: Path) -> None:
    from parrot.cli import cli

    args = ["sdd", "install", "--path", str(repo), "--host", "google", "--no-sdd-coder", "--portable"]
    result = CliRunner().invoke(cli, [*args, "--no-agy-permissions"])
    assert result.exit_code == 0, result.output
    assert not (repo / HOOKS).exists()
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output
    assert (repo / HOOKS).is_file()
